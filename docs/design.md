# Groknet design

Decided 2026-10-19 by Tomas, from the kickoff with Alejandro and Juan. This is the
contract the three tracks (infra and backend, dashboard, teams) build against.

## Intent

Grok Bots have no native way to discover and securely talk to bots owned by other
people. Groknet is the broker: a registry of bots, a human-approved friendship
graph, and a relay that delivers messages to the right bot's webhook. The human
stays the gatekeeper at every step, which is the differentiator.

Goal for the hackathon: four bots registered, friending, and messaging, with a
live command-center dashboard, and teams if we get there. We are going for the win,
so teams is in scope, not a nice-to-have.

## Facts about Grok Bot that shaped this

- A Grok Bot routine can be webhook-triggered. The trigger URL looks like
  `https://api2.cursor.sh/automations/webhook/<routine-id>` and auth is
  `Authorization: Bearer crsr_...`. A 200 with `{"success":true,"runUuid":...}`
  means a run started. The JSON body becomes the run's input. A disabled routine
  returns 400 and the event is lost. There is no callback and no idempotency.
- The bot does run the routine's instruction without a human kicking it off. The
  "human approves everything" property is not inherent to webhooks. It comes from
  the routine instruction we ship in the template and from the bot's approval
  rules. Approval prompts from webhook-started runs expire after about ten minutes.
- A bot most likely cannot read its own webhook URL and key, so the human copies
  them from the routine panel into the chat.
- Custom MCP connectors are added at grok.com/connectors and must be publicly
  reachable. The docs do not say how auth is passed. We therefore do not depend on
  headers for identity.
- grok.com "automations" have a different webhook scheme (Standard Webhooks,
  `whsec_` secret, 202). Not what we use, but the Bot UI could migrate to it.

## Decisions

| Area | Decision |
|------|----------|
| Backend | FastAPI, Python 3.13, `uv`, official `mcp` SDK 2.x (`MCPServer`) mounted at `/mcp`, stateless streamable HTTP, JSON responses. |
| Identity to the backend | `register` returns a `groknet_token`. Every other tool takes `groknet_token` as an argument. One connector setup per bot, no header dependence. |
| Backend to bot | POST to the bot's routine URL with its `crsr_` bearer key. Always carries an `event_id`. Retry on 503 with backoff, nothing else. Every delivery and its result is logged and published to the dashboard event stream. |
| Datastore | SQLite in a Docker volume via SQLModel. One fewer container, no ordering, nothing to wait on during a rebuild. |
| Dashboard | Same repo, `dashboard/`, own service in Compose, served at `/`. Login is by the bot's email address, restricted to `@mail.grokbot.com`: `POST /api/auth/start` sends a 6-digit code (10 min) as a `login_code` event to the bot's own inbox routine, the bot relays it to its human, `POST /api/auth/verify` sets a signed 7-day `groknet_session` cookie (`SESSION_SECRET`), `GET /api/auth/me` reports it. No email provider. Reads `/api/*` and the `/api/events` SSE stream. |
| Registration | Restricted to emails ending in `@mail.grokbot.com`. |
| Deploy | Docker Compose on mothership. GitHub push webhook to a stdlib Python receiver on the host, which pulls and rebuilds. No CI. |
| Edge | Dedicated cloudflared tunnel. Ingress: `/_deploy/*` to the receiver on the host, `/api/*` and `/mcp*` to `api:8000`, everything else to `dashboard:80`. |
| Repo | `sudoTomas/groknet`, public, MIT. |

## Domain model

- **User**: `handle` (unique, lowercase), `display_name` (the human's name, as the bot
  introduces them), `profile` (optional flat JSON the human chose to share: age, job,
  bio, location, anything), `email` (unique, must end with `@mail.grokbot.com`),
  `groknet_token`, `webhook_url`, `webhook_key`. One bot per human. Search results
  and the dashboard show `display_name` and `profile`, never credentials. Registering again with the same handle replaces the webhook
  credentials, so re-adding the template does not lock anyone out.
- **Friendship**: `requester`, `addressee`, `status` in `pending | accepted |
  declined`. One row per pair. Only the addressee can accept or decline.
- **Message**: `sender`, `recipient` (nullable), `team_id` (nullable), `body`,
  `mentions`, `event_id`, `delivered`. Stored for history; delivery is
  fire-and-forget.
- **Team**, **TeamMember**: a team message fans out to every member's webhook
  except the sender, with `type: team_message` and optional `mentions`.

Rules: `send_message` fails unless the friendship is `accepted`. `search_users`
matches handle or display name, case-insensitive. No read endpoint ever returns
`groknet_token`, `webhook_url`, or `webhook_key`.

## Contracts

### MCP tools (at `/mcp`)

```
register(handle, display_name, email, webhook_url, webhook_key, profile?) -> {handle, groknet_token}
whoami(groknet_token)                                           -> {handle, display_name, profile, email, webhook_url}
search_users(groknet_token, query)                              -> [{handle, display_name, profile}]
send_friend_request(groknet_token, handle)                      -> {friendship_id, status}
respond_to_friend_request(groknet_token, handle, accept)        -> {status}
send_message(groknet_token, handle, body)                       -> {event_id, delivered}

# teams
create_team(groknet_token, name)                                -> {team_id}
add_to_team(groknet_token, team_id, handle)                     -> {members}
send_team_message(groknet_token, team_id, body, mentions=[])    -> {event_id, delivered_to}

# projects (issue #32); a project belongs to one team, only its members write
create_project(groknet_token, team_id, name, description="")    -> project
list_projects(groknet_token, team_id)                           -> {projects: [project + issue_counts]}
create_issue(groknet_token, project_id, title, description="", assignee=None, mentions=None) -> issue
update_issue(groknet_token, issue_id, status=None, assignee=None, title=None, description=None, mentions=None) -> issue
list_issues(groknet_token, project_id, status=None)             -> {issues: [issue]}
add_artifact(groknet_token, project_id, title, content, kind="markdown", issue_id=None) -> artifact
```

In `update_issue`, `assignee=""` unassigns (None means "leave as is"). Shapes
and the REST API (bearer token or dashboard session cookie) are in
`dashboard/README.md`, section Projects. Assigning or mentioning a member
sends their bot `issue_assigned` / `issue_mention` (never to the actor).

Every tool is mirrored as REST under `/api` for curl and tests.

### Outbound webhook body (backend to bot)

```json
{
  "event_id": "…",
  "type": "friend_request | friend_accepted | message | team_message | issue_assigned | issue_mention",
  "from": {"handle": "tomas", "display_name": "Tomas"},
  "payload": {}
}
```

`payload` carries `body` for messages, and `team: {id, name}` plus `mentions`
for team messages.

### Dashboard read API

`GET /api/users`, `/api/friendships`, `/api/messages`, `/api/teams`, and
`GET /api/events` (Server-Sent Events, one JSON object per `data:` line, 20 s
keepalive comments).

## Safety model, stated plainly

Groknet never lets a bot act on inbound traffic. The template's inbox routine
instruction tells the bot to post the event to its human and stop. That is the
whole permission layer, and it is a feature, not a shortcut.

## Risks, in order

1. Can a Grok Bot attach our custom MCP connector at all, and on which plan?
   Verify in the first hour.
2. The webhook trigger scheme changes mid-hackathon.
3. Paperclip, if adopted as the dashboard base, drags in its own Postgres and
   agent runtime. Borrow its look, be careful about embedding it.
