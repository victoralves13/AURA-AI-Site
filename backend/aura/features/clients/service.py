"""AURA AI — clientes como entidade: vínculo reunião-cliente, edição e fusão reversível (regras).

A correspondência de nomes está em `matching.py` (regra pura). Aqui ficam o vínculo de uma reunião nova e os casos de uso da API.
Nada é fundido nem criado a partir do que a IA diz sem uma pessoa confirmar. Falha ao vincular nunca impede a análise: a reunião é
salva sem vínculo.
"""
from __future__ import annotations

import logging

from aura.core import security as sec
from aura.core.errors import AppError
from aura.features.clients import repository
from aura.features.clients.matching import is_placeholder, match_client, normalize_name
from aura.features.clients.schemas import ClientCreate, ClientUpdate, LinkChange, MergeRequest

log = logging.getLogger("aura.clients")

FORBIDDEN = repository.FORBIDDEN
MERGED = "Este cliente foi fundido em outro e não aceita novos vínculos."
SCOPE_MISMATCH = "O cliente precisa ser do mesmo espaço (organização ou conta pessoal) da reunião."


def scope_filter(user: sec.AuthUser, org_id: str | None) -> str:
    return repository.scope_filter(user, org_id)


def clean_group(value) -> str | None:
    """Grupo do cliente: texto curto sem espaços sobrando; vazio = sem grupo."""
    text = " ".join(str(value or "").split())
    if len(text) > 120:
        raise AppError(400, "O nome do grupo deve ter até 120 caracteres.")
    return text or None


def create_client(user: sec.AuthUser, org_id: str | None, name: str, via: str = "user", aliases: list[str] | None = None,
                  group_name: str | None = None) -> dict:
    row = {"org_id": org_id, "owner_id": user.id, "name": name.strip()[:200], "normalized_name": normalize_name(name),
           "created_via": via, "aliases": aliases or []}
    if group_name:
        row["group_name"] = group_name
    return repository.insert_client(user, row)


def _suggestion(matches: list[tuple[dict, float]], proposal: str | None) -> list[dict]:
    out = [{"kind": "existing", "client_id": c["id"], "name": c["name"], "score": s} for c, s in matches]
    if proposal:
        out.append({"kind": "new", "name": proposal[:200]})
    return out


def groups_by_client(user: sec.AuthUser, org_id: str | None) -> dict[str, str]:
    """{id do cliente: grupo} do espaço, para o chat. Vazio se o banco ainda não tem a coluna ou a leitura falhar (o chat segue sem grupos)."""
    try:
        return {c["id"]: c["group_name"] for c in repository.list_scope_clients(user, org_id) if c.get("group_name")}
    except (AppError, RuntimeError) as exc:
        log.warning("grupos dos clientes indisponíveis: %s", exc)
        return {}


def resolve_chosen(user: sec.AuthUser, org_id: str | None, client_id: str | None) -> dict | None:
    """Cliente que a pessoa ESCOLHEU na Nova análise: precisa existir, ser visível para ela, do mesmo espaço da reunião e não estar fundido.
    Levanta AppError com o motivo (a análise ainda não gastou IA quando isto é chamado)."""
    if not client_id:
        return None
    cid = _uuid(client_id, "Cliente")
    client = repository.get_client(user, cid)
    if client is None:
        raise AppError(404, "Cliente não encontrado.")
    if client.get("merged_into"):
        raise AppError(409, MERGED)
    if client.get("org_id") != org_id or (org_id is None and client.get("owner_id") != user.id):
        raise AppError(409, SCOPE_MISMATCH)
    return client


def apply_group(user: sec.AuthUser, client: dict | None, group_name: str | None) -> bool:
    """Grava o grupo no cliente quando a pessoa informou e ele é diferente. Falhar aqui nunca perde a análise. Retorna se o grupo ficou salvo."""
    if not client or not group_name:
        return False
    if (client.get("group_name") or "") == group_name:
        return True
    if not repository.groups_supported():
        return False
    try:
        if client.get("org_id"):
            sec.require_org_permission(user, client["org_id"], "clients.write")
        row = repository.patch_client(user, client["id"], {"group_name": group_name})
        return bool(row) and repository.groups_supported() and row.get("group_name") == group_name
    except (AppError, RuntimeError) as exc:
        log.warning("grupo do cliente não salvo: %s", exc)
        return False


def link_for_new_meeting(user: sec.AuthUser | None, org_id: str | None, typed: str | None, ai_name: str | None,
                         is_demo: bool = False, chosen: dict | None = None, group_name: str | None = None) -> dict:
    """Decide o vínculo de uma reunião recém-analisada (ver as regras em matching.py).

    `chosen` é o cliente que a pessoa escolheu no formulário (já validado por resolve_chosen): vale sem adivinhar nada."""
    none = {"client_id": None, "client_link": "unlinked", "client_suggestion": []}
    if user is None or is_demo:
        return none
    if chosen:
        saved = apply_group(user, chosen, group_name)
        return {"client_id": chosen["id"], "client_link": "confirmed", "client_suggestion": [], "client_group_saved": saved if group_name else None}
    name = (typed or "").strip() or (ai_name or "").strip()
    if is_placeholder(name):
        return none
    try:
        match = match_client(name, repository.list_scope_clients(user, org_id))
        found = match["matches"]
        if match["kind"] == "exact" and len(found) == 1:
            hit = found[0][0]
            saved = apply_group(user, hit, group_name) if typed else None
            return {"client_id": hit["id"], "client_link": "confirmed" if typed else "auto", "client_suggestion": [],
                    "client_group_saved": saved if (typed and group_name) else None}
        if match["kind"] in ("exact", "similar"):  # ambíguo ou parecido: nunca decide sozinho
            return {"client_id": None, "client_link": "suggested", "client_suggestion": _suggestion(found, name)}
        if typed:
            created = create_client(user, org_id, name, "user", group_name=group_name)
            sec.audit(user, "client.create", org_id, "client", created.get("id"), {"via": "user"})
            return {"client_id": created["id"], "client_link": "confirmed", "client_suggestion": [],
                    "client_group_saved": (created.get("group_name") == group_name) if group_name else None}
        return {"client_id": None, "client_link": "suggested", "client_suggestion": _suggestion([], name)}
    except RuntimeError as exc:  # inclui falhas do banco: a análise nunca é perdida por causa do vínculo
        log.warning("vínculo de cliente não realizado: %s", exc)
        return none


# ---------------------------------------------------------------------------
# Casos de uso da API
# ---------------------------------------------------------------------------
def _uuid(value: str | None, what: str) -> str:
    if not value or not sec.UUID_RE.match(value):
        raise AppError(400, f"{what} inválido.")
    return value.lower()


def _scope(user: sec.AuthUser, org_id: str | None, permission: str) -> str | None:
    """'personal'/vazio -> conta pessoal (None); uuid -> organização, com a permissão pedida."""
    if not org_id or org_id == "personal":
        return None
    org_id = _uuid(org_id, "Espaço")
    sec.require_org_permission(user, org_id, permission)
    return org_id


def _clean_aliases(aliases: list[str] | None, own_name: str) -> list[str]:
    seen, out = {normalize_name(own_name)}, []
    for raw in (aliases or [])[:20]:
        a = (raw or "").strip()[:200]
        n = normalize_name(a)
        if a and n and n not in seen:
            seen.add(n)
            out.append(a)
    return out


def _get_client(user: sec.AuthUser, client_id: str) -> dict:
    client = repository.get_client(user, client_id)
    if client is None:
        raise AppError(404, "Cliente não encontrado.")
    return client


def list_clients(user, org_id: str | None) -> dict:
    org = _scope(user, org_id, "clients.read")
    where = scope_filter(user, org)
    clients = repository.list_clients(user, where)
    linked = repository.linked_meeting_rows(user, where)
    pending = repository.pending_suggestion_rows(user, where)
    counts: dict[str, int] = {}
    for row in linked:
        counts[row["client_id"]] = counts.get(row["client_id"], 0) + 1
    return {"ok": True, "pending_suggestions": len(pending), "clients": [{**c, "meetings": counts.get(c["id"], 0)} for c in clients]}


def create(user, payload: ClientCreate) -> dict:
    org = _scope(user, payload.org_id, "clients.write")
    name = " ".join((payload.name or "").split())
    if not 1 <= len(name) <= 200 or not normalize_name(name):
        raise AppError(400, "O nome do cliente deve ter entre 1 e 200 caracteres.")
    group = clean_group(payload.group_name)
    row_in = {"org_id": org, "owner_id": user.id, "name": name[:200], "normalized_name": normalize_name(name), "created_via": "user",
              "aliases": _clean_aliases(payload.aliases, name)}
    if group:
        row_in["group_name"] = group
    row = repository.insert_client_guarded(user, row_in)
    sec.audit(user, "client.create", org, "client", row.get("id"), {"via": "user"})
    return {"ok": True, "client": row}


def get_one(user, client_id: str) -> dict:
    client_id = _uuid(client_id, "Cliente")
    client = _get_client(user, client_id)
    return {"ok": True, "client": client, "meetings": repository.client_meetings(user, client_id)}


def update(user, client_id: str, payload: ClientUpdate) -> dict:
    client_id = _uuid(client_id, "Cliente")
    client = _get_client(user, client_id)
    if client.get("org_id"):
        sec.require_org_permission(user, client["org_id"], "clients.write")
    if client.get("merged_into"):
        raise AppError(409, MERGED)
    changes: dict = {}
    name = client["name"]
    if payload.name is not None:
        name = " ".join(payload.name.split())
        if not 1 <= len(name) <= 200 or not normalize_name(name):
            raise AppError(400, "O nome do cliente deve ter entre 1 e 200 caracteres.")
        changes.update(name=name, normalized_name=normalize_name(name))
    if payload.aliases is not None or payload.name is not None:
        changes["aliases"] = _clean_aliases(payload.aliases if payload.aliases is not None else client.get("aliases"), name)
    if payload.group_name is not None:
        changes["group_name"] = clean_group(payload.group_name)
    if not changes:
        return {"ok": True, "client": client}
    row = repository.patch_client(user, client_id, changes)
    if row is None:
        raise AppError(403, FORBIDDEN)
    sec.audit(user, "client.update", client.get("org_id"), "client", client_id, {"fields": sorted(changes)})
    return {"ok": True, "client": row}


def change_link(user, meeting_id: str, payload: LinkChange) -> dict:
    meeting_id = _uuid(meeting_id, "Reunião")
    meeting = repository.get_meeting_scope(user, meeting_id)
    if meeting is None:
        raise AppError(404, "Reunião não encontrada.")
    org = meeting.get("org_id")
    action = payload.action
    if action == "unlink":
        change = {"client_id": None, "client_link": "unlinked", "client_suggestion": []}
    elif action in ("confirm", "set"):
        client = _get_client(user, _uuid(payload.client_id, "Cliente"))
        if client.get("merged_into"):
            raise AppError(409, MERGED)
        if client.get("org_id") != org or (org is None and client.get("owner_id") != meeting.get("owner_id")):
            raise AppError(409, SCOPE_MISMATCH)
        change = {"client_id": client["id"], "client_link": "confirmed", "client_suggestion": []}
    elif action == "create":
        name = " ".join((payload.name or "").split())
        if not 1 <= len(name) <= 200 or not normalize_name(name):
            raise AppError(400, "Informe o nome do novo cliente (até 200 caracteres).")
        if org:
            sec.require_org_permission(user, org, "clients.write")
        created = repository.insert_client_guarded(user, {"org_id": org, "owner_id": user.id, "name": name[:200],
                                                          "normalized_name": normalize_name(name), "created_via": "user", "aliases": []})
        sec.audit(user, "client.create", org, "client", created.get("id"), {"via": "user"})
        change = {"client_id": created["id"], "client_link": "confirmed", "client_suggestion": []}
    else:
        raise AppError(400, "Ação inválida. Use confirm, set, create ou unlink.")
    if not repository.patch_meeting_link(user, meeting_id, change):
        raise AppError(403, "Você não pode alterar o cliente desta reunião.")
    sec.audit(user, "meeting.client_link", org, "meeting", meeting_id, {"action": action})
    return {"ok": True, "meeting": {"id": meeting_id, **change}}


def merge(user, client_id: str, payload: MergeRequest) -> dict:
    source, target = _uuid(client_id, "Cliente"), _uuid(payload.into, "Cliente de destino")
    result = repository.merge_clients(user, source, target)
    sec.audit(user, "client.merge", None, "client", source, {"into": target, "moved": result.get("moved")})
    return {"ok": True, **result}


def unmerge(user, client_id: str) -> dict:
    source = _uuid(client_id, "Cliente")
    result = repository.unmerge_clients(user, source)
    sec.audit(user, "client.unmerge", None, "client", source, {"restored": result.get("restored")})
    return {"ok": True, **result}
