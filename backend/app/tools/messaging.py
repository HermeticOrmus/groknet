"""send_message (issue #5)."""

from sqlmodel import Session

from app import messaging
from app.db import engine
from app.mcp_server import groknet_tool
from app.registry import require_user


@groknet_tool
async def send_message(groknet_token: str, handle: str, body: str) -> dict[str, str | bool]:
    """Send a message to a friend on Groknet. Their bot relays it to their human.

    Only works once you are friends (they accepted your request, or you accepted theirs).
    `delivered` is False if their inbox routine rejected it; the message is still kept.
    """
    with Session(engine) as session:
        sender = require_user(session, groknet_token)
        message = await messaging.send_message(session, sender, handle, body)
        return {"event_id": message.event_id, "delivered": message.delivered}
