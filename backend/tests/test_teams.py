import asyncio
import json
from uuid import uuid4

import pytest
from conftest import ToolError, register_args
from sqlmodel import Session, select

from app.db import engine
from app.events import bus
from app.models import Friendship, FriendshipStatus, Message, TeamMember


@pytest.fixture
def network(mcp, make_inbox):
    handles = [f"{role}_{uuid4().hex[:8]}" for role in ("owner", "first", "second", "outside")]
    inboxes = {handle: make_inbox() for handle in handles}
    tokens = {
        handle: mcp.call("register", **register_args(handle, webhook_url=inboxes[handle].url))[
            "groknet_token"
        ]
        for handle in handles
    }
    with Session(engine) as session:
        for handle in handles[1:3]:
            session.add(
                Friendship(
                    requester=handle,
                    addressee=handles[0],
                    status=FriendshipStatus.accepted,
                )
            )
        session.commit()
    team_id = mcp.call("create_team", groknet_token=tokens[handles[0]], name="Demo team")["team_id"]
    return handles, inboxes, tokens, team_id


def join(mcp, network, count=2):
    handles, _, tokens, team_id = network
    for handle in handles[1 : count + 1]:
        mcp.call("add_to_team", groknet_token=tokens[handles[0]], team_id=team_id, handle=handle)


def test_creator_membership_and_idempotent_add(mcp, client, network):
    handles, _, tokens, team_id = network
    initial = next(team for team in client.get("/api/teams").json() if team["id"] == team_id)
    assert initial["members"] == [handles[0]]
    assert initial["member_details"][0]["handle"] == handles[0]
    join(mcp, network)
    result = mcp.call(
        "add_to_team", groknet_token=tokens[handles[0]], team_id=team_id, handle=handles[1]
    )
    assert sorted(result["members"]) == sorted(handles[:3])
    with Session(engine) as session:
        assert len(session.exec(select(TeamMember).where(TeamMember.team_id == team_id)).all()) == 3


def test_membership_and_accepted_friendship_are_required(mcp, network):
    handles, _, tokens, team_id = network
    for caller, target, expected in (
        (handles[0], handles[3], "accepted friendship"),
        (handles[3], handles[1], "team member"),
    ):
        with pytest.raises(ToolError, match=expected):
            mcp.call("add_to_team", groknet_token=tokens[caller], team_id=team_id, handle=target)
    with pytest.raises(ToolError, match="team member"):
        mcp.call("send_team_message", groknet_token=tokens[handles[3]], team_id=team_id, body="Hi")
    with pytest.raises(ToolError, match="Unknown groknet_token"):
        mcp.call("create_team", groknet_token="invalid", name="Nope")


def test_invalid_mentions_and_empty_inputs_have_no_delivery_side_effect(mcp, network):
    handles, inboxes, tokens, team_id = network
    join(mcp, network)
    for body, mentions in (("Hi", [handles[3]]), ("Hi", ["@" + handles[1]]), ("  ", [])):
        with pytest.raises(ToolError):
            mcp.call(
                "send_team_message",
                groknet_token=tokens[handles[0]],
                team_id=team_id,
                body=body,
                mentions=mentions,
            )
    with Session(engine) as session:
        assert session.exec(select(Message).where(Message.team_id == team_id)).all() == []
    assert all(inbox.events == [] for inbox in inboxes.values())
    with pytest.raises(ToolError, match="name"):
        mcp.call("create_team", groknet_token=tokens[handles[0]], name=" ")


def test_fanout_one_message_sender_excluded_and_receipts_survive_reads(mcp, client, network):
    handles, inboxes, tokens, team_id = network
    with Session(engine) as session:
        session.add(
            Friendship(requester=handles[0], addressee=handles[3], status=FriendshipStatus.accepted)
        )
        session.commit()
    join(mcp, network, count=3)
    feed = bus.subscribe()
    try:
        result = mcp.call(
            "send_team_message",
            groknet_token=tokens[handles[0]],
            team_id=team_id,
            body=f"Hello @{handles[1]}",
            mentions=[handles[1], handles[1]],
        )
        events = []
        while not feed.empty():
            events.append(json.loads(feed.get_nowait()))
    finally:
        bus.unsubscribe(feed)
    assert sorted(result["delivered_to"]) == sorted(handles[1:])
    assert inboxes[handles[0]].events == []
    for handle in handles[1:]:
        [event] = inboxes[handle].events
        assert event["event_id"] == result["event_id"]
        assert event["payload"] == {
            "body": f"Hello @{handles[1]}",
            "team": {"id": team_id, "name": "Demo team"},
            "mentions": [handles[1]],
        }
        assert inboxes[handle].keys == [f"Bearer crsr_{handle}_secret"]
    [initial] = [event for event in events if event["type"] == "team_message"]
    assert initial["team_id"] == team_id
    assert all(receipt["status"] == "pending" for receipt in initial["deliveries"])
    receipts = [event for event in events if event["type"] == "delivery"]
    assert len(receipts) == 3
    assert {event["to"] for event in receipts} == set(handles[1:])
    assert all(event["team_id"] == team_id and event["revision"] == 2 for event in receipts)
    for _ in range(2):
        [stored] = client.get(f"/api/teams/{team_id}/messages").json()
        assert stored["event_id"] == result["event_id"]
        assert stored["mentions"] == [handles[1]]
        assert all(r["status"] == "delivered" and r["revision"] == 2 for r in stored["deliveries"])
    rendered = json.dumps(events) + json.dumps(stored)
    assert "groknet_token" not in rendered and "webhook_key" not in rendered
    assert "crsr_" not in rendered and "automations/webhook" not in rendered


def test_partial_failure_does_not_erase_success(mcp, client, network):
    handles, inboxes, tokens, team_id = network
    join(mcp, network)
    inboxes[handles[2]].respond_with = [401]
    result = mcp.call(
        "send_team_message", groknet_token=tokens[handles[0]], team_id=team_id, body="Hello"
    )
    assert result["delivered_to"] == [handles[1]]
    [stored] = client.get(f"/api/teams/{team_id}/messages").json()
    assert {r["recipient"]: r["status"] for r in stored["deliveries"]} == {
        handles[1]: "delivered",
        handles[2]: "failed",
    }
    assert len(inboxes[handles[2]].keys) == 1
    assert stored["delivered"] is False


def test_fanout_really_runs_concurrently(mcp, network, monkeypatch):
    from app import teams

    handles, _, tokens, team_id = network
    join(mcp, network)
    started = set()
    all_started = asyncio.Event()

    async def sender(recipient, **kwargs):
        started.add(recipient.handle)
        if len(started) == 2:
            all_started.set()
        await asyncio.wait_for(all_started.wait(), timeout=1)
        kwargs["on_result"]({"ok": True, "status": 200})
        return True

    monkeypatch.setattr(teams, "deliver", sender)
    result = mcp.call(
        "send_team_message", groknet_token=tokens[handles[0]], team_id=team_id, body="Concurrent"
    )
    assert set(result["delivered_to"]) == set(handles[1:3])


def test_transport_exception_is_unknown_and_other_recipient_completes(
    mcp, client, network, monkeypatch
):
    from app import teams

    handles, _, tokens, team_id = network
    join(mcp, network)

    async def sender(recipient, **kwargs):
        if recipient.handle == handles[1]:
            raise RuntimeError("private webhook_key crsr_secret must not reach history")
        kwargs["on_result"]({"ok": True, "status": 200})
        return True

    monkeypatch.setattr(teams, "deliver", sender)
    result = mcp.call(
        "send_team_message", groknet_token=tokens[handles[0]], team_id=team_id, body="Hello"
    )
    assert result["delivered_to"] == [handles[2]]
    response = client.get(f"/api/teams/{team_id}/messages")
    [stored] = response.json()
    assert {r["recipient"]: r["status"] for r in stored["deliveries"]} == {
        handles[1]: "unknown",
        handles[2]: "delivered",
    }
    assert "crsr_secret" not in response.text


def test_rest_and_mcp_share_team_rules(client, mcp, network):
    handles, _, tokens, _ = network
    assert client.post("/api/teams", json={"name": "REST team"}).status_code == 401
    assert (
        client.post(
            "/api/teams", headers={"Authorization": "Bearer invalid"}, json={"name": "No"}
        ).status_code
        == 401
    )
    headers = {"Authorization": f"Bearer {tokens[handles[0]]}"}
    response = client.post("/api/teams", headers=headers, json={"name": "REST team"})
    assert response.status_code == 200
    team_id = response.json()["team_id"]
    assert client.post(
        f"/api/teams/{team_id}/members", headers=headers, json={"handle": handles[1]}
    ).json() == {"members": sorted(handles[:2])}
    outsider = {"Authorization": f"Bearer {tokens[handles[3]]}"}
    assert (
        client.post(
            f"/api/teams/{team_id}/messages", headers=outsider, json={"body": "No"}
        ).status_code
        == 403
    )
    sent = client.post(
        f"/api/teams/{team_id}/messages",
        headers=headers,
        json={"body": "REST says hello", "mentions": [handles[1]]},
    )
    assert sent.status_code == 200
    assert sent.json()["delivered_to"] == [handles[1]]
    [message] = client.get(f"/api/teams/{team_id}/messages?limit=1").json()
    assert message["event_id"] == sent.json()["event_id"]
    assert client.get(f"/api/teams/{team_id}/messages?limit=0").status_code == 422
    assert client.get("/api/teams/missing/messages").status_code == 404
