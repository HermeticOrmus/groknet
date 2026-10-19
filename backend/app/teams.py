"""Team membership and concurrent message fan-out, shared by REST and MCP."""

import asyncio
from datetime import UTC, datetime
from typing import Any

from sqlmodel import Session, select

from app.errors import GroknetError
from app.events import bus
from app.messaging import are_friends
from app.models import Message, Team, TeamMember, User, now
from app.team_models import TeamDelivery
from app.webhooks import deliver


class TeamError(GroknetError):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def utc_timestamp(value: datetime) -> str:
    # SQLite returns naive datetimes even when the original value was UTC.
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def require_team(session: Session, team_id: str) -> Team:
    team = session.get(Team, team_id)
    if team is None:
        raise TeamError("Team not found.", 404)
    return team


def require_member(session: Session, team_id: str, handle: str) -> Team:
    team = require_team(session, team_id)
    if session.get(TeamMember, (team_id, handle)) is None:
        raise TeamError("You must be a team member to do that.", 403)
    return team


def team_view(session: Session, team: Team) -> dict[str, Any]:
    members = session.exec(
        select(User)
        .join(TeamMember, TeamMember.user_handle == User.handle)
        .where(TeamMember.team_id == team.id)
        .order_by(TeamMember.added_at, User.handle)
    ).all()
    return {
        **team.model_dump(mode="json"),
        "created_at": utc_timestamp(team.created_at),
        "members": sorted(u.handle for u in members),
        "member_details": [{"handle": u.handle, "display_name": u.display_name} for u in members],
    }


def list_teams(session: Session) -> list[dict[str, Any]]:
    return [
        team_view(session, team)
        for team in session.exec(select(Team).order_by(Team.created_at, Team.id)).all()
    ]


def create_team(session: Session, creator: User, name: str) -> Team:
    name = name.strip()
    if not name or len(name) > 100:
        raise TeamError("Team name must be between 1 and 100 characters.")
    team = Team(name=name, created_by=creator.handle)
    session.add(team)
    session.add(TeamMember(team_id=team.id, user_handle=creator.handle))
    session.commit()
    session.refresh(team)
    bus.publish({"type": "team_created", "team_id": team.id})
    return team


def add_to_team(session: Session, caller: User, team_id: str, handle: str) -> list[str]:
    require_member(session, team_id, caller.handle)
    if session.get(User, handle) is None:
        raise TeamError(f"No one on Groknet has the handle {handle!r}.", 404)
    if session.get(TeamMember, (team_id, handle)) is None:
        if not are_friends(session, caller.handle, handle):
            raise TeamError("An accepted friendship is required before adding this member.", 403)
        session.add(TeamMember(team_id=team_id, user_handle=handle))
        session.commit()
        bus.publish({"type": "team_member_added", "team_id": team_id, "handle": handle})
    return list(
        session.exec(
            select(TeamMember.user_handle)
            .where(TeamMember.team_id == team_id)
            .order_by(TeamMember.user_handle)
        ).all()
    )


def receipt_view(receipt: TeamDelivery) -> dict[str, Any]:
    return {
        **receipt.model_dump(mode="json", exclude={"event_id"}),
        "updated_at": utc_timestamp(receipt.updated_at),
    }


def message_view(session: Session, message: Message) -> dict[str, Any]:
    sender = session.get(User, message.sender)
    receipts = session.exec(
        select(TeamDelivery)
        .where(TeamDelivery.event_id == message.event_id)
        .order_by(TeamDelivery.recipient)
    ).all()
    return {
        **message.model_dump(mode="json"),
        "created_at": utc_timestamp(message.created_at),
        "sender_name": sender.display_name if sender else message.sender,
        "mentions": message.mentions.split(",") if message.mentions else [],
        "deliveries": [receipt_view(receipt) for receipt in receipts],
    }


def message_history(session: Session, team_id: str, limit: int = 200) -> list[dict[str, Any]]:
    require_team(session, team_id)
    messages = session.exec(
        select(Message)
        .where(Message.team_id == team_id)
        .order_by(Message.created_at.desc(), Message.id.desc())
        .limit(limit)
    ).all()
    return [message_view(session, message) for message in reversed(messages)]


async def send_team_message(
    session: Session, sender: User, team_id: str, body: str, mentions: list[str] | None = None
) -> dict[str, Any]:
    team = require_member(session, team_id, sender.handle)
    if not body.strip():
        raise TeamError("Message body is empty.")
    members = session.exec(
        select(User)
        .join(TeamMember, TeamMember.user_handle == User.handle)
        .where(TeamMember.team_id == team_id)
        .order_by(User.handle)
    ).all()
    handles = {u.handle for u in members}
    mentions = list(dict.fromkeys(mentions or []))
    if any(handle not in handles for handle in mentions):
        raise TeamError("Every mentioned handle must be a team member (use bare handles).")
    recipients = [u for u in members if u.handle != sender.handle]
    # Snapshot identities and credentials before commits expire ORM state. These
    # private objects stay in process and never reach dashboard events or JSON.
    targets = [User.model_validate(u.model_dump()) for u in recipients]
    sender_snapshot = User.model_validate(sender.model_dump())
    payload = {"body": body, "team": {"id": team.id, "name": team.name}, "mentions": mentions}
    message = Message(sender=sender.handle, team_id=team_id, body=body, mentions=",".join(mentions))
    session.add(message)
    for recipient in targets:
        session.add(TeamDelivery(event_id=message.event_id, recipient=recipient.handle))
    session.commit()
    session.refresh(message)
    event_id = message.event_id
    bus.publish(
        {
            "type": "team_message",
            "from": sender_snapshot.handle,
            "team": payload["team"],
            **message_view(session, message),
        }
    )

    async def send_one(recipient: User) -> str | None:
        result: dict[str, Any] = {}
        try:
            ok = await deliver(
                recipient,
                event_type="team_message",
                sender=sender_snapshot,
                payload=payload,
                event_id=event_id,
                on_result=result.update,
            )
        except Exception:  # noqa: BLE001 - isolate recipients without exposing secret URLs
            # Exceptions may carry a secret URL/key. Keep the outcome uncertain
            # and keep delivering to other members; never publish exception text.
            ok = False
        status = result.get("status")
        definitive_rejection = isinstance(status, int) and 400 <= status < 500 and status != 408
        delivery_status = "delivered" if ok else "failed" if definitive_rejection else "unknown"
        receipt = session.get(TeamDelivery, (event_id, recipient.handle))
        assert receipt is not None
        receipt.status = delivery_status
        receipt.revision += 1
        receipt.updated_at = now()
        session.add(receipt)
        session.commit()
        session.refresh(receipt)
        bus.publish(
            {
                "type": "delivery",
                "event_type": "team_message",
                "event_id": event_id,
                "team_id": team_id,
                "to": recipient.handle,
                "delivery_status": receipt.status,
                "revision": receipt.revision,
                "updated_at": utc_timestamp(receipt.updated_at),
                "ok": bool(ok),
                "status": status,
            }
        )
        return recipient.handle if ok else None

    outcomes = await asyncio.gather(*(send_one(recipient) for recipient in targets))
    delivered_to = [handle for handle in outcomes if handle is not None]
    message.delivered = bool(targets) and len(delivered_to) == len(targets)
    session.add(message)
    session.commit()
    return {"event_id": event_id, "delivered_to": delivered_to}
