import { formatExactCount } from '../utils/ratedBallot';

const reasons = {
  fewer_than_two_options: 'At least two options are required.',
  no_positive_weight_preferences: 'No positive-weight, non-abstaining ballots were submitted.',
  all_bottom_ratings: 'No option received a rating above zero.',
  quorum_not_met: 'Participation did not meet quorum.',
};

export default function ScoreResultsPanel({ tally, proposal }) {
  const result = tally?.method_result;
  if (!result) return <p className="text-sm text-gray-500">Score results are not available.</p>;
  const labels = result.option_labels || Object.fromEntries((proposal.options || []).map(o => [o.id, o.label]));
  const label = id => labels[id] || id;
  const closed = result.finalized === true || ['passed', 'failed', 'closed'].includes(proposal.status);
  const unit = tally.weighted ? tally.unit_label || 'voting shares' : 'votes';
  const entries = Object.entries(result.scores || {});
  const maximum = entries.reduce((max, [, value]) => BigInt(value) > max ? BigInt(value) : max, 0n);
  const tiedTop = entries.filter(([, value]) => BigInt(value) === maximum).map(([id]) => id);
  return <section className="space-y-4" aria-label="Score results">
    <h3 className="text-sm font-semibold uppercase tracking-wide">Score results</h3>
    {result.winner && <p className="font-semibold">{closed && result.quorum_met ? 'Winner' : 'Provisional leader'}: {label(result.winner)}</p>}
    {result.no_result_reason && <p className="text-sm text-amber-800">No finalized winner: {reasons[result.no_result_reason] || result.no_result_reason.replaceAll('_', ' ')}</p>}
    {!result.quorum_met && <p className="text-sm text-amber-800">Quorum not met. Any displayed tally is provisional.</p>}
    <div className="overflow-x-auto"><table className="w-full text-sm text-left">
      <caption className="text-left font-medium mb-2">Total points</caption>
      <thead><tr><th scope="col" className="py-1 pr-3">Option</th><th scope="col">Points</th></tr></thead>
      <tbody>{entries.map(([id, count]) => <tr key={id} className="border-t"><th scope="row" className="py-2 pr-3 font-normal break-words">{label(id)}</th><td className="tabular-nums">{formatExactCount(count)}</td></tr>)}</tbody>
    </table></div>
    <p className="text-xs text-gray-600">Each rating contributes its points multiplied by the represented voting weight. Unrated options receive zero. These totals are not approval percentages.</p>
    {maximum > 0n && tiedTop.length > 1 && <p className="text-sm">Tied highest totals: {tiedTop.map(label).join(', ')}.</p>}
    <div className="text-xs space-y-1">
      <div>Participating people: {formatExactCount(result.participating_headcount)}</div>
      <div>Eligible people: {formatExactCount(result.eligible_headcount)}</div>
      <div>Ballots cast ({unit}): {formatExactCount(result.total_ballots_cast)}</div>
      <div>Abstentions ({unit}): {formatExactCount(result.total_abstain)}</div>
    </div>
    {result.priority_used && <p className="text-xs text-amber-800">Equal highest totals were resolved by the committed draw order. {closed ? 'The recorded outcome preserves that draw.' : 'This result is provisional and cannot satisfy Stable Result Required.'}</p>}
    {!!result.tie_trace?.length && <details><summary className="text-sm cursor-pointer">How ties were resolved</summary><p className="text-xs mt-2">The committed draw order selected among the options tied for the highest total points.</p></details>}
    {proposal.voting_rules?.tie_commitment && <details><summary className="text-xs cursor-pointer">Auditable voting rules</summary><p className="text-xs break-all mt-2">Rule: {proposal.voting_rules.rule_id}<br />Draw commitment: {proposal.voting_rules.tie_commitment}</p>{result.tie_seed && <p className="text-xs break-all mt-2">Revealed seed: {result.tie_seed}</p>}</details>}
  </section>;
}
