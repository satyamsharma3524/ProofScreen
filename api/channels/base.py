"""One Channel interface, two implementations. Adding a third (SMS, Telegram)
means writing one class and nothing else."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from api.schemas import Channel, InboundMessage


class BaseChannel(ABC):
    kind: Channel

    @abstractmethod
    def parse_inbound(self, payload: dict[str, Any]) -> InboundMessage:
        """Normalise a provider-specific payload into an InboundMessage."""

    @abstractmethod
    async def send(self, to: str, text: str) -> bool:
        """Push a message out. Returns False when the channel is in dry-run."""
