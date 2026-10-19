from contextlib import asynccontextmanager

from fastapi import FastAPI
from mcp.server.transport_security import TransportSecuritySettings

import app.tools
from app.api import router as api_router
from app.db import init_db
from app.mcp_server import mcp
from app.rest import EXCEPTION_HANDLERS
from app.rest import router as rest_router

# DNS-rebinding protection is off because cloudflared fronts us and the Host
# header is groknet.eastwood.ai, not 127.0.0.1. Path is /mcp inside the sub-app,
# which is mounted at "/": a Mount at /mcp would 307-redirect POST /mcp to /mcp/,
# and MCP clients do not follow redirects on POST.
mcp_app = mcp.streamable_http_app(
    streamable_http_path="/mcp",
    json_response=True,
    stateless_http=True,
    transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    # A mounted sub-app's lifespan never runs, so we drive the MCP session manager here.
    async with mcp.session_manager.run():
        yield


app = FastAPI(
    title="Groknet", version="0.1.0", lifespan=lifespan, exception_handlers=EXCEPTION_HANDLERS
)
app.include_router(api_router)
app.include_router(rest_router)
# Mounted last and at the root so /mcp is matched exactly; /api routes above win first.
app.mount("/", mcp_app)
