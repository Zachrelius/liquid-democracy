import { optionLabelOf } from '../utils/optionDisplay';
import { formatBudget as fmt } from '../utils/budgetFormat';

/**
 * BudgetResultsPanel — Phase 73 allocation-budget results.
 *
 * Renders the final per-bucket amounts as proportional bars summing to the
 * envelope, with the unallocated remainder surfaced (when bucket ceilings
 * force a shortfall) and a degenerate "the group chose to allocate nothing"
 * empty-state.
 */

export default function BudgetResultsPanel({ tally, proposal }) {
  if (!tally || tally.voting_method !== 'budget_allocation') return null;
  const currency = tally.budget_currency || 'USD';
  const envelope = Number(tally.budget_envelope || 0);
  const amounts = tally.budget_amounts || {};
  const labelOf = optionLabelOf(proposal, tally.option_labels || {});
  const remainder = Number(tally.budget_unallocated_remainder || 0);

  const rows = (proposal.options || [])
    .map((o) => ({ id: o.id, amount: Number(amounts[o.id] || 0) }))
    .sort((a, b) => b.amount - a.amount);
  const maxAmount = Math.max(1, ...rows.map((r) => r.amount));

  return (
    <div className="space-y-3">
      <h3 className="text-sm font-semibold text-gray-700 uppercase tracking-wide">Budget Allocation</h3>

      {tally.budget_degenerate_no_support ? (
        <p className="text-sm text-gray-500 bg-gray-50 border border-gray-200 rounded-lg px-3 py-2">
          The group chose to allocate nothing — every bucket received {fmt(0, currency)}.
        </p>
      ) : (
        <div className="space-y-2">
          {rows.map((r) => (
            <div key={r.id}>
              <div className="flex justify-between gap-3 text-sm mb-0.5">
                <span className="text-gray-700 truncate">{labelOf(r.id)}</span>
                <span className="font-medium text-gray-800 tabular-nums">{fmt(r.amount, currency)}</span>
              </div>
              <div className="h-2 bg-gray-100 rounded">
                <div
                  className="h-2 rounded bg-[var(--brand-accent)]"
                  style={{ width: `${(r.amount / maxAmount) * 100}%` }}
                />
              </div>
            </div>
          ))}
        </div>
      )}

      <div className="text-xs text-gray-500 space-y-0.5 pt-1 border-t border-gray-100">
        <div>Envelope: {fmt(envelope, currency)}</div>
        <div>Allocated: {fmt(Number(tally.budget_total_allocated || 0), currency)}</div>
        {remainder > 0 && (
          <div className="text-amber-700">
            Unallocated: {fmt(remainder, currency)} — bucket ceilings sum below the envelope.
          </div>
        )}
        <div>
          {tally.total_ballots_cast || 0} ballot(s) · {tally.budget_aggregation === 'trimmed_mean' ? 'trimmed mean' : 'median'} aggregation
        </div>
      </div>
    </div>
  );
}
