"""Import every feature module so its tools register on the shared `mcp` instance."""

from app.tools import (
    identity,  # noqa: F401
    messaging,  # noqa: F401
)
