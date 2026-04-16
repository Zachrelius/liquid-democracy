/**
 * Compact stacked vote tally bar.
 * Props: yes, no, abstain (counts or percents, will be normalised)
 */
export default function VoteBar({ yes = 0, no = 0, abstain = 0, showLabels = true }) {
  const total = yes + no + abstain;
  const yesPct  = total ? (yes  / total) * 100 : 0;
  const noPct   = total ? (no   / total) * 100 : 0;
  const absPct  = total ? (abstain / total) * 100 : 0;

  return (
    <div className="space-y-1">
      <div className="flex h-3 rounded overflow-hidden bg-gray-100">
        {yesPct  > 0 && <div style={{ width: `${yesPct}%`  }} className="bg-[#2D8A56]" />}
        {noPct   > 0 && <div style={{ width: `${noPct}%`   }} className="bg-[#C0392B]" />}
        {absPct  > 0 && <div style={{ width: `${absPct}%`  }} className="bg-[#7F8C8D]" />}
      </div>
      {showLabels && total > 0 && (
        <div className="flex gap-3 text-xs text-gray-500">
          <span className="text-[#2D8A56] font-medium">{yesPct.toFixed(0)}% Yes</span>
          <span>·</span>
          <span className="text-[#C0392B] font-medium">{noPct.toFixed(0)}% No</span>
          <span>·</span>
          <span className="text-gray-500">{absPct.toFixed(0)}% Abstain</span>
        </div>
      )}
    </div>
  );
}
