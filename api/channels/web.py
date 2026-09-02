"""Web chat channel — the one with no external dependency.

This is the Twilio fallback and the channel the Next.js candidate UI talks to.
`send` is a no-op because the HTTP response itself carries the next question.
"""

from __future__ import annotations

import logging
from typing import Any

from api.channels.base import BaseChannel
from api.schemas import Channel, InboundMessage

log = logging.getLogger("proofscreen.channel.web")


class WebChannel(BaseChannel):
    kind = Channel.web

    def parse_inbound(self, payload: dict[str, Any]) -> InboundMessage:
        return InboundMessage(
            channel=Channel.web,
            text=payload.get("text"),
            media_url=payload.get("audio_url"),
            session_id=payload.get("session_id"),
        )

    async def send(self, to: str, text: str) -> bool:
        log.debug("web channel: reply delivered in the HTTP response body")
        return True


web_channel = WebChannel()
