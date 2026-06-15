import { optionLabelOf } from '../utils/optionDisplay';

/**
 * BudgetProjectResultsPanel — Phase 74 project-budget results.
 *
 * Shows the funded set in priority order (with the funded tier + a fallback
 * note when a cheaper tier was substituted), the stop point / group desired
 * total ("the group chose to spend ~$X of $Y"), the halt reason, and the
 * unfunded list (high-priority items that didn't fit are marked).
 */
function fmt(n, currency = 'USD') {
  try {
    return new Intl.NumberFormat(undefined, {
      style: 'currency', currency, maximumFractionDigits: 0,
    }).format(n || 0);
  } catch {
    return `$${Math.round(n || 0).toLocaleString()}`;
  }
}

const HALT_COPY = {
  stop_point: 'Stopped at the group’s chosen spend level.',
  item_did_not_fit: 'Stopped — the next-priority item didn’t fit the budget.',
  queue_exhausted: 'Funded everything that cleared priority and fit.',
};

export default function BudgetProjectResultsPanel({ tally, proposal }) {
  if (!tally || tally.voting_method !== 'budget_project') return null;
  const currency = tally.budget_currency || 'USD';
  const labels = tally.option_labels || {};
  const labelOf = optionLabelOf(proposal, labels);
  const funded = tally.project_funded || [];
  const unfunded = tally.project_unfunded || [];
  // Tier children carry budget_tier_parent_id; build a parent->children map so
  // we can detect a fallback (funded tier != the cheapest/only expectation).
  const tierLabel = (tierId) => (tierId ? labels[tierId] || tierId : null);

  return (
    <div className="space-y-3">
      <h3 className="text-sm font-semibold text-gray-700 uppercase tracking-wide">Project Budget</h3>

      <p className="text-sm text-gray-600">
        The group chose to spend{' '}
        <strong>{fmt(tally.project_total_committed, currency)}</strong>{' '}
        of {fmt(tally.budget_envelope, currency)} available
        {tally.project_group_desired_total != null && (
          <span className="text-gray-400"> (target ~{fmt(tally.project_group_desired_total, currency)})</span>
        )}.
      </p>

      {funded.length > 0 ? (
        <div>
          <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-1">Funded (priority order)</p>
          <ul className="space-y-1">
            {funded.map((f, i) => (
              <li key={f.option_id} className="flex justify-between gap-3 text-sm">
                <span className="text-gray-700 truncate">
                  <span className="text-gray-400 mr-1">{i + 1}.</span>
                  {labelOf(f.option_id)}
                  {f.tier_id && (
                    <span className="text-xs text-[var(--brand-accent)] ml-1">— {tierLabel(f.tier_id)}</span>
                  )}
                </span>
                <span className="font-medium text-gray-800 tabular-nums">{fmt(f.amount, currency)}</span>
              </li>
            ))}
          </ul>
        </div>
      ) : (
        <p className="text-sm text-gray-500 bg-gray-50 border border-gray-200 rounded-lg px-3 py-2">
          The group chose to fund nothing.
        </p>
      )}

      {unfunded.length > 0 && (
        <div>
          <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-1">Not funded</p>
          <ul className="text-xs text-gray-500 space-y-0.5">
            {unfunded.map((oid) => (
              <li key={oid} className="truncate">
                {labelOf(oid)}
                {tally.project_halt_reason === 'item_did_not_fit' && unfunded[0] === oid && (
                  <span className="text-amber-700"> — ranked high but didn’t fit</span>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className="text-xs text-gray-400 pt-1 border-t border-gray-100">
        {HALT_COPY[tally.project_halt_reason] || ''}{' '}
        {tally.total_ballots_cast || 0} ballot(s).
      </div>
    </div>
  );
}
