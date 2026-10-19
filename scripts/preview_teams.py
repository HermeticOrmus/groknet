#!/usr/bin/env python3
"""Disposable local team simulator, with real API/HTTP delivery and fake bots.

Run from repo root: backend/.venv/bin/python scripts/preview_teams.py
No production data, remote webhook credentials, or real Grok Bots are used.
"""

import argparse
import asyncio
import json
import os
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8017)
    parser.add_argument(
        "--smoke", action="store_true", help="check the fixture and exit"
    )
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    handles = ("juan", "alejandro", "tomas", "demo-bot")

    class Inbox(BaseHTTPRequestHandler):
        def do_POST(self):
            handle = self.path.rsplit("/", 1)[-1]
            self.rfile.read(int(self.headers.get("Content-Length", "0")))
            ok = handle in handles and handle != "demo-bot"
            ok = (
                ok
                and self.headers.get("Authorization")
                == f"Bearer local-preview-{handle}"
            )
            data = json.dumps({"success": ok}).encode()
            self.send_response(200 if ok else 401)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *_):
            pass

    with tempfile.TemporaryDirectory(prefix="groknet-teams-preview-") as temporary:
        # Must precede importing app.db. This script never resets the normal DB.
        os.environ["DATABASE_URL"] = f"sqlite:///{temporary}/preview.db"
        sys.path.insert(0, str(root / "backend"))
        from app.db import engine, init_db
        from app.main import app
        from app.models import Friendship, FriendshipStatus, User
        from app.registry import register_user
        from app.teams import (
            add_to_team,
            create_team,
            message_history,
            send_team_message,
        )
        from sqlmodel import Session, select
        from starlette.responses import FileResponse, JSONResponse
        from starlette.routing import Route

        inbox = ThreadingHTTPServer(("127.0.0.1", 0), Inbox)
        threading.Thread(target=inbox.serve_forever, daemon=True).start()
        try:
            init_db()
            with Session(engine) as session:
                for handle in handles:
                    register_user(
                        session,
                        handle=handle,
                        display_name=handle.replace("-", " ").title(),
                        email=f"{handle}@mail.grokbot.com",
                        webhook_url=f"http://127.0.0.1:{inbox.server_port}/inbox/{handle}",
                        webhook_key=f"local-preview-{handle}",
                    )
                juan = session.get(User, "juan")
                for handle in handles[1:]:
                    session.add(
                        Friendship(
                            requester="juan",
                            addressee=handle,
                            status=FriendshipStatus.accepted,
                        )
                    )
                session.commit()
                team_id = create_team(session, juan, "Groknet demo").id
                for handle in handles[1:]:
                    add_to_team(session, juan, team_id, handle)
                asyncio.run(
                    send_team_message(
                        session,
                        juan,
                        team_id,
                        "@alejandro, can your bot hear mine? Reply here so the team can see.",
                        ["alejandro"],
                    )
                )
                asyncio.run(
                    send_team_message(
                        session,
                        session.get(User, "alejandro"),
                        team_id,
                        "@juan, yes — your message reached my local simulated inbox.",
                        ["juan"],
                    )
                )
                history = message_history(session, team_id)
                assert len(history) == 2
                assert {r["status"] for r in history[0]["deliveries"]} == {
                    "delivered",
                    "failed",
                }
            if args.smoke:
                print(
                    "TEAM_PREVIEW messages=2 recipient_receipts=6 partial_failure=PASS"
                )
                return

            def file_endpoint(filename):
                async def endpoint(_request):
                    return FileResponse(root / "dashboard" / "public" / filename)

                return endpoint

            for filename in ("teams.html", "teams.js", "teams.css"):
                app.router.routes.insert(
                    0, Route(f"/{filename}", file_endpoint(filename))
                )

            async def simulated_reply(request):
                data = await request.json()
                with Session(engine) as session:
                    sender = session.exec(
                        select(User).where(User.handle == "alejandro")
                    ).one()
                    result = await send_team_message(
                        session,
                        sender,
                        team_id,
                        str(
                            data.get("body", "A new simulated reply arrived over SSE.")
                        ),
                        ["juan"],
                    )
                    return JSONResponse(result)

            app.router.routes.insert(
                0, Route("/_preview/reply", simulated_reply, methods=["POST"])
            )
            import uvicorn

            print(
                f"LOCAL SIMULATOR: http://127.0.0.1:{args.port}/teams.html?demo=1",
                flush=True,
            )
            print(
                "Only fake loopback inboxes. Ctrl-C removes the temporary database.",
                flush=True,
            )
            uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")
        finally:
            inbox.shutdown()
            inbox.server_close()


if __name__ == "__main__":
    main()
