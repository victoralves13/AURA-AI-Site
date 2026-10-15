"""AURA AI — integrações: cadastro, segredos cifrados, registro de eventos e entrega idempotente (regras).

Arquitetura:
  * Um EVENTO ("reunião analisada", "ação concluída"...) é registrado uma vez (`emit_event`) e, para cada integração ativa do
    mesmo espaço que assina esse tipo, nasce UMA entrega (UNIQUE integração+evento no banco: repetir não duplica).
  * `dispatch_due` entrega o que está vencido: reserva a entrega com um UPDATE condicional (duas execuções simultâneas nunca
    entregam a mesma), chama o PROVEDOR, e agenda nova tentativa com espera crescente. Passadas as tentativas, a entrega vira
    "dead"; muitas falhas seguidas desligam a integração. Um provedor com erro nunca derruba quem emitiu o evento.
  * PROVEDORES são plugáveis (`providers.register_provider`); o webhook assinado está em `webhook.py`.
  * Só quem tem `integrations.manage` (ou o dono, na conta pessoal) vê e gerencia. O segredo é cifrado (`crypto`) e mostrado
    UMA vez, ao criar ou girar. Nada de transcrição vai nos eventos.
"""
from __future__ import annotations

import hmac
import logging
import os
import secrets
import time
import uuid
from datetime import datetime, timedelta, timezone

from aura.core import security as sec
from aura.core.errors import AppError
from aura.features.integrations import crypto as ic
from aura.features.integrations import providers, repository
from aura.features.integrations.providers import DeliveryResult, Provider
from aura.features.integrations.schemas import IntegrationCreate, IntegrationUpdate

log = logging.getLogger("aura.integrations")

PERMISSION = "integrations.manage"
EVENT_TYPES = ("meeting.analyzed", "action.completed", "live.consolidated")  # assináveis; 'integration.test' é só do botão de teste
ALL_EVENT_TYPES = EVENT_TYPES + ("integration.test",)
MAX_ATTEMPTS = 6
BACKOFF_MINUTES = (1, 5, 30, 120, 360)  # espera depois da 1ª, 2ª, ... falha
LEASE_MINUTES = 5  # reserva de uma entrega em andamento (se a função cair, ela volta a valer depois)
DISABLE_AFTER = 10  # falhas seguidas que desligam a integração
BUDGET_SECONDS = 40  # tempo máximo de uma rodada de entregas (a função da hospedagem tem limite); o resto fica para a próxima
MAX_TESTS_PER_HOUR = 10  # botão 'Testar' por integração (evita usar o servidor como disparador de requisições)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _uuid(value, what: str) -> str:
    if not isinstance(value, str) or not sec.UUID_RE.match(value):
        raise AppError(400, f"{what} inválido.")
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
        raise AppError(503, "As integrações ainda não estão configuradas neste ambiente.")


def _need_provider(name: str) -> Provider:
    provider = providers.get_provider(name)
    if provider is None:
        raise AppError(501, "Este tipo de integração ainda não está disponível.")
    return provider


def _new_secret() -> str:
    return "whsec_" + secrets.token_urlsafe(32)


def _hint(secret: str) -> str:
    return secret[-4:]


def _get_integration(user: sec.AuthUser, integration_id: str) -> dict:
    row = repository.get_for_user(user, integration_id)
    if row is None:
        raise AppError(404, "Integração não encontrada.")
    return row


def _manageable(user: sec.AuthUser, integration_id: str) -> tuple[str, dict]:
    """Valida o id, lê a integração (o RLS esconde as de outros espaços) e exige a permissão de gerenciar."""
    iid = _uuid(integration_id, "Integração")
    current = _get_integration(user, iid)
    sec.require_org_permission(user, current.get("org_id"), PERMISSION)
    return iid, current


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
        created = repository.insert_event(row)
    except sec.SupabaseError as exc:
        if repository.is_duplicate(exc):
            return None  # mesmo evento de origem já registrado: nada a fazer
        raise
    event_id = created.get("id")
    for integ in repository.active_targets(_space_filter(org_id, owner_id)):
        if type_ in (integ.get("events") or []):
            repository.create_delivery(integ["id"], event_id)
    return event_id


def emit_safe(*args, **kwargs) -> str | None:
    """Como emit_event, mas NUNCA levanta erro: quem emite (análise, ação...) não pode falhar por causa de integração."""
    try:
        return emit_event(*args, **kwargs)
    except Exception as exc:  # noqa: BLE001
        log.warning("Falha ao registrar evento de integração: %s", type(exc).__name__)
        return None


def _finish(delivery: dict, integ: dict, result: DeliveryResult, attempts: int) -> str:
    now = _now()
    if result.ok:
        repository.update_delivery(delivery["id"], {"status": "succeeded", "attempts": attempts, "last_status": result.status_code,
                                                    "last_error": None, "delivered_at": _iso(now)})
        repository.update_integration(integ["id"], {"consecutive_failures": 0, "last_success_at": _iso(now)})
        return "succeeded"
    dead = (not result.retryable) or attempts >= MAX_ATTEMPTS
    patch = {"status": "dead" if dead else "failed", "attempts": attempts, "last_status": result.status_code,
             "last_error": (result.error or "Falha na entrega.")[:300]}
    if not dead:
        patch["next_attempt_at"] = _iso(now + timedelta(minutes=BACKOFF_MINUTES[min(attempts - 1, len(BACKOFF_MINUTES) - 1)]))
    repository.update_delivery(delivery["id"], patch)
    failures = int(integ.get("consecutive_failures") or 0) + 1
    integ_patch = {"consecutive_failures": failures, "last_failure_at": _iso(now)}
    if failures >= DISABLE_AFTER:
        integ_patch.update({"status": "disabled", "disabled_reason": "Desligada após falhas seguidas. Corrija o destino e reative."})
    repository.update_integration(integ["id"], integ_patch)
    return patch["status"]


def deliver_one(delivery: dict) -> str | None:
    """Entrega uma (reservando antes). Retorna o estado final, ou None se outra execução já a pegou ou ela não pode seguir."""
    attempts_before = int(delivery.get("attempts") or 0)
    lease = _iso(_now() + timedelta(minutes=LEASE_MINUTES))
    if not repository.claim_delivery(delivery["id"], attempts_before, lease):
        return None
    attempts = attempts_before + 1
    integ = repository.get_integration_with_secret(delivery["integration_id"])
    event = repository.get_event(delivery["event_id"])
    if not integ or not event:
        return None
    if integ.get("status") != "active":
        # pausada: devolve a reserva sem gastar a tentativa; desligada: encerra
        if integ.get("status") == "disabled":
            repository.update_delivery(delivery["id"], {"status": "dead", "last_error": "Integração desligada."})
            return "dead"
        repository.update_delivery(delivery["id"], {"attempts": attempts_before, "next_attempt_at": _iso(_now() + timedelta(minutes=5))})
        return None
    provider = providers.get_provider(integ["provider"])
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
    return _run(repository.due_deliveries(_iso(_now()), limit))


def _run(rows: list[dict], budget: float = BUDGET_SECONDS) -> dict:
    """Entrega em sequência, parando ao esgotar o tempo: o que sobrar continua pendente para a próxima rodada."""
    summary = {"found": len(rows), "succeeded": 0, "failed": 0, "dead": 0, "skipped": 0, "deferred": 0}
    start = time.monotonic()
    for i, row in enumerate(rows):
        if time.monotonic() - start > budget:
            summary["deferred"] = len(rows) - i
            break
        try:
            outcome = deliver_one(row)
        except Exception as exc:  # noqa: BLE001
            log.warning("Falha ao processar entrega: %s", type(exc).__name__)
            outcome = None
        summary["skipped" if outcome is None else outcome] += 1
    return summary


def retention_days() -> int:
    try:
        return max(1, int(os.getenv("AURA_INTEGRATION_EVENT_RETENTION_DAYS", "30")))
    except ValueError:
        return 30


def prune_old_events() -> None:
    """Apaga eventos (e, em cascata, as entregas) mais antigos que a retenção. Eventos ainda com entrega pendente ficam."""
    cutoff = _iso(_now() - timedelta(days=retention_days()))
    old = repository.events_older_than(cutoff)
    if not old:
        return
    ids = [e["id"] for e in old]
    open_ids = repository.events_with_open_deliveries(ids)
    removable = [i for i in ids if i not in open_ids]
    if removable:
        repository.delete_events(removable)


def check_cron_secret(authorization: str | None, x_cron_secret: str | None) -> None:
    """O agendador da Vercel envia 'Authorization: Bearer <CRON_SECRET>'; outros agendadores podem usar X-Cron-Secret."""
    expected = [v for v in (os.getenv("AURA_CRON_SECRET"), os.getenv("CRON_SECRET")) if v]
    if not expected:
        raise AppError(503, "Entrega agendada não configurada.")
    given = x_cron_secret or (authorization[7:] if authorization and authorization.lower().startswith("bearer ") else "")
    if not given or not any(hmac.compare_digest(given.encode(), e.encode()) for e in expected):
        raise AppError(401, "Não autorizado.")


def dispatch_scheduled(authorization: str | None, x_cron_secret: str | None) -> dict:
    """Rodada do agendador: entrega o que está vencido e limpa eventos antigos."""
    check_cron_secret(authorization, x_cron_secret)
    summary = dispatch_due()
    try:
        prune_old_events()
    except Exception as exc:  # noqa: BLE001 — a limpeza nunca impede as entregas
        log.warning("Falha ao limpar eventos antigos: %s", type(exc).__name__)
    return {"ok": True, **summary}


# ---------------------------------------------------------------------------
# Casos de uso da API
# ---------------------------------------------------------------------------
def _clean_events(events) -> list[str]:
    out = []
    for e in events or []:
        if e not in EVENT_TYPES:
            raise AppError(400, "Tipo de evento inválido.")
        if e not in out:
            out.append(e)
    return out


def _clean_name(value) -> str:
    name = " ".join(str(value or "").split())
    if not 1 <= len(name) <= 100:
        raise AppError(400, "O nome deve ter entre 1 e 100 caracteres.")
    return name


def _validate_config(provider: Provider, config) -> dict:
    try:
        return provider.validate_config(config or {})
    except ValueError as exc:
        raise AppError(400, str(exc)) from exc


def list_integrations(user, org_id: str | None) -> dict:
    org = _org(user, org_id)
    rows = repository.list_for_space(user, _space_filter(org, user.id))
    return {"ok": True, "integrations": rows, "configured": ic.configured(), "providers": providers.names(), "events": list(EVENT_TYPES)}


def create_integration(user, payload: IntegrationCreate) -> dict:
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
    created = repository.insert_integration(row)
    sec.audit(user, "integration.create", org, "integration", integration_id, {"provider": payload.provider})
    return {"ok": True, "integration": _public(created), "secret": secret}  # o segredo só aparece aqui


def update_integration(user, integration_id: str, payload: IntegrationUpdate) -> dict:
    iid, current = _manageable(user, integration_id)
    patch: dict = {}
    if payload.name is not None:
        patch["name"] = _clean_name(payload.name)
    if payload.events is not None:
        patch["events"] = _clean_events(payload.events)
    if payload.config is not None:
        patch["config"] = _validate_config(_need_provider(current["provider"]), payload.config)
    if payload.status is not None:
        if payload.status not in ("active", "paused"):
            raise AppError(400, "Estado inválido.")
        patch["status"] = payload.status
        if payload.status == "active":
            patch.update({"consecutive_failures": 0, "disabled_reason": None})
    if not patch:
        raise AppError(400, "Nada para alterar.")
    row = repository.patch_integration(iid, patch)
    sec.audit(user, "integration.update", current.get("org_id"), "integration", iid, {"fields": sorted(patch)})
    return {"ok": True, "integration": _public(row if row else {**current, **patch})}


def rotate_secret(user, integration_id: str) -> dict:
    iid, current = _manageable(user, integration_id)
    _need_crypto()
    secret = _new_secret()
    secret_ct, version = ic.encrypt(secret, iid)
    repository.patch_integration(iid, {"secret_ct": secret_ct, "secret_hint": _hint(secret), "key_version": version})
    sec.audit(user, "integration.rotate_secret", current.get("org_id"), "integration", iid)
    return {"ok": True, "secret": secret}


def delete_integration(user, integration_id: str) -> dict:
    iid, current = _manageable(user, integration_id)
    repository.delete_integration(iid)
    sec.audit(user, "integration.delete", current.get("org_id"), "integration", iid, {"provider": current.get("provider")})
    return {"ok": True}


def list_deliveries(user, integration_id: str, limit: int) -> dict:
    iid = _uuid(integration_id, "Integração")
    _get_integration(user, iid)
    return {"ok": True, "deliveries": repository.list_deliveries(user, iid, max(1, min(limit, 200)))}


def test_integration(user, integration_id: str) -> dict:
    """Envia um evento de teste SÓ para esta integração e mostra o resultado na hora."""
    iid, current = _manageable(user, integration_id)
    if current["status"] != "active":
        raise AppError(409, "Reative a integração antes de testar.")
    _need_provider(current["provider"])
    since = _iso(_now() - timedelta(hours=1))
    if len(repository.recent_test_events(iid, since, MAX_TESTS_PER_HOUR)) >= MAX_TESTS_PER_HOUR:
        raise AppError(429, "Muitos testes seguidos. Tente de novo daqui a pouco.")
    event = repository.insert_test_event({
        "org_id": current.get("org_id"), "owner_id": user.id, "type": "integration.test", "entity_type": "integration", "entity_id": iid,
        "data": {"message": "Evento de teste do AURA AI."}})
    delivery_id = repository.create_delivery(iid, event["id"])
    pending = repository.get_delivery(delivery_id) if delivery_id else None
    summary = {"outcome": deliver_one(pending) if pending else None}
    sec.audit(user, "integration.test", current.get("org_id"), "integration", iid)
    return {"ok": True, "delivery": repository.get_delivery_result(user, delivery_id), "summary": summary}


def retry_delivery(user, integration_id: str, delivery_id: str) -> dict:
    """Reenvia uma entrega encerrada ('dead') ou com falha: volta ao início da fila, com as tentativas zeradas."""
    _uuid(integration_id, "Integração")
    did = _uuid(delivery_id, "Entrega")
    iid, current = _manageable(user, integration_id)
    delivery = repository.get_delivery_of_integration(user, iid, did)
    if delivery is None:
        raise AppError(404, "Entrega não encontrada.")
    if delivery["status"] == "succeeded":
        raise AppError(409, "Esta entrega já foi concluída.")
    if current["status"] == "disabled":
        raise AppError(409, "Reative a integração antes de reenviar.")
    repository.requeue_delivery(did, _iso(_now()))
    sec.audit(user, "integration.retry", current.get("org_id"), "integration", iid)
    return {"ok": True}


def flush_integration(user, integration_id: str) -> dict:
    """Entrega agora o que já está vencido DESTA integração (botão 'enviar pendentes'). O agendador faz o mesmo para todas."""
    iid, _current = _manageable(user, integration_id)
    return {"ok": True, **_run(repository.due_for_integration(iid, _iso(_now()), 10))}
