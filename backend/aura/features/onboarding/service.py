"""AURA AI — onboarding guiado com progresso no servidor (regras).

  * O progresso é da PESSOA e vale em qualquer aparelho. O banco (RLS) garante que ninguém lê ou altera o de outra pessoa.
  * O que está "feito" é CALCULADO aqui a partir dos dados reais dela (reuniões, clientes, ações, conversas, gravações).
    O banco só guarda as escolhas: passos pulados, tutorial dispensado e conclusão.
  * Nada é gravado só por abrir a tela: a primeira linha nasce quando a pessoa pula, dispensa ou conclui.
"""
from __future__ import annotations

from datetime import datetime, timezone

from aura.core import security as sec
from aura.core.errors import AppError
from aura.features.onboarding import repository

# chave -> (título, descrição, tabela, coluna do dono, tela de destino). A mesma lista existe no banco (onboarding_steps).
STEPS = [
    ("first_meeting", "Analise sua primeira reunião", "Envie um áudio ou uma transcrição e veja resumo, riscos e evidências.", "meetings", "owner_id", "analysis"),
    ("client", "Confira seus clientes", "O AURA agrupa as reuniões por cliente. Confirme ou ajuste o vínculo.", "clients", "owner_id", "clients"),
    ("action", "Acompanhe uma ação", "Transforme uma decisão em ação com responsável e prazo.", "actions", "created_by", "actions"),
    ("chat", "Pergunte aos seus dados", "Faça uma pergunta no chat e veja de qual trecho vem a resposta.", "conversations", "owner_id", "chat"),
    ("live", "Grave uma reunião ao vivo", "Com o consentimento de todos, receba transcrição e alertas durante a conversa.", "live_sessions", "owner_id", "live"),
]
KEYS = [s[0] for s in STEPS]


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def build_state(user) -> dict:
    row = repository.get_progress(user) or {}
    skipped = row.get("skipped") or {}
    steps = []
    for key, title, description, table, column, view in STEPS:
        done = repository.owns_any(user, table, column)
        steps.append({"key": key, "title": title, "description": description, "view": view, "done": done,
                      "skipped": (not done) and key in skipped})
    finished = sum(1 for s in steps if s["done"] or s["skipped"])
    return {"ok": True, "steps": steps, "total": len(steps), "finished": finished, "done_count": sum(1 for s in steps if s["done"]),
            "dismissed": bool(row.get("dismissed_at")), "completed": bool(row.get("completed_at")) or finished == len(steps),
            "visible": not row.get("dismissed_at") and finished < len(steps)}


def get_state(user) -> dict:
    state = build_state(user)
    row = repository.get_progress(user)
    if state["finished"] == state["total"] and not (row or {}).get("completed_at"):
        repository.save_progress(user, row, {"completed_at": _now()})  # registra a conclusão uma vez
        sec.audit(user, "onboarding.complete", None, "onboarding", user.id)
    return state


def skip_step(user, key: str) -> dict:
    if key not in KEYS:
        raise AppError(400, repository.INVALID)
    row = repository.get_progress(user)
    skipped = dict((row or {}).get("skipped") or {})
    skipped[key] = _now()
    repository.save_progress(user, row, {"skipped": skipped})
    sec.audit(user, "onboarding.skip", None, "onboarding", user.id, {"step": key})
    return build_state(user)


def dismiss(user) -> dict:
    repository.save_progress(user, repository.get_progress(user), {"dismissed_at": _now()})
    sec.audit(user, "onboarding.dismiss", None, "onboarding", user.id)
    return build_state(user)


def reset(user) -> dict:
    """Recomeçar o tutorial: limpa os passos pulados e volta a mostrá-lo."""
    repository.save_progress(user, repository.get_progress(user), {"skipped": {}, "dismissed_at": None, "completed_at": None})
    sec.audit(user, "onboarding.reset", None, "onboarding", user.id)
    return build_state(user)
