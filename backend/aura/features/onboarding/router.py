"""AURA AI — onboarding guiado com progresso no servidor (etapa 7, fase 3).

Regras:
  * O progresso é da PESSOA e vale em qualquer aparelho. O banco (RLS) garante que ninguém lê ou altera o de outra pessoa.
  * O que está "feito" é CALCULADO aqui a partir dos dados reais dela (reuniões, clientes, ações, conversas, gravações),
    sempre com o JWT da pessoa. O banco só guarda as escolhas: passos pulados, tutorial dispensado e conclusão.
  * Nada é gravado só por abrir a tela: a primeira linha nasce quando a pessoa pula, dispensa ou conclui.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException

from aura.core import security as sec

log = logging.getLogger("aura.onboarding")
router = APIRouter()

# chave -> (título, descrição, tabela, coluna do dono, tela de destino). A mesma lista existe no banco (onboarding_steps).
STEPS = [
    ("first_meeting", "Analise sua primeira reunião", "Envie um áudio ou uma transcrição e veja resumo, riscos e evidências.", "meetings", "owner_id", "analysis"),
    ("client", "Confira seus clientes", "O AURA agrupa as reuniões por cliente. Confirme ou ajuste o vínculo.", "clients", "owner_id", "clients"),
    ("action", "Acompanhe uma ação", "Transforme uma decisão em ação com responsável e prazo.", "actions", "created_by", "actions"),
    ("chat", "Pergunte aos seus dados", "Faça uma pergunta no chat e veja de qual trecho vem a resposta.", "conversations", "owner_id", "chat"),
    ("live", "Grave uma reunião ao vivo", "Com o consentimento de todos, receba transcrição e alertas durante a conversa.", "live_sessions", "owner_id", "live"),
]
KEYS = [s[0] for s in STEPS]
GENERIC = "Não foi possível carregar o seu progresso agora. Tente novamente."


def _db(call):
    try:
        return call()
    except sec.SupabaseError as exc:
        if exc.db_message in ("onboarding_invalid_step", "onboarding_immutable") or exc.db_code in ("23514", "22P02"):
            raise HTTPException(status_code=400, detail="Passo inválido.") from exc
        raise HTTPException(status_code=502, detail=GENERIC) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=GENERIC) from exc


def _need_user(user):
    if user is None:
        raise HTTPException(status_code=401, detail="Autenticação necessária.")
    return user


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _row(user) -> dict | None:
    rows = _db(lambda: sec.user_rest(user, "GET", f"onboarding_progress?select=skipped,dismissed_at,completed_at&user_id=eq.{user.id}&limit=1")) or []
    return rows[0] if rows else None


def _has(user, table: str, column: str) -> bool:
    return bool(_db(lambda: sec.user_rest(user, "GET", f"{table}?select=id&{column}=eq.{user.id}&limit=1")))


def _save(user, current: dict | None, changes: dict) -> dict:
    if current is None:
        body = {"user_id": user.id, **changes}
        return (_db(lambda: sec.user_rest(user, "POST", "onboarding_progress", body)) or [body])[0]
    rows = _db(lambda: sec.user_rest(user, "PATCH", f"onboarding_progress?user_id=eq.{user.id}", changes)) or []
    return rows[0] if rows else {**current, **changes}


def build_state(user) -> dict:
    row = _row(user) or {}
    skipped = row.get("skipped") or {}
    steps = []
    for key, title, description, table, column, view in STEPS:
        done = _has(user, table, column)
        steps.append({"key": key, "title": title, "description": description, "view": view, "done": done,
                      "skipped": (not done) and key in skipped})
    finished = sum(1 for s in steps if s["done"] or s["skipped"])
    return {"ok": True, "steps": steps, "total": len(steps), "finished": finished, "done_count": sum(1 for s in steps if s["done"]),
            "dismissed": bool(row.get("dismissed_at")), "completed": bool(row.get("completed_at")) or finished == len(steps),
            "visible": not row.get("dismissed_at") and finished < len(steps)}


@router.get("/api/onboarding")
def get_onboarding(user=Depends(sec.current_user)):
    user = _need_user(user)
    state = build_state(user)
    row = _row(user)
    if state["finished"] == state["total"] and not (row or {}).get("completed_at"):
        _save(user, row, {"completed_at": _now()})  # registra a conclusão uma vez
        sec.audit(user, "onboarding.complete", None, "onboarding", user.id)
    return state


@router.post("/api/onboarding/steps/{key}/skip")
def skip_step(key: str, user=Depends(sec.current_user)):
    user = _need_user(user)
    if key not in KEYS:
        raise HTTPException(status_code=400, detail="Passo inválido.")
    row = _row(user)
    skipped = dict((row or {}).get("skipped") or {})
    skipped[key] = _now()
    _save(user, row, {"skipped": skipped})
    sec.audit(user, "onboarding.skip", None, "onboarding", user.id, {"step": key})
    return build_state(user)


@router.post("/api/onboarding/dismiss")
def dismiss(user=Depends(sec.current_user)):
    user = _need_user(user)
    _save(user, _row(user), {"dismissed_at": _now()})
    sec.audit(user, "onboarding.dismiss", None, "onboarding", user.id)
    return build_state(user)


@router.post("/api/onboarding/reset")
def reset(user=Depends(sec.current_user)):
    """Recomeçar o tutorial: limpa os passos pulados e volta a mostrá-lo."""
    user = _need_user(user)
    _save(user, _row(user), {"skipped": {}, "dismissed_at": None, "completed_at": None})
    sec.audit(user, "onboarding.reset", None, "onboarding", user.id)
    return build_state(user)
