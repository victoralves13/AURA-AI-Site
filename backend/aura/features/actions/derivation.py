"""Ações — derivação das ações de uma reunião (regra pura, sem banco e sem rede).

  * A ação nasce da análise (origem "ai") ou é digitada por uma pessoa (origem "user").
  * Responsável e prazo só existem como foram ditos na reunião (texto) ou como uma pessoa definiu.
  * Evidência marcada como "não localizada" na transcrição não vira ação acompanhável (fica só no detalhe).
  * A sincronização é idempotente (chave = texto normalizado).
"""
from __future__ import annotations

import hashlib
from datetime import date

from aura.core import verification

MAX_ACTIONS_PER_MEETING = 50


def source_key(text: str) -> str:
    return hashlib.sha1(verification.normalize(text).encode("utf-8")).hexdigest()[:20]


def iso_date(value) -> str | None:
    try:
        return date.fromisoformat(str(value).strip()).isoformat()
    except (TypeError, ValueError):
        return None


def short(value, size: int) -> str | None:
    text = " ".join(str(value or "").split())
    return text[:size] or None


def actions_from_meeting(meeting: dict) -> list[dict]:
    """Ações acompanháveis de uma reunião, no formato da tabela `actions` (sem meeting_id/org_id)."""
    out: list[dict] = []
    seen: set[str] = set()

    def add(row: dict) -> None:
        key = row["source_key"]
        if key not in seen and len(out) < MAX_ACTIONS_PER_MEETING:
            seen.add(key)
            out.append(row)

    detail = meeting.get("actions_detail") or []
    if isinstance(detail, list) and detail:
        for item in detail:
            if not isinstance(item, dict):
                continue
            text = short(item.get("description"), 1000)
            if not text or item.get("evidence_check") == verification.NAO_LOCALIZADA:
                continue
            basis = item.get("basis") if item.get("basis") in ("dito", "inferido") else None
            evidence = {k: item.get(k) for k in ("evidence", "timestamp", "speaker", "evidence_check", "inference_rationale")
                        if item.get(k) is not None}
            add({"text": text, "source": "ai", "source_key": source_key(text), "basis": basis, "evidence": evidence,
                 "assignee_text": short(item.get("owner"), 200), "due_text": short(item.get("deadline"), 200),
                 "due_date": iso_date(item.get("deadline"))})
        return out
    # reuniões antigas (antes da análise v2): só o texto das pendências, sem responsável nem prazo inventados
    for raw in meeting.get("pending_actions") or []:
        text = short(raw.get("description") if isinstance(raw, dict) else raw, 1000)
        if text:
            add({"text": text, "source": "ai", "source_key": source_key(text), "basis": None, "evidence": {},
                 "assignee_text": None, "due_text": None, "due_date": None})
    return out
