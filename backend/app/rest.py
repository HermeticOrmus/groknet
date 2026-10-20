"""REST mirror of the MCP tools (issue #6), for curl, scripts and tests.

Same service functions as app/tools/*, so the rules are identical. Auth is
`Authorization: Bearer <groknet_token>` instead of a `groknet_token` argument.
A GroknetError becomes 400 {"detail": message}, an AuthError 401 (handlers in main.py).
"""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel
from sqlmodel import Session

from app import friendships, messaging, teams
from app.db import get_session
from app.errors import AuthError, GroknetError
from app.models import User
from app.registry import register_user, require_user

router = APIRouter(prefix="/api", tags=["mirror"])
SessionDep = Annotated[Session, Depends(get_session)]
_bearer = HTTPBearer(auto_error=False)


def current_user(
    session: SessionDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> User:
    if credentials is None:
        raise AuthError("Missing Authorization: Bearer <groknet_token> header.")
    return require_user(session, credentials.credentials)


UserDep = Annotated[User, Depends(current_user)]


class RegisterBody(BaseModel):
    handle: str
    display_name: str
    email: str
    webhook_url: str
    webhook_key: str
    profile: dict[str, str | int] | None = None


class HandleBody(BaseModel):
    handle: str


class RespondBody(BaseModel):
    handle: str
    accept: bool


class MessageBody(BaseModel):
    handle: str
    body: str


class TeamBody(BaseModel):
    name: str


class TeamMessageBody(BaseModel):
    body: str
    mentions: list[str] | None = None


@router.post("/register", status_code=201)
def register(body: RegisterBody, session: SessionDep) -> dict[str, str]:
    user = register_user(session, **body.model_dump())
    return {"handle": user.handle, "groknet_token": user.groknet_token}


@router.get("/me")
def me(user: UserDep) -> dict[str, Any]:
    return {
        "handle": user.handle,
        "display_name": user.display_name,
        "profile": user.profile,
        "email": user.email,
        "webhook_url": user.webhook_url,
    }


@router.get("/search")
def search(user: UserDep, session: SessionDep, q: str = "") -> list[dict[str, Any]]:
    return [
        {"handle": u.handle, "display_name": u.display_name, "profile": u.profile or {}}
        for u in friendships.search_users(session, user, q)
    ]


@router.post("/friends/request")
async def friend_request(body: HandleBody, user: UserDep, session: SessionDep) -> dict[str, str]:
    friendship = await friendships.send_friend_request(session, user, body.handle)
    return {"friendship_id": friendship.id, "status": friendship.status}


@router.post("/friends/respond")
async def friend_respond(body: RespondBody, user: UserDep, session: SessionDep) -> dict[str, str]:
    friendship = await friendships.respond_to_friend_request(
        session, user, body.handle, body.accept
    )
    return {"status": friendship.status}


@router.post("/messages")
async def send_message(
    body: MessageBody, user: UserDep, session: SessionDep
) -> dict[str, str | bool]:
    message = await messaging.send_message(session, user, body.handle, body.body)
    return {"event_id": message.event_id, "delivered": message.delivered}


@router.post("/teams")
def create_team(body: TeamBody, user: UserDep, session: SessionDep) -> dict[str, Any]:
    team = teams.create_team(session, user, body.name)
    return {"team_id": team.id, "name": team.name, "members": [user.handle]}


@router.post("/teams/{team_id}/members")
def add_to_team(
    team_id: str, body: HandleBody, user: UserDep, session: SessionDep
) -> dict[str, Any]:
    return {"team_id": team_id, "members": teams.add_to_team(session, user, team_id, body.handle)}


@router.post("/teams/{team_id}/messages")
async def send_team_message(
    team_id: str, body: TeamMessageBody, user: UserDep, session: SessionDep
) -> dict[str, Any]:
    message, delivered_to, failed = await teams.send_team_message(
        session, user, team_id, body.body, body.mentions
    )
    return {"event_id": message.event_id, "delivered_to": delivered_to, "failed": failed}


def groknet_error_handler(_: Request, exc: Exception) -> JSONResponse:
    status = 401 if isinstance(exc, AuthError) else 400
    return JSONResponse(status_code=status, content={"detail": str(exc)})


EXCEPTION_HANDLERS = {GroknetError: groknet_error_handler}
