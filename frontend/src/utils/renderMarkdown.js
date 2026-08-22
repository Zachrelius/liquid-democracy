/**
 * Phase 10 W2 — shared inline markdown renderer.
 *
 * Lifted byte-for-byte from the inline helper that used to live in
 * ``ProposalDetail.jsx``. Now used by both proposal bodies and the
 * Phase 10 W3 comment thread so the two surfaces stay visually
 * identical and we don't drift one renderer ahead of the other.
 *
 * Strategy: escape-then-substitute. The input is first run through a
 * minimal HTML escape (``& < >``) so no caller-supplied HTML can leak
 * into the rendered output. The result is then walked with a small
 * series of regex substitutions to convert a deliberately tiny subset
 * of markdown to HTML:
 *
 *   - ``# h1`` / ``## h2`` / ``### h3`` (line-anchored)
 *   - ``**bold**`` and ``*italic*``
 *   - inline `` `code` ``
 *   - explicit ``[label](https://example.test)`` links for absolute
 *     HTTP(S) destinations only (still no raw-URL autolinking)
 *   - ``- item`` / ``* item`` bullet list (the first run gets wrapped
 *     in a single ``<ul>``)
 *   - paragraph breaks on blank lines
 *
 * We deliberately avoid pulling in a markdown library (``react-markdown``,
 * ``marked``, ``markdown-it``) for two reasons:
 *
 *   1. Bundle size. The whole renderer is < 1 kB; the smallest serious
 *      markdown library is ~30 kB minified. For the supported syntax
 *      (proposal bodies + comments) the extra surface area is not worth
 *      the cost.
 *
 *   2. Explicitness. The supported syntax IS the regex list below — there
 *      are no surprise extensions, no raw-URL auto-detection, no HTML
 *      passthrough. Explicit Markdown links are scheme-validated before
 *      anchor emission. The server-side
 *      sanitizer (``backend/schemas.py:_sanitize_markdown``) uses ``nh3``
 *      with a matching allowlist, so the two layers stay in sync.
 *
 * If the supported syntax ever needs to expand meaningfully (tables,
 * footnotes, images, link cards, etc.) revisit the library decision; the
 * call sites all use ``dangerouslySetInnerHTML`` so swapping the renderer
 * is a one-shot replacement.
 *
 * @param {string} text — raw markdown source (already trusted for
 *   sanitization purposes; the server's ``_sanitize_markdown`` runs
 *   before persistence and the escape-first step here is defense in
 *   depth against any client-only render paths).
 * @returns {string} rendered HTML safe to drop into
 *   ``dangerouslySetInnerHTML``.
 */
export function safeMarkdownLinkDestination(rawDestination) {
  const hasControlOrSpace = [...(rawDestination || '')].some(character => {
    const code = character.charCodeAt(0);
    return code <= 32 || code === 127;
  });
  if (!rawDestination || hasControlOrSpace || /["'<>\\]/.test(rawDestination)) {
    return null;
  }
  try {
    const parsed = new URL(rawDestination);
    if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') return null;
    // Requiring the serialized URL to begin with an explicit supported
    // scheme rejects relative and protocol-relative destinations.
    if (!/^https?:\/\//i.test(rawDestination)) return null;
    return parsed.href;
  } catch {
    return null;
  }
}

function escapeHtml(text) {
  return text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');
}

function escapeAttribute(text) {
  return escapeHtml(text)
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function tokenizeSafeLinks(text) {
  const anchors = [];
  const tokenized = text.replace(
    /\[([^\]\r\n]+)\]\(([^()\s]+)\)/g,
    (match, label, destination) => {
      const safeDestination = safeMarkdownLinkDestination(destination);
      if (!safeDestination) return match;
      const token = `\u0001LDLINK${anchors.length}\u0002`;
      anchors.push(
        `<a href="${escapeAttribute(safeDestination)}" target="_blank" rel="noopener noreferrer">${escapeHtml(label)}</a>`,
      );
      return token;
    },
  );
  return { tokenized, anchors };
}

export default function renderMarkdown(text) {
  if (!text) return '';
  const { tokenized, anchors } = tokenizeSafeLinks(text);
  let rendered = escapeHtml(tokenized)
    .replace(/^### (.+)$/gm, '<h3>$1</h3>')
    .replace(/^## (.+)$/gm, '<h2>$1</h2>')
    .replace(/^# (.+)$/gm, '<h1>$1</h1>')
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/\*(.+?)\*/g, '<em>$1</em>')
    .replace(/`(.+?)`/g, '<code>$1</code>')
    .replace(/^[-*] (.+)$/gm, '<li>$1</li>')
    .replace(/(<li>.*<\/li>)/s, '<ul>$1</ul>')
    .replace(/\n\n/g, '</p><p>')
    .replace(/^(?!<[hul])(.+)$/gm, (m) => m.startsWith('<') ? m : m);
  anchors.forEach((anchor, index) => {
    rendered = rendered.replace(`\u0001LDLINK${index}\u0002`, anchor);
  });
  return rendered;
}
