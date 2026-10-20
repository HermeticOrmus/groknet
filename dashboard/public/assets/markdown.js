/**
 * Rich markdown for artifacts: marked + DOMPurify, Mermaid for ```mermaid fences.
 * Libraries load lazily from the CDN on first use, so the rest of the Workroom
 * never depends on it. If they cannot load, the escape-first renderer from
 * projects.js is used instead, with a short note.
 */
import { escapeHtml, safeUrl, renderMarkdown } from './projects.js?v=20261020c';

export const CDN = {
  marked: 'https://cdn.jsdelivr.net/npm/marked@18.0.14/lib/marked.esm.js',
  purify: 'https://cdn.jsdelivr.net/npm/dompurify@3.4.16/dist/purify.es.mjs',
  mermaid: 'https://cdn.jsdelivr.net/npm/mermaid@11.17.2/dist/mermaid.esm.min.mjs',
};

/** The fence info string's first word is `mermaid` (any case). */
export function isMermaidFence(info) {
  return String(info ?? '').trim().split(/\s+/)[0].toLowerCase() === 'mermaid';
}

/** Links and images: absolute http(s) only. Relative, javascript:, data:, mailto: are dropped. */
export const linkUrl = href => safeUrl(href);
export const imageUrl = src => safeUrl(src);

export const FALLBACK_NOTE = 'Rich preview unavailable. Showing basic formatting.';

export function fallbackHtml(source) {
  return `<p class="markdown-note">${FALLBACK_NOTE}</p>${renderMarkdown(source)}`;
}

const PURIFY_CONFIG = {
  ALLOWED_TAGS: ['h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'p', 'br', 'hr', 'strong', 'em', 'del', 's', 'code', 'pre',
    'blockquote', 'ul', 'ol', 'li', 'input', 'table', 'thead', 'tbody', 'tr', 'th', 'td', 'a', 'img', 'span'],
  ALLOWED_ATTR: ['href', 'title', 'alt', 'src', 'rel', 'target', 'class', 'type', 'checked', 'disabled', 'align',
    'start', 'loading', 'referrerpolicy'],
  ALLOWED_URI_REGEXP: /^https?:\/\//i,
  ALLOW_DATA_ATTR: false,
  ALLOW_ARIA_ATTR: false,
};

const defaultImporter = url => import(url);
let libsPromise = null;
let mermaidPromise = null;

/** marked + DOMPurify, configured once. Resolves to null when the CDN import fails. */
export function loadLibraries(importer = defaultImporter) {
  libsPromise ||= Promise.all([importer(CDN.marked), importer(CDN.purify)]).then(([markedModule, purifyModule]) => {
    const purify = purifyModule.default;
    purify.addHook('afterSanitizeAttributes', node => {
      if (node.tagName === 'A') {
        const href = linkUrl(node.getAttribute('href'));
        if (href) { node.setAttribute('rel', 'noopener noreferrer'); node.setAttribute('target', '_blank'); }
        else { node.removeAttribute('href'); node.removeAttribute('target'); }
      }
      if (node.tagName === 'IMG' && !imageUrl(node.getAttribute('src'))) node.remove();
      if (node.tagName === 'INPUT') {
        if (node.getAttribute('type') !== 'checkbox') node.remove();
        else node.setAttribute('disabled', '');
      }
    });
    const marked = new markedModule.Marked({ gfm: true, breaks: false, async: false, renderer: markedRenderer() });
    return { marked, purify };
  }).catch(() => null);
  return libsPromise;
}

function markedRenderer() {
  return {
    // No raw HTML passthrough: block and inline HTML render as text.
    html({ text }) { return escapeHtml(text); },
    // Artifacts sit under the page h1 and section h2, so shift headings down two levels.
    heading({ tokens, depth }) {
      const level = Math.min(depth + 2, 6);
      return `<h${level}>${this.parser.parseInline(tokens)}</h${level}>\n`;
    },
    link({ href, title, tokens }) {
      const text = this.parser.parseInline(tokens);
      const url = linkUrl(href);
      if (!url) return text;
      return `<a href="${escapeHtml(url)}"${title ? ` title="${escapeHtml(title)}"` : ''} rel="noopener noreferrer" target="_blank">${text}</a>`;
    },
    image({ href, title, text }) {
      const url = imageUrl(href);
      if (!url) return escapeHtml(text);
      return `<img src="${escapeHtml(url)}" alt="${escapeHtml(text)}"${title ? ` title="${escapeHtml(title)}"` : ''} loading="lazy" referrerpolicy="no-referrer">`;
    },
    code({ text, lang }) {
      if (isMermaidFence(lang)) return `<pre class="mermaid-pending"><code>${escapeHtml(text)}</code></pre>\n`;
      return false; // marked's default (escaped) code block
    },
  };
}

function loadMermaid(importer) {
  mermaidPromise ||= importer(CDN.mermaid).then(m => m.default).catch(error => { mermaidPromise = null; throw error; });
  return mermaidPromise;
}

let diagramCount = 0;
let diagramQueue = Promise.resolve();

/** Replace each pending mermaid block in `root` with an SVG, or with its source and the parser's message. */
async function renderDiagrams(root, theme, importer) {
  const blocks = [...root.querySelectorAll('pre.mermaid-pending')];
  if (!blocks.length) return;
  let mermaid;
  try { mermaid = await loadMermaid(importer); } catch {
    for (const pre of blocks) {
      pre.classList.remove('mermaid-pending');
      pre.insertAdjacentHTML('beforebegin', '<p class="markdown-note">Diagram preview unavailable. Showing the source.</p>');
    }
    return;
  }
  // Mermaid's config is global; run one render at a time so themes never mix.
  const run = diagramQueue.then(async () => {
    mermaid.initialize({ startOnLoad: false, securityLevel: 'strict', theme: theme === 'dark' ? 'dark' : 'default',
      fontFamily: 'inherit' });
    for (const pre of blocks) {
      const source = pre.textContent;
      const id = `groknet-mermaid-${++diagramCount}`;
      const box = document.createElement('div');
      try {
        await mermaid.parse(source);
        const { svg } = await mermaid.render(id, source);
        box.className = 'mermaid-diagram';
        box.innerHTML = svg; // securityLevel 'strict' sanitizes the diagram's labels
        const el = box.querySelector('svg');
        el?.removeAttribute('height');
        el?.setAttribute('role', 'img');
      } catch (error) {
        box.className = 'mermaid-error';
        const message = String(error?.message || error || 'Unknown error').trim();
        box.innerHTML = `<p class="markdown-note">Diagram could not be rendered.</p><pre class="mermaid-message">${escapeHtml(message)}</pre><pre><code>${escapeHtml(source)}</code></pre>`;
      } finally {
        // A failed render can leave its scratch nodes in <body>.
        document.getElementById(`d${id}`)?.remove();
        document.getElementById(id)?.remove();
      }
      pre.replaceWith(box);
    }
  });
  diagramQueue = run.catch(() => {});
  await run;
}

const cache = new Map();
const CACHE_LIMIT = 40;

async function toHtml(source, theme, importer) {
  const libs = await loadLibraries(importer);
  if (!libs) return fallbackHtml(source);
  let clean;
  try {
    clean = libs.purify.sanitize(libs.marked.parse(String(source ?? '')), PURIFY_CONFIG);
  } catch {
    return fallbackHtml(source);
  }
  const root = document.createElement('div');
  root.innerHTML = clean;
  await renderDiagrams(root, theme, importer);
  return root.innerHTML;
}

/**
 * Render `source` into `element`. Results are cached per (theme, source), so a
 * Workroom re-render fills the element synchronously and diagrams do not
 * re-run. The element keeps its current content until the new HTML is ready.
 */
export function renderMarkdownInto(element, source, { theme = 'dark', importer = defaultImporter } = {}) {
  const key = `${theme}\u0000${source}`;
  let entry = cache.get(key);
  if (typeof entry === 'string') { element.innerHTML = entry; return Promise.resolve(); }
  if (!entry) {
    entry = toHtml(source, theme, importer).catch(() => fallbackHtml(source)).then(html => {
      cache.delete(key);
      cache.set(key, html);
      while (cache.size > CACHE_LIMIT) cache.delete(cache.keys().next().value);
      return html;
    });
    cache.set(key, entry);
  }
  return entry.then(html => { if (element.isConnected !== false) element.innerHTML = html; });
}
