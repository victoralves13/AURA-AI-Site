"""Reuniões ao vivo — camada HTTP: sessões, pedaços, transcrição, alertas, consolidação e áudio."""
from fastapi import APIRouter, Depends

from aura.core import security as sec
from aura.core.errors import require_user
from aura.features.live import alerts, consolidation, service, transcription
from aura.features.live.schemas import (ChunkRegister, ConsolidateRequest, LiveCreate, LiveUpdate, ScanRequest, TranscribeRequest,
                                        UploadUrlRequest)

router = APIRouter()


@router.post("/api/live")
def create_session(payload: LiveCreate, user=Depends(sec.current_user)):
    return service.create_session(require_user(user), payload)


@router.get("/api/live")
def list_sessions(org_id: str | None = None, status: str | None = None, limit: int = 50, user=Depends(sec.current_user)):
    return service.list_sessions(require_user(user), org_id, status, limit)


@router.get("/api/live/{session_id}")
def get_session(session_id: str, user=Depends(sec.current_user)):
    return service.read_session(require_user(user), session_id)


@router.patch("/api/live/{session_id}")
def update_session(session_id: str, payload: LiveUpdate, user=Depends(sec.current_user)):
    return service.update_session(require_user(user), session_id, payload)


@router.post("/api/live/{session_id}/chunks/upload-url")
def chunk_upload_url(session_id: str, payload: UploadUrlRequest, user=Depends(sec.current_user)):
    return service.chunk_upload_url(require_user(user), session_id, payload)


@router.post("/api/live/{session_id}/chunks")
def register_chunk(session_id: str, payload: ChunkRegister, user=Depends(sec.current_user)):
    return service.register_chunk(require_user(user), session_id, payload)


@router.post("/api/live/{session_id}/finish")
def finish_session(session_id: str, user=Depends(sec.current_user)):
    return service.finish_session(require_user(user), session_id)


@router.delete("/api/live/{session_id}")
def delete_session(session_id: str, user=Depends(sec.current_user)):
    return service.delete_session(require_user(user), session_id)


@router.post("/api/live/{session_id}/transcribe")
def transcribe(session_id: str, payload: TranscribeRequest | None = None, user=Depends(sec.current_user)):
    return transcription.transcribe(require_user(user), session_id, payload)


@router.get("/api/live/{session_id}/transcript")
def transcript(session_id: str, user=Depends(sec.current_user)):
    return transcription.transcript(require_user(user), session_id)


@router.post("/api/live/{session_id}/alerts/scan")
def scan(session_id: str, payload: ScanRequest | None = None, user=Depends(sec.current_user)):
    return alerts.scan(require_user(user), session_id, payload)


@router.post("/api/live/{session_id}/consolidate")
def consolidate(session_id: str, payload: ConsolidateRequest | None = None, user=Depends(sec.current_user)):
    return consolidation.consolidate(require_user(user), session_id, payload)


@router.delete("/api/live/{session_id}/audio")
def delete_audio(session_id: str, user=Depends(sec.current_user)):
    return service.delete_audio(require_user(user), session_id)
