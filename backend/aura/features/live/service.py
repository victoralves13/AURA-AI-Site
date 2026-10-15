"""AURA AI — reuniões ao vivo: sessões de gravação e pedaços de áudio (regras).

Fluxo: o navegador cria a sessão (com o consentimento obrigatório), grava em pedaços de ~30 s, pede uma URL assinada para
cada pedaço, envia o áudio DIRETO ao bucket privado e depois registra o pedaço aqui. Transcrição, alertas e consolidação em uma
reunião estão em `transcription.py`, `alerts.py` e `consolidation.py`.

Regras:
  * A sessão é privada de quem a iniciou (RLS). Só o backend muda estado final, duração e vínculo com a reunião.
  * O caminho do áudio é SEMPRE montado aqui a partir da sessão e do número do pedaço (o cliente nunca escolhe o caminho),
    e só se registra um pedaço cujo arquivo realmente chegou ao bucket. Registrar o mesmo pedaço de novo é seguro (idempotente).
  * Sessão sem sinal de vida vira "interrompida" (não se perde nada: dá para finalizar depois).
  * Apagar a sessão apaga primeiro o áudio no bucket; se isso falhar, nada é apagado do banco (para tentar de novo).
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone

from aura.core import security as sec
from aura.core import storage
from aura.core.errors import AppError
from aura.features.live import repository
from aura.features.live.schemas import ChunkRegister, LiveCreate, LiveUpdate, UploadUrlRequest

log = logging.getLogger("aura.live")

MAX_SEQ = 399
MAX_CHUNK_BYTES = 25 * 1024 * 1024
MAX_CHUNK_MS = 120_000
EXTENSIONS = (".webm", ".ogg", ".m4a", ".mp4", ".wav", ".mp3")
RECORDING_SILENCE = timedelta(minutes=10)   # gravando sem nenhum sinal por tanto tempo = aba/aparelho caiu
PAUSE_LIMIT = timedelta(hours=6)
ACCEPTING = ("recording", "paused", "processing")
USER_STATUS = ("recording", "paused")
CONTEXTS_MAX = 60
GENERIC = repository.GENERIC


def _uuid(value, what: str) -> str:
    if not isinstance(value, str) or not sec.UUID_RE.match(value):
        raise AppError(400, f"{what} inválido.")
    return value.lower()


def _clean(value, size: int) -> str:
    return " ".join(str(value or "").split())[:size]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value) -> datetime | None:
    try:
        d = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def chunk_path(owner_id: str, org_id: str | None, session_id: str, seq: int, ext: str) -> str:
    scope = f"orgs/{org_id}" if org_id else f"users/{owner_id}"
    return f"{scope}/live/{session_id}/{seq:04d}{ext}"


def _seq(value) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= MAX_SEQ:
        raise AppError(400, f"O número do pedaço deve ir de 0 a {MAX_SEQ}.")
    return value


def _ext(value) -> str:
    ext = (value or ".webm").lower()
    ext = ext if ext.startswith(".") else "." + ext
    if ext not in EXTENSIONS:
        raise AppError(400, "Formato de áudio não suportado.")
    return ext


def _stale(session: dict, now: datetime) -> bool:
    """Gravando sem sinal por 10 min (ou pausada por mais de 6 h) = interrompida."""
    marks = [d for d in (_iso(session.get("last_chunk_at")), _iso(session.get("updated_at")), _iso(session.get("started_at"))) if d]
    if not marks:
        return False
    last = max(marks)
    if session.get("status") == "recording":
        return now - last > RECORDING_SILENCE
    if session.get("status") == "paused":
        return now - last > PAUSE_LIMIT
    return False


def _sweep(sessions: list[dict]) -> list[dict]:
    """Marca como interrompidas as sessões sem sinal de vida. Nunca falha a chamada por causa disso."""
    now = _now()
    stale = [s for s in sessions if _stale(s, now)]
    if not stale:
        return sessions
    try:
        changed = repository.abandon_sessions(",".join(s["id"] for s in stale))  # só o que de fato mudou (outra chamada pode ter encerrado no meio)
        for s in stale:
            if s["id"] in changed:
                s["status"] = "abandoned"
    except RuntimeError as exc:
        log.warning("sessões ao vivo não marcadas como interrompidas: %s", exc)
    return sessions


def retention_days() -> int:
    """Dias que o áudio de uma gravação ENCERRADA fica guardado (0 = guarda até a pessoa apagar). Padrão: 0."""
    try:
        return max(0, int(os.getenv("AURA_LIVE_AUDIO_RETENTION_DAYS", "0") or "0"))
    except ValueError:
        return 0


def delete_audio_of(user: sec.AuthUser, session: dict, reason: str = "user") -> int:
    """Apaga o ÁUDIO da gravação (o texto, a sessão e a reunião ficam). O áudio sai primeiro; só depois se marca no banco."""
    paths = repository.chunk_paths(user, session["id"])
    storage.delete_objects(paths)
    repository.set_audio_deleted(session["id"], _now().isoformat())
    session["audio_deleted_at"] = _now().isoformat()
    sec.audit(user, "live.audio_delete", session.get("org_id"), "live_session", session["id"], {"chunks": len(paths), "reason": reason})
    return len(paths)


def _retention(user: sec.AuthUser, sessions: list[dict]) -> list[dict]:
    """Retenção preguiçosa (sem agendador): ao listar, apaga o áudio de gravações encerradas há mais que o prazo (no máximo 3 por vez)."""
    days = retention_days()
    if days <= 0:
        return sessions
    cutoff = _now() - timedelta(days=days)
    due = [s for s in sessions if s.get("status") == "ended" and not s.get("audio_deleted_at") and (_iso(s.get("ended_at")) or _now()) < cutoff][:3]
    for s in due:
        try:
            delete_audio_of(user, s, "retention")
        except Exception as exc:  # falhou: tenta de novo na próxima listagem; nada é perdido
            log.warning("retenção do áudio da gravação %s não aplicada: %s", s.get("id"), type(exc).__name__)
    return sessions


def get_session(user: sec.AuthUser, session_id: str) -> dict:
    row = repository.get_session_row(user, session_id)
    if row is None:
        raise AppError(404, repository.SESSION_NOT_FOUND)
    session = _sweep([row])[0]
    if session.get("org_id"):
        sec.require_org_permission(user, session["org_id"], "meetings.write")
    return session


def _public(session: dict) -> dict:
    return {k: v for k, v in session.items() if k != "owner_id"}


# ---------------------------------------------------------------------------
# Casos de uso da API
# ---------------------------------------------------------------------------
def create_session(user, payload: LiveCreate) -> dict:
    if payload.consent is not True:
        raise AppError(400, "Confirme que os participantes foram avisados de que a reunião está sendo gravada.")
    org = None if not payload.org_id or payload.org_id == "personal" else _uuid(payload.org_id, "Espaço")
    sec.require_org_permission(user, org, "meetings.write")
    row = {"owner_id": user.id, "org_id": org, "consent_at": _now().isoformat(), "alerts_enabled": bool(payload.alerts_enabled)}
    for key, size in (("title", 200), ("context", CONTEXTS_MAX), ("client_name", 200)):
        value = _clean(getattr(payload, key), size)
        if value:
            row[key] = value
    created = repository.insert_session(user, row)
    sec.audit(user, "live.start", org, "live_session", created.get("id"), {"alerts": bool(payload.alerts_enabled)})
    return {"ok": True, "session": _public(created)}


def list_sessions(user, org_id: str | None, status: str | None, limit: int) -> dict:
    where = ""
    if org_id:
        where += "&org_id=is.null" if org_id == "personal" else f"&org_id=eq.{_uuid(org_id, 'Espaço')}"
    if status:
        if status not in ("recording", "paused", "processing", "ended", "failed", "abandoned"):
            raise AppError(400, "Filtro de estado inválido.")
        where += f"&status=eq.{status}"
    rows = repository.list_sessions(user, where, max(1, min(limit, 100)))
    return {"ok": True, "sessions": [_public(s) for s in _retention(user, _sweep(rows))]}


def read_session(user, session_id: str) -> dict:
    sid = _uuid(session_id, "Gravação")
    session = get_session(user, sid)
    return {"ok": True, "session": _public(session), "chunks": repository.list_chunks(user, sid)}


def update_session(user, session_id: str, payload: LiveUpdate) -> dict:
    sid = _uuid(session_id, "Gravação")
    session = get_session(user, sid)
    data = payload.model_dump(exclude_unset=True)
    changes: dict = {}
    for key, size in (("title", 200), ("context", CONTEXTS_MAX), ("client_name", 200)):
        if key in data:
            value = _clean(data[key], size + 1)
            if len(value) > size or (key != "client_name" and not value):
                raise AppError(400, "Texto inválido ou longo demais.")
            changes[key] = value or None
    if "alerts_enabled" in data and data["alerts_enabled"] is not None:
        changes["alerts_enabled"] = bool(data["alerts_enabled"])
    if data.get("status") is not None:
        if data["status"] not in USER_STATUS:
            raise AppError(400, "Use recording ou paused (para encerrar, use /finish).")
        if data["status"] != session["status"]:
            changes["status"] = data["status"]
    if not changes:
        return {"ok": True, "session": _public(session)}
    row = repository.patch_session(user, sid, changes)
    if row is None:
        raise AppError(403, "Você não tem permissão para alterar esta gravação.")
    return {"ok": True, "session": _public({**session, **row})}


def chunk_upload_url(user, session_id: str, payload: UploadUrlRequest) -> dict:
    sid = _uuid(session_id, "Gravação")
    seq, ext = _seq(payload.seq), _ext(payload.ext)
    session = get_session(user, sid)
    if session["status"] not in ACCEPTING or session.get("audio_deleted_at"):
        raise AppError(409, repository.SESSION_CLOSED)
    path = chunk_path(session["owner_id"], session.get("org_id"), sid, seq, ext)
    try:
        url, token = storage.signed_upload(path)
    except Exception as exc:
        log.warning("URL de upload do pedaço não gerada: %s", type(exc).__name__)
        raise AppError(502, "Não foi possível preparar o envio do áudio. Tente novamente.") from exc
    return {"ok": True, "seq": seq, "path": path, "signed_url": url, "token": token}


def register_chunk(user, session_id: str, payload: ChunkRegister) -> dict:
    """Registra um pedaço depois de o áudio ter chegado ao bucket. Repetir a chamada é seguro."""
    sid = _uuid(session_id, "Gravação")
    seq, ext = _seq(payload.seq), _ext(payload.ext)
    if not isinstance(payload.duration_ms, int) or not 0 <= payload.duration_ms <= MAX_CHUNK_MS:
        raise AppError(400, "A duração do pedaço deve ir de 0 a 2 minutos.")
    session = get_session(user, sid)
    path = chunk_path(session["owner_id"], session.get("org_id"), sid, seq, ext)
    existing = repository.get_chunk(user, sid, seq)
    if existing:
        return {"ok": True, "duplicate": True, "chunk": existing}
    if session["status"] not in ACCEPTING or session.get("audio_deleted_at"):
        raise AppError(409, repository.SESSION_CLOSED)
    try:
        size = storage.object_size(path)
    except RuntimeError as exc:
        raise AppError(502, GENERIC) from exc
    if size is None:
        raise AppError(409, "O áudio deste pedaço ainda não chegou ao armazenamento. Envie-o e tente de novo.")
    if not 0 < size <= MAX_CHUNK_BYTES:
        raise AppError(400, "O áudio do pedaço está vazio ou grande demais.")
    row = {"session_id": sid, "seq": seq, "storage_path": path, "duration_ms": payload.duration_ms, "size_bytes": size}
    try:
        created = repository.insert_chunk(user, row)
        duplicate = False
    except AppError as exc:
        if exc.status_code != 409 or exc.detail != repository.DUPLICATE_CHUNK:
            raise
        created, duplicate = row, True  # outra chamada registrou ao mesmo tempo
    if not duplicate:
        _touch_session(sid)
    return {"ok": True, "duplicate": duplicate, "chunk": {k: created.get(k) for k in ("seq", "status", "duration_ms", "size_bytes")}}


def _touch_session(session_id: str) -> None:
    """Atualiza último sinal e duração total da sessão (campos do backend). Falha aqui não perde o pedaço."""
    try:
        repository.touch_session(session_id, _now().isoformat())
    except RuntimeError as exc:
        log.warning("sessão ao vivo não atualizada após o pedaço: %s", exc)


def finish_session(user, session_id: str) -> dict:
    """Pede o encerramento. Informa se faltam pedaços na sequência."""
    sid = _uuid(session_id, "Gravação")
    session = get_session(user, sid)
    chunks = repository.list_chunks(user, sid)
    seqs = {c["seq"] for c in chunks}
    missing = [i for i in range(max(seqs) + 1) if i not in seqs] if seqs else []
    if session["status"] == "ended":
        raise AppError(409, "Esta gravação já foi encerrada.")
    if session["status"] != "processing":
        row = repository.patch_session(user, sid, {"status": "processing"})
        if row is None:
            raise AppError(403, "Você não tem permissão para alterar esta gravação.")
        session = {**session, **row}
        sec.audit(user, "live.finish", session.get("org_id"), "live_session", sid, {"chunks": len(chunks), "missing": len(missing)})
    return {"ok": True, "session": _public(session), "chunks": len(chunks), "missing": missing}


def delete_session(user, session_id: str) -> dict:
    """Apaga a gravação e o áudio. O áudio sai primeiro; se falhar, o banco fica intacto para tentar de novo."""
    sid = _uuid(session_id, "Gravação")
    session = get_session(user, sid)
    paths = repository.chunk_paths(user, sid)
    try:
        storage.delete_objects(paths)
    except Exception as exc:
        log.warning("áudio da gravação não apagado: %s", type(exc).__name__)
        raise AppError(502, "Não foi possível apagar o áudio agora. Nada foi apagado; tente novamente.") from exc
    repository.delete_session(user, sid)
    sec.audit(user, "live.delete", session.get("org_id"), "live_session", sid, {"chunks": len(paths)})
    return {"ok": True, "deleted_audio": len(paths)}


def delete_audio(user, session_id: str) -> dict:
    """Apaga só o áudio: a transcrição, a sessão e a reunião ficam. Só depois de o texto estar pronto (reunião gerada ou tudo transcrito)."""
    sid = _uuid(session_id, "Gravação")
    session = get_session(user, sid)
    if session.get("audio_deleted_at"):
        return {"ok": True, "deleted": 0, "already": True}
    if session["status"] in ("recording", "paused"):
        raise AppError(409, "Encerre a gravação antes de apagar o áudio.")
    if session["status"] != "ended":
        if any(r["status"] != "transcribed" for r in repository.chunk_statuses(user, sid)):
            raise AppError(409, "Ainda há trechos sem transcrição. Gere a reunião antes de apagar o áudio, ou apague a gravação inteira.")
    try:
        n = delete_audio_of(user, session, "user")
    except Exception as exc:
        log.warning("áudio da gravação não apagado: %s", type(exc).__name__)
        raise AppError(502, "Não foi possível apagar o áudio agora. Nada foi apagado; tente novamente.") from exc
    return {"ok": True, "deleted": n}
