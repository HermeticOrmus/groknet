#!/usr/bin/env python3
"""Stand-in for a Grok Bot's "Groknet inbox" webhook routine. Standard library only.

    scripts/fake_bot.py <name> <port> [--fail 400|401|503[,503,...]]

Accepts POST on any path, expects `Authorization: Bearer crsr_<name>`, prints each
event, and answers like the real trigger: 200 + {"success": true, "runUuid": ...}.
`--fail` scripts the status codes of the first N requests (e.g. `--fail 503,503`
makes the first two requests fail with 503 so you can watch the sender retry).
Register the matching user with:

    webhook_url = http://localhost:<port>/automations/webhook/<name>
    webhook_key = crsr_<name>
"""

import argparse
import json
import sys
import uuid
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("name", help="bot name; the expected bearer key is crsr_<name>")
    ap.add_argument("port", type=int)
    ap.add_argument(
        "--host",
        default="127.0.0.1",
        help="bind address; use 0.0.0.0 when the backend runs in Docker and reaches you via the bridge gateway",
    )
    ap.add_argument(
        "--fail",
        default="",
        help="comma-separated status codes to return for the first requests, e.g. 503,503 or 401",
    )
    args = ap.parse_args()

    expected_key = f"crsr_{args.name}"
    scripted = [int(c) for c in args.fail.split(",") if c.strip()]
    received: list[dict] = []

    class Handler(BaseHTTPRequestHandler):
        def _reply(self, status: int, body: dict) -> None:
            data = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_POST(self) -> None:  # noqa: N802
            raw = self.rfile.read(int(self.headers.get("Content-Length", "0")))
            stamp = datetime.now(UTC).strftime("%H:%M:%S")
            auth = self.headers.get("Authorization", "")

            if auth != f"Bearer {expected_key}":
                print(f"[{stamp}] {args.name}: 401 bad key {auth!r}", flush=True)
                self._reply(401, {"code": "error", "message": "Invalid API key"})
                return

            if scripted:
                status = scripted.pop(0)
                print(f"[{stamp}] {args.name}: scripted failure -> {status}", flush=True)
                if status == 400:
                    self._reply(400, {"success": False, "error": f"Automation {args.name} is disabled"})
                elif status == 401:
                    self._reply(401, {"code": "error", "message": "Invalid API key"})
                else:
                    self._reply(status, {"error": "temporarily unavailable"})
                return

            try:
                event = json.loads(raw)
            except json.JSONDecodeError:
                self._reply(400, {"success": False, "error": "invalid JSON"})
                return

            received.append(event)
            sender = event.get("from", {})
            print(
                f"[{stamp}] {args.name} <- {event.get('type', '?')} from "
                f"{sender.get('handle', '?')} ({sender.get('display_name', '')})"
                f"  event_id={event.get('event_id', '?')}",
                flush=True,
            )
            payload = event.get("payload") or {}
            if payload:
                print("    " + json.dumps(payload, ensure_ascii=False), flush=True)
            self._reply(200, {"success": True, "runUuid": uuid.uuid4().hex})

        def do_GET(self) -> None:  # noqa: N802
            # Handy for demo.sh: dump everything this bot has received so far.
            self._reply(200, {"bot": args.name, "received": received})

        def log_message(self, *_: object) -> None:
            pass

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(
        f"fake bot {args.name!r} listening on http://{args.host}:{args.port}/automations/webhook/{args.name}"
        f"  (key crsr_{args.name})",
        flush=True,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        sys.exit(0)


if __name__ == "__main__":
    main()
