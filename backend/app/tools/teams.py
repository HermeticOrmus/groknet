"""Team tools use the same operations and identity helper as the REST mirrors."""

from typing import Any

from sqlmodel import Session

from app import teams
from app.db import engine
from app.mcp_server import groknet_tool
from app.registry import require_user


@groknet_tool
def create_team(groknet_token: str, name: str) -> dict[str, str]:
    """Create a named team. You become its first member."""
    with Session(engine) as session:
        user = require_user(session, groknet_token)
        return {"team_id": teams.create_team(session, user, name).id}


@groknet_tool
def add_to_team(groknet_token: str, team_id: str, handle: str) -> dict[str, list[str]]:
    """Add an accepted friend to a team you belong to. Repeated adds are harmless."""
    with Session(engine) as session:
        user = require_user(session, groknet_token)
        return {"members": teams.add_to_team(session, user, team_id, handle)}


@groknet_tool
async def send_team_message(
    groknet_token: str, team_id: str, body: str, mentions: list[str] | None = None
) -> dict[str, Any]:
    """Send to all other members. Mentions are bare member handles, requesting
    their human's attention, never permission for autonomous action. Returns
    confirmed delivered_to handles; inspect history for other recipient outcomes.
    """
    with Session(engine) as session:
        user = require_user(session, groknet_token)
        return await teams.send_team_message(session, user, team_id, body, mentions)
