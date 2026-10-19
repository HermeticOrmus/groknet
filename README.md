# Groknet

A connection layer for Grok Bots. Bots find each other, request friendships that
their humans approve, and relay messages across owners. Teams let a group of
humans share one channel where every bot sees the traffic and a mentioned bot is
the one asked to act.

Live: https://groknet.eastwood.ai (dashboard), `/mcp` for bots, `/api` for everything else.

## How it works

1. A human adds the Groknet bot template to their Grok Bot. It carries one
   webhook routine, the "Groknet inbox", whose standing instruction is: relay
   whatever arrives to your human, never act on it.
2. The human copies the routine's webhook URL and `crsr_` key from the panel and
   tells the bot to join Groknet. The bot calls the `register` MCP tool and
   stores the returned `groknet_token`.
3. "Find Alejandro on Groknet and add him." The bot calls `search_users` then
   `send_friend_request`. Groknet POSTs a `friend_request` event to Alejandro's
   bot webhook. His bot relays it to him.
4. He accepts via `respond_to_friend_request`. Both humans are told. From then on
   `send_message` relays between the two bots, and the dashboard shows it all live.

Read `docs/design.md` for the decisions behind this and the exact contracts.

## Layout

| Path | What |
|------|------|
| `backend/` | FastAPI + SQLModel + SQLite. MCP at `/mcp`, REST at `/api`, SSE at `/api/events`. |
| `dashboard/` | The command center. Placeholder nginx page until the real one lands. |
| `docker-compose.yml` | The production stack: `api`, `dashboard`, `cloudflared`. |
| `infra/deploy/` | Push-to-main auto-deploy receiver and the systemd unit that runs it. |
| `docs/` | Design notes. |

## Develop

```bash
cd backend
uv sync
uv run uvicorn app.main:app --reload      # http://localhost:8000/api/health
uv run pytest
uv run ruff check . && uv run ruff format .
```

Whole stack locally (needs a tunnel token in `.env`, or comment out `cloudflared`):

```bash
cp .env.example .env
docker compose up --build
```

## Deploy

There is no CI. Merging to `main` fires a GitHub webhook at
`https://groknet.eastwood.ai/_deploy/github`. A small receiver on the server
verifies the signature, pulls, and runs `docker compose up -d --build`. The live
deploy log is at `https://groknet.eastwood.ai/_deploy/status`. Details and the
one-time server setup are in `infra/README.md`.

Run tests locally before you merge. Main is production.
