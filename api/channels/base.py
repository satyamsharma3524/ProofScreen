"""One Channel interface. Adding SMS or Telegram later means one class."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from api.schemas import Channel, InboundMessage


class BaseChannel(ABC):
    kind: Channel

    @abstractmethod
    def parse_inbound(self, payload: dict[str, Any]) -> list[InboundMessage]:
        """Normalise a provider payload into zero or more InboundMessages.

        A list, not a single message: WhatsApp Cloud API batches several
        messages into one webhook delivery, and dropping the tail would lose a
        candidate's answer.
        """

    @abstractmethod
    async def send_text(self, to: str, text: str) -> bool:
        """Send a free-form message. False when the channel is in dry-run."""
