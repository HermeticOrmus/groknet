"""REST for projects, issues and artifacts (issue #32).

Auth is `current_actor`: a bot's `Authorization: Bearer <groknet_token>` or the dashboard's
session cookie. Reads need any actor; writes also need membership of the project's team.
Errors come from app/projects.py and app/teams.py through the GroknetError handler:
400 invalid input, 401 no actor, 403 non-member, 404 unknown id.
"""

from typing import Annotated, Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlmodel import Session

from app import projects
from app.auth import current_actor
from app.db import get_session
from app.models import User

router = APIRouter(prefix="/api", tags=["projects"])
SessionDep = Annotated[Session, Depends(get_session)]
ActorDep = Annotated[User, Depends(current_actor)]


class CreateProject(BaseModel):
    team_id: str
    name: str
    description: str = ""


class PatchProject(BaseModel):
    name: str | None = None
    description: str | None = None
    status: str | None = None


class CreateIssue(BaseModel):
    title: str
    description: str = ""
    assignee: str | None = None
    mentions: list[str] = Field(default_factory=list)


class PatchIssue(BaseModel):
    title: str | None = None
    description: str | None = None
    status: str | None = None
    assignee: str | None = None
    mentions: list[str] | None = None


class CreateArtifact(BaseModel):
    title: str
    kind: str
    content: str
    issue_id: str | None = None


def _sent(body: BaseModel, nullable: tuple[str, ...] = ()) -> dict[str, Any]:
    """The fields the client actually sent. An explicit null only counts where it means
    something (assignee: null clears); elsewhere it is ignored like an absent field."""
    sent = body.model_dump(exclude_unset=True)
    return {k: v for k, v in sent.items() if v is not None or k in nullable}


@router.get("/projects")
def list_projects(session: SessionDep, _: ActorDep, team_id: str | None = None):
    return projects.list_projects(session, team_id)


@router.post("/projects", status_code=201)
def create_project(data: CreateProject, session: SessionDep, actor: ActorDep):
    return projects.create_project(session, actor, data.team_id, data.name, data.description)


@router.get("/projects/{project_id}")
def get_project(project_id: str, session: SessionDep, _: ActorDep):
    return projects.project_detail(session, project_id)


@router.patch("/projects/{project_id}")
def patch_project(project_id: str, data: PatchProject, session: SessionDep, actor: ActorDep):
    return projects.update_project(session, actor, project_id, _sent(data))


@router.get("/projects/{project_id}/issues")
def list_issues(project_id: str, session: SessionDep, _: ActorDep, status: str | None = None):
    return projects.list_issues(session, project_id, status)


@router.post("/projects/{project_id}/issues", status_code=201)
async def create_issue(project_id: str, data: CreateIssue, session: SessionDep, actor: ActorDep):
    return await projects.create_issue(
        session, actor, project_id, data.title, data.description, data.assignee, data.mentions
    )


@router.patch("/issues/{issue_id}")
async def patch_issue(issue_id: str, data: PatchIssue, session: SessionDep, actor: ActorDep):
    return await projects.update_issue(session, actor, issue_id, _sent(data, ("assignee",)))


@router.get("/projects/{project_id}/artifacts")
def list_artifacts(project_id: str, session: SessionDep, _: ActorDep):
    return projects.list_artifacts(session, project_id)


@router.post("/projects/{project_id}/artifacts", status_code=201)
def add_artifact(project_id: str, data: CreateArtifact, session: SessionDep, actor: ActorDep):
    return projects.add_artifact(
        session, actor, project_id, data.title, data.content, data.kind, data.issue_id
    )
