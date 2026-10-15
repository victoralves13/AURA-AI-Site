"""AURA AI — conversas do chat: histórico persistente, privado e por espaço (fase 5.1).

Regras:
  * A conversa é PRIVADA: só quem a criou a vê. Administradores da organização não leem o chat de outra pessoa.
    O banco garante isso (RLS); aqui o JWT da pessoa é sempre usado.
  * A conversa vive em um espaço (conta pessoal ou organização, com a permissão `chat.use`) e pode ter um escopo
    (uma reunião, um cliente ou uma ação do MESMO espaço), que limita sobre o que se conversa.
  * O navegador só grava a pergunta da pessoa. A resposta do AURA, com as fontes citadas, é gravada só pelo
    backend com a chave de serviço (`append_assistant`), depois de conferir que a conversa é da pessoa.
  * Quem sai da organização tem as conversas feitas nela apagadas pelo banco.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

import security as sec

log = logging.getLogger("aura.conversations")
router = APIRouter()

DEFAULT_TITLE = "Nova conversa"
MAX_CONTENT = 4000
SCOPE_TABLES = {"meeting_id": "meetings", "client_id": "clients", "action_id": "actions"}
EVIDENCE_LEVELS = ("forte", "parcial", "insuficiente")
ERRORS = {
    "conversation_full": (409, "Esta conversa atingiu o limite de mensagens. Comece uma nova conversa."),
    "too_many_conversations": (409, "Você atingiu o limite de conversas. Apague alguma para criar outra."),
    "conversation_immutable": (409, "Esse campo da conversa não pode ser alterado."),
    "conversation_not_found": (404, "Conversa não encontrada."),
}
GENERIC = "Não foi possível concluir a operação com a conversa. Tente novamente."


def _db(call):
    try:
        return call()
    except sec.SupabaseError as exc:
        if exc.db_message in ERRORS:
            status, detail = ERRORS[exc.db_message]
            raise HTTPException(status_code=status, detail=detail) from exc
        if exc.db_code in ("23514", "22P02"):
            raise HTTPException(status_code=400, detail="Dados da conversa inválidos.") from exc
        if exc.status in (401, 403):
            raise HTTPException(status_code=403, detail="Você não tem permissão para usar o chat neste espaço.") from exc
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
    """'personal'/vazio -> conta pessoal (None); uuid -> organização, exigindo a permissão de usar o chat."""
    if not org_id or org_id == "personal":
        return None
    org = _uuid(org_id, "Espaço")
    sec.require_org_permission(user, org, "chat.use")
    return org


def _clean(value, size: int) -> str:
    return " ".join(str(value or "").split())[:size]


def _clean_content(value) -> str:
    text = str(value or "").replace("\r\n", "\n").strip()
    if not text or len(text) > MAX_CONTENT:
        raise HTTPException(status_code=400, detail=f"Escreva uma mensagem de até {MAX_CONTENT} caracteres.")
    return text


def _space_filter(org: str | None) -> str:
    return f"org_id=eq.{org}" if org else "org_id=is.null"


def _check_scope(user: sec.AuthUser, org: str | None, scope) -> dict:
    """Valida o escopo: só chaves conhecidas, ids válidos, itens que a pessoa lê e que são do MESMO espaço."""
    if scope in (None, {}):
        return {}
    if not isinstance(scope, dict):
        raise HTTPException(status_code=400, detail="Escopo inválido.")
    out: dict = {}
    for key, value in scope.items():
        if key not in SCOPE_TABLES:
            raise HTTPException(status_code=400, detail="Escopo inválido.")
        item_id = _uuid(value, "Item do escopo")
        rows = _db(lambda: sec.user_rest(user, "GET", f"{SCOPE_TABLES[key]}?select=id,org_id&id=eq.{item_id}&limit=1")) or []
        if not rows:
            raise HTTPException(status_code=404, detail="Item do escopo não encontrado.")
        if rows[0].get("org_id") != org:
            raise HTTPException(status_code=409, detail="O item do escopo precisa ser do mesmo espaço da conversa.")
        out[key] = item_id
    return out


def _get_conversation(user: sec.AuthUser, conversation_id: str) -> dict:
    rows = _db(lambda: sec.user_rest(user, "GET", f"conversations?select=id,title,scope,org_id,owner_id,created_at,last_message_at&id=eq.{conversation_id}&limit=1")) or []
    if not rows:
        raise HTTPException(status_code=404, detail=ERRORS["conversation_not_found"][1])
    return rows[0]


def append_assistant(user: sec.AuthUser, conversation_id: str, content: str, sources: list | None = None,
                     evidence_level: str | None = None) -> dict:
    """Grava a resposta do AURA (só o backend faz isso). Confere antes que a conversa é da pessoa."""
    conversation = _get_conversation(user, _uuid(conversation_id, "Conversa"))
    if evidence_level is not None and evidence_level not in EVIDENCE_LEVELS:
        raise ValueError("nível de evidência inválido")
    row = {"conversation_id": conversation["id"], "owner_id": user.id, "role": "assistant", "content": str(content)[:20000],
           "sources": list(sources or []), "evidence_level": evidence_level}
    return (_db(lambda: sec.service_rest("POST", "messages", row)) or [row])[0]


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------
class ConversationCreate(BaseModel):
    title: str | None = None
    org_id: str | None = None
    scope: dict | None = None


class ConversationUpdate(BaseModel):
    title: str


class MessageCreate(BaseModel):
    content: str


@router.get("/api/conversations")
def list_conversations(org_id: str | None = None, limit: int = 100, user=Depends(sec.current_user)):
    user = _need_user(user)
    org = _org(user, org_id)
    limit = max(1, min(limit, 200))
    rows = _db(lambda: sec.user_rest(user, "GET", f"conversations?select=id,title,scope,org_id,created_at,last_message_at&{_space_filter(org)}&order=last_message_at.desc&limit={limit}")) or []
    return {"ok": True, "conversations": rows}


@router.post("/api/conversations")
def create_conversation(payload: ConversationCreate, user=Depends(sec.current_user)):
    user = _need_user(user)
    org = _org(user, payload.org_id)
    title = _clean(payload.title, 200) or DEFAULT_TITLE
    scope = _check_scope(user, org, payload.scope)
    row = {"owner_id": user.id, "org_id": org, "title": title, "scope": scope}
    created = (_db(lambda: sec.user_rest(user, "POST", "conversations", row)) or [row])[0]
    sec.audit(user, "conversation.create", org, "conversation", created.get("id"), {"scoped": bool(scope)})
    return {"ok": True, "conversation": created}


@router.get("/api/conversations/{conversation_id}")
def get_conversation(conversation_id: str, user=Depends(sec.current_user)):
    user = _need_user(user)
    cid = _uuid(conversation_id, "Conversa")
    conversation = _get_conversation(user, cid)
    messages = _db(lambda: sec.user_rest(user, "GET", f"messages?select=id,role,content,sources,evidence_level,created_at&conversation_id=eq.{cid}&order=created_at.asc&limit=500")) or []
    return {"ok": True, "conversation": conversation, "messages": messages}


@router.patch("/api/conversations/{conversation_id}")
def rename_conversation(conversation_id: str, payload: ConversationUpdate, user=Depends(sec.current_user)):
    user = _need_user(user)
    cid = _uuid(conversation_id, "Conversa")
    title = _clean(payload.title, 201)
    if not title or len(title) > 200:
        raise HTTPException(status_code=400, detail="O título deve ter entre 1 e 200 caracteres.")
    current = _get_conversation(user, cid)
    rows = _db(lambda: sec.user_rest(user, "PATCH", f"conversations?id=eq.{cid}", {"title": title})) or []
    if not rows:
        raise HTTPException(status_code=404, detail=ERRORS["conversation_not_found"][1])
    sec.audit(user, "conversation.rename", current.get("org_id"), "conversation", cid)
    return {"ok": True, "conversation": rows[0]}


@router.delete("/api/conversations/{conversation_id}")
def delete_conversation(conversation_id: str, user=Depends(sec.current_user)):
    user = _need_user(user)
    cid = _uuid(conversation_id, "Conversa")
    current = _get_conversation(user, cid)
    _db(lambda: sec.user_rest(user, "DELETE", f"conversations?id=eq.{cid}"))
    sec.audit(user, "conversation.delete", current.get("org_id"), "conversation", cid)
    return {"ok": True}


@router.post("/api/conversations/{conversation_id}/messages")
def add_message(conversation_id: str, payload: MessageCreate, user=Depends(sec.current_user)):
    """Grava a pergunta da pessoa. (A resposta do AURA entra pela fase 5.2, via `append_assistant`.)"""
    user = _need_user(user)
    cid = _uuid(conversation_id, "Conversa")
    content = _clean_content(payload.content)
    conversation = _get_conversation(user, cid)
    if conversation.get("org_id"):  # a permissão pode ter sido retirada depois da criação
        sec.require_org_permission(user, conversation["org_id"], "chat.use")
    row = {"conversation_id": cid, "role": "user", "content": content}
    message = (_db(lambda: sec.user_rest(user, "POST", "messages", row)) or [row])[0]
    if conversation.get("title") == DEFAULT_TITLE:  # a primeira pergunta nomeia a conversa
        try:
            sec.user_rest(user, "PATCH", f"conversations?id=eq.{cid}", {"title": _clean(content, 60)})
        except RuntimeError as exc:
            log.warning("título da conversa não atualizado: %s", exc)
    return {"ok": True, "message": message}
