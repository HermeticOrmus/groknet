"""REST team tool mirrors; dashboard reads follow the app's shared read policy."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field
from sqlmodel import Session

from app import teams
from app.db import get_session
from app.errors import AuthError
from app.models import User
from app.registry import require_user

router = APIRouter(prefix="/api/teams", tags=["teams"])
SessionDep = Annotated[Session, Depends(get_session)]
bearer = HTTPBearer(auto_error=False)


class CreateTeam(BaseModel):
    name: str


class AddMember(BaseModel):
    handle: str


class SendTeamMessage(BaseModel):
    body: str
    mentions: list[str] = Field(default_factory=list)


def caller(
    session: SessionDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> User:
    if credentials is None:
        raise HTTPException(401, "Bearer groknet_token required.")
    try:
        return require_user(session, credentials.credentials)
    except AuthError as exc:
        raise HTTPException(401, str(exc)) from exc


CallerDep = Annotated[User, Depends(caller)]


def rejected(exc: teams.TeamError) -> HTTPException:
    return HTTPException(exc.status_code, str(exc))


@router.post("")
def create_team(data: CreateTeam, session: SessionDep, user: CallerDep):
    try:
        return {"team_id": teams.create_team(session, user, data.name).id}
    except teams.TeamError as exc:
        raise rejected(exc) from exc


@router.post("/{team_id}/members")
def add_member(team_id: str, data: AddMember, session: SessionDep, user: CallerDep):
    try:
        return {"members": teams.add_to_team(session, user, team_id, data.handle)}
    except teams.TeamError as exc:
        raise rejected(exc) from exc


@router.post("/{team_id}/messages")
async def send_message(team_id: str, data: SendTeamMessage, session: SessionDep, user: CallerDep):
    try:
        return await teams.send_team_message(session, user, team_id, data.body, data.mentions)
    except teams.TeamError as exc:
        raise rejected(exc) from exc


@router.get("/{team_id}/messages")
def history(team_id: str, session: SessionDep, limit: int = Query(200, ge=1, le=200)):
    try:
        return teams.message_history(session, team_id, limit)
    except teams.TeamError as exc:
        raise rejected(exc) from exc
