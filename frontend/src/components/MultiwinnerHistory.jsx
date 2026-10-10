import { formatExactCount } from '../utils/ratedBallot';
import { displayRational } from '../utils/exactRational';
import { MAJORITY_JUDGMENT_GRADES, votingMethodLabel } from '../utils/votingMethods';

export default function MultiwinnerHistory({ snapshots, optionsById, method }) {
  return <section aria-label={`${votingMethodLabel(method)} selected-set history`} className="space-y-3 p-3">
    <p className="text-sm">History records the complete selected set, unfilled places and any committed-priority use. A change to the option set restarts stability observation. Any consulted priority prevents Stable Result Required.</p>
    {method === 'allocated_score' && <p className="text-sm">Allocated Score records proportional allocation with no automatic runoff. Selection order is not a universal quality ranking.</p>}
    <div className="overflow-x-auto"><table className="text-xs w-full text-left"><caption className="text-left font-medium">Recorded selected sets</caption><thead><tr><th scope="col">Time</th><th scope="col">Selections</th><th scope="col">Counting detail</th></tr></thead><tbody>{snapshots.map((snapshot,i) => {
      const result=snapshot.method_result;
      const label=id => result?.option_labels?.[id] || optionsById[id]?.label || id;
      return <tr key={snapshot.id || i} className="border-t align-top"><td className="p-2">{new Date(snapshot.captured_at).toLocaleString()}</td><td className="p-2">{result ? <>{(result.winners || []).map(label).join(', ') || 'No meaningful selections'}<br />{formatExactCount(result.filled_count)} of {formatExactCount(result.requested_count)} selected.{Number(result.unfilled_count)>0 && <> Unfilled: {formatExactCount(result.unfilled_count)} ({result.unfilled_reason?.replaceAll('_',' ')}).</>}{result.priority_used && ' Committed priority consulted.'}</> : 'Historical selected-set detail unavailable'}</td><td className="p-2">{result && <details><summary className="cursor-pointer">Recorded aggregates</summary>
        {method==='allocated_score' && <p>Fixed quota: {displayRational(result.quota)}; allocated weight: {displayRational(result.allocated_weight)}; remaining: {displayRational(result.remaining_weight)}.</p>}
        {method==='majority_judgment' ? Object.entries(result.majority_grades || {}).map(([id,g]) => <p key={id}>{label(id)}: {g==null ? 'No grades' : MAJORITY_JUDGMENT_GRADES[Number(g)]}.</p>) : method==='ranked_pairs' ? <><p>Collective order: {(result.ranked_order || []).map(label).join(', ')}.</p><p>{(result.locked_edges || []).length} original locked victories; {(result.skipped_edges || []).length} skipped cycles.</p></> : Object.entries(result.scores || {}).map(([id,n]) => <p key={id}>{label(id)} initial total: {formatExactCount(n)}.</p>)}
        {(result.rounds || []).map((round,j) => <details key={j}><summary>Round {j+1}: {label(round.winner)}</summary>{method==='star' ? round.competitive_runoff ? <p>Runoff: {Object.entries(round.runoff).map(([id,n]) => `${label(id)} ${formatExactCount(n)}`).join('; ')}. Equal preference: {formatExactCount(round.equal_preference)}.</p> : <p>Selected without a competitive runoff.</p> : method==='allocated_score' && <p>Allocated weight: {displayRational(round.allocated_weight)}; remaining influence: {displayRational(round.remaining_weight_after)}. No automatic runoff.</p>}</details>)}
      </details>}</td></tr>;
    })}</tbody></table></div>
  </section>;
}
