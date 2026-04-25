import { useState, useMemo } from 'react';
import BinaryVoteFlowGraph from './BinaryVoteFlowGraph';
import OptionAttractorVoteFlowGraph from './OptionAttractorVoteFlowGraph';
import { formatVotingStatus } from './voteFlowGraphUtils';

/**
 * VoteFlowGraph — top-level dispatcher that renders the appropriate
 * sub-component based on `data.voting_method` (Phase 7B).
 *
 *   binary         -> BinaryVoteFlowGraph (preserved bit-for-bit)
 *   approval       -> OptionAttractorVoteFlowGraph (uniform attractor 1.0)
 *   ranked_choice  -> OptionAttractorVoteFlowGraph (linear ranking decay)
 *
 * Also renders a method-appropriate tally summary above the graph.
 *
 * Backend contract reminders (see phase7B_spec.md):
 *   data.voting_method        -> top-level method string
 *   data.options              -> [{id,label,display_order,approval_count,first_pref_count}]
 *   data.nodes[i].ballot      -> {vote_value | approvals | ranking} or null (privacy)
 *   data.clusters             -> { voting_method, total_eligible, total_cast,
 *                                  total_abstain, not_cast,
 *                                  binary?: {...}, approval?: {...}, rcv?: {...} }
 *   data.clusters.yes/no/...  -> back-compat top-level binary fields when method=binary
 */
export default function VoteFlowGraph({ data, onNodeClick, proposal, tally }) {
  if (!data) return null;

  const method = data.voting_method || 'binary';

  return (
    <div className="space-y-3">
      <TallySummary data={data} proposal={proposal} tally={tally} />
      {method === 'binary' ? (
        <BinaryVoteFlowGraph data={data} onNodeClick={onNodeClick} />
      ) : (
        <OptionAttractorVoteFlowGraph data={data} onNodeClick={onNodeClick} />
      )}
    </div>
  );
}

/**
 * TallySummary — small line of method-aware aggregate counts shown above the graph.
 * Reads `data.clusters` (Phase 7B-extended) with back-compat for legacy binary shape.
 */
function TallySummary({ data, proposal, tally }) {
  const method = data.voting_method || data.clusters?.voting_method || 'binary';
  const clusters = data.clusters || {};
  const inProgress = proposal?.status === 'voting';

  const [expanded, setExpanded] = useState(false);

  const optionLabel = useMemo(() => {
    const m = new Map();
    (data.options || []).forEach((o) => m.set(o.id, o.label));
    return m;
  }, [data.options]);

  if (method === 'binary') {
    // Item 5: when in voting status, show a "Currently passing/failing"
    // headline derived from tally.threshold_met (when available).
    const status = inProgress && proposal && tally
      ? formatVotingStatus(proposal, { runnerUpDelta: !!tally.threshold_met })
      : null;
    return (
      <div className="flex flex-wrap gap-3 text-xs text-gray-500 items-center">
        <span className="text-[#2D8A56] font-medium">
          {clusters.yes?.count || 0} Yes
          <span className="text-gray-400 font-normal">
            {' '}
            ({clusters.yes?.direct || 0}d + {clusters.yes?.delegated || 0}del)
          </span>
        </span>
        <span className="text-[#C0392B] font-medium">
          {clusters.no?.count || 0} No
          <span className="text-gray-400 font-normal">
            {' '}
            ({clusters.no?.direct || 0}d + {clusters.no?.delegated || 0}del)
          </span>
        </span>
        <span className="text-gray-500 font-medium">
          {clusters.abstain?.count || 0} Abstain
        </span>
        <span className="text-gray-400">
          {clusters.not_cast?.count || 0} Not cast
        </span>
        {status && (
          <span className="text-[#2E75B6] font-medium">{status.label}</span>
        )}
      </div>
    );
  }

  // Approval / RCV path uses the new aggregates.
  const totalCast = clusters.total_cast ?? 0;
  const totalAbstain = clusters.total_abstain ?? 0;
  // Backend ships `not_cast` as the legacy dict {count, direct, delegated}
  // for back-compat with the binary frontend; unwrap to int for new paths.
  const notCast =
    typeof clusters.not_cast === 'object' && clusters.not_cast !== null
      ? clusters.not_cast.count ?? 0
      : clusters.not_cast ?? 0;

  if (method === 'approval') {
    const approvalAggs = clusters.approval || {};
    const counts = approvalAggs.counts || {}; // { option_id: count }
    const winners = approvalAggs.winners || [];
    let topId = null;
    let topCount = 0;
    for (const [oid, c] of Object.entries(counts)) {
      if (c > topCount) {
        topCount = c;
        topId = oid;
      }
    }
    const topLabel = topId ? optionLabel.get(topId) || topId : null;
    const winnerLabels =
      winners.length > 1 ? winners.map((id) => optionLabel.get(id) || id).join(', ') : null;

    // Sort options by approval count for breakdown.
    const breakdown = (data.options || [])
      .map((o) => ({ ...o, count: counts[o.id] || 0 }))
      .sort((a, b) => b.count - a.count);

    // Item 5: tense-aware headline. In voting -> "Top option (currently)",
    // closed -> "Winner".
    const headline = topLabel && proposal
      ? formatVotingStatus(proposal, { winnerLabel: topLabel })
      : null;

    return (
      <div className="text-xs text-gray-500 space-y-1">
        <div className="flex flex-wrap gap-3 items-center">
          <span className="font-medium text-gray-600">
            {totalCast} ballot{totalCast === 1 ? '' : 's'} cast
          </span>
          <span className="text-gray-500">
            ({totalAbstain} abstain{totalAbstain === 1 ? '' : 's'}, {notCast} not cast)
          </span>
          {headline ? (
            <span className="text-[#2E75B6] font-medium">
              {headline.label}: {headline.suffix} ({topCount})
            </span>
          ) : topLabel ? (
            <span className="text-[#2E75B6] font-medium">
              Top: {topLabel} ({topCount})
            </span>
          ) : null}
          {winnerLabels && (
            <span className="text-amber-600">Tied winners: {winnerLabels}</span>
          )}
          {(data.options || []).length > 0 && (
            <button
              onClick={() => setExpanded((v) => !v)}
              className="text-gray-400 hover:text-gray-600 underline text-[11px]"
            >
              {expanded ? 'Hide' : 'Show'} per-option breakdown
            </button>
          )}
        </div>
        {expanded && (
          <ul className="text-[11px] text-gray-600 pl-2 space-y-0.5">
            {breakdown.map((o) => (
              <li key={o.id}>
                <span className="font-medium">{o.label}:</span> {o.count} approval
                {o.count === 1 ? '' : 's'}
              </li>
            ))}
          </ul>
        )}
      </div>
    );
  }

  if (method === 'ranked_choice') {
    const rcv = clusters.rcv || {};
    const winners = rcv.winners || [];
    const totalRounds = rcv.total_rounds ?? null;
    const winnerLabels = winners.map((id) => optionLabel.get(id) || id).join(', ');

    const elimination = rcv.elimination || rcv.rounds || null; // backend may surface either

    // Item 5: in-progress -> "Currently winning", closed -> "Winner".
    // formatVotingStatus handles the singular case; multi-winner STV keeps
    // the explicit "Winners: " label below.
    const singleWinnerStatus =
      winners.length === 1 && proposal
        ? formatVotingStatus(proposal, { winnerLabel: winnerLabels, totalRounds })
        : null;

    return (
      <div className="text-xs text-gray-500 space-y-1">
        <div className="flex flex-wrap gap-3 items-center">
          <span className="font-medium text-gray-600">
            {totalCast} ballot{totalCast === 1 ? '' : 's'} cast
          </span>
          <span className="text-gray-500">
            ({totalAbstain} abstain{totalAbstain === 1 ? '' : 's'}, {notCast} not cast)
          </span>
          {singleWinnerStatus ? (
            <span className="text-[#2E75B6] font-medium">
              {singleWinnerStatus.label}: {singleWinnerStatus.suffix}
            </span>
          ) : winners.length > 0 ? (
            <span className="text-[#2E75B6] font-medium">
              {winners.length > 1 ? (inProgress ? 'Currently winning: ' : 'Winners: ') : 'Winner: '}
              {winnerLabels}
              {totalRounds != null && (
                <span className="text-gray-500 font-normal">
                  {' '}
                  after {totalRounds} round{totalRounds === 1 ? '' : 's'}
                </span>
              )}
            </span>
          ) : null}
          {elimination && (
            <button
              onClick={() => setExpanded((v) => !v)}
              className="text-gray-400 hover:text-gray-600 underline text-[11px]"
            >
              {expanded ? 'Hide' : 'Show'} elimination summary
            </button>
          )}
        </div>
        {expanded && elimination && (
          <pre className="text-[10px] text-gray-500 bg-gray-50 border border-gray-100 rounded p-2 overflow-auto max-h-40">
            {JSON.stringify(elimination, null, 2)}
          </pre>
        )}
      </div>
    );
  }

  return null;
}
