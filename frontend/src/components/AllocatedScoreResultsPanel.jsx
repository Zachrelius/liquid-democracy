import { formatExactCount } from '../utils/ratedBallot';
import { displayRational, exactRational } from '../utils/exactRational';
import { ALLOCATED_SCORE_COPY } from '../utils/votingMethods';

export default function AllocatedScoreResultsPanel({ tally, proposal }) {
  const result = tally?.method_result;
  if (!result) return <p>Results are unavailable.</p>;
  const labels = result.option_labels || Object.fromEntries((proposal.options || []).map(o => [o.id, o.label]));
  const label = id => labels[id] || id;
  const selected = new Set(result.winners || []);
  const official = result.finalized && result.quorum_met;
  const ids = [...(result.winners || []), ...Object.keys(result.scores || {}).filter(id => !selected.has(id))];
  return <section aria-label="Allocated Score multiple-winner results" className="space-y-4">
    <h3 className="font-semibold">Allocated Score · No automatic runoff</h3>
    <p className="text-sm">{ALLOCATED_SCORE_COPY}</p>
    <p className="font-medium">{official ? 'Selected' : 'Provisional selections'}: {(result.winners || []).map(label).join(', ') || 'None'}.</p>
    <p className="text-sm">{formatExactCount(result.filled_count)} of {formatExactCount(result.requested_count)} places selected. Selection order is not a universal best-to-worst quality ranking.</p>
    {Number(result.unfilled_count) > 0 && <p className="text-sm text-amber-800">{formatExactCount(result.unfilled_count)} unfilled: no remaining candidate has positive score under remaining influence.</p>}
    {!result.quorum_met && <p className="text-sm text-amber-800">Quorum not met. There are no official selections or office grants.</p>}
    {result.priority_used && <p className="text-xs text-amber-800">An exact score tie consulted committed priority. This result cannot satisfy Stable Result Required.</p>}
    <p className="text-sm">Fixed quota: {displayRational(result.quota)} {tally.weighted ? tally.unit_label || 'voting shares' : 'vote weight'}. Original informative voting weight: {formatExactCount(result.informative_weight)}. All-zero and abstaining ballots are excluded from this allocation denominator.</p>
    <p className="text-sm">Allocated weight: {displayRational(result.allocated_weight)}. Remaining influence: {displayRational(result.remaining_weight)}. {result.stop_reason === 'winner_count_reached' ? 'The requested winner count was reached.' : 'Counting stopped on exhausted positive support.'}</p>
    <div className="overflow-x-auto"><table className="w-full text-left text-sm"><caption className="text-left font-medium">Initial total points</caption><thead><tr><th scope="col">Option</th><th scope="col">Points</th><th scope="col">Selection</th></tr></thead><tbody>{ids.map(id => <tr className="border-t" key={id}><th scope="row" className="font-normal py-2 pr-2 break-words">{label(id)}</th><td>{formatExactCount(result.scores[id])}</td><td>{selected.has(id) ? official ? 'Selected' : 'Provisional' : BigInt(result.scores[id] || 0)===0n ? 'Unsupported' : ''}</td></tr>)}</tbody></table></div>
    <div className="space-y-3"><h4 className="font-medium">Allocation rounds</h4>{(result.rounds || []).map((round,i) => <details key={i} open={i===0}><summary className="text-sm cursor-pointer">Round {i+1}: {label(round.winner)}</summary>
      <p className="text-sm">Remaining pool: {round.pool.map(label).join(', ')}.</p>
      <p className="text-sm">Influence before: {displayRational(round.remaining_weight_before)}; allocated: {displayRational(round.allocated_weight)}; after: {displayRational(round.remaining_weight_after)}. Quota shortfall: {displayRational(round.quota_shortfall)}.</p>
      <ul className="text-xs">{Object.entries(round.totals).map(([id,n]) => <li key={id}>{label(id)} remaining score: {displayRational(n)}.</li>)}</ul>
      {round.priority_used && <p className="text-xs">The highest-score tie used committed candidate priority.</p>}
      <details><summary className="text-xs cursor-pointer">Exact totals and aggregate contribution bands</summary><p className="text-xs">Bands are ordered by remaining fraction × score per unit of original voting weight. A boundary band allocates the same fraction from each remaining share. Zero-contribution bands can be reached to fill the quota.</p>
        <p className="text-xs break-words [overflow-wrap:anywhere]">Fixed quota: {exactRational(result.quota)}. Allocated: {exactRational(round.allocated_weight)}. Remaining: {exactRational(round.remaining_weight_after)}.</p>
        {Object.entries(round.totals).map(([id,n]) => <p className="text-xs break-words [overflow-wrap:anywhere]" key={id}>{label(id)}: {exactRational(n)}.</p>)}
        {(round.allocation_bands || []).map((band,j) => <p className="text-xs break-words [overflow-wrap:anywhere] mt-2" key={j}>Contribution {exactRational(band.contribution)}: remaining mass {exactRational(band.remaining_mass)}; allocated {exactRational(band.allocated_mass)}; common fraction allocated {exactRational(band.allocated_fraction)}.</p>)}
      </details>
    </details>)}</div>
    <p className="text-xs text-gray-600">Representation follows expressed support and voting weight, including shares when applicable. Allocation changes influence only within this vote; member shares and delegation permissions remain unchanged. This does not guarantee demographic representation.</p>
    <p className="text-xs text-gray-600">Participating people: {formatExactCount(result.participating_headcount)}. Ballot weight cast: {formatExactCount(result.total_ballots_cast)}. Abstentions: {formatExactCount(result.total_abstain)}.</p>
    <details><summary className="text-sm cursor-pointer">Auditable counting rules</summary><p className="text-xs break-words [overflow-wrap:anywhere]">Rule: {proposal.voting_rules?.rule_id}. Draw commitment: {proposal.voting_rules?.tie_commitment}. Exact quota: {exactRational(result.quota)}.</p>{result.tie_seed && <p className="text-xs break-words [overflow-wrap:anywhere]">Revealed seed: {result.tie_seed}</p>}<p className="text-xs">Appendix D, STAR technical specification v1.3, December 20, 2024, with the disclosed informative-weight quota and support-exhaustion policies. Displayed rounded numbers never decide a seat.</p></details>
  </section>;
}
