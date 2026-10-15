"""AURA AI — transcrição contínua das reuniões ao vivo (fase 6.3).

O navegador chama POST /api/live/{id}/transcribe enquanto grava (e depois de encerrar) e consulta GET /api/live/{id}/transcript para
mostrar o texto crescendo. Cada chamada transcreve poucos pedaços e termina rápido (cabe nas funções da Vercel).

Garantias:
  * Cada pedaço é transcrito UMA vez: a "reserva" é um UPDATE condicional (status uploaded/failed -> transcribing) no banco; duas chamadas
    simultâneas nunca pegam o mesmo pedaço, e uma reserva abandonada (função interrompida) é retomada depois de 2 minutos.
  * Falhou? Até 3 tentativas por pedaço; depois fica "falhou" (a pessoa pode pedir nova tentativa). O áudio nunca é apagado por falha.
  * Pedaços fora de ordem ou repetidos não bagunçam nada: o texto é montado por número do pedaço, lacunas aparecem como lacunas, e o
    pequeno trecho repetido na emenda entre dois pedaços (o gravador seguinte começa antes do anterior parar) é removido na montagem.
  * Custo sob controle: limite de minutos de áudio transcritos por pessoa por hora (AURA_MAX_LIVE_MINUTES_PER_HOUR, padrão 90), com a
    estimativa de custo sempre exibida como ESTIMATIVA. Passou do limite: o áudio continua guardado e a transcrição retoma depois.
  * Sem rótulos de interlocutor: cada pedaço é transcrito isoladamente, então um rótulo "A/B" não seria o mesmo entre pedaços.
Limite honesto: o modelo pode inventar frases comuns ("Obrigado por assistir") em trechos de silêncio; as mais conhecidas são descartadas
quando são o pedaço inteiro, mas isso não elimina o risco. A análise final da reunião (6.5) também confere tudo contra a transcrição.
"""
from __future__ import annotations

import logging
import os
import tempfile
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

import live
import security as sec
import storage_io
import verification

log = logging.getLogger("aura.live.transcribe")
router = APIRouter()

LIVE_MODEL = os.getenv("AURA_OPENAI_LIVE_TRANSCRIPTION_MODEL", "gpt-4o-mini-transcribe")
MAX_ATTEMPTS = 3
CLAIM_TTL = timedelta(minutes=2)
BATCH = 2                      # pedaços por chamada (cada um leva alguns segundos)
OVERLAP_WORDS = 5
CONTEXT_CHARS = 220            # fim do texto anterior, passado ao modelo como contexto
HALLUCINATIONS = {"obrigado", "obrigada", "obrigado por assistir", "obrigada por assistir", "legendas pela comunidade amara org",
                  "inscreva se no canal", "ate a proxima", "tchau", "tchau tchau", "musica"}
CHUNK_COLUMNS = "id,seq,status,attempts,claimed_at,duration_ms,storage_path"


class TranscribeRequest(BaseModel):
    retry_failed: bool = False


class Unavailable(RuntimeError):
    """A transcrição não está configurada neste ambiente (sem chave da OpenAI)."""


# ---------------------------------------------------------------------------
# Custo e limites
# ---------------------------------------------------------------------------
def cost_per_minute() -> float:
    try:
        return max(0.0, float(os.getenv("AURA_LIVE_COST_PER_MIN_USD", "0.006")))  # ESTIMATIVA configurável, não é preço confirmado
    except ValueError:
        return 0.006


def estimate_cost(minutes: float) -> float:
    return round(minutes * cost_per_minute(), 4)


def hourly_limit_minutes() -> float:
    try:
        return max(1.0, float(os.getenv("AURA_MAX_LIVE_MINUTES_PER_HOUR", "90")))
    except ValueError:
        return 90.0


def minutes_last_hour(user: sec.AuthUser) -> float:
    since = (live._now() - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")  # sem "+00:00": o "+" na URL viraria espaço e o banco recusaria
    rows = sec.service_rest("GET", f"live_chunks?select=duration_ms&owner_id=eq.{user.id}&status=eq.transcribed&transcribed_at=gte.{since}&limit=2000") or []
    return sum(int(r.get("duration_ms") or 0) for r in rows) / 60000


def enforce_hourly_limit(user: sec.AuthUser) -> float:
    try:
        used = minutes_last_hour(user)
    except RuntimeError as exc:
        raise sec.limit_check_failed(exc) from exc
    if used >= hourly_limit_minutes():
        raise HTTPException(status_code=429, detail="Limite de transcrição por hora atingido. O áudio continua guardado e a transcrição segue quando o limite liberar.")
    return used


# ---------------------------------------------------------------------------
# Texto: limpeza e montagem
# ---------------------------------------------------------------------------
def clean_text(text: str | None) -> str:
    out = " ".join(str(text or "").split())
    return "" if verification.normalize(out) in HALLUCINATIONS else out


def trim_overlap(previous: str, text: str, max_words: int = OVERLAP_WORDS) -> str:
    """Remove do começo de `text` as palavras que repetem o fim de `previous` (emenda entre pedaços). Exige 2+ palavras iguais."""
    prev_words, words = previous.split(), text.split()
    prev_norm = [verification.normalize(w) for w in prev_words]
    norm = [verification.normalize(w) for w in words]
    for k in range(min(max_words, len(prev_words), len(words)), 1, -1):
        if prev_norm[-k:] == norm[:k] and all(norm[:k]):
            return " ".join(words[k:])
    return text


def assemble(chunks: list[dict]) -> dict:
    """Monta a transcrição a partir dos pedaços (qualquer ordem). Retorna linhas por pedaço, lacunas e o texto completo."""
    ordered = sorted(chunks, key=lambda c: c["seq"])
    starts, acc = {}, 0
    for c in ordered:  # início de cada pedaço = soma das durações dos anteriores (conhecidas desde o registro)
        starts[c["seq"]] = acc
        acc += int(c.get("duration_ms") or 0)
    seqs = {c["seq"] for c in ordered}
    missing = [i for i in range(max(seqs) + 1) if i not in seqs] if seqs else []
    lines, previous_text, previous_seq = [], "", None
    for c in ordered:
        raw = clean_text(c.get("text")) if c.get("status") == "transcribed" else ""
        shown = trim_overlap(previous_text, raw) if (raw and previous_seq is not None and c["seq"] == previous_seq + 1) else raw
        lines.append({"seq": c["seq"], "status": c["status"], "start_ms": starts[c["seq"]], "end_ms": starts[c["seq"]] + int(c.get("duration_ms") or 0),
                      "text": shown, "attempts": c.get("attempts", 0)})
        if c.get("status") == "transcribed":
            previous_text, previous_seq = raw, c["seq"]
        else:
            previous_text, previous_seq = "", None   # pedaço faltando/pendente: não há emenda para aparar
    return {"lines": lines, "missing": missing, "text": " ".join(l["text"] for l in lines if l["text"])}


# ---------------------------------------------------------------------------
# Modelo de transcrição (único ponto que usa a rede de IA)
# ---------------------------------------------------------------------------
def transcribe_audio(data: bytes, ext: str, context: str = "") -> str:
    if not os.getenv("OPENAI_API_KEY"):
        raise Unavailable("A transcrição não está configurada neste ambiente.")
    from openai_engine import _client  # import tardio: os testes não precisam do pacote
    with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
        tmp.write(data)
        path = tmp.name
    try:
        with open(path, "rb") as audio:
            kwargs = {"model": LIVE_MODEL, "file": audio, "language": "pt", "response_format": "json"}
            if context:
                kwargs["prompt"] = context[-CONTEXT_CHARS:]
            result = _client().audio.transcriptions.create(**kwargs)
        return str(getattr(result, "text", "") or "")
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Processamento de pedaços
# ---------------------------------------------------------------------------
def _stale_claim(chunk: dict, now: datetime) -> bool:
    claimed = live._iso(chunk.get("claimed_at"))
    return chunk.get("status") == "transcribing" and (claimed is None or now - claimed > CLAIM_TTL)


def pick_pending(chunks: list[dict], now: datetime, retry_failed: bool) -> list[dict]:
    out = []
    for c in sorted(chunks, key=lambda c: c["seq"]):
        if c["status"] == "uploaded" or _stale_claim(c, now) or (c["status"] == "failed" and (retry_failed or c.get("attempts", 0) < MAX_ATTEMPTS)):
            out.append(c)
    return out


def _claim(chunk: dict, now: datetime, reset: bool) -> bool:
    """Reserva o pedaço com um UPDATE condicional: só uma chamada vence."""
    attempts = 1 if reset else int(chunk.get("attempts") or 0) + 1
    rows = sec.service_rest("PATCH", f"live_chunks?id=eq.{chunk['id']}&status=eq.{chunk['status']}",
                            {"status": "transcribing", "claimed_at": now.isoformat(), "attempts": attempts}) or []
    return bool(rows)


def _previous_text(session_id: str, seq: int) -> str:
    if seq <= 0:
        return ""
    rows = sec.service_rest("GET", f"live_chunks?select=text,status&session_id=eq.{session_id}&seq=eq.{seq - 1}&limit=1") or []
    return clean_text(rows[0].get("text")) if rows and rows[0].get("status") == "transcribed" else ""


def process_chunk(session_id: str, chunk: dict, now: datetime, restore_attempts: int = 0) -> str:
    """Transcreve UM pedaço já reservado por esta chamada. Retorna 'transcribed' ou 'failed'. Nunca apaga o áudio."""
    try:
        data = storage_io.download(chunk["storage_path"])
        text = clean_text(transcribe_audio(data, os.path.splitext(chunk["storage_path"])[1] or ".webm", _previous_text(session_id, chunk["seq"])))
    except Unavailable:
        sec.service_rest("PATCH", f"live_chunks?id=eq.{chunk['id']}", {"status": "uploaded", "claimed_at": None, "attempts": restore_attempts})  # sem chave: devolve o pedaço à fila sem gastar tentativa
        raise
    except Exception as exc:  # download, rede, modelo: o motivo detalhado vai só para o log
        log.warning("pedaço %s da sessão %s não transcrito: %s", chunk.get("seq"), session_id, type(exc).__name__)
        sec.service_rest("PATCH", f"live_chunks?id=eq.{chunk['id']}", {"status": "failed", "claimed_at": None, "error": "transcription_failed"})
        return "failed"
    sec.service_rest("PATCH", f"live_chunks?id=eq.{chunk['id']}",
                     {"status": "transcribed", "text": text[:20000], "claimed_at": None, "error": None, "transcribed_at": now.isoformat()})
    return "transcribed"


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------
def run_batch(sid: str, chunks: list[dict], now: datetime, retry: bool = False) -> tuple[list[int], list[int], int]:
    """Transcreve até BATCH pedaços pendentes (reservando cada um). Retorna (transcritos, falhos, pulados). Levanta HTTPException 503/502."""
    pending = pick_pending(chunks, now, retry)
    done, failed, skipped = [], [], 0
    for chunk in pending:
        if len(done) + len(failed) >= BATCH:
            break
        try:
            reset = retry and chunk["status"] == "failed" and chunk.get("attempts", 0) >= MAX_ATTEMPTS
            if not _claim(chunk, now, reset):
                skipped += 1  # outra chamada pegou primeiro
                continue
            result = process_chunk(sid, chunk, now, 0 if reset else int(chunk.get("attempts") or 0))
            (done if result == "transcribed" else failed).append(chunk["seq"])
        except Unavailable as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=502, detail=live.GENERIC) from exc
    return done, failed, skipped


@router.post("/api/live/{session_id}/transcribe")
def transcribe(session_id: str, payload: TranscribeRequest | None = None, user=Depends(sec.current_user)):
    user = live._need_user(user)
    sid = live._uuid(session_id, "Gravação")
    session = live._get_session(user, sid)
    if session.get("audio_deleted_at"):
        raise HTTPException(status_code=409, detail="O áudio desta gravação foi apagado.")
    retry = bool(payload and payload.retry_failed)
    enforce_hourly_limit(user)
    now = live._now()
    try:
        chunks = sec.service_rest("GET", f"live_chunks?select={CHUNK_COLUMNS}&session_id=eq.{sid}&order=seq.asc&limit=400") or []
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=live.GENERIC) from exc
    done, failed, skipped = run_batch(sid, chunks, now, retry)
    remaining = len(pick_pending([c for c in chunks if c["seq"] not in done and c["seq"] not in failed], now, False))
    return {"ok": True, "transcribed": done, "failed": failed, "skipped": skipped, "remaining": remaining}


@router.get("/api/live/{session_id}/transcript")
def transcript(session_id: str, user=Depends(sec.current_user)):
    user = live._need_user(user)
    sid = live._uuid(session_id, "Gravação")
    session = live._get_session(user, sid)
    rows = live._db(lambda: sec.user_rest(user, "GET", f"live_chunks?select=seq,status,duration_ms,attempts,text&session_id=eq.{sid}&order=seq.asc&limit=400")) or []
    built = assemble(rows)
    done = [r for r in rows if r["status"] == "transcribed"]
    minutes = sum(int(r.get("duration_ms") or 0) for r in done) / 60000
    pending = sum(1 for r in rows if r["status"] in ("uploaded", "transcribing") or (r["status"] == "failed" and r.get("attempts", 0) < MAX_ATTEMPTS))
    stuck = sum(1 for r in rows if r["status"] == "failed" and r.get("attempts", 0) >= MAX_ATTEMPTS)
    try:
        used = round(minutes_last_hour(user), 2)
    except RuntimeError:
        used = None
    return {"ok": True, "session_status": session["status"], "lines": built["lines"], "missing": built["missing"], "text": built["text"],
            "counts": {"chunks": len(rows), "transcribed": len(done), "pending": pending, "failed": stuck},
            "usage": {"minutes_transcribed": round(minutes, 2), "estimated_cost_usd": estimate_cost(minutes), "cost_is_estimate": True,
                      "minutes_last_hour": used, "hourly_limit_minutes": hourly_limit_minutes(), "model": LIVE_MODEL}}
