import test from 'node:test';
import assert from 'node:assert/strict';
import { ChannelStore, connectionsFor, relationshipFor, mergeReceipts,
  deliverySummary, handoffPrompt, mentionParts } from '../public/assets/state.js';

test('accepted friendships are undirected, deduplicated, and viewer scoped', () => {
  const rows = [
    { requester: 'a', addressee: 'juan', status: 'accepted' },
    { requester: 'juan', addressee: 'b', status: 'pending' },
    { requester: 'b', addressee: 'c', status: 'accepted' },
    { requester: 'juan', addressee: 'a', status: 'accepted' },
  ];
  assert.deepEqual(connectionsFor(rows, 'juan'), ['a']);
  assert.deepEqual(connectionsFor(rows, ''), []);
  assert.equal(relationshipFor(rows, 'b', 'juan'), 'incoming');
  assert.equal(relationshipFor(rows, 'juan', 'b'), 'outgoing');
});

const msg = (team = 'team-a', extra = {}) => ({
  event_id: 'event-1', id: 'message-1', team_id: team, sender: 'juan',
  body: 'Hi @tomas', mentions: ['tomas'], created_at: '2026-10-20T00:00:00Z',
  deliveries: [{ recipient: 'tomas', revision: 1, status: 'pending' }], ...extra,
});

test('out-of-order receipt before message survives a late pending history snapshot', () => {
  const store = new ChannelStore();
  store.apply({ type: 'delivery', event_type: 'team_message', team_id: 'team-a',
    event_id: 'event-1', to: 'tomas', revision: 2, delivery_status: 'delivered' });
  store.apply({ type: 'team_message', ...msg() });
  store.mergeHistory('team-a', [msg()]);
  store.apply({ type: 'delivery', event_type: 'team_message', team_id: 'team-a',
    event_id: 'event-1', to: 'tomas', revision: 1, delivery_status: 'pending' });
  assert.deepEqual(store.messages('team-a')[0].deliveries.map(r => [r.status, r.revision]),
    [['delivered', 2]]);
  assert.equal(store.messages('team-a').length, 1);
});

test('history merge preserves newer live messages and isolates teams', () => {
  const store = new ChannelStore();
  store.apply({ type: 'team_message', ...msg('team-a', { event_id: 'new',
    created_at: '2026-10-20T00:02:00Z' }) });
  store.mergeHistory('team-a', [msg(), msg('team-b')]);
  assert.deepEqual(store.messages('team-a').map(m => m.event_id), ['event-1', 'new']);
  assert.equal(store.messages('team-b').length, 0);
});

test('reconnect snapshot settles missed receipts without reassigning old recipients', () => {
  const store = new ChannelStore();
  store.mergeHistory('team-a', [msg()]);
  store.mergeHistory('team-a', [msg('team-a', { deliveries: [
    { recipient: 'tomas', revision: 2, status: 'unknown' },
  ] })]);
  assert.deepEqual(store.messages('team-a')[0].deliveries.map(r => [r.recipient, r.status]),
    [['tomas', 'unknown']]);
  assert.equal(store.messages('team-a')[0].body, 'Hi @tomas');
});

test('receipt summaries distinguish uncertainty, rejection, and delivery, never approval', () => {
  const summary = deliverySummary({ delivered: true, deliveries: [
    { recipient: 'a', status: 'delivered' }, { recipient: 'b', status: 'failed' },
    { recipient: 'c', status: 'unknown' }, { recipient: 'd', status: 'pending' },
  ] });
  assert.equal(summary.text, '1 delivered · 1 pending · 1 failed · 1 unknown');
  assert.equal(summary.tone, 'danger');
  assert.equal(deliverySummary({ delivered: true }).text, 'No recipient receipts');
  assert.equal(mergeReceipts([], [{ recipient: 'a', status: 'unexpected' }])[0].status, 'unknown');
});

test('structured mentions highlight matching handles and leave other text untouched', () => {
  const parts = mentionParts('Hi @Juan <img src=x> @stranger', ['juan']);
  assert.deepEqual(parts.filter(part => part.mention).map(part => part.text), ['@Juan']);
  assert.equal(parts.map(part => part.text).join(''), 'Hi @Juan <img src=x> @stranger');
});

test('handoff preserves exact team ID and explicit mentions separately from body text', () => {
  const prompt = handoffPrompt({ id: 'abc', name: 'Research' }, 'Ask @someone about @tomas', ['tomas']);
  assert.match(prompt, /team_id: "abc"/);
  assert.match(prompt, /bare handles: \["tomas"\]/);
});
