from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Literal

from openai import OpenAI, RateLimitError
from pydantic import BaseModel, ValidationError

import verification


EvidenceStrength = Literal["alta", "média", "baixa"]
# "dito": afirmado literalmente na conversa. "inferido": conclusão da IA a partir de trechos citados.
Basis = Literal["dito", "inferido"]
Confidence = Literal["alta", "média", "baixa"]


class EvidenceItem(BaseModel):
    description: str
    evidence: str
    evidence_strength: EvidenceStrength
    timestamp: str | None = None
    basis: Basis = "dito"
    inference_rationale: str | None = None
    speaker: str | None = None


class NextAction(BaseModel):
    action: str
    evidence: str
    evidence_strength: EvidenceStrength
    timestamp: str | None = None
    speaker: str | None = None
    owner: str | None = None
    deadline: str | None = None


class InsightItem(BaseModel):
    description: str
    evidence: str
    evidence_strength: EvidenceStrength
    timestamp: str | None = None
    category: Literal["risco", "oportunidade", "sinal", "relacionamento", "comercial", "operacional", "financeiro", "decisão", "objeção", "ação"]
    impact_score: int = 50
    basis: Basis = "dito"
    inference_rationale: str | None = None
    speaker: str | None = None
    confidence: Confidence = "média"
    confidence_reason: str | None = None


class DecisionItem(BaseModel):
    description: str
    evidence: str
    timestamp: str | None = None
    speaker: str | None = None
    basis: Basis = "dito"
    inference_rationale: str | None = None


class ActionItem(BaseModel):
    description: str
    evidence: str
    timestamp: str | None = None
    speaker: str | None = None
    owner: str | None = None
    deadline: str | None = None
    basis: Basis = "dito"
    inference_rationale: str | None = None


class FinancialItem(BaseModel):
    amount: float
    currency: str = "BRL"
    financial_type: Literal["receita","lucro","custo","economia","investimento","contrato","oportunidade","perda","meta","orçamento","outro"]
    nature: Literal["realizado","potencial","estimado","risco","mencionado"]
    description: str
    evidence: str
    evidence_strength: EvidenceStrength
    timestamp: str | None = None
    period: str | None = None


class AURAAnalysis(BaseModel):
    """Contrato v2: decisões e ações com evidência; achados marcados como dito/inferido."""
    client_name: str | None = None
    summary: str
    main_topics: list[str]
    decisions: list[DecisionItem]
    pending_actions: list[ActionItem]
    risks: list[EvidenceItem]
    opportunities: list[EvidenceItem]
    objections: list[str]
    important_signals: list[EvidenceItem]
    insights: list[InsightItem]
    financial_data: list[FinancialItem]
    next_actions: list[NextAction]
    participants: list[str]
    intelligence_type: str
    sentiment: str


class AURAAnalysisV1(BaseModel):
    """Contrato v1 (reserva): decisões e pendências como texto simples."""
    client_name: str | None = None
    summary: str
    main_topics: list[str]
    decisions: list[str]
    pending_actions: list[str]
    risks: list[EvidenceItem]
    opportunities: list[EvidenceItem]
    objections: list[str]
    important_signals: list[EvidenceItem]
    insights: list[InsightItem]
    financial_data: list[FinancialItem]
    next_actions: list[NextAction]
    participants: list[str]
    intelligence_type: str
    sentiment: str


def analysis_version(analysis) -> int:
    return 1 if isinstance(analysis, AURAAnalysisV1) else 2


ANALYSIS_MODEL = os.getenv("AURA_OPENAI_ANALYSIS_MODEL", "gpt-6-sol")
TRANSCRIPTION_MODEL = os.getenv("AURA_OPENAI_TRANSCRIPTION_MODEL", "gpt-4o-transcribe-diarize")
MAX_OPENAI_AUDIO_BYTES = 25 * 1024 * 1024


SYSTEM_PROMPT_V1 = """
Você é o motor de inteligência do AURA AI.

Se a conversa mencionar explicitamente o nome de uma empresa, conta ou cliente, retorne esse nome em client_name. Não invente nomes; se não houver identificação explícita, use null.

O contexto selecionado pelo usuário é fornecido na mensagem de análise. Use-o como lente prioritária, sem inventar fatos.

Sua função é transformar uma reunião real em inteligência estruturada e acionável,
preservando fielmente o que foi dito.

REGRAS:
- Não invente informações.
- Não complete lacunas com conhecimento externo.
- Diferencie fatos, decisões, hipóteses, sugestões, opiniões e inferências.
- Uma possibilidade discutida NÃO é uma decisão.
- Só classifique algo como decisão quando houver evidência de decisão ou confirmação.
- Só classifique algo como próxima ação quando houver uma ação definida ou claramente atribuída.
- Não transforme qualquer problema em risco automaticamente.
- Não transforme qualquer ideia em oportunidade automaticamente.
- Se não houver evidência suficiente, deixe a lista vazia.
- Para riscos, oportunidades, sinais importantes e próximas ações, sempre inclua evidência textual curta.
- Primeiro percorra mentalmente a transcrição inteira e construa uma lista abrangente de insights distintos. Depois selecione/organize os itens em riscos, oportunidades, sinais, decisões e ações quando aplicável.
- O campo insights é a memória analítica completa da reunião. Registre nele todos os achados distintos e sustentados pela conversa, sem limite artificial de quantidade. Uma reunião rica pode gerar dezenas de itens; uma reunião objetiva pode gerar poucos.
- Não crie insights apenas para atingir uma quantidade. Qualidade e rastreabilidade vêm antes de volume.
- Evite condensar vários fatos diferentes em um único insight. Se houver mudanças, preocupações, oportunidades, objeções, decisões ou sinais comerciais distintos, preserve-os separadamente.
- Use as categorias de insights para permitir posterior filtragem e leitura executiva: risco, oportunidade, sinal, relacionamento, comercial, operacional, financeiro, decisão, objeção ou ação.
- Os campos risks, opportunities, important_signals, decisions e next_actions continuam existindo como visões estruturadas derivadas dos achados; não devem substituir nem limitar a lista completa de insights.
- Identifique TODOS os valores financeiros explicitamente mencionados na reunião quando houver contexto suficiente para entender o que o número representa.
- Para cada valor financeiro, registre o número em amount como valor absoluto (por exemplo, R$ 2 milhões = 2000000), a moeda, o financial_type, a natureza (realizado, potencial, estimado, risco ou apenas mencionado), uma descrição curta, a evidência textual e o timestamp mais próximo.
- Nunca transforme um contrato em lucro ou receita realizada sem que isso tenha sido dito. Um valor de oportunidade, contrato, investimento ou meta deve manter seu próprio tipo e natureza.
- Se um número aparecer sem contexto financeiro suficiente, não o registre como financial_data. Não invente cálculos, totais ou variações.
- Preserve períodos quando forem explicitamente mencionados (por exemplo, mensal, anual, próximo trimestre), sem inferir períodos ausentes.
- A lista completa deve refletir a reunião inteira, e não apenas os momentos mais dramáticos ou mais importantes.
- Quando a transcrição trouxer timestamps no formato [MM:SS] ou [HH:MM:SS], associe o timestamp mais próximo da evidência e retorne-o no campo timestamp.
- Nunca invente timestamp. Se não houver timestamp disponível para aquele trecho, deixe timestamp como null.
- A força da evidência deve ser alta, média ou baixa.
- Para cada insight, atribua impact_score de 0 a 100. Esse score mede o impacto empresarial daquele achado dentro da reunião: capacidade de mudar uma decisão, alterar uma oportunidade, elevar um risco, destravar uma ação ou mudar a relação com o cliente. Considere também urgência, especificidade e consequência explícita.
- Não use impact_score apenas como sinônimo de força da evidência: um fato muito bem evidenciado pode ter baixo impacto, e um sinal explícito com consequência grande pode ter alto impacto.
- Use a escala de forma discriminativa: 90–100 para momentos críticos/decisivos, 75–89 para achados muito relevantes, 55–74 para relevância intermediária e abaixo de 55 para sinais contextuais.
- Preserve nomes e informações relevantes para executar ações.
- Não faça diagnóstico médico nem aconselhamento médico.
- Uma inferência deve ser tratada como inferência, nunca como fato.
- Identifique o tipo dominante de inteligência da conversa: comercial, operacional,
  gestão, risco, compliance/auditoria, estratégico, relacionamento ou outro.
- O sentimento deve refletir a conversa como um todo, sem usar uma única frase isolada.
- Quando a transcrição de áudio trouxer marcações de locutor como [A], [B] ou [Participante A], preserve a atribuição ao avaliar evidências e preencha participants com os identificadores disponíveis, sem inventar nomes.
- Responda exclusivamente no formato estruturado solicitado.
"""


SYSTEM_PROMPT_V2_ADDENDUM = """

REGRAS ADICIONAIS (contrato v2 — dito x inferido, citações e interlocutores):
- Todo achado (risco, oportunidade, sinal, insight, decisão, ação) tem "basis":
  - "dito": o conteúdo foi afirmado explicitamente na conversa. "evidence" DEVE ser um trecho LITERAL copiado da transcrição,
    sem parafrasear, sem corrigir e sem juntar falas de momentos diferentes. Use "…" apenas para omitir partes do mesmo trecho.
  - "inferido": conclusão SUA a partir de um ou mais trechos. "evidence" continua sendo o(s) trecho(s) literal(is) que a sustentam
    e "inference_rationale" é OBRIGATÓRIA (1 a 2 frases explicando o raciocínio, sem fatos novos). Nunca apresente inferência como fato.
- Se você não consegue citar um trecho literal, NÃO registre o achado.
- "speaker": identificador do interlocutor exatamente como aparece na transcrição ([A], Participante A, um nome escrito ali) ou null.
  Não invente nomes nem atribua falas a quem não as disse.
- Em insights, informe "confidence" (alta, média, baixa) e "confidence_reason" (uma frase curta). Confiança baixa é aceitável; omitir a incerteza não é.
- decisions: cada decisão é um objeto com description, evidence (trecho literal), timestamp, speaker e basis. Só é decisão com confirmação explícita.
- pending_actions: cada ação é um objeto. "owner" e "deadline" só quando ditos de forma explícita; caso contrário, null.
- next_actions: "owner" e "deadline" seguem a mesma regra (null quando não ditos).
"""
SYSTEM_PROMPT = SYSTEM_PROMPT_V1 + SYSTEM_PROMPT_V2_ADDENDUM


def _client() -> OpenAI:
    if not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError("OPENAI_API_KEY não configurada no ambiente.")
    return OpenAI(max_retries=0)


def _parse(schema, prompt: str, context: str, text: str):
    try:
        response = _client().responses.parse(
            model=ANALYSIS_MODEL,
            input=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": f"CONTEXTO DA ANÁLISE: {context or 'Outro'}\n\nTRANSCRIÇÃO:\n{text}"},
            ],
            text_format=schema,
        )
    except RateLimitError as exc:
        message = str(exc)
        if "credit_balance_exhausted" in message or "no credits remaining" in message.lower():
            raise RuntimeError(
                "Créditos da OpenAI API esgotados. Adicione créditos ao saldo da API "
                "para o AURA continuar processando análises."
            ) from exc
        raise
    parsed = response.output_parsed
    if parsed is None:
        raise RuntimeError("A OpenAI não retornou uma análise estruturada.")
    return parsed


def analyze_transcript(transcript: str, context: str = "Outro"):
    """Analisa com o contrato v2. Se a resposta estruturada não validar, tenta UMA vez o contrato v1.
    Erros de API (limite, créditos, rede) nunca disparam a nova tentativa."""
    text = (transcript or "").strip()
    if len(text) < 4:
        raise ValueError("Transcrição vazia.")
    try:
        return _parse(AURAAnalysis, SYSTEM_PROMPT, context, text)
    except (ValidationError, RuntimeError) as exc:
        if isinstance(exc, RuntimeError) and "Créditos" in str(exc):
            raise
        if isinstance(exc, RuntimeError) and "não retornou uma análise" not in str(exc):
            raise
        return _parse(AURAAnalysisV1, SYSTEM_PROMPT_V1, context, text)



def _transcribe_one(path: str, prompt: str = "", offset_seconds: float = 0) -> tuple[str, list[dict]]:
    with open(path, "rb") as audio:
        if TRANSCRIPTION_MODEL == "gpt-4o-transcribe-diarize":
            # Diarized JSON already carries start/end timestamps and speaker
            # labels. Do not send prompt/timestamp_granularities here: the
            # diarization endpoint has a different request contract.
            result = _client().audio.transcriptions.create(
                model=TRANSCRIPTION_MODEL,
                file=audio,
                language="pt",
                response_format="diarized_json",
                chunking_strategy="auto",
            )
        elif TRANSCRIPTION_MODEL == "gpt-transcribe":
            # gpt-transcribe is the general transcription path. It does not
            # provide segment timestamps, so keep this fallback intentionally
            # simple instead of sending unsupported timestamp parameters.
            result = _client().audio.transcriptions.create(
                model=TRANSCRIPTION_MODEL,
                file=audio,
                languages=["pt"],
                prompt=prompt or (
                    "Reunião de trabalho em português do Brasil. "
                    "Preserve nomes, siglas, sistemas, números, decisões e termos técnicos."
                ),
            )
        else:
            raise RuntimeError(
                f"Modelo de transcrição não suportado pelo AURA: {TRANSCRIPTION_MODEL}. "
                "Use gpt-4o-transcribe-diarize para transcrição com locutores e timestamps."
            )

    segments = []
    for segment in (getattr(result, "segments", None) or []):
        start = float(getattr(segment, "start", 0) or 0) + offset_seconds
        end = float(getattr(segment, "end", start) or start) + offset_seconds
        text = (getattr(segment, "text", "") or "").strip()
        speaker = getattr(segment, "speaker", None)
        if isinstance(segment, dict):
            speaker = segment.get("speaker")
        item = {"start": round(start, 2), "end": round(end, 2), "text": text}
        if speaker:
            item["speaker"] = str(speaker)
        if text:
            segments.append(item)

    return (getattr(result, "text", "") or "").strip(), segments


def transcribe_audio(path: str) -> tuple[str, dict]:
    source = Path(path)
    if source.stat().st_size <= MAX_OPENAI_AUDIO_BYTES:
        text, segments = _transcribe_one(str(source))
        return text, {"chunks": 1, "model": TRANSCRIPTION_MODEL, "speaker_labels": TRANSCRIPTION_MODEL == "gpt-4o-transcribe-diarize", "segments": segments}

    # OpenAI file transcription accepts up to 25 MB per request.
    # Normalize/compress locally first, then split only when the compressed
    # recording still exceeds that limit.
    try:
        from pydub import AudioSegment
        import imageio_ffmpeg
    except Exception as exc:
        raise RuntimeError(
            "O AURA precisa de pydub/imageio-ffmpeg para processar áudios grandes."
        ) from exc

    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    AudioSegment.converter = ffmpeg

    with tempfile.TemporaryDirectory() as tmp:
        normalized = Path(tmp) / "normalized.mp3"
        # Decode through the configured ffmpeg binary; no standalone ffprobe is required.
        audio = AudioSegment.from_file(str(source), codec="pcm_s16le")
        audio = audio.set_channels(1).set_frame_rate(16000)
        audio.export(normalized, format="mp3", bitrate="64k")

        if normalized.stat().st_size <= MAX_OPENAI_AUDIO_BYTES:
            text, segments = _transcribe_one(str(normalized))
            return text, {"chunks": 1, "model": TRANSCRIPTION_MODEL, "normalized": True, "speaker_labels": TRANSCRIPTION_MODEL == "gpt-4o-transcribe-diarize", "segments": segments}

        chunks: list[str] = []
        all_segments: list[dict] = []
        chunk_ms = 8 * 60 * 1000
        overlap_ms = 2000

        for start in range(0, len(audio), chunk_ms):
            end = min(len(audio), start + chunk_ms)
            chunk_start = max(0, start - overlap_ms if start else 0)
            chunk = audio[chunk_start:end]
            chunk_path = Path(tmp) / f"chunk-{len(chunks)+1}.mp3"
            chunk.export(chunk_path, format="mp3", bitrate="64k")

            if chunk_path.stat().st_size > MAX_OPENAI_AUDIO_BYTES:
                raise RuntimeError("Não foi possível reduzir um trecho de áudio abaixo de 25 MB.")

            prompt = (
                "Reunião de trabalho em português do Brasil. "
                "Este é um trecho de uma reunião maior. "
                "Preserve nomes, siglas, sistemas, números, decisões e termos técnicos."
            )
            chunk_text, chunk_segments = _transcribe_one(str(chunk_path), prompt, offset_seconds=chunk_start / 1000)
            chunks.append(chunk_text)
            all_segments.extend(chunk_segments)

        text = " ".join(part for part in chunks if part).strip()
        return text, {
            "chunks": len(chunks),
            "model": TRANSCRIPTION_MODEL,
            "normalized": True,
            "speaker_labels": TRANSCRIPTION_MODEL == "gpt-4o-transcribe-diarize",
            "speaker_scope": "per_chunk" if TRANSCRIPTION_MODEL == "gpt-4o-transcribe-diarize" else None,
            "overlap_seconds": 2,
            "segments": all_segments,
        }


# ---------------------------------------------------------------------------
# Pontuação e campos de produto (com evidências conferidas contra a transcrição)
# ---------------------------------------------------------------------------
STRENGTH_WEIGHT = {"alta": 34, "média": 22, "baixa": 10}
# Evidência não localizada não pesa; parcial vale metade; inferência vale metade de um fato dito.
CHECK_FACTOR = {
    verification.LOCALIZADA: 1.0,
    verification.PARCIAL: 0.5,
    verification.NAO_LOCALIZADA: 0.0,
    verification.NAO_VERIFICADA: 1.0,  # sem transcrição para conferir (comportamento anterior)
}
BASIS_FACTOR = {"dito": 1.0, "inferido": 0.5}


def evidence_score(items: list[dict]) -> int:
    total = 0.0
    for item in items:
        total += (
            STRENGTH_WEIGHT.get(item.get("evidence_strength"), 0)
            * CHECK_FACTOR.get(item.get("evidence_check") or verification.NAO_VERIFICADA, 1.0)
            * BASIS_FACTOR.get(item.get("basis") or "dito", 1.0)
        )
    return min(95, round(total))


def _kept(items: list[dict]) -> list[dict]:
    """Itens cuja evidência existe na transcrição (os demais continuam salvos, mas marcados)."""
    return [x for x in items if x.get("evidence_check") != verification.NAO_LOCALIZADA]


def _plain_item(text: str) -> dict:
    return {"description": text, "evidence": None, "evidence_check": verification.NAO_VERIFICADA,
            "basis": None, "timestamp": None, "speaker": None, "corrections": []}


def _clear_v2_fields(items: list[dict]) -> list[dict]:
    """Contrato v1 não pedia dito/inferido: não se mostra um valor padrão como se tivesse sido classificado."""
    for item in items:
        for key in ("basis", "inference_rationale", "confidence", "confidence_reason"):
            if key in item:
                item[key] = None
    return items


def _evidence_summary(groups: list[list[dict]]) -> dict:
    items = [i for group in groups for i in group if i.get("evidence")]
    count = lambda check: sum(1 for i in items if i.get("evidence_check") == check)
    return {
        "total": len(items),
        "localizada": count(verification.LOCALIZADA),
        "parcial": count(verification.PARCIAL),
        "nao_localizada": count(verification.NAO_LOCALIZADA),
        "nao_verificada": count(verification.NAO_VERIFICADA),
        "inferido": sum(1 for i in items if i.get("basis") == "inferido"),
        "corrigidos": sum(1 for i in items if i.get("corrections")),
    }


def build_product_fields(analysis, transcript: str | None = None) -> dict:
    v1 = isinstance(analysis, AURAAnalysisV1)
    data = analysis.model_dump()
    tr = verification.Transcript(transcript) if transcript else None
    ann = lambda items: [verification.annotate_item(i, tr) for i in items]
    maybe_v1 = lambda items: _clear_v2_fields(items) if v1 else items

    risks = maybe_v1(ann(data["risks"]))
    opportunities = maybe_v1(ann(data["opportunities"]))
    signals = maybe_v1(ann(data["important_signals"]))
    insights = maybe_v1(ann(data["insights"]))
    next_actions = ann(data["next_actions"])
    if v1:
        decisions = [_plain_item(text) for text in data["decisions"]]
        actions = [_plain_item(text) for text in data["pending_actions"]]
    else:
        decisions = ann(data["decisions"])
        actions = ann(data["pending_actions"])
    financial = []
    for item in ann(data["financial_data"]):
        item["amount_check"] = verification.amount_check(float(item["amount"]), item["evidence"]) if item.get("evidence") else "nao_verificavel"
        financial.append(item)

    risk_score = evidence_score(risks)
    opportunity_score = evidence_score(opportunities)

    if risk_score >= 60:
        risk = "Alto"
    elif risk_score >= 25:
        risk = "Médio"
    else:
        risk = "Baixo"

    opportunity = "Detectada" if opportunity_score >= 25 else "Não identificada"

    if risk == "Alto":
        priority = "Crítica"
    elif opportunity == "Detectada" and opportunity_score >= 60:
        priority = "Alta"
    elif risk == "Médio" or opportunity == "Detectada":
        priority = "Média"
    else:
        priority = "Baixa"

    if risk == "Alto":
        impact = "Retenção / risco"
    elif opportunity == "Detectada":
        impact = "Oportunidade"
    else:
        impact = "Qualificação"

    first_action = next(iter(_kept(next_actions)), None)
    next_move = (
        first_action["action"]
        if first_action
        else "Definir o próximo movimento a partir das decisões e pendências identificadas."
    )

    kept_risks, kept_opps = _kept(risks), _kept(opportunities)
    why = data["summary"]
    if kept_risks:
        why = kept_risks[0]["description"]
    elif kept_opps:
        why = kept_opps[0]["description"]

    return {
        "client_name": data["client_name"],
        "summary": data["summary"],
        "topics": data["main_topics"][:10],
        "opportunity": opportunity,
        "opportunity_score": opportunity_score,
        "opportunity_signals": [x["description"] for x in kept_opps[:4]],
        "risk": risk,
        "risk_score": risk_score,
        "risk_signals": [x["description"] for x in kept_risks[:4]],
        "priority": priority,
        "impact": impact,
        "why_it_matters": why,
        "intent": data["intelligence_type"],
        "objections": data["objections"][:5],
        "products": [],
        "evidence": [
            {
                "description": x["description"],
                "evidence": x["evidence"],
                "evidence_strength": x["evidence_strength"],
                "timestamp": x.get("timestamp"),
                "basis": x.get("basis"),
                "speaker": x.get("speaker"),
                "evidence_check": x.get("evidence_check"),
            }
            for x in (risks + opportunities + signals)
            if x.get("evidence")
        ][:10],
        "next_move": next_move,
        # Só quando ditos na conversa; senão o texto padrão histórico das colunas legadas.
        "owner": (first_action or {}).get("owner") or "Não identificado",
        "deadline": (first_action or {}).get("deadline") or "Não identificado",
        "intelligence_type": data["intelligence_type"],
        # Listas de texto (compatibilidade com a interface atual): só o que tem evidência na transcrição.
        "decisions": [x["description"] for x in _kept(decisions)],
        "pending_actions": [x["description"] for x in _kept(actions)],
        "decisions_detail": decisions,
        "actions_detail": actions,
        "important_signals": [x["description"] for x in _kept(signals)],
        "insights": [
            {
                "description": x["description"],
                "evidence": x["evidence"],
                "evidence_strength": x["evidence_strength"],
                "timestamp": x.get("timestamp"),
                "type": x["category"],
                "impact_score": max(0, min(100, int(x["impact_score"]))),
                "basis": x.get("basis"),
                "inference_rationale": x.get("inference_rationale"),
                "speaker": x.get("speaker"),
                "confidence": x.get("confidence"),
                "confidence_reason": x.get("confidence_reason"),
                "evidence_check": x.get("evidence_check"),
                "evidence_coverage": x.get("evidence_coverage"),
                "corrections": x.get("corrections", []),
            }
            for x in insights
            if x.get("evidence")
        ],
        "financial_data": [
            {
                "amount": float(x["amount"]),
                "currency": x.get("currency") or "BRL",
                "financial_type": x["financial_type"],
                "nature": x["nature"],
                "description": x["description"],
                "evidence": x["evidence"],
                "evidence_strength": x["evidence_strength"],
                "timestamp": x.get("timestamp"),
                "period": x.get("period"),
                "evidence_check": x.get("evidence_check"),
                "amount_check": x.get("amount_check"),
            }
            for x in financial
            if x.get("evidence") and x["amount"] >= 0
        ],
        "participants": data["participants"],
        "sentiment": data["sentiment"],
        "analysis_model": ANALYSIS_MODEL,
        "transcription_model": TRANSCRIPTION_MODEL,
        "analysis_version": 1 if v1 else 2,
        "evidence_summary": _evidence_summary([risks, opportunities, signals, insights, decisions, actions, financial, next_actions]),
    }
