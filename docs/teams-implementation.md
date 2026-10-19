# Teams implementation handoff

## Issue status

| Issue | Implementation | Remaining verification |
| --- | --- | --- |
| #15 | Shared team service and three MCP tools; creator membership, friendship checks, validated mentions, concurrent fan-out, one logical message and persisted recipient receipts | Real Grok webhook smoke |
| #17 | Authenticated REST mutations, team/member reads, message history, correlated SSE events; shapes in `dashboard/README.md` | Existing dashboard can consume these contracts |
| #16 | Copyable inbox extension and exact tool arguments in `docs/bot-teams.md` | Integrate into Alejandro's base template when its location is available; run the documented real-bot smoke |
| #18 | Deferred at Juan's request | No UI implementation included |

## Evidence

`bin/prove` exits 0: **52 backend tests passed**, with
`PROVE typecheck=NA lint=PASS build=PASS smoke=PASS`.

The gate checks Ruff, Python source compilation, and REST/MCP integration tests.
Tests deliver to local HTTP inboxes, check recipient isolation and actual
concurrency, and verify membership, mentions, history, SSE receipts, partial
failure, and credential exclusion. No static type checker is configured.
No real Grok bot, production deployment, or Docker build was exercised.

## Integration

- Reuses the shared identity helper, REST dependencies, accepted-friendship
  predicate, webhook sender and retry policy. No dependency changes.
- `TeamDelivery` is an additive table created by the existing startup schema
  initialization. Existing `members` handle arrays remain unchanged; detailed
  member names are additive.
- Persisted receipts describe webhook acceptance, not human attention or action.
  An uncertain delivery remains `unknown`; this feature adds no resend loop.
- Team reads inherit the existing shared read policy. Login/session work in
  #12 is outside this change.
- Main auto-deploys. This branch is prepared for review without changing main.
