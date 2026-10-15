"""Ações — indicadores de acompanhamento e eficácia (cálculo puro). Taxas ficam nulas quando não há base para calculá-las."""
from __future__ import annotations

STATUSES = ("open", "in_progress", "done", "cancelled")
ACTIVE = ("open", "in_progress")
EFFECTIVENESS = ("worked", "partial", "not_worked", "uncertain")


def _rate(worked: int, judged: int) -> float | None:
    return round(worked / judged, 3) if judged else None  # sem avaliações, sem taxa (nunca inventada)


def compute(rows: list[dict], today: str) -> dict:
    by_status = {s: 0 for s in STATUSES}
    effect = {e: 0 for e in EFFECTIVENESS}
    overdue = with_outcome = closed_without = 0
    groups: dict[str, dict[str, int]] = {}
    useful = not_useful = 0
    for r in rows:
        for v in r.get("action_feedback") or []:
            useful += v.get("rating") == "useful"
            not_useful += v.get("rating") == "not_useful"
        status = r.get("status")
        by_status[status] = by_status.get(status, 0) + 1
        late = status in ACTIVE and bool(r.get("due_date")) and r["due_date"] < today
        overdue += late
        outcomes = r.get("action_outcomes") or []
        if outcomes:
            with_outcome += 1
            latest = max(outcomes, key=lambda o: o.get("created_at") or "")["effectiveness"]
            effect[latest] += 1
            if latest != "uncertain":  # "incerto" não entra nas taxas
                key = "ia_" + (r.get("basis") or "sem_base") if r.get("source") == "ai" else "pessoa"
                g = groups.setdefault(key, {"evaluated": 0, "worked": 0})
                g["evaluated"] += 1
                g["worked"] += latest == "worked"
        elif status in ("done", "cancelled") or late:
            closed_without += 1
    tracked = len(rows) - by_status["cancelled"]
    judged = effect["worked"] + effect["partial"] + effect["not_worked"]
    return {"total": len(rows), "by_status": by_status, "overdue": overdue,
            "completion_rate": round(by_status["done"] / tracked, 3) if tracked else None,
            "with_outcome": with_outcome, "closed_without_outcome": closed_without, "effectiveness": effect,
            "effective_rate": _rate(effect["worked"], judged), "evaluated": judged,
            "by_origin": {k: {**g, "effective_rate": _rate(g["worked"], g["evaluated"])} for k, g in sorted(groups.items())},
            "feedback": {"useful": useful, "not_useful": not_useful, "useful_rate": _rate(useful, useful + not_useful)}}
