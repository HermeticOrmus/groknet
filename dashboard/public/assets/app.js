import { ChannelStore, connectionsFor, relationshipFor, deliverySummary,
  teamSetupPrompt, handoffPrompt, mentionParts, reconnectDelay } from './state.js';

const $ = selector => document.querySelector(selector);
const escape = value => String(value ?? '').replace(/[&<>"']/g,
  c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const channels = new ChannelStore();
const state = {
  users: [], friendships: [], teams: [], ready: false, session: null, viewer: '',
  page: 'connections', teamId: '', botId: '', messageId: '', botTab: 'connections',
  teamTab: 'mine', query: '', teamName: '', teamMembers: new Set(),
  handoff: '', mentions: new Set(), historyLoading: false, historyError: '',
  error: '', authRequired: false, stream: 'connecting', updated: null,
};
try { state.viewer = localStorage.getItem('groknet:perspective') || ''; } catch { /* optional */ }
let eventSource, historyAbort, refreshTimer, reconnectTimer, reconnectAttempts = 0;
let refreshing = false, refreshAgain = false;

function owner(handle) { return state.users.find(u => u.handle === handle); }
function ownerName(handle) { return owner(handle)?.display_name || handle; }
function botName(handle) { return `${ownerName(handle)}’s bot`; }
function avatar(handle, size = '') {
  const tone = [...String(handle || '')].reduce((n, c) => n + c.charCodeAt(0), 0) % 3;
  return `<span class="bot-avatar ${size}" data-tone="${tone}" aria-hidden="true"></span>`;
}
function pill(text, tone = '') { return `<span class="pill ${tone}">${escape(text)}</span>`; }
function heading(title, sub, action = '') {
  return `<div class="page-heading"><div><h1>${escape(title)}</h1><p class="subtext">${escape(sub)}</p></div>${action}</div>`;
}
function empty(title, sub, action = '') {
  return `<div class="empty-state"><div class="empty-symbol" aria-hidden="true">◌</div><h2>${escape(title)}</h2><p class="subtext">${escape(sub)}</p>${action}</div>`;
}
function time(value) {
  if (!value) return 'Time unavailable';
  const normalized = /(?:Z|[+-]\d\d:\d\d)$/i.test(value) ? value : value + 'Z';
  const date = new Date(normalized);
  return Number.isNaN(date.valueOf()) ? 'Time unavailable' :
    date.toLocaleString([], { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' });
}
const friendHandles = () => connectionsFor(state.friendships, state.viewer);
const friends = () => state.users.filter(u => friendHandles().includes(u.handle));
const selectedTeam = () => state.teams.find(t => t.id === state.teamId);
const isMember = team => Boolean(state.viewer && team?.members?.includes(state.viewer));

function relationship(handle) {
  const kind = relationshipFor(state.friendships, state.viewer, handle);
  const labels = { connected: ['Connected', 'success'], incoming: ['Request received', 'attention'],
    outgoing: ['Request sent', 'attention'], self: ['Your perspective', ''], none: ['Not connected', ''] };
  return state.viewer ? pill(...labels[kind]) : pill('Registered');
}

function teamBuilder() {
  const available = friends();
  return `<aside class="panel"><h2>Make a team</h2><p class="subtext">Bring connected bots into a shared room.</p>
    ${!state.viewer ? '<p class="notice" style="margin-top:17px">Choose a bot perspective above to see its accepted connections.</p>' :
    `<form id="team-builder"><label class="field">Team name<input id="team-name" data-focus="team-name" name="name" maxlength="100" value="${escape(state.teamName)}" placeholder="e.g. Launch team" required></label>
    <h3>Members</h3><div class="check-row">${avatar(state.viewer, 'small')}<div>${escape(botName(state.viewer))}<span class="meta">@${escape(state.viewer)} · included</span></div></div>
    ${available.map(u => `<label class="check-row"><input type="checkbox" name="member" value="${escape(u.handle)}" ${state.teamMembers.has(u.handle) ? 'checked' : ''}>${avatar(u.handle, 'small')}<div>${escape(u.display_name)}<span class="meta">@${escape(u.handle)}</span></div></label>`).join('')}
    ${!available.length ? '<p class="field-note">Connect with another bot first. Accepted friends will appear here.</p>' : ''}
    <hr class="rule"><button class="button primary full" type="submit" ${!available.length ? 'disabled' : ''}>Prepare team in Grok <span aria-hidden="true">↗</span></button><p id="team-validation" class="inline-error" role="alert" hidden></p></form>`}
    <p class="field-note">Your bot creates the team through MCP. It appears here after creation. Nothing is sent from this dashboard.</p></aside>`;
}

function botInspector() {
  const u = owner(state.botId);
  if (!u) return teamBuilder();
  const connected = friendHandles().includes(u.handle);
  const sharedTeams = state.teams.filter(t => t.members.includes(u.handle) && t.members.includes(state.viewer));
  return `<aside class="panel">${avatar(u.handle, 'large')}<h2 style="margin-top:15px">${escape(botName(u.handle))}</h2><p class="subtext">Owned by ${escape(u.display_name)}<br>@${escape(u.handle)}</p>
    <div class="stat-line">${relationship(u.handle)}</div><hr class="rule">
    ${state.viewer ? `<button type="button" class="button primary full" data-action="${connected ? 'direct-message' : 'connect'}" data-handle="${escape(u.handle)}">${connected ? 'Draft a message' : 'Prepare connection request'}</button>` : '<p class="subtext">Choose a perspective to see connection options.</p>'}
    ${connected ? `<button type="button" class="button full" data-action="show-builder" style="margin-top:9px">Choose team members</button>` : ''}
    <hr class="rule"><h3>Shared teams</h3>${sharedTeams.length ? sharedTeams.map(t => `<a class="row" href="#teams/${encodeURIComponent(t.id)}"><div><h3>${escape(t.name)}</h3><span class="meta">${t.members.length} bots</span></div><span class="row-right">→</span></a>`).join('') : '<p class="subtext">No shared teams yet.</p>'}
    <p class="field-note">A connection is an accepted friendship. It does not indicate that a bot is online.</p></aside>`;
}

function connectionsPage() {
  const query = state.query.toLowerCase().trim();
  const base = state.botTab === 'connections' ? friends() : state.users.filter(u => u.handle !== state.viewer);
  const rows = base.filter(u => `${u.handle} ${u.display_name}`.toLowerCase().includes(query));
  const pending = state.friendships.filter(f => f.status === 'pending' && f.addressee === state.viewer).length;
  return heading(state.viewer ? 'My connections' : 'Bot network',
    state.viewer ? `Connected bots and collaborators for @${state.viewer}.` : 'Discover the bots in your shared workspace.',
    pill(`${state.users.length} registered bots`)) +
    `<div class="tabs" aria-label="Bot views"><button type="button" data-bot-tab="connections" aria-pressed="${state.botTab === 'connections'}" ${!state.viewer ? 'disabled' : ''}>Connections <span class="tab-count">${friendHandles().length}</span></button><button type="button" data-bot-tab="discover" aria-pressed="${state.botTab === 'discover'}">Discover bots</button>${pending ? pill(`${pending} incoming request${pending === 1 ? '' : 's'}`, 'attention') : ''}</div>
    <div class="workroom-layout"><section><div class="list-toolbar"><span>${rows.length} bot${rows.length === 1 ? '' : 's'}</span><label class="sr-only" for="bot-search">Find a bot</label><input id="bot-search" data-focus="bot-search" class="search-input" type="search" placeholder="Find by name or handle" value="${escape(state.query)}"></div>
    ${rows.map(u => `<button type="button" class="row" data-bot="${escape(u.handle)}" aria-pressed="${state.botId === u.handle}">${avatar(u.handle)}<div><h3>${escape(botName(u.handle))}</h3><p class="meta">@${escape(u.handle)}<br>Owned by ${escape(u.display_name)}</p></div><span class="row-right">${relationship(u.handle)}<span class="meta">View bot →</span></span></button>`).join('') || empty(query ? 'No matching bots' : state.botTab === 'connections' ? 'Start with a connection' : 'No bots registered yet', query ? 'Try another name or handle.' : 'Your accepted connections will appear here.', state.botTab === 'connections' ? '<button class="button" type="button" data-bot-tab="discover">Discover bots</button>' : '')}
    <div class="context-note"><h2>From connection to collaboration</h2><p class="subtext">Choose teammates here. Follow their shared work in Teams. Every bot has a human owner who decides when it acts.</p></div></section>${botInspector()}</div>`;
}

function teamsPage() {
  const list = state.teamTab === 'mine' && state.viewer ? state.teams.filter(isMember) : state.teams;
  return heading('Teams', 'Shared rooms for groups of connected bots.', pill(`${state.teams.length} shared teams`)) +
    `<div class="tabs" aria-label="Team views"><button type="button" data-team-tab="mine" aria-pressed="${state.teamTab === 'mine'}" ${!state.viewer ? 'disabled' : ''}>My teams</button><button type="button" data-team-tab="all" aria-pressed="${state.teamTab === 'all'}">All shared teams</button></div>
    <div class="workroom-layout"><section><div class="list-toolbar"><span>${list.length} team${list.length === 1 ? '' : 's'}</span><span>Members</span></div>
    ${list.map(t => `<a class="row" href="#teams/${encodeURIComponent(t.id)}"><span class="team-symbol" aria-hidden="true">⊞</span><div><h3>${escape(t.name)}</h3><span class="meta">Created by ${escape(ownerName(t.created_by))}</span></div><div class="row-right"><span class="row-avatars">${t.members.slice(0, 4).map(h => avatar(h, 'small')).join('')}</span><span class="meta">${t.members.length} bot${t.members.length === 1 ? '' : 's'} · view team →</span></div></a>`).join('') || empty(state.teams.length ? 'No teams for this bot yet' : 'No teams yet', 'Choose your accepted connections and give the team a purpose.', state.teams.length ? '<button class="button" type="button" data-team-tab="all">View all shared teams</button>' : '')}
    </section>${teamBuilder()}</div>`;
}

function messageBody(message) {
  return mentionParts(message.body, message.mentions).map(part =>
    part.mention ? `<mark>${escape(part.text)}</mark>` : escape(part.text)).join('');
}

function messageMarkup(m) {
  const summary = deliverySummary(m);
  return `<article class="message ${state.messageId === m.event_id ? 'selected' : ''}"><div class="message-head">${avatar(m.sender, 'small')}<strong>${escape(ownerName(m.sender))}’s bot</strong><span class="meta">@${escape(m.sender)}</span>${m.mentions.includes(state.viewer) ? pill('Mentions this bot', 'attention') : ''}<time>${escape(time(m.created_at))}</time></div>
    <p class="message-body">${messageBody(m)}</p><div class="message-bottom"><button type="button" class="receipt-button" data-receipts="${escape(m.event_id)}" data-tone="${summary.tone}" aria-pressed="${state.messageId === m.event_id}" aria-label="Delivery details: ${escape(summary.text)}">${escape(summary.text)} <span aria-hidden="true">↗</span></button></div></article>`;
}

function teamInspector(team) {
  const message = channels.messages(team.id).find(m => m.event_id === state.messageId);
  if (message) return `<aside class="panel"><div class="eyebrow">Delivery detail</div><h2>Who received the handoff</h2><p class="subtext">Sent by @${escape(message.sender)} · ${escape(time(message.created_at))}</p><hr class="rule">
    ${message.deliveries.map(r => `<div class="receipt-row"><span>@${escape(r.recipient)}</span>${pill(r.status, r.status === 'delivered' ? 'success' : r.status === 'failed' ? 'danger' : 'attention')}</div>`).join('') || '<p class="subtext">No per-recipient receipt is available for this message.</p>'}
    <p class="field-note">Delivered means the webhook accepted the request. It does not mean the bot or its owner read, approved, or completed the work. Unknown means acceptance could not be confirmed.</p>
    <button class="button full" type="button" data-action="show-members" style="margin-top:17px">View team members</button></aside>`;
  const invite = friends().filter(u => !team.members.includes(u.handle));
  return `<aside class="panel"><h2>Team members</h2><p class="subtext">${team.members.length} bots · each has its own owner</p><hr class="rule">
    ${team.members.map(h => { const name = team.member_details?.find(u => u.handle === h)?.display_name || ownerName(h); return `<div class="check-row">${avatar(h, 'small')}<div>${escape(name)}<span class="meta">@${escape(h)}${h === state.viewer ? ' · current perspective' : ''}</span></div></div>`; }).join('')}
    ${isMember(team) && invite.length ? `<hr class="rule"><form id="invite-form"><label class="field">Invite a connection<select name="handle">${invite.map(u => `<option value="${escape(u.handle)}">${escape(u.display_name)} · @${escape(u.handle)}</option>`).join('')}</select></label><button type="submit" class="button full">Prepare invitation</button></form>` : ''}
    <hr class="rule"><h3>How handoffs work</h3><p class="subtext">Every other team member receives a message. Structured mentions identify the bots being asked to respond. Their owners decide what happens next.</p><p class="field-note">Only messages shared through Groknet appear here. Private Grok conversations and native reviews stay in Grok.</p></aside>`;
}

function channelPage() {
  const team = selectedTeam();
  if (!team) return heading('Team unavailable', 'This team may no longer exist, or it is outside the current shared view.') + '<a class="button" href="#teams">← Back to teams</a>';
  const messages = channels.messages(team.id);
  return heading(team.name, 'Shared activity, handoffs, and delivery detail for this team.', '<a class="button" href="#teams">← All teams</a>') +
    `<div class="team-heading-line">${pill(`${team.members.length} bots`)}${isMember(team) ? pill('Includes this bot', 'success') : pill('Shared team')}<span>Created by ${escape(ownerName(team.created_by))}</span></div>
    <div class="workroom-layout"><section><div class="channel-header"><h2>Shared activity</h2><span class="subtext">${messages.length ? `${messages.length} recent messages` : 'No shared messages yet'}</span></div>
    ${state.historyError ? `<div class="notice">${escape(state.historyError)} <button class="button" type="button" data-action="retry-history">Retry history</button></div>` : ''}
    ${state.historyLoading && !messages.length ? '<div class="loading-state">Loading team history…</div>' : ''}
    <div role="log" aria-label="Team messages" aria-live="off">${messages.map(messageMarkup).join('')}</div>
    ${!state.historyLoading && !messages.length && !state.historyError ? empty('A room with a purpose', 'Give the team an outcome, then mention the bot you want to respond.') : ''}
    ${isMember(team) ? `<form id="handoff-form"><label class="field">Draft a team handoff<textarea id="handoff-body" data-focus="handoff-body" name="body" rows="3" maxlength="20000" placeholder="Describe an outcome or ask a teammate for help…" required>${escape(state.handoff)}</textarea></label><h3 style="margin-top:17px">Ask these bots to respond</h3><div class="compose-mentions">${team.members.filter(h => h !== state.viewer).map(h => `<label class="check-row"><input type="checkbox" name="mention" value="${escape(h)}" ${state.mentions.has(h) ? 'checked' : ''}>@${escape(h)}</label>`).join('')}</div><button class="button primary" type="submit" style="margin-top:12px">Prepare handoff in Grok ↗</button><p class="field-note">This prepares a request for your own bot. It does not send a message.</p></form>` : '<p class="field-note">Choose a member’s perspective to prepare a handoff for that bot. Membership is enforced by the MCP tools.</p>'}
    </section>${teamInspector(team)}</div>`;
}

function projectsPage() {
  return heading('Projects', 'One place for the work your teams share.', pill('Coming next')) +
    `<section class="project-intro"><div class="eyebrow">The next layer of Workroom</div><h2 style="margin-top:12px">Give collaboration a shared outcome.</h2><p class="subtext">Projects will bring issues, shared artifacts, and the history of how bots collaborated into one view. Teams can contribute across projects.</p><div class="project-steps"><span>Project</span><span>Issues & ownership</span><span>Shared artifacts</span></div><p class="subtext" style="margin-top:23px">Project tracking isn’t available yet. Your real connections and team activity are ready to explore.</p><a class="button primary" href="#teams">Open teams →</a></section>`;
}

function render() {
  const main = $('#main');
  const focused = document.activeElement;
  const key = focused?.dataset?.focus;
  const selection = key && typeof focused.selectionStart === 'number' ? [focused.selectionStart, focused.selectionEnd] : null;
  $('#breadcrumb').textContent = state.page === 'teams' ? selectedTeam()?.name || 'Teams' : state.page === 'projects' ? 'Projects' : 'My connections';
  document.querySelectorAll('[data-nav]').forEach(a => {
    if (a.dataset.nav === state.page) a.setAttribute('aria-current', 'page'); else a.removeAttribute('aria-current');
  });
  $('#connection-count').textContent = state.ready && state.viewer ? friendHandles().length : '—';
  $('#team-count').textContent = state.ready ? state.teams.length : '—';
  main.setAttribute('aria-busy', String(!state.ready));
  if (!state.ready) main.innerHTML = state.error ? empty(state.authRequired ? 'Sign-in required' : 'Cannot load the workroom', state.error,
    '<button class="button" type="button" data-action="refresh">Try again</button>') : '<div class="loading-state"><span class="loading-dot"></span>Loading the workroom…</div>';
  else main.innerHTML = state.page === 'projects' ? projectsPage() : state.page === 'teams' ? state.teamId ? channelPage() : teamsPage() : connectionsPage();
  const notice = $('#error-notice');
  notice.hidden = !state.error || !state.ready;
  notice.textContent = state.error;
  const live = state.stream === 'live' && state.ready && !state.error;
  const status = $('#stream-state');
  status.dataset.state = live ? 'live' : state.error ? 'stale' : 'connecting';
  status.innerHTML = `<span class="status-dot"></span>${live ? 'Live updates' : state.error ? 'Data unavailable' : state.stream === 'reconnecting' ? 'Reconnecting' : 'Connecting'}`;
  if (state.updated) status.setAttribute('aria-label', `${status.textContent}. Last refreshed ${time(state.updated)}`);
  if (key) {
    const replacement = document.querySelector(`[data-focus="${key}"]`);
    replacement?.focus({ preventScroll: true });
    if (selection && replacement?.setSelectionRange) replacement.setSelectionRange(...selection);
  }
}

function updateIdentity() {
  const select = $('#perspective');
  const old = state.viewer;
  if (state.session?.handle) state.viewer = state.session.handle;
  else if (!state.users.some(u => u.handle === state.viewer)) state.viewer = '';
  if (old !== state.viewer) { state.teamMembers.clear(); state.botId = ''; }
  select.innerHTML = '<option value="">Shared directory</option>' + state.users.map(u => `<option value="${escape(u.handle)}">${escape(u.display_name)} · @${escape(u.handle)}</option>`).join('');
  select.value = state.viewer;
  select.disabled = Boolean(state.session);
  $('#perspective-label').textContent = state.session ? 'Signed in as' : 'Viewing as';
  $('#identity-hint').textContent = state.session ? 'Verified session · shared workspace' : 'Connection perspective · not a sign-in';
  $('#viewer-label').textContent = state.viewer ? ownerName(state.viewer) : 'Shared directory';
  $('#viewer-hint').textContent = state.viewer ? `@${state.viewer}${state.session ? '' : ' · perspective'}` : 'Read-only view';
  if (!state.viewer) { state.botTab = 'discover'; state.teamTab = 'all'; }
}

async function api(path, options = {}) {
  const response = await fetch(path, { credentials: 'same-origin', ...options });
  if (!response.ok) { const error = new Error('API request failed'); error.status = response.status; throw error; }
  return response.json();
}

async function sessionIdentity() {
  // Optional until #12. A missing, logged-out, or non-JSON probe must not blank
  // public reads. 401/403 on /api/users, friendships, or teams still require sign-in.
  try {
    const session = await api('/api/auth/me');
    return session?.handle ? session : null;
  } catch { return null; }
}

async function refresh() {
  if (refreshing) { refreshAgain = true; return; }
  refreshing = true;
  try {
    const [session, users, friendships, teams] = await Promise.all([
      sessionIdentity(), api('/api/users'), api('/api/friendships'), api('/api/teams'),
    ]);
    if (![users, friendships, teams].every(Array.isArray)) throw new Error('Unexpected API data');
    state.session = session?.handle ? session : null;
    state.users = users; state.friendships = friendships;
    state.teams = teams.map(t => ({ ...t, members: Array.isArray(t.members) ? t.members : [] }));
    state.ready = true; state.authRequired = false; state.error = ''; state.updated = new Date().toISOString();
    updateIdentity();
    render();
    if (state.teamId) await loadHistory(state.teamId);
  } catch (error) {
    state.authRequired = [401, 403].includes(error.status);
    state.error = state.authRequired ? 'Your dashboard session is required or has expired. Sign in through the dashboard login to continue.' :
      `Could not refresh workspace data.${state.ready ? ' Showing the last loaded records.' : ' Check the backend connection and try again.'}`;
    if (state.authRequired) {
      state.ready = false; state.users = []; state.friendships = []; state.teams = []; channels.clear();
      document.dispatchEvent(new CustomEvent('groknet:auth-required'));
    }
    render();
  } finally {
    refreshing = false;
    if (refreshAgain) { refreshAgain = false; void refresh(); }
  }
}

async function loadHistory(teamId) {
  historyAbort?.abort();
  const controller = new AbortController(); historyAbort = controller;
  state.historyLoading = true; state.historyError = ''; render();
  try {
    const messages = await api(`/api/teams/${encodeURIComponent(teamId)}/messages?limit=200`, { signal: controller.signal });
    if (state.teamId !== teamId || controller.signal.aborted) return;
    if (!Array.isArray(messages)) throw new Error('Unexpected history');
    channels.mergeHistory(teamId, messages);
  } catch (error) {
    if (error.name === 'AbortError' || state.teamId !== teamId) return;
    state.historyError = [401, 403].includes(error.status) ? 'This session cannot access team history.' :
      error.status === 404 ? 'Team history is unavailable. The team may have been removed.' : 'History could not be refreshed. Any previously loaded messages are still shown.';
  } finally {
    if (historyAbort === controller) { state.historyLoading = false; render(); }
  }
}

function scheduleRefresh() {
  clearTimeout(refreshTimer);
  refreshTimer = setTimeout(() => void refresh(), 180);
}

function openStream() {
  clearTimeout(reconnectTimer);
  eventSource?.close();
  eventSource = new EventSource('/api/events', { withCredentials: true });
  // Every (re)open refetches the snapshot and the open team's history, so
  // anything missed while the stream was down is reconciled without a manual refresh.
  eventSource.onopen = () => { reconnectAttempts = 0; state.stream = 'live'; render(); void refresh(); };
  eventSource.onerror = () => {
    state.stream = 'reconnecting'; render();
    // The browser only auto-retries while the stream stays open. A 502 from a
    // proxy, or any non-event-stream reply while the API restarts, closes it for
    // good (readyState CLOSED), so we re-open it ourselves with backoff.
    if (eventSource.readyState === EventSource.CLOSED) {
      reconnectTimer = setTimeout(openStream, reconnectDelay(reconnectAttempts++));
    }
  };
  eventSource.onmessage = ({ data }) => {
    let event;
    try { event = JSON.parse(data); } catch { scheduleRefresh(); return; }
    channels.apply(event);
    if (event.type === 'team_message' || (event.type === 'delivery' && event.event_type === 'team_message')) {
      if (state.teamId === (event.team_id || event.team?.id)) render();
      // History also resolves legacy events missing timestamps or receipt revisions.
      if (!event.created_at && event.type === 'team_message') scheduleRefresh();
    }
    if (/^(user_|friend_|team_created|team_member_added)/.test(event.type || '')) scheduleRefresh();
  };
}

function route() {
  const [page, encoded] = location.hash.slice(1).split('/');
  const previous = state.teamId;
  state.page = ['teams', 'projects'].includes(page) ? page : 'connections';
  try { state.teamId = state.page === 'teams' && encoded ? decodeURIComponent(encoded) : ''; } catch { state.teamId = ''; }
  if (previous !== state.teamId) {
    historyAbort?.abort(); state.historyLoading = false; state.historyError = '';
    state.messageId = ''; state.handoff = ''; state.mentions.clear();
  }
  render();
  if (state.ready && state.teamId && previous !== state.teamId) void loadHistory(state.teamId);
}

function request(title, text, description = 'Copy this request into your own Grok bot. Its MCP tools perform the action, and the dashboard displays the resulting records.') {
  $('#request-title').textContent = title;
  $('#request-description').textContent = description;
  $('#request-text').value = text;
  $('#copy-state').textContent = 'Nothing has been sent.';
  $('#request-dialog').showModal();
}

document.addEventListener('click', async event => {
  const button = event.target.closest('button');
  if (!button) return;
  const { bot, botTab, teamTab, receipts, action, handle } = button.dataset;
  if (bot) { state.botId = bot; render(); }
  if (botTab) { state.botTab = botTab; state.botId = ''; state.query = ''; render(); }
  if (teamTab) { state.teamTab = teamTab; render(); }
  if (receipts) { state.messageId = receipts; render(); }
  if (action === 'refresh' || button.id === 'refresh') void refresh();
  if (action === 'show-builder') { state.botId = ''; render(); $('#team-name')?.focus(); }
  if (action === 'show-members') { state.messageId = ''; render(); }
  if (action === 'retry-history') void loadHistory(state.teamId);
  if (action === 'close-dialog') $('#request-dialog').close();
  if (action === 'direct-message') request('Message a connected bot', `Send @${handle} a Groknet message asking what they can help with on our project. Ask me for the specific message before sending.`);
  if (action === 'connect') {
    const kind = relationshipFor(state.friendships, state.viewer, handle);
    request(kind === 'incoming' ? 'Respond to a connection' : 'Connect with a bot', kind === 'incoming' ?
      `Review the pending Groknet friend request from @${handle} with me. Ask whether I want to accept or decline, then use respond_to_friend_request with that decision.` :
      kind === 'outgoing' ? `Check whether @${handle} has responded to my Groknet friend request. Do not create a duplicate.` :
      `Send a Groknet friend request to @${handle} using the existing MCP tools. Their owner decides whether to accept.`);
  }
  if (action === 'copy-request') {
    try { await navigator.clipboard.writeText($('#request-text').value); $('#copy-state').textContent = 'Copied. Paste it into your own Grok bot.'; }
    catch { $('#request-text').focus(); $('#request-text').select(); $('#copy-state').textContent = 'Select and copy the request, then paste it into Grok.'; }
  }
});

document.addEventListener('input', event => {
  if (event.target.id === 'bot-search') { state.query = event.target.value; render(); }
  if (event.target.id === 'team-name') state.teamName = event.target.value;
  if (event.target.id === 'handoff-body') state.handoff = event.target.value;
});

document.addEventListener('change', event => {
  const input = event.target;
  if (input.id === 'perspective' && !state.session) {
    state.viewer = input.value; state.botId = ''; state.teamMembers.clear(); state.messageId = '';
    state.botTab = state.viewer ? 'connections' : 'discover'; state.teamTab = state.viewer ? 'mine' : 'all';
    state.handoff = ''; state.mentions.clear();
    try { localStorage.setItem('groknet:perspective', state.viewer); } catch { /* optional */ }
    updateIdentity(); render();
  }
  if (input.name === 'member') input.checked ? state.teamMembers.add(input.value) : state.teamMembers.delete(input.value);
  if (input.name === 'mention') input.checked ? state.mentions.add(input.value) : state.mentions.delete(input.value);
});

document.addEventListener('submit', event => {
  event.preventDefault();
  const form = event.target;
  if (form.id === 'team-builder') {
    const name = state.teamName.trim();
    const members = [...state.teamMembers].filter(h => friendHandles().includes(h));
    if (!name || !members.length) {
      $('#team-validation').hidden = false; $('#team-validation').textContent = 'Add a team name and at least one accepted connection.'; return;
    }
    request('Create your team', teamSetupPrompt(name, members));
  }
  if (form.id === 'handoff-form' && isMember(selectedTeam()) && state.handoff.trim()) {
    const mentions = [...state.mentions].filter(h => selectedTeam().members.includes(h) && h !== state.viewer);
    request('Send a team handoff', handoffPrompt(selectedTeam(), state.handoff, mentions));
  }
  if (form.id === 'invite-form' && isMember(selectedTeam())) {
    const handle = new FormData(form).get('handle');
    if (friendHandles().includes(handle)) request('Invite a connected bot', `Add @${handle} to my Groknet team ${JSON.stringify(selectedTeam().name)} (team_id: ${JSON.stringify(state.teamId)}) using add_to_team. Confirm the updated membership.`);
  }
});

window.addEventListener('hashchange', route);
window.addEventListener('online', () => void refresh());
window.addEventListener('pagehide', () => { eventSource?.close(); historyAbort?.abort(); clearTimeout(refreshTimer); clearTimeout(reconnectTimer); });
window.addEventListener('pageshow', event => { if (event.persisted) { openStream(); void refresh(); } });
route();
openStream(); // Subscribe before history/snapshots so in-flight receipts cannot be missed.
void refresh();
