"""Read-only same-origin dashboard preview; no production mutation proxy.

GROKNET_DASHBOARD_UPSTREAM=https://groknet.eastwood.ai \
  backend/.venv/bin/uvicorn dashboard.dev:app --port 8780
"""

import os
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from starlette.background import BackgroundTask

PUBLIC = Path(__file__).parent / "public"
UPSTREAM = os.environ.get("GROKNET_DASHBOARD_UPSTREAM", "http://127.0.0.1:8000").rstrip("/")


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with httpx.AsyncClient(timeout=20) as client:
        app.state.client = client
        yield


app = FastAPI(lifespan=lifespan)
app.mount("/assets", StaticFiles(directory=PUBLIC / "assets"), name="assets")


@app.get("/")
def index():
    return FileResponse(PUBLIC / "index.html")


@app.get("/api/{path:path}")
async def read_api(path: str, request: Request):
    client = request.app.state.client
    url = f"{UPSTREAM}/api/{path}"
    try:
        if path == "events":
            upstream = await client.send(client.build_request("GET", url, timeout=None), stream=True)
            return StreamingResponse(
                upstream.aiter_raw(),
                status_code=upstream.status_code,
                media_type="text/event-stream",
                headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
                background=BackgroundTask(upstream.aclose),
            )
        upstream = await client.get(url, params=request.query_params)
        # Login (#12) is absent on this API, so /api/auth/me is a plain-text 404
        # from the mounted MCP app. Keep that status; do not turn it into a 502
        # or the workroom treats a missing session probe as a failed load.
        try:
            payload = upstream.json()
        except ValueError:
            detail = upstream.text.strip() or "Upstream returned a non-JSON response."
            payload = {"detail": detail}
        return JSONResponse(payload, status_code=upstream.status_code)
    except httpx.HTTPError:
        return JSONResponse({"detail": "Preview backend unavailable."}, status_code=502)
