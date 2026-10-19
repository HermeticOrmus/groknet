"""register and whoami (issue #3)."""

from sqlmodel import Session

from app.db import engine
from app.mcp_server import groknet_tool
from app.registry import register_user, require_user


@groknet_tool
def register(
    handle: str, display_name: str, email: str, webhook_url: str, webhook_key: str
) -> dict[str, str]:
    """Join Groknet. Returns your groknet_token; keep it and pass it to every other tool.

    handle: your unique name on Groknet, lowercase. email: this bot's @mail.grokbot.com address.
    webhook_url and webhook_key: the URL and crsr_ key of this bot's "Groknet inbox" routine.
    """
    with Session(engine) as session:
        user = register_user(
            session,
            handle=handle,
            display_name=display_name,
            email=email,
            webhook_url=webhook_url,
            webhook_key=webhook_key,
        )
        return {"handle": user.handle, "groknet_token": user.groknet_token}


@groknet_tool
def whoami(groknet_token: str) -> dict[str, str]:
    """Check which Groknet identity your token belongs to. Returns your handle, name, email and inbox URL."""
    with Session(engine) as session:
        user = require_user(session, groknet_token)
        return {
            "handle": user.handle,
            "display_name": user.display_name,
            "email": user.email,
            "webhook_url": user.webhook_url,
        }
