"""Teams (issue #15): create_team, add_to_team, send_team_message with fan-out and mentions."""

import json

import pytest
from conftest import ToolError, register_args
from sqlmodel import Session, delete

from app.db import engine
from app.models import Friendship, FriendshipStatus, Message, Team, TeamMember, User

DEAD_INBOX = "http://127.0.0.1:9/dead"


@pytest.fixture(autouse=True)
def _clean_tables_after_each_test():
    yield
    with Session(engine) as session:
        for table in (Message, TeamMember, Team, Friendship, User):
            session.exec(delete(table))
        session.commit()


def make_friends(a: str, b: str) -> None:
    with Session(engine) as session:
        session.add(Friendship(requester=a, addressee=b, status=FriendshipStatus.accepted))
        session.commit()


def register(mcp, handle: str, url: str = DEAD_INBOX) -> str:
    return mcp.call("register", **register_args(handle, webhook_url=url))["groknet_token"]


@pytest.fixture
def squad(mcp, make_inbox):
    """team_a (creator), team_b, team_c: a is friends with b and c; all three in one team."""
    inboxes = {h: make_inbox() for h in ("team_a", "team_b", "team_c")}
    tokens = {h: register(mcp, h, inboxes[h].url) for h in inboxes}
    make_friends("team_a", "team_b")
    make_friends("team_c", "team_a")
    team = mcp.call("create_team", groknet_token=tokens["team_a"], name="Core")
    for h in ("team_b", "team_c"):
        mcp.call("add_to_team", groknet_token=tokens["team_a"], team_id=team["team_id"], handle=h)
    return tokens, inboxes, team["team_id"]


def test_create_team_makes_the_creator_the_first_member(mcp) -> None:
    token = register(mcp, "team_a")

    team = mcp.call("create_team", groknet_token=token, name="Core")

    assert team["team_id"]
    assert team["name"] == "Core"
    assert team["members"] == ["team_a"]


@pytest.mark.parametrize("name", ["", "   ", "x" * 65])
def test_create_team_rejects_bad_names(mcp, name) -> None:
    token = register(mcp, "team_a")
    with pytest.raises(ToolError, match="name"):
        mcp.call("create_team", groknet_token=token, name=name)


def test_add_to_team_requires_friendship_and_is_idempotent(mcp) -> None:
    a = register(mcp, "team_a")
    register(mcp, "team_b")
    register(mcp, "team_x")
    make_friends("team_a", "team_b")
    team_id = mcp.call("create_team", groknet_token=a, name="Core")["team_id"]

    first = mcp.call("add_to_team", groknet_token=a, team_id=team_id, handle="team_b")
    again = mcp.call("add_to_team", groknet_token=a, team_id=team_id, handle="team_b")

    assert first == again == {"team_id": team_id, "members": ["team_a", "team_b"]}
    with pytest.raises(ToolError, match="not friends"):
        mcp.call("add_to_team", groknet_token=a, team_id=team_id, handle="team_x")


def test_pending_friendship_is_not_enough_to_add(mcp) -> None:
    a = register(mcp, "team_a")
    register(mcp, "team_b")
    with Session(engine) as session:
        session.add(Friendship(requester="team_a", addressee="team_b"))
        session.commit()
    team_id = mcp.call("create_team", groknet_token=a, name="Core")["team_id"]

    with pytest.raises(ToolError, match="not friends"):
        mcp.call("add_to_team", groknet_token=a, team_id=team_id, handle="team_b")


def test_only_members_can_add(mcp) -> None:
    a = register(mcp, "team_a")
    register(mcp, "team_b")
    x = register(mcp, "team_x")
    make_friends("team_x", "team_b")
    team_id = mcp.call("create_team", groknet_token=a, name="Core")["team_id"]

    with pytest.raises(ToolError, match="not a member"):
        mcp.call("add_to_team", groknet_token=x, team_id=team_id, handle="team_b")


def test_unknown_team_or_handle_is_rejected(mcp) -> None:
    a = register(mcp, "team_a")
    team_id = mcp.call("create_team", groknet_token=a, name="Core")["team_id"]

    with pytest.raises(ToolError, match="No team"):
        mcp.call("add_to_team", groknet_token=a, team_id="nope", handle="team_a")
    with pytest.raises(ToolError, match="team_ghost"):
        mcp.call("add_to_team", groknet_token=a, team_id=team_id, handle="team_ghost")


def test_team_message_fans_out_to_every_other_member(mcp, squad) -> None:
    tokens, inboxes, team_id = squad

    result = mcp.call(
        "send_team_message",
        groknet_token=tokens["team_a"],
        team_id=team_id,
        body="standup",
        mentions=["team_c"],
    )

    assert result["delivered_to"] == ["team_b", "team_c"]
    assert result["failed"] == []
    assert inboxes["team_a"].events == []
    for h in ("team_b", "team_c"):
        [event] = inboxes[h].events
        assert event == {
            "event_id": result["event_id"],
            "type": "team_message",
            "from": {"handle": "team_a", "display_name": "Team_a"},
            "payload": {
                "body": "standup",
                "team": {"id": team_id, "name": "Core"},
                "mentions": ["team_c"],
            },
        }
        assert inboxes[h].keys == [f"Bearer crsr_{h}_secret"]


def test_team_message_is_one_stored_row(mcp, client, squad) -> None:
    tokens, _, team_id = squad

    result = mcp.call(
        "send_team_message",
        groknet_token=tokens["team_b"],
        team_id=team_id,
        body="hi all",
        mentions=["team_a", "team_c"],
    )

    rows = [m for m in client.get("/api/messages").json() if m["team_id"] == team_id]
    assert len(rows) == 1
    [row] = rows
    assert row["event_id"] == result["event_id"]
    assert row["sender"] == "team_b" and row["recipient"] is None
    assert row["mentions"] == "team_a,team_c"
    assert row["delivered"] is True


def test_a_503_then_200_member_counts_as_delivered(mcp, squad) -> None:
    tokens, inboxes, team_id = squad
    inboxes["team_b"].respond_with = [503]
    inboxes["team_c"].respond_with = [401]

    result = mcp.call(
        "send_team_message", groknet_token=tokens["team_a"], team_id=team_id, body="retry"
    )

    assert result["delivered_to"] == ["team_b"]
    assert result["failed"] == ["team_c"]
    assert len(inboxes["team_b"].keys) == 2
    assert inboxes["team_b"].events[0]["payload"]["mentions"] == []


def test_non_member_cannot_send(mcp, squad) -> None:
    _, inboxes, team_id = squad
    outsider = register(mcp, "team_x")

    with pytest.raises(ToolError, match="not a member"):
        mcp.call("send_team_message", groknet_token=outsider, team_id=team_id, body="hey")
    assert all(i.events == [] for i in inboxes.values())


def test_mentions_must_be_members_and_body_not_empty(mcp, squad) -> None:
    tokens, inboxes, team_id = squad
    register(mcp, "team_x")

    with pytest.raises(ToolError, match="team_x"):
        mcp.call(
            "send_team_message",
            groknet_token=tokens["team_a"],
            team_id=team_id,
            body="hey",
            mentions=["team_x"],
        )
    with pytest.raises(ToolError, match="empty"):
        mcp.call("send_team_message", groknet_token=tokens["team_a"], team_id=team_id, body=" ")
    assert all(i.events == [] for i in inboxes.values())


def test_bus_sees_team_events_without_credentials(mcp, make_inbox) -> None:
    from app.events import bus

    a = register(mcp, "team_a")
    register(mcp, "team_b", make_inbox().url)
    make_friends("team_a", "team_b")
    feed = bus.subscribe()
    try:
        team_id = mcp.call("create_team", groknet_token=a, name="Core")["team_id"]
        mcp.call("add_to_team", groknet_token=a, team_id=team_id, handle="team_b")
        result = mcp.call(
            "send_team_message",
            groknet_token=a,
            team_id=team_id,
            body="yo",
            mentions=["team_b"],
        )
        events = []
        while not feed.empty():
            events.append(json.loads(feed.get_nowait()))
    finally:
        bus.unsubscribe(feed)

    by_type = {e["type"]: e for e in events}
    team = {"id": team_id, "name": "Core"}
    assert by_type["team_created"] == {"type": "team_created", "team": team, "by": "team_a"}
    assert by_type["team_member_added"] == {
        "type": "team_member_added",
        "team": team,
        "by": "team_a",
        "handle": "team_b",
    }
    assert by_type["team_message"] == {
        "type": "team_message",
        "event_id": result["event_id"],
        "from": "team_a",
        "team": team,
        "body": "yo",
        "mentions": ["team_b"],
        "delivered_to": ["team_b"],
        "failed": [],
    }
    assert by_type["delivery"]["event_type"] == "team_message"
    assert by_type["delivery"]["event_id"] == result["event_id"]
    dump = json.dumps(events)
    assert "crsr_" not in dump and "groknet_token" not in dump


def test_read_api_lists_teams_and_team_messages(mcp, client, squad) -> None:
    tokens, _, team_id = squad
    first = mcp.call("send_team_message", groknet_token=tokens["team_a"], team_id=team_id, body="1")
    second = mcp.call(
        "send_team_message", groknet_token=tokens["team_b"], team_id=team_id, body="2"
    )

    [team] = [t for t in client.get("/api/teams").json() if t["id"] == team_id]
    assert set(team) == {"id", "name", "created_by", "created_at", "members"}
    assert team["name"] == "Core" and team["created_by"] == "team_a"
    assert team["members"] == ["team_a", "team_b", "team_c"]

    msgs = client.get(f"/api/teams/{team_id}/messages").json()
    assert [m["event_id"] for m in msgs] == [second["event_id"], first["event_id"]]
    assert all(m["team_id"] == team_id for m in msgs)
    assert client.get("/api/teams/nope/messages").status_code == 404


def test_teams_over_rest(client, make_inbox) -> None:
    inbox = make_inbox()
    a = client.post("/api/register", json=register_args("team_a")).json()["groknet_token"]
    client.post("/api/register", json=register_args("team_b", webhook_url=inbox.url))
    make_friends("team_a", "team_b")
    auth = {"Authorization": f"Bearer {a}"}

    created = client.post("/api/teams", json={"name": "Core"}, headers=auth)
    assert created.status_code == 200, created.text
    team_id = created.json()["team_id"]
    added = client.post(f"/api/teams/{team_id}/members", json={"handle": "team_b"}, headers=auth)
    assert added.json() == {"team_id": team_id, "members": ["team_a", "team_b"]}
    sent = client.post(
        f"/api/teams/{team_id}/messages",
        json={"body": "rest", "mentions": ["team_b"]},
        headers=auth,
    )
    assert sent.status_code == 200, sent.text
    assert sent.json()["delivered_to"] == ["team_b"]
    assert inbox.events[-1]["event_id"] == sent.json()["event_id"]

    bad = client.post(f"/api/teams/{team_id}/messages", json={"body": ""}, headers=auth)
    assert bad.status_code == 400 and "empty" in bad.json()["detail"]
    assert client.post("/api/teams", json={"name": "x"}).status_code == 401
