"""
WhatsApp Business Cloud API (Meta, direct).  Owned by Dev A.

This is the real Business API — graph.facebook.com against a WABA phone number
id — not the Twilio sandbox.

FOUR THINGS THAT ARE DIFFERENT FROM A SANDBOX, AND ALL FOUR BITE
----------------------------------------------------------------
1. NO INLINE REPLY. There is no TwiML equivalent. The webhook must return 200
   fast and the answer goes out as a SEPARATE authenticated API call. Outbound
   credentials are therefore mandatory for the demo, not optional.

2. THE 24-HOUR WINDOW. Free-form text is only allowed within 24 hours of the
   candidate's last message. Outside it, only an approved TEMPLATE can be sent.
   That is why the candidate opts in first: their opt-in message opens the
   window and every question after it is free-form.

3. TWO-STEP MEDIA. A voice note arrives as a media id, not a URL. You GET the
   id to obtain a short-lived URL, then GET that URL — both with the bearer
   token. Missing the token on the second call is a 401 that looks like a bug
   in your own code.

4. BATCHED DELIVERIES AND STATUS NOISE. One webhook call can carry several
   messages, and most calls carry only delivery statuses with no message at
   all. Anything that assumes "one webhook, one message" silently drops
   answers.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
from typing import Any

import httpx

from api.channels.base import BaseChannel
from api.config import settings
from api.schemas import Channel, InboundMessage

log = logging.getLogger("proofscreen.whatsapp")

TEXT_LIMIT = 4096          # Meta's body limit


def normalise_phone(raw: str | None) -> str | None:
    """Meta sends a bare wa_id like '919812345678'. Store it E.164 with a '+'
    so it matches whatever the recruiter typed into the upload form."""
    if not raw:
        return None
    digits = "".join(ch for ch in str(raw) if ch.isdigit())
    return f"+{digits}" if digits else None


class WhatsAppCloudChannel(BaseChannel):
    kind = Channel.whatsapp

    # -- inbound ----------------------------------------------------------

    def verify_challenge(
        self, mode: str | None, token: str | None, challenge: str | None
    ) -> str | None:
        """Meta's GET handshake. Returns the challenge to echo, or None."""
        if mode == "subscribe" and token and token == settings.whatsapp_verify_token:
            return challenge or ""
        log.warning("webhook verification failed (mode=%s)", mode)
        return None

    def validate_signature(self, raw_body: bytes, header: str | None) -> bool:
        """X-Hub-Signature-256: sha256=<hmac of the RAW body with the app secret>.

        Must be computed on the exact bytes received — re-serialising the parsed
        JSON changes whitespace and key order and the digest never matches.
        """
        if not settings.whatsapp_validate_signature:
            return True
        if not settings.whatsapp_app_secret or not header:
            log.warning("signature validation on but app secret or header missing")
            return False
        expected = hmac.new(
            settings.whatsapp_app_secret.encode(), raw_body, hashlib.sha256
        ).hexdigest()
        provided = header.split("=", 1)[-1].strip()
        return hmac.compare_digest(expected, provided)

    def parse_inbound(self, payload: dict[str, Any]) -> list[InboundMessage]:
        """Pull every candidate message out of one webhook delivery.

        Ignores `statuses` entries (delivery receipts), reactions, and system
        messages — they are the majority of traffic and none of them are answers.
        """
        out: list[InboundMessage] = []
        for entry in payload.get("entry") or []:
            for change in entry.get("changes") or []:
                value = change.get("value") or {}
                if not value.get("messages"):
                    continue                      # status-only delivery

                names: dict[str, str] = {}
                for contact in value.get("contacts") or []:
                    wa_id = contact.get("wa_id")
                    name = ((contact.get("profile") or {}).get("name") or "").strip()
                    if wa_id and name:
                        names[str(wa_id)] = name

                for message in value["messages"]:
                    kind = message.get("type")
                    sender = str(message.get("from") or "")
                    text: str | None = None
                    media_id: str | None = None

                    if kind == "text":
                        text = ((message.get("text") or {}).get("body") or "").strip() or None
                    elif kind in ("audio", "voice"):
                        media_id = (message.get(kind) or {}).get("id")
                    elif kind == "button":
                        text = ((message.get("button") or {}).get("text") or "").strip() or None
                    elif kind == "interactive":
                        interactive = message.get("interactive") or {}
                        reply = (
                            interactive.get("button_reply")
                            or interactive.get("list_reply")
                            or {}
                        )
                        text = (reply.get("title") or "").strip() or None
                    else:
                        log.info("ignoring unsupported message type %r", kind)
                        continue

                    out.append(
                        InboundMessage(
                            channel=Channel.whatsapp,
                            text=text,
                            media_id=media_id,
                            external_id=sender,
                            profile_name=names.get(sender),
                            provider_message_id=message.get("id"),
                        )
                    )
        return out

    # -- outbound ---------------------------------------------------------

    async def _post(self, body: dict[str, Any]) -> bool:
        if not settings.whatsapp_enabled:
            target = body.get("to") or body.get("message_id") or "?"
            log.info(
                "[dry-run] whatsapp %s -> %s: %s",
                body.get("type") or body.get("status") or "message",
                target, str(body.get("text") or body)[:180],
            )
            return False

        url = f"{settings.graph_api_base}/{settings.whatsapp_phone_number_id}/messages"
        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                resp = await client.post(
                    url,
                    json=body,
                    headers={
                        "Authorization": f"Bearer {settings.whatsapp_access_token}",
                        "Content-Type": "application/json",
                    },
                )
            if resp.status_code >= 300:
                log.error(
                    "whatsapp send failed %s: %s", resp.status_code, resp.text[:400]
                )
                return False
            return True
        except Exception as exc:  # noqa: BLE001  never let this 500 a webhook
            log.error("whatsapp send raised: %s", exc)
            return False

    async def send_text(self, to: str, text: str) -> bool:
        """Free-form message. Only valid inside the 24-hour window."""
        return await self._post(
            {
                "messaging_product": "whatsapp",
                "recipient_type": "individual",
                "to": normalise_phone(to) or to,
                "type": "text",
                "text": {"preview_url": False, "body": (text or "")[:TEXT_LIMIT]},
            }
        )

    async def send_template(
        self, to: str, parameters: list[str] | None = None
    ) -> bool:
        """Open a conversation with a candidate who has not messaged us.

        Required outside the 24-hour window. The template must already be
        approved in the WhatsApp Manager; WHATSAPP_TEMPLATE_NAME names it.
        """
        if not settings.whatsapp_template_name:
            log.info("no WHATSAPP_TEMPLATE_NAME configured; cannot initiate")
            return False

        template: dict[str, Any] = {
            "name": settings.whatsapp_template_name,
            "language": {"code": settings.whatsapp_template_language},
        }
        if parameters:
            template["components"] = [
                {
                    "type": "body",
                    "parameters": [{"type": "text", "text": p} for p in parameters],
                }
            ]
        return await self._post(
            {
                "messaging_product": "whatsapp",
                "recipient_type": "individual",
                "to": normalise_phone(to) or to,
                "type": "template",
                "template": template,
            }
        )

    async def mark_read(self, provider_message_id: str) -> bool:
        """Blue ticks. Cosmetic, but on a live demo the candidate sees them."""
        if not provider_message_id:
            return False
        return await self._post(
            {
                "messaging_product": "whatsapp",
                "status": "read",
                "message_id": provider_message_id,
            }
        )

    # -- media ------------------------------------------------------------

    async def media_url(self, media_id: str) -> tuple[str | None, str | None]:
        """Step 1 of 2: media id -> short-lived URL + mime type."""
        if not settings.whatsapp_enabled:
            return None, None
        url = f"{settings.graph_api_base}/{media_id}"
        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                resp = await client.get(
                    url,
                    headers={"Authorization": f"Bearer {settings.whatsapp_access_token}"},
                )
            resp.raise_for_status()
            data = resp.json()
            return data.get("url"), data.get("mime_type")
        except Exception as exc:  # noqa: BLE001
            log.error("media lookup failed for %s: %s", media_id, exc)
            return None, None

    async def download_media(self, media_id: str) -> tuple[bytes | None, str]:
        """Step 2 of 2. The bearer token is required on BOTH calls — omitting
        it on this one is the 401 that eats an afternoon."""
        url, mime = await self.media_url(media_id)
        if not url:
            return None, "audio/ogg"
        try:
            async with httpx.AsyncClient(timeout=45.0, follow_redirects=True) as client:
                resp = await client.get(
                    url,
                    headers={"Authorization": f"Bearer {settings.whatsapp_access_token}"},
                )
            resp.raise_for_status()
            return resp.content, mime or "audio/ogg"
        except Exception as exc:  # noqa: BLE001
            log.error("media download failed for %s: %s", media_id, exc)
            return None, mime or "audio/ogg"


whatsapp_channel = WhatsAppCloudChannel()
