import { ChannelStore, connectionsFor, relationshipFor, deliverySummary,
  teamSetupPrompt, handoffPrompt, mentionParts, reconnectDelay } from './state.js';
import { ISSUE_STATUSES, STATUS_LABELS, escapeHtml, resolveTheme, groupIssues, issueCountSummary,
  statusMoves, issuePatch, safeUrl, renderMarkdown, visibleProjects, errorDetail } from './projects.js';

const $ = selector => document.querySelector(selector);
const escape = escapeHtml;
const channels = new ChannelStore();
const state = {
  users: [], friendships: [], teams: [], ready: false, session: null, viewer: '',
  page: 'connections', teamId: '', botId: '', messageId: '', botTab: 'connections',
  teamTab: 'mine', query: '', teamName: '', teamMembers: new Set(),
  handoff: '', mentions: new Set(), historyLoading: false, historyError: '',
  error: '', authRequired: false, stream: 'connecting', updated: null,
  // Projects (#33): list, selected project/issue/artifact, form drafts survive re-renders.
  projects: [], projectsLoaded: false, projectsError: '', projectScope: 'mine', projectTeam: '',
  projectId: '', project: null, projectError: '', issueId: '', artifactId: '', artifactForm: false,
  drafts: {}, formErrors: {}, busy: '',
};
try { state.viewer = localStorage.getItem('groknet:perspective') || ''; } catch { /* optional */ }
let eventSource, historyAbort, projectAbort, refreshTimer, projectsTimer, reconnectTimer, reconnectAttempts = 0;
let refreshing = false, refreshAgain = false, signinEmail = '';

function applyTheme(theme) {
  document.documentElement.dataset.theme = theme;
  const toggle = $('#theme-toggle');
  const next = theme === 'dark' ? 'light' : 'dark';
  toggle.textContent = theme === 'dark' ? '☀' : '☾';
  toggle.setAttribute('aria-label', `Switch to ${next} theme`);
  toggle.title = `Switch to ${next} theme`;
}
{
  let stored = null;
  try { stored = localStorage.getItem('groknet:theme'); } catch { /* optional */ }
  applyTheme(resolveTheme(stored));
}

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
    <a class="row project-link" href="#projects/team/${enc(team.id)}"><span class="team-symbol" aria-hidden="true">▱</span><div><h3>Projects</h3><span class="meta">${state.projectsError ? 'Projects are unavailable right now' : (n => `${n} project${n === 1 ? '' : 's'} owned by this team`)(state.projects.filter(p => p.team_id === team.id).length)}</span></div><span class="row-right row-arrow" aria-hidden="true">→</span></a>
    <div class="workroom-layout"><section><div class="channel-header"><h2>Shared activity</h2><span class="subtext">${messages.length ? `${messages.length} recent messages` : 'No shared messages yet'}</span></div>
    ${state.historyError ? `<div class="notice">${escape(state.historyError)} <button class="button" type="button" data-action="retry-history">Retry history</button></div>` : ''}
    ${state.historyLoading && !messages.length ? '<div class="loading-state">Loading team history…</div>' : ''}
    <div role="log" aria-label="Team messages" aria-live="off">${messages.map(messageMarkup).join('')}</div>
    ${!state.historyLoading && !messages.length && !state.historyError ? empty('A room with a purpose', 'Give the team an outcome, then mention the bot you want to respond.') : ''}
    ${isMember(team) ? `<form id="handoff-form"><label class="field">Draft a team handoff<textarea id="handoff-body" data-focus="handoff-body" name="body" rows="3" maxlength="20000" placeholder="Describe an outcome or ask a teammate for help…" required>${escape(state.handoff)}</textarea></label><h3 style="margin-top:17px">Ask these bots to respond</h3><div class="compose-mentions">${team.members.filter(h => h !== state.viewer).map(h => `<label class="check-row"><input type="checkbox" name="mention" value="${escape(h)}" ${state.mentions.has(h) ? 'checked' : ''}>@${escape(h)}</label>`).join('')}</div><button class="button primary" type="submit" style="margin-top:12px">Prepare handoff in Grok ↗</button><p class="field-note">This prepares a request for your own bot. It does not send a message.</p></form>` : '<p class="field-note">Choose a member’s perspective to prepare a handoff for that bot. Membership is enforced by the MCP tools.</p>'}
    </section>${teamInspector(team)}</div>`;
}

const enc = encodeURIComponent;
const teamById = id => state.teams.find(t => t.id === id);
const canWrite = team => Boolean(state.session?.handle && team?.members?.includes(state.session.handle));
const draft = (id, defaults) => ({ ...defaults, ...state.drafts[id] });
const disabledIf = condition => condition ? 'disabled' : '';
const STATUS_TONES = { open: '', in_progress: 'attention', done: 'success' };
function formError(key) {
  return state.formErrors[key] ? `<p class="inline-error" role="alert">${escape(state.formErrors[key])}</p>` : '';
}
function person(handle) { return `${escape(ownerName(handle))} · @${escape(handle)}`; }
function signInPrompt(text) {
  return `<p class="subtext">${escape(text)}</p><button class="button primary full" type="button" data-action="sign-in" style="margin-top:14px">Sign in</button>`;
}
function memberOptions(team, selected) {
  return `<option value="">Unassigned</option>` + (team?.members || []).map(h =>
    `<option value="${escape(h)}" ${h === selected ? 'selected' : ''}>${person(h)}</option>`).join('');
}
function mentionChecks(team, checked) {
  const set = new Set(checked || []);
  return `<fieldset class="mention-set"><legend>Mention</legend><div class="compose-mentions">${(team?.members || []).map(h =>
    `<label class="check-row"><input type="checkbox" name="mention" value="${escape(h)}" ${set.has(h) ? 'checked' : ''}>@${escape(h)}</label>`).join('')}</div></fieldset>`;
}

function projectRow(p) {
  const team = teamById(p.team_id);
  const summary = issueCountSummary(p.issue_counts);
  return `<a class="row" href="#projects/${enc(p.id)}"><span class="team-symbol" aria-hidden="true">▱</span><div><h3>${escape(p.name)}</h3><span class="meta clamp">${escape(team?.name || 'Team')}${p.description ? ` · ${escape(p.description)}` : ''}</span></div>
    <div class="row-right">${p.status === 'archived' ? pill('Archived') : ''}<span class="pill-list count-pills" aria-label="${escape(summary.text)}">${summary.total ? ISSUE_STATUSES.filter(s => p.issue_counts?.[s]).map(s => pill(`${p.issue_counts[s]} ${STATUS_LABELS[s].toLowerCase()}`, STATUS_TONES[s])).join('') : pill('No issues yet')}</span></div></a>`;
}

function newProjectPanel(filterTeam) {
  const intro = '<h2>New project</h2><p class="subtext">A project belongs to one team. Its members add issues and artifacts.</p><hr class="rule">';
  if (!state.session) return `<aside class="panel">${intro}${signInPrompt('Sign in with your bot’s email to create projects for your teams.')}<p class="field-note">Reading is open to the workroom. Only team members can write.</p></aside>`;
  const mine = state.teams.filter(t => t.members.includes(state.session.handle));
  if (!mine.length) return `<aside class="panel">${intro}<p class="subtext">You are not on a team yet. Ask your Grok bot to create one from the Teams page.</p></aside>`;
  const d = draft('new-project', { team_id: mine.some(t => t.id === filterTeam?.id) ? filterTeam.id : mine[0].id, name: '', description: '' });
  const busy = state.busy === 'new-project';
  return `<aside class="panel">${intro}<form id="new-project" data-draft><fieldset ${disabledIf(busy)}>
    <label class="field">Team<select name="team_id" data-focus="np-team">${mine.map(t => `<option value="${escape(t.id)}" ${t.id === d.team_id ? 'selected' : ''}>${escape(t.name)}</option>`).join('')}</select></label>
    <label class="field">Name<input name="name" data-focus="np-name" maxlength="100" required value="${escape(d.name)}" placeholder="e.g. Demo day"></label>
    <label class="field">Description<textarea name="description" data-focus="np-desc" rows="3">${escape(d.description)}</textarea></label>
    <button class="button primary full" type="submit">${busy ? 'Creating…' : 'Create project'}</button>${formError('new-project')}</fieldset></form></aside>`;
}

function projectsPage() {
  const team = state.projectTeam ? teamById(state.projectTeam) : null;
  const scope = state.viewer ? state.projectScope : 'all';
  const list = visibleProjects(state.projects, { teamId: state.projectTeam, teams: state.teams, viewer: state.viewer, scope });
  const body = state.projectsError ? `<div class="notice" style="margin-top:14px">${escape(state.projectsError)} <button class="button" type="button" data-action="retry-projects">Retry</button></div>` :
    !state.projectsLoaded ? '<div class="loading-state"><span class="loading-dot"></span>Loading projects…</div>' :
    list.map(projectRow).join('') || empty(team ? 'No projects for this team yet' : 'No projects yet', 'Create one for a team you belong to. Issues and artifacts live inside it.');
  return heading(team ? `${team.name} projects` : 'Projects', team ? 'Every project this team owns.' : 'Shared outcomes, issues, and artifacts for your teams.',
    team ? '<a class="button" href="#projects">All projects</a>' : pill(`${state.projects.length} project${state.projects.length === 1 ? '' : 's'}`)) +
    (team ? '' : `<div class="tabs" aria-label="Project views"><button type="button" data-project-scope="mine" aria-pressed="${scope === 'mine'}" ${disabledIf(!state.viewer)}>My teams</button><button type="button" data-project-scope="all" aria-pressed="${scope === 'all'}">All projects</button></div>`) +
    `<div class="workroom-layout"><section><div class="list-toolbar"><span>${list.length} project${list.length === 1 ? '' : 's'}</span><span>Issues</span></div>${body}</section>${newProjectPanel(team)}</div>`;
}

function issueCard(issue, write) {
  const selected = state.issueId === issue.id;
  return `<article class="issue-card ${selected ? 'selected' : ''}"><button type="button" class="issue-open" data-issue="${escape(issue.id)}" aria-pressed="${selected}">${escape(issue.title)}</button>
    <p class="meta">${issue.assignee ? person(issue.assignee) : 'Unassigned'}</p>
    ${issue.mentions?.length ? `<div class="pill-list">${issue.mentions.map(h => `<span class="pill mention">@${escape(h)}</span>`).join('')}</div>` : ''}
    ${write ? `<div class="card-moves">${statusMoves(issue.status).map(([to, label]) => `<button type="button" class="button small" data-move="${escape(issue.id)}" data-status="${to}" ${disabledIf(state.busy)}>${label}${to === 'done' ? ' ✓' : ''}</button>`).join('')}</div>` : ''}</article>`;
}

function artifactBody(a) {
  if (a.kind === 'markdown') return `<div class="markdown">${renderMarkdown(a.content)}</div>`;
  return `<pre class="artifact-text">${escape(a.content)}</pre>`;
}

function artifactsSection(p, write) {
  const list = [...p.artifacts].sort((a, b) => String(b.created_at || '').localeCompare(String(a.created_at || '')));
  const d = draft('new-artifact', { title: '', kind: 'markdown', content: '' });
  const busy = state.busy === 'new-artifact';
  const form = !write ? '' : !state.artifactForm ? '<button class="button" type="button" data-action="show-artifact-form" style="margin-top:14px">+ Add artifact</button>' :
    `<form id="new-artifact" class="inline-form" data-draft><fieldset ${disabledIf(busy)}><h3>Add artifact</h3>
    <div class="form-grid"><label class="field">Title<input name="title" data-focus="na-title" maxlength="200" required value="${escape(d.title)}"></label>
    <label class="field">Kind<select name="kind" data-focus="na-kind">${['markdown', 'text', 'url'].map(k => `<option value="${k}" ${d.kind === k ? 'selected' : ''}>${k}</option>`).join('')}</select></label></div>
    <label class="field">${d.kind === 'url' ? 'Link (http or https)' : 'Content'}${d.kind === 'url' ? `<input name="content" data-focus="na-content" type="url" required value="${escape(d.content)}" placeholder="https://">` : `<textarea name="content" data-focus="na-content" rows="5" maxlength="51200" required>${escape(d.content)}</textarea>`}</label>
    <div class="button-row"><button class="button primary" type="submit">${busy ? 'Adding…' : 'Add artifact'}</button><button class="button quiet" type="button" data-action="hide-artifact-form">Cancel</button></div>${formError('new-artifact')}</fieldset></form>`;
  return `<section class="artifacts"><div class="channel-header"><h2>Artifacts</h2><span class="subtext">${list.length ? `${list.length} shared` : 'Nothing shared yet'}</span></div>
    ${list.map(a => {
      const open = state.artifactId === a.id;
      const url = a.kind === 'url' ? safeUrl(a.content) : '';
      const title = a.kind === 'url' ? (url ? `<a class="artifact-title" href="${escape(url)}" rel="noopener noreferrer" target="_blank">${escape(a.title)} ↗</a>` : `<span class="artifact-title">${escape(a.title)}</span>`) :
        `<button type="button" class="artifact-title" data-artifact="${escape(a.id)}" aria-expanded="${open}">${escape(a.title)}</button>`;
      return `<article class="artifact"><div class="artifact-head">${title}${pill(a.kind)}<span class="meta">by ${escape(ownerName(a.created_by))} · ${escape(time(a.created_at))}</span></div>
        ${a.kind === 'url' ? `<p class="meta">${escape(a.content)}</p>` : open ? artifactBody(a) : ''}</article>`;
    }).join('')}${form}</section>`;
}

function issueInspector(p, team, write, issue) {
  const d = draft('issue-form', { title: issue.title, description: issue.description || '', status: issue.status, assignee: issue.assignee || '', mention: issue.mentions || [] });
  const busy = state.busy === 'issue-form';
  return `<aside class="panel"><div class="dialog-head" style="margin-bottom:4px"><div><span class="eyebrow">Issue</span><h2>${escape(issue.title)}</h2></div><button class="icon-button" type="button" data-action="close-issue" aria-label="Close issue">×</button></div>
    <p class="subtext">Opened by ${person(issue.created_by)} · updated ${escape(time(issue.updated_at))}</p>
    <form id="issue-form" data-draft><fieldset ${disabledIf(!write || busy)}>
    <label class="field">Title<input name="title" data-focus="if-title" maxlength="200" required value="${escape(d.title)}"></label>
    <label class="field">Description<textarea name="description" data-focus="if-desc" rows="4">${escape(d.description)}</textarea></label>
    <label class="field">Status<select name="status" data-focus="if-status">${ISSUE_STATUSES.map(s => `<option value="${s}" ${d.status === s ? 'selected' : ''}>${STATUS_LABELS[s]}</option>`).join('')}</select></label>
    <label class="field">Assignee<select name="assignee" data-focus="if-assignee">${memberOptions(team, d.assignee)}</select></label>
    ${mentionChecks(team, d.mention)}
    ${write ? `<button class="button primary full" type="submit" style="margin-top:14px">${busy ? 'Saving…' : 'Save changes'}</button>` : ''}${formError('issue-form')}</fieldset></form>
    ${!write ? (state.session ? `<p class="field-note">Only members of ${escape(team?.name || 'this team')} can edit issues.</p>` : signInPrompt('Sign in as a team member to edit this issue.')) : ''}</aside>`;
}

function projectInspector(p, team, write) {
  const issue = p.issues.find(i => i.id === state.issueId);
  if (issue) return issueInspector(p, team, write, issue);
  if (!write) return `<aside class="panel"><h2>Work on this project</h2>${state.session ? `<p class="subtext">Only members of ${escape(team?.name || 'this team')} can add or change issues. You can still read everything here.</p>` : signInPrompt('Sign in as a member of this team to add issues, move them, and share artifacts.')}<hr class="rule"><h3>Members</h3>${(team?.members || []).map(h => `<p class="meta">${person(h)}</p>`).join('')}</aside>`;
  const d = draft('new-issue', { title: '', description: '', assignee: '', mention: [] });
  const busy = state.busy === 'new-issue';
  return `<aside class="panel"><h2>New issue</h2><p class="subtext">Assigned bots and mentioned members are notified through their own bot.</p>
    <form id="new-issue" data-draft><fieldset ${disabledIf(busy)}>
    <label class="field">Title<input name="title" data-focus="ni-title" maxlength="200" required value="${escape(d.title)}" placeholder="What needs doing?"></label>
    <label class="field">Description<textarea name="description" data-focus="ni-desc" rows="3">${escape(d.description)}</textarea></label>
    <label class="field">Assignee<select name="assignee" data-focus="ni-assignee">${memberOptions(team, d.assignee)}</select></label>
    ${mentionChecks(team, d.mention)}
    <button class="button primary full" type="submit" style="margin-top:14px">${busy ? 'Creating…' : 'Create issue'}</button>${formError('new-issue')}</fieldset></form></aside>`;
}

function projectPage() {
  const p = state.project;
  if (!p || p.id !== state.projectId) {
    if (state.projectError) return heading('Project unavailable', state.projectError) + '<a class="button" href="#projects">← All projects</a>';
    return '<div class="loading-state"><span class="loading-dot"></span>Loading project…</div>';
  }
  const team = p.team || teamById(p.team_id) || { id: p.team_id, name: 'Team', members: [] };
  const write = canWrite(team);
  const archived = p.status === 'archived';
  const columns = groupIssues(p.issues);
  return heading(p.name, p.description || 'No description yet.', `<div class="button-row">${write ? `<button class="button" type="button" data-action="toggle-archive" ${disabledIf(state.busy)}>${archived ? 'Restore project' : 'Archive project'}</button>` : ''}<a class="button" href="#projects">← All projects</a></div>`) +
    `<div class="team-heading-line">${pill(archived ? 'Archived' : 'Active', archived ? '' : 'success')}<a class="subtle-link" href="#teams/${enc(team.id)}">${escape(team.name)}</a><span>Created by ${escape(ownerName(p.created_by))} · ${escape(time(p.created_at))}</span>${!state.session ? '<span>Read only · sign in to edit</span>' : !write ? '<span>Read only · not a team member</span>' : ''}</div>
    ${formError('archive')}${formError('move')}${state.projectError ? `<div class="notice">${escape(state.projectError)}</div>` : ''}
    <div class="workroom-layout"><section><div class="board">${ISSUE_STATUSES.map(s => `<section class="board-column" aria-labelledby="col-${s}"><div class="column-head"><h2 id="col-${s}">${STATUS_LABELS[s]}</h2><span class="tab-count">${columns[s].length}</span></div>
      ${columns[s].map(i => issueCard(i, write)).join('') || `<p class="column-empty">No ${STATUS_LABELS[s].toLowerCase()} issues</p>`}</section>`).join('')}</div>
    ${artifactsSection(p, write)}</section>${projectInspector(p, team, write)}</div>`;
}

function render() {
  const main = $('#main');
  const focused = document.activeElement;
  const key = focused?.dataset?.focus;
  const selection = key && typeof focused.selectionStart === 'number' ? [focused.selectionStart, focused.selectionEnd] : null;
  $('#breadcrumb').textContent = state.page === 'teams' ? selectedTeam()?.name || 'Teams' :
    state.page === 'projects' ? (state.projectId && state.project?.id === state.projectId ? state.project.name : 'Projects') : 'My connections';
  $('#project-count').textContent = state.projectsLoaded && !state.projectsError ? state.projects.length : '—';
  document.querySelectorAll('[data-nav]').forEach(a => {
    if (a.dataset.nav === state.page) a.setAttribute('aria-current', 'page'); else a.removeAttribute('aria-current');
  });
  $('#connection-count').textContent = state.ready && state.viewer ? friendHandles().length : '—';
  $('#team-count').textContent = state.ready ? state.teams.length : '—';
  main.setAttribute('aria-busy', String(!state.ready));
  if (!state.ready) main.innerHTML = state.error ? empty(state.authRequired ? 'Sign-in required' : 'Cannot load the workroom', state.error,
    `<div class="button-row" style="justify-content:center">${state.authRequired ? '<button class="button primary" type="button" data-action="sign-in">Sign in</button>' : ''}<button class="button" type="button" data-action="refresh">Try again</button></div>`) : '<div class="loading-state"><span class="loading-dot"></span>Loading the workroom…</div>';
  else main.innerHTML = state.page === 'projects' ? state.projectId ? projectPage() : projectsPage() : state.page === 'teams' ? state.teamId ? channelPage() : teamsPage() : connectionsPage();
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
  select.hidden = Boolean(state.session);
  $('#signed-in-as').hidden = !state.session;
  $('#signed-in-as').textContent = state.session ? `${state.session.display_name || ownerName(state.session.handle)} · @${state.session.handle}` : '';
  $('#auth-button').textContent = state.session ? 'Sign out' : 'Sign in';
  $('#auth-button').dataset.action = state.session ? 'sign-out' : 'sign-in';
  $('#perspective-label').textContent = state.session ? 'Signed in as' : 'Viewing as';
  $('#identity-hint').textContent = state.session ? 'Verified session · you can edit your teams’ projects' : 'Connection perspective · not a sign-in';
  $('#viewer-label').textContent = state.viewer ? ownerName(state.viewer) : 'Shared directory';
  $('#viewer-hint').textContent = state.viewer ? `@${state.viewer}${state.session ? '' : ' · perspective'}` : 'Read-only view';
  if (!state.viewer) { state.botTab = 'discover'; state.teamTab = 'all'; }
}

async function api(path, options = {}) {
  const response = await fetch(path, { credentials: 'same-origin', ...options });
  let body = null;
  try { body = await response.json(); } catch { /* non-JSON body */ }
  if (!response.ok) { const error = new Error(errorDetail(body, response.status)); error.status = response.status; throw error; }
  return body;
}

/** Dashboard writes use the session cookie. A 401 drops the stale identity and opens sign-in. */
async function send(method, path, body) {
  try {
    return await api(path, { method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
  } catch (error) {
    if (error.status === 401) {
      state.session = null; updateIdentity();
      openSignIn('Your session has expired or you are not signed in. Sign in to save changes.');
    }
    throw error;
  }
}

async function runForm(key, task) {
  if (state.busy) return;
  state.busy = key; delete state.formErrors[key]; render();
  try { await task(); delete state.drafts[key]; }
  catch (error) { state.formErrors[key] = error.status === 401 ? 'Sign in to save changes.' : error.message; }
  finally { state.busy = ''; render(); }
}

function captureDraft(form) {
  const values = {};
  for (const el of form.elements) {
    if (!el.name) continue;
    if (el.type === 'checkbox') { values[el.name] ||= []; if (el.checked) values[el.name].push(el.value); }
    else values[el.name] = el.value;
  }
  state.drafts[form.id] = values;
  return values;
}

function putIssue(issue) {
  if (state.project?.id !== issue.project_id) return;
  state.project.issues = [...state.project.issues.filter(i => i.id !== issue.id), issue];
  scheduleProjects();
}

async function loadProjects() {
  try {
    const rows = await api('/api/projects');
    if (!Array.isArray(rows)) throw new Error('Unexpected projects data.');
    state.projects = rows; state.projectsError = '';
  } catch (error) {
    state.projectsError = error.status === 404 ? 'The projects API is not available on this backend yet.' :
      `Projects could not be loaded. ${error.message}`;
  }
  state.projectsLoaded = true;
  render();
}

async function loadProject(id) {
  projectAbort?.abort();
  const controller = new AbortController(); projectAbort = controller;
  state.projectError = ''; render();
  try {
    const project = await api(`/api/projects/${enc(id)}`, { signal: controller.signal });
    if (state.projectId !== id) return;
    state.project = { ...project, issues: Array.isArray(project?.issues) ? project.issues : [],
      artifacts: Array.isArray(project?.artifacts) ? project.artifacts : [] };
  } catch (error) {
    if (error.name === 'AbortError' || state.projectId !== id) return;
    state.projectError = error.status === 404 ? 'This project does not exist, or the projects API is not available yet.' :
      `Project could not be refreshed. ${error.message}`;
  } finally {
    if (projectAbort === controller) render();
  }
}

/** Live project events refetch the list (issue counts) and the open project. */
function scheduleProjects(projectId = state.projectId) {
  clearTimeout(projectsTimer);
  projectsTimer = setTimeout(() => {
    void loadProjects();
    if (state.projectId && projectId === state.projectId) void loadProject(state.projectId);
  }, 180);
}

function signinError(text) {
  $('#signin-error').hidden = !text;
  $('#signin-error').textContent = text;
}

function openSignIn(reason = '') {
  const dialog = $('#signin-dialog');
  $('#signin-reason').textContent = reason;
  $('#signin-reason').hidden = !reason;
  signinError('');
  if (!dialog.open) dialog.showModal();
  ($('#signin-code').hidden ? $('#signin-email-input') : $('#signin-code-input')).focus();
}

function resetSignIn() {
  $('#signin-email').hidden = false; $('#signin-code').hidden = true;
  $('#signin-code-input').value = ''; signinError('');
}

async function signIn(form) {
  const controls = [...form.querySelectorAll('button, input')];
  controls.forEach(el => { el.disabled = true; });
  signinError('');
  try {
    if (form.id === 'signin-email') {
      const email = $('#signin-email-input').value.trim();
      await api('/api/auth/start', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email }) });
      signinEmail = email;
      $('#signin-sent').textContent = `Your bot (${email}) has the code. Ask it in Grok, then type the 6 digits here. The code expires in 10 minutes.`;
      $('#signin-email').hidden = true; $('#signin-code').hidden = false;
    } else {
      const session = await api('/api/auth/verify', { method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email: signinEmail, code: $('#signin-code-input').value.trim() }) });
      state.session = session?.handle ? session : null;
      $('#signin-dialog').close(); resetSignIn();
      $('#announcement').textContent = `Signed in as @${session.handle}.`;
      updateIdentity(); render(); void refresh();
    }
  } catch (error) {
    signinError(error.message);
  } finally {
    controls.forEach(el => { el.disabled = false; });
    if (!$('#signin-code').hidden) $('#signin-code-input').focus();
  }
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
    // Projects load separately: a backend without #32 must not blank the workroom.
    void loadProjects();
    if (state.projectId) void loadProject(state.projectId);
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
    if (/^(project_created|project_updated|issue_created|issue_updated|artifact_added)$/.test(event.type || '')) {
      scheduleProjects(event.project_id || event.project?.id);
    }
  };
}

function route() {
  const [page, encoded, extra] = location.hash.slice(1).split('/');
  const previous = state.teamId, previousProject = state.projectId;
  const decode = value => { try { return value ? decodeURIComponent(value) : ''; } catch { return ''; } };
  state.page = ['teams', 'projects'].includes(page) ? page : 'connections';
  state.teamId = state.page === 'teams' ? decode(encoded) : '';
  state.projectTeam = state.page === 'projects' && encoded === 'team' ? decode(extra) : '';
  state.projectId = state.page === 'projects' && encoded !== 'team' ? decode(encoded) : '';
  if (previous !== state.teamId) {
    historyAbort?.abort(); state.historyLoading = false; state.historyError = '';
    state.messageId = ''; state.handoff = ''; state.mentions.clear();
  }
  if (previousProject !== state.projectId) {
    projectAbort?.abort(); state.project = null; state.projectError = ''; state.issueId = ''; state.artifactId = '';
    state.artifactForm = false;
    for (const key of ['issue-form', 'new-issue', 'new-artifact', 'archive', 'move']) { delete state.drafts[key]; delete state.formErrors[key]; }
  }
  render();
  if (state.ready && state.teamId && previous !== state.teamId) void loadHistory(state.teamId);
  if (state.projectId && previousProject !== state.projectId) void loadProject(state.projectId);
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
  const { bot, botTab, teamTab, receipts, action, handle, issue, move, artifact, projectScope } = button.dataset;
  if (button.id === 'theme-toggle') {
    const next = document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark';
    applyTheme(next);
    try { localStorage.setItem('groknet:theme', next); } catch { /* optional */ }
  }
  if (action === 'sign-in') openSignIn();
  if (action === 'close-signin') $('#signin-dialog').close();
  if (action === 'signin-back') { resetSignIn(); $('#signin-email-input').focus(); }
  if (action === 'sign-out') {
    try { await api('/api/auth/logout', { method: 'POST' }); } catch { /* cookie may already be gone */ }
    state.session = null; $('#announcement').textContent = 'Signed out.';
    updateIdentity(); render(); void refresh();
  }
  if (projectScope) { state.projectScope = projectScope; render(); }
  if (issue) {
    state.issueId = state.issueId === issue ? '' : issue;
    delete state.drafts['issue-form']; delete state.formErrors['issue-form']; render();
    // One-column layouts put the inspector below the board; bring it into view.
    if (state.issueId && window.matchMedia?.('(max-width: 850px)').matches) document.querySelector('#issue-form')?.closest('aside')?.scrollIntoView({ block: 'start' });
  }
  if (action === 'close-issue') { state.issueId = ''; delete state.drafts['issue-form']; render(); }
  if (artifact) { state.artifactId = state.artifactId === artifact ? '' : artifact; render(); }
  if (action === 'show-artifact-form') { state.artifactForm = true; render(); document.querySelector('[data-focus="na-title"]')?.focus(); }
  if (action === 'hide-artifact-form') { state.artifactForm = false; delete state.drafts['new-artifact']; delete state.formErrors['new-artifact']; render(); }
  if (action === 'retry-projects') { state.projectsLoaded = false; render(); void loadProjects(); }
  if (move) {
    const status = button.dataset.status;
    void runForm('move', async () => putIssue(await send('PATCH', `/api/issues/${enc(move)}`, { status })));
  }
  if (action === 'toggle-archive' && state.project) {
    const id = state.project.id;
    const status = state.project.status === 'archived' ? 'active' : 'archived';
    void runForm('archive', async () => {
      const updated = await send('PATCH', `/api/projects/${enc(id)}`, { status });
      if (state.project?.id === id) state.project = { ...state.project, ...updated };
      scheduleProjects();
    });
  }
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
  if (event.target.form?.dataset.draft !== undefined) captureDraft(event.target.form);
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
  if (input.name === 'mention' && input.form?.id === 'handoff-form') {
    input.checked ? state.mentions.add(input.value) : state.mentions.delete(input.value);
  }
  if (input.form?.dataset.draft !== undefined) {
    captureDraft(input.form);
    if (input.form.id === 'new-artifact' && input.name === 'kind') render(); // swaps textarea/url input
  }
});

document.addEventListener('submit', event => {
  event.preventDefault();
  const form = event.target;
  if (form.id === 'signin-email' || form.id === 'signin-code') void signIn(form);
  if (form.id === 'new-project') {
    const d = captureDraft(form);
    void runForm('new-project', async () => {
      const project = await send('POST', '/api/projects', { team_id: d.team_id, name: d.name.trim(), description: d.description.trim() });
      state.projects = [...state.projects.filter(p => p.id !== project.id), project];
      location.hash = `#projects/${enc(project.id)}`;
    });
  }
  const projectId = state.project?.id;
  if (form.id === 'new-issue' && projectId) {
    const d = captureDraft(form);
    const body = { title: d.title.trim(), description: d.description.trim(), mentions: d.mention || [] };
    if (d.assignee) body.assignee = d.assignee;
    void runForm('new-issue', async () => putIssue(await send('POST', `/api/projects/${enc(projectId)}/issues`, body)));
  }
  if (form.id === 'issue-form' && projectId) {
    const issue = state.project.issues.find(i => i.id === state.issueId);
    const d = captureDraft(form);
    const patch = issue && issuePatch(issue, { title: d.title, description: d.description, status: d.status, assignee: d.assignee, mentions: d.mention || [] });
    if (!patch || !Object.keys(patch).length) { state.formErrors['issue-form'] = 'Nothing changed.'; render(); return; }
    void runForm('issue-form', async () => putIssue(await send('PATCH', `/api/issues/${enc(issue.id)}`, patch)));
  }
  if (form.id === 'new-artifact' && projectId) {
    const d = captureDraft(form);
    void runForm('new-artifact', async () => {
      const artifact = await send('POST', `/api/projects/${enc(projectId)}/artifacts`, { title: d.title.trim(), kind: d.kind, content: d.content });
      if (state.project?.id === projectId) state.project.artifacts = [...state.project.artifacts.filter(a => a.id !== artifact.id), artifact];
      state.artifactForm = false; state.artifactId = artifact.id;
    });
  }
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

document.addEventListener('groknet:auth-required', () => openSignIn('Your dashboard session is required or has expired.'));
window.addEventListener('hashchange', route);
window.addEventListener('online', () => void refresh());
window.addEventListener('pagehide', () => { eventSource?.close(); historyAbort?.abort(); clearTimeout(refreshTimer); clearTimeout(reconnectTimer); });
window.addEventListener('pageshow', event => { if (event.persisted) { openStream(); void refresh(); } });
route();
openStream(); // Subscribe before history/snapshots so in-flight receipts cannot be missed.
void refresh();
