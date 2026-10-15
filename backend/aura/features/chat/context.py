"""Chat — montagem do contexto que o modelo recebe (regra pura: sem banco, sem HTTP, sem IA).

O problema que isto resolve: antes, o modelo só via até 6 reuniões escolhidas por palavras da PERGUNTA ATUAL, sem datas, sem a evolução do
risco, sem a carteira de clientes e sem lembrar de quem se falava. Perguntas naturais ("quais clientes mais preocupam?", "o que mudou?",
"e depois?") ficavam sem dado para responder. Agora o contexto tem três camadas:

  S0  VISÃO GERAL da carteira: uma linha por cliente (datas, evolução do risco, oportunidade, ações em aberto, último resumo),
      do mais preocupante ao menos preocupante. Pequena (dezenas de linhas) e sempre presente.
  S1… DETALHE das reuniões escolhidas, em ordem cronológica por cliente, com sinais de risco/oportunidade, decisões, ações e trechos.
  FOCO  de que cliente/reunião vinha a conversa (resolve "esse cliente", "qual deles?", "e depois?").

A escolha do detalhe usa (1) o escopo da conversa, (2) clientes citados na pergunta, (3) o foco herdado da resposta anterior e, sem nenhum
desses, (4) os clientes mais preocupantes e as reuniões mais ligadas ao assunto. Nada de lista fixa de perguntas ou respostas prontas.
"""
from __future__ import annotations

from datetime import date

from aura.core import verification
from aura.features.chat import engine
from aura.features.clients.matching import GENERIC, is_placeholder, normalize_name

MAX_DETAIL_MEETINGS = 8        # reuniões com detalhe na primeira rodada
MAX_DETAIL_AFTER_NEEDS = 11    # teto depois de a IA pedir mais detalhe
PER_CLIENT = 3                 # últimas reuniões de um cliente em foco
OVERVIEW_CLIENTS = 40
RISK_WEIGHT = {"Alto": 3, "Médio": 2, "Baixo": 1, "—": 0}


def risk_level(value) -> str:
    n = verification.normalize(str(value or ""))
    if "alto" in n or "critic" in n:
        return "Alto"
    if "medio" in n or "moderad" in n:
        return "Médio"
    if "baixo" in n:
        return "Baixo"
    return "—"


def _day(m: dict) -> str:
    return str(m.get("created_at") or "")[:10]


def client_key(m: dict) -> str:
    return str(m.get("client_id") or "") or "n:" + normalize_name(m.get("client_name") or "")


def client_label(m: dict) -> str:
    name = (m.get("client_name") or "").strip()
    return name if name and not is_placeholder(name) else "Cliente não identificado"


def group_by_client(meetings: list[dict]) -> dict[str, list[dict]]:
    """Reuniões por cliente, da mais antiga para a mais recente."""
    groups: dict[str, list[dict]] = {}
    for m in sorted(meetings, key=lambda x: str(x.get("created_at") or "")):
        groups.setdefault(client_key(m), []).append(m)
    return groups


def _is_late(a: dict, today: str) -> bool:
    return a.get("status") in ("open", "in_progress") and bool(a.get("due_date")) and str(a["due_date"]) < today


def build_overview(meetings: list[dict], actions: list[dict], today: str) -> tuple[str, list[dict]]:
    """Texto da visão geral (S0) e a lista de clientes ordenada do mais para o menos preocupante."""
    by_client: dict[str, list[dict]] = {}
    for a in actions:
        mt = a.get("meetings") or {}
        key = str(mt.get("client_id") or "") or "n:" + normalize_name(mt.get("client_name") or "")
        by_client.setdefault(key, []).append(a)
    rows = []
    for key, ms in group_by_client(meetings).items():
        risks = [risk_level(m.get("risk")) for m in ms]
        last = ms[-1]
        acts = by_client.get(key, [])
        open_acts = [a for a in acts if a.get("status") in ("open", "in_progress")]
        late = sum(1 for a in open_acts if _is_late(a, today))
        worry = RISK_WEIGHT[risks[-1]] * 10 + (5 if RISK_WEIGHT[risks[-1]] > RISK_WEIGHT[risks[0]] else 0) + 3 * late + len(open_acts)
        rows.append({"key": key, "name": client_label(last), "meetings": ms, "risks": risks, "last": last, "open": len(open_acts), "late": late,
                     "worry": worry})
    rows.sort(key=lambda r: (r["worry"], _day(r["last"])), reverse=True)
    lines = []
    for r in rows[:OVERVIEW_CLIENTS]:
        ms = r["meetings"]
        dates = ", ".join(_day(m) for m in ms[-5:])
        trend = " → ".join(r["risks"][-5:])
        direction = ("subiu" if RISK_WEIGHT[r["risks"][-1]] > RISK_WEIGHT[r["risks"][0]] else
                     "caiu" if RISK_WEIGHT[r["risks"][-1]] < RISK_WEIGHT[r["risks"][0]] else "estável") if len(ms) > 1 else "uma reunião só"
        acts = f"{r['open']} em aberto" + (f" ({r['late']} atrasada(s))" if r["late"] else "")
        lines.append(f"- {r['name']} | reuniões: {len(ms)} ({dates}) | risco: {trend} ({direction}) | oportunidade atual: {risk_level(r['last'].get('opportunity'))}"
                     f" | ações: {acts} | último resumo: {engine._clip(r['last'].get('summary'), 130)}")
    hidden = len(rows) - len(lines)
    head = f"[S0] VISÃO GERAL · {len(meetings)} reunião(ões) de {len(rows)} cliente(s) · do mais preocupante ao menos preocupante · hoje: {today}"
    if hidden > 0:
        lines.append(f"(+{hidden} cliente(s) menos relevantes não listados)")
    return engine.neutralize(head + "\n" + "\n".join(lines)), rows


def overview_source(text: str) -> engine.Source:
    return engine.Source("S0", "overview", "", "Visão geral dos clientes", text, transcript="", analysis=text, meta={})


# ---------------------------------------------------------------------------
# Clientes citados e foco herdado da conversa
# ---------------------------------------------------------------------------
def _meaningful(name: str) -> set[str]:
    return {t for t in normalize_name(name).split() if t not in GENERIC and len(t) > 1}


def mentioned_clients(text: str, clients: list[dict]) -> list[str]:
    """Chaves dos clientes citados no texto. Vale o nome inteiro (todas as palavras relevantes) e, na falta dele, só a PRIMEIRA palavra
    relevante do nome ("Órbita" para "Órbita Saúde"), que é como as pessoas falam; palavras comuns da conversa não contam."""
    wanted = set(verification.normalize(text or "").split())
    full, head = [], []  # full: (palavras, chave)
    for c in clients:
        words = _meaningful(c["name"])
        if not words:
            continue
        if words <= wanted:
            full.append((len(words), c["key"]))
            continue
        first = next((t for t in normalize_name(c["name"]).split() if t in words), "")
        if len(first) >= 4 and first in wanted and first not in engine.STOPWORDS:
            head.append(c["key"])
    if full:  # nomes inteiros: vale o mais específico ("Atlas Sul" vence "Grupo Atlas" quando a pergunta diz "Atlas Sul")
        top = max(n for n, _ in full)
        return list(dict.fromkeys(k for n, k in full if n == top))
    return list(dict.fromkeys(head))


def carried_over(history: list[dict], clients: list[dict], meeting_client: dict[str, str]) -> list[str]:
    """Clientes em discussão: os da última resposta do AURA (pelas fontes citadas) ou, na falta, os citados nas últimas perguntas."""
    for h in reversed(history):
        if h.get("role") != "assistant":
            continue
        keys = []
        for s in (h.get("sources") or []):
            if isinstance(s, dict) and s.get("type") == "meeting" and s.get("id") in meeting_client:
                k = meeting_client[s["id"]]
                if k not in keys:
                    keys.append(k)
        if keys:
            return keys
        break
    keys = []
    for h in reversed(history[-6:]):
        if h.get("role") == "user":
            for k in mentioned_clients(h.get("content") or "", clients):
                if k not in keys:
                    keys.append(k)
    return keys


def _last(rows_by_key: dict[str, dict], key: str, count: int) -> list[dict]:
    return rows_by_key[key]["meetings"][-count:] if key in rows_by_key else []


def choose_focus(question: str, history: list[dict], scope: dict, meetings: list[dict], clients: list[dict],
                 extra_clients: list[str] | None = None, limit: int = MAX_DETAIL_MEETINGS) -> tuple[list[dict], list[str], str]:
    """Reuniões que entram com detalhe (ordem cronológica por cliente), chaves dos clientes em foco e a frase de foco para o prompt."""
    rows_by_key = {r["key"]: r for r in clients}
    meeting_client = {m["id"]: client_key(m) for m in meetings}
    keys: list[str] = []
    note = ""
    if scope.get("meeting_id") and scope["meeting_id"] in meeting_client:
        keys = [meeting_client[scope["meeting_id"]]]
        note = "a conversa é sobre uma reunião específica e o cliente dela"
    elif scope.get("client_id"):
        keys = [k for k in rows_by_key if k == scope["client_id"]] or list(rows_by_key)[:1]
        note = "a conversa é sobre um cliente específico"
    mentioned = mentioned_clients(question, clients)
    if mentioned:
        keys = list(dict.fromkeys(mentioned + keys))
        note = note or "cliente citado na pergunta"
    if not keys:
        carried = carried_over(history, clients, meeting_client)
        if carried:
            keys, note = carried, "cliente(s) da resposta anterior (a pergunta atual não cita cliente)"
    for k in extra_clients or []:
        if k not in keys:
            keys.append(k)
    chosen: list[dict] = []

    def add(ms):
        for m in ms:
            if m not in chosen and len(chosen) < limit:
                chosen.append(m)

    if scope.get("meeting_id"):
        add([m for m in meetings if m["id"] == scope["meeting_id"]])
    if keys:
        for k in keys:
            add(_last(rows_by_key, k, PER_CLIENT))
        names = ", ".join(rows_by_key[k]["name"] for k in keys if k in rows_by_key)
        note = f"{note}: {names}" if names else note
    else:
        for r in clients[:3]:  # sem cliente definido: os mais preocupantes, com as duas últimas reuniões de cada um
            add(r["meetings"][-2:])
        for m in engine.rank_meetings(question, meetings, limit=3):
            if engine.tokens(question) & engine.tokens(engine.meeting_text(m)):  # só quando há assunto em comum de verdade
                add([m])
        note = "nenhum cliente específico; foram detalhados os mais preocupantes e as reuniões ligadas ao assunto"
    chosen.sort(key=lambda m: (client_key(m), str(m.get("created_at") or "")))
    return chosen, keys, note


def today_iso() -> str:
    return date.today().isoformat()
