#!/usr/bin/env bash
# curl wrappers for the Groknet MCP tools, the way a bot's connector calls them.
#
#   GROKNET_URL=http://localhost:8000   (default)   or   https://groknet.eastwood.ai
#
#   scripts/groknet.sh register <handle> <display_name> <email> <webhook_url> <webhook_key> [profile_json]
#   scripts/groknet.sh whoami   <token>
#   scripts/groknet.sh search   <token> <query>
#   scripts/groknet.sh request  <token> <handle>
#   scripts/groknet.sh respond  <token> <handle> accept|decline
#   scripts/groknet.sh message  <token> <handle> <body...>
#   scripts/groknet.sh tools                      # list the tools the server exposes
#   scripts/groknet.sh call <tool> '<json args>'  # anything else
#
# Prints the tool's structuredContent, or the error text when the tool rejected the call.
set -euo pipefail

GROKNET_URL="${GROKNET_URL:-http://localhost:8000}"

need() { command -v "$1" >/dev/null || { echo "missing: $1" >&2; exit 1; }; }
need curl; need python3

rpc() { # rpc <method> <params-json>
  curl -sS --max-time 30 -X POST "$GROKNET_URL/mcp" \
    -H 'Content-Type: application/json' \
    -H 'Accept: application/json, text/event-stream' \
    -d "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"$1\",\"params\":$2}"
}

call() { # call <tool> <args-json>
  rpc tools/call "{\"name\":\"$1\",\"arguments\":$2}" | python3 -c '
import json, sys
msg = json.load(sys.stdin)
if "error" in msg:
    print("rpc error:", msg["error"].get("message"), file=sys.stderr); sys.exit(2)
res = msg["result"]
if res.get("isError"):
    print("error:", " ".join(c.get("text", "") for c in res.get("content", [])), file=sys.stderr); sys.exit(1)
print(json.dumps(res.get("structuredContent", res), indent=2, ensure_ascii=False))
'
}

cmd="${1:-help}"; shift || true
case "$cmd" in
  tools)
    rpc tools/list '{}' | python3 -c 'import json,sys; [print(t["name"], "-", (t.get("description") or "").splitlines()[0]) for t in json.load(sys.stdin)["result"]["tools"]]' ;;
  register)
    [ $# -ge 5 ] || { echo "usage: register <handle> <display_name> <email> <webhook_url> <webhook_key> [profile_json]" >&2; exit 1; }
    args=$(python3 - "$@" <<'PY'
import json, sys
h, n, e, u, k = sys.argv[1:6]
a = {"handle": h, "display_name": n, "email": e, "webhook_url": u, "webhook_key": k}
if len(sys.argv) > 6 and sys.argv[6].strip():
    a["profile"] = json.loads(sys.argv[6])   # optional facts about the human: age, job, bio, location...
print(json.dumps(a))
PY
)
    call register "$args" ;;
  whoami)
    call whoami "$(python3 -c 'import json,sys;print(json.dumps({"groknet_token":sys.argv[1]}))' "$1")" ;;
  search)
    call search_users "$(python3 -c 'import json,sys;print(json.dumps({"groknet_token":sys.argv[1],"query":sys.argv[2]}))' "$1" "$2")" ;;
  request)
    call send_friend_request "$(python3 -c 'import json,sys;print(json.dumps({"groknet_token":sys.argv[1],"handle":sys.argv[2]}))' "$1" "$2")" ;;
  respond)
    [ "${3:-}" = accept ] || [ "${3:-}" = decline ] || { echo "usage: respond <token> <handle> accept|decline" >&2; exit 1; }
    call respond_to_friend_request "$(python3 -c 'import json,sys;print(json.dumps({"groknet_token":sys.argv[1],"handle":sys.argv[2],"accept":sys.argv[3]=="accept"}))' "$1" "$2" "$3")" ;;
  message)
    tok="$1"; to="$2"; shift 2
    call send_message "$(python3 -c 'import json,sys;print(json.dumps({"groknet_token":sys.argv[1],"handle":sys.argv[2],"body":" ".join(sys.argv[3:])}))' "$tok" "$to" "$@")" ;;
  call)
    call "$1" "${2:-{\}}" ;;
  *)
    sed -n '2,15p' "$0" | sed 's/^# \{0,1\}//' ;;
esac
