"""Projects, issues and artifacts (issue #32), shared by REST (app/projects_api.py) and MCP
(app/tools/projects.py).

A project belongs to exactly one team. Anyone authenticated reads; only members of the
project's team write. Assigning or mentioning someone notifies their bot through
`webhooks.deliver`; a failed delivery is logged and published, never raised.
"""

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlmodel import Session, func, select

from app.errors import GroknetError
from app.events import bus
from app.models import Artifact, Issue, Project, Team, TeamMember, User, now
from app.teams import require_member, require_team
from app.webhooks import deliver

log = logging.getLogger("groknet.projects")

PROJECT_STATUSES = ("active", "archived")
ISSUE_STATUSES = ("open", "in_progress", "done")
ARTIFACT_KINDS = ("markdown", "text", "url")
ASSIGNMENT_STATUSES = ("pending", "accepted", "declined")
MAX_RESPONSE_COMMENT = 2000
MAX_ARTIFACT_BYTES = 50 * 1024


class ProjectError(GroknetError):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


# --- views ----------------------------------------------------------------------------


def _aware(value: datetime) -> datetime:
    # SQLite returns naive datetimes even when the original value was UTC.
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _ts(value: datetime) -> str:
    # Fixed microsecond width so timestamps also sort correctly as strings.
    return _aware(value).astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _touch(previous: datetime) -> datetime:
    """A new updated_at, strictly later than the previous one even within one clock tick."""
    return max(now(), _aware(previous) + timedelta(microseconds=1))


def _split(mentions: str | None) -> list[str]:
    return mentions.split(",") if mentions else []


def project_view(project: Project) -> dict[str, Any]:
    return {
        "id": project.id,
        "team_id": project.team_id,
        "name": project.name,
        "description": project.description,
        "status": project.status,
        "created_by": project.created_by,
        "created_at": _ts(project.created_at),
        "updated_at": _ts(project.updated_at),
    }


def issue_view(issue: Issue) -> dict[str, Any]:
    return {
        "id": issue.id,
        "project_id": issue.project_id,
        "title": issue.title,
        "description": issue.description,
        "status": issue.status,
        "assignee": issue.assignee,
        "mentions": _split(issue.mentions),
        # Rows assigned before answers existed have no status yet: they are pending.
        "assignment_status": (issue.assignment_status or "pending") if issue.assignee else None,
        "assignment_comment": issue.assignment_comment if issue.assignee else None,
        "assigned_by": issue.assigned_by if issue.assignee else None,
        "created_by": issue.created_by,
        "created_at": _ts(issue.created_at),
        "updated_at": _ts(issue.updated_at),
    }


def artifact_view(artifact: Artifact) -> dict[str, Any]:
    return {
        "id": artifact.id,
        "project_id": artifact.project_id,
        "issue_id": artifact.issue_id,
        "title": artifact.title,
        "kind": artifact.kind,
        "content": artifact.content,
        "created_by": artifact.created_by,
        "created_at": _ts(artifact.created_at),
    }


def _issue_counts(session: Session, project_id: str) -> dict[str, int]:
    rows = session.exec(
        select(Issue.status, func.count())
        .where(Issue.project_id == project_id)
        .group_by(Issue.status)
    ).all()
    counts = dict.fromkeys(ISSUE_STATUSES, 0)
    counts.update({status: n for status, n in rows if status in counts})
    return counts


# --- lookups and validation -------------------------------------------------------------


def require_project(session: Session, project_id: str) -> Project:
    project = session.get(Project, project_id)
    if project is None:
        raise ProjectError("Project not found.", 404)
    return project


def require_issue(session: Session, issue_id: str) -> Issue:
    issue = session.get(Issue, issue_id)
    if issue is None:
        raise ProjectError("Issue not found.", 404)
    return issue


def _text(value: str, field: str, limit: int) -> str:
    value = value.strip()
    if not value or len(value) > limit:
        raise ProjectError(f"{field} must be between 1 and {limit} characters.")
    return value


def _choice(value: str, field: str, allowed: tuple[str, ...]) -> str:
    if value not in allowed:
        raise ProjectError(f"{field} must be one of {', '.join(allowed)}, got {value!r}.")
    return value


def _member_handles(session: Session, team_id: str) -> set[str]:
    return set(
        session.exec(select(TeamMember.user_handle).where(TeamMember.team_id == team_id)).all()
    )


def _check_assignee(assignee: str | None, members: set[str]) -> str | None:
    if assignee is not None and assignee not in members:
        raise ProjectError(
            f"assignee must be a bare handle of a member of this project's team, got {assignee!r}."
        )
    return assignee


def _check_mentions(mentions: list[str] | None, members: set[str]) -> list[str]:
    mentions = list(dict.fromkeys(mentions or []))
    bad = [handle for handle in mentions if handle not in members]
    if bad:
        raise ProjectError(
            f"Every mention must be a bare handle of a team member; not members: {', '.join(bad)}."
        )
    return mentions


# --- projects ---------------------------------------------------------------------------


def list_projects(session: Session, team_id: str | None = None) -> list[dict[str, Any]]:
    stmt = select(Project).order_by(Project.created_at, Project.id)
    if team_id is not None:
        stmt = stmt.where(Project.team_id == team_id)
    return [
        {**project_view(p), "issue_counts": _issue_counts(session, p.id)}
        for p in session.exec(stmt).all()
    ]


def create_project(
    session: Session, actor: User, team_id: str, name: str, description: str = ""
) -> dict[str, Any]:
    require_member(session, team_id, actor.handle)
    project = Project(
        team_id=team_id,
        name=_text(name, "Project name", 100),
        description=description,
        created_by=actor.handle,
    )
    session.add(project)
    session.commit()
    session.refresh(project)
    bus.publish(
        {
            "type": "project_created",
            "project": {"id": project.id, "name": project.name},
            "team_id": team_id,
            "by": actor.handle,
        }
    )
    return project_view(project)


def project_detail(session: Session, project_id: str) -> dict[str, Any]:
    project = require_project(session, project_id)
    team = require_team(session, project.team_id)
    issues = session.exec(
        select(Issue).where(Issue.project_id == project_id).order_by(Issue.created_at, Issue.id)
    ).all()
    artifacts = session.exec(
        select(Artifact)
        .where(Artifact.project_id == project_id)
        .order_by(Artifact.created_at, Artifact.id)
    ).all()
    return {
        **project_view(project),
        "team": {
            "id": team.id,
            "name": team.name,
            "members": sorted(_member_handles(session, team.id)),
        },
        "issues": [issue_view(i) for i in issues],
        "artifacts": [artifact_view(a) for a in artifacts],
    }


def update_project(
    session: Session, actor: User, project_id: str, changes: dict[str, Any]
) -> dict[str, Any]:
    """`changes` holds only the fields the caller sent: name, description, status."""
    project = require_project(session, project_id)
    require_member(session, project.team_id, actor.handle)
    new: dict[str, Any] = {}
    if "name" in changes:
        new["name"] = _text(changes["name"], "Project name", 100)
    if "description" in changes:
        new["description"] = changes["description"]
    if "status" in changes:
        new["status"] = _choice(changes["status"], "status", PROJECT_STATUSES)
    changed = [field for field, value in new.items() if getattr(project, field) != value]
    for field, value in new.items():
        setattr(project, field, value)
    project.updated_at = _touch(project.updated_at)
    session.add(project)
    session.commit()
    session.refresh(project)
    bus.publish(
        {
            "type": "project_updated",
            "project_id": project.id,
            "team_id": project.team_id,
            "by": actor.handle,
            "changes": changed,
        }
    )
    return project_view(project)


# --- issues -----------------------------------------------------------------------------


def list_issues(session: Session, project_id: str, status: str | None = None) -> list[dict]:
    require_project(session, project_id)
    stmt = select(Issue).where(Issue.project_id == project_id)
    if status is not None:
        stmt = stmt.where(Issue.status == _choice(status, "status", ISSUE_STATUSES))
    return [issue_view(i) for i in session.exec(stmt.order_by(Issue.created_at, Issue.id)).all()]


async def create_issue(
    session: Session,
    actor: User,
    project_id: str,
    title: str,
    description: str = "",
    assignee: str | None = None,
    mentions: list[str] | None = None,
) -> dict[str, Any]:
    project = require_project(session, project_id)
    team = require_member(session, project.team_id, actor.handle)
    members = _member_handles(session, project.team_id)
    issue = Issue(
        project_id=project_id,
        title=_text(title, "Issue title", 200),
        description=description,
        assignee=_check_assignee(assignee, members),
        mentions=",".join(_check_mentions(mentions, members)),
        created_by=actor.handle,
    )
    _reset_assignment(issue, actor)
    session.add(issue)
    session.commit()
    session.refresh(issue)
    view = issue_view(issue)
    bus.publish(
        {
            "type": "issue_created",
            "issue": {
                "id": issue.id,
                "title": issue.title,
                "status": issue.status,
                "assignee": issue.assignee,
                "assignment_status": view["assignment_status"],
                "assignment_comment": view["assignment_comment"],
            },
            "project_id": project_id,
            "team_id": project.team_id,
            "by": actor.handle,
        }
    )
    await _notify(session, actor, issue, project, team, issue.assignee, view["mentions"])
    return view


async def update_issue(
    session: Session, actor: User, issue_id: str, changes: dict[str, Any]
) -> dict[str, Any]:
    """`changes` holds only the fields the caller sent: title, description, status,
    assignee (None clears it) and mentions (replaces the list)."""
    issue = require_issue(session, issue_id)
    project = require_project(session, issue.project_id)
    team = require_member(session, project.team_id, actor.handle)
    members = _member_handles(session, project.team_id)
    new: dict[str, Any] = {}
    if "title" in changes:
        new["title"] = _text(changes["title"], "Issue title", 200)
    if "description" in changes:
        new["description"] = changes["description"]
    if "status" in changes:
        new["status"] = _choice(changes["status"], "status", ISSUE_STATUSES)
    if "assignee" in changes:
        new["assignee"] = _check_assignee(changes["assignee"], members)
    if "mentions" in changes:
        new["mentions"] = ",".join(_check_mentions(changes["mentions"], members))
    changed = [field for field, value in new.items() if getattr(issue, field) != value]
    old_assignee, old_mentions = issue.assignee, set(_split(issue.mentions))
    for field, value in new.items():
        setattr(issue, field, value)
    if issue.assignee != old_assignee:
        _reset_assignment(issue, actor)
    issue.updated_at = _touch(issue.updated_at)
    session.add(issue)
    session.commit()
    session.refresh(issue)
    view = issue_view(issue)
    bus.publish(
        {
            "type": "issue_updated",
            "issue_id": issue.id,
            "project_id": project.id,
            "team_id": project.team_id,
            "by": actor.handle,
            "changes": changed,
            "status": issue.status,
            "assignee": issue.assignee,
            "assignment_status": view["assignment_status"],
            "assignment_comment": view["assignment_comment"],
        }
    )
    new_assignee = issue.assignee if issue.assignee != old_assignee else None
    new_mentions = [h for h in view["mentions"] if h not in old_mentions]
    await _notify(session, actor, issue, project, team, new_assignee, new_mentions)
    return view


def _reset_assignment(issue: Issue, actor: User) -> None:
    """A new (or no) assignee starts over: no answer yet, assigned by the actor."""
    issue.assignment_status = "pending" if issue.assignee else None
    issue.assignment_comment = None
    issue.assigned_by = actor.handle if issue.assignee else None


async def respond_to_issue(
    session: Session, actor: User, issue_id: str, accept: bool, comment: str = ""
) -> dict[str, Any]:
    """The assignee accepts or declines the assignment, optionally with a comment.
    Whoever assigned it and the issue's creator hear back by webhook (never the actor)."""
    issue = require_issue(session, issue_id)
    if issue.assignee != actor.handle:
        raise ProjectError("Only the issue's current assignee can accept or decline it.", 403)
    comment = (comment or "").strip()
    if len(comment) > MAX_RESPONSE_COMMENT:
        raise ProjectError(f"comment must be at most {MAX_RESPONSE_COMMENT} characters.")
    project = require_project(session, issue.project_id)
    team = require_team(session, project.team_id)
    issue.assignment_status = "accepted" if accept else "declined"
    issue.assignment_comment = comment or None
    issue.updated_at = _touch(issue.updated_at)
    session.add(issue)
    session.commit()
    session.refresh(issue)
    view = issue_view(issue)
    bus.publish(
        {
            "type": "issue_response",
            "issue_id": issue.id,
            "project_id": project.id,
            "team_id": project.team_id,
            "by": actor.handle,
            "assignment_status": issue.assignment_status,
            "comment": issue.assignment_comment,
        }
    )
    handles = dict.fromkeys(h for h in (issue.assigned_by, issue.created_by) if h)
    recipients = [session.get(User, h) for h in handles if h != actor.handle]
    sender = User.model_validate(actor.model_dump())
    verb = "accepted" if accept else "declined"
    message = f"{sender.display_name} {verb} '{issue.title}'" + (f": {comment}" if comment else "")
    payload = {
        "issue": {
            "id": issue.id,
            "title": issue.title,
            "status": issue.status,
            "assignment_status": issue.assignment_status,
            "comment": issue.assignment_comment,
        },
        "project": {"id": project.id, "name": project.name},
        "team": {"id": team.id, "name": team.name},
        "message": message,
    }

    async def send_one(recipient: User) -> None:
        try:
            await deliver(
                User.model_validate(recipient.model_dump()),
                event_type="issue_response",
                sender=sender,
                payload=payload,
            )
        except Exception:  # noqa: BLE001 - a notification must never fail the write
            log.warning("notify issue_response -> @%s failed", recipient.handle, exc_info=False)

    await asyncio.gather(*(send_one(r) for r in recipients if r is not None))
    return view


async def _notify(
    session: Session,
    actor: User,
    issue: Issue,
    project: Project,
    team: Team,
    assignee: str | None,
    mentions: list[str],
) -> None:
    """Webhook the newly assigned member and the newly mentioned ones, never the actor,
    and never twice to the same bot. Concurrent; failures are logged, not raised."""
    targets: list[tuple[str, str]] = []
    if assignee and assignee != actor.handle:
        targets.append((assignee, "issue_assigned"))
    targets += [
        (handle, "issue_mention")
        for handle in mentions
        if handle != actor.handle and handle != assignee
    ]
    if not targets:
        return
    # Snapshot identities and credentials: they stay in process, never in events or JSON.
    sender = User.model_validate(actor.model_dump())
    recipients = {handle: session.get(User, handle) for handle, _ in targets}
    base = {
        "issue": {"id": issue.id, "title": issue.title, "status": issue.status},
        "project": {"id": project.id, "name": project.name},
        "team": {"id": team.id, "name": team.name},
    }
    verbs = {"issue_assigned": "assigned you", "issue_mention": "mentioned you in"}

    async def send_one(handle: str, event_type: str) -> None:
        recipient = recipients[handle]
        if recipient is None:
            return
        message = f"{sender.display_name} {verbs[event_type]} '{issue.title}' in {project.name}"
        try:
            await deliver(
                User.model_validate(recipient.model_dump()),
                event_type=event_type,
                sender=sender,
                payload={**base, "message": message},
            )
        except Exception:  # noqa: BLE001 - a notification must never fail the write
            log.warning("notify %s -> @%s failed", event_type, handle, exc_info=False)

    await asyncio.gather(*(send_one(handle, event_type) for handle, event_type in targets))


# --- artifacts --------------------------------------------------------------------------


def list_artifacts(session: Session, project_id: str) -> list[dict[str, Any]]:
    require_project(session, project_id)
    artifacts = session.exec(
        select(Artifact)
        .where(Artifact.project_id == project_id)
        .order_by(Artifact.created_at, Artifact.id)
    ).all()
    return [artifact_view(a) for a in artifacts]


def add_artifact(
    session: Session,
    actor: User,
    project_id: str,
    title: str,
    content: str,
    kind: str = "markdown",
    issue_id: str | None = None,
) -> dict[str, Any]:
    project = require_project(session, project_id)
    require_member(session, project.team_id, actor.handle)
    title = _text(title, "Artifact title", 200)
    _choice(kind, "kind", ARTIFACT_KINDS)
    if len(content.encode()) > MAX_ARTIFACT_BYTES:
        raise ProjectError("Artifact content must be at most 50 KB.")
    if kind == "url":
        content = content.strip()
        if not content.startswith(("http://", "https://")):
            raise ProjectError("A url artifact's content must start with http:// or https://.")
    if issue_id is not None and require_issue(session, issue_id).project_id != project_id:
        raise ProjectError("That issue belongs to a different project.")
    artifact = Artifact(
        project_id=project_id,
        issue_id=issue_id,
        title=title,
        kind=kind,
        content=content,
        created_by=actor.handle,
    )
    session.add(artifact)
    session.commit()
    session.refresh(artifact)
    bus.publish(
        {
            "type": "artifact_added",
            "artifact": {"id": artifact.id, "title": artifact.title, "kind": artifact.kind},
            "project_id": project_id,
            "issue_id": issue_id,
            "team_id": project.team_id,
            "by": actor.handle,
        }
    )
    return artifact_view(artifact)
