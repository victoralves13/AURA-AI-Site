"""AURA AI — ações como entidade: responsável, prazo, estado e histórico, sempre ligadas à reunião de origem (regras).

  * Ação da IA guarda texto, base (dito/inferido) e evidência imutáveis (rastreabilidade): só o estado,
    o responsável e o prazo mudam, e ela não é apagada, e sim cancelada. O banco garante isso.
  * Quem vê uma ação é quem vê a reunião; quem edita é o dono da reunião ou quem tem `actions.manage`.
    Tudo isso vale no banco (RLS); aqui o JWT da pessoa é sempre usado, nunca a chave de serviço.
  * A sincronização com a análise nunca bloqueia a análise.
A derivação das ações de uma reunião está em `derivation.py` e os indicadores em `stats.py` (regras puras).
"""
from __future__ import annotations

import logging
from datetime import date, timedelta

from aura.core import security as sec
from aura.core.errors import AppError
from aura.features.actions import repository, stats
from aura.features.actions.derivation import actions_from_meeting, iso_date, short  # noqa: F401  (actions_from_meeting: porta pública)
from aura.features.actions.schemas import ActionCreate, ActionUpdate, FeedbackBody, OutcomeCreate
from aura.features.actions.stats import EFFECTIVENESS, STATUSES
from aura.features.integrations.service import emit_safe

log = logging.getLogger("aura.actions")

MAX_SYNC_MEETINGS = 100
RATINGS = ("useful", "not_useful")


def _uuid(value: str | None, what: str) -> str:
    if not value or not sec.UUID_RE.match(value):
        raise AppError(400, f"{what} inválido.")
    return value.lower()


def _space(user: sec.AuthUser, org_id: str | None) -> str:
    if not org_id:
        return ""
    if org_id == "personal":
        return "&org_id=is.null"
    return f"&org_id=eq.{_uuid(org_id, 'Espaço')}"


def _get_meeting(user: sec.AuthUser, meeting_id: str) -> dict:
    meeting = repository.get_meeting(user, meeting_id)
    if meeting is None:
        raise AppError(404, "Reunião não encontrada.")
    return meeting


def _with_latest(rows: list[dict], user: sec.AuthUser | None = None) -> list[dict]:
    """Troca os resultados embutidos por `latest_outcome` (o mais recente vale) e resume o feedback da ação."""
    for row in rows:
        votes = row.pop("action_feedback", None) or []
        row["feedback"] = {"useful": sum(v.get("rating") == "useful" for v in votes),
                           "not_useful": sum(v.get("rating") == "not_useful" for v in votes),
                           "mine": next((v["rating"] for v in votes if user is not None and v.get("user_id") == user.id), None)}
        outcomes = row.pop("action_outcomes", None) or []
        row["outcomes_count"] = len(outcomes)
        row["latest_outcome"] = max(outcomes, key=lambda o: o.get("created_at") or "") if outcomes else None
    return rows


def _get_action(user: sec.AuthUser, action_id: str) -> dict:
    row = repository.get_action(user, action_id)
    if row is None:
        raise AppError(404, "Ação não encontrada.")
    return _with_latest([row], user)[0]


def sync_for_meeting(user: sec.AuthUser | None, meeting: dict) -> int:
    """Cria as ações que ainda não existem para a reunião (idempotente). Retorna quantas foram criadas.

    Nunca levanta erro por falha de banco: a análise/consulta que a chamou não pode ser perdida por isso."""
    if user is None or not meeting or not meeting.get("id"):
        return 0
    try:
        wanted = actions_from_meeting(meeting)
        if not wanted:
            return 0
        existing = repository.existing_source_keys(user, meeting["id"])
        created = 0
        for row in wanted:
            if row["source_key"] in existing:
                continue
            if repository.insert_synced_action(user, {**row, "meeting_id": meeting["id"]}):
                created += 1
        return created
    except RuntimeError as exc:
        log.warning("ações não sincronizadas (reunião %s): %s", (meeting or {}).get("id"), exc)
        return 0


def _clean_fields(data: dict) -> dict:
    """Valida e normaliza os campos enviados (só os presentes). Vazio limpa o campo."""
    out: dict = {}
    if "status" in data:
        if data["status"] not in STATUSES:
            raise AppError(400, "Estado inválido. Use open, in_progress, done ou cancelled.")
        out["status"] = data["status"]
    if "text" in data:
        text = short(data["text"], 1001)
        if not text or len(text) > 1000:
            raise AppError(400, "O texto da ação deve ter entre 1 e 1000 caracteres.")
        out["text"] = text
    for field in ("assignee_text", "due_text"):
        if field in data:
            value = short(data[field], 201)
            if value and len(value) > 200:
                raise AppError(400, "Texto longo demais (máximo 200 caracteres).")
            out[field] = value
    if "assignee_user_id" in data:
        out["assignee_user_id"] = _uuid(data["assignee_user_id"], "Responsável") if data["assignee_user_id"] else None
    if "due_date" in data:
        if data["due_date"]:
            if not iso_date(data["due_date"]):
                raise AppError(400, "Data inválida. Use o formato AAAA-MM-DD.")
            out["due_date"] = iso_date(data["due_date"])
        else:
            out["due_date"] = None
    return out


# ---------------------------------------------------------------------------
# Casos de uso da API
# ---------------------------------------------------------------------------
def list_actions(user, org_id, status, meeting_id, client_id, assignee, overdue: bool, limit: int) -> dict:
    where = _space(user, org_id)
    if status:
        if status == "active":
            where += "&status=in.(open,in_progress)"
        elif status in STATUSES:
            where += f"&status=eq.{status}"
        else:
            raise AppError(400, "Filtro de estado inválido.")
    if meeting_id:
        where += f"&meeting_id=eq.{_uuid(meeting_id, 'Reunião')}"
    if client_id:
        ids = repository.meetings_of_client(user, _uuid(client_id, "Cliente"))
        if not ids:
            return {"ok": True, "actions": [], "count": 0}
        where += "&meeting_id=in.(" + ",".join(ids) + ")"
    if assignee == "me":
        where += f"&assignee_user_id=eq.{user.id}"
    if overdue:
        where += f"&due_date=lt.{date.today().isoformat()}&status=in.(open,in_progress)"
    rows = repository.list_actions(user, where, max(1, min(limit, 500)))
    return {"ok": True, "actions": _with_latest(rows, user), "count": len(rows)}


def action_stats(user, org_id, client_id) -> dict:
    """Acompanhamento e eficácia das ações do espaço. Taxas ficam nulas quando não há base para calculá-las."""
    where = _space(user, org_id)
    if client_id:
        ids = repository.meetings_of_client(user, _uuid(client_id, "Cliente"))
        where += "&meeting_id=in.(" + ",".join(ids or ["00000000-0000-0000-0000-000000000000"]) + ")"
    rows = repository.stats_rows(user, where)
    return {"ok": True, **stats.compute(rows, date.today().isoformat()), "truncated": len(rows) >= repository.STATS_LIMIT}


def sync_space(user, org_id) -> dict:
    """Cria as ações das reuniões do espaço que ainda não as têm (inclui as reuniões antigas)."""
    meetings = repository.meetings_to_sync(user, _space(user, org_id), MAX_SYNC_MEETINGS)
    created = sum(sync_for_meeting(user, m) for m in meetings)
    if created:
        sec.audit(user, "actions.sync", None if not org_id or org_id == "personal" else org_id, "space", None, {"created": created, "meetings": len(meetings)})
    return {"ok": True, "created": created, "meetings": len(meetings)}


def meeting_actions(user, meeting_id: str) -> dict:
    mid = _uuid(meeting_id, "Reunião")
    _get_meeting(user, mid)
    rows = repository.list_for_meeting(user, mid)
    return {"ok": True, "actions": _with_latest(rows, user), "count": len(rows)}


def sync_meeting(user, meeting_id: str) -> dict:
    meeting = _get_meeting(user, _uuid(meeting_id, "Reunião"))
    created = sync_for_meeting(user, meeting)
    if created:
        sec.audit(user, "actions.sync", meeting.get("org_id"), "meeting", meeting["id"], {"created": created})
    return {"ok": True, "created": created}


def create_action(user, meeting_id: str, payload: ActionCreate) -> dict:
    meeting = _get_meeting(user, _uuid(meeting_id, "Reunião"))
    fields = _clean_fields({k: v for k, v in payload.model_dump().items() if v is not None or k == "text"})
    if "text" not in fields:
        raise AppError(400, "O texto da ação é obrigatório.")
    created = repository.insert_action(user, {**fields, "meeting_id": meeting["id"], "source": "user", "basis": None})
    sec.audit(user, "action.create", meeting.get("org_id"), "action", created.get("id"), {"source": "user"})
    return {"ok": True, "action": created}


def update_action(user, action_id: str, payload: ActionUpdate) -> dict:
    aid = _uuid(action_id, "Ação")
    current = _get_action(user, aid)
    changes = _clean_fields(payload.model_dump(exclude_unset=True))
    if not changes:
        return {"ok": True, "action": current}
    row = repository.patch_action(user, aid, changes)
    if row is None:  # a ação é visível, mas a pessoa não pode editá-la
        raise AppError(403, "Você não tem permissão para alterar esta ação.")
    sec.audit(user, "action.update", current.get("org_id"), "action", aid, {"fields": sorted(changes)})
    if changes.get("status") == "done" and current.get("status") != "done":
        emit_safe(current.get("org_id"), user.id, "action.completed", "action", aid,
                  {"action_id": aid, "meeting_id": current.get("meeting_id"), "text": str(row.get("text") or "")[:120]},
                  f"action.completed:{aid}:{row.get('completed_at') or ''}")
    return {"ok": True, "action": row}


def delete_action(user, action_id: str) -> dict:
    aid = _uuid(action_id, "Ação")
    current = _get_action(user, aid)
    if current.get("source") == "ai":
        raise AppError(409, "Ações geradas pela análise não são apagadas. Cancele a ação.")
    if not repository.delete_action(user, aid) and repository.action_exists(user, aid):
        raise AppError(403, "Você não tem permissão para apagar esta ação.")
    sec.audit(user, "action.delete", current.get("org_id"), "action", aid)
    return {"ok": True}


def action_events(user, action_id: str) -> dict:
    aid = _uuid(action_id, "Ação")
    _get_action(user, aid)
    return {"ok": True, "events": repository.list_events(user, aid)}


def add_outcome(user, action_id: str, payload: OutcomeCreate) -> dict:
    """Registra o que a pessoa observou depois da ação e se funcionou. Só acrescenta: corrigir é registrar de novo."""
    aid = _uuid(action_id, "Ação")
    current = _get_action(user, aid)
    result = short(payload.result, 2001)
    if not result or len(result) > 2000:
        raise AppError(400, "Descreva o resultado observado (até 2000 caracteres).")
    if payload.effectiveness not in EFFECTIVENESS:
        raise AppError(400, "Avaliação inválida. Use worked, partial, not_worked ou uncertain.")
    row = {"action_id": aid, "result": result, "effectiveness": payload.effectiveness}
    if payload.observed_at:
        observed = iso_date(payload.observed_at)
        if not observed:
            raise AppError(400, "Data inválida. Use o formato AAAA-MM-DD.")
        if observed > (date.today() + timedelta(days=1)).isoformat():  # tolera 1 dia: fusos à frente do servidor
            raise AppError(400, repository.OBSERVED_IN_FUTURE)
        row["observed_at"] = observed
    created = repository.insert_outcome(user, row)
    sec.audit(user, "action.outcome", current.get("org_id"), "action", aid, {"effectiveness": payload.effectiveness})
    return {"ok": True, "outcome": created}


def list_outcomes(user, action_id: str) -> dict:
    aid = _uuid(action_id, "Ação")
    _get_action(user, aid)
    return {"ok": True, "outcomes": repository.list_outcomes(user, aid)}


def set_feedback(user, action_id: str, payload: FeedbackBody) -> dict:
    """O voto "útil / não útil" da própria pessoa sobre uma ação da análise. Cria ou troca; um voto por pessoa."""
    aid = _uuid(action_id, "Ação")
    current = _get_action(user, aid)
    if payload.rating not in RATINGS:
        raise AppError(400, "Avaliação inválida. Use useful ou not_useful.")
    note = short(payload.note, 501)
    if note and len(note) > 500:
        raise AppError(400, "A observação deve ter até 500 caracteres.")
    if current.get("source") != "ai":
        raise AppError(409, repository.FEEDBACK_ONLY_AI)
    row = repository.save_feedback(user, aid, {"rating": payload.rating, "note": note})
    sec.audit(user, "action.feedback", current.get("org_id"), "action", aid, {"rating": payload.rating})
    return {"ok": True, "feedback": {"rating": row.get("rating", payload.rating)}}


def clear_feedback(user, action_id: str) -> dict:
    aid = _uuid(action_id, "Ação")
    current = _get_action(user, aid)
    repository.clear_feedback(user, aid)
    sec.audit(user, "action.feedback_clear", current.get("org_id"), "action", aid)
    return {"ok": True}
