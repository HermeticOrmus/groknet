"""create_team, add_to_team, send_team_message (issue #15)."""

from typing import Any

from sqlmodel import Session

from app import teams
from app.db import engine
from app.mcp_server import groknet_tool
from app.registry import require_user


@groknet_tool
def create_team(groknet_token: str, name: str) -> dict[str, Any]:
    """Start a team (a group chat between bots). You are its first member.

    name: 1-64 characters. Returns {team_id, name, members}. Keep team_id for the other team tools.
    """
    with Session(engine) as session:
        caller = require_user(session, groknet_token)
        team = teams.create_team(session, caller, name)
        return {"team_id": team.id, "name": team.name, "members": [caller.handle]}


@groknet_tool
def add_to_team(groknet_token: str, team_id: str, handle: str) -> dict[str, Any]:
    """Add one of your accepted friends to a team you belong to. Adding a member again is harmless.

    Returns {team_id, members}.
    """
    with Session(engine) as session:
        caller = require_user(session, groknet_token)
        members = teams.add_to_team(session, caller, team_id, handle)
        return {"team_id": team_id, "members": members}


@groknet_tool
async def send_team_message(
    groknet_token: str, team_id: str, body: str, mentions: list[str] | None = None
) -> dict[str, Any]:
    """Send a message to every other member of a team. Each member's bot relays it to their human.

    mentions: optional list of member handles to call out (each must be in the team).
    Returns {event_id, delivered_to, failed}: handles whose inbox accepted it, and those that did not.
    """
    with Session(engine) as session:
        sender = require_user(session, groknet_token)
        message, delivered_to, failed = await teams.send_team_message(
            session, sender, team_id, body, mentions
        )
        return {"event_id": message.event_id, "delivered_to": delivered_to, "failed": failed}
