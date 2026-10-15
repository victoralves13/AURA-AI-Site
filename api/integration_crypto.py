"""AURA AI — cifra dos segredos de integrações (AES-256-GCM, chave só do servidor).

  * AURA_INTEGRATIONS_KEY: chave atual, 32 bytes em base64 (gere com `python -c "import os,base64;print(base64.urlsafe_b64encode(os.urandom(32)).decode())"`).
  * AURA_INTEGRATIONS_KEY_VERSION: número da chave atual (padrão 1).
  * AURA_INTEGRATIONS_KEY_PREV: chave anterior (versão atual - 1), só para ler segredos antigos durante uma troca de chave.
  * O texto cifrado leva o id da integração como dado autenticado (AAD): copiar o cifrado de uma integração para outra não funciona.
  * Sem chave configurada o recurso fica indisponível (nunca há "plano B" em texto aberto).
"""
from __future__ import annotations

import base64
import binascii
import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class CryptoUnavailable(RuntimeError):
    """Chave ausente ou inválida."""


class CryptoError(RuntimeError):
    """Texto cifrado inválido, adulterado ou de outra chave."""


def _decode(value: str | None) -> bytes | None:
    if not value:
        return None
    try:
        raw = base64.urlsafe_b64decode(value.strip() + "=" * (-len(value.strip()) % 4))
    except (binascii.Error, ValueError):
        return None
    return raw if len(raw) == 32 else None


def current_version() -> int:
    try:
        return max(1, int(os.getenv("AURA_INTEGRATIONS_KEY_VERSION", "1")))
    except ValueError:
        return 1


def _key_for(version: int) -> bytes:
    current = current_version()
    if version == current:
        key = _decode(os.getenv("AURA_INTEGRATIONS_KEY"))
    elif version == current - 1:
        key = _decode(os.getenv("AURA_INTEGRATIONS_KEY_PREV"))
    else:
        key = None
    if key is None:
        raise CryptoUnavailable("Chave de cifra das integrações indisponível.")
    return key


def configured() -> bool:
    return _decode(os.getenv("AURA_INTEGRATIONS_KEY")) is not None


def encrypt(plaintext: str, aad: str) -> tuple[str, int]:
    version = current_version()
    nonce = os.urandom(12)
    ct = AESGCM(_key_for(version)).encrypt(nonce, plaintext.encode("utf-8"), aad.encode("utf-8"))
    return base64.urlsafe_b64encode(nonce + ct).decode("ascii"), version


def decrypt(token: str, aad: str, version: int) -> str:
    key = _key_for(version)
    try:
        raw = base64.urlsafe_b64decode(token + "=" * (-len(token) % 4))
        return AESGCM(key).decrypt(raw[:12], raw[12:], aad.encode("utf-8")).decode("utf-8")
    except (InvalidTag, binascii.Error, ValueError, UnicodeDecodeError) as exc:
        raise CryptoError("Segredo ilegível.") from exc
