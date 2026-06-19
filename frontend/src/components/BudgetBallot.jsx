import { useState, useMemo } from 'react';
import api from '../api';
import { useToast } from './Toast';
import { optionDisplayLabel } from '../utils/optionDisplay';
import { formatBudget as fmt, unitInputSymbol } from '../utils/budgetFormat';

/**
 * BudgetBallot — Phase 73 allocation-budget ballot.
 *
 * Voters distribute a fixed envelope across continuously-fundable buckets.
 * A live "remaining" readout tracks the unspent envelope; the submit button is
 * blocked while the total exceeds the envelope or any bucket exceeds its
 * ceiling. Under-allocation is allowed (the unspent remainder is explicit).
 * Budget proposals are direct-vote only, so there's no delegate path here.
 */

export default function BudgetBallot({ proposal, myVote, proposalId, onVoteChange, emailVerified }) {
  const toast = useToast();
  const cfg = proposal.budget_config || {};
  const envelope = Number(cfg.envelope || 0);
  const currency = cfg.currency || 'USD';
  const inputSymbol = unitInputSymbol(currency);
  const options = useMemo(() => proposal.options || [], [proposal.options]);

  const [showBallot, setShowBallot] = useState(false);
  const [amounts, setAmounts] = useState({});
  const [casting, setCasting] = useState(false);
  const [err, setErr] = useState('');

  const unverified = !emailVerified;
  const hasVote = myVote?.allocations != null;

  function startBallot() {
    const initial = {};
    options.forEach((o) => {
      const v = myVote?.allocations?.[o.id];
      initial[o.id] = v != null ? String(v) : '';
    });
    setAmounts(initial);
    setShowBallot(true);
    setErr('');
  }

  const total = useMemo(
    () => Object.values(amounts).reduce((s, v) => s + (Number(v) || 0), 0),
    [amounts],
  );
  const remaining = envelope - total;

  const overCeiling = options.filter((o) => {
    const cap = o.budget_max_amount != null ? Number(o.budget_max_amount) : envelope;
    return (Number(amounts[o.id]) || 0) > cap + 1e-9;
  });
  const overEnvelope = total > envelope + 1e-9;
  const blocked = overEnvelope || overCeiling.length > 0;

  async function submitBallot() {
    setCasting(true);
    setErr('');
    const allocations = {};
    options.forEach((o) => {
      const v = Number(amounts[o.id]) || 0;
      if (v > 0) allocations[o.id] = v;
    });
    try {
      await api.post(`/api/proposals/${proposalId}/vote`, { allocations });
      toast.success('Budget allocation submitted');
      setShowBallot(false);
      onVoteChange();
    } catch (e) {
      setErr(e.message || 'Failed to submit allocation');
    } finally {
      setCasting(false);
    }
  }

  // Already-cast summary
  if (hasVote && !showBallot) {
    return (
      <div className="bg-gray-50 border border-gray-200 rounded-xl p-4 space-y-3">
        <h3 className="text-sm font-semibold text-gray-700 uppercase tracking-wide">Your Allocation</h3>
        {unverified && (
          <p className="text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded-lg px-3 py-2">
            Verify your email to vote.
          </p>
        )}
        <ul className="text-sm text-gray-700 space-y-1">
          {options.map((o) => (
            <li key={o.id} className="flex justify-between gap-3">
              <span className="truncate">{optionDisplayLabel(proposal, o)}</span>
              <span className="font-medium tabular-nums">{fmt(myVote.allocations[o.id] || 0, currency)}</span>
            </li>
          ))}
        </ul>
        <p className="text-xs text-gray-500">Budget proposals are direct-vote only.</p>
        <button
          onClick={startBallot}
          disabled={unverified}
          className="text-xs px-3 py-1.5 border border-[var(--brand-accent)] text-[var(--brand-accent)] rounded-lg hover:bg-[var(--brand-accent)] hover:text-white transition-colors disabled:opacity-50"
        >
          Change Allocation
        </button>
        {err && <p className="text-xs text-red-600">{err}</p>}
      </div>
    );
  }

  if (!hasVote && !showBallot) {
    return (
      <div className="bg-gray-50 border border-gray-200 rounded-xl p-4 space-y-3">
        <h3 className="text-sm font-semibold text-gray-700 uppercase tracking-wide">Your Allocation</h3>
        {unverified && (
          <p className="text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded-lg px-3 py-2">
            Verify your email to vote.
          </p>
        )}
        <p className="text-sm text-gray-500">
          Distribute the {fmt(envelope, currency)} budget across the buckets below.
          Budget proposals are direct-vote only.
        </p>
        <button
          onClick={startBallot}
          disabled={unverified}
          className="text-sm px-3 py-1.5 bg-[var(--brand-primary)] text-white rounded-lg hover:bg-[var(--brand-accent)] transition-colors disabled:opacity-50"
        >
          Allocate Budget
        </button>
      </div>
    );
  }

  return (
    <div className="bg-gray-50 border border-gray-200 rounded-xl p-4 space-y-3">
      <h3 className="text-sm font-semibold text-gray-700 uppercase tracking-wide">Your Allocation</h3>
      {unverified && (
        <p className="text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded-lg px-3 py-2">
          Verify your email to vote.
        </p>
      )}
      <p className="text-xs text-gray-500">
        Distribute up to {fmt(envelope, currency)} across the buckets. You can
        leave some unallocated.
      </p>

      <div className="space-y-2">
        {options.map((o) => {
          const cap = o.budget_max_amount != null ? Number(o.budget_max_amount) : null;
          const over = (Number(amounts[o.id]) || 0) > (cap ?? envelope) + 1e-9;
          return (
            <div key={o.id} className="bg-white border border-gray-200 rounded-lg px-3 py-2">
              <div className="flex items-center justify-between gap-2">
                <span className="text-sm font-medium text-gray-800 leading-snug">{optionDisplayLabel(proposal, o)}</span>
                <div className="flex items-center gap-1 shrink-0">
                  {inputSymbol && <span className="text-gray-400 text-sm">{inputSymbol}</span>}
                  <input
                    type="number"
                    min="0"
                    step="1"
                    value={amounts[o.id] ?? ''}
                    onChange={(e) => setAmounts((p) => ({ ...p, [o.id]: e.target.value }))}
                    disabled={unverified}
                    className={`w-28 text-sm text-right border rounded px-2 py-1 tabular-nums ${
                      over ? 'border-red-400 bg-red-50' : 'border-gray-300'
                    }`}
                  />
                </div>
              </div>
              {!proposal.is_election && o.description && (
                <p className="text-xs text-gray-500 mt-0.5 line-clamp-2">{o.description}</p>
              )}
              {cap != null && (
                <p className={`text-[11px] mt-0.5 ${over ? 'text-red-600' : 'text-gray-400'}`}>
                  Ceiling: {fmt(cap, currency)}
                </p>
              )}
            </div>
          );
        })}
      </div>

      <div className={`text-sm font-medium ${remaining < 0 ? 'text-red-600' : 'text-gray-700'}`}>
        Remaining: {fmt(remaining, currency)} of {fmt(envelope, currency)}
      </div>
      {overEnvelope && (
        <p className="text-xs text-red-600">Total exceeds the budget envelope.</p>
      )}
      {overCeiling.length > 0 && (
        <p className="text-xs text-red-600">One or more buckets exceed their ceiling.</p>
      )}

      <div className="flex gap-2 pt-1">
        <button
          onClick={submitBallot}
          disabled={casting || unverified || blocked}
          className="text-sm px-4 py-2 bg-[var(--brand-primary)] text-white rounded-lg hover:bg-[var(--brand-accent)] transition-colors disabled:opacity-50"
        >
          {casting ? 'Submitting...' : 'Submit Allocation'}
        </button>
        <button onClick={() => setShowBallot(false)} className="text-xs text-gray-400 hover:text-gray-600 px-2">
          Cancel
        </button>
      </div>
      {err && <p className="text-xs text-red-600">{err}</p>}
    </div>
  );
}
