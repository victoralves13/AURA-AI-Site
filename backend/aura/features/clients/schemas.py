"""Clientes — modelos dos pedidos."""
from pydantic import BaseModel


class ClientCreate(BaseModel):
    name: str
    aliases: list[str] = []
    org_id: str | None = None


class ClientUpdate(BaseModel):
    name: str | None = None
    aliases: list[str] | None = None


class LinkChange(BaseModel):
    action: str  # confirm | set | create | unlink
    client_id: str | None = None
    name: str | None = None


class MergeRequest(BaseModel):
    into: str
