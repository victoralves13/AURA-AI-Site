"""AURA AI — integrações: cadastro, segredos cifrados, registro de eventos e entrega idempotente (etapa 7, fase 4).

Arquitetura:
  * Um EVENTO ("reunião analisada", "ação concluída"...) é registrado uma vez (`emit_event`) e, para cada integração ativa do
    mesmo espaço que assina esse tipo, nasce UMA entrega (UNIQUE integração+evento no banco: repetir não duplica).
  * `dispatch_due` entrega o que está vencido: reserva a entrega com um UPDATE condicional (duas execuções simultâneas nunca
    entregam a mesma), chama o PROVEDOR, e agenda nova tentativa com espera crescente. Passadas as tentativas, a entrega vira
    "dead"; muitas falhas seguidas desligam a integração. Um provedor com erro nunca derruba quem emitiu o evento.
  * PROVEDORES são plugáveis (`register_provider`). Aqui não há nenhum de verdade: o webhook assinado chega na fase 7.5 e os
    testes usam um provedor falso.
  * Só quem tem `integrations.manage` (ou o dono, na conta pessoal) vê e gerencia. O segredo é cifrado (integration_crypto)
    e mostrado UMA vez, ao criar ou girar. Nada de transcrição vai nos eventos.
  * O banco (RLS) é a autoridade para ler; as escritas passam pelo backend (chave de serviço) depois de conferir a permissão.
"""
from __future__ import annotations

import hmac
import logging
import os
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Protocol

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel

import integration_crypto as ic
import security as sec

log = logging.getLogger("aura.integrations")
router = APIRouter()

PERMISSION = "integrations.manage"
EVENT_TYPES = ("meeting.analyzed", "action.completed", "live.consolidated")  # assináveis; 'integration.test' é só do botão de teste
ALL_EVENT_TYPES = EVENT_TYPES + ("integration.test",)
MAX_ATTEMPTS = 6
BACKOFF_MINUTES = (1, 5, 30, 120, 360)  # espera depois da 1ª, 2ª, ... falha
LEASE_MINUTES = 5  # reserva de uma entrega em andamento (se a função cair, ela volta a valer depois)
DISABLE_AFTER = 10  # falhas seguidas que desligam a integração
SAFE_COLUMNS = ("id,org_id,provider,name,status,config,events,secret_hint,consecutive_failures,last_success_at,last_failure_at,"
                "disabled_reason,created_at,updated_at")
ERRORS = {
    "too_many_integrations": (409, "Você atingiu o limite de integrações deste espaço."),
    "integration_invalid_url": (400, "Informe uma URL https válida."),
    "integration_invalid_event": (400, "Tipo de evento inválido."),
    "integration_invalid_provider": (400, "Provedor inválido."),
}
GENERIC = "Não foi possível concluir a operação com a integração. Tente novamente."


# ---------------------------------------------------------------------------
# Provedores
# ---------------------------------------------------------------------------
@dataclass
class DeliveryResult:
    ok: bool
    status_code: int | None = None
    error: str | None = None  # texto curto e sem dados sensíveis
    retryable: bool = True


class Provider(Protocol):
    name: str

    def validate_config(self, config: dict) -> dict:
        """Confere/limpa a configuração (sem o segredo). Levanta ValueError com uma mensagem para a pessoa."""

    def deliver(self, config: dict, secret: str, event: dict) -> DeliveryResult:
        """Entrega o evento. `event` = {id, type, entity_type, entity_id, data, created_at}."""


_PROVIDERS: dict[str, Provider] = {}


def register_provider(provider: Provider) -> None:
    _PROVIDERS[provider.name] = provider


def unregister_provider(name: str) -> None:
    _PROVIDERS.pop(name, None)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# Acesso ao banco
# ---------------------------------------------------------------------------
def _db(call):
    try:
        return call()
    except sec.SupabaseError as exc:
        if exc.db_message in ERRORS:
            status, detail = ERRORS[exc.db_message]
            raise HTTPException(status_code=status, detail=detail) from exc
        if exc.db_code in ("23514", "22P02"):
            raise HTTPException(status_code=400, detail="Dados da integração inválidos.") from exc
        if exc.status in (401, 403):
            raise HTTPException(status_code=403, detail="Você não tem permissão para gerenciar integrações aqui.") from exc
        raise HTTPException(status_code=502, detail=GENERIC) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=GENERIC) from exc


def _need_user(user):
    if user is None:
        raise HTTPException(status_code=401, detail="Autenticação necessária.")
    return user


def _uuid(value, what: str) -> str:
    if not isinstance(value, str) or not sec.UUID_RE.match(value):
        raise HTTPException(status_code=400, detail=f"{what} inválido.")
    return value.lower()


def _org(user: sec.AuthUser, org_id: str | None) -> str | None:
    if not org_id or org_id == "personal":
        return None
    org = _uuid(org_id, "Espaço")
    sec.require_org_permission(user, org, PERMISSION)
    return org


def _space_filter(org: str | None, owner: str) -> str:
    return f"org_id=eq.{org}" if org else f"org_id=is.null&owner_id=eq.{owner}"


def _need_crypto():
    if not ic.configured():
        raise HTTPException(status_code=503, detail="As integrações ainda não estão configuradas neste ambiente.")


def _need_provider(name: str) -> Provider:
    provider = _PROVIDERS.get(name)
    if provider is None:
        raise HTTPException(status_code=501, detail="Este tipo de integração ainda não está disponível.")
    return provider


def _new_secret() -> str:
    return "whsec_" + secrets.token_urlsafe(32)


def _hint(secret: str) -> str:
    return secret[-4:]


def _get_integration(user: sec.AuthUser, integration_id: str) -> dict:
    """Lê com o JWT da pessoa: o RLS só devolve a de quem pode gerenciá-la (as outras viram 404)."""
    rows = _db(lambda: sec.user_rest(user, "GET", f"integrations?select={SAFE_COLUMNS},owner_id&id=eq.{integration_id}&limit=1")) or []
    if not rows:
        raise HTTPException(status_code=404, detail="Integração não encontrada.")
    return rows[0]


def _public(row: dict) -> dict:
    return {k: v for k, v in row.items() if k not in ("secret_ct", "owner_id")}


# ---------------------------------------------------------------------------
# Eventos e entregas (usados pelo restante do backend)
# ---------------------------------------------------------------------------
def emit_event(org_id: str | None, owner_id: str, type_: str, entity_type: str | None = None, entity_id: str | None = None,
               data: dict | None = None, dedupe_key: str | None = None) -> str | None:
    """Registra o evento e cria uma entrega por integração ativa que o assina. Retorna o id do evento, ou None se já existia."""
    if type_ not in EVENT_TYPES:
        raise ValueError("tipo de evento inválido")
    row = {"org_id": org_id, "owner_id": owner_id, "type": type_, "entity_type": entity_type, "entity_id": entity_id,
           "data": data or {}, "dedupe_key": dedupe_key}
    try:
        created = (sec.service_rest("POST", "integration_events", row) or [{}])[0]
    except sec.SupabaseError as exc:
        if exc.db_code == "23505" or exc.status == 409:
            return None  # mesmo evento de origem já registrado: nada a fazer
        raise
    event_id = created.get("id")
    space = f"org_id=eq.{org_id}" if org_id else f"org_id=is.null&owner_id=eq.{owner_id}"
    targets = sec.service_rest("GET", f"integrations?select=id,events&status=eq.active&{space}") or []
    for integ in targets:
        if type_ in (integ.get("events") or []):
            _create_delivery(integ["id"], event_id)
    return event_id


def emit_safe(*args, **kwargs) -> str | None:
    """Como emit_event, mas NUNCA levanta erro: quem emite (análise, ação...) não pode falhar por causa de integração."""
    try:
        return emit_event(*args, **kwargs)
    except Exception as exc:  # noqa: BLE001
        log.warning("Falha ao registrar evento de integração: %s", type(exc).__name__)
        return None


def _create_delivery(integration_id: str, event_id: str) -> str | None:
    try:
        return (sec.service_rest("POST", "integration_deliveries", {"integration_id": integration_id, "event_id": event_id}) or [{}])[0].get("id")
    except sec.SupabaseError as exc:
        if exc.db_code == "23505" or exc.status == 409:
            return None  # já existe: idempotente
        raise


def _finish(delivery: dict, integ: dict, result: DeliveryResult, attempts: int) -> str:
    now = _now()
    if result.ok:
        sec.service_rest("PATCH", f"integration_deliveries?id=eq.{delivery['id']}",
                         {"status": "succeeded", "attempts": attempts, "last_status": result.status_code, "last_error": None, "delivered_at": _iso(now)})
        sec.service_rest("PATCH", f"integrations?id=eq.{integ['id']}", {"consecutive_failures": 0, "last_success_at": _iso(now)})
        return "succeeded"
    dead = (not result.retryable) or attempts >= MAX_ATTEMPTS
    patch = {"status": "dead" if dead else "failed", "attempts": attempts, "last_status": result.status_code,
             "last_error": (result.error or "Falha na entrega.")[:300]}
    if not dead:
        patch["next_attempt_at"] = _iso(now + timedelta(minutes=BACKOFF_MINUTES[min(attempts - 1, len(BACKOFF_MINUTES) - 1)]))
    sec.service_rest("PATCH", f"integration_deliveries?id=eq.{delivery['id']}", patch)
    failures = int(integ.get("consecutive_failures") or 0) + 1
    integ_patch = {"consecutive_failures": failures, "last_failure_at": _iso(now)}
    if failures >= DISABLE_AFTER:
        integ_patch.update({"status": "disabled", "disabled_reason": "Desligada após falhas seguidas. Corrija o destino e reative."})
    sec.service_rest("PATCH", f"integrations?id=eq.{integ['id']}", integ_patch)
    return patch["status"]


def deliver_one(delivery: dict) -> str | None:
    """Entrega uma (reservando antes). Retorna o estado final, ou None se outra execução já a pegou ou ela não pode seguir."""
    attempts_before = int(delivery.get("attempts") or 0)
    lease = _iso(_now() + timedelta(minutes=LEASE_MINUTES))
    claimed = sec.service_rest("PATCH", f"integration_deliveries?id=eq.{delivery['id']}&attempts=eq.{attempts_before}&status=in.(pending,failed)",
                               {"attempts": attempts_before + 1, "next_attempt_at": lease}) or []
    if not claimed:
        return None
    attempts = attempts_before + 1
    integs = sec.service_rest("GET", f"integrations?select=id,provider,status,config,secret_ct,key_version,consecutive_failures&id=eq.{delivery['integration_id']}&limit=1") or []
    events = sec.service_rest("GET", f"integration_events?select=id,type,entity_type,entity_id,data,created_at&id=eq.{delivery['event_id']}&limit=1") or []
    if not integs or not events:
        return None
    integ, event = integs[0], events[0]
    if integ.get("status") != "active":
        # pausada: devolve a reserva sem gastar a tentativa; desligada: encerra
        if integ.get("status") == "disabled":
            sec.service_rest("PATCH", f"integration_deliveries?id=eq.{delivery['id']}", {"status": "dead", "last_error": "Integração desligada."})
            return "dead"
        sec.service_rest("PATCH", f"integration_deliveries?id=eq.{delivery['id']}", {"attempts": attempts_before, "next_attempt_at": _iso(_now() + timedelta(minutes=5))})
        return None
    provider = _PROVIDERS.get(integ["provider"])
    if provider is None:
        return _finish(delivery, integ, DeliveryResult(False, None, "Provedor indisponível.", retryable=True), attempts)
    try:
        secret = ic.decrypt(integ["secret_ct"], integ["id"], int(integ.get("key_version") or 1)) if integ.get("secret_ct") else ""
        result = provider.deliver(integ.get("config") or {}, secret, event)
    except (ic.CryptoError, ic.CryptoUnavailable):
        result = DeliveryResult(False, None, "Segredo indisponível.", retryable=False)
    except Exception as exc:  # noqa: BLE001 — um provedor com defeito não derruba a entrega das outras
        log.warning("Provedor %s falhou: %s", integ["provider"], type(exc).__name__)
        result = DeliveryResult(False, None, f"Erro no provedor ({type(exc).__name__}).", retryable=True)
    return _finish(delivery, integ, result, attempts)


def dispatch_due(limit: int = 25) -> dict:
    now = _iso(_now())
    query = f"integration_deliveries?select=id,integration_id,event_id,attempts&status=in.(pending,failed)&next_attempt_at=lte.{now}&order=next_attempt_at.asc&limit={int(limit)}"
    rows = sec.service_rest("GET", query) or []
    summary = {"found": len(rows), "succeeded": 0, "failed": 0, "dead": 0, "skipped": 0}
    for row in rows:
        try:
            outcome = deliver_one(row)
        except Exception as exc:  # noqa: BLE001
            log.warning("Falha ao processar entrega: %s", type(exc).__name__)
            outcome = None
        summary["skipped" if outcome is None else outcome] += 1
    return summary


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------
class IntegrationCreate(BaseModel):
    org_id: str | None = None
    provider: str
    name: str
    config: dict | None = None
    events: list[str] | None = None


class IntegrationUpdate(BaseModel):
    name: str | None = None
    status: str | None = None
    config: dict | None = None
    events: list[str] | None = None


def _clean_events(events) -> list[str]:
    out = []
    for e in events or []:
        if e not in EVENT_TYPES:
            raise HTTPException(status_code=400, detail="Tipo de evento inválido.")
        if e not in out:
            out.append(e)
    return out


def _clean_name(value) -> str:
    name = " ".join(str(value or "").split())
    if not 1 <= len(name) <= 100:
        raise HTTPException(status_code=400, detail="O nome deve ter entre 1 e 100 caracteres.")
    return name


def _validate_config(provider: Provider, config) -> dict:
    try:
        return provider.validate_config(config or {})
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/api/integrations")
def list_integrations(org_id: str | None = None, user=Depends(sec.current_user)):
    user = _need_user(user)
    org = _org(user, org_id)
    rows = _db(lambda: sec.user_rest(user, "GET", f"integrations?select={SAFE_COLUMNS}&{_space_filter(org, user.id)}&order=created_at.desc&limit=100")) or []
    return {"ok": True, "integrations": rows, "configured": ic.configured(), "providers": sorted(_PROVIDERS), "events": list(EVENT_TYPES)}


@router.post("/api/integrations")
def create_integration(payload: IntegrationCreate, user=Depends(sec.current_user)):
    user = _need_user(user)
    org = _org(user, payload.org_id)
    _need_crypto()
    provider = _need_provider(payload.provider)
    name = _clean_name(payload.name)
    config = _validate_config(provider, payload.config)
    events = _clean_events(payload.events)
    integration_id = str(uuid.uuid4())
    secret = _new_secret()
    secret_ct, version = ic.encrypt(secret, integration_id)
    row = {"id": integration_id, "org_id": org, "owner_id": user.id, "provider": payload.provider, "name": name, "config": config,
           "events": events, "secret_ct": secret_ct, "secret_hint": _hint(secret), "key_version": version}
    created = (_db(lambda: sec.service_rest("POST", "integrations", row)) or [row])[0]
    sec.audit(user, "integration.create", org, "integration", integration_id, {"provider": payload.provider})
    return {"ok": True, "integration": _public(created), "secret": secret}  # o segredo só aparece aqui


@router.patch("/api/integrations/{integration_id}")
def update_integration(integration_id: str, payload: IntegrationUpdate, user=Depends(sec.current_user)):
    user = _need_user(user)
    iid = _uuid(integration_id, "Integração")
    current = _get_integration(user, iid)
    sec.require_org_permission(user, current.get("org_id"), PERMISSION)
    patch: dict = {}
    if payload.name is not None:
        patch["name"] = _clean_name(payload.name)
    if payload.events is not None:
        patch["events"] = _clean_events(payload.events)
    if payload.config is not None:
        patch["config"] = _validate_config(_need_provider(current["provider"]), payload.config)
    if payload.status is not None:
        if payload.status not in ("active", "paused"):
            raise HTTPException(status_code=400, detail="Estado inválido.")
        patch["status"] = payload.status
        if payload.status == "active":
            patch.update({"consecutive_failures": 0, "disabled_reason": None})
    if not patch:
        raise HTTPException(status_code=400, detail="Nada para alterar.")
    rows = _db(lambda: sec.service_rest("PATCH", f"integrations?id=eq.{iid}", patch)) or []
    sec.audit(user, "integration.update", current.get("org_id"), "integration", iid, {"fields": sorted(patch)})
    return {"ok": True, "integration": _public(rows[0] if rows else {**current, **patch})}


@router.post("/api/integrations/{integration_id}/rotate-secret")
def rotate_secret(integration_id: str, user=Depends(sec.current_user)):
    user = _need_user(user)
    iid = _uuid(integration_id, "Integração")
    current = _get_integration(user, iid)
    sec.require_org_permission(user, current.get("org_id"), PERMISSION)
    _need_crypto()
    secret = _new_secret()
    secret_ct, version = ic.encrypt(secret, iid)
    _db(lambda: sec.service_rest("PATCH", f"integrations?id=eq.{iid}", {"secret_ct": secret_ct, "secret_hint": _hint(secret), "key_version": version}))
    sec.audit(user, "integration.rotate_secret", current.get("org_id"), "integration", iid)
    return {"ok": True, "secret": secret}


@router.delete("/api/integrations/{integration_id}")
def delete_integration(integration_id: str, user=Depends(sec.current_user)):
    user = _need_user(user)
    iid = _uuid(integration_id, "Integração")
    current = _get_integration(user, iid)
    sec.require_org_permission(user, current.get("org_id"), PERMISSION)
    _db(lambda: sec.service_rest("DELETE", f"integrations?id=eq.{iid}"))
    sec.audit(user, "integration.delete", current.get("org_id"), "integration", iid, {"provider": current.get("provider")})
    return {"ok": True}


@router.get("/api/integrations/{integration_id}/deliveries")
def list_deliveries(integration_id: str, limit: int = 50, user=Depends(sec.current_user)):
    user = _need_user(user)
    iid = _uuid(integration_id, "Integração")
    _get_integration(user, iid)
    limit = max(1, min(limit, 200))
    rows = _db(lambda: sec.user_rest(user, "GET", f"integration_deliveries?select=id,event_id,status,attempts,next_attempt_at,last_status,last_error,delivered_at,created_at&integration_id=eq.{iid}&order=created_at.desc&limit={limit}")) or []
    return {"ok": True, "deliveries": rows}


@router.post("/api/integrations/{integration_id}/test")
def test_integration(integration_id: str, user=Depends(sec.current_user)):
    """Envia um evento de teste SÓ para esta integração e mostra o resultado na hora."""
    user = _need_user(user)
    iid = _uuid(integration_id, "Integração")
    current = _get_integration(user, iid)
    sec.require_org_permission(user, current.get("org_id"), PERMISSION)
    if current["status"] != "active":
        raise HTTPException(status_code=409, detail="Reative a integração antes de testar.")
    _need_provider(current["provider"])
    event = (_db(lambda: sec.service_rest("POST", "integration_events", {
        "org_id": current.get("org_id"), "owner_id": user.id, "type": "integration.test", "entity_type": "integration", "entity_id": iid,
        "data": {"message": "Evento de teste do AURA AI."}})) or [{}])[0]
    delivery_id = _create_delivery(iid, event["id"])
    pending = (sec.service_rest("GET", f"integration_deliveries?select=id,integration_id,event_id,attempts&id=eq.{delivery_id}&limit=1") or []) if delivery_id else []
    summary = {"outcome": deliver_one(pending[0]) if pending else None}
    rows = _db(lambda: sec.user_rest(user, "GET", f"integration_deliveries?select=status,attempts,last_status,last_error&id=eq.{delivery_id}&limit=1")) or [{}]
    sec.audit(user, "integration.test", current.get("org_id"), "integration", iid)
    return {"ok": True, "delivery": rows[0], "summary": summary}


@router.post("/api/integrations/{integration_id}/deliveries/{delivery_id}/retry")
def retry_delivery(integration_id: str, delivery_id: str, user=Depends(sec.current_user)):
    """Reenvia uma entrega encerrada ('dead') ou com falha: volta ao início da fila, com as tentativas zeradas."""
    user = _need_user(user)
    iid = _uuid(integration_id, "Integração")
    did = _uuid(delivery_id, "Entrega")
    current = _get_integration(user, iid)
    sec.require_org_permission(user, current.get("org_id"), PERMISSION)
    rows = _db(lambda: sec.user_rest(user, "GET", f"integration_deliveries?select=id,status&id=eq.{did}&integration_id=eq.{iid}&limit=1")) or []
    if not rows:
        raise HTTPException(status_code=404, detail="Entrega não encontrada.")
    if rows[0]["status"] == "succeeded":
        raise HTTPException(status_code=409, detail="Esta entrega já foi concluída.")
    if current["status"] == "disabled":
        raise HTTPException(status_code=409, detail="Reative a integração antes de reenviar.")
    _db(lambda: sec.service_rest("PATCH", f"integration_deliveries?id=eq.{did}&status=in.(pending,failed,dead)",
                                 {"status": "pending", "attempts": 0, "next_attempt_at": _iso(_now()), "last_error": None}))
    sec.audit(user, "integration.retry", current.get("org_id"), "integration", iid)
    return {"ok": True}


@router.post("/api/integrations/{integration_id}/flush")
def flush_integration(integration_id: str, user=Depends(sec.current_user)):
    """Entrega agora o que já está vencido DESTA integração (botão 'enviar pendentes'). O agendador faz o mesmo para todas."""
    user = _need_user(user)
    iid = _uuid(integration_id, "Integração")
    current = _get_integration(user, iid)
    sec.require_org_permission(user, current.get("org_id"), PERMISSION)
    due = sec.service_rest("GET", f"integration_deliveries?select=id,integration_id,event_id,attempts&integration_id=eq.{iid}&status=in.(pending,failed)&next_attempt_at=lte.{_iso(_now())}&order=next_attempt_at.asc&limit=10") or []
    summary = {"found": len(due), "succeeded": 0, "failed": 0, "dead": 0, "skipped": 0}
    for row in due:
        outcome = deliver_one(row)
        summary["skipped" if outcome is None else outcome] += 1
    return {"ok": True, **summary}


def retention_days() -> int:
    try:
        return max(1, int(os.getenv("AURA_INTEGRATION_EVENT_RETENTION_DAYS", "30")))
    except ValueError:
        return 30


def prune_old_events() -> None:
    """Apaga eventos (e, em cascata, as entregas) mais antigos que a retenção. Eventos ainda com entrega pendente ficam."""
    cutoff = _iso(_now() - timedelta(days=retention_days()))
    old = sec.service_rest("GET", f"integration_events?select=id&created_at=lt.{cutoff}&limit=500") or []
    if not old:
        return
    ids = ",".join(e["id"] for e in old)
    open_ids = {d["event_id"] for d in sec.service_rest("GET", f"integration_deliveries?select=event_id&event_id=in.({ids})&status=in.(pending,failed)") or []}
    removable = [e["id"] for e in old if e["id"] not in open_ids]
    if removable:
        sec.service_rest("DELETE", f"integration_events?id=in.({','.join(removable)})")


def _cron_allowed(authorization: str | None, x_cron_secret: str | None) -> None:
    """O agendador da Vercel envia 'Authorization: Bearer <CRON_SECRET>'; outros agendadores podem usar X-Cron-Secret."""
    expected = [v for v in (os.getenv("AURA_CRON_SECRET"), os.getenv("CRON_SECRET")) if v]
    if not expected:
        raise HTTPException(status_code=503, detail="Entrega agendada não configurada.")
    given = x_cron_secret or (authorization[7:] if authorization and authorization.lower().startswith("bearer ") else "")
    if not given or not any(hmac.compare_digest(given.encode(), e.encode()) for e in expected):
        raise HTTPException(status_code=401, detail="Não autorizado.")


@router.api_route("/api/integrations/dispatch", methods=["GET", "POST"])
def dispatch_endpoint(authorization: str | None = Header(default=None), x_cron_secret: str | None = Header(default=None)):
    """Chamada pelo agendador (cron) da hospedagem: entrega o que está vencido e limpa eventos antigos."""
    _cron_allowed(authorization, x_cron_secret)
    summary = dispatch_due()
    try:
        prune_old_events()
    except Exception as exc:  # noqa: BLE001 — a limpeza nunca impede as entregas
        log.warning("Falha ao limpar eventos antigos: %s", type(exc).__name__)
    return {"ok": True, **summary}
