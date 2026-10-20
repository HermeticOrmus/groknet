"""Projects, issues and artifacts (issue #32): REST with token or cookie, MCP tools, webhooks."""

import json
from uuid import uuid4

import pytest
from conftest import NO_AUTH, ToolError, register_args
from sqlmodel import Session, delete

from app import config
from app.db import engine
from app.events import bus
from app.models import Artifact, Friendship, FriendshipStatus, Issue, LoginCode, Project


@pytest.fixture(autouse=True)
def _clean(client, monkeypatch):
    # The TestClient talks plain http://testserver, which would drop a Secure cookie.
    monkeypatch.setattr(config, "PUBLIC_BASE_URL", "http://testserver")
    client.cookies.clear()
    yield
    client.cookies.clear()
    with Session(engine) as session:
        for table in (Artifact, Issue, Project, LoginCode):
            session.exec(delete(table))
        session.commit()


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def crew(mcp, make_inbox):
    """owner + first + second on one team, outsider not on it. Each bot has its own inbox."""
    suffix = uuid4().hex[:6]
    roles = ("owner", "first", "second", "outsider")
    handles = {role: f"proj_{role[:5]}_{suffix}" for role in roles}
    inboxes = {role: make_inbox() for role in roles}
    tokens = {
        role: mcp.call("register", **register_args(handles[role], webhook_url=inboxes[role].url))[
            "groknet_token"
        ]
        for role in roles
    }
    with Session(engine) as session:
        for role in ("first", "second", "outsider"):
            session.add(
                Friendship(
                    requester=handles[role],
                    addressee=handles["owner"],
                    status=FriendshipStatus.accepted,
                )
            )
        session.commit()
    team_id = mcp.call("create_team", groknet_token=tokens["owner"], name="Proj team")["team_id"]
    for role in ("first", "second"):
        mcp.call(
            "add_to_team", groknet_token=tokens["owner"], team_id=team_id, handle=handles[role]
        )
    return {"h": handles, "inbox": inboxes, "tok": tokens, "team_id": team_id}


def login_cookie(client, crew, role: str) -> dict[str, str]:
    """Real dashboard login: the code arrives in the bot's inbox. Returns a Cookie header."""
    inbox = crew["inbox"][role]
    email = f"{crew['h'][role]}@mail.grokbot.com"
    assert client.post("/api/auth/start", json={"email": email}).status_code == 200
    code = [e for e in inbox.events if e["type"] == "login_code"][-1]["payload"]["code"]
    resp = client.post("/api/auth/verify", json={"email": email, "code": code})
    assert resp.status_code == 200, resp.text
    value = resp.cookies["groknet_session"]
    client.cookies.clear()
    # Drop the default test bearer so the cookie is the actor.
    return {"Cookie": f"groknet_session={value}", **NO_AUTH}


def new_project(client, crew, role="owner", **body):
    payload = {"team_id": crew["team_id"], "name": "Launch", **body}
    resp = client.post("/api/projects", json=payload, headers=bearer(crew["tok"][role]))
    assert resp.status_code == 201, resp.text
    return resp.json()


def new_issue(client, crew, pid, role="owner", **body):
    resp = client.post(
        f"/api/projects/{pid}/issues",
        json={"title": "T", **body},
        headers=bearer(crew["tok"][role]),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def drain(q) -> list[dict]:
    out = []
    while not q.empty():
        out.append(json.loads(q.get_nowait()))
    return out


def inbox_types(crew, role, prefix="issue_") -> list[str]:
    return [e["type"] for e in crew["inbox"][role].events if e["type"].startswith(prefix)]


# --- auth ---------------------------------------------------------------------


def test_no_actor_is_401_and_bad_credentials_are_401(client, crew):
    assert client.get("/api/projects", headers=NO_AUTH).status_code == 401
    body = {"team_id": crew["team_id"], "name": "x"}
    assert client.post("/api/projects", json=body, headers=NO_AUTH).status_code == 401
    assert client.get("/api/projects", headers=bearer("nope")).status_code == 401
    forged = {"Cookie": "groknet_session=forged.not-signed", **NO_AUTH}
    assert client.get("/api/projects", headers=forged).status_code == 401


def test_session_cookie_writes_like_a_token(client, crew):
    cookie = login_cookie(client, crew, "first")
    resp = client.post(
        "/api/projects",
        json={"team_id": crew["team_id"], "name": "From the dashboard"},
        headers=cookie,
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["created_by"] == crew["h"]["first"]
    listed = client.get("/api/projects", params={"team_id": crew["team_id"]}, headers=cookie)
    assert [p["name"] for p in listed.json()] == ["From the dashboard"]


def test_non_member_cannot_write_but_can_read(client, crew):
    out = bearer(crew["tok"]["outsider"])
    resp = client.post("/api/projects", json={"team_id": crew["team_id"], "name": "x"}, headers=out)
    assert resp.status_code == 403 and "team member" in resp.json()["detail"]
    pid = new_project(client, crew)["id"]
    for method, path, body in (
        ("PATCH", f"/api/projects/{pid}", {"name": "y"}),
        ("POST", f"/api/projects/{pid}/issues", {"title": "t"}),
        ("POST", f"/api/projects/{pid}/artifacts", {"title": "a", "kind": "text", "content": "c"}),
    ):
        resp = client.request(method, path, json=body, headers=out)
        assert resp.status_code == 403, (path, resp.text)
    issue = new_issue(client, crew, pid)
    resp = client.patch(f"/api/issues/{issue['id']}", json={"status": "done"}, headers=out)
    assert resp.status_code == 403
    assert client.get(f"/api/projects/{pid}", headers=out).status_code == 200
    assert client.get(f"/api/projects/{pid}/issues", headers=out).status_code == 200
    assert client.get(f"/api/projects/{pid}/artifacts", headers=out).status_code == 200


def test_unknown_ids_are_404(client, crew):
    h = bearer(crew["tok"]["owner"])
    assert client.get("/api/projects/nope", headers=h).status_code == 404
    assert client.patch("/api/projects/nope", json={"name": "x"}, headers=h).status_code == 404
    assert client.get("/api/projects/nope/issues", headers=h).status_code == 404
    assert client.get("/api/projects/nope/artifacts", headers=h).status_code == 404
    resp = client.post("/api/projects/nope/issues", json={"title": "x"}, headers=h)
    assert resp.status_code == 404
    assert client.patch("/api/issues/nope", json={"title": "x"}, headers=h).status_code == 404
    resp = client.post("/api/projects", json={"team_id": "nope", "name": "x"}, headers=h)
    assert resp.status_code == 404


# --- projects -----------------------------------------------------------------


def test_project_shapes_counts_and_patch(client, crew):
    h = bearer(crew["tok"]["owner"])
    project = new_project(client, crew, description="Ship it")
    assert set(project) == {
        "id",
        "team_id",
        "name",
        "description",
        "status",
        "created_by",
        "created_at",
        "updated_at",
    }
    assert project["status"] == "active" and project["description"] == "Ship it"
    assert project["created_by"] == crew["h"]["owner"]
    pid = project["id"]
    for status in (None, "in_progress", "done", "done"):
        issue = new_issue(client, crew, pid)
        if status:
            client.patch(f"/api/issues/{issue['id']}", json={"status": status}, headers=h)
    listed = client.get("/api/projects", params={"team_id": crew["team_id"]}, headers=h).json()
    assert len(listed) == 1
    assert listed[0]["issue_counts"] == {"open": 1, "in_progress": 1, "done": 2}
    assert {k: v for k, v in listed[0].items() if k != "issue_counts"} == project
    assert client.get("/api/projects", params={"team_id": "other"}, headers=h).json() == []

    q = bus.subscribe()
    try:
        resp = client.patch(
            f"/api/projects/{pid}", json={"status": "archived", "name": "L2"}, headers=h
        )
        events = drain(q)
    finally:
        bus.unsubscribe(q)
    assert resp.status_code == 200, resp.text
    patched = resp.json()
    assert patched["status"] == "archived" and patched["name"] == "L2"
    assert patched["updated_at"] > project["updated_at"]
    again = client.patch(f"/api/projects/{pid}", json={}, headers=h).json()
    assert again["updated_at"] > patched["updated_at"]
    (event,) = [e for e in events if e["type"] == "project_updated"]
    assert event == {
        "type": "project_updated",
        "project_id": pid,
        "team_id": crew["team_id"],
        "by": crew["h"]["owner"],
        "changes": ["name", "status"],
    }


@pytest.mark.parametrize(
    "body", [{"name": ""}, {"name": "   "}, {"name": "x" * 101}, {"status": "deleted"}]
)
def test_project_validation(client, crew, body):
    h = bearer(crew["tok"]["owner"])
    if "status" in body:
        pid = new_project(client, crew)["id"]
        resp = client.patch(f"/api/projects/{pid}", json=body, headers=h)
    else:
        resp = client.post("/api/projects", json={"team_id": crew["team_id"], **body}, headers=h)
    assert resp.status_code == 400 and resp.json()["detail"]


def test_project_detail_composite_shape(client, crew):
    h = bearer(crew["tok"]["owner"])
    project = new_project(client, crew)
    pid = project["id"]
    issue = new_issue(
        client,
        crew,
        pid,
        title="Write spec",
        assignee=crew["h"]["first"],
        mentions=[crew["h"]["second"]],
    )
    artifact = client.post(
        f"/api/projects/{pid}/artifacts",
        json={"title": "Spec", "kind": "markdown", "content": "# Spec", "issue_id": issue["id"]},
        headers=h,
    ).json()
    detail = client.get(f"/api/projects/{pid}", headers=h).json()
    assert {k: v for k, v in detail.items() if k not in ("team", "issues", "artifacts")} == project
    assert detail["team"] == {
        "id": crew["team_id"],
        "name": "Proj team",
        "members": sorted(crew["h"][r] for r in ("owner", "first", "second")),
    }
    assert detail["issues"] == [issue]
    assert detail["artifacts"] == [artifact]


# --- issues -------------------------------------------------------------------


def test_issue_shape_validation_and_status_transitions(client, crew):
    h = bearer(crew["tok"]["owner"])
    pid = new_project(client, crew)["id"]
    first, second, outsider = (crew["h"][r] for r in ("first", "second", "outsider"))
    issue = new_issue(
        client, crew, pid, title="Do it", description="d", assignee=first, mentions=[second, second]
    )
    assert set(issue) == {
        "id",
        "project_id",
        "title",
        "description",
        "status",
        "assignee",
        "mentions",
        "created_by",
        "created_at",
        "updated_at",
    }
    assert issue["status"] == "open" and issue["assignee"] == first
    assert issue["mentions"] == [second] and issue["project_id"] == pid
    assert issue["description"] == "d" and issue["created_by"] == crew["h"]["owner"]

    for bad in (
        {"title": ""},
        {"title": "x" * 201},
        {"title": "ok", "assignee": outsider},
        {"title": "ok", "assignee": "nobody_here"},
        {"title": "ok", "mentions": [outsider]},
        {"title": "ok", "mentions": ["@" + first]},
    ):
        resp = client.post(f"/api/projects/{pid}/issues", json=bad, headers=h)
        assert resp.status_code == 400, (bad, resp.text)

    iid = issue["id"]
    last = issue["updated_at"]
    for status in ("in_progress", "done", "open", "done"):
        resp = client.patch(f"/api/issues/{iid}", json={"status": status}, headers=h)
        assert resp.status_code == 200 and resp.json()["status"] == status
        assert resp.json()["updated_at"] > last
        last = resp.json()["updated_at"]
    for bad in ({"status": "closed"}, {"assignee": outsider}, {"title": ""}):
        assert client.patch(f"/api/issues/{iid}", json=bad, headers=h).status_code == 400

    cleared = client.patch(f"/api/issues/{iid}", json={"assignee": None}, headers=h).json()
    assert cleared["assignee"] is None and cleared["mentions"] == [second]
    kept = client.patch(f"/api/issues/{iid}", json={"title": "Renamed"}, headers=h).json()
    assert kept["assignee"] is None and kept["title"] == "Renamed"
    assert kept["updated_at"] > cleared["updated_at"]

    def by_status(status):
        return client.get(f"/api/projects/{pid}/issues", params={"status": status}, headers=h)

    assert [i["id"] for i in by_status("done").json()] == [iid]
    assert by_status("open").json() == []
    assert by_status("x").status_code == 400
    assert [i["id"] for i in client.get(f"/api/projects/{pid}/issues", headers=h).json()] == [iid]


def test_assignment_webhook_reaches_assignee_with_their_key(client, crew):
    pid = new_project(client, crew)["id"]
    owner, first, second = (crew["h"][r] for r in ("owner", "first", "second"))
    q = bus.subscribe()
    try:
        issue = new_issue(
            client, crew, pid, title="Fix login", assignee=first, mentions=[first, second]
        )
        events = drain(q)
    finally:
        bus.unsubscribe(q)

    inbox = crew["inbox"]["first"]
    # Mentioned and assigned: one webhook, the assignment.
    assert inbox_types(crew, "first") == ["issue_assigned"]
    assigned = inbox.events[-1]
    assert inbox.keys[-1] == f"Bearer crsr_{first}_secret"
    assert assigned["from"]["handle"] == owner
    assert assigned["payload"] == {
        "issue": {"id": issue["id"], "title": "Fix login", "status": "open"},
        "project": {"id": pid, "name": "Launch"},
        "team": {"id": crew["team_id"], "name": "Proj team"},
        "message": f"{owner.capitalize()} assigned you 'Fix login' in Launch",
    }
    assert inbox_types(crew, "second") == ["issue_mention"]
    mention = crew["inbox"]["second"].events[-1]
    assert crew["inbox"]["second"].keys[-1] == f"Bearer crsr_{second}_secret"
    assert mention["payload"]["issue"] == assigned["payload"]["issue"]
    assert (
        mention["payload"]["message"]
        == f"{owner.capitalize()} mentioned you in 'Fix login' in Launch"
    )
    assert inbox_types(crew, "owner") == []

    assert [e for e in events if e["type"] == "issue_created"] == [
        {
            "type": "issue_created",
            "issue": {"id": issue["id"], "title": "Fix login", "status": "open", "assignee": first},
            "project_id": pid,
            "team_id": crew["team_id"],
            "by": owner,
        }
    ]
    deliveries = [e for e in events if e["type"] == "delivery"]
    assert sorted(e["event_type"] for e in deliveries) == ["issue_assigned", "issue_mention"]
    assert all(e["ok"] for e in deliveries)
    blob = json.dumps(events)
    assert "crsr_" not in blob and "groknet_token" not in blob and "webhook" not in blob


def test_reassign_notifies_only_new_assignee_and_never_self(client, crew):
    h = bearer(crew["tok"]["owner"])
    pid = new_project(client, crew)["id"]
    first, second = crew["h"]["first"], crew["h"]["second"]
    iid = new_issue(client, crew, pid, assignee=first)["id"]
    # Same assignee again: no second webhook.
    client.patch(f"/api/issues/{iid}", json={"assignee": first}, headers=h)
    assert inbox_types(crew, "first") == ["issue_assigned"]
    # Self-assignment: nothing to the actor.
    resp = client.patch(
        f"/api/issues/{iid}", json={"assignee": second}, headers=bearer(crew["tok"]["second"])
    )
    assert resp.status_code == 200
    assert inbox_types(crew, "second") == []

    q = bus.subscribe()
    try:
        client.patch(
            f"/api/issues/{iid}",
            json={"assignee": first, "mentions": [second], "status": "in_progress"},
            headers=h,
        )
        events = drain(q)
    finally:
        bus.unsubscribe(q)
    assert inbox_types(crew, "first") == ["issue_assigned", "issue_assigned"]
    assert inbox_types(crew, "second") == ["issue_mention"]
    # Already mentioned: no repeat.
    client.patch(f"/api/issues/{iid}", json={"mentions": [second]}, headers=h)
    assert inbox_types(crew, "second") == ["issue_mention"]
    (updated,) = [e for e in events if e["type"] == "issue_updated"]
    assert updated == {
        "type": "issue_updated",
        "issue_id": iid,
        "project_id": pid,
        "team_id": crew["team_id"],
        "by": crew["h"]["owner"],
        "changes": ["status", "assignee", "mentions"],
        "status": "in_progress",
        "assignee": first,
    }


def test_dead_inbox_never_fails_the_request(client, crew, mcp):
    dead = f"proj_dead_{uuid4().hex[:6]}"
    mcp.call("register", **register_args(dead))  # webhook on a closed port
    with Session(engine) as session:
        session.add(
            Friendship(
                requester=dead, addressee=crew["h"]["owner"], status=FriendshipStatus.accepted
            )
        )
        session.commit()
    mcp.call(
        "add_to_team", groknet_token=crew["tok"]["owner"], team_id=crew["team_id"], handle=dead
    )
    pid = new_project(client, crew)["id"]
    q = bus.subscribe()
    try:
        resp = client.post(
            f"/api/projects/{pid}/issues",
            json={"title": "T", "assignee": dead},
            headers=bearer(crew["tok"]["owner"]),
        )
        events = drain(q)
    finally:
        bus.unsubscribe(q)
    assert resp.status_code == 201
    (delivery,) = [e for e in events if e["type"] == "delivery"]
    assert delivery["ok"] is False and delivery["to"] == dead


# --- artifacts ----------------------------------------------------------------


def test_artifacts_validation_and_events(client, crew):
    h = bearer(crew["tok"]["owner"])
    pid = new_project(client, crew)["id"]
    other = new_project(client, crew)["id"]
    elsewhere = new_issue(client, crew, other)
    for bad in (
        {"title": "", "kind": "text", "content": "c"},
        {"title": "x" * 201, "kind": "text", "content": "c"},
        {"title": "t", "kind": "pdf", "content": "c"},
        {"title": "t", "kind": "url", "content": "ftp://x"},
        {"title": "t", "kind": "url", "content": "javascript:alert(1)"},
        {"title": "t", "kind": "markdown", "content": "x" * (50 * 1024 + 1)},
        {"title": "t", "kind": "text", "content": "c", "issue_id": elsewhere["id"]},
    ):
        resp = client.post(f"/api/projects/{pid}/artifacts", json=bad, headers=h)
        assert resp.status_code == 400, (bad["kind"], resp.text)
    resp = client.post(
        f"/api/projects/{pid}/artifacts",
        json={"title": "t", "kind": "text", "content": "c", "issue_id": "nope"},
        headers=h,
    )
    assert resp.status_code == 404

    q = bus.subscribe()
    try:
        resp = client.post(
            f"/api/projects/{pid}/artifacts",
            json={"title": "Demo", "kind": "url", "content": "https://example.com/demo"},
            headers=h,
        )
        events = drain(q)
    finally:
        bus.unsubscribe(q)
    assert resp.status_code == 201, resp.text
    artifact = resp.json()
    assert set(artifact) == {
        "id",
        "project_id",
        "issue_id",
        "title",
        "kind",
        "content",
        "created_by",
        "created_at",
    }
    assert artifact["issue_id"] is None and artifact["kind"] == "url"
    assert artifact["content"] == "https://example.com/demo"
    assert client.get(f"/api/projects/{pid}/artifacts", headers=h).json() == [artifact]
    assert [e for e in events if e["type"] == "artifact_added"] == [
        {
            "type": "artifact_added",
            "artifact": {"id": artifact["id"], "title": "Demo", "kind": "url"},
            "project_id": pid,
            "issue_id": None,
            "team_id": crew["team_id"],
            "by": crew["h"]["owner"],
        }
    ]
    at_limit = {"title": "Notes", "kind": "markdown", "content": "x" * (50 * 1024)}
    assert (
        client.post(f"/api/projects/{pid}/artifacts", json=at_limit, headers=h).status_code == 201
    )


def test_project_created_event(client, crew):
    q = bus.subscribe()
    try:
        project = new_project(client, crew)
        events = drain(q)
    finally:
        bus.unsubscribe(q)
    assert [e for e in events if e["type"] == "project_created"] == [
        {
            "type": "project_created",
            "project": {"id": project["id"], "name": "Launch"},
            "team_id": crew["team_id"],
            "by": crew["h"]["owner"],
        }
    ]


# --- MCP ----------------------------------------------------------------------


def test_mcp_tools_end_to_end(mcp, client, crew):
    tools = set(mcp.list_tools())
    assert {
        "create_project",
        "list_projects",
        "create_issue",
        "update_issue",
        "list_issues",
        "add_artifact",
    } <= tools
    owner, first = crew["tok"]["owner"], crew["tok"]["first"]
    project = mcp.call(
        "create_project", groknet_token=owner, team_id=crew["team_id"], name="Bot project"
    )
    pid = project["id"]
    assert project["description"] == "" and project["status"] == "active"
    listed = mcp.call("list_projects", groknet_token=first, team_id=crew["team_id"])["projects"]
    assert [p["id"] for p in listed] == [pid] and listed[0]["issue_counts"]["open"] == 0

    issue = mcp.call(
        "create_issue",
        groknet_token=owner,
        project_id=pid,
        title="From a bot",
        assignee=crew["h"]["first"],
        mentions=[crew["h"]["second"]],
    )
    assert issue["assignee"] == crew["h"]["first"] and issue["mentions"] == [crew["h"]["second"]]
    assert inbox_types(crew, "first") == ["issue_assigned"]
    updated = mcp.call(
        "update_issue", groknet_token=first, issue_id=issue["id"], status="in_progress"
    )
    assert updated["status"] == "in_progress" and updated["assignee"] == crew["h"]["first"]
    cleared = mcp.call("update_issue", groknet_token=first, issue_id=issue["id"], assignee="")
    assert cleared["assignee"] is None and cleared["status"] == "in_progress"
    issues = mcp.call("list_issues", groknet_token=first, project_id=pid, status="in_progress")
    assert [i["id"] for i in issues["issues"]] == [issue["id"]]

    artifact = mcp.call(
        "add_artifact",
        groknet_token=first,
        project_id=pid,
        title="Notes",
        content="# hi",
        issue_id=issue["id"],
    )
    assert artifact["kind"] == "markdown" and artifact["issue_id"] == issue["id"]

    with pytest.raises(ToolError, match="team member"):
        mcp.call("create_issue", groknet_token=crew["tok"]["outsider"], project_id=pid, title="no")
    with pytest.raises(ToolError, match="Unknown groknet_token"):
        mcp.call("list_projects", groknet_token="bad", team_id=crew["team_id"])
    with pytest.raises(ToolError, match="status"):
        mcp.call("update_issue", groknet_token=owner, issue_id=issue["id"], status="closed")
    with pytest.raises(ToolError, match="not found"):
        mcp.call("list_issues", groknet_token=owner, project_id="nope")
