"""The REST mirror of the MCP tools (issue #6): same services, bearer-token auth."""

import pytest
from conftest import register_args
from sqlmodel import Session, delete

from app.db import engine
from app.models import Friendship, Message, User


@pytest.fixture(autouse=True)
def _clean_tables_after_each_test():
    yield
    with Session(engine) as session:
        for table in (Message, Friendship, User):
            session.exec(delete(table))
        session.commit()


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def register(client, handle: str, **overrides) -> str:
    resp = client.post("/api/register", json=register_args(handle, **overrides))
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["handle"] == handle
    return body["groknet_token"]


def test_full_flow_over_rest(client, make_inbox) -> None:
    inboxes = {"resta": make_inbox(), "restb": make_inbox()}
    a = register(client, "resta", webhook_url=inboxes["resta"].url, profile={"job": "Founder"})
    b = register(client, "restb", display_name="Bea Rest", webhook_url=inboxes["restb"].url)

    me = client.get("/api/me", headers=bearer(a)).json()
    assert me == {
        "handle": "resta",
        "display_name": "Resta",
        "profile": {"job": "Founder"},
        "email": "resta@mail.grokbot.com",
        "webhook_url": inboxes["resta"].url,
    }

    hits = client.get("/api/search", params={"q": "bea"}, headers=bearer(a)).json()
    assert hits == [{"handle": "restb", "display_name": "Bea Rest", "profile": {}}]

    req = client.post("/api/friends/request", json={"handle": "restb"}, headers=bearer(a))
    assert req.status_code == 200, req.text
    assert req.json()["status"] == "pending" and req.json()["friendship_id"]
    assert [e["type"] for e in inboxes["restb"].events] == ["friend_request"]

    resp = client.post(
        "/api/friends/respond", json={"handle": "resta", "accept": True}, headers=bearer(b)
    )
    assert resp.json() == {"status": "accepted"}
    assert [e["type"] for e in inboxes["resta"].events] == ["friend_accepted"]

    msg = client.post("/api/messages", json={"handle": "restb", "body": "hola"}, headers=bearer(a))
    assert msg.status_code == 200, msg.text
    assert msg.json()["delivered"] is True
    event = inboxes["restb"].events[-1]
    assert event["type"] == "message"
    assert event["event_id"] == msg.json()["event_id"]
    assert event["payload"] == {"body": "hola"}
    assert inboxes["restb"].keys[-1] == "Bearer crsr_restb_secret"


@pytest.mark.parametrize("headers", [{}, {"Authorization": "Bearer nope"}, {"Authorization": "x"}])
def test_bad_or_missing_token_is_401(client, headers) -> None:
    resp = client.get("/api/me", headers=headers)
    assert resp.status_code == 401
    assert "detail" in resp.json()


def test_service_rejection_is_400_with_the_message(client) -> None:
    resp = client.post("/api/register", json=register_args("resta", email="resta@gmail.com"))
    assert resp.status_code == 400
    assert "@mail.grokbot.com" in resp.json()["detail"]


def test_messaging_a_stranger_is_400(client) -> None:
    a = register(client, "resta")
    register(client, "restb")
    resp = client.post("/api/messages", json={"handle": "restb", "body": "hi"}, headers=bearer(a))
    assert resp.status_code == 400
    assert "not friends" in resp.json()["detail"]
