"""AURA AI — clientes como entidade: vínculo reunião-cliente, edição e fusão reversível.

Regra de vínculo (determinística, sem IA, SEMPRE dentro do mesmo espaço: organização ou conta pessoal):
  * Nome digitado pela pessoa:  igual a um cliente/apelido -> vincula (confirmado);
                                parecido -> sugere e espera confirmação; sem correspondência -> cria o cliente.
  * Nome extraído pela IA:      igual a um cliente/apelido -> vincula (automático);
                                parecido ou ambíguo -> sugere; sem correspondência -> propõe criar e espera confirmação.
  * Sem nome (ou "Cliente não identificado"), reunião demo ou modo sem login -> sem vínculo.
Nada é fundido nem criado a partir do que a IA diz sem uma pessoa confirmar. Falha ao vincular nunca
impede a análise: a reunião é salva sem vínculo.
"""
from __future__ import annotations

import logging
import re
from difflib import SequenceMatcher

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

import security as sec
import verification

log = logging.getLogger("aura.clients")
router = APIRouter()

PLACEHOLDERS = {"cliente nao identificado", "nao identificado", "sem cliente", "desconhecido", "nao informado", "n a", "na"}
LEGAL_SUFFIXES = {"ltda", "eireli", "epp", "me", "sa"}
GENERIC = {"grupo", "empresa", "companhia", "cia", "cliente", "holding", "corporacao", "organizacao", "de", "do", "da", "dos", "das", "e"}
SIMILAR_MIN = 0.5      # similaridade mínima de palavras relevantes para sugerir
RATIO_MIN = 0.88       # similaridade mínima de texto para sugerir (erros de digitação)
MAX_CANDIDATES = 3
MAX_CLIENTS_SCANNED = 500


# ---------------------------------------------------------------------------
# Nomes e correspondência
# ---------------------------------------------------------------------------
def normalize_name(name: str) -> str:
    """Minúsculas, sem acento nem pontuação e sem sufixo societário (Ltda, S.A., ME…)."""
    tokens = verification.normalize(name).split()
    while tokens and tokens[-1] in LEGAL_SUFFIXES:
        tokens.pop()
    while len(tokens) >= 2 and tokens[-2:] == ["s", "a"]:
        tokens = tokens[:-2]
    return " ".join(tokens) or verification.normalize(name)


def is_placeholder(name: str | None) -> bool:
    n = verification.normalize(name or "")
    return not n or n in PLACEHOLDERS


def _meaningful(norm: str) -> set[str]:
    return {t for t in norm.split() if t not in GENERIC and len(t) > 1}


def similarity(a_norm: str, b_norm: str) -> float:
    """0..1 entre dois nomes normalizados (palavras relevantes, depois texto)."""
    ma, mb = _meaningful(a_norm), _meaningful(b_norm)
    if ma and mb:
        if ma == mb:
            return 0.95
        jaccard = len(ma & mb) / len(ma | mb)
        if jaccard >= SIMILAR_MIN and (ma <= mb or mb <= ma or jaccard >= 0.6):
            return round(jaccard, 2)
    ratio = SequenceMatcher(None, a_norm, b_norm).ratio()
    return round(ratio, 2) if ratio >= RATIO_MIN else 0.0


def match_client(name: str, clients: list[dict]) -> dict:
    """Retorna {"kind": "exact"|"similar"|"none", "matches": [(cliente, pontuação)]}."""
    norm = normalize_name(name)
    if is_placeholder(name) or not norm:
        return {"kind": "none", "matches": []}
    exact = [c for c in clients
             if c.get("normalized_name") == norm or norm in {normalize_name(a) for a in (c.get("aliases") or [])}]
    if exact:
        return {"kind": "exact", "matches": [(c, 1.0) for c in exact]}
    scored = sorted(((c, similarity(norm, c.get("normalized_name") or normalize_name(c.get("name", "")))) for c in clients),
                    key=lambda x: -x[1])
    scored = [(c, s) for c, s in scored if s > 0][:MAX_CANDIDATES]
    return {"kind": "similar" if scored else "none", "matches": scored}


# ---------------------------------------------------------------------------
# Acesso aos dados do espaço (sempre com o JWT do usuário: o RLS vale)
# ---------------------------------------------------------------------------
def scope_filter(user: sec.AuthUser, org_id: str | None) -> str:
    return f"org_id=eq.{org_id}" if org_id else f"org_id=is.null&owner_id=eq.{user.id}"


def list_scope_clients(user: sec.AuthUser, org_id: str | None) -> list[dict]:
    return sec.user_rest(user, "GET", f"clients?select=id,name,normalized_name,aliases&merged_into=is.null&{scope_filter(user, org_id)}"
                                      f"&order=name.asc&limit={MAX_CLIENTS_SCANNED}") or []


def create_client(user: sec.AuthUser, org_id: str | None, name: str, via: str = "user", aliases: list[str] | None = None) -> dict:
    row = {"org_id": org_id, "owner_id": user.id, "name": name.strip()[:200], "normalized_name": normalize_name(name),
           "created_via": via, "aliases": aliases or []}
    return (sec.user_rest(user, "POST", "clients", row) or [row])[0]


def _suggestion(matches: list[tuple[dict, float]], proposal: str | None) -> list[dict]:
    out = [{"kind": "existing", "client_id": c["id"], "name": c["name"], "score": s} for c, s in matches]
    if proposal:
        out.append({"kind": "new", "name": proposal[:200]})
    return out


def link_for_new_meeting(user: sec.AuthUser | None, org_id: str | None, typed: str | None, ai_name: str | None,
                         is_demo: bool = False) -> dict:
    """Decide o vínculo de uma reunião recém-analisada (ver as regras no topo do módulo)."""
    none = {"client_id": None, "client_link": "unlinked", "client_suggestion": []}
    if user is None or is_demo:
        return none
    name = (typed or "").strip() or (ai_name or "").strip()
    if is_placeholder(name):
        return none
    try:
        match = match_client(name, list_scope_clients(user, org_id))
        found = match["matches"]
        if match["kind"] == "exact" and len(found) == 1:
            return {"client_id": found[0][0]["id"], "client_link": "confirmed" if typed else "auto", "client_suggestion": []}
        if match["kind"] in ("exact", "similar"):  # ambíguo ou parecido: nunca decide sozinho
            return {"client_id": None, "client_link": "suggested", "client_suggestion": _suggestion(found, name)}
        if typed:
            created = create_client(user, org_id, name, "user")
            sec.audit(user, "client.create", org_id, "client", created.get("id"), {"via": "user"})
            return {"client_id": created["id"], "client_link": "confirmed", "client_suggestion": []}
        return {"client_id": None, "client_link": "suggested", "client_suggestion": _suggestion([], name)}
    except RuntimeError as exc:  # inclui falhas do banco: a análise nunca é perdida por causa do vínculo
        log.warning("vínculo de cliente não realizado: %s", exc)
        return none


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------
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


def _need_user(user):
    if user is None:
        raise HTTPException(status_code=401, detail="Autenticação necessária.")
    return user


def _uuid(value: str | None, what: str) -> str:
    if not value or not sec.UUID_RE.match(value):
        raise HTTPException(status_code=400, detail=f"{what} inválido.")
    return value.lower()


def _scope(user: sec.AuthUser, org_id: str | None, permission: str) -> str | None:
    """'personal'/vazio -> conta pessoal (None); uuid -> organização, com a permissão pedida."""
    if not org_id or org_id == "personal":
        return None
    org_id = _uuid(org_id, "Espaço")
    sec.require_org_permission(user, org_id, permission)
    return org_id


ERRORS = {
    "client_not_found": (404, "Cliente não encontrado."),
    "forbidden": (403, "Você não tem permissão para esta operação com clientes."),
    "same_client": (400, "Escolha dois clientes diferentes."),
    "client_scope_mismatch": (409, "O cliente precisa ser do mesmo espaço (organização ou conta pessoal) da reunião."),
    "already_merged": (409, "Um dos clientes já foi fundido em outro."),
    "not_merged": (409, "Este cliente não está fundido."),
    "client_merged": (409, "Este cliente foi fundido em outro e não aceita novos vínculos."),
}


def _db(call):
    """Executa uma chamada ao banco traduzindo o erro em resposta HTTP clara."""
    try:
        return call()
    except sec.SupabaseError as exc:
        if exc.db_message in ERRORS:
            status, detail = ERRORS[exc.db_message]
            raise HTTPException(status_code=status, detail=detail) from exc
        if exc.db_code == "23505":
            raise HTTPException(status_code=409, detail="Já existe um cliente com esse nome neste espaço.") from exc
        if exc.status in (401, 403):
            raise HTTPException(status_code=403, detail=ERRORS["forbidden"][1]) from exc
        raise HTTPException(status_code=502, detail="Não foi possível concluir a operação com clientes. Tente novamente.") from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail="Não foi possível concluir a operação com clientes. Tente novamente.") from exc


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
    rows = _db(lambda: sec.user_rest(user, "GET", f"clients?select=*&id=eq.{client_id}&limit=1")) or []
    if not rows:
        raise HTTPException(status_code=404, detail=ERRORS["client_not_found"][1])
    return rows[0]


@router.get("/api/clients")
def list_clients(org_id: str | None = None, user=Depends(sec.current_user)):
    user = _need_user(user)
    org = _scope(user, org_id, "clients.read")
    where = scope_filter(user, org)
    clients = _db(lambda: sec.user_rest(user, "GET", f"clients?select=id,name,aliases,created_via,created_at&merged_into=is.null&{where}&order=name.asc&limit=500")) or []
    linked = _db(lambda: sec.user_rest(user, "GET", f"meetings?select=client_id&client_id=not.is.null&{where}&limit=2000")) or []
    pending = _db(lambda: sec.user_rest(user, "GET", f"meetings?select=id&client_link=eq.suggested&{where}&limit=1000")) or []
    counts: dict[str, int] = {}
    for row in linked:
        counts[row["client_id"]] = counts.get(row["client_id"], 0) + 1
    return {"ok": True, "pending_suggestions": len(pending),
            "clients": [{**c, "meetings": counts.get(c["id"], 0)} for c in clients]}


@router.post("/api/clients")
def create(payload: ClientCreate, user=Depends(sec.current_user)):
    user = _need_user(user)
    org = _scope(user, payload.org_id, "clients.write")
    name = " ".join((payload.name or "").split())
    if not 1 <= len(name) <= 200 or not normalize_name(name):
        raise HTTPException(status_code=400, detail="O nome do cliente deve ter entre 1 e 200 caracteres.")
    row = _db(lambda: create_client(user, org, name, "user", _clean_aliases(payload.aliases, name)))
    sec.audit(user, "client.create", org, "client", row.get("id"), {"via": "user"})
    return {"ok": True, "client": row}


@router.get("/api/clients/{client_id}")
def get_one(client_id: str, user=Depends(sec.current_user)):
    user = _need_user(user)
    client_id = _uuid(client_id, "Cliente")
    client = _get_client(user, client_id)
    meetings = _db(lambda: sec.user_rest(user, "GET", f"meetings?select=id,meeting_title,created_at,client_link,sentiment,risk,opportunity&client_id=eq.{client_id}&order=created_at.desc&limit=100")) or []
    return {"ok": True, "client": client, "meetings": meetings}


@router.patch("/api/clients/{client_id}")
def update(client_id: str, payload: ClientUpdate, user=Depends(sec.current_user)):
    user = _need_user(user)
    client_id = _uuid(client_id, "Cliente")
    client = _get_client(user, client_id)
    if client.get("org_id"):
        sec.require_org_permission(user, client["org_id"], "clients.write")
    if client.get("merged_into"):
        raise HTTPException(status_code=409, detail=ERRORS["client_merged"][1])
    changes: dict = {}
    name = client["name"]
    if payload.name is not None:
        name = " ".join(payload.name.split())
        if not 1 <= len(name) <= 200 or not normalize_name(name):
            raise HTTPException(status_code=400, detail="O nome do cliente deve ter entre 1 e 200 caracteres.")
        changes.update(name=name, normalized_name=normalize_name(name))
    if payload.aliases is not None or payload.name is not None:
        changes["aliases"] = _clean_aliases(payload.aliases if payload.aliases is not None else client.get("aliases"), name)
    if not changes:
        return {"ok": True, "client": client}
    rows = _db(lambda: sec.user_rest(user, "PATCH", f"clients?id=eq.{client_id}", changes)) or []
    if not rows:
        raise HTTPException(status_code=403, detail=ERRORS["forbidden"][1])
    sec.audit(user, "client.update", client.get("org_id"), "client", client_id, {"fields": sorted(changes)})
    return {"ok": True, "client": rows[0]}


@router.patch("/api/meetings/{meeting_id}/client")
def change_link(meeting_id: str, payload: LinkChange, user=Depends(sec.current_user)):
    user = _need_user(user)
    meeting_id = _uuid(meeting_id, "Reunião")
    rows = _db(lambda: sec.user_rest(user, "GET", f"meetings?select=id,org_id,owner_id&id=eq.{meeting_id}&limit=1")) or []
    if not rows:
        raise HTTPException(status_code=404, detail="Reunião não encontrada.")
    meeting = rows[0]
    org = meeting.get("org_id")
    action = payload.action
    if action == "unlink":
        change = {"client_id": None, "client_link": "unlinked", "client_suggestion": []}
    elif action in ("confirm", "set"):
        client = _get_client(user, _uuid(payload.client_id, "Cliente"))
        if client.get("merged_into"):
            raise HTTPException(status_code=409, detail=ERRORS["client_merged"][1])
        if client.get("org_id") != org or (org is None and client.get("owner_id") != meeting.get("owner_id")):
            raise HTTPException(status_code=409, detail=ERRORS["client_scope_mismatch"][1])
        change = {"client_id": client["id"], "client_link": "confirmed", "client_suggestion": []}
    elif action == "create":
        name = " ".join((payload.name or "").split())
        if not 1 <= len(name) <= 200 or not normalize_name(name):
            raise HTTPException(status_code=400, detail="Informe o nome do novo cliente (até 200 caracteres).")
        if org:
            sec.require_org_permission(user, org, "clients.write")
        created = _db(lambda: create_client(user, org, name, "user"))
        sec.audit(user, "client.create", org, "client", created.get("id"), {"via": "user"})
        change = {"client_id": created["id"], "client_link": "confirmed", "client_suggestion": []}
    else:
        raise HTTPException(status_code=400, detail="Ação inválida. Use confirm, set, create ou unlink.")
    updated = _db(lambda: sec.user_rest(user, "PATCH", f"meetings?id=eq.{meeting_id}", change)) or []
    if not updated:
        raise HTTPException(status_code=403, detail="Você não pode alterar o cliente desta reunião.")
    sec.audit(user, "meeting.client_link", org, "meeting", meeting_id, {"action": action})
    return {"ok": True, "meeting": {"id": meeting_id, **change}}


@router.post("/api/clients/{client_id}/merge")
def merge(client_id: str, payload: MergeRequest, user=Depends(sec.current_user)):
    user = _need_user(user)
    source, target = _uuid(client_id, "Cliente"), _uuid(payload.into, "Cliente de destino")
    result = _db(lambda: sec.user_rest(user, "POST", "rpc/merge_clients", {"p_source": source, "p_target": target})) or {}
    sec.audit(user, "client.merge", None, "client", source, {"into": target, "moved": result.get("moved")})
    return {"ok": True, **result}


@router.post("/api/clients/{client_id}/unmerge")
def unmerge(client_id: str, user=Depends(sec.current_user)):
    user = _need_user(user)
    source = _uuid(client_id, "Cliente")
    result = _db(lambda: sec.user_rest(user, "POST", "rpc/unmerge_clients", {"p_source": source})) or {}
    sec.audit(user, "client.unmerge", None, "client", source, {"restored": result.get("restored")})
    return {"ok": True, **result}
