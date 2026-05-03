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
 *      are no surprise extensions, no link auto-detection, no HTML
 *      passthrough. What you see is what gets rendered. The server-side
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
export default function renderMarkdown(text) {
  if (!text) return '';
  return text
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
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
}
