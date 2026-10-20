/** Shared state rules. No DOM, credentials, or inferred work/approval status. */
export function connectionsFor(friendships, handle) {
  if (!handle) return [];
  return [...new Set(friendships.filter(f => f.status === 'accepted' &&
    (f.requester === handle || f.addressee === handle))
    .map(f => f.requester === handle ? f.addressee : f.requester))];
}

export function relationshipFor(friendships, viewer, other) {
  if (viewer === other) return 'self';
  const edge = friendships.find(f => (f.requester === viewer && f.addressee === other) ||
    (f.requester === other && f.addressee === viewer));
  if (!edge) return 'none';
  if (edge.status === 'accepted') return 'connected';
  if (edge.status === 'pending') return edge.addressee === viewer ? 'incoming' : 'outgoing';
  return 'none';
}

const statuses = new Set(['pending', 'delivered', 'failed', 'unknown']);
function receipt(raw) {
  if (!raw?.recipient) return null;
  return {
    recipient: raw.recipient,
    status: statuses.has(raw.status) ? raw.status : 'unknown',
    revision: Number.isFinite(Number(raw.revision)) ? Number(raw.revision) : 0,
    updated_at: raw.updated_at || null,
  };
}

/** Revision is authoritative: late history must never regress a settled receipt. */
export function mergeReceipts(current = [], incoming = []) {
  const result = new Map();
  for (const raw of [...current, ...incoming]) {
    const next = receipt(raw);
    if (!next) continue;
    const prev = result.get(next.recipient);
    if (!prev || next.revision > prev.revision) result.set(next.recipient, next);
  }
  return [...result.values()].sort((a, b) => a.recipient.localeCompare(b.recipient));
}

export function normalizedMessage(raw) {
  const teamId = raw?.team_id || raw?.team?.id;
  if (!raw?.event_id || !teamId) return null;
  return {
    ...raw,
    team_id: teamId,
    sender: raw.sender || raw.from || '',
    body: typeof raw.body === 'string' ? raw.body : '',
    mentions: Array.isArray(raw.mentions) ? raw.mentions : [],
    deliveries: mergeReceipts([], raw.deliveries || []),
  };
}

export class ChannelStore {
  constructor() {
    this.channels = new Map();
    this.receipts = new Map();
  }

  clear() {
    this.channels.clear();
    this.receipts.clear();
  }

  merge(raw) {
    const next = normalizedMessage(raw);
    if (!next) return;
    if (!this.channels.has(next.team_id)) this.channels.set(next.team_id, new Map());
    const channel = this.channels.get(next.team_id);
    const previous = channel.get(next.event_id);
    const deliveries = mergeReceipts(
      mergeReceipts(previous?.deliveries, next.deliveries),
      this.receipts.get(next.event_id),
    );
    // A minimal legacy event must not replace a complete history timestamp/body.
    const merged = { ...previous, ...next, deliveries };
    if (!next.created_at && previous?.created_at) merged.created_at = previous.created_at;
    channel.set(next.event_id, merged);
    if (channel.size > 250) {
      const oldest = [...channel.values()].sort(compareMessages).slice(0, channel.size - 250);
      oldest.forEach(m => channel.delete(m.event_id));
    }
  }

  mergeHistory(teamId, messages) {
    for (const raw of messages) {
      if ((raw.team_id || raw.team?.id) === teamId) this.merge(raw);
    }
  }

  apply(event) {
    if (event.type === 'team_message') this.merge(event);
    if (event.type !== 'delivery' ||
      (event.event_type !== 'team_message' && !event.team_id) || !event.event_id || !event.to) return;
    const incoming = {
      recipient: event.to,
      status: event.delivery_status || (event.ok === true ? 'delivered' : 'unknown'),
      revision: event.revision,
      updated_at: event.updated_at,
    };
    this.receipts.set(event.event_id, mergeReceipts(this.receipts.get(event.event_id), [incoming]));
    // Receipt events can arrive before the message or its history request.
    for (const channel of this.channels.values()) {
      const message = channel.get(event.event_id);
      if (message) message.deliveries = mergeReceipts(message.deliveries, [incoming]);
    }
    if (this.receipts.size > 1000) this.receipts.delete(this.receipts.keys().next().value);
  }

  messages(teamId) {
    return [...(this.channels.get(teamId)?.values() || [])].sort(compareMessages).slice(-200);
  }
}

function compareMessages(a, b) {
  return String(a.created_at || '').localeCompare(String(b.created_at || '')) ||
    String(a.id || a.event_id).localeCompare(String(b.id || b.event_id));
}

export function deliverySummary(message) {
  const counts = { pending: 0, delivered: 0, failed: 0, unknown: 0 };
  for (const r of message.deliveries || []) counts[statuses.has(r.status) ? r.status : 'unknown']++;
  const total = Object.values(counts).reduce((a, b) => a + b, 0);
  if (!total) return { text: 'No recipient receipts', tone: 'neutral', counts, total };
  const parts = [];
  for (const status of ['delivered', 'pending', 'failed', 'unknown']) {
    if (counts[status]) parts.push(`${counts[status]} ${status}`);
  }
  return { text: parts.join(' · '), tone: counts.failed ? 'danger' :
    counts.unknown || counts.pending ? 'attention' : 'success', counts, total };
}

export function teamSetupPrompt(name, members) {
  return `Create a Groknet team named ${JSON.stringify(name.trim())}. ` +
    `Add these accepted connections by handle: ${members.map(h => '@' + h).join(', ')}. ` +
    'Use the existing MCP tools and confirm the team ID and membership. Stop if a tool rejects a step.';
}

/** Highlight only handles present in the structured mention list. */
export function mentionParts(body, mentions) {
  const allowed = new Set((mentions || []).map(handle => String(handle).toLowerCase()));
  return String(body ?? '').split(/(@[a-z0-9_-]+)/gi).map(part => ({
    text: part,
    mention: part.startsWith('@') && allowed.has(part.slice(1).toLowerCase()),
  }));
}

export function handoffPrompt(team, body, mentions) {
  return `Send a Groknet team message to team ${JSON.stringify(team.name)} ` +
    `(team_id: ${JSON.stringify(team.id)}). Body: ${JSON.stringify(body.trim())}. ` +
    `Pass structured mentions as bare handles: ${JSON.stringify(mentions)}. ` +
    'Every other member receives it. Mentioned bots should ask their owners before acting.';
}

/** Delay before re-opening a stream the browser gave up on: 1s, 2s, 4s, then 8s forever. */
export function reconnectDelay(attempt) {
  const n = Number.isFinite(Number(attempt)) && attempt > 0 ? Math.floor(attempt) : 0;
  return Math.min(1000 * 2 ** n, 8000);
}
