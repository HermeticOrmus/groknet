/** Projects, issues, artifacts and theme rules. No DOM, no fetch. */
export const ISSUE_STATUSES = ['open', 'in_progress', 'done'];
export const STATUS_LABELS = { open: 'Open', in_progress: 'In progress', done: 'Done' };

export const escapeHtml = value => String(value ?? '').replace(/[&<>"']/g,
  c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

/**
 * A stored toggle choice wins; otherwise dark. prefers-color-scheme has no
 * "no preference" value in current browsers (light is what most report by
 * default), so following it would make light the de facto default.
 */
export function resolveTheme(stored) {
  return stored === 'dark' || stored === 'light' ? stored : 'dark';
}

export function groupIssues(issues = []) {
  const columns = Object.fromEntries(ISSUE_STATUSES.map(s => [s, []]));
  for (const issue of issues) if (columns[issue?.status]) columns[issue.status].push(issue);
  for (const list of Object.values(columns)) {
    list.sort((a, b) => String(a.created_at || '').localeCompare(String(b.created_at || '')) ||
      String(a.id).localeCompare(String(b.id)));
  }
  return columns;
}

export function issueCountSummary(counts = {}) {
  const n = s => Math.max(0, Number(counts?.[s]) || 0);
  const total = ISSUE_STATUSES.reduce((sum, s) => sum + n(s), 0);
  if (!total) return { total, text: 'No issues yet' };
  return { total, text: ISSUE_STATUSES.filter(s => n(s)).map(s => `${n(s)} ${STATUS_LABELS[s].toLowerCase()}`).join(' · ') };
}

/** Status moves offered on a card; no drag and drop. */
export function statusMoves(status) {
  return {
    open: [['in_progress', 'Start'], ['done', 'Done']],
    in_progress: [['open', 'Reopen'], ['done', 'Done']],
    done: [['open', 'Reopen']],
  }[status] || [];
}

/** Only the fields the person changed, in the #32 PATCH shape (assignee null clears). */
export function issuePatch(original, draft) {
  const patch = {};
  for (const key of ['title', 'description', 'status']) {
    if (draft[key] !== undefined && String(draft[key]) !== String(original[key] ?? '')) patch[key] = draft[key];
  }
  if (draft.assignee !== undefined) {
    const next = draft.assignee || null;
    if (next !== (original.assignee || null)) patch.assignee = next;
  }
  if (draft.mentions !== undefined) {
    const next = [...new Set(draft.mentions)].sort();
    const prev = [...new Set(original.mentions || [])].sort();
    if (next.join(',') !== prev.join(',')) patch.mentions = next;
  }
  if (typeof patch.title === 'string') patch.title = patch.title.trim();
  return patch;
}

/** Form values for the issue dialog: blanks for a new issue, the issue's own values to edit one. */
export function issueFormModel(issue = null) {
  return {
    title: issue?.title || '',
    description: issue?.description || '',
    status: ISSUE_STATUSES.includes(issue?.status) ? issue.status : 'open',
    assignee: issue?.assignee || '',
    mentions: [...new Set(issue?.mentions || [])],
  };
}

/** Handles offered as mention checkboxes: team members except the actor, plus anyone already mentioned. */
export function mentionChoices(members = [], actor = '', current = []) {
  return [...new Set([...members.filter(h => h !== actor), ...current])];
}

/**
 * What the issue dialog sends. Create: a POST body with only the filled fields, plus a
 * status to PATCH afterwards (POST /issues takes no status; new issues start open).
 * Edit: the issuePatch of changed fields, empty when nothing changed. A blank title is an error.
 */
export function issueSubmission(form, original = null) {
  if (!String(form?.title ?? '').trim()) return { error: 'Add a title.' };
  if (original) return { patch: issuePatch(original, form) };
  const body = { title: String(form.title).trim() };
  const description = String(form.description ?? '').trim();
  if (description) body.description = description;
  if (form.assignee) body.assignee = form.assignee;
  const mentions = [...new Set(form.mentions || [])];
  if (mentions.length) body.mentions = mentions;
  const status = ISSUE_STATUSES.includes(form.status) && form.status !== 'open' ? form.status : '';
  return { body, status };
}

const ASSIGNMENT_CHIPS = {
  pending: { label: 'Awaiting answer', tone: 'attention' },
  accepted: { label: 'Accepted', tone: 'success' },
  declined: { label: 'Declined', tone: 'danger' },
};

/** The assignee's answer as a pill, or null when nobody is assigned. Unknown reads as waiting. */
export function assignmentChip(issue) {
  if (!issue?.assignee) return null;
  return { ...(ASSIGNMENT_CHIPS[issue.assignment_status] || ASSIGNMENT_CHIPS.pending) };
}

/** Apply an `issue_response` SSE event to the open project detail without mutating it. */
export function applyIssueResponse(project, event) {
  if (!project || event?.project_id !== project.id) return project;
  if (!project.issues?.some(i => i.id === event.issue_id)) return project;
  return {
    ...project,
    issues: project.issues.map(i => i.id !== event.issue_id ? i :
      { ...i, assignment_status: event.assignment_status, assignment_comment: event.comment ?? null }),
  };
}

export function safeUrl(value) {
  const url = String(value ?? '').trim();
  return /^https?:\/\/[^\s]+$/i.test(url) ? url : '';
}

function inline(escaped) {
  // Input is already HTML-escaped. Code spans are protected from bold/link rules.
  return escaped.split(/(`[^`]+`)/g).map(part => {
    if (/^`[^`]+`$/.test(part)) return `<code>${part.slice(1, -1)}</code>`;
    return part
      .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
      .replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/gi,
        '<a href="$2" rel="noopener noreferrer" target="_blank">$1</a>');
  }).join('');
}

/** Escape first, then a minimal markdown subset. Raw HTML always renders as text. */
export function renderMarkdown(source) {
  const lines = escapeHtml(source).replace(/\r\n?/g, '\n').split('\n');
  const out = [];
  let list = null, paragraph = [], code = null;
  const flushParagraph = () => { if (paragraph.length) out.push(`<p>${inline(paragraph.join(' '))}</p>`); paragraph = []; };
  const closeList = () => { if (list) out.push(`</${list}>`); list = null; };
  for (const line of lines) {
    if (code) {
      if (/^```/.test(line)) { out.push(`<pre><code>${code.join('\n')}</code></pre>`); code = null; } else code.push(line);
      continue;
    }
    if (/^```/.test(line)) { flushParagraph(); closeList(); code = []; continue; }
    const head = line.match(/^(#{1,6})\s+(.*)$/);
    const bullet = line.match(/^\s*[-*]\s+(.*)$/);
    const ordered = line.match(/^\s*\d+[.)]\s+(.*)$/);
    if (head) { flushParagraph(); closeList(); const level = Math.min(head[1].length + 2, 6); out.push(`<h${level}>${inline(head[2])}</h${level}>`); }
    else if (bullet || ordered) {
      flushParagraph();
      const kind = bullet ? 'ul' : 'ol';
      if (list !== kind) { closeList(); out.push(`<${kind}>`); list = kind; }
      out.push(`<li>${inline((bullet || ordered)[1])}</li>`);
    } else if (!line.trim()) { flushParagraph(); closeList(); }
    else { closeList(); paragraph.push(line.trim()); }
  }
  if (code) out.push(`<pre><code>${code.join('\n')}</code></pre>`);
  flushParagraph(); closeList();
  return out.join('');
}

/** Projects for one team, or for the viewer's teams, or everything. Newest activity first. */
export function visibleProjects(projects = [], { teamId = '', teams = [], viewer = '', scope = 'all' } = {}) {
  let list = projects;
  if (teamId) list = list.filter(p => p.team_id === teamId);
  else if (scope === 'mine' && viewer) {
    const mine = new Set(teams.filter(t => t.members?.includes(viewer)).map(t => t.id));
    list = list.filter(p => mine.has(p.team_id));
  }
  return [...list].sort((a, b) => (a.status === 'archived') - (b.status === 'archived') ||
    String(b.updated_at || '').localeCompare(String(a.updated_at || '')));
}

/** Read the API's `detail` (string or FastAPI validation list) into one line. */
export function errorDetail(body, status) {
  const detail = body?.detail;
  if (typeof detail === 'string' && detail.trim()) return detail;
  if (Array.isArray(detail) && detail.length) return detail.map(d => d?.msg || String(d)).join('; ');
  return status === 401 ? 'Sign in to continue.' : status === 403 ? 'You do not have access to change this.' :
    status === 404 ? 'Not found. It may have been removed.' : `Request failed (${status || 'network error'}).`;
}
