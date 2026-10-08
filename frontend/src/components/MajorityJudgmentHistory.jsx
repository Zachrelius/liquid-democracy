import { GradeDistributions } from './MajorityJudgmentResultsPanel';

export default function MajorityJudgmentHistory({ snapshots, optionsById }) {
  return <section aria-label="Majority Judgment result history" className="space-y-3 p-3">
    <p className="text-sm">Majority Judgment history preserves the initial majority grades and grade distributions. A change to the option set restarts stability observation. Results requiring the committed draw order are not stable.</p>
    {snapshots.map((snapshot, index) => {
      const result = snapshot.method_result;
      const labels = result?.option_labels || Object.fromEntries(Object.entries(optionsById).map(([id, option]) => [id, option.label]));
      return <details key={snapshot.id || index} className="border rounded p-3">
        <summary className="text-sm cursor-pointer">{new Date(snapshot.captured_at).toLocaleString()} — {result?.winner ? labels[result.winner] || result.winner : 'No meaningful result'}{result?.priority_used && ' (draw order needed)'}</summary>
        <div className="mt-3">{result ? <GradeDistributions result={result} labels={labels} /> : <p className="text-sm">Historical method detail unavailable</p>}</div>
      </details>;
    })}
  </section>;
}
