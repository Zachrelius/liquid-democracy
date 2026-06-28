import { Link } from 'react-router-dom';
import { polisTopicLabel } from '../utils/polis';

/**
 * Phase 9 Session 4 — Linked-Polis card for proposal-detail rendering.
 *
 * Renders a single linked Polis as a card that voters see in the
 * "Linked Deliberations" section of a proposal detail page. Distinct
 * enough from blockquotes / external links that voters notice the
 * platform-level linkage.
 *
 * Props:
 *   - polis: { id, title, prompt, status, participation_count } — also
 *     accepts the resolved-shape returned by `_build_linked_polises`
 *     (`{id, title, prompt, status, participation_count}`).
 *   - orgSlug: parent-org slug for routing — used to construct the
 *     /<slug>/polises/<id> link (Phase 11 D3 dropped the /orgs/ prefix).
 *   - missing: optional flag for the "Polis no longer available" state
 *     (URL-detected pol.is link that didn't resolve to any Polis the
 *     viewer can see).
 *   - originalUrl: when `missing` is true, the original pol.is URL is
 *     shown as plain text so the voter still sees the reference.
 *
 * Visual style mirrors the platform card aesthetic
 * (`bg-white border border-gray-200 rounded-xl p-4`).
 */
export default function LinkedPolisCard({
  polis,
  orgSlug,
  missing = false,
  originalUrl = null,
}) {
  // Missing/deleted-Polis state — the URL was detected in proposal body but
  // didn't resolve to a Polis visible to the viewer.
  if (missing) {
    return (
      <div className="bg-white border border-gray-200 rounded-xl p-4 space-y-1">
        <div className="flex items-center gap-2 mb-1">
          <span className="text-[10px] uppercase tracking-wide text-gray-400 font-semibold">
            Linked deliberation
          </span>
          <span className="text-[10px] uppercase px-1.5 py-0.5 rounded bg-gray-100 text-gray-500">
            Unavailable
          </span>
        </div>
        <p className="text-sm font-medium text-gray-700">
          Polis no longer available
        </p>
        {originalUrl && (
          <p className="text-xs text-gray-400 break-all">{originalUrl}</p>
        )}
      </div>
    );
  }

  if (!polis) return null;

  const status = polis.status || 'active';
  const isArchived = status === 'archived';
  const participation = polis.participation_count;
  const liveStatsUnavailable = polis.live_stats_unavailable === true;

  const truncatedPrompt = (() => {
    const p = (polis.prompt || '').trim();
    if (!p) return '';
    return p.length > 150 ? p.slice(0, 150).trimEnd() + '…' : p;
  })();

  const detailHref = orgSlug && polis.id
    ? `/${orgSlug}/polises/${polis.id}`
    : null;

  function formatParticipants() {
    if (liveStatsUnavailable) return '—';
    if (participation === null || participation === undefined) return '—';
    const n = Number(participation);
    if (!Number.isFinite(n)) return '—';
    return n.toLocaleString();
  }

  return (
    <div className="bg-white border border-gray-200 rounded-xl p-4 space-y-2">
      <div className="flex items-center gap-2 flex-wrap">
        <span className="text-[10px] uppercase tracking-wide text-[var(--brand-accent)] font-semibold">
          Linked deliberation
        </span>
        {isArchived ? (
          <span className="text-[10px] uppercase px-1.5 py-0.5 rounded bg-gray-200 text-gray-600">
            Archived — read-only
          </span>
        ) : (
          <span className="text-[10px] uppercase px-1.5 py-0.5 rounded bg-green-100 text-green-700">
            Active
          </span>
        )}
      </div>
      <h3 className="text-sm font-semibold text-[var(--brand-primary)] leading-snug">
        {polisTopicLabel(polis)}
      </h3>
      {truncatedPrompt && (
        <p className="text-xs text-gray-600 leading-relaxed">
          {truncatedPrompt}
        </p>
      )}
      <div className="flex items-center justify-between pt-1">
        <span className="text-xs text-gray-400">
          {formatParticipants()} participant{participation === 1 ? '' : 's'}
        </span>
        {detailHref && (
          <Link
            to={detailHref}
            className="text-xs px-3 py-1.5 bg-[var(--brand-primary)] text-white rounded-lg hover:bg-[var(--brand-accent)] transition-colors"
          >
            Open
          </Link>
        )}
      </div>
    </div>
  );
}
