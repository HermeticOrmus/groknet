"""Discovery and the human-approved friendship graph (issue #4).

The sync functions change the graph. `send_friend_request` and `respond_to_friend_request`
wrap them with the async webhook delivery; those two are what the MCP tools and the REST
mirror call.
"""

from sqlmodel import Session, col, or_, select

from app.errors import GroknetError
from app.events import bus
from app.models import Friendship, FriendshipStatus, User, now
from app.webhooks import deliver


class FriendshipError(GroknetError):
    pass


def search_users(session: Session, caller: User, query: str) -> list[User]:
    stmt = select(User).where(User.handle != caller.handle)
    q = query.strip().lower()
    if q:
        stmt = stmt.where(or_(col(User.handle).contains(q), col(User.display_name).ilike(f"%{q}%")))
    return list(session.exec(stmt.order_by(User.handle)).all())


def get_user(session: Session, handle: str) -> User:
    user = session.get(User, handle.strip().lower())
    if user is None:
        raise FriendshipError(f"No one on Groknet has the handle {handle!r}.")
    return user


def find_friendship(session: Session, a: str, b: str) -> Friendship | None:
    """The single row for this pair, whichever side asked first."""
    return session.exec(
        select(Friendship).where(
            or_(
                (Friendship.requester == a) & (Friendship.addressee == b),
                (Friendship.requester == b) & (Friendship.addressee == a),
            )
        )
    ).first()


def request_friendship(
    session: Session, caller: User, handle: str
) -> tuple[Friendship, str | None]:
    """Returns (friendship, event_to_deliver) where event_to_deliver is
    'friend_request', 'friend_accepted' (cross-request), or None (no-op)."""
    other = get_user(session, handle)
    if other.handle == caller.handle:
        raise FriendshipError("You cannot send a friend request to yourself.")

    existing = find_friendship(session, caller.handle, other.handle)
    if existing is None:
        friendship = Friendship(requester=caller.handle, addressee=other.handle)
        session.add(friendship)
        session.commit()
        session.refresh(friendship)
        bus.publish({"type": "friend_request", "from": caller.handle, "to": other.handle})
        return friendship, "friend_request"

    if existing.status == FriendshipStatus.pending and existing.addressee == caller.handle:
        # They already asked us: asking back is an acceptance.
        return _accept(session, existing, caller), "friend_accepted"

    # Pending (we already asked), accepted, or declined: nothing to do.
    return existing, None


def respond(session: Session, caller: User, handle: str, accept: bool) -> Friendship:
    other = get_user(session, handle)
    friendship = find_friendship(session, caller.handle, other.handle)
    if (
        friendship is None
        or friendship.status != FriendshipStatus.pending
        or friendship.addressee != caller.handle
    ):
        raise FriendshipError(f"There is no pending friend request from {other.handle!r} to you.")
    if accept:
        return _accept(session, friendship, caller)
    friendship.status = FriendshipStatus.declined
    friendship.updated_at = now()
    session.add(friendship)
    session.commit()
    session.refresh(friendship)
    bus.publish({"type": "friend_declined", "from": caller.handle, "to": other.handle})
    return friendship


def _accept(session: Session, friendship: Friendship, caller: User) -> Friendship:
    friendship.status = FriendshipStatus.accepted
    friendship.updated_at = now()
    session.add(friendship)
    session.commit()
    session.refresh(friendship)
    bus.publish({"type": "friend_accepted", "from": caller.handle, "to": friendship.requester})
    return friendship


async def send_friend_request(session: Session, caller: User, handle: str) -> Friendship:
    """request_friendship, then tell the other bot: a new request, or an acceptance."""
    friendship, event = request_friendship(session, caller, handle)
    other_handle = (
        friendship.addressee if friendship.requester == caller.handle else friendship.requester
    )
    other = get_user(session, other_handle)
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
    return friendship


async def respond_to_friend_request(
    session: Session, caller: User, handle: str, accept: bool
) -> Friendship:
    """respond, then tell the requester's bot if accepted."""
    friendship = respond(session, caller, handle, accept)
    if accept:
        requester = get_user(session, friendship.requester)
        await deliver(
            requester,
            event_type="friend_accepted",
            sender=caller,
            payload={"message": f"{caller.display_name} accepted your request"},
        )
    return friendship
