import os

DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./groknet.db")
PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL", "https://groknet.eastwood.ai")
