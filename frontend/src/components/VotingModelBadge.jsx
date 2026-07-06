/**
 * VotingModelBadge — Phase 88c transparency surface.
 *
 * Renders a persistent, non-dismissable badge declaring an org's voting model
 * whenever weighted voting is enabled, so a weighted org can never masquerade
 * as one-member-one-vote. Unweighted orgs render NOTHING here (absence = one
 * member, one vote); the affirmative "One member, one vote" line is shown only
 * on the public landing page, where a prospective joiner needs an explicit
 * declaration either way.
 *
 * `weightedVoting` is the {enabled, unit_label} object surfaced on every
 * org-shaped response (OrgOut, OrgPublicOut, ExploreOrgCard).
 */
export default function VotingModelBadge({ weightedVoting, className = '' }) {
  if (!weightedVoting?.enabled) return null;
  const unit = weightedVoting.unit_label || 'shares';
  return (
    <span
      title="This organization weights votes by member shares."
      className={`inline-flex items-center gap-1 text-xs font-medium px-2 py-0.5 rounded-full bg-indigo-50 text-indigo-700 border border-indigo-200 ${className}`}
    >
      <svg width="11" height="11" viewBox="0 0 20 20" fill="currentColor" aria-hidden="true">
        <path d="M10 2a1 1 0 0 1 .9.56l2 4 4.4.64a1 1 0 0 1 .55 1.7l-3.2 3.1.76 4.4a1 1 0 0 1-1.45 1.05L10 15.9l-3.96 2.1a1 1 0 0 1-1.45-1.05l.76-4.4-3.2-3.1a1 1 0 0 1 .55-1.7l4.4-.64 2-4A1 1 0 0 1 10 2z" opacity="0.35" />
      </svg>
      Weighted voting · {unit}
    </span>
  );
}
