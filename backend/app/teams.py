"""Teams (issue #15): create, add friends, and fan a message out to every member.

Shared by the MCP tools and the REST mirror. One Message row per team message; one
webhook delivery per member except the sender, all carrying the same event_id.
"""

import asyncio

from sqlmodel import Session, select

from app.errors import GroknetError
from app.events import bus
from app.friendships import find_friendship, get_user
from app.models import FriendshipStatus, Message, Team, TeamMember, User
from app.webhooks import deliver

MAX_NAME = 64


class TeamError(GroknetError):
    pass


def member_handles(session: Session, team_id: str) -> list[str]:
    rows = session.exec(select(TeamMember.user_handle).where(TeamMember.team_id == team_id))
    return sorted(rows.all())


def get_team(session: Session, team_id: str) -> Team:
    team = session.get(Team, team_id)
    if team is None:
        raise TeamError(f"No team with id {team_id!r}.")
    return team


def _require_member(session: Session, team: Team, user: User) -> list[str]:
    members = member_handles(session, team.id)
    if user.handle not in members:
        raise TeamError(f"You are not a member of team {team.name!r}.")
    return members


def _team_ref(team: Team) -> dict[str, str]:
    return {"id": team.id, "name": team.name}


def create_team(session: Session, caller: User, name: str) -> Team:
    name = name.strip()
    if not 1 <= len(name) <= MAX_NAME:
        raise TeamError(f"Team name must be 1-{MAX_NAME} characters.")
    team = Team(name=name, created_by=caller.handle)
    session.add(team)
    session.add(TeamMember(team_id=team.id, user_handle=caller.handle))
    session.commit()
    session.refresh(team)
    bus.publish({"type": "team_created", "team": _team_ref(team), "by": caller.handle})
    return team


def add_to_team(session: Session, caller: User, team_id: str, handle: str) -> list[str]:
    """Add a friend of the caller. Returns the member handles. Adding a member again is a no-op."""
    team = get_team(session, team_id)
    members = _require_member(session, team, caller)
    other = get_user(session, handle)
    if other.handle in members:
        return members
    friendship = find_friendship(session, caller.handle, other.handle)
    if friendship is None or friendship.status != FriendshipStatus.accepted:
        raise TeamError(
            f"You are not friends with @{other.handle}. Only accepted friends can be added."
        )
    session.add(TeamMember(team_id=team.id, user_handle=other.handle))
    session.commit()
    bus.publish(
        {
            "type": "team_member_added",
            "team": _team_ref(team),
            "by": caller.handle,
            "handle": other.handle,
        }
    )
    return member_handles(session, team.id)


async def send_team_message(
    session: Session, sender: User, team_id: str, body: str, mentions: list[str] | None = None
) -> tuple[Message, list[str], list[str]]:
    """Returns (message, delivered_to, failed), both lists of handles in sorted order."""
    team = get_team(session, team_id)
    members = _require_member(session, team, sender)
    if not body.strip():
        raise TeamError("Message body is empty.")
    mentions = [m.strip().lower().lstrip("@") for m in mentions or []]
    strangers = [m for m in mentions if m not in members]
    if strangers:
        raise TeamError(f"Mentions must be team members; not in {team.name!r}: {strangers}.")

    message = Message(
        sender=sender.handle,
        team_id=team.id,
        body=body,
        mentions=",".join(mentions) or None,
    )
    session.add(message)
    session.commit()
    session.refresh(message)

    team_ref = _team_ref(team)
    recipients = [session.get(User, h) for h in members if h != sender.handle]
    results = await asyncio.gather(
        *(
            deliver(
                r,
                event_type="team_message",
                sender=sender,
                payload={"body": body, "team": team_ref, "mentions": mentions},
                event_id=message.event_id,
            )
            for r in recipients
        )
    )
    delivered_to = [r.handle for r, ok in zip(recipients, results, strict=True) if ok]
    failed = [r.handle for r, ok in zip(recipients, results, strict=True) if not ok]

    message.delivered = bool(delivered_to)
    session.add(message)
    session.commit()
    session.refresh(message)

    bus.publish(
        {
            "type": "team_message",
            "event_id": message.event_id,
            "from": sender.handle,
            "team": team_ref,
            "body": body,
            "mentions": mentions,
            "delivered_to": delivered_to,
            "failed": failed,
        }
    )
    return message, delivered_to, failed
