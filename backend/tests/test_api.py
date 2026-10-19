import json

import pytest
from conftest import register_args
from sqlmodel import Session, delete

from app.db import engine
from app.models import Friendship, Message, Team, TeamMember, User


@pytest.fixture(autouse=True)
def _clean_tables_after_each_test():
    """These tests seed the shared test database; leave it empty for the other modules."""
    yield
    with Session(engine) as session:
        for table in (Message, TeamMember, Team, Friendship, User):
            session.exec(delete(table))
        session.commit()


@pytest.fixture
def dev_mode(monkeypatch):
    from app import config

    monkeypatch.setattr(config, "DEV_MODE", True)


def test_users_carry_email_and_profile_but_never_credentials(mcp, client) -> None:
    mcp.call("register", **register_args("api-user"))

    users = {u["handle"]: u for u in client.get("/api/users").json()}
    assert users["api-user"]["email"] == "api-user@mail.grokbot.com"
    assert isinstance(users["api-user"]["profile"], dict)
    assert set(users["api-user"]) == {"handle", "display_name", "email", "profile", "created_at"}


def test_dev_endpoints_are_hidden_without_dev_mode(client) -> None:
    assert client.post("/api/dev/seed").status_code == 404
    assert client.post("/api/dev/emit", json={"type": "message"}).status_code == 404


def test_seed_loads_the_demo_dataset_and_is_idempotent(client, dev_mode) -> None:
    first = client.post("/api/dev/seed").json()
    second = client.post("/api/dev/seed").json()

    expected = {"users": 4, "friendships": 3, "messages": 10, "teams": 1, "team_members": 3}
    assert first == second == expected
    users = {u["handle"]: u for u in client.get("/api/users").json()}
    assert set(users) == {"tomas", "alejandro", "juan", "demo-bot"}
    statuses = sorted(f["status"] for f in client.get("/api/friendships").json())
    assert statuses == ["accepted", "accepted", "pending"]
    teams = client.get("/api/teams").json()
    assert teams[0]["name"] == "Groknet core"
    assert teams[0]["members"] == ["alejandro", "juan", "tomas"]


def test_messages_support_limit_and_handle_filter(client, dev_mode) -> None:
    client.post("/api/dev/seed")

    assert len(client.get("/api/messages").json()) == 10
    assert len(client.get("/api/messages?limit=3").json()) == 3
    juan = client.get("/api/messages?handle=juan").json()
    assert len(juan) == 5
    assert all("juan" in (m["sender"], m["recipient"]) for m in juan)
    newest_first = [m["created_at"] for m in client.get("/api/messages").json()]
    assert newest_first == sorted(newest_first, reverse=True)
    assert client.get("/api/messages?limit=0").status_code == 422


def test_emit_publishes_a_fake_event_on_the_bus(client, dev_mode) -> None:
    from app.events import bus

    inbox = bus.subscribe()
    try:
        resp = client.post("/api/dev/emit", json={"type": "delivery", "ok": False, "status": 503})
        event = json.loads(inbox.get_nowait())
    finally:
        bus.unsubscribe(inbox)

    assert resp.status_code == 200
    assert event["type"] == "delivery"
    assert event["ok"] is False and event["status"] == 503
    assert event["to"] == "tomas"  # default filled from the fake-event template
    assert client.post("/api/dev/emit", json={}).status_code == 422
