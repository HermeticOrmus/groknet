import os

DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./groknet.db")
PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL", "https://groknet.eastwood.ai")
# GROKNET_DEV=1 enables /api/dev/* (seed data, fake events). Never set in production.
DEV_MODE = os.environ.get("GROKNET_DEV", "") == "1"
