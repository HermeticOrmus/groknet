import pytest
from conftest import ToolError, register_args
from sqlmodel import Session

from app.db import engine
from app.models import Friendship, FriendshipStatus


def make_friends(a: str, b: str) -> None:
    """Test setup only: the friendship tools are built in #4, so insert the accepted row."""
    with Session(engine) as session:
        session.add(Friendship(requester=a, addressee=b, status=FriendshipStatus.accepted))
        session.commit()


@pytest.fixture
def two_friends(mcp, make_inbox):
    """tomas and alejandro, friends, each with their own inbox. Returns (tokens, inboxes)."""
    inboxes = {"tomas": make_inbox(), "alejandro": make_inbox()}
    tokens = {
        h: mcp.call("register", **register_args(h, webhook_url=inboxes[h].url))["groknet_token"]
        for h in inboxes
    }
    make_friends("tomas", "alejandro")
    return tokens, inboxes


def test_send_message_lands_in_the_friends_inbox(mcp, two_friends) -> None:
    tokens, inboxes = two_friends

    result = mcp.call("send_message", groknet_token=tokens["tomas"], handle="alejandro", body="hey")

    assert result["delivered"] is True
    [event] = inboxes["alejandro"].events
    assert event == {
        "event_id": result["event_id"],
        "type": "message",
        "from": {"handle": "tomas", "display_name": "Tomas"},
        "payload": {"body": "hey"},
    }
    assert inboxes["alejandro"].keys == ["Bearer crsr_alejandro_secret"]
    assert inboxes["tomas"].events == []


def test_send_message_requires_an_accepted_friendship(mcp, make_inbox) -> None:
    stranger = make_inbox()
    juan = mcp.call("register", **register_args("juan", webhook_url=make_inbox().url))
    mcp.call("register", **register_args("stranger", webhook_url=stranger.url))

    with pytest.raises(ToolError, match="not friends"):
        mcp.call(
            "send_message", groknet_token=juan["groknet_token"], handle="stranger", body="psst"
        )

    assert stranger.events == []


def test_send_message_retries_a_503_and_then_succeeds(mcp, two_friends, monkeypatch) -> None:
    import app.webhooks

    monkeypatch.setattr(app.webhooks, "RETRY_BACKOFF_S", (0, 0, 0))
    tokens, inboxes = two_friends
    inboxes["alejandro"].respond_with = [503, 503]

    result = mcp.call(
        "send_message", groknet_token=tokens["tomas"], handle="alejandro", body="again"
    )

    assert result["delivered"] is True
    assert len(inboxes["alejandro"].keys) == 3  # two 503s, then the accepted attempt
    assert [e["payload"]["body"] for e in inboxes["alejandro"].events] == ["again"]


def test_send_message_does_not_retry_a_bad_key_and_keeps_the_message(
    mcp, client, two_friends, monkeypatch
) -> None:
    import app.webhooks

    monkeypatch.setattr(app.webhooks, "RETRY_BACKOFF_S", (0, 0, 0))
    tokens, inboxes = two_friends
    inboxes["alejandro"].respond_with = [401]

    result = mcp.call(
        "send_message", groknet_token=tokens["tomas"], handle="alejandro", body="lost?"
    )

    assert result["delivered"] is False
    assert len(inboxes["alejandro"].keys) == 1
    stored = {m["event_id"]: m for m in client.get("/api/messages").json()}
    assert stored[result["event_id"]]["body"] == "lost?"
    assert stored[result["event_id"]]["delivered"] is False


def test_dashboard_bus_sees_the_message_and_its_delivery(mcp, two_friends) -> None:
    import json

    from app.events import bus

    tokens, _ = two_friends
    feed = bus.subscribe()
    try:
        result = mcp.call(
            "send_message", groknet_token=tokens["tomas"], handle="alejandro", body="hi"
        )
        events = []
        while not feed.empty():
            events.append(json.loads(feed.get_nowait()))
    finally:
        bus.unsubscribe(feed)

    by_type = {e["type"]: e for e in events}
    assert by_type["delivery"] == {
        "type": "delivery",
        "event_id": result["event_id"],
        "event_type": "message",
        "to": "alejandro",
        "ok": True,
        "status": 200,
    }
    assert by_type["message"]["body"] == "hi"
    assert "webhook_key" not in json.dumps(events) and "crsr_" not in json.dumps(events)
