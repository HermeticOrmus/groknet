"""REST surface.

/api/health              liveness
/api/users ...           dashboard read API (TODO: fill in; returns live DB rows, never credentials)
/api/events              SSE stream of everything the backend sends to bots
Mirrors of the MCP tools under /api (TODO, issue: REST mirror).
"""

import asyncio
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlmodel import Session, select

from app.db import get_session
from app.events import bus
from app.models import Friendship, Message, User
from app.teams import list_teams as read_teams

router = APIRouter(prefix="/api")
SessionDep = Annotated[Session, Depends(get_session)]


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "groknet"}


@router.get("/users")
def list_users(session: SessionDep) -> list[dict]:
    return [
        {"handle": u.handle, "display_name": u.display_name, "created_at": u.created_at}
        for u in session.exec(select(User)).all()
    ]


@router.get("/friendships")
def list_friendships(session: SessionDep) -> list[Friendship]:
    return list(session.exec(select(Friendship)).all())


@router.get("/messages")
def list_messages(session: SessionDep) -> list[Message]:
    return list(session.exec(select(Message).order_by(Message.created_at.desc()).limit(200)).all())


@router.get("/teams")
def list_teams(session: SessionDep) -> list[dict]:
    return read_teams(session)


@router.get("/events")
async def events() -> StreamingResponse:
    q = bus.subscribe()

    async def stream() -> AsyncIterator[str]:
        try:
            yield ": connected\n\n"
            while True:
                try:
                    data = await asyncio.wait_for(q.get(), timeout=20)
                    yield f"data: {data}\n\n"
                except TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            bus.unsubscribe(q)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
