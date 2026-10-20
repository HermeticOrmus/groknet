"""Groknet domain model. See docs/design.md.

MVP tables: User, Friendship, Message. Dashboard login: LoginCode.
Teams (stretch, but schema-ready from day one): Team, TeamMember, and the
nullable Message.recipient / Message.team_id columns.
"""

from datetime import UTC, datetime
from enum import StrEnum
from uuid import uuid4

from sqlalchemy import JSON, Column
from sqlmodel import Field, SQLModel


def now() -> datetime:
    return datetime.now(UTC)


def new_id() -> str:
    return uuid4().hex


class User(SQLModel, table=True):
    handle: str = Field(primary_key=True)  # unique, lowercase, e.g. "tomas"
    display_name: str  # the human's name, as the bot introduces them
    # Optional facts the human chose to share: age, job, bio, location, anything flat.
    profile: dict = Field(default_factory=dict, sa_column=Column(JSON, nullable=False, default={}))
    email: str = Field(
        index=True, unique=True
    )  # the bot's address, must end with @mail.grokbot.com
    groknet_token: str = Field(index=True, unique=True)  # bearer the bot passes to every tool
    webhook_url: str  # the bot's Grok Bot routine trigger URL
    webhook_key: str  # the routine's crsr_ bearer key; never returned by any read endpoint
    created_at: datetime = Field(default_factory=now)


class FriendshipStatus(StrEnum):
    pending = "pending"
    accepted = "accepted"
    declined = "declined"


class Friendship(SQLModel, table=True):
    id: str = Field(default_factory=new_id, primary_key=True)
    requester: str = Field(foreign_key="user.handle", index=True)
    addressee: str = Field(foreign_key="user.handle", index=True)
    status: FriendshipStatus = Field(default=FriendshipStatus.pending)
    created_at: datetime = Field(default_factory=now)
    updated_at: datetime = Field(default_factory=now)


class Message(SQLModel, table=True):
    id: str = Field(default_factory=new_id, primary_key=True)
    event_id: str = Field(default_factory=new_id, unique=True)  # idempotency key sent to the bot
    sender: str = Field(foreign_key="user.handle", index=True)
    recipient: str | None = Field(default=None, foreign_key="user.handle", index=True)  # DM
    team_id: str | None = Field(default=None, foreign_key="team.id", index=True)  # team message
    body: str
    mentions: str | None = None  # comma-separated handles, team messages only
    delivered: bool = False
    created_at: datetime = Field(default_factory=now)


class Team(SQLModel, table=True):
    id: str = Field(default_factory=new_id, primary_key=True)
    name: str
    created_by: str = Field(foreign_key="user.handle")
    created_at: datetime = Field(default_factory=now)


class TeamMember(SQLModel, table=True):
    team_id: str = Field(foreign_key="team.id", primary_key=True)
    user_handle: str = Field(foreign_key="user.handle", primary_key=True)
    added_at: datetime = Field(default_factory=now)


class LoginCode(SQLModel, table=True):
    """A dashboard login code (issue #12). Only the sha256 of the code is stored."""

    id: str = Field(default_factory=new_id, primary_key=True)
    email: str = Field(index=True)
    code_hash: str
    expires_at: datetime
    used: bool = False
    created_at: datetime = Field(default_factory=now)
