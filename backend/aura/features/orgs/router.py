"""Organizações — camada HTTP: conta (/me), organizações, membros e convites."""
from fastapi import APIRouter, Depends

from aura.core import security as sec
from aura.core.errors import require_user
from aura.features.orgs import service
from aura.features.orgs.schemas import InviteAccept, InviteCreate, OrgCreateRequest, RoleChange

router = APIRouter()


@router.get("/api/me")
def me(user=Depends(sec.current_user)):
    return service.me(user)


@router.post("/api/orgs")
def create_org(payload: OrgCreateRequest, user=Depends(sec.current_user)):
    return service.create_org(user, payload)


@router.get("/api/orgs/{org_id}/members")
def list_members(org_id: str, user=Depends(sec.current_user)):
    return service.list_members(require_user(user), org_id)


@router.patch("/api/orgs/{org_id}/members/{member_id}")
def change_role(org_id: str, member_id: str, payload: RoleChange, user=Depends(sec.current_user)):
    return service.change_role(require_user(user), org_id, member_id, payload)


@router.delete("/api/orgs/{org_id}/members/{member_id}")
def remove_member(org_id: str, member_id: str, user=Depends(sec.current_user)):
    return service.remove_member(require_user(user), org_id, member_id)


@router.get("/api/orgs/{org_id}/invitations")
def list_invitations(org_id: str, user=Depends(sec.current_user)):
    return service.list_invitations(require_user(user), org_id)


@router.post("/api/orgs/{org_id}/invitations")
def create_invitation(org_id: str, payload: InviteCreate, user=Depends(sec.current_user)):
    return service.create_invitation(require_user(user), org_id, payload)


@router.delete("/api/orgs/{org_id}/invitations/{invitation_id}")
def revoke_invitation(org_id: str, invitation_id: str, user=Depends(sec.current_user)):
    return service.revoke_invitation(require_user(user), org_id, invitation_id)


@router.post("/api/invitations/accept")
def accept_invitation(payload: InviteAccept, user=Depends(sec.current_user)):
    return service.accept_invitation(require_user(user), payload)
