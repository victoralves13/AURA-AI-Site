"""Testes do AURA AI. Rode da raiz: python -m unittest discover -s tests -t .

Este pacote põe backend/ no caminho de importação (os testes importam `aura`) e `tests.support` traz o Supabase simulado."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]  # raiz do repositório
_BACKEND = str(ROOT / "backend")
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)
