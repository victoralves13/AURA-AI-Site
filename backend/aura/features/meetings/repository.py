"""Reuniões — acesso aos dados (PostgREST).

Com `user`, usa o JWT da pessoa (o RLS do banco vale); sem `user` (modo legado, sem login), usa a chave de serviço.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

from aura.core import security as sec

# Colunas da análise v2 (migração 20261014140000). Se ainda não existirem no banco, o salvamento
# degrada: grava sem elas e devolve tudo na resposta, em vez de perder a reunião.
V2_COLUMNS = ("analysis_version", "decisions_detail", "actions_detail", "evidence_summary", "client_link", "client_suggestion")


def request(method: str, path: str, payload=None, user=None):
    """Chamada PostgREST. Sem credenciais configuradas (e sem usuário) devolve None: a reunião fica só no navegador."""
    url, key = os.getenv("SUPABASE_URL"), (os.getenv("SUPABASE_SECRET_KEY") or os.getenv("SUPABASE_SERVICE_ROLE_KEY"))
    if user is not None:
        if not url or not sec.publishable_key():
            raise RuntimeError("Supabase não configurado para autenticação de usuários.")
        headers = {**sec.rest_headers(user), "Content-Type": "application/json"}
    else:
        if not url or not key:
            return None
        headers = {"apikey": key, "Authorization": f"Bearer {key}", "Content-Type": "application/json", "Prefer": "return=representation"}
    req = urllib.request.Request(url.rstrip("/") + "/rest/v1/" + path, method=method, headers=headers)
    if payload is not None:
        req.data = json.dumps(payload, ensure_ascii=False).encode()
    try:
        with urllib.request.urlopen(req, timeout=15) as response:
            return json.loads(response.read().decode() or "[]")
    except urllib.error.HTTPError as exc:
        try:
            body = exc.read().decode("utf-8", errors="replace")
        except Exception:
            body = ""
        detail = body or str(exc)
        raise RuntimeError(f"Supabase error: HTTP {exc.code}: {detail}") from exc
    except Exception as exc:
        raise RuntimeError(f"Supabase error: {exc}") from exc


def is_schema_error(exc: RuntimeError, names: tuple) -> bool:
    """O PostgREST recusou por coluna desconhecida / cache de esquema desatualizado (logo depois de uma migração)."""
    message = str(exc).lower()
    return "400" in message and any(x in message for x in ("schema cache", "pgrst204", "pgrst") + tuple(names))


def list_meetings(user, limit: int, space: str):
    return request("GET", f"meetings?select=*&order=created_at.desc&limit={limit}{space}", user=user)


def insert_meeting(payload: dict, user=None):
    return request("POST", "meetings", payload, user=user)
