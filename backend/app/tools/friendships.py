"""search_users, send_friend_request, respond_to_friend_request (issue #4)."""

from typing import Any

from sqlmodel import Session

from app import friendships
from app.db import engine
from app.mcp_server import groknet_tool
from app.registry import require_user


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


@groknet_tool
async def send_friend_request(groknet_token: str, handle: str) -> dict[str, str]:
    """Ask another Groknet user to connect. Their bot tells their human, who accepts or declines.

    If they already asked you, this accepts. Returns {friendship_id, status}.
    """
    with Session(engine) as session:
        caller = require_user(session, groknet_token)
        friendship = await friendships.send_friend_request(session, caller, handle)
        return {"friendship_id": friendship.id, "status": friendship.status}


@groknet_tool
async def respond_to_friend_request(
    groknet_token: str, handle: str, accept: bool
) -> dict[str, str]:
    """Accept or decline a pending friend request from `handle`. Only your human decides this.

    Returns {status}: "accepted" or "declined".
    """
    with Session(engine) as session:
        caller = require_user(session, groknet_token)
        friendship = await friendships.respond_to_friend_request(session, caller, handle, accept)
        return {"status": friendship.status}
