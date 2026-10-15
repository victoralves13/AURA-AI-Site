"""AURA AI — reuniões ao vivo: sessões de gravação e pedaços de áudio (fase 6.1).

Fluxo: o navegador cria a sessão (com o consentimento obrigatório), grava em pedaços de ~30 s, pede uma URL assinada para
cada pedaço, envia o áudio DIRETO ao bucket privado e depois registra o pedaço aqui. A transcrição contínua (6.3), os alertas
(6.4) e a consolidação em uma reunião (6.5) vêm nas próximas fases; esta fase guarda tudo com segurança.

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

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from aura.core import security as sec
from aura.core import storage as storage_io

log = logging.getLogger("aura.live")
router = APIRouter()

MAX_SEQ = 399
MAX_CHUNK_BYTES = 25 * 1024 * 1024
MAX_CHUNK_MS = 120_000
EXTENSIONS = (".webm", ".ogg", ".m4a", ".mp4", ".wav", ".mp3")
RECORDING_SILENCE = timedelta(minutes=10)   # gravando sem nenhum sinal por tanto tempo = aba/aparelho caiu
PAUSE_LIMIT = timedelta(hours=6)
ACCEPTING = ("recording", "paused", "processing")
USER_STATUS = ("recording", "paused")
CONTEXTS_MAX = 60
SESSION_COLUMNS = ("id,org_id,title,context,client_name,status,consent_at,alerts_enabled,started_at,last_chunk_at,ended_at,"
                   "duration_seconds,meeting_id,audio_deleted_at,error,created_at,updated_at")
ERRORS = {
    "too_many_active_sessions": (409, "Você já tem 3 gravações ativas. Encerre ou finalize alguma antes de iniciar outra."),
    "invalid_transition": (409, "Essa mudança de estado não é permitida para esta gravação."),
    "live_field_reserved": (403, "Esse campo é gerenciado pelo AURA."),
    "live_immutable": (409, "Esse campo da gravação não pode ser alterado."),
    "session_closed": (409, "Esta gravação não aceita mais áudio."),
    "session_not_found": (404, "Gravação não encontrada."),
}
GENERIC = "Não foi possível concluir a operação com a gravação. Tente novamente."


def _db(call):
    try:
        return call()
    except sec.SupabaseError as exc:
        if exc.db_message in ERRORS:
            status, detail = ERRORS[exc.db_message]
            raise HTTPException(status_code=status, detail=detail) from exc
        if exc.db_code == "23505":
            raise HTTPException(status_code=409, detail="Este pedaço já foi registrado.") from exc
        if exc.db_code in ("23514", "22P02", "23502"):
            raise HTTPException(status_code=400, detail="Dados da gravação inválidos.") from exc
        if exc.status in (401, 403):
            raise HTTPException(status_code=403, detail="Você não tem permissão para gravar neste espaço.") from exc
        raise HTTPException(status_code=502, detail=GENERIC) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=GENERIC) from exc


def _need_user(user):
    if user is None:
        raise HTTPException(status_code=401, detail="Autenticação necessária.")
    return user


def _uuid(value, what: str) -> str:
    if not isinstance(value, str) or not sec.UUID_RE.match(value):
        raise HTTPException(status_code=400, detail=f"{what} inválido.")
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
        raise HTTPException(status_code=400, detail=f"O número do pedaço deve ir de 0 a {MAX_SEQ}.")
    return value


def _ext(value) -> str:
    ext = (value or ".webm").lower()
    ext = ext if ext.startswith(".") else "." + ext
    if ext not in EXTENSIONS:
        raise HTTPException(status_code=400, detail="Formato de áudio não suportado.")
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
    ids = ",".join(s["id"] for s in stale)
    try:
        done = sec.service_rest("PATCH", f"live_sessions?id=in.({ids})&status=in.(recording,paused)", {"status": "abandoned"}) or []
        changed = {r["id"] for r in done}  # só o que de fato mudou (outra chamada pode ter encerrado a sessão no meio)
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
    paths = [r["storage_path"] for r in (_db(lambda: sec.user_rest(user, "GET", f"live_chunks?select=storage_path&session_id=eq.{session['id']}&limit=400")) or [])]
    storage_io.delete_objects(paths)
    sec.service_rest("PATCH", f"live_sessions?id=eq.{session['id']}", {"audio_deleted_at": _now().isoformat()})
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


def _get_session(user: sec.AuthUser, session_id: str) -> dict:
    rows = _db(lambda: sec.user_rest(user, "GET", f"live_sessions?select={SESSION_COLUMNS},owner_id&id=eq.{session_id}&limit=1")) or []
    if not rows:
        raise HTTPException(status_code=404, detail=ERRORS["session_not_found"][1])
    session = _sweep(rows)[0]
    if session.get("org_id"):
        sec.require_org_permission(user, session["org_id"], "meetings.write")
    return session


def _chunks(user: sec.AuthUser, session_id: str) -> list[dict]:
    return _db(lambda: sec.user_rest(user, "GET", f"live_chunks?select=seq,status,duration_ms,size_bytes,attempts,error,created_at,transcribed_at&session_id=eq.{session_id}&order=seq.asc&limit=400")) or []


def _public(session: dict) -> dict:
    return {k: v for k, v in session.items() if k != "owner_id"}


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------
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


@router.post("/api/live")
def create_session(payload: LiveCreate, user=Depends(sec.current_user)):
    user = _need_user(user)
    if payload.consent is not True:
        raise HTTPException(status_code=400, detail="Confirme que os participantes foram avisados de que a reunião está sendo gravada.")
    org = None if not payload.org_id or payload.org_id == "personal" else _uuid(payload.org_id, "Espaço")
    sec.require_org_permission(user, org, "meetings.write")
    row = {"owner_id": user.id, "org_id": org, "consent_at": _now().isoformat(), "alerts_enabled": bool(payload.alerts_enabled)}
    for key, size in (("title", 200), ("context", CONTEXTS_MAX), ("client_name", 200)):
        value = _clean(getattr(payload, key), size)
        if value:
            row[key] = value
    created = (_db(lambda: sec.user_rest(user, "POST", "live_sessions", row)) or [row])[0]
    sec.audit(user, "live.start", org, "live_session", created.get("id"), {"alerts": bool(payload.alerts_enabled)})
    return {"ok": True, "session": _public(created)}


@router.get("/api/live")
def list_sessions(org_id: str | None = None, status: str | None = None, limit: int = 50, user=Depends(sec.current_user)):
    user = _need_user(user)
    where = ""
    if org_id:
        where += "&org_id=is.null" if org_id == "personal" else f"&org_id=eq.{_uuid(org_id, 'Espaço')}"
    if status:
        if status not in ("recording", "paused", "processing", "ended", "failed", "abandoned"):
            raise HTTPException(status_code=400, detail="Filtro de estado inválido.")
        where += f"&status=eq.{status}"
    limit = max(1, min(limit, 100))
    rows = _db(lambda: sec.user_rest(user, "GET", f"live_sessions?select={SESSION_COLUMNS}{where}&order=started_at.desc&limit={limit}")) or []
    return {"ok": True, "sessions": [_public(s) for s in _retention(user, _sweep(rows))]}


@router.get("/api/live/{session_id}")
def get_session(session_id: str, user=Depends(sec.current_user)):
    user = _need_user(user)
    sid = _uuid(session_id, "Gravação")
    session = _get_session(user, sid)
    return {"ok": True, "session": _public(session), "chunks": _chunks(user, sid)}


@router.patch("/api/live/{session_id}")
def update_session(session_id: str, payload: LiveUpdate, user=Depends(sec.current_user)):
    user = _need_user(user)
    sid = _uuid(session_id, "Gravação")
    session = _get_session(user, sid)
    data = payload.model_dump(exclude_unset=True)
    changes: dict = {}
    for key, size in (("title", 200), ("context", CONTEXTS_MAX), ("client_name", 200)):
        if key in data:
            value = _clean(data[key], size + 1)
            if len(value) > size or (key != "client_name" and not value):
                raise HTTPException(status_code=400, detail="Texto inválido ou longo demais.")
            changes[key] = value or None
    if "alerts_enabled" in data and data["alerts_enabled"] is not None:
        changes["alerts_enabled"] = bool(data["alerts_enabled"])
    if data.get("status") is not None:
        if data["status"] not in USER_STATUS:
            raise HTTPException(status_code=400, detail="Use recording ou paused (para encerrar, use /finish).")
        if data["status"] != session["status"]:
            changes["status"] = data["status"]
    if not changes:
        return {"ok": True, "session": _public(session)}
    rows = _db(lambda: sec.user_rest(user, "PATCH", f"live_sessions?id=eq.{sid}", changes)) or []
    if not rows:
        raise HTTPException(status_code=403, detail="Você não tem permissão para alterar esta gravação.")
    return {"ok": True, "session": _public({**session, **rows[0]})}


@router.post("/api/live/{session_id}/chunks/upload-url")
def chunk_upload_url(session_id: str, payload: UploadUrlRequest, user=Depends(sec.current_user)):
    user = _need_user(user)
    sid = _uuid(session_id, "Gravação")
    seq, ext = _seq(payload.seq), _ext(payload.ext)
    session = _get_session(user, sid)
    if session["status"] not in ACCEPTING or session.get("audio_deleted_at"):
        raise HTTPException(status_code=409, detail=ERRORS["session_closed"][1])
    path = chunk_path(session["owner_id"], session.get("org_id"), sid, seq, ext)
    try:
        url, token = storage_io.signed_upload(path)
    except Exception as exc:
        log.warning("URL de upload do pedaço não gerada: %s", type(exc).__name__)
        raise HTTPException(status_code=502, detail="Não foi possível preparar o envio do áudio. Tente novamente.") from exc
    return {"ok": True, "seq": seq, "path": path, "signed_url": url, "token": token}


@router.post("/api/live/{session_id}/chunks")
def register_chunk(session_id: str, payload: ChunkRegister, user=Depends(sec.current_user)):
    """Registra um pedaço depois de o áudio ter chegado ao bucket. Repetir a chamada é seguro."""
    user = _need_user(user)
    sid = _uuid(session_id, "Gravação")
    seq, ext = _seq(payload.seq), _ext(payload.ext)
    if not isinstance(payload.duration_ms, int) or not 0 <= payload.duration_ms <= MAX_CHUNK_MS:
        raise HTTPException(status_code=400, detail="A duração do pedaço deve ir de 0 a 2 minutos.")
    session = _get_session(user, sid)
    path = chunk_path(session["owner_id"], session.get("org_id"), sid, seq, ext)
    existing = _db(lambda: sec.user_rest(user, "GET", f"live_chunks?select=seq,status,duration_ms,size_bytes&session_id=eq.{sid}&seq=eq.{seq}&limit=1")) or []
    if existing:
        return {"ok": True, "duplicate": True, "chunk": existing[0]}
    if session["status"] not in ACCEPTING or session.get("audio_deleted_at"):
        raise HTTPException(status_code=409, detail=ERRORS["session_closed"][1])
    try:
        size = storage_io.object_size(path)
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=GENERIC) from exc
    if size is None:
        raise HTTPException(status_code=409, detail="O áudio deste pedaço ainda não chegou ao armazenamento. Envie-o e tente de novo.")
    if not 0 < size <= MAX_CHUNK_BYTES:
        raise HTTPException(status_code=400, detail="O áudio do pedaço está vazio ou grande demais.")
    row = {"session_id": sid, "seq": seq, "storage_path": path, "duration_ms": payload.duration_ms, "size_bytes": size}
    try:
        created = (_db(lambda: sec.user_rest(user, "POST", "live_chunks", row)) or [row])[0]
        duplicate = False
    except HTTPException as exc:
        if exc.status_code != 409 or exc.detail != "Este pedaço já foi registrado.":
            raise
        created, duplicate = row, True  # outra chamada registrou ao mesmo tempo
    if not duplicate:
        _touch_session(sid)
    return {"ok": True, "duplicate": duplicate, "chunk": {k: created.get(k) for k in ("seq", "status", "duration_ms", "size_bytes")}}


def _touch_session(session_id: str) -> None:
    """Atualiza último sinal e duração total da sessão (campos do backend). Falha aqui não perde o pedaço."""
    try:
        rows = sec.service_rest("GET", f"live_chunks?select=duration_ms&session_id=eq.{session_id}&limit=400") or []
        total = sum(int(r.get("duration_ms") or 0) for r in rows) // 1000
        sec.service_rest("PATCH", f"live_sessions?id=eq.{session_id}", {"last_chunk_at": _now().isoformat(), "duration_seconds": total})
    except RuntimeError as exc:
        log.warning("sessão ao vivo não atualizada após o pedaço: %s", exc)


@router.post("/api/live/{session_id}/finish")
def finish_session(session_id: str, user=Depends(sec.current_user)):
    """Pede o encerramento (a consolidação em reunião vem na fase 6.5). Informa se faltam pedaços na sequência."""
    user = _need_user(user)
    sid = _uuid(session_id, "Gravação")
    session = _get_session(user, sid)
    chunks = _chunks(user, sid)
    seqs = {c["seq"] for c in chunks}
    missing = [i for i in range(max(seqs) + 1) if i not in seqs] if seqs else []
    if session["status"] == "ended":
        raise HTTPException(status_code=409, detail="Esta gravação já foi encerrada.")
    if session["status"] != "processing":
        rows = _db(lambda: sec.user_rest(user, "PATCH", f"live_sessions?id=eq.{sid}", {"status": "processing"})) or []
        if not rows:
            raise HTTPException(status_code=403, detail="Você não tem permissão para alterar esta gravação.")
        session = {**session, **rows[0]}
        sec.audit(user, "live.finish", session.get("org_id"), "live_session", sid, {"chunks": len(chunks), "missing": len(missing)})
    return {"ok": True, "session": _public(session), "chunks": len(chunks), "missing": missing}


@router.delete("/api/live/{session_id}")
def delete_session(session_id: str, user=Depends(sec.current_user)):
    """Apaga a gravação e o áudio. O áudio sai primeiro; se falhar, o banco fica intacto para tentar de novo."""
    user = _need_user(user)
    sid = _uuid(session_id, "Gravação")
    session = _get_session(user, sid)
    paths = [r["storage_path"] for r in (_db(lambda: sec.user_rest(user, "GET", f"live_chunks?select=storage_path&session_id=eq.{sid}&limit=400")) or [])]
    try:
        storage_io.delete_objects(paths)
    except Exception as exc:
        log.warning("áudio da gravação não apagado: %s", type(exc).__name__)
        raise HTTPException(status_code=502, detail="Não foi possível apagar o áudio agora. Nada foi apagado; tente novamente.") from exc
    _db(lambda: sec.user_rest(user, "DELETE", f"live_sessions?id=eq.{sid}"))
    sec.audit(user, "live.delete", session.get("org_id"), "live_session", sid, {"chunks": len(paths)})
    return {"ok": True, "deleted_audio": len(paths)}
