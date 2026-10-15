"""Clientes — correspondência de nomes (regra pura, sem banco e sem HTTP).

Regra de vínculo (determinística, sem IA, SEMPRE dentro do mesmo espaço: organização ou conta pessoal):
  * Nome digitado pela pessoa:  igual a um cliente/apelido -> vincula (confirmado);
                                parecido -> sugere e espera confirmação; sem correspondência -> cria o cliente.
  * Nome extraído pela IA:      igual a um cliente/apelido -> vincula (automático);
                                parecido ou ambíguo -> sugere; sem correspondência -> propõe criar e espera confirmação.
  * Sem nome (ou "Cliente não identificado"), reunião demo ou modo sem login -> sem vínculo.
"""
from __future__ import annotations

from difflib import SequenceMatcher

from aura.core import verification

PLACEHOLDERS = {"cliente nao identificado", "nao identificado", "sem cliente", "desconhecido", "nao informado", "n a", "na"}
LEGAL_SUFFIXES = {"ltda", "eireli", "epp", "me", "sa"}
GENERIC = {"grupo", "empresa", "companhia", "cia", "cliente", "holding", "corporacao", "organizacao", "de", "do", "da", "dos", "das", "e"}
SIMILAR_MIN = 0.5      # similaridade mínima de palavras relevantes para sugerir
RATIO_MIN = 0.88       # similaridade mínima de texto para sugerir (erros de digitação)
MAX_CANDIDATES = 3


def normalize_name(name: str) -> str:
    """Minúsculas, sem acento nem pontuação e sem sufixo societário (Ltda, S.A., ME…)."""
    tokens = verification.normalize(name).split()
    while tokens and tokens[-1] in LEGAL_SUFFIXES:
        tokens.pop()
    while len(tokens) >= 2 and tokens[-2:] == ["s", "a"]:
        tokens = tokens[:-2]
    return " ".join(tokens) or verification.normalize(name)


def is_placeholder(name: str | None) -> bool:
    n = verification.normalize(name or "")
    return not n or n in PLACEHOLDERS


def _meaningful(norm: str) -> set[str]:
    return {t for t in norm.split() if t not in GENERIC and len(t) > 1}


def similarity(a_norm: str, b_norm: str) -> float:
    """0..1 entre dois nomes normalizados (palavras relevantes, depois texto)."""
    ma, mb = _meaningful(a_norm), _meaningful(b_norm)
    if ma and mb:
        if ma == mb:
            return 0.95
        jaccard = len(ma & mb) / len(ma | mb)
        if jaccard >= SIMILAR_MIN and (ma <= mb or mb <= ma or jaccard >= 0.6):
            return round(jaccard, 2)
    ratio = SequenceMatcher(None, a_norm, b_norm).ratio()
    return round(ratio, 2) if ratio >= RATIO_MIN else 0.0


def match_client(name: str, clients: list[dict]) -> dict:
    """Retorna {"kind": "exact"|"similar"|"none", "matches": [(cliente, pontuação)]}."""
    norm = normalize_name(name)
    if is_placeholder(name) or not norm:
        return {"kind": "none", "matches": []}
    exact = [c for c in clients
             if c.get("normalized_name") == norm or norm in {normalize_name(a) for a in (c.get("aliases") or [])}]
    if exact:
        return {"kind": "exact", "matches": [(c, 1.0) for c in exact]}
    scored = sorted(((c, similarity(norm, c.get("normalized_name") or normalize_name(c.get("name", "")))) for c in clients),
                    key=lambda x: -x[1])
    scored = [(c, s) for c, s in scored if s > 0][:MAX_CANDIDATES]
    return {"kind": "similar" if scored else "none", "matches": scored}
