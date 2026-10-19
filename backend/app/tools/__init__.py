"""Import every feature module so its tools register on the shared `mcp` instance."""

from app.tools import (
    friendships,  # noqa: F401
    identity,  # noqa: F401
)
