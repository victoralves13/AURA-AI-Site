"""AURA AI — conferência mecânica das evidências contra a transcrição.

A transcrição é a fonte da verdade. A IA propõe citações, horários e interlocutores; este módulo
confere cada um por código determinístico (sem custo de IA) e corrige o que a transcrição contradiz:

  * Citação:      "localizada" (trecho literal), "parcial" (parte dele, ou paráfrase muito próxima)
                  ou "nao_localizada" (não aparece na transcrição).
  * Horário:      vem da linha onde a citação foi encontrada; nunca do que a IA disse.
  * Interlocutor: idem. Sem rótulos na transcrição, nenhum interlocutor é aceito.
  * Valor:        confere se o número do valor financeiro aparece na citação.

Nada é apagado: itens não localizados continuam visíveis e marcados; só deixam de pesar na pontuação.
"""
from __future__ import annotations

import bisect
import re
import unicodedata
from dataclasses import dataclass

LOCALIZADA = "localizada"
PARCIAL = "parcial"
NAO_LOCALIZADA = "nao_localizada"
NAO_VERIFICADA = "nao_verificada"  # sem transcrição para conferir

NGRAM = 4                      # tamanho do trecho usado para medir paráfrase
PARTIAL_MIN_COVERAGE = 0.6     # fração mínima de 4-gramas presentes para aceitar como "parcial"
MIN_WORDS_FOR_FULL = 3         # citação com menos palavras nunca passa de "parcial"
MIN_FRAGMENT_WORDS = 3         # trechos separados por reticências com menos palavras são ignorados

_TS_LINE = re.compile(r"^\s*\[(\d{1,2}:\d{2}(?::\d{2})?)\]\s*(?:\[([^\]\n]{1,40})\]\s*)?(.*)$")
_NAME_PREFIX = re.compile(r"^\s*([^\W\d_][\w .'\-]{0,38}?):\s+(.+)$")
_ELLIPSIS = re.compile(r"\.{3}|…|\[\s*\.\.\.\s*\]|\s/\s")
_QUOTE_CHARS = "\"'“”‘’«»"


def normalize(text: str) -> str:
    """Minúsculas, sem acentos e sem pontuação; palavras separadas por um espaço."""
    decomposed = unicodedata.normalize("NFKD", text or "")
    plain = "".join(c for c in decomposed if not unicodedata.combining(c)).lower()
    return re.sub(r"[^a-z0-9]+", " ", plain).strip()


def to_seconds(ts: str | None) -> int | None:
    try:
        parts = [int(p) for p in str(ts).strip().split(":")]
    except (TypeError, ValueError):
        return None
    if len(parts) == 2:
        return parts[0] * 60 + parts[1]
    if len(parts) == 3:
        return parts[0] * 3600 + parts[1] * 60 + parts[2]
    return None


@dataclass
class Line:
    ts: str | None
    speaker: str | None
    body_norm: str
    full_norm: str


class Transcript:
    """Transcrição quebrada em linhas com horário e interlocutor (próprios ou herdados da anterior)."""

    def __init__(self, text: str):
        self.lines: list[Line] = []
        last_ts: str | None = None
        last_speaker: str | None = None
        for raw in (text or "").splitlines():
            if not raw.strip():
                continue
            ts = speaker = None
            body = raw.strip()
            m = _TS_LINE.match(raw)
            if m:
                ts, speaker, body = m.group(1), (m.group(2) or None), m.group(3)
            if speaker is None:
                n = _NAME_PREFIX.match(body)
                if n and len(n.group(1).split()) <= 4:
                    speaker, body = n.group(1).strip(), n.group(2)
            has_label = bool(ts or speaker)
            eff_ts = ts or (last_ts if not has_label else None)
            eff_speaker = speaker or (last_speaker if not has_label else None)
            if ts:
                last_ts = ts
            if speaker:
                last_speaker = speaker
            label = speaker or ""
            self.lines.append(Line(eff_ts, eff_speaker, normalize(body), normalize(label + " " + body)))
        self.has_timestamps = any(l.ts for l in self.lines)
        self.has_speakers = any(l.speaker for l in self.lines)
        self.timestamps = {to_seconds(l.ts) for l in self.lines if l.ts}
        self.speakers = {normalize(l.speaker) for l in self.lines if l.speaker}
        self._body, self._body_starts = self._join([l.body_norm for l in self.lines])
        self._full, self._full_starts = self._join([l.full_norm for l in self.lines])
        self._grams: set[tuple[str, ...]] | None = None
        self._vocab = set(self._full.split())

    def supports(self, value: str | None, min_ratio: float = 0.7) -> bool:
        """O valor (responsável, prazo) foi dito? Aceita se ao menos 70% das suas palavras estão na transcrição."""
        words = normalize(value or "").split()
        return bool(words) and sum(1 for w in words if w in self._vocab) / len(words) >= min_ratio

    @staticmethod
    def _join(parts: list[str]) -> tuple[str, list[int]]:
        starts, pos, out = [], 1, []
        for p in parts:
            starts.append(pos)
            out.append(p)
            pos += len(p) + 1
        return " " + " ".join(out) + " ", starts

    def _line_at(self, starts: list[int], pos: int) -> Line:
        return self.lines[max(0, bisect.bisect_right(starts, pos) - 1)]

    def _find(self, needle: str) -> Line | None:
        for corpus, starts in ((self._body, self._body_starts), (self._full, self._full_starts)):
            pos = corpus.find(" " + needle + " ")
            if pos >= 0:
                return self._line_at(starts, pos + 1)
        return None

    def _gram_set(self) -> set[tuple[str, ...]]:
        if self._grams is None:
            grams: set[tuple[str, ...]] = set()
            for corpus in (self._body, self._full):
                words = corpus.split()
                grams.update(tuple(words[i:i + NGRAM]) for i in range(max(0, len(words) - NGRAM + 1)))
            self._grams = grams
        return self._grams

    def _best_line(self, hit_grams: list[tuple[str, ...]]) -> Line | None:
        """Linha que contém mais trechos em comum com a citação (a primeira em caso de empate).
        Evita atribuir horário e interlocutor da linha errada quando um trecho curto se repete."""
        best, best_count = None, 0
        wanted = set(hit_grams)
        for line in self.lines:
            words = line.body_norm.split()
            count = len(wanted.intersection(tuple(words[i:i + NGRAM]) for i in range(max(0, len(words) - NGRAM + 1))))
            if count > best_count:
                best, best_count = line, count
        return best

    def locate(self, quote: str) -> tuple[str, float, Line | None]:
        """Retorna (situação, cobertura 0..1, linha onde foi encontrada)."""
        cleaned = (quote or "").strip().strip(_QUOTE_CHARS).strip()
        q = normalize(cleaned)
        words = q.split()
        if not words or not self.lines:
            return NAO_LOCALIZADA, 0.0, None

        line = self._find(q)
        if line is not None:
            return (LOCALIZADA if len(words) >= MIN_WORDS_FOR_FULL else PARCIAL), 1.0, line

        fragments = [normalize(f.strip(_QUOTE_CHARS)) for f in _ELLIPSIS.split(cleaned)]
        fragments = [f for f in fragments if len(f.split()) >= MIN_FRAGMENT_WORDS]
        if fragments and (len(fragments) > 1 or fragments[0] != q):
            hits = [(f, self._find(f)) for f in fragments]
            found = [(f, ln) for f, ln in hits if ln is not None]
            if len(found) == len(fragments):
                return LOCALIZADA, 1.0, found[0][1]
            if found:
                covered = sum(len(f.split()) for f, _ in found) / sum(len(f.split()) for f in fragments)
                return PARCIAL, round(covered, 2), found[0][1]

        if len(words) >= NGRAM:
            grams = [tuple(words[i:i + NGRAM]) for i in range(len(words) - NGRAM + 1)]
            known = self._gram_set()
            hit = [g for g in grams if g in known]
            coverage = len(hit) / len(grams)
            if coverage >= PARTIAL_MIN_COVERAGE:
                return PARCIAL, round(coverage, 2), self._best_line(hit) or self._find(" ".join(hit[0]))
            return NAO_LOCALIZADA, round(coverage, 2), None
        return NAO_LOCALIZADA, 0.0, None


def annotate_item(item: dict, transcript: Transcript | None) -> dict:
    """Confere um item que tenha `evidence`; devolve cópia com evidence_check, evidence_coverage,
    timestamp e speaker finais e a lista `corrections` do que foi corrigido pela transcrição."""
    out = dict(item)
    evidence = out.get("evidence")
    if transcript is None or not evidence:
        out["evidence_check"] = NAO_VERIFICADA
        out.setdefault("corrections", [])
        return out

    status, coverage, line = transcript.locate(str(evidence))
    corrections: list[str] = []
    claimed_ts, claimed_speaker = out.get("timestamp"), out.get("speaker")

    if line is not None and line.ts:
        if claimed_ts is None:
            corrections.append("timestamp_derivado")
        elif to_seconds(claimed_ts) != to_seconds(line.ts):
            corrections.append("timestamp_corrigido")
        out["timestamp"] = line.ts
    else:
        known = claimed_ts is not None and to_seconds(claimed_ts) in transcript.timestamps and line is None
        if claimed_ts is not None and not known:
            corrections.append("timestamp_removido")
            out["timestamp"] = None

    if line is not None and line.speaker:
        if claimed_speaker is None:
            corrections.append("speaker_derivado")
        elif normalize(claimed_speaker) != normalize(line.speaker):
            corrections.append("speaker_corrigido")
        out["speaker"] = line.speaker
    else:
        known = claimed_speaker is not None and normalize(claimed_speaker) in transcript.speakers and line is None
        if claimed_speaker is not None and not known:
            corrections.append("speaker_removido")
            out["speaker"] = None

    # Responsável e prazo só valem quando foram ditos; senão ficam vazios (nunca inventados).
    for key in ("owner", "deadline"):
        if out.get(key) and not transcript.supports(out[key]):
            out[key] = None
            corrections.append(f"{key}_removido")

    out.setdefault("timestamp", None)
    out.setdefault("speaker", None)
    out["evidence_check"] = status
    out["evidence_coverage"] = coverage
    out["corrections"] = corrections
    return out


# ---------------------------------------------------------------------------
# Valores financeiros
# ---------------------------------------------------------------------------
_NUM = re.compile(r"(?<![\w.,])(\d{1,3}(?:\.\d{3})+(?:,\d+)?|\d+(?:[.,]\d+)?)\s*(bilh(?:ão|ões|ao|oes)|bi\b|milh(?:ão|ões|ao|oes)|mi\b|mil\b|k\b)?", re.I)
_THOUSANDS = re.compile(r"\d{1,3}(?:\.\d{3})+(?:,\d+)?")


def _multiplier(unit: str) -> float:
    u = unit.lower()
    if u.startswith("bilh") or u == "bi":
        return 1e9
    if u.startswith("milh") or u == "mi":
        return 1e6
    if u in ("mil", "k"):
        return 1e3
    return 1.0


def number_candidates(text: str) -> set[float]:
    """Valores numéricos que aparecem no texto (formato brasileiro: 1.500,50; 2 milhões; 120 mil)."""
    values: set[float] = set()
    for m in _NUM.finditer(text or ""):
        raw, unit = m.group(1), m.group(2) or ""
        if _THOUSANDS.fullmatch(raw):
            number = float(raw.replace(".", "").replace(",", "."))
        else:
            number = float(raw.replace(",", "."))
        values.add(number)
        if unit:
            values.add(number * _multiplier(unit))
    return values


def amount_check(amount: float, evidence: str) -> str:
    """'confere' | 'nao_confere' | 'nao_verificavel' (número escrito por extenso, por exemplo)."""
    candidates = number_candidates(evidence)
    if not candidates:
        return "nao_verificavel"
    return "confere" if any(abs(c - amount) <= max(0.01, abs(amount) * 0.001) for c in candidates) else "nao_confere"
