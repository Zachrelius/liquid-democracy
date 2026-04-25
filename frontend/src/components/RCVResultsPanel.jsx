import { useState, useMemo } from 'react';
import api from '../api';
import { useOrg } from '../OrgContext';
import { useToast } from './Toast';
import { useConfirm } from './ConfirmDialog';

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
 */
export default function RCVResultsPanel({ tally, proposal }) {
  const { currentOrg, isAdmin } = useOrg();
  const toast = useToast();
  const confirm = useConfirm();
  const [resolving, setResolving] = useState(false);

  const optionLabelMap = useMemo(() => {
    const m = {};
    const fromTally = Array.isArray(tally?.options) ? tally.options : [];
    fromTally.forEach(o => { if (o?.id) m[o.id] = o.label || o.id; });
    if (tally?.option_labels) {
      Object.entries(tally.option_labels).forEach(([k, v]) => { m[k] = v; });
    }
    (proposal?.options || []).forEach(o => { if (!m[o.id]) m[o.id] = o.label; });
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

  async function handleResolveTie(optionId) {
    const ok = await confirm({
      title: 'Resolve Tie',
      message: `Select "${labelOf(optionId)}" as the winning option? This cannot be undone.`,
      destructive: false,
    });
    if (!ok) return;
    setResolving(true);
    try {
      await api.post(`/api/orgs/${currentOrg.slug}/proposals/${proposal.id}/resolve-tie`, {
        selected_option_id: optionId,
      });
      toast.success('Tie resolved');
      window.location.reload();
    } catch (e) {
      toast.error(e.message);
    } finally {
      setResolving(false);
    }
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

      {/* Tie banners (final-round tie) */}
      {tied && !tieResolution && (
        <div className="bg-amber-50 border border-amber-200 rounded-lg p-3">
          <p className="text-sm font-medium text-amber-800">
            Tied final round — {winners.length} option{winners.length !== 1 ? 's' : ''} tied at the final step.
          </p>
          {isAdmin && (
            <div className="mt-2 space-y-1">
              <p className="text-xs text-amber-700">As admin, select the winning option:</p>
              <div className="flex flex-wrap gap-2">
                {winners.map(wid => (
                  <button
                    key={wid}
                    onClick={() => handleResolveTie(wid)}
                    disabled={resolving}
                    className="text-xs px-3 py-1 bg-amber-600 text-white rounded-lg hover:bg-amber-700 disabled:opacity-50"
                  >
                    {labelOf(wid)}
                  </button>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
      {tieResolution && (
        <div className="bg-blue-50 border border-blue-200 rounded-lg p-3">
          <p className="text-sm text-blue-800">
            Tie resolved. Selected winner:{' '}
            <strong>{labelOf(tieResolution.selected_option_id)}</strong>
            {tieResolution.resolved_at && (
              <span className="text-xs text-blue-600 ml-1">
                on {new Date(tieResolution.resolved_at).toLocaleDateString()}
              </span>
            )}
          </p>
        </div>
      )}

      {/* Final result — Item 5: tense-aware label for in-progress vs closed */}
      {!tied && winners.length > 0 && (() => {
        const inProgress = proposal?.status === 'voting';
        const totalRounds = Array.isArray(tally.rounds) ? tally.rounds.length : null;
        const headerWord = inProgress
          ? (numWinners > 1 ? 'Currently winning' : 'Currently winning')
          : (numWinners > 1 ? 'Winners' : 'Winner');
        return (
          <div className={`${inProgress ? 'bg-blue-50 border-blue-200' : 'bg-green-50 border-green-200'} border rounded-lg p-3`}>
            <p className={`text-xs font-medium uppercase tracking-wide mb-1 ${inProgress ? 'text-blue-700' : 'text-green-700'}`}>
              {headerWord}
              {inProgress && totalRounds ? ` after ${totalRounds} round${totalRounds === 1 ? '' : 's'}` : ''}
            </p>
            {numWinners > 1 ? (
              <ol className={`text-sm space-y-0.5 ${inProgress ? 'text-blue-800' : 'text-green-800'}`}>
                {winners.map((wid, idx) => (
                  <li key={wid}>
                    <span className={`mr-1 ${inProgress ? 'text-blue-600' : 'text-green-600'}`}>{idx + 1}.</span>
                    <strong>{labelOf(wid)}</strong>
                  </li>
                ))}
              </ol>
            ) : (
              <p className={`text-base font-bold ${inProgress ? 'text-blue-800' : 'text-green-800'}`}>
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
                <h4 className="text-sm font-semibold text-[#1B3A5C]">
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
                            isElected ? 'bg-[#2D8A56]' : isEliminated ? 'bg-[#C0392B]' : 'bg-[#2E75B6]'
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
                  <strong>{round.elected.map(labelOf).join(', ')}</strong>
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

      {/* Summary stats */}
      <div className="text-sm text-gray-500 space-y-1 pt-1">
        <p>
          {tally.total_ballots_cast ?? 0} ballot{(tally.total_ballots_cast ?? 0) !== 1 ? 's' : ''} cast
          {tally.total_eligible > 0 &&
            ` of ${tally.total_eligible} eligible (${(
              (tally.total_ballots_cast / tally.total_eligible) * 100
            ).toFixed(1)}%)`}
        </p>
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
