import { formatExactCount } from '../utils/ratedBallot';

const reasonLabels = {
  fewer_than_two_options: 'At least two options are required.',
  no_positive_weight_preferences: 'No positive-weight, non-abstaining ballots were submitted.',
  all_bottom_ratings: 'No option received a rating above zero.',
  quorum_not_met: 'Participation did not meet quorum.',
};
const tieLabels = {
  finalist_preferences: 'Finalist tie: compare preferences within the tied group',
  finalist_five_stars: 'Finalist tie: compare five-star ratings',
  finalist_priority: 'Finalist tie: use the committed draw order',
  runoff_total_score: 'Runoff tie: compare original total scores',
  runoff_five_stars: 'Runoff tie: compare five-star ratings',
  runoff_priority: 'Runoff tie: use the committed draw order',
};

export default function StarResultsPanel({ tally, proposal }) {
  const result = tally?.method_result;
  if (!result) return <p className="text-sm text-gray-500">STAR results are not available.</p>;
  const labels = result.option_labels || Object.fromEntries((proposal.options || []).map(o => [o.id, o.label]));
  const label = id => labels[id] || id;
  const closed = result.finalized === true || ['passed', 'failed', 'closed'].includes(proposal.status);
  const unit = tally.weighted ? tally.unit_label || 'voting shares' : 'votes';
  return <section className="space-y-4" aria-label="STAR results">
    <h3 className="text-sm font-semibold uppercase tracking-wide">STAR results</h3>
    {result.winner && <p className="font-semibold">{closed && result.quorum_met ? 'Winner' : 'Provisional leader'}: {label(result.winner)}</p>}
    {result.no_result_reason && <p className="text-sm text-amber-800">No finalized winner: {reasonLabels[result.no_result_reason] || result.no_result_reason.replaceAll('_', ' ')}</p>}
    {!result.quorum_met && <p className="text-sm text-amber-800">Quorum not met. Any displayed tally is provisional.</p>}
    <div className="overflow-x-auto">
      <table className="w-full text-sm text-left"><caption className="text-left font-medium mb-2">Scoring round — total stars</caption>
        <thead><tr><th scope="col" className="py-1 pr-3">Option</th><th scope="col">Total</th><th scope="col">Finalist</th></tr></thead>
        <tbody>{Object.entries(result.scores || {}).map(([id, count]) => <tr key={id} className="border-t"><th scope="row" className="py-2 pr-3 font-normal break-words">{label(id)}</th><td className="pr-2 tabular-nums">{formatExactCount(count)}</td><td>{result.finalists?.includes(id) ? 'Yes' : '—'}</td></tr>)}</tbody>
      </table>
    </div>
    {result.finalists?.length === 2 && <div>
      <h4 className="font-medium text-sm">Automatic runoff — {unit}</h4>
      <ul className="text-sm mt-2 space-y-1">{result.finalists.map(id => <li key={id}>{label(id)}: <strong>{formatExactCount(result.runoff?.[id] ?? '0')}</strong></li>)}</ul>
      <p className="text-xs text-gray-600 mt-2">Equal finalist preference: {formatExactCount(result.equal_preference ?? '0')} {unit}. These ballots support neither finalist in the runoff.</p>
    </div>}
    <p className="text-xs text-gray-600">Scores are total stars, not approval percentages. Only the two finalists compete in the runoff; scores do not establish an overall finish order.</p>
    <div className="text-xs space-y-1">
      <div>Participating people: {formatExactCount(result.participating_headcount)}</div>
      <div>Eligible people: {formatExactCount(result.eligible_headcount)}</div>
      <div>Ballots cast ({unit}): {formatExactCount(result.total_ballots_cast)}</div>
      <div>Abstentions ({unit}): {formatExactCount(result.total_abstain)}</div>
    </div>
    {result.priority_used && <p className="text-xs text-amber-800">The committed draw order was needed to break a tie. {closed ? 'The recorded outcome preserves that draw.' : 'This result is provisional and cannot satisfy Stable Result Required.'}</p>}
    {!!result.tie_trace?.length && <details><summary className="text-sm cursor-pointer">How ties were resolved</summary><ol className="mt-2 text-xs list-decimal pl-4 space-y-2">{result.tie_trace.map((stage, index) => <li key={index}>{tieLabels[stage.stage] || stage.stage.replaceAll('_', ' ')}.{stage.values && <ul>{Object.entries(stage.values).map(([id, value]) => <li key={id}>{label(id)}: {formatExactCount(value)}</li>)}</ul>}</li>)}</ol></details>}
    {proposal.voting_rules?.tie_commitment && <details><summary className="text-xs cursor-pointer">Auditable voting rules</summary><p className="text-xs break-all mt-2">Rule: {proposal.voting_rules.rule_id}<br />Draw commitment: {proposal.voting_rules.tie_commitment}</p>{result.tie_seed && <p className="text-xs break-all mt-2">Revealed seed: {result.tie_seed}</p>}</details>}
  </section>;
}
