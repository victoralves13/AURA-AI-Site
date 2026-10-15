"""Integrações — modelos dos pedidos."""
from pydantic import BaseModel


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
