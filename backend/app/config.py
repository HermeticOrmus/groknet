import logging
import os
import secrets

DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./groknet.db")
PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL", "https://groknet.eastwood.ai")
# GROKNET_DEV=1 enables /api/dev/* (seed data, fake events). Never set in production.
DEV_MODE = os.environ.get("GROKNET_DEV", "") == "1"

# Signs the dashboard session cookie (issue #12). Unset means a random per-process
# secret, so every restart logs everyone out; set it in production.
SESSION_SECRET = os.environ.get("SESSION_SECRET", "")
if not SESSION_SECRET:
    logging.getLogger("groknet.config").warning(
        "SESSION_SECRET is not set; using a random one. Dashboard sessions end on restart."
    )
    SESSION_SECRET = secrets.token_urlsafe(32)
