"""Análise — camada HTTP: transcrição colada, URL de envio do áudio e análise do áudio já enviado."""
from fastapi import APIRouter, Depends

from aura.core import security as sec
from aura.features.analysis import service
from aura.features.analysis.schemas import AudioUploadRequest, StoredAudioRequest

router = APIRouter()


@router.post("/api/analyze-transcript")
def analyze_transcript_endpoint(payload: dict, user=Depends(sec.current_user)):
    return service.analyze_transcript(user, payload)


@router.post("/api/audio-upload-url")
def audio_upload_url(payload: AudioUploadRequest, user=Depends(sec.current_user)):
    return service.audio_upload_url(user, payload)


@router.post("/api/analyze-stored-audio")
def analyze_stored_audio(payload: StoredAudioRequest, user=Depends(sec.current_user)):
    return service.analyze_stored_audio(user, payload)
