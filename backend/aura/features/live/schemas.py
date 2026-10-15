"""Reuniões ao vivo — modelos dos pedidos."""
from pydantic import BaseModel


class LiveCreate(BaseModel):
    consent: bool = False
    title: str | None = None
    context: str | None = None
    client_name: str | None = None
    org_id: str | None = None
    alerts_enabled: bool = True


class LiveUpdate(BaseModel):
    title: str | None = None
    context: str | None = None
    client_name: str | None = None
    alerts_enabled: bool | None = None
    status: str | None = None


class UploadUrlRequest(BaseModel):
    seq: int
    ext: str | None = None


class ChunkRegister(BaseModel):
    seq: int
    duration_ms: int
    ext: str | None = None


class TranscribeRequest(BaseModel):
    retry_failed: bool = False


class ScanRequest(BaseModel):
    from_seq: int = 0


class ConsolidateRequest(BaseModel):
    allow_gaps: bool = False
    retry_failed: bool = False
