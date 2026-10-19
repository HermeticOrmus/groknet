"""Outbound delivery to a bot's Grok Bot routine webhook.

Contract (see docs/design.md):
  POST {recipient.webhook_url}
  Authorization: Bearer {recipient.webhook_key}
  {"event_id": ..., "type": "friend_request"|"friend_accepted"|"message"|"team_message",
   "from": {"handle": ..., "display_name": ...}, "payload": {...}}

Owned by issue #5 (sender: 503 retry with backoff, delivery log, `delivery` bus
event). Other features call `deliver(...)` and must not re-implement it.
"""

from typing import Any
from uuid import uuid4

import httpx

from app.models import User


def new_event_id() -> str:
    return uuid4().hex


async def deliver(
    recipient: User,
    *,
    event_type: str,
    sender: User,
    payload: dict[str, Any],
    event_id: str | None = None,
) -> bool:
    """POST one event to `recipient`'s inbox routine. Returns True only when the bot
    accepted it (HTTP 200 with {"success": true}). Never raises on delivery failure."""
    event = {
        "event_id": event_id or new_event_id(),
        "type": event_type,
        "from": {"handle": sender.handle, "display_name": sender.display_name},
        "payload": payload,
    }
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                recipient.webhook_url,
                json=event,
                headers={"Authorization": f"Bearer {recipient.webhook_key}"},
            )
    except httpx.HTTPError:
        return False
    return resp.status_code == 200 and resp.json().get("success") is True
