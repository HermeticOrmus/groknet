"""search_users, send_friend_request, respond_to_friend_request (issue #4)."""

import functools
from collections.abc import Awaitable, Callable
from typing import Any

from mcp.server.mcpserver.exceptions import ToolError
from sqlmodel import Session

from app import friendships
from app.db import engine
from app.errors import GroknetError
from app.mcp_server import groknet_tool, mcp
from app.registry import require_user
from app.webhooks import deliver


def groknet_async_tool(fn: Callable[..., Awaitable]) -> Callable:
    """Async twin of `groknet_tool`: the sync wrapper would hand the SDK a coroutine.

    Candidate to move into app/mcp_server.py once both tracks that need it have merged.
    """

    @functools.wraps(fn)
    async def wrapper(*args, **kwargs):
        try:
            return await fn(*args, **kwargs)
        except GroknetError as e:
            raise ToolError(str(e)) from e

    return mcp.tool()(wrapper)


@groknet_tool
def search_users(groknet_token: str, query: str = "") -> dict[str, list[dict[str, Any]]]:
    """Find people on Groknet by handle or name (case-insensitive). Empty query lists everyone.

    Returns {"users": [{handle, display_name, profile}]} where profile is whatever the person
    shared about themselves (age, job, bio, location...). Use the handle with send_friend_request.
    """
    with Session(engine) as session:
        caller = require_user(session, groknet_token)
        users = friendships.search_users(session, caller, query)
        return {
            "users": [
                {
                    "handle": u.handle,
                    "display_name": u.display_name,
                    # `profile` lands on User from another branch; default until then.
                    "profile": getattr(u, "profile", None) or {},
                }
                for u in users
            ]
        }


@groknet_async_tool
async def send_friend_request(groknet_token: str, handle: str) -> dict[str, str]:
    """Ask another Groknet user to connect. Their bot tells their human, who accepts or declines.

    If they already asked you, this accepts. Returns {friendship_id, status}.
    """
    with Session(engine) as session:
        caller = require_user(session, groknet_token)
        friendship, event = friendships.request_friendship(session, caller, handle)
        other_handle = (
            friendship.addressee if friendship.requester == caller.handle else friendship.requester
        )
        other = friendships.get_user(session, other_handle)
        if event == "friend_request":
            await deliver(
                other,
                event_type="friend_request",
                sender=caller,
                payload={"message": f"{caller.display_name} wants to connect on Groknet"},
            )
        elif event == "friend_accepted":
            await deliver(
                other,
                event_type="friend_accepted",
                sender=caller,
                payload={"message": f"{caller.display_name} accepted your request"},
            )
        return {"friendship_id": friendship.id, "status": friendship.status}


@groknet_async_tool
async def respond_to_friend_request(
    groknet_token: str, handle: str, accept: bool
) -> dict[str, str]:
    """Accept or decline a pending friend request from `handle`. Only your human decides this.

    Returns {status}: "accepted" or "declined".
    """
    with Session(engine) as session:
        caller = require_user(session, groknet_token)
        friendship = friendships.respond(session, caller, handle, accept)
        if accept:
            requester = friendships.get_user(session, friendship.requester)
            await deliver(
                requester,
                event_type="friend_accepted",
                sender=caller,
                payload={"message": f"{caller.display_name} accepted your request"},
            )
        return {"status": friendship.status}
