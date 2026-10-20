#!/usr/bin/env bash
# End-to-end handshake on one laptop, no Grok Bots needed:
#   two fake bots -> register both -> friend request -> accept -> message -> show both inboxes.
#
#   scripts/demo.sh            # against http://localhost:8000 (starts the backend if needed)
#
# Steps marked [needs #4] / [needs #5] call tools from the friendship and messaging
# issues; until those are merged they print the tool error and the demo continues.
set -uo pipefail
cd "$(dirname "$0")/.."

GROKNET_URL="${GROKNET_URL:-http://localhost:8000}"
export GROKNET_URL
G="scripts/groknet.sh"
PIDS=()
cleanup() { for p in "${PIDS[@]:-}"; do [ -n "$p" ] && kill "$p" 2>/dev/null; done; }
trap cleanup EXIT

step() { printf '\n\033[1m== %s\033[0m\n' "$*"; }

# 1. backend
if ! curl -sf "$GROKNET_URL/api/health" >/dev/null; then
  step "starting backend at $GROKNET_URL"
  (cd backend && DATABASE_URL=sqlite:///./demo.db GROKNET_DEV=1 uv run uvicorn app.main:app --port "${GROKNET_URL##*:}" >/tmp/groknet-demo-backend.log 2>&1) &
  PIDS+=($!)
  for _ in $(seq 1 30); do curl -sf "$GROKNET_URL/api/health" >/dev/null && break; sleep 0.5; done
fi
curl -sf "$GROKNET_URL/api/health" >/dev/null || { echo "backend not reachable at $GROKNET_URL"; exit 1; }

# 2. two fake bots
step "starting fake bots alice (:9101) and bob (:9102)"
python3 scripts/fake_bot.py alice 9101 & PIDS+=($!)
python3 scripts/fake_bot.py bob   9102 & PIDS+=($!)
sleep 1

# 3. register both (unique handles per run so re-running never collides with real users)
RUN=$(date +%s | tail -c 5)
ALICE="alice$RUN"; BOB="bob$RUN"
step "register $ALICE and $BOB"
# (register also takes an optional profile JSON as a 6th argument once the profile column is on main)
A_TOKEN=$($G register "$ALICE" "Alice" "$ALICE@mail.grokbot.com" "http://localhost:9101/automations/webhook/alice" crsr_alice | python3 -c 'import json,sys;print(json.load(sys.stdin)["groknet_token"])')
B_TOKEN=$($G register "$BOB"   "Bob"   "$BOB@mail.grokbot.com"   "http://localhost:9102/automations/webhook/bob"   crsr_bob | python3 -c 'import json,sys;print(json.load(sys.stdin)["groknet_token"])')
echo "alice token: ${A_TOKEN:0:8}…   bob token: ${B_TOKEN:0:8}…"
$G whoami "$A_TOKEN"

# 4. friendship  [needs #4]
step "$ALICE searches for bob and sends a friend request  [needs #4]"
$G search "$A_TOKEN" bob || true
$G request "$A_TOKEN" "$BOB" || true
sleep 1
step "$BOB accepts  [needs #4]"
$G respond "$B_TOKEN" "$ALICE" accept || true
sleep 1

# 5. message  [needs #5]
step "$ALICE messages $BOB  [needs #5]"
$G message "$A_TOKEN" "$BOB" "hey bob, the relay works" || true
sleep 1

# 6. what each bot received
step "alice's inbox"; curl -s http://localhost:9101/ | python3 -m json.tool
step "bob's inbox";   curl -s http://localhost:9102/ | python3 -m json.tool

step "dashboard view: $GROKNET_URL/api/users"
curl -s -H "Authorization: Bearer $A_TOKEN" "$GROKNET_URL/api/users" | python3 -m json.tool
