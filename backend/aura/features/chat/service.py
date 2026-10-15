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
from aura.core import verification
from aura.core.errors import AppError
from aura.features.chat import engine, repository
from aura.features.chat.schemas import ConversationCreate, ConversationUpdate, MessageCreate

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
def retrieve(user: sec.AuthUser, org_id: str | None, scope: dict | None, question: str) -> list[engine.Source]:
    """Reúne as fontes que a pessoa pode ler, no espaço e no escopo da conversa."""
    scope = scope or {}
    space = f"org_id=eq.{org_id}" if org_id else "org_id=is.null"
    meetings: list[dict]
    actions: list[dict] = []
    if scope.get("action_id"):
        actions = repository.action_in_scope(user, space, scope["action_id"])
        ids = ",".join(sorted({a["meeting_id"] for a in actions}))
        meetings = repository.meetings_by_ids(user, ids) if ids else []
    elif scope.get("meeting_id"):
        meetings = repository.meeting_in_scope(user, space, scope["meeting_id"])
    elif scope.get("client_id"):
        meetings = repository.client_meetings(user, space, scope["client_id"], engine.CANDIDATE_MEETINGS)
    else:
        meetings = repository.recent_meetings(user, space, engine.CANDIDATE_MEETINGS)
    meetings = sec.redact_meetings(meetings, user)  # sem finance.read, sem valores financeiros de terceiros
    chosen = engine.rank_meetings(question, meetings)
    ids = [m["id"] for m in chosen]
    transcripts: dict[str, str] = {}
    if ids:
        for row in repository.transcripts(user, ids):
            transcripts[row["id"]] = (row.get("transcript") or "")[:engine.MAX_TRANSCRIPT_CHARS]
    if not actions and not scope.get("meeting_id") and not scope.get("action_id"):
        wants_actions = any(w in verification.normalize(question) for w in engine.ACTION_WORDS)
        wanted = engine.tokens(question)
        pool = repository.action_pool(user, space)
        if scope.get("client_id"):
            pool = [a for a in pool if (a.get("meetings") or {}).get("client_id") == scope["client_id"]]
        ranked = sorted(pool, key=lambda a: (len(wanted & engine.tokens(a.get("text") or "")) + (1 if a.get("status") in ("open", "in_progress") and wants_actions else 0)), reverse=True)
        actions = [a for a in ranked if (len(wanted & engine.tokens(a.get("text") or "")) > 0) or (wants_actions and a.get("status") in ("open", "in_progress"))][:engine.TOP_ACTIONS]
    elif scope.get("meeting_id") and ids:
        actions = repository.meeting_actions(user, ids[0])
    by_meeting: dict[str, list[dict]] = {}
    for a in actions:
        by_meeting.setdefault(a["meeting_id"], []).append(a)
    sources: list[engine.Source] = []
    for i, m in enumerate(chosen, 1):
        key = f"S{i}"
        tr = transcripts.get(m["id"], "")
        block, analysis = engine._meeting_block(key, m, by_meeting.get(m["id"], []), engine.best_lines(tr, question, fallback=bool(scope.get("meeting_id") or scope.get("action_id") or scope.get("client_id"))))
        sources.append(engine.Source(key, "meeting", m["id"], engine._clip(m.get("meeting_title") or m.get("client_name") or "Reunião", 120), block,
                                     transcript=tr, analysis=analysis, meta={"client_name": m.get("client_name"), "date": str(m.get("created_at") or "")[:10]}))
    in_meetings = {s.item_id for s in sources}
    n = len(sources)
    for a in actions:
        if scope.get("action_id") or a["meeting_id"] not in in_meetings:  # ação cuja reunião já está no contexto aparece dentro dela
            n += 1
            sources.append(engine._action_source(f"S{n}", a))
    return sources


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


def answer(user: sec.AuthUser, org_id: str | None, scope: dict | None, question: str, history: list[dict]) -> dict:
    """Responde a uma pergunta: recupera, redige, confere e monta. Retorna {content, sources, evidence_level, stats}."""
    sources = retrieve(user, org_id, scope, question)
    draft = engine.ask_model(engine.SYSTEM_PROMPT, engine.build_prompt(question, history, sources))
    kept, dropped = engine.verify_claims(draft.claims, sources)
    content, out_sources = engine.assemble(kept, draft.not_found, sources, dropped)
    return {"content": content, "sources": out_sources, "evidence_level": engine.evidence_level(kept, dropped),
            "stats": {"searched": len(sources), "kept": len(kept), "dropped": dropped}}


def _answer(user: sec.AuthUser, conversation: dict, question: str) -> tuple[dict | None, str | None]:
    """Gera e grava a resposta do AURA. Retorna (mensagem, None) ou (None, texto do erro). Nunca perde a pergunta."""
    cid = conversation["id"]
    try:
        past = repository.history(user, cid)
        history = past[:-1] if past and past[-1].get("role") == "user" else past  # a pergunta atual não é "conversa anterior"
        result = answer(user, conversation.get("org_id"), conversation.get("scope") or {}, question, history)
        message = append_assistant(user, cid, result["content"], result["sources"], result["evidence_level"])
    except engine.ChatUnavailable as exc:
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
