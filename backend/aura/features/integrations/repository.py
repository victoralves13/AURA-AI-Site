"""Integrações — acesso aos dados (PostgREST).

Duas famílias de funções:
  * as que servem a TELA usam o JWT da pessoa (o RLS decide o que ela vê) ou a chave de serviço com a falha traduzida para AppError;
  * as do PIPELINE de entrega (emitir evento, reservar e concluir entrega) usam a chave de serviço e deixam a falha original subir:
    quem as chama decide (o registro de evento nunca derruba a ação que o gerou; a rodada de entregas segue para a próxima).
"""
from __future__ import annotations

from aura.core import security as sec
from aura.core.errors import db_call

SAFE_COLUMNS = ("id,org_id,provider,name,status,config,events,secret_hint,consecutive_failures,last_success_at,last_failure_at,"
                "disabled_reason,created_at,updated_at")
GENERIC = "Não foi possível concluir a operação com a integração. Tente novamente."
FORBIDDEN = "Você não tem permissão para gerenciar integrações aqui."
INVALID = "Dados da integração inválidos."
KNOWN = {
    "too_many_integrations": (409, "Você atingiu o limite de integrações deste espaço."),
    "integration_invalid_url": (400, "Informe uma URL https válida."),
    "integration_invalid_event": (400, "Tipo de evento inválido."),
    "integration_invalid_provider": (400, "Provedor inválido."),
}


def _db(call):
    return db_call(call, generic=GENERIC, known=KNOWN, invalid=INVALID, forbidden=FORBIDDEN)


def is_duplicate(exc: Exception) -> bool:
    return isinstance(exc, sec.SupabaseError) and (exc.db_code == "23505" or exc.status == 409)


# --- tela (cadastro) -------------------------------------------------------------------------------------------
def get_for_user(user, integration_id: str) -> dict | None:
    """Lê com o JWT da pessoa: o RLS só devolve a de quem pode gerenciá-la."""
    rows = _db(lambda: sec.user_rest(user, "GET", f"integrations?select={SAFE_COLUMNS},owner_id&id=eq.{integration_id}&limit=1")) or []
    return rows[0] if rows else None


def list_for_space(user, space_filter: str) -> list[dict]:
    return _db(lambda: sec.user_rest(user, "GET", f"integrations?select={SAFE_COLUMNS}&{space_filter}&order=created_at.desc&limit=100")) or []


def insert_integration(row: dict) -> dict:
    return (_db(lambda: sec.service_rest("POST", "integrations", row)) or [row])[0]


def patch_integration(integration_id: str, patch: dict) -> dict | None:
    rows = _db(lambda: sec.service_rest("PATCH", f"integrations?id=eq.{integration_id}", patch)) or []
    return rows[0] if rows else None


def delete_integration(integration_id: str) -> None:
    _db(lambda: sec.service_rest("DELETE", f"integrations?id=eq.{integration_id}"))


def list_deliveries(user, integration_id: str, limit: int) -> list[dict]:
    return _db(lambda: sec.user_rest(user, "GET", "integration_deliveries?select=id,event_id,status,attempts,next_attempt_at,last_status,last_error,"
                                                  f"delivered_at,created_at&integration_id=eq.{integration_id}&order=created_at.desc&limit={limit}")) or []


def get_delivery_of_integration(user, integration_id: str, delivery_id: str) -> dict | None:
    rows = _db(lambda: sec.user_rest(user, "GET", f"integration_deliveries?select=id,status&id=eq.{delivery_id}&integration_id=eq.{integration_id}&limit=1")) or []
    return rows[0] if rows else None


def get_delivery_result(user, delivery_id: str) -> dict:
    rows = _db(lambda: sec.user_rest(user, "GET", f"integration_deliveries?select=status,attempts,last_status,last_error&id=eq.{delivery_id}&limit=1")) or [{}]
    return rows[0]


def requeue_delivery(delivery_id: str, next_attempt_at: str) -> None:
    _db(lambda: sec.service_rest("PATCH", f"integration_deliveries?id=eq.{delivery_id}&status=in.(pending,failed,dead)",
                                 {"status": "pending", "attempts": 0, "next_attempt_at": next_attempt_at, "last_error": None}))


def recent_test_events(integration_id: str, since: str, limit: int) -> list[dict]:
    return _db(lambda: sec.service_rest("GET", f"integration_events?select=id&type=eq.integration.test&entity_id=eq.{integration_id}&created_at=gte.{since}&limit={limit}")) or []


def insert_test_event(row: dict) -> dict:
    return (_db(lambda: sec.service_rest("POST", "integration_events", row)) or [{}])[0]


# --- pipeline de entrega (chave de serviço; a falha original sobe) ------------------------------------------------------
def insert_event(row: dict) -> dict:
    return (sec.service_rest("POST", "integration_events", row) or [{}])[0]


def active_targets(space_filter: str) -> list[dict]:
    return sec.service_rest("GET", f"integrations?select=id,events&status=eq.active&{space_filter}") or []


def create_delivery(integration_id: str, event_id: str) -> str | None:
    """Uma entrega por integração e evento (o banco recusa a repetição: aí devolve None)."""
    try:
        return (sec.service_rest("POST", "integration_deliveries", {"integration_id": integration_id, "event_id": event_id}) or [{}])[0].get("id")
    except sec.SupabaseError as exc:
        if is_duplicate(exc):
            return None
        raise


def get_delivery(delivery_id: str) -> dict | None:
    rows = sec.service_rest("GET", f"integration_deliveries?select=id,integration_id,event_id,attempts&id=eq.{delivery_id}&limit=1") or []
    return rows[0] if rows else None


def due_deliveries(now: str, limit: int) -> list[dict]:
    return sec.service_rest("GET", "integration_deliveries?select=id,integration_id,event_id,attempts&status=in.(pending,failed)"
                                   f"&next_attempt_at=lte.{now}&order=next_attempt_at.asc&limit={int(limit)}") or []


def due_for_integration(integration_id: str, now: str, limit: int) -> list[dict]:
    return sec.service_rest("GET", f"integration_deliveries?select=id,integration_id,event_id,attempts&integration_id=eq.{integration_id}"
                                   f"&status=in.(pending,failed)&next_attempt_at=lte.{now}&order=next_attempt_at.asc&limit={limit}") or []


def claim_delivery(delivery_id: str, attempts_before: int, lease: str) -> bool:
    """Reserva por UPDATE condicional: só uma execução ganha (as outras veem 0 linhas)."""
    rows = sec.service_rest("PATCH", f"integration_deliveries?id=eq.{delivery_id}&attempts=eq.{attempts_before}&status=in.(pending,failed)",
                            {"attempts": attempts_before + 1, "next_attempt_at": lease}) or []
    return bool(rows)


def get_integration_with_secret(integration_id: str) -> dict | None:
    rows = sec.service_rest("GET", "integrations?select=id,provider,status,config,secret_ct,key_version,consecutive_failures"
                                   f"&id=eq.{integration_id}&limit=1") or []
    return rows[0] if rows else None


def get_event(event_id: str) -> dict | None:
    rows = sec.service_rest("GET", f"integration_events?select=id,type,entity_type,entity_id,data,created_at&id=eq.{event_id}&limit=1") or []
    return rows[0] if rows else None


def update_delivery(delivery_id: str, patch: dict) -> None:
    sec.service_rest("PATCH", f"integration_deliveries?id=eq.{delivery_id}", patch)


def update_integration(integration_id: str, patch: dict) -> None:
    sec.service_rest("PATCH", f"integrations?id=eq.{integration_id}", patch)


# --- retenção ---------------------------------------------------------------------------------------------------------
def events_older_than(cutoff: str, limit: int = 500) -> list[dict]:
    return sec.service_rest("GET", f"integration_events?select=id&created_at=lt.{cutoff}&limit={limit}") or []


def events_with_open_deliveries(event_ids: list[str]) -> set[str]:
    rows = sec.service_rest("GET", f"integration_deliveries?select=event_id&event_id=in.({','.join(event_ids)})&status=in.(pending,failed)") or []
    return {d["event_id"] for d in rows}


def delete_events(event_ids: list[str]) -> None:
    sec.service_rest("DELETE", f"integration_events?id=in.({','.join(event_ids)})")
