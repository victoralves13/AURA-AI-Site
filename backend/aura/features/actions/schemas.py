"""Ações — modelos dos pedidos."""
from pydantic import BaseModel


class ActionCreate(BaseModel):
    text: str
    assignee_text: str | None = None
    assignee_user_id: str | None = None
    due_text: str | None = None
    due_date: str | None = None


class ActionUpdate(BaseModel):
    status: str | None = None
    text: str | None = None
    assignee_text: str | None = None
    assignee_user_id: str | None = None
    due_text: str | None = None
    due_date: str | None = None


class OutcomeCreate(BaseModel):
    result: str
    effectiveness: str
    observed_at: str | None = None


class FeedbackBody(BaseModel):
    rating: str
    note: str | None = None
