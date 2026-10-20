"""Same-origin dashboard preview. Not part of the production image (nginx serves public/).

GROKNET_DASHBOARD_UPSTREAM=http://127.0.0.1:8000 \
  backend/.venv/bin/uvicorn dashboard.dev:app --port 8780

GET, POST and PATCH under /api are forwarded with the browser's cookie and body,
and upstream Set-Cookie is passed back, so login and dashboard writes work through
the preview. GROKNET_DASHBOARD_MOCK=1 serves in-memory projects/issues/artifacts
fixtures (issue #32 shapes) from dashboard/dev_mock.py for backends without them.
"""

import os
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI, Request, Response
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from starlette.background import BackgroundTask

PUBLIC = Path(__file__).parent / "public"
UPSTREAM = os.environ.get("GROKNET_DASHBOARD_UPSTREAM", "http://127.0.0.1:8000").rstrip("/")
MOCK = os.environ.get("GROKNET_DASHBOARD_MOCK") == "1"


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with httpx.AsyncClient(timeout=20) as client:
        app.state.client = client
        app.state.upstream = UPSTREAM
        yield


app = FastAPI(lifespan=lifespan)
app.mount("/assets", StaticFiles(directory=PUBLIC / "assets"), name="assets")

if MOCK:
    from dashboard.dev_mock import router as mock_router

    app.include_router(mock_router)


@app.get("/")
def index():
    return FileResponse(PUBLIC / "index.html")


def _forward_headers(request: Request) -> dict[str, str]:
    keep = ("cookie", "content-type", "authorization")
    return {k: v for k, v in request.headers.items() if k.lower() in keep}


@app.api_route("/api/{path:path}", methods=["GET", "POST", "PATCH"])
async def proxy_api(path: str, request: Request):
    client = request.app.state.client
    url = f"{UPSTREAM}/api/{path}"
    headers = _forward_headers(request)
    try:
        if path == "events":
            upstream = await client.send(
                client.build_request("GET", url, headers=headers, timeout=None), stream=True
            )
            return StreamingResponse(
                upstream.aiter_raw(),
                status_code=upstream.status_code,
                media_type="text/event-stream",
                headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
                background=BackgroundTask(upstream.aclose),
            )
        upstream = await client.request(
            request.method,
            url,
            params=request.query_params,
            headers=headers,
            content=await request.body() if request.method != "GET" else None,
        )
        # A missing route can be a plain-text 404 from the mounted MCP app. Keep the
        # status; do not turn it into a 502 or the workroom treats it as a failed load.
        try:
            payload = upstream.json()
        except ValueError:
            detail = upstream.text.strip() or "Upstream returned a non-JSON response."
            payload = {"detail": detail}
        response: Response = JSONResponse(payload, status_code=upstream.status_code)
        for cookie in upstream.headers.get_list("set-cookie"):
            response.headers.append("set-cookie", cookie)
        return response
    except httpx.HTTPError:
        return JSONResponse({"detail": "Preview backend unavailable."}, status_code=502)
