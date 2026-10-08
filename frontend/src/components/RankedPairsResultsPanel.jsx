import { formatExactCount } from '../utils/ratedBallot';

const reasons = {
  fewer_than_two_options: 'At least two options are required.',
  no_positive_weight_preferences: 'No positive-weight, non-abstaining ballots were submitted.',
  no_strict_preferences: 'No ballot expressed a strict preference between any options.',
  quorum_not_met: 'Participation did not meet quorum.',
};

export default function RankedPairsResultsPanel({ tally, proposal }) {
  const result = tally?.method_result;
  if (!result) return <p className="text-sm text-gray-500">Ranked Pairs results are not available.</p>;
  const labels = result.option_labels || Object.fromEntries((proposal.options || []).map(option => [option.id, option.label]));
  const label = id => labels[id] || id;
  const ids = Object.keys(result.pairwise || {});
  const closed = ['passed', 'failed', 'closed'].includes(proposal.status);
  const unit = tally.weighted ? tally.unit_label || 'voting shares' : 'votes';
  const locked = new Set((result.locked_edges || []).map(edge => `${edge.winner}:${edge.loser}`));
  return <section className="space-y-4" aria-label="Ranked Pairs results">
    <h3 className="text-sm font-semibold uppercase tracking-wide">Ranked Pairs results</h3>
    {result.winner && <p className="font-semibold">{closed && result.quorum_met ? 'Winner' : 'Provisional leader'}: {label(result.winner)}</p>}
    {result.no_result_reason && <p className="text-sm text-amber-800">No finalized winner: {reasons[result.no_result_reason] || result.no_result_reason.replaceAll('_', ' ')}</p>}
    {!result.quorum_met && <p className="text-sm text-amber-800">Quorum not met. Any displayed tally is provisional.</p>}
    <p className="text-sm">Head-to-head victories are considered by largest winning margin, then greatest winning support. A victory is locked unless it would create a cycle. The winner has no incoming locked defeat.</p>
    {!!result.source_candidates?.length && <p className="text-sm">Options with no incoming locked defeat: {result.source_candidates.map(label).join(', ')}.</p>}
    <details><summary className="text-sm cursor-pointer">Head-to-head victories and locking decisions</summary>
      <p className="text-xs text-gray-600 mt-2">Shown in the order considered. Margin and support use {unit}. Pairwise equalities create no victory.</p>
      {result.ordered_victories?.length ? <ol className="list-decimal pl-5 text-sm space-y-3 mt-2">{result.ordered_victories.map((edge, index) => <li key={index}>
        <span className="font-medium">{label(edge.winner)} over {label(edge.loser)}</span>: margin {formatExactCount(edge.margin)}, support {formatExactCount(edge.support)}.
        <p className="text-xs">{locked.has(`${edge.winner}:${edge.loser}`) ? 'Locked — kept this head-to-head victory.' : 'Skipped — would create a directed cycle.'}</p>
      </li>)}</ol> : <p className="text-sm mt-2">No strict head-to-head victories.</p>}
    </details>
    <details><summary className="text-sm cursor-pointer">Pairwise preference matrix</summary>
      <div className="overflow-x-auto mt-2"><table className="text-xs text-left w-full">
        <caption className="text-left mb-2">Each cell counts {unit} preferring the row option over the column option. Equal rankings contribute to neither direction.</caption>
        <thead><tr><th scope="col" className="p-2">Preferred over →</th>{ids.map(id => <th scope="col" className="p-2" key={id}>{label(id)}</th>)}</tr></thead>
        <tbody>{ids.map(row => <tr key={row} className="border-t"><th scope="row" className="p-2 font-medium">{label(row)}</th>{ids.map(column => <td key={column} className="p-2 tabular-nums">{row === column ? '—' : formatExactCount(result.pairwise[row][column])}</td>)}</tr>)}</tbody>
      </table></div>
    </details>
    <div className="text-xs space-y-1">
      <div>Participating people: {formatExactCount(result.participating_headcount)}</div>
      <div>Eligible people: {formatExactCount(result.eligible_headcount)}</div>
      <div>Ballots cast ({unit}): {formatExactCount(result.total_ballots_cast)}</div>
      <div>Abstentions ({unit}): {formatExactCount(result.total_abstain)}</div>
    </div>
    {result.priority_used && <p className="text-xs text-amber-800">The committed draw order was consulted for equal-strength victories or tied source options. {closed ? 'The recorded outcome preserves that draw.' : 'This result is provisional and cannot satisfy Stable Result Required.'}</p>}
    {!!result.tie_trace?.length && <details><summary className="text-sm cursor-pointer">How ties were resolved</summary><ol className="text-xs list-decimal pl-4 mt-2 space-y-2">{result.tie_trace.map((stage, index) => <li key={index}>{stage.stage === 'edge_priority' ? `Equal-strength victories: margin ${formatExactCount(stage.margin)}, support ${formatExactCount(stage.support)}. Used committed option priorities to order the edges.` : `Multiple source options: ${(stage.pool || []).map(label).join(', ')}. Used the committed draw order.`}</li>)}</ol></details>}
    {proposal.voting_rules?.tie_commitment && <details><summary className="text-xs cursor-pointer">Auditable voting rules</summary><p className="text-xs break-all mt-2">Rule: {proposal.voting_rules.rule_id}<br />Draw commitment: {proposal.voting_rules.tie_commitment}</p>{result.tie_seed && <p className="text-xs break-all mt-2">Revealed seed: {result.tie_seed}</p>}</details>}
  </section>;
}
