import json
import os
import re
import tempfile
import uuid
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

try:
    from supabase import Client, create_client
except Exception:
    Client = Any
    create_client = None

ROOT = Path(__file__).resolve().parents[1]\n# Vercel can load api/index.py as a standalone function module, so the api/\n# directory is not guaranteed to be on sys.path. Keep the existing module\n# layout and make the sibling engine import explicit and reliable.\nAPI_DIR = ROOT / "api"\nif str(API_DIR) not in os.sys.path:\n    os.sys.path.insert(0, str(API_DIR))\napp = FastAPI(title="AURA AI API", version="1.0.0-cloud")
handler = app
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

MAX_AUDIO_BYTES = 100 * 1024 * 1024
AUDIO_BUCKET = os.getenv("AURA_AUDIO_BUCKET", "aura-audio")
AUDIO_ALLOWED = {"audio/mpeg","audio/wav","audio/x-wav","audio/mp4","audio/x-m4a","audio/webm","audio/ogg","audio/m4a","video/mp4"}

class AudioUploadRequest(BaseModel):
    file_name: str
    content_type: str = "audio/mpeg"
    size_bytes: int = 0

class StoredAudioRequest(BaseModel):
    path: str
    file_name: str = "reuniao"
    client_name: str = "Cliente não identificado"
    context: str = "Outro"

def _clean(value: str | None) -> str:
    return re.sub(r"\s+", " ", value or "").strip()

def _supabase() -> Client:
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SECRET_KEY") or os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key or create_client is None:
        raise RuntimeError("Supabase server credentials não configuradas.")
    return create_client(url, key)

def _supabase_request(method: str, path: str, payload=None):
    url, key = os.getenv("SUPABASE_URL"), (os.getenv("SUPABASE_SECRET_KEY") or os.getenv("SUPABASE_SERVICE_ROLE_KEY"))
    if not url or not key:
        return None
    import urllib.request
    headers = {"apikey": key, "Authorization": f"Bearer {key}", "Content-Type": "application/json", "Prefer": "return=representation"}
    req = urllib.request.Request(url.rstrip("/") + "/rest/v1/" + path, method=method, headers=headers)
    if payload is not None:
        req.data = json.dumps(payload, ensure_ascii=False).encode()
    try:
        with urllib.request.urlopen(req, timeout=15) as response:
            return json.loads(response.read().decode() or "[]")
    except Exception as exc:
        raise RuntimeError(f"Supabase error: {exc}") from exc

def _save_meeting(data: dict):
    fields = ["source_type","file_name","meeting_title","context","is_demo","demo_scenario","transcript","summary","sentiment","sentiment_confidence","opportunity","risk","risk_score","opportunity_score","opportunity_signals","risk_signals","priority","impact","why_it_matters","intent","objections","products","evidence","decisions","pending_actions","important_signals","participants","next_move","owner","deadline","model"]
    payload = {key: data.get(key) for key in fields}
    payload["client_name"] = data.get("client_name") or "Cliente não identificado"
    result = _supabase_request("POST", "meetings", payload)
    if result is None:
        return {"persisted": False, "storage": "local-only"}
    return {"persisted": True, "storage": "supabase", "meeting": result[0] if result else None}

def _create_upload_url(path: str):
    response = _supabase().storage.from_(AUDIO_BUCKET).create_signed_upload_url(path, options={"upsert": "false"})
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

def _build_result(transcript: str, client_name: str, file_name: str, source_type: str, context: str = "Outro", transcription_meta: dict | None = None, is_demo: bool = False, demo_scenario: str | None = None, meeting_title: str | None = None, analysis_transcript: str | None = None):
    from openai_engine import analyze_transcript, build_product_fields
    analysis = analyze_transcript(analysis_transcript or transcript, context=context)
    fields = build_product_fields(analysis)
    result = {"ok": True, "source": source_type, "file_name": file_name, "meeting_title": meeting_title or file_name, "client_name": client_name or "Cliente não identificado", "context": context or "Outro", "is_demo": bool(is_demo), "demo_scenario": demo_scenario, "transcript": transcript, "sentiment": fields["sentiment"], "sentiment_confidence": 0, "model": fields["analysis_model"], "analysis_model": fields["analysis_model"], **fields}
    if transcription_meta:
        result["transcription"] = transcription_meta
    result["intent"] = f"{context or 'Outro'} · {fields['intent']}"
    result.update(_save_meeting({**result, "source_type": source_type}))
    return result

@app.get("/api/health")
def health():
    return {"ok": True, "service": "aura-ai", "version": "1.0.0-cloud", "engine": "OpenAI + AURA Intelligence", "openai_configured": bool(os.getenv("OPENAI_API_KEY")), "supabase_configured": bool(os.getenv("SUPABASE_URL") and (os.getenv("SUPABASE_SECRET_KEY") or os.getenv("SUPABASE_SERVICE_ROLE_KEY"))), "audio_storage": AUDIO_BUCKET}

@app.get("/api/meetings")
def meetings(limit: int = 50):
    limit = max(1, min(limit, 100))
    try:
        result = _supabase_request("GET", f"meetings?select=*&order=created_at.desc&limit={limit}")
        return {"ok": True, "persisted": result is not None, "meetings": result or []}
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

@app.post("/api/meetings")
def create_meeting(payload: dict):
    if not payload.get("transcript"):
        raise HTTPException(status_code=400, detail="transcript é obrigatório")
    try:
        return {"ok": True, **_save_meeting(payload)}
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

@app.post("/api/analyze-transcript")
def analyze_transcript_endpoint(payload: dict):
    transcript = _clean(payload.get("transcript"))
    if len(transcript) < 4:
        raise HTTPException(status_code=400, detail="transcript é obrigatório")
    try:
        return _build_result(transcript, _clean(payload.get("client_name")), payload.get("meeting_title") or "transcript", "transcript", _clean(payload.get("context")) or "Outro", is_demo=bool(payload.get("is_demo")), demo_scenario=_clean(payload.get("demo_scenario")) or None, meeting_title=_clean(payload.get("meeting_title")) or "Análise por transcrição")
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

@app.post("/api/audio-upload-url")
def audio_upload_url(payload: AudioUploadRequest):
    if payload.size_bytes <= 0 or payload.size_bytes > MAX_AUDIO_BYTES:
        raise HTTPException(status_code=413, detail="Áudio deve ter até 100 MB.")
    if payload.content_type not in AUDIO_ALLOWED and not payload.file_name.lower().endswith((".mp3",".wav",".m4a",".mp4",".webm",".ogg")):
        raise HTTPException(status_code=400, detail="Formato de áudio não suportado.")
    suffix = Path(payload.file_name).suffix.lower() or ".mp3"
    path = f"meetings/{uuid.uuid4().hex}{suffix}"
    try:
        signed_url, token = _create_upload_url(path)
        return {"ok": True, "bucket": AUDIO_BUCKET, "path": path, "signed_url": signed_url, "token": token}
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

@app.post("/api/analyze-stored-audio")
def analyze_stored_audio(payload: StoredAudioRequest):
    if not payload.path.startswith("meetings/"):
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
        timed_transcript = "\n".join(f"[{stamp(s.get('start', 0))}] {s.get('text', '').strip()}" for s in segments if s.get('text'))
        return _build_result(transcript, _clean(payload.client_name), payload.file_name, "audio", _clean(payload.context) or "Outro", meta, meeting_title=payload.file_name, analysis_transcript=timed_transcript or transcript)
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

app.mount("/", StaticFiles(directory=ROOT, html=True), name="frontend")
