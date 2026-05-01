import { useEffect, useRef } from 'react';

/**
 * Phase 9 Session 4 — shared pol.is embed component.
 *
 * Renders the standard pol.is embed pattern:
 *
 *   <div class="polis"
 *        data-conversation_id="<id>"
 *        data-xid="<opaque>"></div>
 *   <script async src="https://pol.is/embed.js"></script>
 *
 * Script-loading approach: lazy-on-first-mount via a module-level boolean.
 * The pol.is embed script auto-discovers `<div class="polis">` nodes already
 * in the DOM and binds them on load; subsequent re-mounts (e.g. navigating
 * Polis -> proposals -> Polis again) trigger a fresh `MutationObserver`-style
 * scan which the script handles internally. Re-appending the script is a
 * no-op on the bound nodes but wastes a network request, so we gate it.
 *
 * If `conversationId` is null/empty (manual-fallback Polis pre-paste), we
 * render a friendly "Polis not yet connected" placeholder instead of the
 * embed div — there's nothing for embed.js to bind to and we don't want
 * to flash an empty iframe shell.
 *
 * Props:
 *   - conversationId: pol.is conversation slug (the short opaque token).
 *   - xid: opaque per-(user, org) pseudonym (Decision 4 identity bridge).
 *     Optional — embed.js will treat the user as anonymous when absent.
 *   - height: optional minHeight in px; defaults to 600.
 *
 * CSP note (logged in Session 1): no Content-Security-Policy is currently
 * set. If/when one is added, it must allow `script-src https://pol.is` and
 * `frame-src https://pol.is` for the embed to load.
 */

let scriptLoaded = false;

function ensureEmbedScript() {
  if (scriptLoaded) return;
  if (typeof document === 'undefined') return;
  // Guard against double-injection if a sibling component beat us to it.
  const existing = document.querySelector(
    'script[src="https://pol.is/embed.js"]'
  );
  if (existing) {
    scriptLoaded = true;
    return;
  }
  const s = document.createElement('script');
  s.async = true;
  s.src = 'https://pol.is/embed.js';
  document.body.appendChild(s);
  scriptLoaded = true;
}

export default function PolisEmbed({ conversationId, xid, height }) {
  const minHeight = height || 600;
  const containerRef = useRef(null);

  useEffect(() => {
    if (!conversationId) return;
    ensureEmbedScript();
  }, [conversationId]);

  if (!conversationId) {
    return (
      <div
        className="bg-white border border-dashed border-gray-300 rounded-xl flex items-center justify-center text-center text-sm text-gray-500 px-6"
        style={{ minHeight }}
      >
        <div className="space-y-1">
          <p className="font-medium text-gray-700">Polis not yet connected</p>
          <p className="text-xs text-gray-500 max-w-md">
            An admin needs to create the conversation on pol.is and paste its
            conversation_id here before participation can begin.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div ref={containerRef} className="w-full">
      <div
        className="polis"
        data-conversation_id={conversationId}
        data-xid={xid || ''}
        style={{ minHeight }}
      />
    </div>
  );
}
