"""AURA AI — membros, papéis e convites das organizações.

Regras:
  * Toda operação exige login e é autorizada pelo papel do usuário NA organização do caminho
    (permissões carregadas sob RLS com o JWT dele; o identificador vem da URL e é validado).
  * Só administradores (members.manage) listam membros, mudam papéis, removem pessoas e convidam.
    Qualquer membro pode sair da própria organização.
  * Nunca fica uma organização sem administrador.
  * Convite: o token (32 bytes aleatórios) só existe no momento da criação; no banco fica apenas o
    hash. Vale 7 dias, é de uso único e só pode ser aceito por quem tem o e-mail convidado e
    confirmado. Não há envio de e-mail: o administrador compartilha o link.
  * Auditoria sem e-mails nem conteúdo.
"""
from __future__ import annotations

import hashlib
import re
import secrets
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

import security as sec

router = APIRouter()

ROLES = ("admin", "manager", "member")
EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]+\.[^@\s]{2,}$")
INVITE_TTL_DAYS = 7
MAX_PENDING_INVITES = 50
_EMAIL_TTL = 300.0
_email_cache: dict[str, tuple[float, str | None]] = {}


class InviteCreate(BaseModel):
    email: str
    role: str = "member"


class RoleChange(BaseModel):
    role: str


class InviteAccept(BaseModel):
    token: str


# ---------------------------------------------------------------------------
def _need_user(user: sec.AuthUser | None) -> sec.AuthUser:
    if user is None:
        raise HTTPException(status_code=401, detail="Autenticação necessária.")
    return user


def _uuid(value: str, what: str) -> str:
    if not sec.UUID_RE.match(value or ""):
        raise HTTPException(status_code=400, detail=f"{what} inválido.")
    return value.lower()


def _role(value: str) -> str:
    if value not in ROLES:
        raise HTTPException(status_code=400, detail="Papel inválido. Use admin, manager ou member.")
    return value


def _svc(method: str, path: str, payload=None):
    try:
        return sec.service_rest(method, path, payload)
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail="Não foi possível concluir a operação. Tente novamente.") from exc


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%S+00:00")


def _parse(value: str | None) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def _membership(org_id: str, user_id: str) -> dict | None:
    rows = _svc("GET", f"memberships?select=user_id,role&org_id=eq.{org_id}&user_id=eq.{user_id}&limit=1") or []
    return rows[0] if rows else None


def _admin_count(org_id: str) -> int:
    return len(_svc("GET", f"memberships?select=user_id&org_id=eq.{org_id}&role=eq.admin&limit=2") or [])


def _member_email(user_id: str) -> str | None:
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


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _require_manage(user: sec.AuthUser, org_id: str) -> None:
    sec.require_org_permission(user, org_id, "members.manage")


# ---------------------------------------------------------------------------
# Membros
# ---------------------------------------------------------------------------
@router.get("/api/orgs/{org_id}/members")
def list_members(org_id: str, user=Depends(sec.current_user)):
    user = _need_user(user)
    org_id = _uuid(org_id, "Organização")
    _require_manage(user, org_id)
    rows = _svc("GET", f"memberships?select=user_id,role,created_at&org_id=eq.{org_id}&order=created_at.asc&limit=200") or []
    return {"ok": True, "members": [
        {"user_id": r["user_id"], "email": _member_email(r["user_id"]), "role": r["role"],
         "created_at": r.get("created_at"), "is_you": r["user_id"] == user.id}
        for r in rows
    ]}


@router.patch("/api/orgs/{org_id}/members/{member_id}")
def change_role(org_id: str, member_id: str, payload: RoleChange, user=Depends(sec.current_user)):
    user = _need_user(user)
    org_id, member_id = _uuid(org_id, "Organização"), _uuid(member_id, "Membro")
    _require_manage(user, org_id)
    role = _role(payload.role)
    target = _membership(org_id, member_id)
    if not target:
        raise HTTPException(status_code=404, detail="Membro não encontrado nesta organização.")
    if target["role"] == "admin" and role != "admin" and _admin_count(org_id) <= 1:
        raise HTTPException(status_code=409, detail="A organização precisa de pelo menos um administrador.")
    if target["role"] != role:
        _svc("PATCH", f"memberships?org_id=eq.{org_id}&user_id=eq.{member_id}", {"role": role})
        sec.audit(user, "org.member.role", org_id, "membership", member_id, {"from": target["role"], "to": role})
    return {"ok": True, "member": {"user_id": member_id, "role": role}}


@router.delete("/api/orgs/{org_id}/members/{member_id}")
def remove_member(org_id: str, member_id: str, user=Depends(sec.current_user)):
    user = _need_user(user)
    org_id, member_id = _uuid(org_id, "Organização"), _uuid(member_id, "Membro")
    leaving = member_id == user.id
    if leaving:
        if not _membership(org_id, user.id):
            raise HTTPException(status_code=404, detail="Você não participa desta organização.")
    else:
        _require_manage(user, org_id)
    target = _membership(org_id, member_id)
    if not target:
        raise HTTPException(status_code=404, detail="Membro não encontrado nesta organização.")
    if target["role"] == "admin" and _admin_count(org_id) <= 1:
        raise HTTPException(status_code=409, detail="A organização precisa de pelo menos um administrador. Promova outra pessoa antes.")
    _svc("DELETE", f"memberships?org_id=eq.{org_id}&user_id=eq.{member_id}")
    sec.audit(user, "org.member.leave" if leaving else "org.member.remove", org_id, "membership", member_id, {"role": target["role"]})
    return {"ok": True}


# ---------------------------------------------------------------------------
# Convites
# ---------------------------------------------------------------------------
@router.get("/api/orgs/{org_id}/invitations")
def list_invitations(org_id: str, user=Depends(sec.current_user)):
    user = _need_user(user)
    org_id = _uuid(org_id, "Organização")
    _require_manage(user, org_id)
    rows = _svc("GET", f"invitations?select=id,email,role,expires_at,created_at&org_id=eq.{org_id}&accepted_at=is.null&order=created_at.desc&limit=100") or []
    now = _now()
    return {"ok": True, "invitations": [
        {**r, "expired": bool((_parse(r.get("expires_at")) or now) < now)} for r in rows
    ]}


@router.post("/api/orgs/{org_id}/invitations")
def create_invitation(org_id: str, payload: InviteCreate, user=Depends(sec.current_user)):
    user = _need_user(user)
    org_id = _uuid(org_id, "Organização")
    _require_manage(user, org_id)
    email = (payload.email or "").strip().lower()
    if len(email) > 254 or not EMAIL_RE.match(email):
        raise HTTPException(status_code=400, detail="Informe um e-mail válido.")
    role = _role(payload.role)
    now = _now()
    pending = _svc("GET", f"invitations?select=id&org_id=eq.{org_id}&accepted_at=is.null&expires_at=gt.{quote(_iso(now), safe='')}&limit={MAX_PENDING_INVITES + 1}") or []
    if len(pending) >= MAX_PENDING_INVITES:
        raise HTTPException(status_code=429, detail="Há convites pendentes demais. Revogue alguns antes de criar novos.")
    # Um convite pendente por e-mail: o novo substitui (e invalida) o anterior.
    _svc("DELETE", f"invitations?org_id=eq.{org_id}&email=eq.{quote(email, safe='')}&accepted_at=is.null")
    token = secrets.token_urlsafe(32)
    expires = now + timedelta(days=INVITE_TTL_DAYS)
    rows = _svc("POST", "invitations", {"org_id": org_id, "email": email, "role": role, "token_hash": _hash(token),
                                        "invited_by": user.id, "expires_at": _iso(expires)})
    inv_id = rows[0]["id"] if rows else None
    sec.audit(user, "org.invite.create", org_id, "invitation", inv_id, {"role": role})
    return {"ok": True, "invitation": {"id": inv_id, "email": email, "role": role, "expires_at": _iso(expires)}, "token": token}


@router.delete("/api/orgs/{org_id}/invitations/{invitation_id}")
def revoke_invitation(org_id: str, invitation_id: str, user=Depends(sec.current_user)):
    user = _need_user(user)
    org_id, invitation_id = _uuid(org_id, "Organização"), _uuid(invitation_id, "Convite")
    _require_manage(user, org_id)
    _svc("DELETE", f"invitations?id=eq.{invitation_id}&org_id=eq.{org_id}&accepted_at=is.null")
    sec.audit(user, "org.invite.revoke", org_id, "invitation", invitation_id)
    return {"ok": True}


@router.post("/api/invitations/accept")
def accept_invitation(payload: InviteAccept, user=Depends(sec.current_user)):
    user = _need_user(user)
    if not user.email_confirmed:
        raise HTTPException(status_code=403, detail="Confirme seu e-mail antes de aceitar o convite.")
    token = (payload.token or "").strip()
    if not 20 <= len(token) <= 200:
        raise HTTPException(status_code=400, detail="Convite inválido.")
    rows = _svc("GET", f"invitations?select=*&token_hash=eq.{_hash(token)}&limit=1") or []
    inv = rows[0] if rows else None
    if not inv or inv.get("accepted_at"):
        raise HTTPException(status_code=404, detail="Convite inválido ou já utilizado.")
    expires = _parse(inv.get("expires_at"))
    if expires is None or expires < _now():
        raise HTTPException(status_code=410, detail="Este convite expirou. Peça um novo ao administrador.")
    if (inv.get("email") or "").strip().lower() != (user.email or "").strip().lower():
        raise HTTPException(status_code=403, detail="Este convite foi enviado para outro e-mail.")
    # Reivindica o convite de forma atômica (só uma requisição consegue: accepted_at precisa estar nulo).
    claimed = _svc("PATCH", f"invitations?id=eq.{inv['id']}&accepted_at=is.null", {"accepted_at": _iso(_now())}) or []
    if not claimed:
        raise HTTPException(status_code=409, detail="Este convite já foi utilizado.")
    org_id = inv["org_id"]
    existing = _membership(org_id, user.id)
    role = existing["role"] if existing else inv["role"]
    if not existing:
        try:
            _svc("POST", "memberships", {"org_id": org_id, "user_id": user.id, "role": inv["role"]})
        except HTTPException:
            _svc("PATCH", f"invitations?id=eq.{inv['id']}", {"accepted_at": None})  # desfaz a reivindicação
            raise
    org = (_svc("GET", f"organizations?select=id,name&id=eq.{org_id}&limit=1") or [{}])[0]
    sec.audit(user, "org.invite.accept", org_id, "invitation", inv["id"], {"role": role, "already_member": bool(existing)})
    return {"ok": True, "organization": {"id": org_id, "name": org.get("name"), "role": role}}
