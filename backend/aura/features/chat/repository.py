"""Chat — acesso aos dados (PostgREST).

  * Conversas e mensagens: com o JWT da pessoa (o RLS garante que a conversa é privada). A única escrita com a chave de serviço é a
    RESPOSTA do AURA (ninguém consegue forjar uma resposta pelo navegador).
  * Recuperação para o motor: só leitura, com o JWT da pessoa, no espaço e no escopo da conversa.
"""
from __future__ import annotations

from aura.core import security as sec
from aura.core.errors import db_call

SCOPE_TABLES = {"meeting_id": "meetings", "client_id": "clients", "action_id": "actions"}
CONVERSATION_COLUMNS = "id,title,scope,org_id,owner_id,created_at,last_message_at"
MEETING_COLUMNS = ("id,org_id,owner_id,meeting_title,client_name,client_id,created_at,summary,risk,opportunity,sentiment,topics,"
                   "decisions,decisions_detail,pending_actions,actions_detail,important_signals,risk_signals,opportunity_signals,insights,financial_data,"
                   "next_move,owner,deadline,participants,objections")
ACTION_COLUMNS = "id,meeting_id,text,status,assignee_text,due_text,due_date,evidence,meetings(meeting_title,client_name,client_id)"
GENERIC = "Não foi possível concluir a operação com a conversa. Tente novamente."
FORBIDDEN = "Você não tem permissão para usar o chat neste espaço."
KNOWN = {
    "conversation_full": (409, "Esta conversa atingiu o limite de mensagens. Comece uma nova conversa."),
    "too_many_conversations": (409, "Você atingiu o limite de conversas. Apague alguma para criar outra."),
    "conversation_immutable": (409, "Esse campo da conversa não pode ser alterado."),
    "conversation_not_found": (404, "Conversa não encontrada."),
}
NOT_FOUND = KNOWN["conversation_not_found"][1]


def _db(call):
    return db_call(call, generic=GENERIC, known=KNOWN, invalid="Dados da conversa inválidos.", forbidden=FORBIDDEN)


# --- conversas e mensagens -------------------------------------------------------------------------------------------------
def list_conversations(user, space_filter: str, limit: int) -> list[dict]:
    return _db(lambda: sec.user_rest(user, "GET", f"conversations?select=id,title,scope,org_id,created_at,last_message_at&{space_filter}&order=last_message_at.desc&limit={limit}")) or []


def insert_conversation(user, row: dict) -> dict:
    return (_db(lambda: sec.user_rest(user, "POST", "conversations", row)) or [row])[0]


def get_conversation(user, conversation_id: str) -> dict | None:
    rows = _db(lambda: sec.user_rest(user, "GET", f"conversations?select={CONVERSATION_COLUMNS}&id=eq.{conversation_id}&limit=1")) or []
    return rows[0] if rows else None


def list_messages(user, conversation_id: str) -> list[dict]:
    return _db(lambda: sec.user_rest(user, "GET", f"messages?select=id,role,content,sources,evidence_level,created_at&conversation_id=eq.{conversation_id}&order=created_at.asc&limit=500")) or []


def rename_conversation(user, conversation_id: str, title: str) -> dict | None:
    rows = _db(lambda: sec.user_rest(user, "PATCH", f"conversations?id=eq.{conversation_id}", {"title": title})) or []
    return rows[0] if rows else None


def delete_conversation(user, conversation_id: str) -> None:
    _db(lambda: sec.user_rest(user, "DELETE", f"conversations?id=eq.{conversation_id}"))


def scope_item(user, table: str, item_id: str) -> dict | None:
    rows = _db(lambda: sec.user_rest(user, "GET", f"{table}?select=id,org_id&id=eq.{item_id}&limit=1")) or []
    return rows[0] if rows else None


def insert_user_message(user, row: dict) -> dict:
    return (_db(lambda: sec.user_rest(user, "POST", "messages", row)) or [row])[0]


def set_title(user, conversation_id: str, title: str) -> None:
    """Falha original sobe: nomear a conversa pela primeira pergunta é um favor, quem chama decide ignorar."""
    sec.user_rest(user, "PATCH", f"conversations?id=eq.{conversation_id}", {"title": title})


def history(user, conversation_id: str, limit: int = 60) -> list[dict]:
    """Mensagens da conversa em ordem. As fontes das respostas do AURA ficam junto: dizem de que cliente/reunião se falava."""
    return _db(lambda: sec.user_rest(user, "GET", f"messages?select=role,content,sources&conversation_id=eq.{conversation_id}&order=created_at.asc&limit={limit}")) or []


def last_message(user, conversation_id: str) -> dict | None:
    rows = _db(lambda: sec.user_rest(user, "GET", f"messages?select=role,content&conversation_id=eq.{conversation_id}&order=created_at.desc&limit=1")) or []
    return rows[0] if rows else None


def insert_assistant_message(row: dict) -> dict:
    """Resposta do AURA: só o backend grava, com a chave de serviço."""
    return (_db(lambda: sec.service_rest("POST", "messages", row)) or [row])[0]


def count_recent_answers(user_id: str, since: str, limit: int) -> int:
    """Quantas respostas do chat a pessoa teve desde `since` (a falha original sobe: quem chama bloqueia por segurança)."""
    return len(sec.service_rest("GET", f"audit_log?select=id&actor_id=eq.{user_id}&action=eq.chat.answer&at=gte.{since}&limit={limit + 1}") or [])


# --- recuperação para o motor (leitura com o JWT da pessoa; a falha original sobe) -------------------------------------------
def action_in_scope(user, space: str, action_id: str) -> list[dict]:
    return sec.user_rest(user, "GET", f"actions?select={ACTION_COLUMNS}&id=eq.{action_id}&{space}&limit=1") or []


def meetings_by_ids(user, ids: str) -> list[dict]:
    return sec.user_rest(user, "GET", f"meetings?select={MEETING_COLUMNS}&id=in.({ids})&limit=1") or []


def meeting_in_scope(user, space: str, meeting_id: str) -> list[dict]:
    return sec.user_rest(user, "GET", f"meetings?select={MEETING_COLUMNS}&id=eq.{meeting_id}&{space}&limit=1") or []


def client_meetings(user, space: str, client_id: str, limit: int) -> list[dict]:
    return sec.user_rest(user, "GET", f"meetings?select={MEETING_COLUMNS}&client_id=eq.{client_id}&{space}&order=created_at.desc&limit={limit}") or []


def recent_meetings(user, space: str, limit: int) -> list[dict]:
    return sec.user_rest(user, "GET", f"meetings?select={MEETING_COLUMNS}&{space}&is_demo=is.false&order=created_at.desc&limit={limit}") or []


def transcripts(user, ids: list[str]) -> list[dict]:
    return sec.user_rest(user, "GET", f"meetings?select=id,transcript&id=in.({','.join(ids)})&limit={len(ids)}") or []


def portfolio_meetings(user, space: str, limit: int = 60) -> list[dict]:
    """As reuniões mais recentes do espaço (sem a transcrição), para a visão geral e para escolher o detalhe."""
    return sec.user_rest(user, "GET", f"meetings?select={MEETING_COLUMNS}&{space}&is_demo=is.false&order=created_at.desc&limit={limit}") or []


def action_pool(user, space: str, limit: int = 80) -> list[dict]:
    return sec.user_rest(user, "GET", f"actions?select={ACTION_COLUMNS}&{space}&order=created_at.desc&limit={limit}") or []


def meeting_actions(user, meeting_id: str, limit: int = 20) -> list[dict]:
    return sec.user_rest(user, "GET", f"actions?select={ACTION_COLUMNS}&meeting_id=eq.{meeting_id}&limit={limit}") or []
