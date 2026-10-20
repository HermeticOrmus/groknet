"""REST team tool mirrors; dashboard reads follow the app's shared read policy."""

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app import teams
from app.auth import current_actor
from app.rest import SessionDep, UserDep

router = APIRouter(prefix="/api/teams", tags=["teams"])


class CreateTeam(BaseModel):
    name: str


class AddMember(BaseModel):
    handle: str


class SendTeamMessage(BaseModel):
    body: str
    mentions: list[str] = Field(default_factory=list)


def rejected(exc: teams.TeamError) -> HTTPException:
    return HTTPException(exc.status_code, str(exc))


@router.post("")
def create_team(data: CreateTeam, session: SessionDep, user: UserDep):
    try:
        return {"team_id": teams.create_team(session, user, data.name).id}
    except teams.TeamError as exc:
        raise rejected(exc) from exc


@router.post("/{team_id}/members")
def add_member(team_id: str, data: AddMember, session: SessionDep, user: UserDep):
    try:
        return {"members": teams.add_to_team(session, user, team_id, data.handle)}
    except teams.TeamError as exc:
        raise rejected(exc) from exc


@router.post("/{team_id}/messages")
async def send_message(team_id: str, data: SendTeamMessage, session: SessionDep, user: UserDep):
    try:
        return await teams.send_team_message(session, user, team_id, data.body, data.mentions)
    except teams.TeamError as exc:
        raise rejected(exc) from exc


@router.get("/{team_id}/messages", dependencies=[Depends(current_actor)])
def history(team_id: str, session: SessionDep, limit: int = Query(200, ge=1, le=200)):
    try:
        return teams.message_history(session, team_id, limit)
    except teams.TeamError as exc:
        raise rejected(exc) from exc
