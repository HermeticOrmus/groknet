"""Outbound delivery to a bot's Grok Bot routine webhook.

Contract (see docs/design.md):
  POST {webhook_url}
  Authorization: Bearer {webhook_key}
  {"event_id": ..., "type": "friend_request"|"friend_accepted"|"message"|"team_message",
   "from": {"handle": ..., "display_name": ...}, "payload": {...}}

TODO (issue: webhook sender): retry on 503 with backoff, log every delivery,
publish delivery result to events.bus, mark Message.delivered.
"""

from typing import Any

import httpx


async def deliver(webhook_url: str, webhook_key: str, event: dict[str, Any]) -> bool:
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            webhook_url,
            json=event,
            headers={"Authorization": f"Bearer {webhook_key}"},
        )
    return resp.status_code == 200
