"""AURA AI — reuniões: gravação e listagem (regras). A análise (IA) vive em aura.features.analysis."""
from __future__ import annotations

from aura.core import security as sec
from aura.core.errors import AppError
from aura.features.integrations.service import emit_safe as emit_integration_event
from aura.features.meetings import repository
from aura.features.meetings.repository import V2_COLUMNS

FIELDS = ["source_type", "file_name", "meeting_title", "context", "is_demo", "demo_scenario", "transcript", "summary", "sentiment",
          "sentiment_confidence", "opportunity", "risk", "risk_score", "opportunity_score", "opportunity_signals", "risk_signals", "priority",
          "impact", "why_it_matters", "intent", "objections", "products", "evidence", "decisions", "pending_actions", "important_signals",
          "insights", "topics", "financial_data", "participants", "next_move", "owner", "deadline", "model"]


def save_meeting(data: dict, user=None) -> dict:
    """Grava a reunião analisada. Dono e organização vêm do token verificado, nunca do corpo. Degrada se colunas novas faltarem."""
    payload = {key: data.get(key) for key in FIELDS}
    payload["client_name"] = data.get("client_name") or "Cliente não identificado"
    for key in V2_COLUMNS:  # só quando presentes: null violaria o NOT NULL das colunas jsonb
        if data.get(key) is not None:
            payload[key] = data[key]
    if data.get("client_id"):  # a coluna existe desde a Etapa 2; o gatilho do banco confere o espaço do cliente
        payload["client_id"] = data["client_id"]
    if data.get("client_link") == "unlinked" and not data.get("client_suggestion"):
        payload.pop("client_link", None)  # padrão do banco; evita enviar coluna nova sem necessidade
        payload.pop("client_suggestion", None)
    if data.get("meeting_at"):  # data real da reunião informada na Nova análise (senão o banco usa "agora")
        payload["created_at"] = data["meeting_at"]
    if user is not None:
        org_id = data.get("org_id") or None
        payload["owner_id"] = user.id
        payload["org_id"] = org_id
        visibility = data.get("visibility")
        payload["visibility"] = visibility if org_id and visibility in ("private", "team", "org") else "private"

    attempt = dict(payload)
    rehydrate = False
    result = None
    for step in range(3):
        try:
            result = repository.insert_meeting(attempt, user=user)
            break
        except RuntimeError as exc:
            if step == 0 and any(k in attempt for k in V2_COLUMNS) and repository.is_schema_error(exc, V2_COLUMNS):
                for key in V2_COLUMNS:
                    attempt.pop(key, None)
                continue
            if step <= 1 and not rehydrate and repository.is_schema_error(exc, ("insights", "topics")):
                # O PostgREST pode servir um cache de esquema velho logo depois de uma migração. Se isso acontecer nas colunas
                # JSONB, a reunião continua utilizável: os insights completos vão pela coluna de evidências, que já existe.
                full_insights = attempt.pop("insights", None) or []
                attempt.pop("topics", None)
                existing_evidence = attempt.get("evidence") or []
                merged = list(existing_evidence) if isinstance(existing_evidence, list) else []
                merged.extend(item for item in full_insights if item not in merged)
                attempt["evidence"] = merged
                rehydrate = True
                continue
            raise

    if rehydrate and result and isinstance(result[0], dict):
        # A resposta pode não expor as colunas novas durante a janela do cache: devolve-as para a tela mostrar a análise completa.
        result[0].setdefault("insights", payload.get("insights") or [])
        result[0].setdefault("topics", data.get("topics") or [])
        result[0].setdefault("financial_data", data.get("financial_data") or [])
    if result and isinstance(result[0], dict):
        for key in V2_COLUMNS:
            if key not in result[0] and data.get(key) is not None:
                result[0][key] = data[key]

    if result is None:
        return {"persisted": False, "storage": "local-only"}
    meeting = result[0] if result else None
    if user is not None and isinstance(meeting, dict) and meeting.get("id") and not payload.get("is_demo"):
        # Avisa as integrações do espaço (só ids e rótulos curtos; nunca a transcrição). Falha aqui nunca afeta a análise.
        emit_integration_event(payload.get("org_id"), user.id, "meeting.analyzed", "meeting", meeting["id"],
                               {"meeting_id": meeting["id"], "title": str(payload.get("meeting_title") or "")[:120], "risk": payload.get("risk"),
                                "sentiment": payload.get("sentiment")}, f"meeting.analyzed:{meeting['id']}")
    return {"persisted": True, "storage": "supabase", "meeting": meeting}


def list_meetings(user, limit: int, org_id: str | None) -> dict:
    limit = max(1, min(limit, 100))
    space = ""
    if user is not None and org_id:
        # Espaço de trabalho: "personal" (sem organização) ou uma organização. O RLS continua decidindo o que o usuário pode ver.
        if org_id == "personal":
            space = "&org_id=is.null"
        elif sec.UUID_RE.match(org_id):
            space = f"&org_id=eq.{org_id.lower()}"
        else:
            raise AppError(400, "Espaço inválido.")
    try:
        result = repository.list_meetings(user, limit, space)
        return {"ok": True, "persisted": result is not None, "meetings": sec.redact_meetings(result or [], user)}
    except RuntimeError as exc:
        raise AppError(502, str(exc)) from exc


def create_meeting(user, payload: dict) -> dict:
    if not payload.get("transcript"):
        raise AppError(400, "transcript é obrigatório")
    sec.require_org_permission(user, payload.get("org_id"), "meetings.write")
    try:
        saved = save_meeting(payload, user)
    except RuntimeError as exc:
        raise AppError(502, str(exc)) from exc
    sec.audit(user, "meeting.create", payload.get("org_id"), "meeting", (saved.get("meeting") or {}).get("id"))
    return {"ok": True, **saved}
