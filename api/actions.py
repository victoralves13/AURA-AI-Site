"""AURA AI — ações como entidade: responsável, prazo, estado e histórico, sempre ligadas à reunião de origem.

Regras:
  * A ação nasce da análise (origem "ai") ou é digitada por uma pessoa (origem "user").
  * Ação da IA guarda texto, base (dito/inferido) e evidência imutáveis (rastreabilidade): só o estado,
    o responsável e o prazo mudam, e ela não é apagada, e sim cancelada. O banco garante isso.
  * Responsável e prazo só existem como foram ditos na reunião (texto) ou como uma pessoa definiu.
  * Quem vê uma ação é quem vê a reunião; quem edita é o dono da reunião ou quem tem `actions.manage`.
    Tudo isso vale no banco (RLS); aqui o JWT da pessoa é sempre usado, nunca a chave de serviço.
  * Evidência marcada como "não localizada" na transcrição não vira ação acompanhável (fica só no detalhe).
  * A sincronização é idempotente (chave = texto normalizado) e nunca bloqueia a análise.
"""
from __future__ import annotations

import hashlib
import logging
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

import security as sec
import verification

log = logging.getLogger("aura.actions")
router = APIRouter()

STATUSES = ("open", "in_progress", "done", "cancelled")
ACTIVE = ("open", "in_progress")
MAX_SYNC_MEETINGS = 100
MAX_ACTIONS_PER_MEETING = 50
SELECT_LIST = "*,meetings(meeting_title,client_name,client_id,created_at)"


# ---------------------------------------------------------------------------
# Derivação das ações de uma reunião (pura, sem rede)
# ---------------------------------------------------------------------------
def source_key(text: str) -> str:
    return hashlib.sha1(verification.normalize(text).encode("utf-8")).hexdigest()[:20]


def _iso_date(value) -> str | None:
    try:
        return date.fromisoformat(str(value).strip()).isoformat()
    except (TypeError, ValueError):
        return None


def _short(value, size: int) -> str | None:
    text = " ".join(str(value or "").split())
    return text[:size] or None


def actions_from_meeting(meeting: dict) -> list[dict]:
    """Ações acompanháveis de uma reunião, no formato da tabela `actions` (sem meeting_id/org_id)."""
    out: list[dict] = []
    seen: set[str] = set()

    def add(row: dict) -> None:
        key = row["source_key"]
        if key not in seen and len(out) < MAX_ACTIONS_PER_MEETING:
            seen.add(key)
            out.append(row)

    detail = meeting.get("actions_detail") or []
    if isinstance(detail, list) and detail:
        for item in detail:
            if not isinstance(item, dict):
                continue
            text = _short(item.get("description"), 1000)
            if not text or item.get("evidence_check") == verification.NAO_LOCALIZADA:
                continue
            basis = item.get("basis") if item.get("basis") in ("dito", "inferido") else None
            evidence = {k: item.get(k) for k in ("evidence", "timestamp", "speaker", "evidence_check", "inference_rationale")
                        if item.get(k) is not None}
            add({"text": text, "source": "ai", "source_key": source_key(text), "basis": basis, "evidence": evidence,
                 "assignee_text": _short(item.get("owner"), 200), "due_text": _short(item.get("deadline"), 200),
                 "due_date": _iso_date(item.get("deadline"))})
        return out
    # reuniões antigas (antes da análise v2): só o texto das pendências, sem responsável nem prazo inventados
    for raw in meeting.get("pending_actions") or []:
        text = _short(raw.get("description") if isinstance(raw, dict) else raw, 1000)
        if text:
            add({"text": text, "source": "ai", "source_key": source_key(text), "basis": None, "evidence": {},
                 "assignee_text": None, "due_text": None, "due_date": None})
    return out


# ---------------------------------------------------------------------------
# Acesso ao banco (sempre com o JWT do usuário: o RLS vale)
# ---------------------------------------------------------------------------
ERRORS = {
    "action_text_locked": (409, "O texto e a evidência de uma ação gerada pela análise não podem ser alterados. Cancele a ação, se necessário."),
    "action_immutable": (409, "Esse campo da ação não pode ser alterado."),
    "assignee_not_member": (400, "O responsável precisa ser membro da organização desta reunião."),
    "meeting_not_found": (404, "Reunião não encontrada."),
}
GENERIC = "Não foi possível concluir a operação com ações. Tente novamente."


def _db(call):
    try:
        return call()
    except sec.SupabaseError as exc:
        if exc.db_message in ERRORS:
            status, detail = ERRORS[exc.db_message]
            raise HTTPException(status_code=status, detail=detail) from exc
        if exc.db_code == "23505":
            raise HTTPException(status_code=409, detail="Essa ação já existe nesta reunião.") from exc
        if exc.db_code == "23514" or exc.db_code == "22P02":
            raise HTTPException(status_code=400, detail="Dados da ação inválidos.") from exc
        if exc.status in (401, 403):
            raise HTTPException(status_code=403, detail="Você não tem permissão para alterar ações desta reunião.") from exc
        raise HTTPException(status_code=502, detail=GENERIC) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=GENERIC) from exc


def _need_user(user):
    if user is None:
        raise HTTPException(status_code=401, detail="Autenticação necessária.")
    return user


def _uuid(value: str | None, what: str) -> str:
    if not value or not sec.UUID_RE.match(value):
        raise HTTPException(status_code=400, detail=f"{what} inválido.")
    return value.lower()


def _space(user: sec.AuthUser, org_id: str | None) -> str:
    if not org_id:
        return ""
    if org_id == "personal":
        return "&org_id=is.null"
    return f"&org_id=eq.{_uuid(org_id, 'Espaço')}"


def _get_meeting(user: sec.AuthUser, meeting_id: str) -> dict:
    rows = _db(lambda: sec.user_rest(user, "GET", f"meetings?select=id,org_id,owner_id,actions_detail,pending_actions&id=eq.{meeting_id}&limit=1")) or []
    if not rows:
        raise HTTPException(status_code=404, detail="Reunião não encontrada.")
    return rows[0]


def _get_action(user: sec.AuthUser, action_id: str) -> dict:
    rows = _db(lambda: sec.user_rest(user, "GET", f"actions?select={SELECT_LIST}&id=eq.{action_id}&limit=1")) or []
    if not rows:
        raise HTTPException(status_code=404, detail="Ação não encontrada.")
    return rows[0]


def sync_for_meeting(user: sec.AuthUser | None, meeting: dict) -> int:
    """Cria as ações que ainda não existem para a reunião (idempotente). Retorna quantas foram criadas.

    Nunca levanta erro por falha de banco: a análise/consulta que a chamou não pode ser perdida por isso."""
    if user is None or not meeting or not meeting.get("id"):
        return 0
    try:
        wanted = actions_from_meeting(meeting)
        if not wanted:
            return 0
        existing = {r["source_key"] for r in (sec.user_rest(user, "GET", f"actions?select=source_key&meeting_id=eq.{meeting['id']}&source_key=not.is.null&limit=200") or [])}
        created = 0
        for row in wanted:
            if row["source_key"] in existing:
                continue
            try:
                sec.user_rest(user, "POST", "actions", {**row, "meeting_id": meeting["id"]})
                created += 1
            except sec.SupabaseError as exc:
                if exc.db_code != "23505":  # outra chamada criou a mesma ação: ok
                    raise
        return created
    except RuntimeError as exc:
        log.warning("ações não sincronizadas (reunião %s): %s", (meeting or {}).get("id"), exc)
        return 0


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------
class ActionCreate(BaseModel):
    text: str
    assignee_text: str | None = None
    assignee_user_id: str | None = None
    due_text: str | None = None
    due_date: str | None = None


class ActionUpdate(BaseModel):
    status: str | None = None
    text: str | None = None
    assignee_text: str | None = None
    assignee_user_id: str | None = None
    due_text: str | None = None
    due_date: str | None = None


def _clean_fields(data: dict) -> dict:
    """Valida e normaliza os campos enviados (só os presentes). Vazio limpa o campo."""
    out: dict = {}
    if "status" in data:
        if data["status"] not in STATUSES:
            raise HTTPException(status_code=400, detail="Estado inválido. Use open, in_progress, done ou cancelled.")
        out["status"] = data["status"]
    if "text" in data:
        text = _short(data["text"], 1001)
        if not text or len(text) > 1000:
            raise HTTPException(status_code=400, detail="O texto da ação deve ter entre 1 e 1000 caracteres.")
        out["text"] = text
    for field in ("assignee_text", "due_text"):
        if field in data:
            value = _short(data[field], 201)
            if value and len(value) > 200:
                raise HTTPException(status_code=400, detail="Texto longo demais (máximo 200 caracteres).")
            out[field] = value
    if "assignee_user_id" in data:
        out["assignee_user_id"] = _uuid(data["assignee_user_id"], "Responsável") if data["assignee_user_id"] else None
    if "due_date" in data:
        if data["due_date"]:
            if not _iso_date(data["due_date"]):
                raise HTTPException(status_code=400, detail="Data inválida. Use o formato AAAA-MM-DD.")
            out["due_date"] = _iso_date(data["due_date"])
        else:
            out["due_date"] = None
    return out


@router.get("/api/actions")
def list_actions(org_id: str | None = None, status: str | None = None, meeting_id: str | None = None,
                 client_id: str | None = None, assignee: str | None = None, overdue: bool = False,
                 limit: int = 200, user=Depends(sec.current_user)):
    user = _need_user(user)
    where = _space(user, org_id)
    if status:
        if status == "active":
            where += "&status=in.(open,in_progress)"
        elif status in STATUSES:
            where += f"&status=eq.{status}"
        else:
            raise HTTPException(status_code=400, detail="Filtro de estado inválido.")
    if meeting_id:
        where += f"&meeting_id=eq.{_uuid(meeting_id, 'Reunião')}"
    if client_id:
        cid = _uuid(client_id, "Cliente")
        ids = [m["id"] for m in _db(lambda: sec.user_rest(user, "GET", f"meetings?select=id&client_id=eq.{cid}&limit=500")) or []]
        if not ids:
            return {"ok": True, "actions": [], "count": 0}
        where += "&meeting_id=in.(" + ",".join(ids) + ")"
    if assignee == "me":
        where += f"&assignee_user_id=eq.{user.id}"
    if overdue:
        where += f"&due_date=lt.{date.today().isoformat()}&status=in.(open,in_progress)"
    limit = max(1, min(limit, 500))
    rows = _db(lambda: sec.user_rest(user, "GET", f"actions?select={SELECT_LIST}{where}&order=created_at.desc&limit={limit}")) or []
    return {"ok": True, "actions": rows, "count": len(rows)}


@router.post("/api/actions/sync")
def sync_space(org_id: str | None = None, user=Depends(sec.current_user)):
    """Cria as ações das reuniões do espaço que ainda não as têm (inclui as reuniões antigas)."""
    user = _need_user(user)
    where = _space(user, org_id)
    meetings = _db(lambda: sec.user_rest(user, "GET", f"meetings?select=id,org_id,owner_id,actions_detail,pending_actions&is_demo=is.false{where}&order=created_at.desc&limit={MAX_SYNC_MEETINGS}")) or []
    created = sum(sync_for_meeting(user, m) for m in meetings)
    if created:
        sec.audit(user, "actions.sync", None if not org_id or org_id == "personal" else org_id, "space", None, {"created": created, "meetings": len(meetings)})
    return {"ok": True, "created": created, "meetings": len(meetings)}


@router.get("/api/meetings/{meeting_id}/actions")
def meeting_actions(meeting_id: str, user=Depends(sec.current_user)):
    user = _need_user(user)
    mid = _uuid(meeting_id, "Reunião")
    _get_meeting(user, mid)
    rows = _db(lambda: sec.user_rest(user, "GET", f"actions?select={SELECT_LIST}&meeting_id=eq.{mid}&order=created_at.asc&limit=200")) or []
    return {"ok": True, "actions": rows, "count": len(rows)}


@router.post("/api/meetings/{meeting_id}/actions/sync")
def sync_meeting(meeting_id: str, user=Depends(sec.current_user)):
    user = _need_user(user)
    meeting = _get_meeting(user, _uuid(meeting_id, "Reunião"))
    created = sync_for_meeting(user, meeting)
    if created:
        sec.audit(user, "actions.sync", meeting.get("org_id"), "meeting", meeting["id"], {"created": created})
    return {"ok": True, "created": created}


@router.post("/api/meetings/{meeting_id}/actions")
def create_action(meeting_id: str, payload: ActionCreate, user=Depends(sec.current_user)):
    user = _need_user(user)
    meeting = _get_meeting(user, _uuid(meeting_id, "Reunião"))
    fields = _clean_fields({k: v for k, v in payload.model_dump().items() if v is not None or k == "text"})
    if "text" not in fields:
        raise HTTPException(status_code=400, detail="O texto da ação é obrigatório.")
    row = {**fields, "meeting_id": meeting["id"], "source": "user", "basis": None}
    created = (_db(lambda: sec.user_rest(user, "POST", "actions", row)) or [row])[0]
    sec.audit(user, "action.create", meeting.get("org_id"), "action", created.get("id"), {"source": "user"})
    return {"ok": True, "action": created}


@router.patch("/api/actions/{action_id}")
def update_action(action_id: str, payload: ActionUpdate, user=Depends(sec.current_user)):
    user = _need_user(user)
    aid = _uuid(action_id, "Ação")
    current = _get_action(user, aid)
    changes = _clean_fields(payload.model_dump(exclude_unset=True))
    if not changes:
        return {"ok": True, "action": current}
    rows = _db(lambda: sec.user_rest(user, "PATCH", f"actions?id=eq.{aid}", changes)) or []
    if not rows:  # a ação é visível, mas a pessoa não pode editá-la
        raise HTTPException(status_code=403, detail="Você não tem permissão para alterar esta ação.")
    sec.audit(user, "action.update", current.get("org_id"), "action", aid, {"fields": sorted(changes)})
    return {"ok": True, "action": rows[0]}


@router.delete("/api/actions/{action_id}")
def delete_action(action_id: str, user=Depends(sec.current_user)):
    user = _need_user(user)
    aid = _uuid(action_id, "Ação")
    current = _get_action(user, aid)
    if current.get("source") == "ai":
        raise HTTPException(status_code=409, detail="Ações geradas pela análise não são apagadas. Cancele a ação.")
    rows = _db(lambda: sec.user_rest(user, "DELETE", f"actions?id=eq.{aid}")) or []
    if not rows and _db(lambda: sec.user_rest(user, "GET", f"actions?select=id&id=eq.{aid}&limit=1")):
        raise HTTPException(status_code=403, detail="Você não tem permissão para apagar esta ação.")
    sec.audit(user, "action.delete", current.get("org_id"), "action", aid)
    return {"ok": True}


@router.get("/api/actions/{action_id}/events")
def action_events(action_id: str, user=Depends(sec.current_user)):
    user = _need_user(user)
    aid = _uuid(action_id, "Ação")
    _get_action(user, aid)
    rows = _db(lambda: sec.user_rest(user, "GET", f"action_events?select=at,actor_id,event,data&action_id=eq.{aid}&order=at.asc&limit=200")) or []
    return {"ok": True, "events": rows}
