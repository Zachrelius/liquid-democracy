import { formatExactCount } from '../utils/ratedBallot';
import { MULTIWINNER_COPY, votingMethodLabel } from '../utils/votingMethods';

export default function MultiwinnerResultsPanel({ tally, proposal }) {
  const result = tally?.method_result;
  if (!result) return <p>Results are unavailable.</p>;
  const labels = result.option_labels || Object.fromEntries((proposal.options || []).map(o => [o.id, o.label]));
  const label = id => labels[id] || id;
  const selected = new Set(result.winners || []);
  const official = result.finalized && result.quorum_met;
  const ordered = [...(result.ranked_order || []), ...Object.keys(result.scores || {}).filter(id => !(result.ranked_order || []).includes(id))];
  return <section aria-label={`${votingMethodLabel(proposal.voting_method)} multiple-winner results`} className="space-y-4">
    <h3 className="font-semibold">{votingMethodLabel(proposal.voting_method)}: multiple winners</h3>
    <p className="text-sm">{MULTIWINNER_COPY[proposal.voting_method]}</p>
    <p className="font-medium">{official ? 'Selected' : 'Provisional selections'}: {(result.winners || []).map(label).join(', ') || 'None'}.</p>
    <p className="text-sm">{formatExactCount(result.filled_count)} of {formatExactCount(result.requested_count)} places selected.</p>
    {Number(result.unfilled_count) > 0 && <p className="text-sm text-amber-800">{formatExactCount(result.unfilled_count)} unfilled: no remaining supported options. Zero total scores cannot fill a place.</p>}
    {!result.quorum_met && <p className="text-sm text-amber-800">Quorum not met. No official winners or office grants can be finalized.</p>}
    {result.selection_boundary_tie && <p className="text-sm">Equal totals at the selection boundary use the committed candidate priority. The winner count does not expand.</p>}
    {result.priority_used && <p className="text-xs text-amber-800">A tie consulted committed priority. This result cannot satisfy Stable Result Required.</p>}
    <div className="overflow-x-auto"><table className="w-full text-left text-sm">
      <caption className="text-left font-medium">Ranked total points</caption><thead><tr><th scope="col">Option</th><th scope="col">Points</th><th scope="col">Selection</th></tr></thead>
      <tbody>{ordered.map(id => <tr key={id} className="border-t"><th scope="row" className="py-2 pr-2 font-normal break-words">{label(id)}</th><td>{formatExactCount(result.scores?.[id])}</td><td>{selected.has(id) ? official ? 'Selected' : 'Provisional' : BigInt(result.scores?.[id] || 0) === 0n ? 'Unsupported' : ''}</td></tr>)}</tbody>
    </table></div>
    <p className="text-xs text-gray-600">Participating people: {formatExactCount(result.participating_headcount)}. Ballots cast ({tally.weighted ? tally.unit_label || 'voting shares' : 'votes'}): {formatExactCount(result.total_ballots_cast)}. Abstentions: {formatExactCount(result.total_abstain)}.</p>
    <details><summary className="text-sm cursor-pointer">Auditable counting rules</summary>
      <p className="text-xs break-all mt-2">Rule: {proposal.voting_rules?.rule_id}. Draw commitment: {proposal.voting_rules?.tie_commitment}.</p>
      {result.tie_seed && <p className="text-xs break-all">Revealed seed: {result.tie_seed}</p>}
    </details>
  </section>;
}
