"""AURA AI — autenticação, autorização, auditoria e proteção de arquivos estáticos.

Princípios:
  * A identidade vem do JWT do Supabase Auth, verificado no próprio Supabase (nunca confiamos em
    identificadores enviados pelo navegador).
  * Leituras/escritas de reuniões usam o JWT do usuário, então o RLS do banco é a barreira final.
    A chave de serviço só é usada para o que o usuário não pode fazer sozinho (criar organização,
    gravar auditoria, assinar URLs de storage).
  * AURA_AUTH_REQUIRED liga a exigência de login. Desligado, o comportamento anterior é mantido
    (útil durante a migração); o /api/health informa o estado.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import HTTPException, Request
from fastapi.staticfiles import StaticFiles

log = logging.getLogger("aura.security")

# Espelho de aura_private.role_permissions (supabase/migrations/...identidade_organizacoes.sql).
# Usado só para decidir o que mostrar (ex.: dados financeiros); o RLS continua sendo a barreira.
ROLE_PERMISSIONS: dict[str, frozenset[str]] = {
    "admin": frozenset({
        "org.settings", "members.manage", "integrations.manage", "meetings.read_all",
        "meetings.write", "meetings.manage", "meetings.delete", "finance.read", "export.data",
        "actions.manage", "clients.read", "clients.write", "clients.manage", "audit.read",
    }),
    "manager": frozenset({
        "meetings.read_all", "meetings.write", "meetings.manage", "finance.read", "export.data",
        "actions.manage", "clients.read", "clients.write", "clients.manage",
    }),
    "member": frozenset({"meetings.write", "clients.read", "clients.write"}),
}

UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)
AUDIO_EXTENSIONS = (".mp3", ".wav", ".m4a", ".mp4", ".webm", ".ogg")


def auth_required() -> bool:
    return os.getenv("AURA_AUTH_REQUIRED", "").strip().lower() in ("1", "true", "yes")


def supabase_url() -> str:
    return (os.getenv("SUPABASE_URL") or "").rstrip("/")


def publishable_key() -> str:
    return os.getenv("SUPABASE_PUBLISHABLE_KEY") or os.getenv("SUPABASE_ANON_KEY") or ""


def service_key() -> str:
    return os.getenv("SUPABASE_SECRET_KEY") or os.getenv("SUPABASE_SERVICE_ROLE_KEY") or ""


def allowed_origins() -> list[str]:
    return [o.strip() for o in os.getenv("AURA_ALLOWED_ORIGINS", "").split(",") if o.strip()]


def http_json(method: str, url: str, headers: dict[str, str], payload: Any = None, timeout: int = 15) -> tuple[int, Any]:
    """Único ponto de rede da camada de segurança (os testes substituem esta função)."""
    data = json.dumps(payload, ensure_ascii=False).encode() if payload is not None else None
    req = urllib.request.Request(url, method=method, headers={"Content-Type": "application/json", **headers}, data=data)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            raw = response.read().decode() or "null"
            return response.status, json.loads(raw)
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            return exc.code, json.loads(raw)
        except ValueError:
            return exc.code, {"message": raw[:300]}
    except Exception as exc:  # rede, DNS, timeout
        raise RuntimeError(f"Falha de rede: {type(exc).__name__}") from exc


@dataclass(frozen=True)
class AuthUser:
    id: str
    email: str | None
    token: str
    email_confirmed: bool = False


_token_cache: dict[str, tuple[float, AuthUser]] = {}
_TOKEN_TTL = 30.0


def verify_token(token: str) -> AuthUser:
    digest = hashlib.sha256(token.encode()).hexdigest()
    hit = _token_cache.get(digest)
    now = time.monotonic()
    if hit and hit[0] > now:
        return hit[1]
    try:
        status, body = http_json("GET", f"{supabase_url()}/auth/v1/user",
                                 {"apikey": publishable_key(), "Authorization": f"Bearer {token}"})
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail="Serviço de autenticação indisponível.") from exc
    if status != 200 or not isinstance(body, dict) or not UUID_RE.match(str(body.get("id", ""))):
        raise HTTPException(status_code=401, detail="Sessão inválida ou expirada.")
    confirmed = bool(body.get("email_confirmed_at") or body.get("confirmed_at"))
    user = AuthUser(id=body["id"], email=body.get("email"), token=token, email_confirmed=confirmed)
    if len(_token_cache) > 2000:
        _token_cache.clear()
    _token_cache[digest] = (now + _TOKEN_TTL, user)
    return user


def current_user(request: Request) -> AuthUser | None:
    """Dependência FastAPI. Retorna None apenas no modo legado (AURA_AUTH_REQUIRED desligado)."""
    if not auth_required():
        return None
    scheme, _, token = request.headers.get("authorization", "").partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise HTTPException(status_code=401, detail="Autenticação necessária.")
    if not supabase_url() or not publishable_key():
        raise HTTPException(status_code=503, detail="Autenticação não configurada no servidor.")
    return verify_token(token.strip())


def rest_headers(user: AuthUser | None, prefer: str = "return=representation") -> dict[str, str]:
    """Com usuário: JWT dele + chave pública (RLS vale). Sem usuário: chave de serviço."""
    if user is not None:
        return {"apikey": publishable_key(), "Authorization": f"Bearer {user.token}", "Prefer": prefer}
    key = service_key()
    return {"apikey": key, "Authorization": f"Bearer {key}", "Prefer": prefer}


class SupabaseError(RuntimeError):
    """Erro do PostgREST com o status e o corpo preservados (o texto da mensagem não muda)."""

    def __init__(self, status: int, body: Any = None):
        super().__init__(f"Supabase error: HTTP {status}")
        self.status = status
        self.body = body if isinstance(body, dict) else {}

    @property
    def db_message(self) -> str:
        return str(self.body.get("message") or "")

    @property
    def db_code(self) -> str:
        return str(self.body.get("code") or "")


def service_rest(method: str, path: str, payload: Any = None) -> Any:
    """Chamada PostgREST com a chave de serviço (somente para operações do backend)."""
    if not supabase_url() or not service_key():
        raise RuntimeError("Supabase server credentials não configuradas.")
    status, body = http_json(method, f"{supabase_url()}/rest/v1/{path}", rest_headers(None), payload)
    if status >= 400:
        raise SupabaseError(status, body)
    return body


def user_rest(user: AuthUser, method: str, path: str, payload: Any = None) -> Any:
    status, body = http_json(method, f"{supabase_url()}/rest/v1/{path}", rest_headers(user), payload)
    if status >= 400:
        raise SupabaseError(status, body)
    return body


# ---------------------------------------------------------------------------
# Permissões
# ---------------------------------------------------------------------------
def load_access(user: AuthUser) -> dict[str, frozenset[str]]:
    """Permissões efetivas do usuário por organização (papel + ajustes 'allow'/'deny')."""
    # O RLS deixa cada membro ver TODOS os vínculos da própria organização; por isso o filtro
    # por user_id é obrigatório (sem ele, o papel de outro membro poderia ser atribuído ao usuário).
    memberships = user_rest(user, "GET", f"memberships?select=org_id,role&user_id=eq.{user.id}") or []
    overrides = user_rest(user, "GET", f"membership_permissions?select=org_id,permission,effect&user_id=eq.{user.id}") or []
    access: dict[str, set[str]] = {}
    for m in memberships:
        access[m["org_id"]] = set(ROLE_PERMISSIONS.get(m.get("role"), frozenset()))
    for o in overrides:
        perms = access.get(o["org_id"])
        if perms is None:
            continue
        (perms.add if o.get("effect") == "allow" else perms.discard)(o["permission"])
    return {k: frozenset(v) for k, v in access.items()}


def require_org_permission(user: AuthUser | None, org_id: str | None, permission: str) -> None:
    """Conta pessoal (org_id nulo) é sempre permitida ao próprio dono. Organização exige permissão."""
    if user is None or not org_id:
        return
    if not UUID_RE.match(org_id):
        raise HTTPException(status_code=400, detail="Identificador de organização inválido.")
    try:
        access = load_access(user)
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail="Não foi possível verificar suas permissões.") from exc
    if permission not in access.get(org_id, frozenset()):
        raise HTTPException(status_code=403, detail="Você não tem permissão para esta operação nesta organização.")


def redact_meetings(rows: list[dict], user: AuthUser | None) -> list[dict]:
    """Remove dados financeiros de reuniões de terceiros quando falta a permissão finance.read."""
    if user is None or not rows:
        return rows
    try:
        access = load_access(user)
    except RuntimeError:
        access = {}
    out = []
    for row in rows:
        if row.get("owner_id") == user.id or "finance.read" in access.get(row.get("org_id") or "", frozenset()):
            out.append(row)
        else:
            out.append({**row, "financial_data": []})
    return out


# ---------------------------------------------------------------------------
# Auditoria e limite de uso
# ---------------------------------------------------------------------------
def audit(actor: AuthUser | None, action: str, org_id: str | None = None, entity_type: str | None = None,
          entity_id: str | None = None, metadata: dict | None = None) -> None:
    """Registra uma ação sem conteúdo de reunião. Falhas são registradas em log, nunca expostas."""
    if actor is None:
        return
    try:
        service_rest("POST", "audit_log", {
            "actor_id": actor.id, "org_id": org_id, "action": action,
            "entity_type": entity_type, "entity_id": entity_id, "metadata": metadata or {},
        })
    except Exception as exc:
        log.warning("auditoria não gravada (%s): %s", action, exc)


def enforce_usage_limit(user: AuthUser | None) -> None:
    """Limita análises (custo de IA) por usuário/hora. Falha de verificação bloqueia (fail closed)."""
    if user is None:
        return
    limit = int(os.getenv("AURA_MAX_ANALYSES_PER_HOUR", "30") or "30")
    since = (datetime.now(timezone.utc) - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        rows = service_rest("GET", f"audit_log?select=id&actor_id=eq.{user.id}&action=like.analysis.*&at=gte.{since}&limit={limit + 1}") or []
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail="Não foi possível verificar o limite de uso. Tente novamente.") from exc
    if len(rows) >= limit:
        raise HTTPException(status_code=429, detail="Limite de análises por hora atingido. Tente novamente mais tarde.")


# ---------------------------------------------------------------------------
# Caminhos de áudio no bucket privado
# ---------------------------------------------------------------------------
AUDIO_PATH_RE = re.compile(r"^(users|orgs)/([0-9a-f-]{36})/[0-9a-f]{32}(\.[a-z0-9]{2,5})$")


def audio_suffix(file_name: str) -> str:
    suffix = os.path.splitext(file_name or "")[1].lower()
    return suffix if suffix in AUDIO_EXTENSIONS else ".mp3"


def audio_path_for(user: AuthUser, org_id: str | None, token_hex: str, suffix: str) -> str:
    scope = f"orgs/{org_id}" if org_id else f"users/{user.id}"
    return f"{scope}/{token_hex}{suffix}"


def authorize_audio_path(user: AuthUser, path: str) -> str | None:
    """Confirma que o caminho pertence ao usuário (ou a uma organização dele). Retorna org_id ou None."""
    m = AUDIO_PATH_RE.match(path or "")
    if not m:
        raise HTTPException(status_code=400, detail="Caminho de áudio inválido.")
    kind, owner = m.group(1), m.group(2)
    if kind == "users":
        if owner != user.id:
            raise HTTPException(status_code=403, detail="Este áudio não pertence à sua conta.")
        return None
    require_org_permission(user, owner, "meetings.write")
    return owner


# ---------------------------------------------------------------------------
# Arquivos estáticos: apenas o front-end público, nunca código, git ou configuração
# ---------------------------------------------------------------------------
PUBLIC_EXTENSIONS = {".html", ".css", ".js", ".svg", ".jpeg", ".jpg", ".png", ".ico", ".webp", ".woff2"}


class PublicFiles(StaticFiles):
    async def get_response(self, path: str, scope):  # type: ignore[override]
        clean = path.strip("/")
        if clean and clean != ".":
            name = clean.lower()
            if "/" in clean or name.startswith(".") or os.path.splitext(name)[1] not in PUBLIC_EXTENSIONS:
                raise HTTPException(status_code=404)
        return await super().get_response(path, scope)
