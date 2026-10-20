"""Dev-only helpers behind /api/dev/* (GROKNET_DEV=1): seed data and fake events.

Lets the dashboard be built and demoed without a single real Grok Bot.
"""

from datetime import timedelta
from typing import Any

from sqlmodel import Session, delete

from app.events import bus
from app.models import (
    Artifact,
    Friendship,
    FriendshipStatus,
    Issue,
    Message,
    Project,
    Team,
    TeamMember,
    User,
    new_id,
    now,
)
from app.team_models import TeamDelivery

SEED_USERS = [
    (
        "tomas",
        "Tomas",
        {
            "age": 34,
            "job": "Founder and backend engineer",
            "bio": "Runs the home lab Groknet is deployed on. Likes bots that ask before acting.",
            "location": "Panama City",
        },
    ),
    (
        "alejandro",
        "Alejandro",
        {
            "age": 31,
            "job": "Product designer",
            "bio": "Owns the command center dashboard and the Groknet bot template.",
            "location": "Mexico City",
        },
    ),
    (
        "juan",
        "Juan",
        {
            "age": 29,
            "job": "Full-stack developer",
            "bio": "Building teams: fan-out, mentions and the channel views.",
            "location": "Bogota",
        },
    ),
    (
        "demo-bot",
        "Demo Bot",
        {
            "job": "Stage prop",
            "bio": "A bot with no human behind it, used to show pending requests on the dashboard.",
        },
    ),
]

SEED_MESSAGES = [
    ("tomas", "alejandro", "The handshake works end to end. Register your bot when you can."),
    ("alejandro", "tomas", "Registered. My bot just pinged me with your friend request."),
    ("tomas", "alejandro", "Accepted on my side. Can you see this relay?"),
    ("alejandro", "tomas", "Loud and clear. Dashboard next."),
    ("juan", "tomas", "Teams schema looks good, starting on fan-out."),
    ("tomas", "juan", "Mentions should be a list of handles, not @-strings."),
    ("juan", "tomas", "Got it. Pushing a branch in a bit."),
    ("alejandro", "juan", "Which stack for the dashboard? Leaning Vite + React."),
    ("juan", "alejandro", "Works for me. Paperclip is too heavy to embed."),
    ("tomas", "alejandro", "Agreed, borrow the look, not the runtime."),
]

# (title, status, assignee, comma-separated mentions, created_by, assignment answer, comment)
SEED_ISSUES = [
    ("Write the demo script", "done", "alejandro", "tomas", "tomas", "accepted", "Drafted it."),
    (
        "Projects board in the dashboard",
        "in_progress",
        "alejandro",
        "juan",
        "tomas",
        "accepted",
        None,
    ),
    ("Issue webhooks in the inbox routine", "open", "juan", "", "alejandro", "pending", None),
    ("Record a backup demo video", "open", None, "alejandro,juan", "juan", None, None),
]


def seed(session: Session) -> dict[str, int]:
    """Wipe and recreate the demo dataset. Idempotent."""
    for table in (
        Artifact,
        Issue,
        Project,
        TeamDelivery,
        Message,
        TeamMember,
        Team,
        Friendship,
        User,
    ):
        session.exec(delete(table))
    session.commit()

    t0 = now() - timedelta(hours=2)
    # `profile` is being added to User on a parallel branch; seed it once the column exists.
    has_profile = "profile" in User.model_fields
    for i, (handle, name, profile) in enumerate(SEED_USERS):
        fields: dict[str, Any] = {
            "handle": handle,
            "display_name": name,
            "email": f"{handle}@mail.grokbot.com",
            "groknet_token": f"seed-token-{handle}",
            "webhook_url": f"https://api2.cursor.sh/automations/webhook/seed-{handle}",
            "webhook_key": f"crsr_seed_{handle}",
            "created_at": t0 + timedelta(minutes=i),
        }
        if has_profile:
            fields["profile"] = profile
        session.add(User(**fields))

    friendships = [
        ("tomas", "alejandro", FriendshipStatus.accepted),
        ("tomas", "juan", FriendshipStatus.accepted),
        ("demo-bot", "tomas", FriendshipStatus.pending),
    ]
    for requester, addressee, status in friendships:
        session.add(Friendship(requester=requester, addressee=addressee, status=status))

    for i, (sender, recipient, body) in enumerate(SEED_MESSAGES):
        session.add(
            Message(
                sender=sender,
                recipient=recipient,
                body=body,
                delivered=True,
                created_at=t0 + timedelta(minutes=10 + i * 5),
            )
        )

    team_id = new_id()
    session.add(Team(id=team_id, name="Groknet core", created_by="tomas"))
    for handle in ("tomas", "alejandro", "juan"):
        session.add(TeamMember(team_id=team_id, user_handle=handle))

    project_id = new_id()
    t1 = t0 + timedelta(minutes=70)
    session.add(
        Project(
            id=project_id,
            team_id=team_id,
            name="Hackathon demo",
            description="Everything we need on stage: the bot handshake, teams, and projects.",
            created_by="tomas",
            created_at=t1,
            updated_at=t1,
        )
    )
    issue_ids = [new_id() for _ in SEED_ISSUES]
    for i, (issue_id, (title, status, assignee, mentions, by, answer, comment)) in enumerate(
        zip(issue_ids, SEED_ISSUES, strict=True)
    ):
        at = t1 + timedelta(minutes=2 + i * 3)
        session.add(
            Issue(
                id=issue_id,
                project_id=project_id,
                title=title,
                status=status,
                assignee=assignee,
                mentions=mentions,
                assignment_status=answer,
                assignment_comment=comment,
                assigned_by=by if assignee else None,
                created_by=by,
                created_at=at,
                updated_at=at,
            )
        )
    session.add(
        Artifact(
            project_id=project_id,
            issue_id=issue_ids[0],
            title="Demo script",
            kind="markdown",
            content="# Demo script\n\n1. Register two bots.\n2. Befriend.\n3. Relay a message.",
            created_by="alejandro",
            created_at=t1 + timedelta(minutes=20),
        )
    )
    session.add(
        Artifact(
            project_id=project_id,
            title="Repository",
            kind="url",
            content="https://github.com/sudoTomas/groknet",
            created_by="tomas",
            created_at=t1 + timedelta(minutes=21),
        )
    )
    session.commit()

    return {
        "users": len(SEED_USERS),
        "friendships": len(friendships),
        "messages": len(SEED_MESSAGES),
        "teams": 1,
        "team_members": 3,
        "projects": 1,
        "issues": len(SEED_ISSUES),
        "artifacts": 2,
    }


FAKE_EVENTS: dict[str, dict[str, Any]] = {
    "user_registered": {"handle": "demo-bot", "display_name": "Demo Bot"},
    "user_reregistered": {"handle": "demo-bot", "display_name": "Demo Bot"},
    "friend_request": {"from": "demo-bot", "to": "tomas", "friendship_id": "seed-fr-1"},
    "friend_accepted": {"from": "tomas", "to": "demo-bot", "friendship_id": "seed-fr-1"},
    "friend_declined": {"from": "tomas", "to": "demo-bot", "friendship_id": "seed-fr-1"},
    "message": {
        "event_id": "seed-evt-1",
        "from": "demo-bot",
        "to": "tomas",
        "body": "Hello from the fake event emitter.",
    },
    "team_message": {
        "event_id": "seed-evt-2",
        "from": "tomas",
        "team": {"id": "seed-team", "name": "Groknet core"},
        "body": "Team, the demo is live.",
        "mentions": ["juan"],
    },
    "project_created": {
        "project": {"id": "seed-project", "name": "Hackathon demo"},
        "team_id": "seed-team",
        "by": "tomas",
    },
    "project_updated": {
        "project_id": "seed-project",
        "team_id": "seed-team",
        "by": "tomas",
        "changes": ["status"],
    },
    "issue_created": {
        "issue": {
            "id": "seed-issue",
            "title": "Write the demo script",
            "status": "open",
            "assignee": "alejandro",
            "assignment_status": "pending",
            "assignment_comment": None,
        },
        "project_id": "seed-project",
        "team_id": "seed-team",
        "by": "tomas",
    },
    "issue_updated": {
        "issue_id": "seed-issue",
        "project_id": "seed-project",
        "team_id": "seed-team",
        "by": "alejandro",
        "changes": ["status"],
        "status": "in_progress",
        "assignee": "alejandro",
        "assignment_status": "accepted",
        "assignment_comment": None,
    },
    "issue_response": {
        "issue_id": "seed-issue",
        "project_id": "seed-project",
        "team_id": "seed-team",
        "by": "alejandro",
        "assignment_status": "accepted",
        "comment": "On it after lunch.",
    },
    "artifact_added": {
        "artifact": {"id": "seed-artifact", "title": "Demo script", "kind": "markdown"},
        "project_id": "seed-project",
        "issue_id": "seed-issue",
        "team_id": "seed-team",
        "by": "alejandro",
    },
    "delivery": {
        "event_id": "seed-evt-1",
        "event_type": "message",
        "to": "tomas",
        "ok": True,
        "status": 200,
    },
}


def emit(event_type: str, overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    """Publish one fake event of `event_type` on the bus. Unknown types get only the overrides."""
    event: dict[str, Any] = {"type": event_type, **FAKE_EVENTS.get(event_type, {})}
    event.update(overrides or {})
    event.setdefault("at", now())
    bus.publish(event)
    return event
