"""Onboarding — acesso aos dados (PostgREST, sempre com o JWT da pessoa: o RLS decide o que ela lê e grava)."""
from __future__ import annotations

from aura.core import security as sec
from aura.core.errors import db_call

GENERIC = "Não foi possível carregar o seu progresso agora. Tente novamente."
INVALID = "Passo inválido."
KNOWN = {"onboarding_invalid_step": (400, INVALID), "onboarding_immutable": (400, INVALID)}


def _db(call):
    return db_call(call, generic=GENERIC, known=KNOWN, invalid=INVALID)


def get_progress(user) -> dict | None:
    rows = _db(lambda: sec.user_rest(user, "GET", f"onboarding_progress?select=skipped,dismissed_at,completed_at&user_id=eq.{user.id}&limit=1")) or []
    return rows[0] if rows else None


def owns_any(user, table: str, column: str) -> bool:
    """A pessoa tem pelo menos um registro seu nesta tabela? (é assim que um passo conta como feito)"""
    return bool(_db(lambda: sec.user_rest(user, "GET", f"{table}?select=id&{column}=eq.{user.id}&limit=1")))


def save_progress(user, current: dict | None, changes: dict) -> dict:
    """Cria a linha da pessoa na primeira vez e atualiza nas seguintes."""
    if current is None:
        body = {"user_id": user.id, **changes}
        return (_db(lambda: sec.user_rest(user, "POST", "onboarding_progress", body)) or [body])[0]
    rows = _db(lambda: sec.user_rest(user, "PATCH", f"onboarding_progress?user_id=eq.{user.id}", changes)) or []
    return rows[0] if rows else {**current, **changes}
