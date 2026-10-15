"""Reuniões — camada HTTP (listar e gravar). O modo legado, sem login, também passa por aqui: `user` pode ser None."""
from fastapi import APIRouter, Depends

from aura.core import security as sec
from aura.features.meetings import service

router = APIRouter()


@router.get("/api/meetings")
def meetings(limit: int = 50, org_id: str | None = None, user=Depends(sec.current_user)):
    return service.list_meetings(user, limit, org_id)


@router.post("/api/meetings")
def create_meeting(payload: dict, user=Depends(sec.current_user)):
    return service.create_meeting(user, payload)
