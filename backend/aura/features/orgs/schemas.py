"""Organizações — modelos dos pedidos."""
from pydantic import BaseModel


class InviteCreate(BaseModel):
    email: str
    role: str = "member"


class RoleChange(BaseModel):
    role: str


class InviteAccept(BaseModel):
    token: str


class OrgCreateRequest(BaseModel):
    name: str
