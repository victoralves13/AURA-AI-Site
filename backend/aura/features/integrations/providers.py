"""Integrações — contrato dos provedores (destinos) e o registro dos que estão disponíveis.

O serviço só conhece este contrato; cada destino (hoje só o webhook assinado) é um adaptador que o cumpre e se registra no app.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass
class DeliveryResult:
    ok: bool
    status_code: int | None = None
    error: str | None = None  # texto curto e sem dados sensíveis
    retryable: bool = True


class Provider(Protocol):
    name: str

    def validate_config(self, config: dict) -> dict:
        """Confere/limpa a configuração (sem o segredo). Levanta ValueError com uma mensagem para a pessoa."""

    def deliver(self, config: dict, secret: str, event: dict) -> DeliveryResult:
        """Entrega o evento. `event` = {id, type, entity_type, entity_id, data, created_at}."""


_PROVIDERS: dict[str, Provider] = {}


def register_provider(provider: Provider) -> None:
    _PROVIDERS[provider.name] = provider


def unregister_provider(name: str) -> None:
    _PROVIDERS.pop(name, None)


def get_provider(name: str) -> Provider | None:
    return _PROVIDERS.get(name)


def names() -> list[str]:
    return sorted(_PROVIDERS)
