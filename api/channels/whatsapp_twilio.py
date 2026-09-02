"""
Twilio WhatsApp Sandbox adapter.

Why the sandbox and not the WhatsApp Business API: Meta onboarding takes days
and needs business verification. The sandbox works in ten minutes — judges join
with a code and message a shared number.

Two Twilio gotchas handled here so they do not eat an evening:
  1. Inbound media URLs need HTTP basic auth (account SID + auth token) or they
     401. Handled in stt.py.
  2. The reply is returned as TwiML in the webhook response, so the demo needs
     no outbound credentials at all. `send()` exists for proactive messages.
"""

from __future__ import annotations

import logging
from typing import Any
from xml.sax.saxutils import escape

import httpx

from api.channels.base import BaseChannel
from api.config import settings
from api.schemas import Channel, InboundMessage

log = logging.getLogger("proofscreen.channel.whatsapp")

TWILIO_API = "https://api.twilio.com/2010-04-01"


def normalise_phone(raw: str | None) -> str | None:
    """'whatsapp:+919812345678' -> '+919812345678'."""
    if not raw:
        return None
    return raw.split(":", 1)[-1].strip() or None


def twiml(text: str) -> str:
    """A TwiML reply. Twilio expects XML, and an empty <Response/> means silence."""
    if not text:
        return '<?xml version="1.0" encoding="UTF-8"?><Response></Response>'
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f"<Response><Message>{escape(text)}</Message></Response>"
    )


class WhatsAppTwilioChannel(BaseChannel):
    kind = Channel.whatsapp

    def parse_inbound(self, payload: dict[str, Any]) -> InboundMessage:
        media_url = None
        content_type = (payload.get("MediaContentType0") or "").lower()
        if payload.get("MediaUrl0") and content_type.startswith(("audio", "video")):
            media_url = payload["MediaUrl0"]

        return InboundMessage(
            channel=Channel.whatsapp,
            text=(payload.get("Body") or "").strip() or None,
            media_url=media_url,
            external_id=payload.get("From"),
        )

    def validate_signature(
        self, url: str, form: dict[str, Any], signature: str | None
    ) -> bool:
        """True when the request really came from Twilio.

        Off by default (TWILIO_VALIDATE_SIGNATURE=false) because during
        development you will be replaying payloads with curl. Turn it on before
        the deployed URL is public.
        """
        if not settings.twilio_validate_signature:
            return True
        if not (settings.twilio_auth_token and signature):
            log.warning("signature validation on but token/signature missing")
            return False
        try:
            from twilio.request_validator import RequestValidator
        except ImportError:
            log.error("twilio package not installed; cannot validate signature")
            return False
        validator = RequestValidator(settings.twilio_auth_token)
        return validator.validate(url, form, signature)

    async def send(self, to: str, text: str) -> bool:
        """Proactive outbound message. Dry-run when credentials are absent."""
        if not settings.twilio_enabled:
            log.info("[dry-run] whatsapp -> %s: %s", to, text[:120])
            return False

        target = to if to.startswith("whatsapp:") else f"whatsapp:{to}"
        url = f"{TWILIO_API}/Accounts/{settings.twilio_account_sid}/Messages.json"
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(
                    url,
                    data={
                        "From": settings.twilio_whatsapp_from,
                        "To": target,
                        "Body": text[:1500],
                    },
                    auth=(settings.twilio_account_sid, settings.twilio_auth_token),
                )
            if resp.status_code >= 300:
                log.error("twilio send failed %s: %s", resp.status_code, resp.text[:300])
                return False
            return True
        except Exception as exc:  # noqa: BLE001  never 500 the webhook
            log.error("twilio send raised: %s", exc)
            return False


whatsapp_channel = WhatsAppTwilioChannel()
