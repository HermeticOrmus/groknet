"""Outbound delivery to a bot's Grok Bot routine webhook.

Contract (see docs/design.md):
  POST {recipient.webhook_url}
  Authorization: Bearer {recipient.webhook_key}
  {"event_id": ..., "type": "friend_request"|"friend_accepted"|"message"|"team_message",
   "from": {"handle": ..., "display_name": ...}, "payload": {...}}

Grok Bot facts that shape this (docs/design.md): 200 + {"success": true} means a run
started; 400 is "routine disabled" and 401 "bad key", both terminal; a resend starts a
second run, so only 503 and transport errors are ever retried.

Other features call `deliver(...)` and must not re-implement it.
"""

import asyncio
import logging
from collections.abc import Callable
from typing import Any
from uuid import uuid4

import httpx

from app.events import bus
from app.models import User

log = logging.getLogger("groknet.webhooks")

# Seconds to wait before each retry. Tests shrink this.
RETRY_BACKOFF_S: tuple[float, ...] = (1, 3, 9)
RETRYABLE_STATUSES = {503}
TIMEOUT_S = 15


def new_event_id() -> str:
    return uuid4().hex


async def deliver(
    recipient: User,
    *,
    event_type: str,
    sender: User,
    payload: dict[str, Any],
    event_id: str | None = None,
    on_result: Callable[[dict[str, Any]], None] | None = None,
) -> bool:
    """POST one event to `recipient`'s inbox routine. Returns True only when the bot
    accepted it (HTTP 200 with {"success": true}). Never raises on delivery failure.

    A feature may provide on_result to persist and publish an enriched receipt.
    Without that hook the existing global delivery event is published unchanged.
    """
    event_id = event_id or new_event_id()
    event = {
        "event_id": event_id,
        "type": event_type,
        "from": {"handle": sender.handle, "display_name": sender.display_name},
        "payload": payload,
    }
    headers = {"Authorization": f"Bearer {recipient.webhook_key}"}

    ok, status = False, None
    async with httpx.AsyncClient(timeout=TIMEOUT_S) as client:
        for attempt in range(len(RETRY_BACKOFF_S) + 1):
            try:
                resp = await client.post(recipient.webhook_url, json=event, headers=headers)
            except httpx.HTTPError as exc:
                status = None
                log.warning(
                    "deliver %s %s -> @%s attempt %d: transport error %s",
                    event_type,
                    event_id,
                    recipient.handle,
                    attempt + 1,
                    type(exc).__name__,
                )
            else:
                status = resp.status_code
                ok = status == 200 and _accepted(resp)
                log.log(
                    logging.INFO if ok else logging.WARNING,
                    "deliver %s %s -> @%s attempt %d: HTTP %d%s",
                    event_type,
                    event_id,
                    recipient.handle,
                    attempt + 1,
                    status,
                    "" if ok else " (not accepted)",
                )
                if ok or status not in RETRYABLE_STATUSES:
                    break
            if attempt < len(RETRY_BACKOFF_S):
                await asyncio.sleep(RETRY_BACKOFF_S[attempt])

    receipt = {
            "type": "delivery",
            "event_id": event_id,
            "event_type": event_type,
            "to": recipient.handle,
            "ok": ok,
            "status": status,
        }
    if on_result is not None:
        on_result(receipt)
    else:
        bus.publish(receipt)
    return ok


def _accepted(resp: httpx.Response) -> bool:
    try:
        return resp.json().get("success") is True
    except ValueError:
        return False
