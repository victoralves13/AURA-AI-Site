"""Chat — modelos dos pedidos."""
from pydantic import BaseModel


class ConversationCreate(BaseModel):
    title: str | None = None
    org_id: str | None = None
    scope: dict | None = None


class ConversationUpdate(BaseModel):
    title: str


class MessageCreate(BaseModel):
    content: str
