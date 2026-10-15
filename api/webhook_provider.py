"""AURA AI — provedor de webhooks de saída assinados (etapa 7, fase 5).

Cada evento vira um POST JSON para a URL https cadastrada, assinado com HMAC-SHA256:

    X-Aura-Event:     tipo do evento (ex.: meeting.analyzed)
    X-Aura-Delivery:  id do evento (o MESMO em todas as tentativas: quem recebe deduplica por ele)
    X-Aura-Timestamp: segundos desde 1970 no envio (rejeite mensagens com mais de 5 minutos)
    X-Aura-Signature: v1=<hex> , com hex = HMAC_SHA256(segredo, "<timestamp>.<corpo>")

Proteções contra o servidor ser usado para atacar a rede interna (SSRF):
  * só https; sem credenciais na URL; sem "localhost", "*.local" ou "*.internal";
  * o nome é resolvido NA HORA do envio e o envio é recusado se QUALQUER endereço não for público
    (loopback, rede privada, link-local/metadados da nuvem, multicast etc.);
  * a conexão vai direto ao IP validado (sem segunda resolução: não há "DNS rebinding"), com o certificado conferido
    contra o nome original;
  * redirecionamentos NÃO são seguidos; tempo limite curto; a resposta do destino não é guardada nem repassada.
"""
from __future__ import annotations

import hashlib
import hmac
import http.client
import ipaddress
import json
import socket
import ssl
import time
from urllib.parse import urlsplit

from integrations import DeliveryResult

TIMEOUT = 8
MAX_BODY = 64 * 1024
BLOCKED_SUFFIXES = (".local", ".localhost", ".internal", ".lan", ".home", ".corp", ".intranet")
USER_AGENT = "AURA-Webhook/1"


class BlockedDestination(Exception):
    pass


def sign(secret: str, timestamp: int, body: bytes) -> str:
    mac = hmac.new(secret.encode("utf-8"), f"{timestamp}.".encode("ascii") + body, hashlib.sha256).hexdigest()
    return "v1=" + mac


def verify(secret: str, timestamp: int, body: bytes, signature: str, tolerance: int = 300, now: float | None = None) -> bool:
    """O que quem recebe deve fazer (útil para documentação e testes)."""
    if abs((now if now is not None else time.time()) - timestamp) > tolerance:
        return False
    return hmac.compare_digest(sign(secret, timestamp, body), signature or "")


def _public_ip(value: str) -> bool:
    try:
        ip = ipaddress.ip_address(value.split("%")[0])
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return ip.is_global and not ip.is_multicast


def parse_url(url: str) -> tuple[str, int, str]:
    """Valida a URL cadastrada e devolve (host, porta, caminho). Levanta ValueError com mensagem para a pessoa."""
    if not isinstance(url, str) or len(url) > 2000 or any(c.isspace() for c in url):
        raise ValueError("Informe uma URL https válida.")
    parts = urlsplit(url)
    if parts.scheme != "https" or not parts.hostname:
        raise ValueError("A URL precisa começar com https://")
    if parts.username or parts.password:
        raise ValueError("A URL não pode ter usuário e senha. Use o segredo de assinatura.")
    if parts.fragment:
        raise ValueError("A URL não pode ter fragmento (#).")
    host = parts.hostname.lower().rstrip(".")
    try:
        port = parts.port or 443
    except ValueError as exc:
        raise ValueError("Porta inválida.") from exc
    if host == "localhost" or host.endswith(BLOCKED_SUFFIXES) or "." not in host and ":" not in host:
        raise ValueError("Esse endereço não é público. Informe o endereço de um serviço na internet.")
    try:
        ipaddress.ip_address(host)
        if not _public_ip(host):
            raise ValueError("Esse endereço não é público. Informe o endereço de um serviço na internet.")
    except ValueError as exc:
        if "público" in str(exc):
            raise
    path = parts.path or "/"
    if parts.query:
        path += "?" + parts.query
    return host, port, path


class _PinnedHTTPS(http.client.HTTPSConnection):
    """HTTPS que conecta num IP já validado, mas verifica o certificado e envia o Host do nome original."""

    def __init__(self, host: str, ip: str, port: int, timeout: float, context: ssl.SSLContext):
        super().__init__(host, port, timeout=timeout, context=context)
        self._ip = ip

    def connect(self):
        sock = socket.create_connection((self._ip, self.port), self.timeout)
        self.sock = self._context.wrap_socket(sock, server_hostname=self.host)


def _resolve(host: str, port: int) -> list[str]:
    infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    return list(dict.fromkeys(i[4][0] for i in infos))


class WebhookProvider:
    name = "webhook"

    def __init__(self, resolver=None, ssl_context: ssl.SSLContext | None = None, allow_private: bool = False):
        # `resolver`, `ssl_context` e `allow_private` existem para os testes; em produção ficam nos padrões seguros.
        self._resolve = resolver or _resolve
        self._ctx = ssl_context
        self._allow_private = allow_private

    # --- cadastro -----------------------------------------------------------------------------------
    def validate_config(self, config: dict) -> dict:
        host, port, path = parse_url((config or {}).get("url"))
        url = f"https://{host}{'' if port == 443 else ':' + str(port)}{path}"
        return {"url": url}

    # --- envio --------------------------------------------------------------------------------------
    def _context(self) -> ssl.SSLContext:
        if self._ctx is not None:
            return self._ctx
        ctx = ssl.create_default_context()
        ctx.minimum_version = ssl.TLSVersion.TLSv1_2
        return ctx

    def _pick_ip(self, host: str, port: int) -> str:
        addresses = self._resolve(host, port)
        if not addresses:
            raise BlockedDestination("sem endereço")
        if not self._allow_private and not all(_public_ip(a) for a in addresses):
            raise BlockedDestination("endereço não público")
        return addresses[0]

    def deliver(self, config: dict, secret: str, event: dict) -> DeliveryResult:
        try:
            host, port, path = parse_url((config or {}).get("url"))
        except ValueError:
            return DeliveryResult(False, None, "URL inválida.", retryable=False)
        body = json.dumps({"id": event["id"], "type": event["type"], "created_at": event.get("created_at"),
                           "entity": {"type": event.get("entity_type"), "id": event.get("entity_id")}, "data": event.get("data") or {}},
                          ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        if len(body) > MAX_BODY:
            return DeliveryResult(False, None, "Evento grande demais.", retryable=False)
        ts = int(time.time())
        headers = {"Content-Type": "application/json; charset=utf-8", "User-Agent": USER_AGENT, "X-Aura-Event": event["type"],
                   "X-Aura-Delivery": str(event["id"]), "X-Aura-Timestamp": str(ts), "X-Aura-Signature": sign(secret, ts, body),
                   "Accept": "*/*"}
        try:
            ip = self._pick_ip(host, port)
        except BlockedDestination:
            return DeliveryResult(False, None, "Destino bloqueado: o endereço não é público.", retryable=False)
        except OSError:
            return DeliveryResult(False, None, "Não foi possível resolver o endereço.", retryable=True)
        conn = _PinnedHTTPS(host, ip, port, TIMEOUT, self._context())
        try:
            conn.request("POST", path, body=body, headers=headers)
            response = conn.getresponse()
            response.read(1024)  # a resposta do destino é descartada
            status = response.status
        except ssl.SSLError:
            return DeliveryResult(False, None, "Certificado do destino inválido.", retryable=False)
        except (socket.timeout, TimeoutError):
            return DeliveryResult(False, None, "Tempo esgotado.", retryable=True)
        except (OSError, http.client.HTTPException):
            return DeliveryResult(False, None, "Falha de conexão.", retryable=True)
        finally:
            conn.close()
        if 200 <= status < 300:
            return DeliveryResult(True, status)
        if 300 <= status < 400:
            return DeliveryResult(False, status, f"HTTP {status} (redirecionamentos não são seguidos).", retryable=False)
        retryable = status >= 500 or status in (408, 425, 429)
        return DeliveryResult(False, status, f"HTTP {status}", retryable=retryable)
