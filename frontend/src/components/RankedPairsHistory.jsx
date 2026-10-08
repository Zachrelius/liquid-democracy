import { formatExactCount } from '../utils/ratedBallot';

export default function RankedPairsHistory({ snapshots, optionsById }) {
  return <section aria-label="Ranked Pairs result history" className="space-y-3 p-3">
    <p className="text-sm">Ranked Pairs history records the winner and head-to-head locking decisions. A change to the option set restarts stability observation. Results that require the committed draw order are not stable.</p>
    <div className="overflow-x-auto"><table className="text-xs text-left w-full">
      <caption className="text-left font-medium mb-2">Recorded Ranked Pairs snapshots</caption>
      <thead><tr><th scope="col">Time</th><th scope="col">Leader</th><th scope="col">Head-to-head detail</th></tr></thead>
      <tbody>{snapshots.map((snapshot, index) => {
        const result = snapshot.method_result;
        const label = id => result?.option_labels?.[id] || optionsById[id]?.label || id;
        return <tr className="border-t align-top" key={snapshot.id || index}>
          <td className="p-2">{new Date(snapshot.captured_at).toLocaleString()}</td>
          <td className="p-2">{result?.winner ? label(result.winner) : 'No meaningful result'}{result?.priority_used && ' (draw order needed)'}</td>
          <td className="p-2">{result ? <details><summary className="cursor-pointer">View exact margins and support</summary>
            <ul className="space-y-1 mt-2">{(result.ordered_victories || []).map((edge, edgeIndex) => <li key={edgeIndex}>{label(edge.winner)} over {label(edge.loser)}: margin {formatExactCount(edge.margin)}, support {formatExactCount(edge.support)}.</li>)}</ul>
            <p className="mt-2">Locked: {(result.locked_edges || []).map(edge => `${label(edge.winner)} over ${label(edge.loser)}`).join('; ') || 'None'}.</p>
            <p>Skipped to avoid cycles: {(result.skipped_edges || []).map(edge => `${label(edge.winner)} over ${label(edge.loser)}`).join('; ') || 'None'}.</p>
          </details> : 'Historical method detail unavailable'}</td>
        </tr>;
      })}</tbody>
    </table></div>
  </section>;
}
