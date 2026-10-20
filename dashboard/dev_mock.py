"""Opt-in preview fixtures for the projects API (issue #32 shapes), GROKNET_DASHBOARD_MOCK=1.

In-memory and reset on restart. Projects attach to the upstream's first team so team
links and members are real. Writes require a real upstream session (checked with
/api/auth/me) and publish the matching SSE event through the upstream's dev-only
/api/dev/emit, so the live path is exercised too. Membership is not enforced here.
"""

import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

router = APIRouter()
log = logging.getLogger(__name__)
DB: dict[str, Any] = {}
STATUSES = ("open", "in_progress", "done")


def _ts(minutes_ago: int = 0) -> str:
    return (datetime.now(UTC) - timedelta(minutes=minutes_ago)).isoformat().replace("+00:00", "Z")


async def _team(request: Request) -> dict[str, Any]:
    if "team" not in DB:
        team = {"id": "mock-team", "name": "Mock team", "members": ["tomas", "alejandro", "juan"]}
        try:
            r = await request.app.state.client.get(f"{request.app.state.upstream}/api/teams")
            if r.status_code == 200 and r.json():
                first = r.json()[0]
                team = {"id": first["id"], "name": first["name"], "members": first["members"]}
        except (httpx.HTTPError, ValueError, KeyError, IndexError):
            log.warning("Upstream teams unavailable; mock projects use a placeholder team.")
        DB["team"] = team
        _seed(team)
    return DB["team"]


def _seed(team: dict[str, Any]) -> None:
    m = team["members"] + ["tomas"] * 3
    p1, p2 = "mock-proj-launch", "mock-proj-archive"
    DB["projects"] = {
        p1: {
            "id": p1,
            "team_id": team["id"],
            "name": "Hackathon launch",
            "description": "Everything we need for the demo on stage.",
            "status": "active",
            "created_by": m[0],
            "created_at": _ts(300),
            "updated_at": _ts(5),
        },
        p2: {
            "id": p2,
            "team_id": team["id"],
            "name": "Bot template v1",
            "description": "Retired once v2 shipped.",
            "status": "archived",
            "created_by": m[1],
            "created_at": _ts(900),
            "updated_at": _ts(600),
        },
    }
    rows = [
        (p1, "Record the demo video", "Screen capture of two bots meeting.", "open", m[1], [m[2]]),
        (p1, "Write the pitch", "Three slides, no more.", "open", None, []),
        (p1, "Wire live project events", "SSE for issue changes.", "in_progress", m[2], [m[0]]),
        (p1, "Dark mode for the projector", "", "in_progress", m[0], [m[1], m[2]]),
        (p1, "Register all three bots", "Done on day one.", "done", m[0], []),
        (p2, "Inbox routine prompt", "Superseded by v2.", "done", m[1], []),
    ]
    DB["issues"] = {}
    for i, (pid, title, desc, status, assignee, mentions) in enumerate(rows):
        iid = f"mock-issue-{i + 1}"
        DB["issues"][iid] = {
            "id": iid,
            "project_id": pid,
            "title": title,
            "description": desc,
            "status": status,
            "assignee": assignee,
            "mentions": mentions,
            "created_by": m[0],
            "created_at": _ts(200 - i * 10),
            "updated_at": _ts(100 - i),
        }
    DB["artifacts"] = {
        "mock-art-1": {
            "id": "mock-art-1",
            "project_id": p1,
            "issue_id": None,
            "title": "Demo runbook",
            "kind": "markdown",
            "created_by": m[0],
            "created_at": _ts(90),
            "content": "# Runbook\n\n1. Seed the backend\n2. Open the **Workroom**\n\n"
            "- Check `/api/events` is live\n- See [the repo](https://github.com/sudoTomas/groknet)\n\n"
            "<script>alert('xss')</script> must render as text.",
        },
        "mock-art-2": {
            "id": "mock-art-2",
            "project_id": p1,
            "issue_id": "mock-issue-1",
            "title": "Design reference",
            "kind": "url",
            "created_by": m[1],
            "created_at": _ts(60),
            "content": "https://example.com/design",
        },
        "mock-art-3": {
            "id": "mock-art-3",
            "project_id": p1,
            "issue_id": None,
            "title": "Raw notes",
            "kind": "text",
            "created_by": m[2],
            "created_at": _ts(30),
            "content": "Plain text keeps <b>tags</b> and\nline breaks.",
        },
    }


def _counts(pid: str) -> dict[str, int]:
    counts = dict.fromkeys(STATUSES, 0)
    for issue in DB["issues"].values():
        if issue["project_id"] == pid:
            counts[issue["status"]] += 1
    return counts


def _project(p: dict[str, Any]) -> dict[str, Any]:
    return {**p, "issue_counts": _counts(p["id"])}


def _err(status: int, detail: str) -> JSONResponse:
    return JSONResponse({"detail": detail}, status_code=status)


async def _actor(request: Request) -> str | None:
    cookie = request.headers.get("cookie")
    if not cookie:
        return None
    r = await request.app.state.client.get(
        f"{request.app.state.upstream}/api/auth/me", headers={"cookie": cookie}
    )
    return r.json().get("handle") if r.status_code == 200 else None


async def _emit(request: Request, event: dict[str, Any]) -> None:
    try:
        await request.app.state.client.post(
            f"{request.app.state.upstream}/api/dev/emit", json=event
        )
    except httpx.HTTPError:
        log.warning("Could not emit %s through the upstream; live update skipped.", event["type"])


@router.get("/api/projects")
async def list_projects(request: Request, team_id: str = ""):
    await _team(request)
    rows = [p for p in DB["projects"].values() if not team_id or p["team_id"] == team_id]
    return [_project(p) for p in rows]


@router.post("/api/projects")
async def create_project(request: Request):
    team = await _team(request)
    by = await _actor(request)
    if not by:
        return _err(401, "Not logged in.")
    body = await request.json()
    name = str(body.get("name", "")).strip()
    if not 1 <= len(name) <= 100:
        return _err(400, "Project name must be 1 to 100 characters.")
    if body.get("team_id") != team["id"]:
        return _err(404, "Team not found.")
    pid = f"mock-proj-{uuid.uuid4().hex[:8]}"
    p = {
        "id": pid,
        "team_id": team["id"],
        "name": name,
        "description": body.get("description") or "",
        "status": "active",
        "created_by": by,
        "created_at": _ts(),
        "updated_at": _ts(),
    }
    DB["projects"][pid] = p
    await _emit(
        request,
        {
            "type": "project_created",
            "project": {"id": pid, "name": name},
            "team_id": team["id"],
            "by": by,
        },
    )
    return JSONResponse(_project(p), status_code=201)


@router.get("/api/projects/{pid}")
async def get_project(pid: str, request: Request):
    team = await _team(request)
    p = DB["projects"].get(pid)
    if not p:
        return _err(404, "Project not found.")
    return {
        **_project(p),
        "team": team,
        "issues": [i for i in DB["issues"].values() if i["project_id"] == pid],
        "artifacts": [a for a in DB["artifacts"].values() if a["project_id"] == pid],
    }


@router.patch("/api/projects/{pid}")
async def patch_project(pid: str, request: Request):
    team = await _team(request)
    by = await _actor(request)
    if not by:
        return _err(401, "Not logged in.")
    p = DB["projects"].get(pid)
    if not p:
        return _err(404, "Project not found.")
    body = await request.json()
    if "status" in body and body["status"] not in ("active", "archived"):
        return _err(400, "Status must be active or archived.")
    changes = [k for k in ("name", "description", "status") if k in body]
    p.update({k: body[k] for k in changes}, updated_at=_ts())
    await _emit(
        request,
        {
            "type": "project_updated",
            "project_id": pid,
            "team_id": team["id"],
            "by": by,
            "changes": changes,
        },
    )
    return _project(p)


@router.get("/api/projects/{pid}/issues")
async def list_issues(pid: str, request: Request, status: str = ""):
    await _team(request)
    return [
        i
        for i in DB["issues"].values()
        if i["project_id"] == pid and (not status or i["status"] == status)
    ]


@router.post("/api/projects/{pid}/issues")
async def create_issue(pid: str, request: Request):
    team = await _team(request)
    by = await _actor(request)
    if not by:
        return _err(401, "Not logged in.")
    if pid not in DB["projects"]:
        return _err(404, "Project not found.")
    body = await request.json()
    title = str(body.get("title", "")).strip()
    if not 1 <= len(title) <= 200:
        return _err(400, "Issue title must be 1 to 200 characters.")
    assignee = body.get("assignee") or None
    mentions = body.get("mentions") or []
    for h in [assignee, *mentions]:
        if h and h not in team["members"]:
            return _err(400, f"@{h} is not a member of {team['name']}.")
    iid = f"mock-issue-{uuid.uuid4().hex[:8]}"
    issue = {
        "id": iid,
        "project_id": pid,
        "title": title,
        "description": body.get("description") or "",
        "status": "open",
        "assignee": assignee,
        "mentions": mentions,
        "created_by": by,
        "created_at": _ts(),
        "updated_at": _ts(),
    }
    DB["issues"][iid] = issue
    await _emit(
        request,
        {
            "type": "issue_created",
            "project_id": pid,
            "team_id": team["id"],
            "by": by,
            "issue": {k: issue[k] for k in ("id", "title", "status", "assignee")},
        },
    )
    return JSONResponse(issue, status_code=201)


@router.patch("/api/issues/{iid}")
async def patch_issue(iid: str, request: Request):
    team = await _team(request)
    by = await _actor(request)
    if not by:
        return _err(401, "Not logged in.")
    issue = DB["issues"].get(iid)
    if not issue:
        return _err(404, "Issue not found.")
    body = await request.json()
    if "status" in body and body["status"] not in STATUSES:
        return _err(400, "Status must be open, in_progress or done.")
    for h in [body.get("assignee"), *(body.get("mentions") or [])]:
        if h and h not in team["members"]:
            return _err(400, f"@{h} is not a member of {team['name']}.")
    changes = [k for k in ("title", "description", "status", "assignee", "mentions") if k in body]
    issue.update({k: body[k] for k in changes}, updated_at=_ts())
    await _emit(
        request,
        {
            "type": "issue_updated",
            "issue_id": iid,
            "project_id": issue["project_id"],
            "team_id": team["id"],
            "by": by,
            "changes": changes,
            "status": issue["status"],
            "assignee": issue["assignee"],
        },
    )
    return issue


@router.get("/api/projects/{pid}/artifacts")
async def list_artifacts(pid: str, request: Request):
    await _team(request)
    return [a for a in DB["artifacts"].values() if a["project_id"] == pid]


@router.post("/api/projects/{pid}/artifacts")
async def add_artifact(pid: str, request: Request):
    team = await _team(request)
    by = await _actor(request)
    if not by:
        return _err(401, "Not logged in.")
    if pid not in DB["projects"]:
        return _err(404, "Project not found.")
    body = await request.json()
    title, kind, content = (
        str(body.get("title", "")).strip(),
        body.get("kind"),
        str(body.get("content", "")),
    )
    if not 1 <= len(title) <= 200:
        return _err(400, "Artifact title must be 1 to 200 characters.")
    if kind not in ("markdown", "text", "url"):
        return _err(400, "Kind must be markdown, text or url.")
    if kind == "url" and not content.startswith(("http://", "https://")):
        return _err(400, "A url artifact must start with http:// or https://.")
    aid = f"mock-art-{uuid.uuid4().hex[:8]}"
    art = {
        "id": aid,
        "project_id": pid,
        "issue_id": body.get("issue_id"),
        "title": title,
        "kind": kind,
        "content": content,
        "created_by": by,
        "created_at": _ts(),
    }
    DB["artifacts"][aid] = art
    await _emit(
        request,
        {
            "type": "artifact_added",
            "artifact": {"id": aid, "title": title, "kind": kind},
            "project_id": pid,
            "issue_id": art["issue_id"],
            "team_id": team["id"],
            "by": by,
        },
    )
    return JSONResponse(art, status_code=201)
