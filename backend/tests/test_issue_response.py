"""Answering an assignment: the assignee accepts or declines, the assigner hears back."""

import json
from uuid import uuid4

import pytest
from conftest import ToolError, register_args
from sqlmodel import Session, delete

from app.db import engine
from app.events import bus
from app.models import Artifact, Friendship, FriendshipStatus, Issue, Project


@pytest.fixture(autouse=True)
def _clean():
    yield
    with Session(engine) as session:
        for table in (Artifact, Issue, Project):
            session.exec(delete(table))
        session.commit()


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def crew(mcp, make_inbox):
    """owner, first, second on one team; each bot has its own inbox."""
    suffix = uuid4().hex[:6]
    roles = ("owner", "first", "second")
    h = {role: f"resp_{role[:5]}_{suffix}" for role in roles}
    inbox = {role: make_inbox() for role in roles}
    tok = {
        role: mcp.call("register", **register_args(h[role], webhook_url=inbox[role].url))[
            "groknet_token"
        ]
        for role in roles
    }
    with Session(engine) as session:
        for role in ("first", "second"):
            session.add(
                Friendship(
                    requester=h[role], addressee=h["owner"], status=FriendshipStatus.accepted
                )
            )
        session.commit()
    team_id = mcp.call("create_team", groknet_token=tok["owner"], name="Resp team")["team_id"]
    for role in ("first", "second"):
        mcp.call("add_to_team", groknet_token=tok["owner"], team_id=team_id, handle=h[role])
    return {"h": h, "inbox": inbox, "tok": tok, "team_id": team_id}


def setup_issue(client, crew, assignee_role="first", by="owner"):
    auth = bearer(crew["tok"][by])
    body = {"team_id": crew["team_id"], "name": "Launch"}
    pid = client.post("/api/projects", json=body, headers=auth).json()["id"]
    issue = {"title": "Fix login"}
    if assignee_role:
        issue["assignee"] = crew["h"][assignee_role]
    resp = client.post(f"/api/projects/{pid}/issues", json=issue, headers=auth)
    assert resp.status_code == 201, resp.text
    return pid, resp.json()


def respond(client, crew, role, iid, **body):
    return client.post(f"/api/issues/{iid}/respond", json=body, headers=bearer(crew["tok"][role]))


def responses(crew, role) -> list[dict]:
    return [e for e in crew["inbox"][role].events if e["type"] == "issue_response"]


def drain(q) -> list[dict]:
    out = []
    while not q.empty():
        out.append(json.loads(q.get_nowait()))
    return out


def test_new_assignment_is_pending_and_unassigned_is_null(client, crew):
    _, issue = setup_issue(client, crew)
    assert issue["assignment_status"] == "pending"
    assert issue["assignment_comment"] is None
    assert issue["assigned_by"] == crew["h"]["owner"]
    _, bare = setup_issue(client, crew, assignee_role=None)
    assert bare["assignment_status"] is None and bare["assigned_by"] is None


def test_assignee_accepts_with_comment_and_creator_hears_back(client, crew):
    owner, first = crew["h"]["owner"], crew["h"]["first"]
    pid, issue = setup_issue(client, crew)
    iid = issue["id"]
    q = bus.subscribe()
    try:
        resp = respond(client, crew, "first", iid, accept=True, comment="  On it tomorrow ")
        events = drain(q)
    finally:
        bus.unsubscribe(q)
    assert resp.status_code == 200, resp.text
    answered = resp.json()
    assert answered["assignment_status"] == "accepted"
    assert answered["assignment_comment"] == "On it tomorrow"
    assert answered["updated_at"] > issue["updated_at"]

    auth = bearer(crew["tok"]["second"])
    (seen,) = client.get(f"/api/projects/{pid}", headers=auth).json()["issues"]
    assert seen == answered
    assert client.get(f"/api/projects/{pid}/issues", headers=auth).json() == [answered]

    (hook,) = responses(crew, "owner")
    assert crew["inbox"]["owner"].keys[-1] == f"Bearer crsr_{owner}_secret"
    assert hook["from"]["handle"] == first
    assert hook["payload"] == {
        "issue": {
            "id": iid,
            "title": "Fix login",
            "status": "open",
            "assignment_status": "accepted",
            "comment": "On it tomorrow",
        },
        "project": {"id": pid, "name": "Launch"},
        "team": {"id": crew["team_id"], "name": "Resp team"},
        "message": f"{first.capitalize()} accepted 'Fix login': On it tomorrow",
    }
    assert responses(crew, "first") == []

    (event,) = [e for e in events if e["type"] == "issue_response"]
    assert event == {
        "type": "issue_response",
        "issue_id": iid,
        "project_id": pid,
        "team_id": crew["team_id"],
        "by": first,
        "assignment_status": "accepted",
        "comment": "On it tomorrow",
    }
    deliveries = [e for e in events if e["type"] == "delivery"]
    assert [(d["event_type"], d["to"], d["ok"]) for d in deliveries] == [
        ("issue_response", owner, True)
    ]
    blob = json.dumps(events)
    assert "crsr_" not in blob and "groknet_token" not in blob


def test_decline_without_comment(client, crew):
    first = crew["h"]["first"]
    _, issue = setup_issue(client, crew)
    resp = respond(client, crew, "first", issue["id"], accept=False)
    assert resp.status_code == 200, resp.text
    assert resp.json()["assignment_status"] == "declined"
    assert resp.json()["assignment_comment"] is None
    (hook,) = responses(crew, "owner")
    assert hook["payload"]["message"] == f"{first.capitalize()} declined 'Fix login'"
    assert hook["payload"]["issue"]["comment"] is None


def test_assigner_and_creator_both_hear_back_once(client, crew):
    # owner creates it unassigned, second assigns first: both get the answer, once each.
    _, issue = setup_issue(client, crew, assignee_role=None)
    iid = issue["id"]
    resp = client.patch(
        f"/api/issues/{iid}",
        json={"assignee": crew["h"]["first"]},
        headers=bearer(crew["tok"]["second"]),
    )
    assert resp.json()["assigned_by"] == crew["h"]["second"]
    assert respond(client, crew, "first", iid, accept=True).status_code == 200
    assert len(responses(crew, "owner")) == 1
    assert len(responses(crew, "second")) == 1


def test_only_the_assignee_may_respond(client, crew):
    _, issue = setup_issue(client, crew)
    for role in ("owner", "second"):
        resp = respond(client, crew, role, issue["id"], accept=True)
        assert resp.status_code == 403 and "assignee" in resp.json()["detail"]
    _, bare = setup_issue(client, crew, assignee_role=None)
    assert respond(client, crew, "first", bare["id"], accept=True).status_code == 403
    assert responses(crew, "owner") == []


def test_comment_length_is_limited(client, crew):
    _, issue = setup_issue(client, crew)
    resp = respond(client, crew, "first", issue["id"], accept=True, comment="x" * 2001)
    assert resp.status_code == 400
    ok = respond(client, crew, "first", issue["id"], accept=True, comment="x" * 2000)
    assert ok.status_code == 200


def test_reassigning_resets_the_answer(client, crew):
    owner_auth = bearer(crew["tok"]["owner"])
    _, issue = setup_issue(client, crew)
    iid = issue["id"]
    respond(client, crew, "first", iid, accept=False, comment="No time")
    # The same assignee again is not a change: the answer stands.
    same = client.patch(
        f"/api/issues/{iid}", json={"assignee": crew["h"]["first"]}, headers=owner_auth
    )
    assert same.json()["assignment_status"] == "declined"
    assert same.json()["assignment_comment"] == "No time"
    q = bus.subscribe()
    try:
        moved = client.patch(
            f"/api/issues/{iid}", json={"assignee": crew["h"]["second"]}, headers=owner_auth
        ).json()
        events = drain(q)
    finally:
        bus.unsubscribe(q)
    assert moved["assignment_status"] == "pending" and moved["assignment_comment"] is None
    (updated,) = [e for e in events if e["type"] == "issue_updated"]
    assert updated["assignment_status"] == "pending" and updated["assignment_comment"] is None
    cleared = client.patch(f"/api/issues/{iid}", json={"assignee": None}, headers=owner_auth).json()
    assert cleared["assignment_status"] is None and cleared["assigned_by"] is None


def test_unknown_issue_is_404(client, crew):
    assert respond(client, crew, "first", "nope", accept=True).status_code == 404


def test_mcp_tool(mcp, client, crew):
    assert "respond_to_issue" in mcp.list_tools()
    _, issue = setup_issue(client, crew)
    result = mcp.call(
        "respond_to_issue",
        groknet_token=crew["tok"]["first"],
        issue_id=issue["id"],
        accept=False,
        comment="Swamped",
    )
    assert result == {
        "issue_id": issue["id"],
        "assignment_status": "declined",
        "comment": "Swamped",
    }
    with pytest.raises(ToolError, match="assignee"):
        mcp.call(
            "respond_to_issue",
            groknet_token=crew["tok"]["second"],
            issue_id=issue["id"],
            accept=True,
        )
    with pytest.raises(ToolError, match="not found"):
        mcp.call("respond_to_issue", groknet_token=crew["tok"]["first"], issue_id="x", accept=True)
