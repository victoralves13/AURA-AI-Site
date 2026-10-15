"""AURA AI — membros, papéis e convites das organizações (regras).

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
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

from aura.core import security as sec
from aura.core.errors import AppError
from aura.features.orgs import repository
from aura.features.orgs.schemas import InviteAccept, InviteCreate, OrgCreateRequest, RoleChange

ROLES = ("admin", "manager", "member")
EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]+\.[^@\s]{2,}$")
INVITE_TTL_DAYS = 7
MAX_PENDING_INVITES = 50


def _uuid(value: str, what: str) -> str:
    if not sec.UUID_RE.match(value or ""):
        raise AppError(400, f"{what} inválido.")
    return value.lower()


def _role(value: str) -> str:
    if value not in ROLES:
        raise AppError(400, "Papel inválido. Use admin, manager ou member.")
    return value


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%S+00:00")


def _parse(value: str | None) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _require_manage(user: sec.AuthUser, org_id: str) -> None:
    sec.require_org_permission(user, org_id, "members.manage")


def _clean_name(value) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


# --- conta e organizações ------------------------------------------------------------------------------------------
def me(user) -> dict:
    if user is None:
        return {"ok": True, "auth_required": False, "user": None, "organizations": []}
    rows, access = repository.user_organizations(user)
    orgs = [{"id": r["org_id"], "name": (r.get("organizations") or {}).get("name"), "role": r.get("role"),
             "permissions": sorted(access.get(r["org_id"], []))} for r in rows]
    return {"ok": True, "auth_required": True, "user": {"id": user.id, "email": user.email, "email_confirmed": user.email_confirmed}, "organizations": orgs}


def create_org(user, payload: OrgCreateRequest) -> dict:
    if user is None:
        raise AppError(401, "Autenticação necessária para criar organizações.")
    name = _clean_name(payload.name)
    if not 1 <= len(name) <= 120:
        raise AppError(400, "O nome da organização deve ter entre 1 e 120 caracteres.")
    org_id = repository.create_organization_with_admin(name, user.id)
    sec.audit(user, "org.create", org_id, "organization", org_id)
    return {"ok": True, "organization": {"id": org_id, "name": name, "role": "admin"}}


# --- membros -----------------------------------------------------------------------------------------------------
def list_members(user, org_id: str) -> dict:
    org_id = _uuid(org_id, "Organização")
    _require_manage(user, org_id)
    return {"ok": True, "members": [
        {"user_id": r["user_id"], "email": repository.member_email(r["user_id"]), "role": r["role"],
         "created_at": r.get("created_at"), "is_you": r["user_id"] == user.id}
        for r in repository.list_members(org_id)
    ]}


def change_role(user, org_id: str, member_id: str, payload: RoleChange) -> dict:
    org_id, member_id = _uuid(org_id, "Organização"), _uuid(member_id, "Membro")
    _require_manage(user, org_id)
    role = _role(payload.role)
    target = repository.get_membership(org_id, member_id)
    if not target:
        raise AppError(404, "Membro não encontrado nesta organização.")
    if target["role"] == "admin" and role != "admin" and repository.count_admins(org_id) <= 1:
        raise AppError(409, "A organização precisa de pelo menos um administrador.")
    if target["role"] != role:
        repository.set_role(org_id, member_id, role)
        sec.audit(user, "org.member.role", org_id, "membership", member_id, {"from": target["role"], "to": role})
    return {"ok": True, "member": {"user_id": member_id, "role": role}}


def remove_member(user, org_id: str, member_id: str) -> dict:
    org_id, member_id = _uuid(org_id, "Organização"), _uuid(member_id, "Membro")
    leaving = member_id == user.id
    if leaving:
        if not repository.get_membership(org_id, user.id):
            raise AppError(404, "Você não participa desta organização.")
    else:
        _require_manage(user, org_id)
    target = repository.get_membership(org_id, member_id)
    if not target:
        raise AppError(404, "Membro não encontrado nesta organização.")
    if target["role"] == "admin" and repository.count_admins(org_id) <= 1:
        raise AppError(409, "A organização precisa de pelo menos um administrador. Promova outra pessoa antes.")
    repository.delete_membership(org_id, member_id)
    sec.audit(user, "org.member.leave" if leaving else "org.member.remove", org_id, "membership", member_id, {"role": target["role"]})
    return {"ok": True}


# --- convites ----------------------------------------------------------------------------------------------------
def list_invitations(user, org_id: str) -> dict:
    org_id = _uuid(org_id, "Organização")
    _require_manage(user, org_id)
    now = _now()
    return {"ok": True, "invitations": [
        {**r, "expired": bool((_parse(r.get("expires_at")) or now) < now)} for r in repository.list_open_invitations(org_id)
    ]}


def create_invitation(user, org_id: str, payload: InviteCreate) -> dict:
    org_id = _uuid(org_id, "Organização")
    _require_manage(user, org_id)
    email = (payload.email or "").strip().lower()
    if len(email) > 254 or not EMAIL_RE.match(email):
        raise AppError(400, "Informe um e-mail válido.")
    role = _role(payload.role)
    now = _now()
    if repository.count_valid_invitations(org_id, quote(_iso(now), safe=""), MAX_PENDING_INVITES + 1) >= MAX_PENDING_INVITES:
        raise AppError(429, "Há convites pendentes demais. Revogue alguns antes de criar novos.")
    # Um convite pendente por e-mail: o novo substitui (e invalida) o anterior.
    repository.delete_open_invitations_for_email(org_id, quote(email, safe=""))
    token = secrets.token_urlsafe(32)
    expires = now + timedelta(days=INVITE_TTL_DAYS)
    inv_id = repository.insert_invitation({"org_id": org_id, "email": email, "role": role, "token_hash": _hash(token),
                                           "invited_by": user.id, "expires_at": _iso(expires)})
    sec.audit(user, "org.invite.create", org_id, "invitation", inv_id, {"role": role})
    return {"ok": True, "invitation": {"id": inv_id, "email": email, "role": role, "expires_at": _iso(expires)}, "token": token}


def revoke_invitation(user, org_id: str, invitation_id: str) -> dict:
    org_id, invitation_id = _uuid(org_id, "Organização"), _uuid(invitation_id, "Convite")
    _require_manage(user, org_id)
    repository.delete_open_invitation(org_id, invitation_id)
    sec.audit(user, "org.invite.revoke", org_id, "invitation", invitation_id)
    return {"ok": True}


def accept_invitation(user, payload: InviteAccept) -> dict:
    if not user.email_confirmed:
        raise AppError(403, "Confirme seu e-mail antes de aceitar o convite.")
    token = (payload.token or "").strip()
    if not 20 <= len(token) <= 200:
        raise AppError(400, "Convite inválido.")
    inv = repository.get_invitation_by_hash(_hash(token))
    if not inv or inv.get("accepted_at"):
        raise AppError(404, "Convite inválido ou já utilizado.")
    expires = _parse(inv.get("expires_at"))
    if expires is None or expires < _now():
        raise AppError(410, "Este convite expirou. Peça um novo ao administrador.")
    if (inv.get("email") or "").strip().lower() != (user.email or "").strip().lower():
        raise AppError(403, "Este convite foi enviado para outro e-mail.")
    if not repository.claim_invitation(inv["id"], _iso(_now())):
        raise AppError(409, "Este convite já foi utilizado.")
    org_id = inv["org_id"]
    existing = repository.get_membership(org_id, user.id)
    role = existing["role"] if existing else inv["role"]
    if not existing:
        try:
            repository.insert_membership(org_id, user.id, inv["role"])
        except AppError:
            repository.release_invitation(inv["id"])  # desfaz a reivindicação
            raise
    org = repository.get_organization(org_id)
    sec.audit(user, "org.invite.accept", org_id, "invitation", inv["id"], {"role": role, "already_member": bool(existing)})
    return {"ok": True, "organization": {"id": org_id, "name": org.get("name"), "role": role}}
