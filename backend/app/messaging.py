"""Direct messages between friends (issue #5). Shared by the MCP tool and the REST mirror."""

from sqlmodel import Session, or_, select

from app.errors import GroknetError
from app.events import bus
from app.models import Friendship, FriendshipStatus, Message, User
from app.webhooks import deliver


class MessagingError(GroknetError):
    pass


def are_friends(session: Session, a: str, b: str) -> bool:
    row = session.exec(
        select(Friendship).where(
            Friendship.status == FriendshipStatus.accepted,
            or_(
                (Friendship.requester == a) & (Friendship.addressee == b),
                (Friendship.requester == b) & (Friendship.addressee == a),
            ),
        )
    ).first()
    return row is not None


async def send_message(session: Session, sender: User, handle: str, body: str) -> Message:
    if handle == sender.handle:
        raise MessagingError("You cannot message yourself.")
    recipient = session.get(User, handle)
    if recipient is None:
        raise MessagingError(f"No one on Groknet has the handle {handle!r}.")
    if not are_friends(session, sender.handle, handle):
        raise MessagingError(
            f"You are not friends with @{handle} yet. Send a friend request and wait for them to accept."
        )
    if not body.strip():
        raise MessagingError("Message body is empty.")

    message = Message(sender=sender.handle, recipient=handle, body=body)
    session.add(message)
    session.commit()
    session.refresh(message)

    message.delivered = await deliver(
        recipient,
        event_type="message",
        sender=sender,
        payload={"body": body},
        event_id=message.event_id,
    )
    session.add(message)
    session.commit()
    session.refresh(message)

    bus.publish(
        {
            "type": "message",
            "event_id": message.event_id,
            "sender": sender.handle,
            "recipient": handle,
            "body": body,
            "delivered": message.delivered,
        }
    )
    return message
