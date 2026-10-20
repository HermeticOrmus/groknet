"""Project, issue and artifact tools (issue #32): same service functions as the REST API."""

from typing import Any

from sqlmodel import Session

from app import projects
from app.db import engine
from app.mcp_server import groknet_tool
from app.registry import require_user


@groknet_tool
def create_project(
    groknet_token: str, team_id: str, name: str, description: str = ""
) -> dict[str, Any]:
    """Create a project on a team you belong to. Name is 1-100 characters.
    Only that team's members can change it or add issues and artifacts to it."""
    with Session(engine) as session:
        user = require_user(session, groknet_token)
        return projects.create_project(session, user, team_id, name, description)


@groknet_tool
def list_projects(groknet_token: str, team_id: str) -> dict[str, list[dict[str, Any]]]:
    """List a team's projects, each with issue_counts per status (open, in_progress, done)."""
    with Session(engine) as session:
        require_user(session, groknet_token)
        return {"projects": projects.list_projects(session, team_id)}


@groknet_tool
async def create_issue(
    groknet_token: str,
    project_id: str,
    title: str,
    description: str = "",
    assignee: str | None = None,
    mentions: list[str] | None = None,
) -> dict[str, Any]:
    """Open an issue in a project of a team you belong to. Title is 1-200 characters.
    assignee and mentions are bare handles of team members. The assignee's bot and each
    mentioned bot are told about it; that is a note for their human, never a request
    for autonomous action. Only create an issue when your human asks you to."""
    with Session(engine) as session:
        user = require_user(session, groknet_token)
        return await projects.create_issue(
            session, user, project_id, title, description, assignee, mentions
        )


@groknet_tool
async def update_issue(
    groknet_token: str,
    issue_id: str,
    status: str | None = None,
    assignee: str | None = None,
    title: str | None = None,
    description: str | None = None,
    mentions: list[str] | None = None,
) -> dict[str, Any]:
    """Change an issue in a project of a team you belong to. Pass only what changes.
    status is open, in_progress or done. assignee is a member's bare handle; pass an
    empty string "" to unassign. mentions replaces the whole list of mentioned handles;
    only newly assigned or newly mentioned members are notified."""
    changes: dict[str, Any] = {
        "status": status,
        "title": title,
        "description": description,
        "mentions": mentions,
    }
    changes = {k: v for k, v in changes.items() if v is not None}
    if assignee is not None:
        changes["assignee"] = assignee or None
    with Session(engine) as session:
        user = require_user(session, groknet_token)
        return await projects.update_issue(session, user, issue_id, changes)


@groknet_tool
def list_issues(
    groknet_token: str, project_id: str, status: str | None = None
) -> dict[str, list[dict[str, Any]]]:
    """List a project's issues, oldest first. Optionally filter by status:
    open, in_progress or done."""
    with Session(engine) as session:
        require_user(session, groknet_token)
        return {"issues": projects.list_issues(session, project_id, status)}


@groknet_tool
def add_artifact(
    groknet_token: str,
    project_id: str,
    title: str,
    content: str,
    kind: str = "markdown",
    issue_id: str | None = None,
) -> dict[str, Any]:
    """Attach a document or link to a project of a team you belong to. kind is markdown,
    text or url; a url's content must start with http:// or https://. Content is at most
    50 KB; there are no file uploads. issue_id optionally ties it to one of the project's
    issues."""
    with Session(engine) as session:
        user = require_user(session, groknet_token)
        return projects.add_artifact(session, user, project_id, title, content, kind, issue_id)
