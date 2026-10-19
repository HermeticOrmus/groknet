#!/usr/bin/env python3
"""Push-to-main auto-deploy receiver for Groknet. Standard library only.

GitHub POSTs a `push` event here (through the cloudflared tunnel at
https://groknet.eastwood.ai/_deploy/github). We verify the HMAC signature,
ignore everything that is not a push to main, and run deploy.sh in the
background. GitHub gets a 202 immediately; the build can take minutes.

Env (from /home/tomas/containers/groknet/.env via systemd EnvironmentFile):
  GITHUB_WEBHOOK_SECRET  required
  REPO_DIR               default /home/tomas/containers/groknet
  DEPLOY_PORT            default 9797
"""

import hashlib
import hmac
import json
import os
import subprocess
import sys
import threading
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

SECRET = os.environ.get("GITHUB_WEBHOOK_SECRET", "").encode()
REPO_DIR = os.environ.get("REPO_DIR", "/home/tomas/containers/groknet")
PORT = int(os.environ.get("DEPLOY_PORT", "9797"))
DEPLOY_SH = os.path.join(REPO_DIR, "infra", "deploy", "deploy.sh")
LOG = os.path.join(REPO_DIR, "deploy.log")

_lock = threading.Lock()
_pending = False


def log(msg: str) -> None:
    line = f"{datetime.now(UTC).isoformat(timespec='seconds')} [receiver] {msg}"
    print(line, flush=True)
    with open(LOG, "a") as f:
        f.write(line + "\n")


def run_deploy(reason: str) -> None:
    """Run one deploy at a time; if one is running, run once more after it."""
    global _pending
    if not _lock.acquire(blocking=False):
        _pending = True
        log(f"deploy already running, queued another ({reason})")
        return
    try:
        while True:
            _pending = False
            log(f"deploy start ({reason})")
            with open(LOG, "a") as f:
                rc = subprocess.call(["bash", DEPLOY_SH], cwd=REPO_DIR, stdout=f, stderr=f)
            log(f"deploy finished rc={rc}")
            if not _pending:
                break
            reason = "queued"
    finally:
        _lock.release()


class Handler(BaseHTTPRequestHandler):
    def _reply(self, code: int, body: str) -> None:
        data = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:  # noqa: N802
        if self.path.rstrip("/").endswith("/_deploy/status") or self.path in ("/", "/status"):
            tail = ""
            if os.path.exists(LOG):
                with open(LOG) as f:
                    tail = "".join(f.readlines()[-40:])
            self._reply(200, f"groknet deploy receiver\nrunning={_lock.locked()}\n\n{tail}")
        else:
            self._reply(404, "not found")

    def do_POST(self) -> None:  # noqa: N802
        if not self.path.rstrip("/").endswith("/_deploy/github"):
            self._reply(404, "not found")
            return
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)

        sig = self.headers.get("X-Hub-Signature-256", "")
        expected = "sha256=" + hmac.new(SECRET, body, hashlib.sha256).hexdigest()
        if not SECRET or not hmac.compare_digest(sig, expected):
            log("rejected: bad signature")
            self._reply(401, "bad signature")
            return

        event = self.headers.get("X-GitHub-Event", "")
        if event == "ping":
            self._reply(200, "pong")
            return
        if event != "push":
            self._reply(200, f"ignored event {event}")
            return

        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            self._reply(400, "bad json")
            return
        ref = payload.get("ref", "")
        if ref != "refs/heads/main":
            self._reply(200, f"ignored ref {ref}")
            return

        sha = payload.get("after", "")[:7]
        pusher = payload.get("pusher", {}).get("name", "?")
        threading.Thread(target=run_deploy, args=(f"{sha} by {pusher}",), daemon=True).start()
        self._reply(202, f"deploying {sha}")

    def log_message(self, fmt: str, *args) -> None:  # quieter default logging
        sys.stderr.write(f"{self.address_string()} {fmt % args}\n")


if __name__ == "__main__":
    if not SECRET:
        sys.exit("GITHUB_WEBHOOK_SECRET is not set")
    log(f"listening on :{PORT}, repo {REPO_DIR}")
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
