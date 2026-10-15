"""Ações — acesso aos dados (PostgREST, sempre com o JWT da pessoa: o RLS vale e a chave de serviço nunca é usada aqui).

As funções que servem a tela traduzem a falha do banco em AppError; `sync_*` deixam a falha original subir porque a sincronização
roda no meio da análise e nunca pode derrubá-la (o serviço trata).
"""
from __future__ import annotations

from aura.core import security as sec
from aura.core.errors import AppError, db_call

SELECT_LIST = ("*,meetings(meeting_title,client_name,client_id,created_at),"
               "action_outcomes(effectiveness,result,observed_at,created_at),action_feedback(user_id,rating)")
STATS_LIMIT = 2000
GENERIC = "Não foi possível concluir a operação com ações. Tente novamente."
FORBIDDEN = "Você não tem permissão para alterar ações desta reunião."
DUPLICATE = "Essa ação já existe nesta reunião."
KNOWN = {
    "action_text_locked": (409, "O texto e a evidência de uma ação gerada pela análise não podem ser alterados. Cancele a ação, se necessário."),
    "action_immutable": (409, "Esse campo da ação não pode ser alterado."),
    "assignee_not_member": (400, "O responsável precisa ser membro da organização desta reunião."),
    "meeting_not_found": (404, "Reunião não encontrada."),
    "action_not_found": (404, "Ação não encontrada."),
    "action_not_closed": (409, "Só é possível registrar o resultado de uma ação concluída, cancelada ou vencida."),
    "observed_in_future": (400, "A data da observação não pode ser futura."),
    "feedback_only_ai": (409, "Só ações geradas pela análise recebem feedback."),
    "feedback_immutable": (409, "Esse campo do feedback não pode ser alterado."),
}
OBSERVED_IN_FUTURE = KNOWN["observed_in_future"][1]
FEEDBACK_ONLY_AI = KNOWN["feedback_only_ai"][1]


def _db(call):
    try:
        return call()
    except sec.SupabaseError as exc:
        if exc.db_code == "23505":
            raise AppError(409, DUPLICATE) from exc
        raise


def _guarded(call):
    return db_call(lambda: _db(call), generic=GENERIC, known=KNOWN, invalid="Dados da ação inválidos.", forbidden=FORBIDDEN)


# --- reuniões ------------------------------------------------------------------------------------------------------------
def get_meeting(user, meeting_id: str) -> dict | None:
    rows = _guarded(lambda: sec.user_rest(user, "GET", f"meetings?select=id,org_id,owner_id,actions_detail,pending_actions&id=eq.{meeting_id}&limit=1")) or []
    return rows[0] if rows else None


def meetings_of_client(user, client_id: str) -> list[str]:
    return [m["id"] for m in _guarded(lambda: sec.user_rest(user, "GET", f"meetings?select=id&client_id=eq.{client_id}&limit=500")) or []]


def meetings_to_sync(user, where: str, limit: int) -> list[dict]:
    return _guarded(lambda: sec.user_rest(user, "GET", "meetings?select=id,org_id,owner_id,actions_detail,pending_actions&is_demo=is.false"
                                                       f"{where}&order=created_at.desc&limit={limit}")) or []


# --- ações ---------------------------------------------------------------------------------------------------------------
def get_action(user, action_id: str) -> dict | None:
    rows = _guarded(lambda: sec.user_rest(user, "GET", f"actions?select={SELECT_LIST}&id=eq.{action_id}&limit=1")) or []
    return rows[0] if rows else None


def list_actions(user, where: str, limit: int) -> list[dict]:
    return _guarded(lambda: sec.user_rest(user, "GET", f"actions?select={SELECT_LIST}{where}&order=created_at.desc&limit={limit}")) or []


def stats_rows(user, where: str) -> list[dict]:
    return _guarded(lambda: sec.user_rest(user, "GET", "actions?select=id,status,due_date,source,basis,action_outcomes(effectiveness,created_at),"
                                                       f"action_feedback(rating){where}&limit={STATS_LIMIT}")) or []


def list_for_meeting(user, meeting_id: str) -> list[dict]:
    return _guarded(lambda: sec.user_rest(user, "GET", f"actions?select={SELECT_LIST}&meeting_id=eq.{meeting_id}&order=created_at.asc&limit=200")) or []


def insert_action(user, row: dict) -> dict:
    return (_guarded(lambda: sec.user_rest(user, "POST", "actions", row)) or [row])[0]


def patch_action(user, action_id: str, changes: dict) -> dict | None:
    rows = _guarded(lambda: sec.user_rest(user, "PATCH", f"actions?id=eq.{action_id}", changes)) or []
    return rows[0] if rows else None


def delete_action(user, action_id: str) -> bool:
    """True se apagou; False se nada foi apagado (sem permissão ou inexistente)."""
    return bool(_guarded(lambda: sec.user_rest(user, "DELETE", f"actions?id=eq.{action_id}")))


def action_exists(user, action_id: str) -> bool:
    return bool(_guarded(lambda: sec.user_rest(user, "GET", f"actions?select=id&id=eq.{action_id}&limit=1")))


def list_events(user, action_id: str) -> list[dict]:
    return _guarded(lambda: sec.user_rest(user, "GET", f"action_events?select=at,actor_id,event,data&action_id=eq.{action_id}&order=at.asc&limit=200")) or []


# --- resultados e feedback -----------------------------------------------------------------------------------------------
def insert_outcome(user, row: dict) -> dict:
    return (_guarded(lambda: sec.user_rest(user, "POST", "action_outcomes", row)) or [row])[0]


def list_outcomes(user, action_id: str) -> list[dict]:
    return _guarded(lambda: sec.user_rest(user, "GET", "action_outcomes?select=id,result,effectiveness,observed_at,recorded_by,created_at"
                                                       f"&action_id=eq.{action_id}&order=created_at.desc&limit=100")) or []


def save_feedback(user, action_id: str, fields: dict) -> dict:
    """Cria ou troca o voto da pessoa (um por ação). Se outro pedido votou ao mesmo tempo, troca o voto."""
    def save():
        mine = sec.user_rest(user, "GET", f"action_feedback?select=id&action_id=eq.{action_id}&user_id=eq.{user.id}&limit=1") or []
        if mine:
            return sec.user_rest(user, "PATCH", f"action_feedback?id=eq.{mine[0]['id']}", fields)
        return sec.user_rest(user, "POST", "action_feedback", {"action_id": action_id, **fields})
    try:
        return (_guarded(save) or [fields])[0]
    except AppError as exc:
        if exc.status_code != 409 or exc.detail != DUPLICATE:
            raise
        return (_guarded(save) or [fields])[0]


def clear_feedback(user, action_id: str) -> None:
    _guarded(lambda: sec.user_rest(user, "DELETE", f"action_feedback?action_id=eq.{action_id}&user_id=eq.{user.id}"))


# --- sincronização com a análise (a falha original sobe) -----------------------------------------------------------------
def existing_source_keys(user, meeting_id: str) -> set[str]:
    rows = sec.user_rest(user, "GET", f"actions?select=source_key&meeting_id=eq.{meeting_id}&source_key=not.is.null&limit=200") or []
    return {r["source_key"] for r in rows}


def insert_synced_action(user, row: dict) -> bool:
    """Cria a ação derivada; False se outra chamada criou a mesma ao mesmo tempo."""
    try:
        sec.user_rest(user, "POST", "actions", row)
        return True
    except sec.SupabaseError as exc:
        if exc.db_code != "23505":
            raise
        return False
