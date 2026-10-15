"""Reuniões ao vivo — acesso aos dados (PostgREST).

  * Funções que servem a TELA (leitura/criação/alteração da sessão e dos pedaços pelo dono) usam o JWT da pessoa (RLS) e traduzem a
    falha do banco em AppError.
  * Funções do BACKEND (estado de transcrição, reserva de pedaços, consolidação, contagem de uso) usam a chave de serviço: só o
    backend muda esses campos. Nelas a falha original sobe (RuntimeError) porque quem chama decide o que fazer (as rotas viram 502; o
    varredor de sessões e a atualização de último sinal só registram no log).
"""
from __future__ import annotations

from aura.core import security as sec
from aura.core.errors import AppError, db_call

SESSION_COLUMNS = ("id,org_id,title,context,client_name,status,consent_at,alerts_enabled,started_at,last_chunk_at,ended_at,"
                   "duration_seconds,meeting_id,audio_deleted_at,error,created_at,updated_at")
PUBLIC_CHUNK_COLUMNS = "seq,status,duration_ms,size_bytes,attempts,error,created_at,transcribed_at"
CHUNK_COLUMNS = "id,seq,status,attempts,claimed_at,duration_ms,storage_path"
CONSOLIDATION_COLUMNS = "id,seq,status,attempts,claimed_at,duration_ms,storage_path,text"
GENERIC = "Não foi possível concluir a operação com a gravação. Tente novamente."
FORBIDDEN = "Você não tem permissão para gravar neste espaço."
DUPLICATE_CHUNK = "Este pedaço já foi registrado."
KNOWN = {
    "too_many_active_sessions": (409, "Você já tem 3 gravações ativas. Encerre ou finalize alguma antes de iniciar outra."),
    "invalid_transition": (409, "Essa mudança de estado não é permitida para esta gravação."),
    "live_field_reserved": (403, "Esse campo é gerenciado pelo AURA."),
    "live_immutable": (409, "Esse campo da gravação não pode ser alterado."),
    "session_closed": (409, "Esta gravação não aceita mais áudio."),
    "session_not_found": (404, "Gravação não encontrada."),
}
SESSION_NOT_FOUND = KNOWN["session_not_found"][1]
SESSION_CLOSED = KNOWN["session_closed"][1]


def _db(call):
    try:
        return db_call(lambda: _dup(call), generic=GENERIC, known=KNOWN, invalid="Dados da gravação inválidos.", forbidden=FORBIDDEN)
    except AppError:
        raise


def _dup(call):
    try:
        return call()
    except sec.SupabaseError as exc:
        if exc.db_code == "23505":
            raise AppError(409, DUPLICATE_CHUNK) from exc
        if exc.db_code == "23502":
            raise AppError(400, "Dados da gravação inválidos.") from exc
        raise


# --- sessões (tela) --------------------------------------------------------------------------------------------------------
def get_session_row(user, session_id: str) -> dict | None:
    rows = _db(lambda: sec.user_rest(user, "GET", f"live_sessions?select={SESSION_COLUMNS},owner_id&id=eq.{session_id}&limit=1")) or []
    return rows[0] if rows else None


def list_sessions(user, where: str, limit: int) -> list[dict]:
    return _db(lambda: sec.user_rest(user, "GET", f"live_sessions?select={SESSION_COLUMNS}{where}&order=started_at.desc&limit={limit}")) or []


def insert_session(user, row: dict) -> dict:
    return (_db(lambda: sec.user_rest(user, "POST", "live_sessions", row)) or [row])[0]


def patch_session(user, session_id: str, changes: dict) -> dict | None:
    rows = _db(lambda: sec.user_rest(user, "PATCH", f"live_sessions?id=eq.{session_id}", changes)) or []
    return rows[0] if rows else None


def delete_session(user, session_id: str) -> None:
    _db(lambda: sec.user_rest(user, "DELETE", f"live_sessions?id=eq.{session_id}"))


# --- pedaços (tela) --------------------------------------------------------------------------------------------------------
def list_chunks(user, session_id: str) -> list[dict]:
    return _db(lambda: sec.user_rest(user, "GET", f"live_chunks?select={PUBLIC_CHUNK_COLUMNS}&session_id=eq.{session_id}&order=seq.asc&limit=400")) or []


def get_chunk(user, session_id: str, seq: int) -> dict | None:
    rows = _db(lambda: sec.user_rest(user, "GET", f"live_chunks?select=seq,status,duration_ms,size_bytes&session_id=eq.{session_id}&seq=eq.{seq}&limit=1")) or []
    return rows[0] if rows else None


def insert_chunk(user, row: dict) -> dict:
    """Registra o pedaço; se outra chamada registrou o mesmo ao mesmo tempo, levanta AppError 409 (DUPLICATE_CHUNK)."""
    return (_db(lambda: sec.user_rest(user, "POST", "live_chunks", row)) or [row])[0]


def chunk_paths(user, session_id: str) -> list[str]:
    return [r["storage_path"] for r in (_db(lambda: sec.user_rest(user, "GET", f"live_chunks?select=storage_path&session_id=eq.{session_id}&limit=400")) or [])]


def chunk_statuses(user, session_id: str) -> list[dict]:
    return _db(lambda: sec.user_rest(user, "GET", f"live_chunks?select=status&session_id=eq.{session_id}&limit=400")) or []


def chunks_with_text(user, session_id: str) -> list[dict]:
    return _db(lambda: sec.user_rest(user, "GET", f"live_chunks?select=seq,status,duration_ms,attempts,text&session_id=eq.{session_id}&order=seq.asc&limit=400")) or []


# --- backend: sessão ---------------------------------------------------------------------------------------------------------
def abandon_sessions(ids_csv: str) -> set[str]:
    """Marca como interrompidas as sessões ainda em gravação/pausa; devolve só as que de fato mudaram."""
    done = sec.service_rest("PATCH", f"live_sessions?id=in.({ids_csv})&status=in.(recording,paused)", {"status": "abandoned"}) or []
    return {r["id"] for r in done}


def set_audio_deleted(session_id: str, when_iso: str) -> None:
    sec.service_rest("PATCH", f"live_sessions?id=eq.{session_id}", {"audio_deleted_at": when_iso})


def touch_session(session_id: str, when_iso: str) -> None:
    """Atualiza último sinal e duração total da sessão (soma dos pedaços)."""
    rows = sec.service_rest("GET", f"live_chunks?select=duration_ms&session_id=eq.{session_id}&limit=400") or []
    total = sum(int(r.get("duration_ms") or 0) for r in rows) // 1000
    sec.service_rest("PATCH", f"live_sessions?id=eq.{session_id}", {"last_chunk_at": when_iso, "duration_seconds": total})


# --- backend: transcrição ---------------------------------------------------------------------------------------------------
def chunks_to_transcribe(session_id: str) -> list[dict]:
    return sec.service_rest("GET", f"live_chunks?select={CHUNK_COLUMNS}&session_id=eq.{session_id}&order=seq.asc&limit=400") or []


def claim_chunk(chunk_id: str, current_status: str, patch: dict) -> bool:
    """Reserva por UPDATE condicional: só uma chamada vence (as outras veem 0 linhas)."""
    return bool(sec.service_rest("PATCH", f"live_chunks?id=eq.{chunk_id}&status=eq.{current_status}", patch))


def previous_chunk(session_id: str, seq: int) -> dict | None:
    rows = sec.service_rest("GET", f"live_chunks?select=text,status&session_id=eq.{session_id}&seq=eq.{seq}&limit=1") or []
    return rows[0] if rows else None


def update_chunk(chunk_id: str, patch: dict) -> None:
    sec.service_rest("PATCH", f"live_chunks?id=eq.{chunk_id}", patch)


def transcribed_durations(user_id: str, since: str) -> list[dict]:
    return sec.service_rest("GET", f"live_chunks?select=duration_ms&owner_id=eq.{user_id}&status=eq.transcribed&transcribed_at=gte.{since}&limit=2000") or []


# --- backend: alertas e consolidação ---------------------------------------------------------------------------------------
def count_recent_scans(user_id: str, since: str, limit: int) -> int:
    return len(sec.service_rest("GET", f"audit_log?select=id&actor_id=eq.{user_id}&action=eq.live.scan&at=gte.{since}&limit={limit + 1}") or [])


def find_meeting_of_session(user, session_id: str) -> dict | None:
    rows = sec.user_rest(user, "GET", f"meetings?select=id,meeting_title,summary&file_name=eq.live-{session_id}&order=created_at.desc&limit=1") or []
    return rows[0] if rows else None


def chunks_for_consolidation(session_id: str) -> list[dict]:
    return sec.service_rest("GET", f"live_chunks?select={CONSOLIDATION_COLUMNS}&session_id=eq.{session_id}&order=seq.asc&limit=400") or []


def revive_session(session_id: str, from_statuses: str) -> None:
    """Devolve a sessão a 'processing' (de failed/abandoned) para tentar a consolidação de novo."""
    sec.service_rest("PATCH", f"live_sessions?id=eq.{session_id}&status={from_statuses}", {"status": "processing", "error": None})


def link_session_to_meeting(session_id: str, meeting_id: str) -> bool:
    rows = sec.service_rest("PATCH", f"live_sessions?id=eq.{session_id}&status=eq.processing", {"status": "ended", "meeting_id": meeting_id, "error": None}) or []
    return bool(rows)


def claim_consolidation(session_id: str) -> bool:
    """Reserva: só uma chamada analisa (processing sem marca -> 'consolidating')."""
    return bool(sec.service_rest("PATCH", f"live_sessions?id=eq.{session_id}&status=eq.processing&error=is.null", {"error": "consolidating"}))


def reclaim_consolidation(session_id: str) -> None:
    """Retoma uma reserva antiga (de uma chamada que caiu)."""
    sec.service_rest("PATCH", f"live_sessions?id=eq.{session_id}&status=eq.processing", {"error": "consolidating"})


def mark_consolidation_failed(session_id: str) -> None:
    sec.service_rest("PATCH", f"live_sessions?id=eq.{session_id}&status=eq.processing", {"status": "failed", "error": "consolidation_failed"})
