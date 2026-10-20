"""Persistent recipient receipts for a single logical team message."""

from datetime import datetime

from sqlmodel import Field, SQLModel

from app.models import now


class TeamDelivery(SQLModel, table=True):
    event_id: str = Field(foreign_key="message.event_id", primary_key=True)
    recipient: str = Field(foreign_key="user.handle", primary_key=True)
    status: str = "pending"
    revision: int = 1
    updated_at: datetime = Field(default_factory=now)
