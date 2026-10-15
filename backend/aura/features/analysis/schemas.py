"""Análise — modelos dos pedidos."""
from pydantic import BaseModel


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
    org_id: str | None = None
    client_id: str | None = None
    group_name: str | None = None
    meeting_title: str | None = None
    participants: list[str] | str | None = None
    meeting_date: str | None = None
