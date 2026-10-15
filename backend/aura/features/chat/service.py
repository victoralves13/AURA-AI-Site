"""AURA AI — conversas do chat: histórico persistente, privado e por espaço, e a orquestração da resposta (regras).

  * A conversa é PRIVADA: só quem a criou a vê. Administradores da organização não leem o chat de outra pessoa.
    O banco garante isso (RLS); aqui o JWT da pessoa é sempre usado.
  * A conversa vive em um espaço (conta pessoal ou organização, com a permissão `chat.use`) e pode ter um escopo
    (uma reunião, um cliente ou uma ação do MESMO espaço), que limita sobre o que se conversa.
  * O navegador só grava a pergunta da pessoa. A resposta do AURA, com as fontes citadas, é gravada só pelo backend com a
    chave de serviço (`append_assistant`), depois de conferir que a conversa é da pessoa.
  * Ao receber uma pergunta, o motor (`engine`) responde só com dados que a pessoa lê, com cada afirmação comprovada por um
    trecho. Se a IA falhar, a pergunta continua gravada e a pessoa pode pedir a resposta de novo.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone

from aura.core import security as sec
from aura.core.errors import AppError
from aura.features.chat import context, engine, repository
from aura.features.chat.schemas import ConversationCreate, ConversationUpdate, MessageCreate
from aura.features.clients import service as clients_mod

log = logging.getLogger("aura.conversations")

DEFAULT_TITLE = "Nova conversa"
MAX_CONTENT = 4000
EVIDENCE_LEVELS = ("forte", "parcial", "insuficiente")


def _uuid(value, what: str) -> str:
    if not isinstance(value, str) or not sec.UUID_RE.match(value):
        raise AppError(400, f"{what} inválido.")
    return value.lower()


def _org(user: sec.AuthUser, org_id: str | None) -> str | None:
    """'personal'/vazio -> conta pessoal (None); uuid -> organização, exigindo a permissão de usar o chat."""
    if not org_id or org_id == "personal":
        return None
    org = _uuid(org_id, "Espaço")
    sec.require_org_permission(user, org, "chat.use")
    return org


def _clean(value, size: int) -> str:
    return " ".join(str(value or "").split())[:size]


def _clean_content(value) -> str:
    text = str(value or "").replace("\r\n", "\n").strip()
    if not text or len(text) > MAX_CONTENT:
        raise AppError(400, f"Escreva uma mensagem de até {MAX_CONTENT} caracteres.")
    return text


def _space_filter(org: str | None) -> str:
    return f"org_id=eq.{org}" if org else "org_id=is.null"


def _check_scope(user: sec.AuthUser, org: str | None, scope) -> dict:
    """Valida o escopo: só chaves conhecidas, ids válidos, itens que a pessoa lê e que são do MESMO espaço."""
    if scope in (None, {}):
        return {}
    if not isinstance(scope, dict):
        raise AppError(400, "Escopo inválido.")
    out: dict = {}
    for key, value in scope.items():
        if key not in repository.SCOPE_TABLES:
            raise AppError(400, "Escopo inválido.")
        item_id = _uuid(value, "Item do escopo")
        row = repository.scope_item(user, repository.SCOPE_TABLES[key], item_id)
        if row is None:
            raise AppError(404, "Item do escopo não encontrado.")
        if row.get("org_id") != org:
            raise AppError(409, "O item do escopo precisa ser do mesmo espaço da conversa.")
        out[key] = item_id
    return out


def _get_conversation(user: sec.AuthUser, conversation_id: str) -> dict:
    conversation = repository.get_conversation(user, conversation_id)
    if conversation is None:
        raise AppError(404, repository.NOT_FOUND)
    return conversation


def append_assistant(user: sec.AuthUser, conversation_id: str, content: str, sources: list | None = None,
                     evidence_level: str | None = None) -> dict:
    """Grava a resposta do AURA (só o backend faz isso). Confere antes que a conversa é da pessoa."""
    conversation = _get_conversation(user, _uuid(conversation_id, "Conversa"))
    if evidence_level is not None and evidence_level not in EVIDENCE_LEVELS:
        raise ValueError("nível de evidência inválido")
    row = {"conversation_id": conversation["id"], "owner_id": user.id, "role": "assistant", "content": str(content)[:20000],
           "sources": list(sources or []), "evidence_level": evidence_level}
    return repository.insert_assistant_message(row)


# ---------------------------------------------------------------------------
# Recuperação, limite de uso e resposta
# ---------------------------------------------------------------------------
def load_universe(user: sec.AuthUser, org_id: str | None, scope: dict | None) -> dict:
    """Lê (uma vez por pergunta) as reuniões e ações que a pessoa pode ver no espaço e no escopo da conversa, e monta a visão geral.

    Sem escopo: as reuniões mais recentes do espaço. Escopo de reunião/ação: SÓ aquela reunião (a conversa continua limitada ao item).
    Escopo de cliente: as reuniões dele. Tudo com o JWT da pessoa (RLS) e sem valores financeiros de terceiros."""
    scope = scope or {}
    space = f"org_id=eq.{org_id}" if org_id else "org_id=is.null"
    scoped_actions: list[dict] = []
    if scope.get("action_id"):
        scoped_actions = repository.action_in_scope(user, space, scope["action_id"])
        ids = ",".join(sorted({a["meeting_id"] for a in scoped_actions}))
        meetings = repository.meetings_by_ids(user, ids) if ids else []
    elif scope.get("meeting_id"):
        meetings = repository.meeting_in_scope(user, space, scope["meeting_id"])
    elif scope.get("client_id"):
        meetings = repository.client_meetings(user, space, scope["client_id"], context.OVERVIEW_CLIENTS * 3)
    else:
        meetings = repository.portfolio_meetings(user, space)
    meetings = sec.redact_meetings(meetings, user)
    ids = {m["id"] for m in meetings}
    pool = [a for a in repository.action_pool(user, space, 200) if a.get("meeting_id") in ids]
    today = context.today_iso()
    overview, clients = context.build_overview(meetings, pool, today, clients_mod.groups_by_client(user, org_id))
    return {"meetings": meetings, "actions": pool, "scoped_actions": scoped_actions, "overview": overview, "clients": clients, "today": today}


def build_sources(user: sec.AuthUser, universe: dict, scope: dict | None, question: str, history: list[dict],
                  extra_clients: list[str] | None = None, limit: int = context.MAX_DETAIL_MEETINGS) -> tuple[list[engine.Source], str]:
    """Fontes para o prompt: S0 (visão geral) + o detalhe escolhido (S1…), e a frase de foco da conversa."""
    scope = scope or {}
    chosen, _keys, note = context.choose_focus(question, history, scope, universe["meetings"], universe["clients"], extra_clients, limit)
    transcripts: dict[str, str] = {}
    if chosen:
        for row in repository.transcripts(user, [m["id"] for m in chosen]):
            transcripts[row["id"]] = (row.get("transcript") or "")[:engine.MAX_TRANSCRIPT_CHARS]
    by_meeting: dict[str, list[dict]] = {}
    for a in universe["actions"] + universe["scoped_actions"]:
        by_meeting.setdefault(a["meeting_id"], []).append(a)
    sources: list[engine.Source] = [context.overview_source(universe["overview"])]
    forced = bool(scope.get("meeting_id") or scope.get("action_id") or scope.get("client_id"))
    for i, m in enumerate(chosen, 1):
        key = f"S{i}"
        tr = transcripts.get(m["id"], "")
        block, analysis = engine._meeting_block(key, m, by_meeting.get(m["id"], []), engine.best_lines(tr, question, fallback=forced))
        sources.append(engine.Source(key, "meeting", m["id"], engine._clip(m.get("meeting_title") or m.get("client_name") or "Reunião", 120), block,
                                     transcript=tr, analysis=analysis, meta={"client_name": m.get("client_name"), "date": str(m.get("created_at") or "")[:10]}))
    n = len(sources) - 1
    for a in universe["scoped_actions"]:
        n += 1
        sources.append(engine._action_source(f"S{n}", a))
    return sources, note


def retrieve(user: sec.AuthUser, org_id: str | None, scope: dict | None, question: str, history: list[dict] | None = None) -> list[engine.Source]:
    """Fontes (S0 + detalhe) para uma pergunta, no espaço e no escopo da conversa."""
    universe = load_universe(user, org_id, scope)
    return build_sources(user, universe, scope, question, history or [])[0]


def enforce_chat_limit(user: sec.AuthUser) -> None:
    """Limita respostas do chat por pessoa e hora (custo de IA). Falha de verificação bloqueia (fail closed)."""
    limit = int(os.getenv("AURA_MAX_CHAT_PER_HOUR", "60") or "60")
    since = (datetime.now(timezone.utc) - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        used = repository.count_recent_answers(user.id, since, limit)
    except RuntimeError as exc:
        raise sec.limit_check_failed(exc) from exc
    if used >= limit:
        raise AppError(429, "Limite de perguntas por hora atingido. Tente novamente mais tarde.")


def _ask(question: str, history: list[dict], sources: list[engine.Source], note: str, today: str) -> engine.ChatAnswer:
    return engine.ask_model(engine.SYSTEM_PROMPT, engine.build_prompt(question, history, sources, focus=note, today=today))


def answer(user: sec.AuthUser, org_id: str | None, scope: dict | None, question: str, history: list[dict]) -> dict:
    """Responde a uma pergunta: monta o contexto, redige, confere cada afirmação e monta. Retorna {content, sources, evidence_level, stats}.

    Normalmente é UMA chamada à IA. Se a IA disser que faltou detalhe de algum cliente (`needs`), há UMA segunda rodada com esse detalhe."""
    universe = load_universe(user, org_id, scope)
    sources, note = build_sources(user, universe, scope, question, history)
    draft = _ask(question, history, sources, note, universe["today"])
    rounds = 1
    if draft.needs and not draft.reply:
        extra = context.mentioned_clients(", ".join(draft.needs), universe["clients"])
        if extra:  # só se o pedido bater com clientes reais da carteira
            sources, note = build_sources(user, universe, scope, question, history, extra, context.MAX_DETAIL_AFTER_NEEDS)
            draft = _ask(question, history, sources, note, universe["today"])
            rounds = 2
    kept, dropped = engine.verify_claims(draft.claims, sources)
    direct = draft.reply if not draft.claims else None  # resposta direta só quando a IA não afirmou nada sobre os dados
    content, out_sources = engine.assemble(kept, draft.not_found, sources, dropped, reply=direct)
    level = None if (not kept and direct and direct.strip()) else engine.evidence_level(kept, dropped)
    return {"content": content, "sources": out_sources, "evidence_level": level,
            "stats": {"searched": len(sources) - 1, "kept": len(kept), "dropped": dropped, "rounds": rounds}}


def _answer(user: sec.AuthUser, conversation: dict, question: str) -> tuple[dict | None, str | None]:
    """Gera e grava a resposta do AURA. Retorna (mensagem, None) ou (None, texto do erro). Nunca perde a pergunta."""
    cid = conversation["id"]
    try:
        past = repository.history(user, cid)
        history = past[:-1] if past and past[-1].get("role") == "user" else past  # a pergunta atual não é "conversa anterior"
        result = answer(user, conversation.get("org_id"), conversation.get("scope") or {}, question, history)
        message = append_assistant(user, cid, result["content"], result["sources"], result["evidence_level"])
    except (engine.ChatUnavailable, engine.ChatFailure) as exc:
        return None, str(exc)
    except AppError as exc:
        return None, exc.detail if isinstance(exc.detail, str) else repository.GENERIC
    except Exception as exc:  # falha da IA, da rede ou de validação: a pessoa pode tentar de novo
        log.warning("resposta do chat não gerada: %s", type(exc).__name__)
        return None, "Não consegui gerar a resposta agora. Tente novamente."
    sec.audit(user, "chat.answer", conversation.get("org_id"), "conversation", cid,
              {"evidence": result["evidence_level"], "sources": len(result["sources"]), "dropped": result["stats"]["dropped"]})
    return message, None


# ---------------------------------------------------------------------------
# Casos de uso da API
# ---------------------------------------------------------------------------
def list_conversations(user, org_id: str | None, limit: int) -> dict:
    org = _org(user, org_id)
    return {"ok": True, "conversations": repository.list_conversations(user, _space_filter(org), max(1, min(limit, 200)))}


def create_conversation(user, payload: ConversationCreate) -> dict:
    org = _org(user, payload.org_id)
    title = _clean(payload.title, 200) or DEFAULT_TITLE
    scope = _check_scope(user, org, payload.scope)
    created = repository.insert_conversation(user, {"owner_id": user.id, "org_id": org, "title": title, "scope": scope})
    sec.audit(user, "conversation.create", org, "conversation", created.get("id"), {"scoped": bool(scope)})
    return {"ok": True, "conversation": created}


def get_conversation(user, conversation_id: str) -> dict:
    cid = _uuid(conversation_id, "Conversa")
    conversation = _get_conversation(user, cid)
    return {"ok": True, "conversation": conversation, "messages": repository.list_messages(user, cid)}


def rename_conversation(user, conversation_id: str, payload: ConversationUpdate) -> dict:
    cid = _uuid(conversation_id, "Conversa")
    title = _clean(payload.title, 201)
    if not title or len(title) > 200:
        raise AppError(400, "O título deve ter entre 1 e 200 caracteres.")
    current = _get_conversation(user, cid)
    row = repository.rename_conversation(user, cid, title)
    if row is None:
        raise AppError(404, repository.NOT_FOUND)
    sec.audit(user, "conversation.rename", current.get("org_id"), "conversation", cid)
    return {"ok": True, "conversation": row}


def delete_conversation(user, conversation_id: str) -> dict:
    cid = _uuid(conversation_id, "Conversa")
    current = _get_conversation(user, cid)
    repository.delete_conversation(user, cid)
    sec.audit(user, "conversation.delete", current.get("org_id"), "conversation", cid)
    return {"ok": True}


def add_message(user, conversation_id: str, payload: MessageCreate) -> dict:
    """Grava a pergunta da pessoa e devolve a resposta do AURA (ou o motivo de não ter sido gerada)."""
    cid = _uuid(conversation_id, "Conversa")
    content = _clean_content(payload.content)
    conversation = _get_conversation(user, cid)
    if conversation.get("org_id"):  # a permissão pode ter sido retirada depois da criação
        sec.require_org_permission(user, conversation["org_id"], "chat.use")
    enforce_chat_limit(user)  # antes de gravar: pergunta barrada pelo limite não fica sem resposta
    message = repository.insert_user_message(user, {"conversation_id": cid, "role": "user", "content": content})
    if conversation.get("title") == DEFAULT_TITLE:  # a primeira pergunta nomeia a conversa
        try:
            repository.set_title(user, cid, _clean(content, 60))
        except RuntimeError as exc:
            log.warning("título da conversa não atualizado: %s", exc)
    reply, error = _answer(user, conversation, content)
    return {"ok": True, "message": message, "answer": reply, "answer_error": error}


def retry_answer(user, conversation_id: str) -> dict:
    """Pede de novo a resposta da última pergunta (quando a primeira tentativa falhou)."""
    cid = _uuid(conversation_id, "Conversa")
    conversation = _get_conversation(user, cid)
    if conversation.get("org_id"):
        sec.require_org_permission(user, conversation["org_id"], "chat.use")
    last = repository.last_message(user, cid)
    if not last or last.get("role") != "user":
        raise AppError(409, "Não há pergunta sem resposta nesta conversa.")
    enforce_chat_limit(user)
    reply, error = _answer(user, conversation, last["content"])
    return {"ok": True, "answer": reply, "answer_error": error}
