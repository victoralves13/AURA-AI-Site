from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Literal

from openai import OpenAI
from pydantic import BaseModel


EvidenceStrength = Literal["alta", "média", "baixa"]


class EvidenceItem(BaseModel):
    description: str
    evidence: str
    evidence_strength: EvidenceStrength
    timestamp: str | None = None


class NextAction(BaseModel):
    action: str
    evidence: str
    evidence_strength: EvidenceStrength


class AURAAnalysis(BaseModel):
    summary: str
    main_topics: list[str]
    decisions: list[str]
    pending_actions: list[str]
    risks: list[EvidenceItem]
    opportunities: list[EvidenceItem]
    objections: list[str]
    important_signals: list[EvidenceItem]
    next_actions: list[NextAction]
    participants: list[str]
    intelligence_type: str
    sentiment: str


ANALYSIS_MODEL = os.getenv("AURA_OPENAI_ANALYSIS_MODEL", "gpt-6-sol")
TRANSCRIPTION_MODEL = os.getenv("AURA_OPENAI_TRANSCRIPTION_MODEL", "gpt-transcribe")
MAX_OPENAI_AUDIO_BYTES = 25 * 1024 * 1024


SYSTEM_PROMPT = """
Você é o motor de inteligência do AURA AI.

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
- Quando a transcrição trouxer timestamps no formato [MM:SS] ou [HH:MM:SS], associe o timestamp mais próximo da evidência e retorne-o no campo timestamp.
- Nunca invente timestamp. Se não houver timestamp disponível para aquele trecho, deixe timestamp como null.
- A força da evidência deve ser alta, média ou baixa.
- Preserve nomes e informações relevantes para executar ações.
- Não faça diagnóstico médico nem aconselhamento médico.
- Uma inferência deve ser tratada como inferência, nunca como fato.
- Identifique o tipo dominante de inteligência da conversa: comercial, operacional,
  gestão, risco, compliance/auditoria, estratégico, relacionamento ou outro.
- O sentimento deve refletir a conversa como um todo, sem usar uma única frase isolada.
- Responda exclusivamente no formato estruturado solicitado.
"""


def _client() -> OpenAI:
    if not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError("OPENAI_API_KEY não configurada no ambiente.")
    return OpenAI()


def analyze_transcript(transcript: str, context: str = "Outro") -> AURAAnalysis:
    text = (transcript or "").strip()
    if len(text) < 4:
        raise ValueError("Transcrição vazia.")

    response = _client().responses.parse(
        model=ANALYSIS_MODEL,
        input=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"CONTEXTO DA ANÁLISE: {context or 'Outro'}\n\nTRANSCRIÇÃO:\n{text}"},
        ],
        text_format=AURAAnalysis,
    )

    parsed = response.output_parsed
    if parsed is None:
        raise RuntimeError("A OpenAI não retornou uma análise estruturada.")
    return parsed


def _transcribe_one(path: str, prompt: str = "", offset_seconds: float = 0) -> tuple[str, list[dict]]:
    with open(path, "rb") as audio:
        result = _client().audio.transcriptions.create(
            model=TRANSCRIPTION_MODEL,
            file=audio,
            languages=["pt"],
            prompt=prompt or (
                "Reunião de trabalho em português do Brasil. "
                "Preserve nomes, siglas, sistemas, números, decisões e termos técnicos."
            ),
            response_format="verbose_json",
            timestamp_granularities=["segment"],
        )
    segments = []
    for segment in (getattr(result, "segments", None) or []):
        start = float(getattr(segment, "start", 0) or 0) + offset_seconds
        end = float(getattr(segment, "end", start) or start) + offset_seconds
        text = (getattr(segment, "text", "") or "").strip()
        if text:
            segments.append({"start": round(start, 2), "end": round(end, 2), "text": text})
    return (result.text or "").strip(), segments


def transcribe_audio(path: str) -> tuple[str, dict]:
    source = Path(path)
    if source.stat().st_size <= MAX_OPENAI_AUDIO_BYTES:
        text, segments = _transcribe_one(str(source))
        return text, {"chunks": 1, "model": TRANSCRIPTION_MODEL, "segments": segments}

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
        audio = AudioSegment.from_file(source)
        audio = audio.set_channels(1).set_frame_rate(16000)
        audio.export(normalized, format="mp3", bitrate="64k")

        if normalized.stat().st_size <= MAX_OPENAI_AUDIO_BYTES:
            text, segments = _transcribe_one(str(normalized))
            return text, {"chunks": 1, "model": TRANSCRIPTION_MODEL, "normalized": True, "segments": segments}

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
            "overlap_seconds": 2,
            "segments": all_segments,
        }


def evidence_score(items: list[EvidenceItem] | list[NextAction]) -> int:
    weights = {"alta": 34, "média": 22, "baixa": 10}
    return min(95, sum(weights.get(item.evidence_strength, 0) for item in items))


def build_product_fields(analysis: AURAAnalysis) -> dict:
    risk_score = evidence_score(analysis.risks)
    opportunity_score = evidence_score(analysis.opportunities)

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

    next_move = (
        analysis.next_actions[0].action
        if analysis.next_actions
        else "Definir o próximo movimento a partir das decisões e pendências identificadas."
    )

    why = analysis.summary
    if analysis.risks:
        why = analysis.risks[0].description
    elif analysis.opportunities:
        why = analysis.opportunities[0].description

    return {
        "summary": analysis.summary,
        "opportunity": opportunity,
        "opportunity_score": opportunity_score,
        "opportunity_signals": [x.description for x in analysis.opportunities[:4]],
        "risk": risk,
        "risk_score": risk_score,
        "risk_signals": [x.description for x in analysis.risks[:4]],
        "priority": priority,
        "impact": impact,
        "why_it_matters": why,
        "intent": analysis.intelligence_type,
        "objections": analysis.objections[:5],
        "products": [],
        "evidence": [
            {
                "description": x.description,
                "evidence": x.evidence,
                "evidence_strength": x.evidence_strength,
                "timestamp": x.timestamp,
            }
            for x in (analysis.risks + analysis.opportunities + analysis.important_signals)
            if x.evidence
        ][:10],
        "next_move": next_move,
        "owner": "Não identificado",
        "deadline": "Não identificado",
        "intelligence_type": analysis.intelligence_type,
        "decisions": analysis.decisions,
        "pending_actions": analysis.pending_actions,
        "important_signals": [x.description for x in analysis.important_signals],
        "insights": [
            {
                "description": x.description,
                "evidence": x.evidence,
                "evidence_strength": x.evidence_strength,
                "timestamp": x.timestamp,
                "type": "risco" if x in analysis.risks else "oportunidade" if x in analysis.opportunities else "sinal",
            }
            for x in (analysis.risks + analysis.opportunities + analysis.important_signals)
            if x.evidence
        ],
        "participants": analysis.participants,
        "sentiment": analysis.sentiment,
        "analysis_model": ANALYSIS_MODEL,
        "transcription_model": TRANSCRIPTION_MODEL,
    }
