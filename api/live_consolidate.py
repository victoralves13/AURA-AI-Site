"""AURA AI — encerrar e consolidar uma gravação ao vivo em uma REUNIÃO (fase 6.5).

POST /api/live/{id}/consolidate junta a transcrição dos pedaços (com horários), roda a MESMA análise das demais reuniões (cliente, evidências
conferidas, decisões, ações) e liga a reunião criada à sessão (`meeting_id`). Pode ser chamada de novo quantas vezes precisar:
  * Ainda há pedaços sem transcrição? Ela transcreve um lote e devolve state="pending" (a tela chama de novo até acabar).
  * Há pedaços que não puderam ser transcritos ou faltam na sequência? Devolve state="needs_decision": a pessoa escolhe tentar de novo ou
    analisar assim mesmo (allow_gaps). Os buracos entram na transcrição como "[trecho sem transcrição]" e nunca são preenchidos pela IA.
  * Falhou na análise? A sessão vai para "failed" com o áudio e a transcrição intactos; chamar de novo tenta outra vez (failed -> processing).
  * Idempotente: se a reunião já existe (sessão encerrada, ou uma tentativa anterior salvou a reunião mas não conseguiu ligá-la), reaproveita
    em vez de criar outra. Duas chamadas simultâneas não analisam duas vezes (reserva condicional no banco).
Áudio: apagar só o áudio (DELETE /api/live/{id}/audio) mantém texto, sessão e reunião. Retenção automática opcional: AURA_LIVE_AUDIO_RETENTION_DAYS.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

import live
import live_alerts
import live_transcribe as lt
import security as sec

log = logging.getLogger("aura.live.consolidate")
router = APIRouter()

PIPELINE = None            # definido por index.py: a função de análise que cria e salva a reunião (_build_result)
BUSY_TTL = timedelta(minutes=10)
GAP_LINE = "[trecho sem transcrição]"
COLUMNS = "id,seq,status,attempts,claimed_at,duration_ms,storage_path,text"


def set_pipeline(fn) -> None:
    global PIPELINE
    PIPELINE = fn


class ConsolidateRequest(BaseModel):
    allow_gaps: bool = False
    retry_failed: bool = False


def build_transcript(chunks: list[dict]) -> tuple[str, dict]:
    """Transcrição com um horário '[mm:ss]' por pedaço (a análise deriva horários da transcrição). Pedaço sem texto vira lacuna marcada."""
    built = lt.assemble(chunks)
    rows, gaps = [], 0
    for line in built["lines"]:
        stamp = live_alerts.clock(line["start_ms"])
        if line["status"] == "transcribed":
            if line["text"]:
                rows.append(f"[{stamp}] {line['text']}")
        else:
            gaps += 1
            rows.append(f"[{stamp}] {GAP_LINE}")
    return "\n".join(rows), {"gaps": gaps, "missing": built["missing"], "chunks": len(chunks)}


def _busy(session: dict, now: datetime) -> bool:
    if not str(session.get("error") or "").startswith("consolidating"):
        return False
    updated = live._iso(session.get("updated_at"))
    return bool(updated) and now - updated < BUSY_TTL


def _find_existing_meeting(user: sec.AuthUser, sid: str) -> dict | None:
    rows = sec.user_rest(user, "GET", f"meetings?select=id,meeting_title,summary&file_name=eq.live-{sid}&order=created_at.desc&limit=1") or []
    return rows[0] if rows else None


def _finish(sid: str, meeting_id: str) -> bool:
    for _ in range(2):  # uma nova tentativa se o banco falhar na hora de ligar a reunião
        try:
            rows = sec.service_rest("PATCH", f"live_sessions?id=eq.{sid}&status=eq.processing", {"status": "ended", "meeting_id": meeting_id, "error": None}) or []
            return bool(rows)
        except RuntimeError as exc:
            log.warning("sessão ao vivo não ligada à reunião: %s", exc)
    return False


def _done(meeting: dict, extra: dict | None = None) -> dict:
    return {"ok": True, "state": "done", "meeting_id": meeting.get("id"), "title": meeting.get("meeting_title") or meeting.get("title"),
            "summary": (meeting.get("summary") or "")[:400], **(extra or {})}


@router.post("/api/live/{session_id}/consolidate")
def consolidate(session_id: str, payload: ConsolidateRequest | None = None, user=Depends(sec.current_user)):
    user = live._need_user(user)
    sid = live._uuid(session_id, "Gravação")
    allow_gaps, retry = bool(payload and payload.allow_gaps), bool(payload and payload.retry_failed)
    session = live._get_session(user, sid)
    if session["status"] in ("recording", "paused"):
        raise HTTPException(status_code=409, detail="Encerre a gravação antes de gerar a reunião.")
    if session["status"] == "ended" and session.get("meeting_id"):
        return {"ok": True, "state": "done", "meeting_id": session["meeting_id"], "already": True}
    if PIPELINE is None:
        raise HTTPException(status_code=503, detail="A análise de reuniões não está disponível neste ambiente.")
    now = live._now()
    try:
        # uma tentativa anterior pode ter salvo a reunião e falhado ao ligá-la: reaproveita em vez de duplicar
        existing = _find_existing_meeting(user, sid)
        if existing:
            if session["status"] != "processing":
                sec.service_rest("PATCH", f"live_sessions?id=eq.{sid}&status=in.(failed,abandoned)", {"status": "processing", "error": None})
            _finish(sid, existing["id"])
            return _done(existing, {"reused": True})
        chunks = sec.service_rest("GET", f"live_chunks?select={COLUMNS}&session_id=eq.{sid}&order=seq.asc&limit=400") or []
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=live.GENERIC) from exc

    # 1) transcrição pendente: um lote por chamada (a tela chama de novo)
    if not session.get("audio_deleted_at"):
        if lt.pick_pending(chunks, now, retry):
            lt.enforce_hourly_limit(user)
            lt.run_batch(sid, chunks, now, retry)
            chunks = sec.service_rest("GET", f"live_chunks?select={COLUMNS}&session_id=eq.{sid}&order=seq.asc&limit=400") or []
            waiting = [c for c in chunks if c["status"] in ("uploaded", "transcribing") or (c["status"] == "failed" and int(c.get("attempts") or 0) < lt.MAX_ATTEMPTS)]
            if waiting:
                return {"ok": True, "state": "pending", "pending": len(waiting), "transcribed": sum(1 for c in chunks if c["status"] == "transcribed"), "total": len(chunks)}
    transcribed = [c for c in chunks if c["status"] == "transcribed"]
    built_text, info = build_transcript(chunks)
    bad = [c for c in chunks if c["status"] != "transcribed"]
    if (bad or info["missing"]) and not allow_gaps:  # primeiro a decisão sobre os buracos; só depois "sem fala"
        return {"ok": True, "state": "needs_decision", "failed": len(bad), "missing": info["missing"], "transcribed": len(transcribed), "total": len(chunks)}
    if not any(lt.clean_text(c.get("text")) for c in transcribed):
        return {"ok": True, "state": "empty", "total": len(chunks), "message": "Nenhuma fala foi reconhecida nesta gravação."}

    # 2) reserva: só uma chamada analisa (processing + sem marca -> 'consolidating')
    sec.enforce_usage_limit(user)
    try:
        if session["status"] in ("failed", "abandoned"):
            sec.service_rest("PATCH", f"live_sessions?id=eq.{sid}&status=eq.{session['status']}", {"status": "processing", "error": None})
        claimed = sec.service_rest("PATCH", f"live_sessions?id=eq.{sid}&status=eq.processing&error=is.null", {"error": "consolidating"}) or []
        if not claimed:
            current = live._get_session(user, sid)
            if _busy(current, now):
                return {"ok": True, "state": "busy"}
            sec.service_rest("PATCH", f"live_sessions?id=eq.{sid}&status=eq.processing", {"error": "consolidating"})  # reserva antiga (>10 min): retoma
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=live.GENERIC) from exc

    # 3) análise completa (a mesma das demais reuniões: cliente, evidências, decisões, ações)
    meta = {"chunks": len(chunks), "gaps": info["gaps"], "model": lt.LIVE_MODEL, "speaker_labels": False, "live": True,
            "duration_seconds": session.get("duration_seconds") or 0}
    try:
        result = PIPELINE(built_text, (session.get("client_name") or ""), f"live-{sid}", "live", session.get("context") or "Outro", meta,
                          meeting_title=session.get("title") or "Reunião ao vivo", user=user, org_id=session.get("org_id"))
        meeting_id = result.get("id")
        if not result.get("persisted") or not meeting_id:
            raise RuntimeError("A reunião não pôde ser salva.")
    except Exception as exc:
        log.warning("consolidação da gravação %s falhou: %s", sid, type(exc).__name__)
        try:
            sec.service_rest("PATCH", f"live_sessions?id=eq.{sid}&status=eq.processing", {"status": "failed", "error": "consolidation_failed"})
        except RuntimeError:
            pass
        raise HTTPException(status_code=502, detail="Não foi possível analisar a reunião agora. A gravação e a transcrição estão guardadas; tente de novo.") from exc
    linked = _finish(sid, meeting_id)
    sec.audit(user, "analysis.live", session.get("org_id"), "meeting", meeting_id)  # conta no limite de análises por hora
    sec.audit(user, "live.consolidate", session.get("org_id"), "live_session", sid, {"chunks": len(chunks), "gaps": info["gaps"], "linked": linked})
    return _done({"id": meeting_id, "meeting_title": result.get("meeting_title"), "summary": result.get("summary")}, {"gaps": info["gaps"], "linked": linked})


@router.delete("/api/live/{session_id}/audio")
def delete_audio(session_id: str, user=Depends(sec.current_user)):
    """Apaga só o áudio: a transcrição, a sessão e a reunião ficam. Só depois de o texto estar pronto (reunião gerada ou tudo transcrito)."""
    user = live._need_user(user)
    sid = live._uuid(session_id, "Gravação")
    session = live._get_session(user, sid)
    if session.get("audio_deleted_at"):
        return {"ok": True, "deleted": 0, "already": True}
    if session["status"] in ("recording", "paused"):
        raise HTTPException(status_code=409, detail="Encerre a gravação antes de apagar o áudio.")
    if session["status"] != "ended":
        rows = live._db(lambda: sec.user_rest(user, "GET", f"live_chunks?select=status&session_id=eq.{sid}&limit=400")) or []
        if any(r["status"] != "transcribed" for r in rows):
            raise HTTPException(status_code=409, detail="Ainda há trechos sem transcrição. Gere a reunião antes de apagar o áudio, ou apague a gravação inteira.")
    try:
        n = live.delete_audio_of(user, session, "user")
    except Exception as exc:
        log.warning("áudio da gravação não apagado: %s", type(exc).__name__)
        raise HTTPException(status_code=502, detail="Não foi possível apagar o áudio agora. Nada foi apagado; tente novamente.") from exc
    return {"ok": True, "deleted": n}
