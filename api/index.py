import json
import os
import re
import tempfile
import uuid
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

try:
    from supabase import Client, create_client
except Exception:
    Client = Any
    create_client = None

ROOT = Path(__file__).resolve().parents[1]
# Vercel can load api/index.py as a standalone function module, so the api/
# directory is not guaranteed to be on sys.path. Keep the existing module
# layout and make the sibling engine import explicit and reliable.
API_DIR = ROOT / "api"
if str(API_DIR) not in os.sys.path:
    os.sys.path.insert(0, str(API_DIR))
import security as sec
from orgs import router as orgs_router

app = FastAPI(title="AURA AI API", version="1.0.0-cloud")
handler = app
app.include_router(orgs_router)
# O front-end é servido pela mesma origem, então CORS fica desligado por padrão.
# Para liberar origens específicas: AURA_ALLOWED_ORIGINS="https://app.exemplo.com,https://outra.com"
if sec.allowed_origins():
    app.add_middleware(CORSMiddleware, allow_origins=sec.allowed_origins(), allow_methods=["GET", "POST"], allow_headers=["Authorization", "Content-Type"])

MAX_AUDIO_BYTES = 100 * 1024 * 1024
AUDIO_BUCKET = os.getenv("AURA_AUDIO_BUCKET", "aura-audio")
AUDIO_ALLOWED = {"audio/mpeg","audio/wav","audio/x-wav","audio/mp4","audio/x-m4a","audio/webm","audio/ogg","audio/m4a","video/mp4"}

class AudioUploadRequest(BaseModel):
    file_name: str
    content_type: str = "audio/mpeg"
    size_bytes: int = 0
    org_id: str | None = None

class StoredAudioRequest(BaseModel):
    path: str
    file_name: str = "reuniao"
    client_name: str = "Cliente não identificado"
    context: str = "Outro"

class OrgCreateRequest(BaseModel):
    name: str

def _clean(value: str | None) -> str:
    return re.sub(r"\s+", " ", value or "").strip()

def _clean_transcript(value: str | None) -> str:
    # Pasted transcripts keep their line breaks (speaker turns, [MM:SS] stamps);
    # only runs of spaces/tabs and excess blank lines are normalised.
    text = (value or "").replace("\r\n", "\n").replace("\r", "\n")
    text = "\n".join(re.sub(r"[ \t\f\v]+", " ", line).strip() for line in text.split("\n"))
    return re.sub(r"\n{3,}", "\n\n", text).strip()

def _supabase() -> Client:
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SECRET_KEY") or os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key or create_client is None:
        raise RuntimeError("Supabase server credentials não configuradas.")
    return create_client(url, key)

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
V2_COLUMNS = ("analysis_version", "decisions_detail", "actions_detail", "evidence_summary")

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
    return {"persisted": True, "storage": "supabase", "meeting": result[0] if result else None}

def _create_upload_url(path: str):
    response = _supabase().storage.from_(AUDIO_BUCKET).create_signed_upload_url(path)
    data = getattr(response, "data", response)
    if isinstance(data, dict):
        token = data.get("token")
        signed_url = data.get("signed_url") or data.get("signedURL")
        if signed_url:
            return signed_url, token
    if hasattr(data, "token"):
        return getattr(data, "signed_url", None) or getattr(data, "signedURL", None), data.token
    raise RuntimeError("Supabase não retornou uma URL de upload assinada.")

def _create_download_url(path: str):
    response = _supabase().storage.from_(AUDIO_BUCKET).create_signed_url(path, 3600)
    data = getattr(response, "data", response)
    if isinstance(data, dict):
        return data.get("signedURL") or data.get("signed_url")
    return getattr(data, "signedURL", None) or getattr(data, "signed_url", None)

def _download_stored_audio(path: str, target: str):
    url = _create_download_url(path)
    if not url:
        raise RuntimeError("Não foi possível gerar a URL temporária do áudio.")
    import urllib.request
    urllib.request.urlretrieve(url, target)

def _build_result(transcript: str, client_name: str, file_name: str, source_type: str, context: str = "Outro", transcription_meta: dict | None = None, is_demo: bool = False, demo_scenario: str | None = None, meeting_title: str | None = None, analysis_transcript: str | None = None, user=None, org_id: str | None = None):
    from openai_engine import analyze_transcript, build_product_fields
    analysis = analyze_transcript(analysis_transcript or transcript, context=context)
    fields = build_product_fields(analysis, analysis_transcript or transcript)
    resolved_client = _clean(client_name) or _clean(fields.get("client_name")) or "Cliente não identificado"
    resolved_title = _clean(meeting_title)
    if not resolved_title or resolved_title == "Análise por transcrição":
        resolved_title = resolved_client + " · " + (context or "Outro")
    result = {"ok": True, "source": source_type, "file_name": file_name, "meeting_title": resolved_title, "client_name": resolved_client, "context": _clean(context) or "Outro", "is_demo": bool(is_demo), "demo_scenario": demo_scenario, "transcript": transcript, "sentiment": fields["sentiment"], "sentiment_confidence": None, "model": fields["analysis_model"], "analysis_model": fields["analysis_model"], **fields}
    if transcription_meta:
        result["transcription"] = transcription_meta
    result["intent"] = f"{context or 'Outro'} · {fields['intent']}"
    saved = _save_meeting({**result, "source_type": source_type, "org_id": org_id}, user)
    if saved.get("meeting"):
        result["id"] = saved["meeting"].get("id")
        result["created_at"] = saved["meeting"].get("created_at")
    result.update(saved)
    return result

@app.get("/api/health")
def health():
    return {"ok": True, "service": "aura-ai", "version": "1.0.0-cloud", "engine": "OpenAI + AURA Intelligence", "openai_configured": bool(os.getenv("OPENAI_API_KEY")), "supabase_configured": bool(os.getenv("SUPABASE_URL") and (os.getenv("SUPABASE_SECRET_KEY") or os.getenv("SUPABASE_SERVICE_ROLE_KEY"))), "audio_storage": AUDIO_BUCKET, "auth_required": sec.auth_required(), "auth_configured": bool(sec.supabase_url() and sec.publishable_key())}

@app.get("/api/config")
def public_config():
    # Valores públicos por natureza (a chave "publishable" do Supabase é feita para o navegador).
    return {"auth_required": sec.auth_required(), "supabase_url": sec.supabase_url() or None, "supabase_publishable_key": sec.publishable_key() or None}

@app.get("/api/me")
def me(user=Depends(sec.current_user)):
    if user is None:
        return {"ok": True, "auth_required": False, "user": None, "organizations": []}
    try:
        rows = sec.user_rest(user, "GET", f"memberships?select=role,org_id,organizations(id,name)&user_id=eq.{user.id}") or []
        access = sec.load_access(user)
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail="Não foi possível carregar suas organizações.") from exc
    orgs = [{"id": r["org_id"], "name": (r.get("organizations") or {}).get("name"), "role": r.get("role"),
             "permissions": sorted(access.get(r["org_id"], []))} for r in rows]
    return {"ok": True, "auth_required": True, "user": {"id": user.id, "email": user.email, "email_confirmed": user.email_confirmed}, "organizations": orgs}

@app.post("/api/orgs")
def create_org(payload: OrgCreateRequest, user=Depends(sec.current_user)):
    if user is None:
        raise HTTPException(status_code=401, detail="Autenticação necessária para criar organizações.")
    name = _clean(payload.name)
    if not 1 <= len(name) <= 120:
        raise HTTPException(status_code=400, detail="O nome da organização deve ter entre 1 e 120 caracteres.")
    try:
        org_id = sec.service_rest("POST", "organizations", {"name": name, "created_by": user.id})[0]["id"]
        try:
            sec.service_rest("POST", "memberships", {"org_id": org_id, "user_id": user.id, "role": "admin"})
        except Exception:
            sec.service_rest("DELETE", f"organizations?id=eq.{org_id}")
            raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail="Não foi possível criar a organização.") from exc
    sec.audit(user, "org.create", org_id, "organization", org_id)
    return {"ok": True, "organization": {"id": org_id, "name": name, "role": "admin"}}

@app.get("/api/meetings")
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

@app.post("/api/meetings")
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

@app.post("/api/analyze-transcript")
def analyze_transcript_endpoint(payload: dict, user=Depends(sec.current_user)):
    transcript = _clean_transcript(payload.get("transcript"))
    if len(transcript) < 4:
        raise HTTPException(status_code=400, detail="transcript é obrigatório")
    org_id = payload.get("org_id") or None
    sec.require_org_permission(user, org_id, "meetings.write")
    sec.enforce_usage_limit(user)
    try:
        result = _build_result(transcript, _clean(payload.get("client_name")), payload.get("meeting_title") or "transcript", "transcript", _clean(payload.get("context")) or "Outro", is_demo=bool(payload.get("is_demo")), demo_scenario=_clean(payload.get("demo_scenario")) or None, meeting_title=_clean(payload.get("meeting_title")) or "Análise por transcrição", user=user, org_id=org_id)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    sec.audit(user, "analysis.transcript", org_id, "meeting", result.get("id"))
    return result

@app.post("/api/audio-upload-url")
def audio_upload_url(payload: AudioUploadRequest, user=Depends(sec.current_user)):
    if payload.size_bytes <= 0 or payload.size_bytes > MAX_AUDIO_BYTES:
        raise HTTPException(status_code=413, detail="Áudio deve ter até 100 MB.")
    if payload.content_type not in AUDIO_ALLOWED and not payload.file_name.lower().endswith(sec.AUDIO_EXTENSIONS):
        raise HTTPException(status_code=400, detail="Formato de áudio não suportado.")
    org_id = payload.org_id or None
    sec.require_org_permission(user, org_id, "meetings.write")
    suffix = sec.audio_suffix(payload.file_name)
    if user is not None:
        path = sec.audio_path_for(user, org_id, uuid.uuid4().hex, suffix)
    else:
        path = f"meetings/{uuid.uuid4().hex}{suffix}"
    try:
        signed_url, token = _create_upload_url(path)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    sec.audit(user, "audio.upload_url", org_id, "audio", path)
    return {"ok": True, "bucket": AUDIO_BUCKET, "path": path, "signed_url": signed_url, "token": token}

@app.post("/api/analyze-stored-audio")
def analyze_stored_audio(payload: StoredAudioRequest, user=Depends(sec.current_user)):
    org_id = None
    if user is not None:
        # O caminho precisa pertencer ao usuário (users/<id>/...) ou a uma organização dele (orgs/<id>/...).
        org_id = sec.authorize_audio_path(user, payload.path)
        sec.enforce_usage_limit(user)
    elif not payload.path.startswith("meetings/"):
        raise HTTPException(status_code=400, detail="Caminho de áudio inválido.")
    temp_path = None
    try:
        suffix = Path(payload.file_name).suffix or ".mp3"
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as temp:
            temp_path = temp.name
        _download_stored_audio(payload.path, temp_path)
        from openai_engine import transcribe_audio
        transcript, meta = transcribe_audio(temp_path)
        if not transcript:
            raise HTTPException(status_code=422, detail="Não foi possível transcrever o áudio.")
        segments = meta.get("segments") or []
        def stamp(seconds):
            total = max(0, int(seconds))
            hours, rem = divmod(total, 3600)
            minutes, secs = divmod(rem, 60)
            return f"{hours:02d}:{minutes:02d}:{secs:02d}" if hours else f"{minutes:02d}:{secs:02d}"
        timed_transcript = "\n".join(
            f"[{stamp(s.get('start', 0))}] [{s.get('speaker')}] {s.get('text', '').strip()}"
            if s.get('speaker')
            else f"[{stamp(s.get('start', 0))}] {s.get('text', '').strip()}"
            for s in segments
            if s.get('text')
        )
        if timed_transcript:
            meta = {**meta, "plain_text": transcript}
        display_transcript = timed_transcript or transcript
        result = _build_result(display_transcript, _clean(payload.client_name), payload.file_name, "audio", _clean(payload.context) or "Outro", meta, meeting_title=payload.file_name, analysis_transcript=timed_transcript or transcript, user=user, org_id=org_id)
        sec.audit(user, "analysis.audio", org_id, "meeting", result.get("id"))
        return result
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    finally:
        if temp_path:
            try:
                os.remove(temp_path)
            except OSError:
                pass

# Serve só o front-end público (html/css/js/imagens na raiz); nunca api/, supabase/, .git, .env etc.
app.mount("/", sec.PublicFiles(directory=ROOT, html=True), name="frontend")
