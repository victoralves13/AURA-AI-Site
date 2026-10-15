"""Clientes — acesso aos dados (PostgREST, sempre com o JWT da pessoa: o RLS vale).

As funções "guardadas" traduzem a falha do banco em AppError (para a tela). `list_scope_clients` e `insert_client` deixam a falha
original subir porque o vínculo de uma reunião nova precisa dela (ela é tratada lá: a análise nunca se perde por causa do vínculo).
"""
from __future__ import annotations

from aura.core import security as sec
from aura.core.errors import AppError

MAX_CLIENTS_SCANNED = 500
GENERIC = "Não foi possível concluir a operação com clientes. Tente novamente."
FORBIDDEN = "Você não tem permissão para esta operação com clientes."
KNOWN = {
    "client_not_found": (404, "Cliente não encontrado."),
    "forbidden": (403, FORBIDDEN),
    "same_client": (400, "Escolha dois clientes diferentes."),
    "client_scope_mismatch": (409, "O cliente precisa ser do mesmo espaço (organização ou conta pessoal) da reunião."),
    "already_merged": (409, "Um dos clientes já foi fundido em outro."),
    "not_merged": (409, "Este cliente não está fundido."),
    "client_merged": (409, "Este cliente foi fundido em outro e não aceita novos vínculos."),
}
DUPLICATE = "Já existe um cliente com esse nome neste espaço."


def _guarded(call):
    try:
        return call()
    except sec.SupabaseError as exc:
        if exc.db_message in KNOWN:
            status, detail = KNOWN[exc.db_message]
            raise AppError(status, detail) from exc
        if exc.db_code == "23505":
            raise AppError(409, DUPLICATE) from exc
        if exc.status in (401, 403):
            raise AppError(403, FORBIDDEN) from exc
        raise AppError(502, GENERIC) from exc
    except RuntimeError as exc:
        raise AppError(502, GENERIC) from exc


# O grupo do cliente (coluna group_name) vem de uma migração aditiva. Enquanto o banco não a tem, tudo continua funcionando sem grupo.
_GROUPS = {"supported": None}  # None = ainda não sabemos; False = o banco não tem a coluna


def groups_supported() -> bool:
    return _GROUPS["supported"] is not False


def _missing_group_column(exc: Exception) -> bool:
    return isinstance(exc, sec.SupabaseError) and (exc.db_code in ("42703", "PGRST204") or "group_name" in exc.db_message)


def _with_group(call_with, call_without):
    """Tenta com o grupo; se o banco ainda não tem a coluna, lembra disso e refaz sem ela."""
    if _GROUPS["supported"] is False:
        return call_without()
    try:
        result = call_with()
        _GROUPS["supported"] = True
        return result
    except sec.SupabaseError as exc:
        if not _missing_group_column(exc):
            raise
        _GROUPS["supported"] = False
        return call_without()


def scope_filter(user: sec.AuthUser, org_id: str | None) -> str:
    return f"org_id=eq.{org_id}" if org_id else f"org_id=is.null&owner_id=eq.{user.id}"


# --- leitura -------------------------------------------------------------------------------------------------------------
def list_scope_clients(user, org_id: str | None) -> list[dict]:
    """Clientes do espaço para a correspondência de nomes (falha original sobe)."""
    def get(cols):
        return sec.user_rest(user, "GET", f"clients?select={cols}&merged_into=is.null&{scope_filter(user, org_id)}&order=name.asc&limit={MAX_CLIENTS_SCANNED}") or []
    return _with_group(lambda: get("id,name,normalized_name,aliases,group_name"), lambda: get("id,name,normalized_name,aliases"))


def list_clients(user, where: str) -> list[dict]:
    def get(cols):
        return sec.user_rest(user, "GET", f"clients?select={cols}&merged_into=is.null&{where}&order=name.asc&limit=500") or []
    return _guarded(lambda: _with_group(lambda: get("id,name,aliases,created_via,created_at,group_name"), lambda: get("id,name,aliases,created_via,created_at")))


def linked_meeting_rows(user, where: str) -> list[dict]:
    return _guarded(lambda: sec.user_rest(user, "GET", f"meetings?select=client_id&client_id=not.is.null&{where}&limit=2000")) or []


def pending_suggestion_rows(user, where: str) -> list[dict]:
    return _guarded(lambda: sec.user_rest(user, "GET", f"meetings?select=id&client_link=eq.suggested&{where}&limit=1000")) or []


def get_client(user, client_id: str) -> dict | None:
    rows = _guarded(lambda: sec.user_rest(user, "GET", f"clients?select=*&id=eq.{client_id}&limit=1")) or []
    return rows[0] if rows else None


def client_meetings(user, client_id: str) -> list[dict]:
    return _guarded(lambda: sec.user_rest(user, "GET", "meetings?select=id,meeting_title,created_at,client_link,sentiment,risk,opportunity"
                                                       f"&client_id=eq.{client_id}&order=created_at.desc&limit=100")) or []


def get_meeting_scope(user, meeting_id: str) -> dict | None:
    rows = _guarded(lambda: sec.user_rest(user, "GET", f"meetings?select=id,org_id,owner_id&id=eq.{meeting_id}&limit=1")) or []
    return rows[0] if rows else None


# --- escrita -------------------------------------------------------------------------------------------------------------
def insert_client(user, row: dict) -> dict:
    """Cria o cliente (falha original sobe). Sem a coluna de grupo no banco, o cliente é criado sem ela."""
    plain = {k: v for k, v in row.items() if k != "group_name"}
    if "group_name" not in row:
        return (sec.user_rest(user, "POST", "clients", plain) or [plain])[0]
    return _with_group(lambda: (sec.user_rest(user, "POST", "clients", row) or [row])[0], lambda: (sec.user_rest(user, "POST", "clients", plain) or [plain])[0])


def insert_client_guarded(user, row: dict) -> dict:
    return _guarded(lambda: insert_client(user, row))


def patch_client(user, client_id: str, changes: dict) -> dict | None:
    plain = {k: v for k, v in changes.items() if k != "group_name"}

    def go(body):
        return sec.user_rest(user, "PATCH", f"clients?id=eq.{client_id}", body) if body else sec.user_rest(user, "GET", f"clients?select=*&id=eq.{client_id}&limit=1")
    rows = _guarded(lambda: _with_group(lambda: go(changes), lambda: go(plain))) or []
    return rows[0] if rows else None


def patch_meeting_link(user, meeting_id: str, change: dict) -> bool:
    return bool(_guarded(lambda: sec.user_rest(user, "PATCH", f"meetings?id=eq.{meeting_id}", change)))


def merge_clients(user, source: str, target: str) -> dict:
    return _guarded(lambda: sec.user_rest(user, "POST", "rpc/merge_clients", {"p_source": source, "p_target": target})) or {}


def unmerge_clients(user, source: str) -> dict:
    return _guarded(lambda: sec.user_rest(user, "POST", "rpc/unmerge_clients", {"p_source": source})) or {}
