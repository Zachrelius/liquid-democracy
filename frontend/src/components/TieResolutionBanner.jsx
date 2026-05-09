import { useState } from 'react';

/**
 * TieResolutionBanner — Phase 17 F2.
 *
 * Renders an info banner above the winner display on results panels when
 * a proposal's tie was auto-resolved by the org's configured method. Reads
 * the audit record persisted to `Proposal.tie_resolution` (B4):
 *
 *   {
 *     method: 'broader_approval_base' | 'expand_winners'
 *           | 'earliest_decisive_vote' | 'random_seed',
 *     input_winners: [option_id, ...],   // tied set as input
 *     chosen_winners: [option_id, ...],  // post-resolution winner(s)
 *     seed: '<hex>' | null,              // populated only for random_seed
 *     metadata: { ... } | null,          // method-specific extras
 *     applied_at: '<iso8601>',
 *   }
 *
 * `labelOf(option_id) -> string` is passed in by the parent panel so we
 * can map raw option IDs to human-readable labels (the panels already
 * have this lookup; we don't duplicate it here).
 *
 * Pre-Phase-17 closed proposals can carry the older shape
 * `{selected_option_id, resolved_at}` (the manual admin-resolves flow).
 * Per spec D7 we don't backfill; we render a minimal compatibility banner
 * for those rather than crashing.
 */
export default function TieResolutionBanner({ tieResolution, labelOf }) {
  const [showSeed, setShowSeed] = useState(false);

  if (!tieResolution) return null;

  // Legacy admin-resolves shape — Phase 6 / 12.5 era data.
  if (tieResolution.selected_option_id && !tieResolution.method) {
    return (
      <div className="bg-blue-50 border border-blue-200 rounded-lg p-3">
        <p className="text-sm text-blue-800">
          <span className="mr-1" aria-hidden="true">ℹ️</span>
          This proposal had a tie. Resolved by an admin selecting{' '}
          <strong>{labelOf(tieResolution.selected_option_id)}</strong>
          {tieResolution.resolved_at && (
            <span className="text-xs text-blue-600 ml-1">
              on {new Date(tieResolution.resolved_at).toLocaleDateString()}
            </span>
          )}
          .
        </p>
      </div>
    );
  }

  const method = tieResolution.method;
  const inputWinners = Array.isArray(tieResolution.input_winners)
    ? tieResolution.input_winners
    : [];
  const chosenWinners = Array.isArray(tieResolution.chosen_winners)
    ? tieResolution.chosen_winners
    : [];

  const methodLabel = METHOD_LABELS[method] || method || 'an automatic method';
  const explanation = METHOD_EXPLANATIONS[method] || null;

  return (
    <div className="bg-blue-50 border border-blue-200 rounded-lg p-3 space-y-1">
      <p className="text-sm text-blue-800">
        <span className="mr-1" aria-hidden="true">ℹ️</span>
        This proposal had a tie. Resolved via <strong>{methodLabel}</strong>.
      </p>
      {explanation && (
        <p className="text-xs text-blue-700">{explanation}</p>
      )}

      {/* random_seed: a "Show seed" expansion lets curious users verify
          the result by recomputing sha256(proposal_id + ':' + voting_end_iso)
          themselves. The math hint is in a tooltip per spec line 389. */}
      {method === 'random_seed' && tieResolution.seed && (
        <div className="pt-1">
          <button
            type="button"
            onClick={() => setShowSeed(s => !s)}
            className="text-xs text-blue-700 underline hover:text-blue-900"
            title="sha256(proposal_id + ':' + voting_end_iso) seeds Python's random.Random; mod 2^32 then random.choice on sorted(input_winners)."
          >
            {showSeed ? 'Hide seed' : 'Show seed'}
          </button>
          {showSeed && (
            <div className="mt-1 text-xs text-blue-700 bg-white/60 border border-blue-100 rounded p-2 space-y-1 font-mono">
              <div>
                <span className="text-blue-500">seed:</span>{' '}
                <span className="break-all">{tieResolution.seed}</span>
              </div>
              {inputWinners.length > 0 && chosenWinners.length > 0 && (
                <div>
                  <span className="text-blue-500">tied:</span>{' '}
                  {inputWinners.map(labelOf).join(', ')}{' '}
                  <span className="text-blue-500">→ chosen:</span>{' '}
                  {chosenWinners.map(labelOf).join(', ')}
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {/* expand_winners: surface the resolved set explicitly so readers
          see this proposal genuinely seated multiple winners by design. */}
      {method === 'expand_winners' && chosenWinners.length > 1 && (
        <p className="text-xs text-blue-700">
          Seated {chosenWinners.length} winners:{' '}
          {chosenWinners.map(labelOf).join(', ')}.
        </p>
      )}
    </div>
  );
}

const METHOD_LABELS = {
  broader_approval_base: 'broader approval base',
  expand_winners: 'expand winners',
  earliest_decisive_vote: 'earliest decisive vote',
  random_seed: 'random with seed',
};

const METHOD_EXPLANATIONS = {
  broader_approval_base:
    'The tied option co-approved alongside the most other options wins.',
  expand_winners:
    'All tied options are seated as winners.',
  earliest_decisive_vote:
    'The tied option whose support reached its final count earliest wins.',
  random_seed:
    'A deterministic random selection using the proposal ID and end time. Anyone can verify the result by recomputing the hash.',
};
