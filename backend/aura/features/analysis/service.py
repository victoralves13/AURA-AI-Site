"""AURA AI — análise de reuniões (transcrição colada ou áudio): montagem do resultado e casos de uso (regras).

A IA em si está em `engine.py`; o áudio vive no bucket (repository.py); a gravação da reunião é de `aura.features.meetings`.
"""
import os
import re
import tempfile
import uuid
from pathlib import Path

from aura.core import security as sec
from aura.core.errors import AppError
from aura.features.actions import service as actions_mod
from aura.features.analysis import repository
from aura.features.analysis.schemas import AudioUploadRequest, StoredAudioRequest
from aura.features.clients import service as clients_mod
from aura.features.meetings.service import save_meeting

MAX_AUDIO_BYTES = 100 * 1024 * 1024
AUDIO_ALLOWED = {"audio/mpeg", "audio/wav", "audio/x-wav", "audio/mp4", "audio/x-m4a", "audio/webm", "audio/ogg", "audio/m4a", "video/mp4"}


def _clean(value: str | None) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def _clean_transcript(value: str | None) -> str:
    # Transcrições coladas mantêm as quebras de linha (falas, [MM:SS]); só se normalizam espaços e linhas em branco demais.
    text = (value or "").replace("\r\n", "\n").replace("\r", "\n")
    text = "\n".join(re.sub(r"[ \t\f\v]+", " ", line).strip() for line in text.split("\n"))
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def build_result(transcript: str, client_name: str, file_name: str, source_type: str, context: str = "Outro", transcription_meta: dict | None = None, is_demo: bool = False, demo_scenario: str | None = None, meeting_title: str | None = None, analysis_transcript: str | None = None, user=None, org_id: str | None = None):
    from aura.features.analysis.engine import analyze_transcript, build_product_fields
    analysis = analyze_transcript(analysis_transcript or transcript, context=context)
    fields = build_product_fields(analysis, analysis_transcript or transcript)
    # "Cliente não identificado" enviado pela interface é um marcador, não um nome digitado: nesse caso vale
    # o cliente que a IA encontrou na conversa (antes o marcador sobrescrevia o nome extraído).
    typed_client = _clean(client_name) if not clients_mod.is_placeholder(client_name) else ""
    resolved_client = typed_client or _clean(fields.get("client_name")) or "Cliente não identificado"
    resolved_title = _clean(meeting_title)
    if not resolved_title or resolved_title == "Análise por transcrição":
        resolved_title = resolved_client + " · " + (context or "Outro")
    result = {"ok": True, "source": source_type, "file_name": file_name, "meeting_title": resolved_title, "client_name": resolved_client, "context": _clean(context) or "Outro", "is_demo": bool(is_demo), "demo_scenario": demo_scenario, "transcript": transcript, "sentiment": fields["sentiment"], "sentiment_confidence": None, "model": fields["analysis_model"], "analysis_model": fields["analysis_model"], **fields}
    if transcription_meta:
        result["transcription"] = transcription_meta
    result["intent"] = f"{context or 'Outro'} · {fields['intent']}"
    link = clients_mod.link_for_new_meeting(user, org_id, typed_client or None, _clean(fields.get("client_name")) or None, is_demo=bool(is_demo))
    result.update(link)
    saved = save_meeting({**result, "source_type": source_type, "org_id": org_id}, user)
    if saved.get("meeting"):
        result["id"] = saved["meeting"].get("id")
        result["created_at"] = saved["meeting"].get("created_at")
    result.update(saved)
    if saved.get("meeting") and user is not None and not is_demo:
        # As ações viram registros acompanháveis (estado, responsável, prazo). Falha aqui nunca perde a análise.
        actions_mod.sync_for_meeting(user, {**result, "id": result.get("id"), "org_id": org_id})
    return result



def analyze_transcript(user, payload: dict) -> dict:
    transcript = _clean_transcript(payload.get("transcript"))
    if len(transcript) < 4:
        raise AppError(400, "transcript é obrigatório")
    org_id = payload.get("org_id") or None
    sec.require_org_permission(user, org_id, "meetings.write")
    sec.enforce_usage_limit(user)
    try:
        result = build_result(transcript, _clean(payload.get("client_name")), payload.get("meeting_title") or "transcript", "transcript", _clean(payload.get("context")) or "Outro", is_demo=bool(payload.get("is_demo")), demo_scenario=_clean(payload.get("demo_scenario")) or None, meeting_title=_clean(payload.get("meeting_title")) or "Análise por transcrição", user=user, org_id=org_id)
    except Exception as exc:
        raise AppError(502, str(exc)) from exc
    sec.audit(user, "analysis.transcript", org_id, "meeting", result.get("id"))
    return result


def audio_upload_url(user, payload: AudioUploadRequest) -> dict:
    if payload.size_bytes <= 0 or payload.size_bytes > MAX_AUDIO_BYTES:
        raise AppError(413, "Áudio deve ter até 100 MB.")
    if payload.content_type not in AUDIO_ALLOWED and not payload.file_name.lower().endswith(sec.AUDIO_EXTENSIONS):
        raise AppError(400, "Formato de áudio não suportado.")
    org_id = payload.org_id or None
    sec.require_org_permission(user, org_id, "meetings.write")
    suffix = sec.audio_suffix(payload.file_name)
    if user is not None:
        path = sec.audio_path_for(user, org_id, uuid.uuid4().hex, suffix)
    else:
        path = f"meetings/{uuid.uuid4().hex}{suffix}"
    try:
        signed_url, token = repository.create_upload_url(path)
    except Exception as exc:
        raise AppError(502, str(exc)) from exc
    sec.audit(user, "audio.upload_url", org_id, "audio", path)
    return {"ok": True, "bucket": repository.AUDIO_BUCKET, "path": path, "signed_url": signed_url, "token": token}


def analyze_stored_audio(user, payload: StoredAudioRequest) -> dict:
    org_id = None
    if user is not None:
        # O caminho precisa pertencer ao usuário (users/<id>/...) ou a uma organização dele (orgs/<id>/...).
        org_id = sec.authorize_audio_path(user, payload.path)
        sec.enforce_usage_limit(user)
    elif not payload.path.startswith("meetings/"):
        raise AppError(400, "Caminho de áudio inválido.")
    temp_path = None
    try:
        suffix = Path(payload.file_name).suffix or ".mp3"
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as temp:
            temp_path = temp.name
        repository.download_stored_audio(payload.path, temp_path)
        from aura.features.analysis.engine import transcribe_audio
        transcript, meta = transcribe_audio(temp_path)
        if not transcript:
            raise AppError(422, "Não foi possível transcrever o áudio.")
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
        result = build_result(display_transcript, _clean(payload.client_name), payload.file_name, "audio", _clean(payload.context) or "Outro", meta, meeting_title=payload.file_name, analysis_transcript=timed_transcript or transcript, user=user, org_id=org_id)
        sec.audit(user, "analysis.audio", org_id, "meeting", result.get("id"))
        return result
    except AppError:
        raise
    except Exception as exc:
        raise AppError(502, str(exc)) from exc
    finally:
        if temp_path:
            try:
                os.remove(temp_path)
            except OSError:
                pass
