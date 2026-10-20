import test from 'node:test';
import assert from 'node:assert/strict';
import { resolveTheme, groupIssues, issueCountSummary, statusMoves, issuePatch, safeUrl,
  renderMarkdown, visibleProjects, errorDetail, issueFormModel, mentionChoices, issueSubmission } from '../public/assets/projects.js';

test('theme: stored toggle choice wins, dark otherwise', () => {
  assert.equal(resolveTheme('light'), 'light');
  assert.equal(resolveTheme('dark'), 'dark');
  assert.equal(resolveTheme(null), 'dark');
  assert.equal(resolveTheme('sepia'), 'dark');
});

test('issues group into the three status columns, oldest first, unknown statuses dropped', () => {
  const columns = groupIssues([
    { id: 'b', status: 'open', created_at: '2026-10-20T02:00:00Z' },
    { id: 'a', status: 'open', created_at: '2026-10-20T01:00:00Z' },
    { id: 'c', status: 'done', created_at: '2026-10-20T01:00:00Z' },
    { id: 'd', status: 'blocked' },
  ]);
  assert.deepEqual(Object.keys(columns), ['open', 'in_progress', 'done']);
  assert.deepEqual(columns.open.map(i => i.id), ['a', 'b']);
  assert.equal(columns.in_progress.length, 0);
  assert.deepEqual(columns.done.map(i => i.id), ['c']);
});

test('issue count summaries skip empty statuses and handle missing counts', () => {
  assert.deepEqual(issueCountSummary({ open: 2, in_progress: 0, done: 1 }),
    { total: 3, text: '2 open · 1 done' });
  assert.deepEqual(issueCountSummary(undefined), { total: 0, text: 'No issues yet' });
});

test('status moves never offer the current status', () => {
  for (const status of ['open', 'in_progress', 'done']) {
    assert.ok(statusMoves(status).every(([to]) => to !== status));
  }
  assert.deepEqual(statusMoves('nope'), []);
});

test('issue patch sends only changed fields; empty assignee clears with null', () => {
  const original = { title: 'Ship', description: '', status: 'open', assignee: 'juan', mentions: ['b', 'a'] };
  assert.deepEqual(issuePatch(original, { title: 'Ship', description: '', status: 'open', assignee: 'juan', mentions: ['a', 'b'] }), {});
  assert.deepEqual(issuePatch(original, { title: ' Ship it ', status: 'done', assignee: '', mentions: ['a'] }),
    { title: 'Ship it', status: 'done', assignee: null, mentions: ['a'] });
  assert.deepEqual(issuePatch({ ...original, assignee: null }, { assignee: 'tomas' }), { assignee: 'tomas' });
});

test('issue form model: blanks for create, the issue values for edit', () => {
  assert.deepEqual(issueFormModel(), { title: '', description: '', status: 'open', assignee: '', mentions: [] });
  assert.deepEqual(issueFormModel({ title: 'Ship', description: null, status: 'done', assignee: null, mentions: ['a', 'a', 'b'] }),
    { title: 'Ship', description: '', status: 'done', assignee: '', mentions: ['a', 'b'] });
  assert.equal(issueFormModel({ title: 'x', status: 'blocked' }).status, 'open');
});

test('mention choices skip the actor but keep anyone already mentioned', () => {
  assert.deepEqual(mentionChoices(['tomas', 'juan', 'ana'], 'tomas'), ['juan', 'ana']);
  assert.deepEqual(mentionChoices(['tomas', 'juan'], 'tomas', ['tomas', 'juan']), ['juan', 'tomas']);
  assert.deepEqual(mentionChoices(undefined, 'tomas'), []);
});

test('create submission sends only filled fields and sets a non-open status afterwards', () => {
  assert.deepEqual(issueSubmission({ title: ' Ship ', description: '  ', status: 'open', assignee: '', mentions: [] }),
    { body: { title: 'Ship' }, status: '' });
  assert.deepEqual(issueSubmission({ title: 'Ship', description: ' Notes ', status: 'in_progress', assignee: 'juan', mentions: ['ana', 'ana'] }),
    { body: { title: 'Ship', description: 'Notes', assignee: 'juan', mentions: ['ana'] }, status: 'in_progress' });
  assert.deepEqual(issueSubmission({ title: '   ' }), { error: 'Add a title.' });
});

test('edit submission is the issuePatch of changed fields, empty when unchanged', () => {
  const original = { title: 'Ship', description: 'd', status: 'open', assignee: 'juan', mentions: ['ana'] };
  assert.deepEqual(issueSubmission(issueFormModel(original), original), { patch: {} });
  assert.deepEqual(issueSubmission({ ...issueFormModel(original), title: 'Ship it', status: 'done', assignee: '' }, original),
    { patch: { title: 'Ship it', status: 'done', assignee: null } });
  assert.deepEqual(issueSubmission({ ...issueFormModel(original), title: '' }, original), { error: 'Add a title.' });
});

test('only http(s) URLs are linkable', () => {
  assert.equal(safeUrl(' https://example.com/a?b=1 '), 'https://example.com/a?b=1');
  assert.equal(safeUrl('javascript:alert(1)'), '');
  assert.equal(safeUrl('data:text/html,<b>'), '');
});

test('markdown escapes raw HTML before rendering', () => {
  const html = renderMarkdown('<script>alert(1)</script>\n<img src=x onerror=alert(1)>');
  assert.ok(!html.includes('<script'));
  assert.ok(!html.includes('<img'));
  assert.match(html, /&lt;script&gt;alert\(1\)&lt;\/script&gt;/);
});

test('markdown renders headings, bold, lists, code and safe links only', () => {
  const html = renderMarkdown('# Plan\n\nShip **today**.\n\n- one\n- `a**b**`\n\n1. first\n\n```\n<b>x</b>\n```\n[ok](https://x.io) [bad](javascript:alert(1))');
  assert.match(html, /<h3>Plan<\/h3>/);
  assert.match(html, /<strong>today<\/strong>/);
  assert.match(html, /<ul><li>one<\/li><li><code>a\*\*b\*\*<\/code><\/li><\/ul>/);
  assert.match(html, /<ol><li>first<\/li><\/ol>/);
  assert.match(html, /<pre><code>&lt;b&gt;x&lt;\/b&gt;<\/code><\/pre>/);
  assert.match(html, /<a href="https:\/\/x.io" rel="noopener noreferrer" target="_blank">ok<\/a>/);
  assert.ok(!/href="javascript/i.test(html));
});

test('markdown link text and URLs cannot break out of the attribute', () => {
  const html = renderMarkdown('[x](https://a.io/"onmouseover=alert(1))');
  assert.ok(!html.includes('"onmouseover'));
});

test('visible projects filter by team or viewer teams and list archived last', () => {
  const projects = [
    { id: '1', team_id: 't1', status: 'archived', updated_at: '2026-10-20T03:00:00Z' },
    { id: '2', team_id: 't1', status: 'active', updated_at: '2026-10-20T01:00:00Z' },
    { id: '3', team_id: 't2', status: 'active', updated_at: '2026-10-20T02:00:00Z' },
  ];
  const teams = [{ id: 't1', members: ['juan'] }, { id: 't2', members: ['tomas'] }];
  assert.deepEqual(visibleProjects(projects).map(p => p.id), ['3', '2', '1']);
  assert.deepEqual(visibleProjects(projects, { teamId: 't1' }).map(p => p.id), ['2', '1']);
  assert.deepEqual(visibleProjects(projects, { teams, viewer: 'tomas', scope: 'mine' }).map(p => p.id), ['3']);
});

test('error detail prefers the API text and summarises validation lists', () => {
  assert.equal(errorDetail({ detail: 'Only members can write.' }, 403), 'Only members can write.');
  assert.equal(errorDetail({ detail: [{ msg: 'field required' }] }, 422), 'field required');
  assert.equal(errorDetail(null, 401), 'Sign in to continue.');
});
