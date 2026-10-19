from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api import router as api_router
from app.db import init_db
from app.mcp_server import mcp, mcp_app


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    # A mounted sub-app's lifespan never runs, so we drive the MCP session manager here.
    async with mcp.session_manager.run():
        yield


app = FastAPI(title="Groknet", version="0.1.0", lifespan=lifespan)
app.include_router(api_router)
# Mounted last and at the root so /mcp is matched exactly; /api routes above win first.
app.mount("/", mcp_app)
