import test from 'node:test';
import assert from 'node:assert/strict';
import { isMermaidFence, linkUrl, imageUrl, fallbackHtml, loadLibraries, renderMarkdownInto, FALLBACK_NOTE, CDN }
  from '../public/assets/markdown.js';

test('mermaid fences are detected by the first word of the info string', () => {
  for (const info of ['mermaid', 'Mermaid', '  mermaid  ', 'mermaid {"theme":"dark"}']) assert.equal(isMermaidFence(info), true, info);
  for (const info of ['', undefined, null, 'js', 'mermaidjs', 'not-mermaid', 'text mermaid']) assert.equal(isMermaidFence(info), false, String(info));
});

test('links and images accept absolute http(s) URLs only', () => {
  for (const check of [linkUrl, imageUrl]) {
    assert.equal(check('https://example.com/a?b=1'), 'https://example.com/a?b=1');
    assert.equal(check('HTTP://example.com'), 'HTTP://example.com');
    for (const bad of ['javascript:alert(1)', 'JaVaScRiPt:alert(1)', 'data:image/png;base64,AAAA', 'mailto:a@b.c',
      '/relative', '#anchor', '//evil.example', 'vbscript:x', '', undefined, 'https://a.io/x y']) {
      assert.equal(check(bad), '', String(bad));
    }
  }
});

test('CDN imports are pinned to exact versions', () => {
  for (const url of Object.values(CDN)) assert.match(url, /^https:\/\/cdn\.jsdelivr\.net\/npm\/[a-z]+@\d+\.\d+\.\d+\//);
});

test('fallback HTML carries the note and keeps raw HTML as text', () => {
  const html = fallbackHtml('# Title\n<img src=x onerror=alert(1)>');
  assert.ok(html.startsWith(`<p class="markdown-note">${FALLBACK_NOTE}</p>`));
  assert.ok(html.includes('&lt;img src=x onerror=alert(1)&gt;'));
  assert.ok(!html.includes('<img'));
});

test('a failed CDN import renders the escape-first fallback into the element', async () => {
  const offline = () => Promise.reject(new TypeError('Failed to fetch dynamically imported module'));
  assert.equal(await loadLibraries(offline), null);
  const element = { innerHTML: 'Rendering…' };
  await renderMarkdownInto(element, '**bold** <script>alert(1)</script>', { theme: 'light', importer: offline });
  assert.ok(element.innerHTML.includes(FALLBACK_NOTE));
  assert.ok(element.innerHTML.includes('<strong>bold</strong>'));
  assert.ok(element.innerHTML.includes('&lt;script&gt;'));
  // Cached: a second render fills synchronously.
  const again = { innerHTML: '' };
  const pending = renderMarkdownInto(again, '**bold** <script>alert(1)</script>', { theme: 'light', importer: offline });
  assert.ok(again.innerHTML.includes(FALLBACK_NOTE));
  await pending;
});
