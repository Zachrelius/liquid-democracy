import { useMemo } from 'react';
import TieResolutionBanner from './TieResolutionBanner';
// Phase 67 W3 — election proposals show candidate display names
// (option.description) instead of the raw user-id UUID labels.
import { optionDisplayLabel } from '../utils/optionDisplay';

/**
 * RCVResultsPanel — round-by-round breakdown for ranked-choice (IRV / STV) results.
 *
 * Per spec, this is deliberately functional/text-table style. Phase 7B will
 * replace the round breakdown with a Sankey visualization.
 *
 * Expected tally shape (from GET /api/proposals/{id}/results):
 *   {
 *     rounds: [{ round_number, option_counts, eliminated, elected, transferred_from, transfer_breakdown }],
 *     winners: [option_id, ...],
 *     total_ballots_cast, total_abstain, not_cast, total_eligible,
 *     tied: bool, method: 'irv' | 'stv', num_winners,
 *     options: [{id, label, description}],   // optional; falls back to proposal.options
 *     option_labels: { id: label }            // optional alternate
 *   }
 *
 * Phase 17 F2 + B6 frontend cleanup — the manual admin "resolve tie" UI
 * (handler + button row) was removed in this pass. Ties are now auto-
 * resolved at advance-to-passed time via the org's configured method
 * (see backend tie_resolution.py). Resolved ties surface here as a
 * <TieResolutionBanner> rendered above the winner display.
 */
export default function RCVResultsPanel({ tally, proposal }) {
  const optionLabelMap = useMemo(() => {
    const m = {};
    const fromTally = Array.isArray(tally?.options) ? tally.options : [];
    fromTally.forEach(o => { if (o?.id) m[o.id] = o.label || o.id; });
    if (tally?.option_labels) {
      Object.entries(tally.option_labels).forEach(([k, v]) => { m[k] = v; });
    }
    // Phase 67 W3 — for elections the proposal options' descriptions
    // (candidate display names) take precedence over the raw UUID labels.
    (proposal?.options || []).forEach(o => {
      const lbl = optionDisplayLabel(proposal, o);
      if (lbl && (proposal?.is_election || !m[o.id])) m[o.id] = lbl;
    });
    return m;
  }, [tally, proposal]);

  if (!tally || !Array.isArray(tally.rounds)) return null;

  const labelOf = (id) => optionLabelMap[id] || id;
  const method = tally.method || (tally.num_winners > 1 ? 'stv' : 'irv');
  const numWinners = tally.num_winners ?? 1;
  const winners = tally.winners || [];
  const tied = tally.tied;
  const tieResolution = tally.tie_resolution || proposal.tie_resolution;

  const headerLabel = method === 'stv'
    ? `Single Transferable Vote (STV)`
    : `Ranked-Choice (IRV)`;

  function formatCount(v) {
    // STV may produce fractional counts; show 2dp only when needed
    if (Number.isInteger(v)) return String(v);
    return Number(v).toFixed(2);
  }

  // Determine maximum count in any single round (for bar scaling)
  const maxRoundCount = tally.rounds.reduce((max, r) => {
    const counts = Object.values(r.option_counts || {});
    const localMax = counts.length > 0 ? Math.max(...counts) : 0;
    return Math.max(max, localMax);
  }, 0) || 1;

  return (
    <div className="space-y-4">
      <div>
        <h3 className="text-sm font-semibold text-gray-700 uppercase tracking-wide">
          {headerLabel}
        </h3>
        {numWinners > 1 && (
          <p className="text-xs text-gray-500 mt-0.5">{numWinners} winners to elect</p>
        )}
      </div>

      {/* Phase 17 F2 — auto-resolved tie banner. Replaces the old admin
          "select the winning option" amber callout (B6 frontend cleanup):
          ties now auto-resolve at advance-to-passed time via the org's
          configured method, so there is no manual UI to surface here.
          When tally.tied is true but tie_resolution is absent (legacy
          closed proposals from before this pass — D7 says we don't
          backfill), we render a low-key informational note instead of
          the previous admin-action callout. */}
      {tieResolution && (
        <TieResolutionBanner
          tieResolution={tieResolution}
          labelOf={labelOf}
        />
      )}
      {tied && !tieResolution && (
        <div className="bg-amber-50 border border-amber-200 rounded-lg p-3">
          <p className="text-sm text-amber-800">
            Tied final round — {winners.length} option{winners.length !== 1 ? 's' : ''} tied at the final step.
          </p>
        </div>
      )}

      {/* Final result — Item 5: tense-aware label for in-progress vs closed.
          Phase 67 W1 — a failed election (quorum gated) seated nobody:
          the tally still names the most-supported candidates, but the
          box renders neutrally instead of announcing a "Winner". */}
      {!tied && winners.length > 0 && (() => {
        const inProgress = proposal?.status === 'voting';
        const notSeated = proposal?.is_election && proposal?.status === 'failed';
        const totalRounds = Array.isArray(tally.rounds) ? tally.rounds.length : null;
        const headerWord = inProgress
          ? 'Currently winning'
          : notSeated
            ? 'Most support (not seated)'
            : (numWinners > 1 ? 'Winners' : 'Winner');
        const boxCls = inProgress
          ? 'bg-blue-50 border-blue-200'
          : notSeated
            ? 'bg-gray-50 border-gray-200'
            : 'bg-green-50 border-green-200';
        const headCls = inProgress ? 'text-blue-700' : notSeated ? 'text-gray-600' : 'text-green-700';
        const bodyCls = inProgress ? 'text-blue-800' : notSeated ? 'text-gray-700' : 'text-green-800';
        const numCls = inProgress ? 'text-blue-600' : notSeated ? 'text-gray-500' : 'text-green-600';
        return (
          <div className={`${boxCls} border rounded-lg p-3`}>
            <p className={`text-xs font-medium uppercase tracking-wide mb-1 ${headCls}`}>
              {headerWord}
              {inProgress && totalRounds ? ` after ${totalRounds} round${totalRounds === 1 ? '' : 's'}` : ''}
            </p>
            {numWinners > 1 ? (
              <ol className={`text-sm space-y-0.5 ${bodyCls}`}>
                {winners.map((wid, idx) => (
                  <li key={wid}>
                    <span className={`mr-1 ${numCls}`}>{idx + 1}.</span>
                    <strong>{labelOf(wid)}</strong>
                  </li>
                ))}
              </ol>
            ) : (
              <p className={`text-base font-bold ${bodyCls}`}>
                {labelOf(winners[0])}
              </p>
            )}
          </div>
        );
      })()}

      {/* Round-by-round breakdown */}
      <div className="space-y-3">
        <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide">Round-by-round</p>
        {tally.rounds.map(round => {
          const counts = round.option_counts || {};
          const sortedIds = Object.keys(counts).sort((a, b) => counts[b] - counts[a]);
          const transferBreakdown = round.transfer_breakdown || {};
          const transferTargets = Object.keys(transferBreakdown);

          return (
            <div
              key={round.round_number}
              className="bg-white border border-gray-200 rounded-lg p-3 space-y-2"
            >
              <div className="flex items-center justify-between">
                <h4 className="text-sm font-semibold text-[var(--brand-primary)]">
                  Round {round.round_number + 1}
                </h4>
                {round.transferred_from && (
                  <span className="text-xs text-gray-400">
                    Votes from {labelOf(round.transferred_from)} transferred
                  </span>
                )}
              </div>

              {/* Counts as horizontal bars */}
              <div className="space-y-1">
                {sortedIds.map(oid => {
                  const count = counts[oid] || 0;
                  const pct = (count / maxRoundCount) * 100;
                  const isEliminated = round.eliminated === oid;
                  const isElected = (round.elected || []).includes(oid);
                  return (
                    <div key={oid}>
                      <div className="flex items-center justify-between text-xs mb-0.5">
                        <span
                          className={`font-medium ${
                            isElected ? 'text-[#2D8A56]' : isEliminated ? 'text-[#C0392B] line-through' : 'text-gray-700'
                          }`}
                        >
                          {labelOf(oid)}
                          {isElected && ' ✓ elected'}
                          {isEliminated && ' ✗ eliminated'}
                        </span>
                        <span className="text-xs text-gray-500">{formatCount(count)}</span>
                      </div>
                      <div className="w-full bg-gray-100 rounded-full h-2">
                        <div
                          className={`h-2 rounded-full ${
                            isElected ? 'bg-[#2D8A56]' : isEliminated ? 'bg-[#C0392B]' : 'bg-[var(--brand-accent)]'
                          }`}
                          style={{ width: `${pct}%`, minWidth: count > 0 ? '3px' : '0' }}
                        />
                      </div>
                    </div>
                  );
                })}
              </div>

              {/* Eliminated / elected callout text */}
              {round.eliminated && (
                <p className="text-xs text-[#C0392B]">
                  Eliminated this round: <strong>{labelOf(round.eliminated)}</strong>
                </p>
              )}
              {(round.elected || []).length > 0 && (
                <p className="text-xs text-[#2D8A56]">
                  Elected this round:{' '}
                  <strong>{round.elected.map(labelOf).sort((a, b) => a.localeCompare(b)).join(', ')}</strong>
                </p>
              )}

              {/* Transfer breakdown */}
              {transferTargets.length > 0 && (
                <div className="text-xs text-gray-500 bg-gray-50 rounded px-2 py-1.5">
                  <span className="font-medium text-gray-600">Transfers: </span>
                  {transferTargets.map((tid, idx) => (
                    <span key={tid}>
                      {idx > 0 && '  '}
                      → {labelOf(tid)}: {formatCount(transferBreakdown[tid])}
                    </span>
                  ))}
                </div>
              )}
            </div>
          );
        })}
      </div>

      {/* Summary stats. Phase 67 W1 — elections get a neutral turnout
          line. Quorum gates seat installation: an election that closed
          failed under an explicit quorum seated nobody, and says so
          honestly. */}
      <div className="text-sm text-gray-500 space-y-1 pt-1">
        {proposal?.is_election ? (
          <>
            <p>{tally.total_ballots_cast ?? 0} of {tally.total_eligible ?? 0} eligible member{(tally.total_eligible ?? 0) !== 1 ? 's' : ''} voted</p>
            {proposal.status === 'failed' && tally.quorum_met === false && (
              <p className="text-[#C0392B] font-medium">
                Quorum not met — no seats were changed.
              </p>
            )}
          </>
        ) : (
          <p>
            {tally.total_ballots_cast ?? 0} ballot{(tally.total_ballots_cast ?? 0) !== 1 ? 's' : ''} cast
            {tally.total_eligible > 0 &&
              ` of ${tally.total_eligible} eligible (${(
                (tally.total_ballots_cast / tally.total_eligible) * 100
              ).toFixed(1)}%)`}
          </p>
        )}
        {(tally.total_abstain ?? 0) > 0 && (
          <p>
            {tally.total_abstain} empty ranking
            {tally.total_abstain !== 1 ? 's' : ''} (abstain)
          </p>
        )}
      </div>
    </div>
  );
}
