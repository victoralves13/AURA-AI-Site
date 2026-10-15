"""Chat — camada HTTP: conversas e mensagens."""
from fastapi import APIRouter, Depends

from aura.core import security as sec
from aura.core.errors import require_user
from aura.features.chat import service
from aura.features.chat.schemas import ConversationCreate, ConversationUpdate, MessageCreate

router = APIRouter()


@router.get("/api/conversations")
def list_conversations(org_id: str | None = None, limit: int = 100, user=Depends(sec.current_user)):
    return service.list_conversations(require_user(user), org_id, limit)


@router.post("/api/conversations")
def create_conversation(payload: ConversationCreate, user=Depends(sec.current_user)):
    return service.create_conversation(require_user(user), payload)


@router.get("/api/conversations/{conversation_id}")
def get_conversation(conversation_id: str, user=Depends(sec.current_user)):
    return service.get_conversation(require_user(user), conversation_id)


@router.patch("/api/conversations/{conversation_id}")
def rename_conversation(conversation_id: str, payload: ConversationUpdate, user=Depends(sec.current_user)):
    return service.rename_conversation(require_user(user), conversation_id, payload)


@router.delete("/api/conversations/{conversation_id}")
def delete_conversation(conversation_id: str, user=Depends(sec.current_user)):
    return service.delete_conversation(require_user(user), conversation_id)


@router.post("/api/conversations/{conversation_id}/messages")
def add_message(conversation_id: str, payload: MessageCreate, user=Depends(sec.current_user)):
    return service.add_message(require_user(user), conversation_id, payload)


@router.post("/api/conversations/{conversation_id}/answer")
def retry_answer(conversation_id: str, user=Depends(sec.current_user)):
    return service.retry_answer(require_user(user), conversation_id)
