"""send_message (issue #5)."""

import functools
from collections.abc import Callable

from mcp.server.mcpserver.exceptions import ToolError
from sqlmodel import Session

from app import messaging
from app.db import engine
from app.errors import GroknetError
from app.mcp_server import mcp
from app.registry import require_user


def async_groknet_tool(fn: Callable) -> Callable:
    """`groknet_tool` for `async def` tools.

    The sync wrapper in app.mcp_server returns a coroutine for an async function, which the
    SDK then treats as the tool's result. Delivery is async, so this tool needs an async
    wrapper. Candidate to fold into app.mcp_server once the parallel tracks have merged.
    """

    @functools.wraps(fn)
    async def wrapper(*args, **kwargs):
        try:
            return await fn(*args, **kwargs)
        except GroknetError as e:
            raise ToolError(str(e)) from e

    return mcp.tool()(wrapper)


@async_groknet_tool
async def send_message(groknet_token: str, handle: str, body: str) -> dict[str, str | bool]:
    """Send a message to a friend on Groknet. Their bot relays it to their human.

    Only works once you are friends (they accepted your request, or you accepted theirs).
    `delivered` is False if their inbox routine rejected it; the message is still kept.
    """
    with Session(engine) as session:
        sender = require_user(session, groknet_token)
        message = await messaging.send_message(session, sender, handle, body)
        return {"event_id": message.event_id, "delivered": message.delivered}
