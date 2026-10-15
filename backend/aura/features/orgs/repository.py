"""Organizações — acesso aos dados (PostgREST com a chave de serviço, depois de o serviço conferir quem pode o quê)."""
from __future__ import annotations

import time

from aura.core import security as sec
from aura.core.errors import AppError

GENERIC = "Não foi possível concluir a operação. Tente novamente."
_EMAIL_TTL = 300.0
_email_cache: dict[str, tuple[float, str | None]] = {}


def _svc(method: str, path: str, payload=None):
    try:
        return sec.service_rest(method, path, payload)
    except RuntimeError as exc:
        raise AppError(502, GENERIC) from exc


# --- membros ---------------------------------------------------------------------------------------------------------
def get_membership(org_id: str, user_id: str) -> dict | None:
    rows = _svc("GET", f"memberships?select=user_id,role&org_id=eq.{org_id}&user_id=eq.{user_id}&limit=1") or []
    return rows[0] if rows else None


def count_admins(org_id: str) -> int:
    return len(_svc("GET", f"memberships?select=user_id&org_id=eq.{org_id}&role=eq.admin&limit=2") or [])


def list_members(org_id: str) -> list[dict]:
    return _svc("GET", f"memberships?select=user_id,role,created_at&org_id=eq.{org_id}&order=created_at.asc&limit=200") or []


def set_role(org_id: str, user_id: str, role: str) -> None:
    _svc("PATCH", f"memberships?org_id=eq.{org_id}&user_id=eq.{user_id}", {"role": role})


def delete_membership(org_id: str, user_id: str) -> None:
    _svc("DELETE", f"memberships?org_id=eq.{org_id}&user_id=eq.{user_id}")


def insert_membership(org_id: str, user_id: str, role: str) -> None:
    _svc("POST", "memberships", {"org_id": org_id, "user_id": user_id, "role": role})


def member_email(user_id: str) -> str | None:
    """E-mail de um membro pela API administrativa do Auth (com cache curto); nunca falha a chamada por causa disso."""
    hit = _email_cache.get(user_id)
    if hit and hit[0] > time.monotonic():
        return hit[1]
    email = None
    key = sec.service_key()
    try:
        status, body = sec.http_json("GET", f"{sec.supabase_url()}/auth/v1/admin/users/{user_id}",
                                     {"apikey": key, "Authorization": f"Bearer {key}"})
        if status == 200 and isinstance(body, dict):
            email = body.get("email")
    except RuntimeError:
        pass
    _email_cache[user_id] = (time.monotonic() + _EMAIL_TTL, email)
    return email


# --- convites --------------------------------------------------------------------------------------------------------
def list_open_invitations(org_id: str) -> list[dict]:
    return _svc("GET", f"invitations?select=id,email,role,expires_at,created_at&org_id=eq.{org_id}&accepted_at=is.null&order=created_at.desc&limit=100") or []


def count_valid_invitations(org_id: str, now_iso_quoted: str, limit: int) -> int:
    return len(_svc("GET", f"invitations?select=id&org_id=eq.{org_id}&accepted_at=is.null&expires_at=gt.{now_iso_quoted}&limit={limit}") or [])


def delete_open_invitations_for_email(org_id: str, email_quoted: str) -> None:
    _svc("DELETE", f"invitations?org_id=eq.{org_id}&email=eq.{email_quoted}&accepted_at=is.null")


def insert_invitation(row: dict) -> str | None:
    rows = _svc("POST", "invitations", row)
    return rows[0]["id"] if rows else None


def delete_open_invitation(org_id: str, invitation_id: str) -> None:
    _svc("DELETE", f"invitations?id=eq.{invitation_id}&org_id=eq.{org_id}&accepted_at=is.null")


def get_invitation_by_hash(token_hash: str) -> dict | None:
    rows = _svc("GET", f"invitations?select=*&token_hash=eq.{token_hash}&limit=1") or []
    return rows[0] if rows else None


def claim_invitation(invitation_id: str, accepted_at: str) -> bool:
    """Reivindica de forma atômica: só uma requisição consegue (accepted_at precisa estar nulo)."""
    return bool(_svc("PATCH", f"invitations?id=eq.{invitation_id}&accepted_at=is.null", {"accepted_at": accepted_at}))


def release_invitation(invitation_id: str) -> None:
    _svc("PATCH", f"invitations?id=eq.{invitation_id}", {"accepted_at": None})


# --- organizações ----------------------------------------------------------------------------------------------------
def get_organization(org_id: str) -> dict:
    return (_svc("GET", f"organizations?select=id,name&id=eq.{org_id}&limit=1") or [{}])[0]


def create_organization_with_admin(name: str, user_id: str) -> str:
    """Cria a organização e o vínculo de administrador; se o vínculo falhar, desfaz a organização."""
    try:
        org_id = sec.service_rest("POST", "organizations", {"name": name, "created_by": user_id})[0]["id"]
        try:
            sec.service_rest("POST", "memberships", {"org_id": org_id, "user_id": user_id, "role": "admin"})
        except Exception:
            sec.service_rest("DELETE", f"organizations?id=eq.{org_id}")
            raise
    except Exception as exc:
        raise AppError(502, "Não foi possível criar a organização.") from exc
    return org_id


def user_organizations(user) -> tuple[list[dict], dict]:
    """Vínculos da pessoa (com o nome da organização) e as permissões efetivas, lidos com o JWT dela."""
    try:
        rows = sec.user_rest(user, "GET", f"memberships?select=role,org_id,organizations(id,name)&user_id=eq.{user.id}") or []
        access = sec.load_access(user)
    except RuntimeError as exc:
        raise AppError(502, "Não foi possível carregar suas organizações.") from exc
    return rows, access
