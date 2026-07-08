/**
 * CountModeBadge — Phase 90c.
 *
 * Renders a prominent "One member, one vote" chip on a proposal whose author
 * chose `count_mode === 'one_per_member'`, so that in a weighted org a proposal
 * that deliberately counts by headcount announces it everywhere the proposal
 * appears (cards + detail). Mirror of VotingModelBadge's language, inverted:
 * VotingModelBadge says "this org weights votes"; this says "this ONE proposal
 * does not." Anything else renders nothing (the org-level badge already tells
 * the weighted story, and unweighted orgs need no per-proposal marker).
 */
export default function CountModeBadge({ countMode, className = '' }) {
  if (countMode !== 'one_per_member') return null;
  return (
    <span
      title="Votes on this proposal count one per member — member shares do not apply here."
      className={`inline-flex items-center gap-1 text-xs font-medium px-2 py-0.5 rounded-full bg-emerald-50 text-emerald-700 border border-emerald-200 ${className}`}
    >
      <svg width="11" height="11" viewBox="0 0 20 20" fill="currentColor" aria-hidden="true">
        <path d="M10 2a4 4 0 1 1 0 8 4 4 0 0 1 0-8zm-6 15a6 6 0 0 1 12 0 1 1 0 0 1-1 1H5a1 1 0 0 1-1-1z" />
      </svg>
      One member, one vote
    </span>
  );
}
