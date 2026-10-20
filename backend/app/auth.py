"""Dashboard login (issue #12).

Identity is the bot's email. Only a registered User whose email ends with
@mail.grokbot.com can log in. The 6-digit code is not emailed: it is delivered as a
`login_code` event to the user's own inbox routine, the bot relays it to its human,
and the human types it into the dashboard. That proves ownership of the bot.

POST /api/auth/start  {email}        -> 200 {"sent": true}, code delivered to the bot
POST /api/auth/verify {email, code}  -> 200 {handle, display_name, email} + session cookie
GET  /api/auth/me                    -> same shape, or 401
POST /api/auth/logout                -> clears the cookie

`current_dashboard_user` is the dependency other routers use to require a session.
"""

import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from itsdangerous import BadSignature, URLSafeTimedSerializer
from pydantic import BaseModel
from sqlmodel import Session, select

from app import config, webhooks
from app.db import get_session
from app.events import bus
from app.models import LoginCode, User, now
from app.registry import ALLOWED_EMAIL_DOMAIN

router = APIRouter(prefix="/api/auth", tags=["auth"])
SessionDep = Annotated[Session, Depends(get_session)]

COOKIE_NAME = "groknet_session"
SESSION_MAX_AGE_S = 7 * 24 * 3600
CODE_TTL = timedelta(minutes=10)
RATE_LIMIT_WINDOW = timedelta(minutes=10)
RATE_LIMIT_MAX_STARTS = 5

_signer = URLSafeTimedSerializer(config.SESSION_SECRET, salt="groknet-dashboard-session")


class StartBody(BaseModel):
    email: str


class VerifyBody(BaseModel):
    email: str
    code: str


def _normalize(email: str) -> str:
    return email.strip().lower()


def _hash(code: str) -> str:
    return hashlib.sha256(code.encode()).hexdigest()


def _aware(dt: datetime) -> datetime:
    # SQLite hands datetimes back naive; they were written as UTC.
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def _public(user: User) -> dict[str, str]:
    return {"handle": user.handle, "display_name": user.display_name, "email": user.email}


def _refuse(status: int, detail: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"sent": False, "detail": detail})


@router.post("/start", response_model=None)
async def start(body: StartBody, session: SessionDep) -> dict[str, Any] | JSONResponse:
    email = _normalize(body.email)
    if not email.endswith(ALLOWED_EMAIL_DOMAIN) or email == ALLOWED_EMAIL_DOMAIN:
        return _refuse(400, f"Only Grok Bot addresses ending in {ALLOWED_EMAIL_DOMAIN} can log in.")
    user = session.exec(select(User).where(User.email == email)).first()
    if user is None:
        return _refuse(
            400, f"No bot is registered with {email}. Register your bot on Groknet first."
        )

    codes = session.exec(select(LoginCode).where(LoginCode.email == email)).all()
    cutoff = now() - RATE_LIMIT_WINDOW
    if sum(_aware(c.created_at) >= cutoff for c in codes) >= RATE_LIMIT_MAX_STARTS:
        return _refuse(429, "Too many login codes requested. Wait a few minutes and try again.")

    for old in codes:  # only one active code per email
        if not old.used:
            old.used = True
            session.add(old)
    code = f"{secrets.randbelow(10**6):06d}"
    session.add(LoginCode(email=email, code_hash=_hash(code), expires_at=now() + CODE_TTL))
    session.commit()

    bus.publish({"type": "login_requested", "handle": user.handle})
    minutes = int(CODE_TTL.total_seconds() // 60)
    ok = await webhooks.deliver(
        user,
        event_type="login_code",
        sender=user,
        payload={
            "code": code,
            "expires_in_minutes": minutes,
            "message": f"Your Groknet dashboard login code is {code}. "
            "If you did not request it, ignore this.",
        },
    )
    if not ok:
        return _refuse(502, "Could not reach your bot's Groknet inbox routine. Is it enabled?")
    return {"sent": True}


@router.post("/verify")
def verify(body: VerifyBody, response: Response, session: SessionDep) -> dict[str, str]:
    email = _normalize(body.email)
    active = session.exec(
        select(LoginCode).where(LoginCode.email == email, LoginCode.used == False)
    ).first()
    if (
        active is None
        or _aware(active.expires_at) <= now()
        or not hmac.compare_digest(active.code_hash, _hash(body.code.strip()))
    ):
        raise HTTPException(401, "Invalid or expired code. Request a new one.")
    user = session.exec(select(User).where(User.email == email)).first()
    if user is None:
        raise HTTPException(401, "Invalid or expired code. Request a new one.")
    active.used = True
    session.add(active)
    session.commit()

    response.set_cookie(
        COOKIE_NAME,
        _signer.dumps(user.handle),
        max_age=SESSION_MAX_AGE_S,
        httponly=True,
        samesite="lax",
        secure=config.PUBLIC_BASE_URL.startswith("https"),
    )
    bus.publish({"type": "login_succeeded", "handle": user.handle})
    return _public(user)


def current_dashboard_user(request: Request, session: SessionDep) -> User:
    """Dependency: the logged-in dashboard human, or 401."""
    token = request.cookies.get(COOKIE_NAME)
    if token:
        try:
            handle = _signer.loads(token, max_age=SESSION_MAX_AGE_S)
        except BadSignature:
            handle = None
        user = session.get(User, handle) if handle else None
        if user is not None:
            return user
    raise HTTPException(401, "Not logged in.")


@router.get("/me")
def me(user: Annotated[User, Depends(current_dashboard_user)]) -> dict[str, str]:
    return _public(user)


@router.post("/logout")
def logout(response: Response) -> dict[str, bool]:
    response.delete_cookie(
        COOKIE_NAME,
        httponly=True,
        samesite="lax",
        secure=config.PUBLIC_BASE_URL.startswith("https"),
    )
    return {"ok": True}
