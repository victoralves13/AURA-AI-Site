"""AURA AI — reuniões: gravação e listagem (a análise vive em aura.features.analysis)."""
import json
import os
import urllib.error
import urllib.request

from fastapi import APIRouter, Depends, HTTPException

from aura.core import security as sec
from aura.features.integrations.router import emit_safe as emit_integration_event

router = APIRouter()


def _supabase_request(method: str, path: str, payload=None, user=None):
    """PostgREST. Com `user`, usa o JWT dele (o RLS do banco vale); sem `user`, usa a chave de serviço."""
    url, key = os.getenv("SUPABASE_URL"), (os.getenv("SUPABASE_SECRET_KEY") or os.getenv("SUPABASE_SERVICE_ROLE_KEY"))
    import urllib.request
    if user is not None:
        if not url or not sec.publishable_key():
            raise RuntimeError("Supabase não configurado para autenticação de usuários.")
        headers = {**sec.rest_headers(user), "Content-Type": "application/json"}
    else:
        if not url or not key:
            return None
        headers = {"apikey": key, "Authorization": f"Bearer {key}", "Content-Type": "application/json", "Prefer": "return=representation"}
    req = urllib.request.Request(url.rstrip("/") + "/rest/v1/" + path, method=method, headers=headers)
    if payload is not None:
        req.data = json.dumps(payload, ensure_ascii=False).encode()
    try:
        with urllib.request.urlopen(req, timeout=15) as response:
            return json.loads(response.read().decode() or "[]")
    except urllib.error.HTTPError as exc:
        try:
            body = exc.read().decode("utf-8", errors="replace")
        except Exception:
            body = ""
        detail = body or str(exc)
        raise RuntimeError(f"Supabase error: HTTP {exc.code}: {detail}") from exc
    except Exception as exc:
        raise RuntimeError(f"Supabase error: {exc}") from exc

# Colunas da análise v2 (migração 20261014140000). Se ainda não existirem no banco, o salvamento
# degrada: grava sem elas e devolve tudo na resposta, em vez de perder a reunião.
V2_COLUMNS = ("analysis_version", "decisions_detail", "actions_detail", "evidence_summary", "client_link", "client_suggestion")

def _schema_error(exc: RuntimeError, names: tuple) -> bool:
    message = str(exc).lower()
    return "400" in message and any(x in message for x in ("schema cache", "pgrst204", "pgrst") + tuple(names))

def _save_meeting(data: dict, user=None):
    fields = ["source_type","file_name","meeting_title","context","is_demo","demo_scenario","transcript","summary","sentiment","sentiment_confidence","opportunity","risk","risk_score","opportunity_score","opportunity_signals","risk_signals","priority","impact","why_it_matters","intent","objections","products","evidence","decisions","pending_actions","important_signals","insights","topics","financial_data","participants","next_move","owner","deadline","model"]
    payload = {key: data.get(key) for key in fields}
    payload["client_name"] = data.get("client_name") or "Cliente não identificado"
    for key in V2_COLUMNS:  # só quando presentes: null violaria o NOT NULL das colunas jsonb
        if data.get(key) is not None:
            payload[key] = data[key]
    if data.get("client_id"):  # a coluna existe desde a Etapa 2; o gatilho do banco confere o espaço do cliente
        payload["client_id"] = data["client_id"]
    if data.get("client_link") == "unlinked" and not data.get("client_suggestion"):
        payload.pop("client_link", None)  # padrão do banco; evita enviar coluna nova sem necessidade
        payload.pop("client_suggestion", None)
    if user is not None:
        # Dono e organização vêm do token verificado, nunca do corpo da requisição.
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
            result = _supabase_request("POST", "meetings", attempt, user=user)
            break
        except RuntimeError as exc:
            if step == 0 and any(k in attempt for k in V2_COLUMNS) and _schema_error(exc, V2_COLUMNS):
                for key in V2_COLUMNS:
                    attempt.pop(key, None)
                continue
            if step <= 1 and not rehydrate and _schema_error(exc, ("insights", "topics")):
                # PostgREST can briefly serve a stale schema cache immediately after a migration. If that
                # happens for the JSONB columns, keep the meeting usable by persisting the complete insight
                # set through the existing evidence JSONB column and retrying with the stable schema.
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
        # The response may not expose the newly-added columns during a stale cache window. Rehydrate them
        # so the frontend can immediately render the full analysis from this request.
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

@router.get("/api/meetings")
def meetings(limit: int = 50, org_id: str | None = None, user=Depends(sec.current_user)):
    limit = max(1, min(limit, 100))
    space = ""
    if user is not None and org_id:
        # Espaço de trabalho: "personal" (sem organização) ou uma organização. O RLS continua
        # decidindo o que o usuário pode ver; o filtro só escolhe o recorte.
        if org_id == "personal":
            space = "&org_id=is.null"
        elif sec.UUID_RE.match(org_id):
            space = f"&org_id=eq.{org_id.lower()}"
        else:
            raise HTTPException(status_code=400, detail="Espaço inválido.")
    try:
        result = _supabase_request("GET", f"meetings?select=*&order=created_at.desc&limit={limit}{space}", user=user)
        return {"ok": True, "persisted": result is not None, "meetings": sec.redact_meetings(result or [], user)}
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

@router.post("/api/meetings")
def create_meeting(payload: dict, user=Depends(sec.current_user)):
    if not payload.get("transcript"):
        raise HTTPException(status_code=400, detail="transcript é obrigatório")
    sec.require_org_permission(user, payload.get("org_id"), "meetings.write")
    try:
        saved = _save_meeting(payload, user)
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    sec.audit(user, "meeting.create", payload.get("org_id"), "meeting", (saved.get("meeting") or {}).get("id"))
    return {"ok": True, **saved}
