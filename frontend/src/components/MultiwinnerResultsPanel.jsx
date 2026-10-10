import { formatExactCount } from '../utils/ratedBallot';
import { MULTIWINNER_COPY, votingMethodLabel, MAJORITY_JUDGMENT_GRADES } from '../utils/votingMethods';

export default function MultiwinnerResultsPanel({ tally, proposal }) {
  const result = tally?.method_result;
  if (!result) return <p>Results are unavailable.</p>;
  const labels = result.option_labels || Object.fromEntries((proposal.options || []).map(o => [o.id, o.label]));
  const label = id => labels[id] || id;
  const selected = new Set(result.winners || []);
  const official = result.finalized && result.quorum_met;
  const isBloc = proposal.voting_method === 'star';
  const isGrade = proposal.voting_method === 'majority_judgment';
  const isRanked = proposal.voting_method === 'ranked_pairs';
  const graphIds = Object.keys(result.pairwise || {});
  const lockedEdges = new Set((result.locked_edges || []).map(e => `${e.winner}:${e.loser}`));
  const aggregates = isRanked ? result.ranked_weights : isGrade ? result.grade_histograms : result.scores;
  const grade = code => code == null ? 'No grades' : MAJORITY_JUDGMENT_GRADES[Number(code)] || 'Unavailable';
  const ordered = [...(result.ranked_order || []), ...Object.keys(aggregates || {}).filter(id => !(result.ranked_order || []).includes(id))];
  return <section aria-label={`${votingMethodLabel(proposal.voting_method)} multiple-winner results`} className="space-y-4">
    <h3 className="font-semibold">{isBloc ? 'Bloc STAR' : votingMethodLabel(proposal.voting_method)}: multiple winners</h3>
    <p className="text-sm">{MULTIWINNER_COPY[proposal.voting_method]}</p>
    <p className="font-medium">{official ? 'Selected' : 'Provisional selections'}: {(result.winners || []).map(label).join(', ') || 'None'}.</p>
    <p className="text-sm">{formatExactCount(result.filled_count)} of {formatExactCount(result.requested_count)} places selected.</p>
    {Number(result.unfilled_count) > 0 && <p className="text-sm text-amber-800">{formatExactCount(result.unfilled_count)} unfilled: {isRanked && result.no_result_reason === 'no_strict_preferences' ? 'no strict preference among eligible options.' : 'no remaining supported options.'} {isRanked ? 'Wholly unranked options cannot fill a place; all eligible options tied with each other produce no result.' : isGrade ? 'Options graded only Reject cannot fill a place; a Reject median can still have positive support.' : 'Zero total scores cannot fill a place.'}</p>}
    {!result.quorum_met && <p className="text-sm text-amber-800">Quorum not met. No official winners or office grants can be finalized.</p>}
    {result.selection_boundary_tie && <p className="text-sm">{isRanked ? 'Multiple available source nodes at the selection boundary use the committed candidate priority in the same fixed graph.' : isGrade ? 'Equal majority grades at the selection boundary use repeated median removal on original distributions, then committed priority only for identical distributions.' : 'Equal totals at the selection boundary use the committed candidate priority.'} The winner count does not expand.</p>}
    {result.priority_used && <p className="text-xs text-amber-800">A tie consulted committed priority. This result cannot satisfy Stable Result Required.</p>}
    <div className="overflow-x-auto"><table className="w-full text-left text-sm">
      <caption className="text-left font-medium">{isRanked ? 'Collective order from one locked graph' : isGrade ? 'Original majority-grade ranking' : isBloc ? 'Original total scores (runoffs decide selections)' : 'Ranked total points'}</caption><thead><tr><th scope="col">Option</th><th scope="col">{isRanked ? 'Position' : isGrade ? 'Majority grade' : 'Points'}</th><th scope="col">Selection</th></tr></thead>
      <tbody>{ordered.map(id => <tr key={id} className="border-t"><th scope="row" className="py-2 pr-2 font-normal break-words">{label(id)}</th><td>{isRanked ? (result.ranked_order?.includes(id) ? result.ranked_order.indexOf(id)+1 : '—') : isGrade ? grade(result.majority_grades?.[id]) : formatExactCount(result.scores?.[id])}</td><td>{selected.has(id) ? official ? 'Selected' : 'Provisional' : (isRanked ? BigInt(result.ranked_weights?.[id] || 0) === 0n : isGrade ? !result.supported_options?.includes(id) : BigInt(result.scores?.[id] || 0) === 0n) ? 'Unsupported' : ''}</td></tr>)}</tbody>
    </table></div>
    {isRanked && <div className="space-y-3">
      <p className="text-sm">One matrix and one acyclic graph determine the entire order. Select a node with no incoming locked defeat, remove its outgoing edges, and repeat. Multiple source nodes use committed priority. Victories are never recomputed between selections.</p>
      <details><summary className="text-sm cursor-pointer">Victories and locking decisions ({(result.locked_edges || []).length} locked, {(result.skipped_edges || []).length} skipped)</summary>
        <ol className="text-xs list-decimal pl-4 space-y-2">{(result.ordered_victories || []).map((edge,i) => <li key={i}>{label(edge.winner)} over {label(edge.loser)}: margin {formatExactCount(edge.margin)}, support {formatExactCount(edge.support)}. {lockedEdges.has(`${edge.winner}:${edge.loser}`) ? 'Locked' : 'Skipped: would create a cycle'}.</li>)}</ol>
      </details>
      <details><summary className="text-sm cursor-pointer">Pairwise matrix and source ties</summary>
        <div className="overflow-x-auto"><table className="text-xs text-left w-full"><caption>Preferences for the row over the column; equal ranks contribute to neither.</caption><thead><tr><th scope="col">Preferred over</th>{graphIds.map(id => <th key={id} scope="col">{label(id)}</th>)}</tr></thead><tbody>{graphIds.map(a => <tr key={a}><th scope="row">{label(a)}</th>{graphIds.map(b => <td key={b}>{a===b ? '—' : formatExactCount(result.pairwise[a][b])}</td>)}</tr>)}</tbody></table></div>
        {(result.source_ties || []).map((row,i) => <p key={i} className="text-xs">Position {formatExactCount(row.position)}: source options {row.pool.map(label).join(', ')}; committed priority selected {label(row.selected)}.</p>)}
        {(result.tie_trace || []).filter(row => row.stage==='edge_priority').map((row,i) => <p key={i} className="text-xs">Equal-strength victories: margin {formatExactCount(row.margin)}, support {formatExactCount(row.support)}; committed priority ordered the edges.</p>)}
      </details>
    </div>}
    {isGrade && <details><summary className="text-sm cursor-pointer">Original grade distributions and comparison details</summary>
      <p className="text-sm">Grades are ordered descriptions. Numeric averages do not decide this result. Each comparison starts from the original distribution.</p>
      {ordered.map(id => <p key={id} className="text-xs mt-2">{label(id)}: {(result.grade_histograms[id] || []).map((n,g) => `${MAJORITY_JUDGMENT_GRADES[g]} ${formatExactCount(n)}`).join('; ')}.</p>)}
      {(result.comparisons || []).map((row,i) => <details key={i}><summary className="text-xs cursor-pointer">Comparison {i+1}: {row.pool.map(label).join(' / ')}</summary><p className="text-xs">Higher: {label(row.winner)}.</p>{row.tie_trace.map((event,j) => <p className="text-xs" key={j}>{event.stage.replaceAll('_',' ')}. {event.removed_per_candidate != null && <>Temporary grades removed per candidate: {formatExactCount(event.removed_per_candidate)}. </>}{event.majority_grades && Object.entries(event.majority_grades).map(([id,g]) => `${label(id)} ${grade(g)}`).join('; ')}</p>)}</details>)}
    </details>}
    {isBloc && <div className="space-y-3"><h4 className="font-medium">Selection rounds</h4>{(result.rounds || []).map((round,i) => <details key={i} open><summary className="text-sm cursor-pointer">Round {i+1}: {label(round.winner)}</summary>
      <p className="text-sm">Remaining pool: {round.pool.map(label).join(', ')}.</p>
      {round.competitive_runoff ? <><p className="text-sm">Finalists: {round.finalists.map(label).join(', ')}.</p><p className="text-sm">Runoff: {Object.entries(round.runoff).map(([id,n]) => `${label(id)} ${formatExactCount(n)}`).join('; ')}. Equal preference: {formatExactCount(round.equal_preference)}.</p></> : <p className="text-sm">One supported option remained; selected without a competitive runoff.</p>}
      <details><summary className="text-xs cursor-pointer">Scores and tie stages</summary><p className="text-xs">{Object.entries(round.scores).map(([id,n]) => `${label(id)} ${formatExactCount(n)}`).join('; ')}</p>{round.tie_trace.map((event,j) => <p key={j} className="text-xs">{event.stage.replaceAll('_',' ')}: {(event.pool || []).map(label).join(', ')}. {event.values && Object.entries(event.values).map(([id,n]) => `${label(id)} ${formatExactCount(n)}`).join('; ')}</p>)}</details>
    </details>)}</div>}
    <p className="text-xs text-gray-600">Participating people: {formatExactCount(result.participating_headcount)}. Ballots cast ({tally.weighted ? tally.unit_label || 'voting shares' : 'votes'}): {formatExactCount(result.total_ballots_cast)}. Abstentions: {formatExactCount(result.total_abstain)}.</p>
    <details><summary className="text-sm cursor-pointer">Auditable counting rules</summary>
      <p className="text-xs break-all mt-2">Rule: {proposal.voting_rules?.rule_id}. Draw commitment: {proposal.voting_rules?.tie_commitment}.</p>
      {result.tie_seed && <p className="text-xs break-all">Revealed seed: {result.tie_seed}</p>}
    </details>
  </section>;
}
