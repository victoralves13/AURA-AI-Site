"""Clientes — camada HTTP."""
from fastapi import APIRouter, Depends

from aura.core import security as sec
from aura.core.errors import require_user
from aura.features.clients import service
from aura.features.clients.schemas import ClientCreate, ClientUpdate, LinkChange, MergeRequest

router = APIRouter()


@router.get("/api/clients")
def list_clients(org_id: str | None = None, user=Depends(sec.current_user)):
    return service.list_clients(require_user(user), org_id)


@router.post("/api/clients")
def create(payload: ClientCreate, user=Depends(sec.current_user)):
    return service.create(require_user(user), payload)


@router.get("/api/clients/{client_id}")
def get_one(client_id: str, user=Depends(sec.current_user)):
    return service.get_one(require_user(user), client_id)


@router.patch("/api/clients/{client_id}")
def update(client_id: str, payload: ClientUpdate, user=Depends(sec.current_user)):
    return service.update(require_user(user), client_id, payload)


@router.patch("/api/meetings/{meeting_id}/client")
def change_link(meeting_id: str, payload: LinkChange, user=Depends(sec.current_user)):
    return service.change_link(require_user(user), meeting_id, payload)


@router.post("/api/clients/{client_id}/merge")
def merge(client_id: str, payload: MergeRequest, user=Depends(sec.current_user)):
    return service.merge(require_user(user), client_id, payload)


@router.post("/api/clients/{client_id}/unmerge")
def unmerge(client_id: str, user=Depends(sec.current_user)):
    return service.unmerge(require_user(user), client_id)
