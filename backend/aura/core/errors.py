"""AURA AI — erros da aplicação, compartilhados por todas as camadas.

`AppError` é um HTTPException (a API responde com o mesmo status e o mesmo corpo de sempre), mas pode ser levantado pelas camadas de
serviço e de dados sem que elas dependam de FastAPI: elas importam daqui, não de `fastapi`.
"""
from __future__ import annotations

from typing import Any, Callable

from fastapi import HTTPException

from aura.core import security as sec


class AppError(HTTPException):
    def __init__(self, status_code: int, detail: str):
        super().__init__(status_code=status_code, detail=detail)


def require_user(user: Any) -> Any:
    """Os endpoints de dados só existem para quem entrou (no modo legado, sem login, `user` é None)."""
    if user is None:
        raise AppError(401, "Autenticação necessária.")
    return user


def db_call(call: Callable[[], Any], *, generic: str, known: dict[str, tuple[int, str]] | None = None, invalid: str | None = None,
            forbidden: str | None = None) -> Any:
    """Executa uma chamada ao banco e traduz a falha para AppError (a camada de dados é a única que conhece o PostgREST).

    known:     mensagem do banco -> (status, texto para a pessoa)
    invalid:   texto (400) para violação de CHECK / formato inválido (códigos 23514 e 22P02)
    forbidden: texto (403) para recusa por permissão ou RLS (401/403 do banco)
    generic:   texto (502) para qualquer outra falha
    """
    try:
        return call()
    except sec.SupabaseError as exc:
        if known and exc.db_message in known:
            status, detail = known[exc.db_message]
            raise AppError(status, detail) from exc
        if invalid and exc.db_code in ("23514", "22P02"):
            raise AppError(400, invalid) from exc
        if forbidden and exc.status in (401, 403):
            raise AppError(403, forbidden) from exc
        raise AppError(502, generic) from exc
    except RuntimeError as exc:
        raise AppError(502, generic) from exc
