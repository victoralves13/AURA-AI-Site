"""Entrada da função na Vercel: só localiza o pacote do backend e expõe o app ASGI (a aplicação está em backend/aura/app.py)."""
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1] / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from aura.app import app, handler  # noqa: E402,F401
