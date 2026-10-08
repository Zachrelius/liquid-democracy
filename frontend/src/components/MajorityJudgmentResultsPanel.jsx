import { MAJORITY_JUDGMENT_GRADES } from '../utils/votingMethods';
import { gradeDistributionWidths, gradeLabel } from '../utils/majorityJudgment';
import { formatExactCount } from '../utils/ratedBallot';

const gradeColors = ['bg-red-800', 'bg-orange-600', 'bg-amber-400', 'bg-lime-500', 'bg-green-600', 'bg-blue-700'];
const reasons = {
  fewer_than_two_options: 'At least two options are required.',
  no_positive_weight_preferences: 'No positive-weight, non-abstaining ballots were submitted.',
  all_bottom_ratings: 'No option received a grade above Reject.',
  quorum_not_met: 'Participation did not meet quorum.',
};

export function GradeDistributions({ result, labels = {} }) {
  return <div className="space-y-4">
    <p className="text-xs text-gray-600">Original grade distributions of non-abstaining voting weight. Omitted options receive Reject. Tiebreak comparisons do not change these distributions.</p>
    <ul className="flex flex-wrap gap-x-3 gap-y-1 text-xs" aria-label="Grade colors">{MAJORITY_JUDGMENT_GRADES.map((label, index) => <li key={label} className="flex items-center gap-1"><span aria-hidden="true" className={`inline-block h-3 w-3 ${gradeColors[index]}`} />{label}</li>)}</ul>
    {Object.entries(result.grade_histograms || {}).map(([id, histogram]) => {
      const widths = gradeDistributionWidths(histogram);
      return <div key={id} className="border rounded-lg p-3 space-y-2">
        <h4 className="font-medium text-sm break-words">{labels[id] || id}</h4>
        <p className="text-sm">Majority grade: <strong>{result.majority_grades?.[id] == null ? 'No submitted grades' : gradeLabel(result.majority_grades[id])}</strong></p>
        <div role="img" aria-label={`${labels[id] || id} grade distribution: ${histogram.map((count, index) => `${MAJORITY_JUDGMENT_GRADES[index]} ${formatExactCount(count)}`).join(', ')}`} className="flex h-5 w-full overflow-hidden rounded bg-gray-100">
          {widths.map((width, index) => <span key={index} aria-hidden="true" className={gradeColors[index]} style={{ width: `${width}%` }} />)}
        </div>
        <details><summary className="text-xs cursor-pointer">Exact grade counts</summary><ul className="text-xs grid grid-cols-2 gap-2 mt-2">{histogram.map((count, index) => <li key={index}>{MAJORITY_JUDGMENT_GRADES[index]}: {formatExactCount(count)}</li>)}</ul></details>
      </div>;
    })}
  </div>;
}

export default function MajorityJudgmentResultsPanel({ tally, proposal }) {
  const result = tally?.method_result;
  if (!result) return <p className="text-sm text-gray-500">Majority Judgment results are not available.</p>;
  const labels = result.option_labels || Object.fromEntries((proposal.options || []).map(option => [option.id, option.label]));
  const label = id => labels[id] || id;
  const closed = result.finalized === true || ['passed', 'failed', 'closed'].includes(proposal.status);
  const unit = tally.weighted ? tally.unit_label || 'voting shares' : 'votes';
  return <section className="space-y-4" aria-label="Majority Judgment results">
    <h3 className="text-sm font-semibold uppercase tracking-wide">Majority Judgment results</h3>
    {result.winner && <p className="font-semibold">{closed && result.quorum_met ? 'Winner' : 'Provisional leader'}: {label(result.winner)}</p>}
    {result.no_result_reason && <p className="text-sm text-amber-800">No finalized winner: {reasons[result.no_result_reason] || result.no_result_reason.replaceAll('_', ' ')}</p>}
    {!result.quorum_met && <p className="text-sm text-amber-800">Quorum not met. Any displayed tally is provisional.</p>}
    <p className="text-sm">The highest majority grade leads. For an even amount of voting weight, the lower middle grade is used. Tied grades are compared by repeatedly removing one unit of each tied option's current median grade until they separate.</p>
    <GradeDistributions result={result} labels={labels} />
    <div className="text-xs space-y-1">
      <div>Participating people: {formatExactCount(result.participating_headcount)}</div>
      <div>Eligible people: {formatExactCount(result.eligible_headcount)}</div>
      <div>Ballots cast ({unit}): {formatExactCount(result.total_ballots_cast)}</div>
      <div>Abstentions ({unit}): {formatExactCount(result.total_abstain)}</div>
    </div>
    {result.priority_used && <p className="text-xs text-amber-800">Identical grade distributions required the committed draw order. {closed ? 'The recorded outcome preserves that draw.' : 'This result is provisional and cannot satisfy Stable Result Required.'}</p>}
    {!!result.tie_trace?.length && <details><summary className="text-sm cursor-pointer">How tied majority grades were compared</summary><p className="text-xs mt-2">The following comparison steps leave the original distributions and displayed majority grades intact.</p><ol className="text-xs list-decimal pl-4 mt-2 space-y-2">{result.tie_trace.map((stage, index) => <li key={index}>{stage.stage === 'median_removal' ? <>
      Compared {(stage.pool || []).map(label).join(', ')} after removing {formatExactCount(stage.removed_per_candidate)} median units per option.
      <ul>{Object.entries(stage.majority_grades || {}).map(([id, grade]) => <li key={id}>{label(id)}: {gradeLabel(grade)}</li>)}</ul>
      Still tied or leading: {(stage.remaining_candidates || []).map(label).join(', ')}.
    </> : <>Identical distributions: used the committed draw order among {(stage.pool || []).map(label).join(', ')}.</>}</li>)}</ol></details>}
    {proposal.voting_rules?.tie_commitment && <details><summary className="text-xs cursor-pointer">Auditable voting rules</summary><p className="text-xs break-all mt-2">Rule: {proposal.voting_rules.rule_id}<br />Draw commitment: {proposal.voting_rules.tie_commitment}</p>{result.tie_seed && <p className="text-xs break-all mt-2">Revealed seed: {result.tie_seed}</p>}</details>}
  </section>;
}
