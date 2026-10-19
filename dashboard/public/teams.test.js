"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const { mergeMessage, messageKey, statusLabel, escapeHandle, parseMentions, messageSender, receiptStatus, normalizeTeam, recipientHandles } = require("./teams.js");

test("history reconciliation keeps the highest delivery revision per recipient", () => {
  const live = {
    event_id: "evt-1", team_id: "team-1", body: "Check @alejandro",
    deliveries: [{ recipient: "alejandro", status: "delivered", revision: 4, updated_at: "2026-10-19T13:00:04Z" }],
  };
  const staleSnapshot = {
    event_id: "evt-1", team_id: "team-1", body: "Check @alejandro",
    deliveries: [{ recipient: "alejandro", status: "pending", revision: 2, updated_at: "2026-10-19T13:00:02Z" }, { recipient: "lila", status: "failed", revision: 1 }],
  };
  const merged = mergeMessage(live, staleSnapshot);
  assert.deepEqual(Object.fromEntries(merged.deliveries.map((r) => [r.recipient, r.status])), { alejandro: "delivered", lila: "failed" });
  assert.equal(merged.deliveries.find((r) => r.recipient === "alejandro").revision, 4);
});

test("message identity deduplicates event and database IDs", () => {
  assert.equal(messageKey({ id: 12, event_id: "evt-12" }), "evt-12");
  assert.equal(messageKey({ id: 12 }), "12");
  assert.equal(messageKey({}), "");
});

test("delivery labels preserve pending, delivered, failed, and unknown states", () => {
  assert.deepEqual(statusLabel("pending"), ["pending", "Pending"]);
  assert.deepEqual(statusLabel("delivered"), ["delivered", "Delivered"]);
  assert.deepEqual(statusLabel("failed"), ["failed", "Failed"]);
  assert.deepEqual(statusLabel(undefined), ["unknown", "Unknown"]);
});

test("handles are normalized before constructing mention lists", () => {
  assert.equal(escapeHandle("@Alejandro"), "alejandro");
});

test("mention parsing enforces backend syntax and selected-team membership", () => {
  const result = parseMentions("Hi @alejandro, @lila_bot and @bad.name; email x@domain.com", [
    { handle: "alejandro" }, { handle: "lila_bot" },
  ]);
  assert.deepEqual(result, { mentions: ["alejandro", "lila_bot"], rejected: ["bad.name"] });
  assert.deepEqual(parseMentions("Hello @outsider", [{ handle: "alejandro" }]).rejected, ["outsider"]);
  assert.deepEqual(parseMentions("Hello @a", [{ handle: "a" }]).rejected, ["a"]);
});

test("message sender display supports sender handles and sender_name", () => {
  assert.deepEqual(messageSender({ sender: "tomas", sender_name: "Tomas" }), { handle: "tomas", name: "Tomas" });
  assert.deepEqual(messageSender({ sender: "tomas" }), { handle: "tomas", name: "tomas" });
});

test("missing legacy delivery detail remains unknown while enriched status is preserved", () => {
  assert.equal(receiptStatus({ ok: false, status: 503 }), "unknown");
  assert.equal(receiptStatus({ ok: false, delivery_status: "unknown" }), "unknown");
  assert.equal(receiptStatus({ ok: false, delivery_status: "failed" }), "failed");
});

test("team normalization prefers member details and accepts string or object members", () => {
  assert.deepEqual(normalizeTeam({
    id: "t1",
    members: ["legacy"],
    member_details: [{ handle: "Tomas", display_name: "Tomas H." }],
  }).members, [{ handle: "tomas", display_name: "Tomas H." }]);
  assert.deepEqual(normalizeTeam({ members: ["Alejandro", { handle: "lila", display_name: "Lila" }] }).members, [
    { handle: "alejandro" }, { handle: "lila", display_name: "Lila" },
  ]);
});

test("historic recipients use message deliveries when present and roster only as fallback", () => {
  const teamMembers = [{ handle: "tomas" }, { handle: "alejandro" }, { handle: "new-member" }];
  assert.deepEqual(recipientHandles({ sender: "@tomas", deliveries: [{ recipient: "alejandro" }] }, teamMembers), ["alejandro"]);
  assert.deepEqual(recipientHandles({ sender: "tomas", deliveries: [] }, teamMembers), []);
  assert.deepEqual(recipientHandles({ sender: "tomas" }, teamMembers), ["alejandro", "new-member"]);
});
