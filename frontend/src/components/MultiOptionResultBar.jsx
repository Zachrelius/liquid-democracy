/**
 * MultiOptionResultBar — per-option horizontal bars for approval / RCV / STV
 * proposals on the proposals list (summary card) view.
 *
 * Props:
 *   options: Array<{ label: string, percentage: number, isWinner?: boolean }>
 *     Bars are rendered in the order received — the caller is responsible for
 *     sorting (typically count-descending). `percentage` is the raw width
 *     (0..100). The component does NOT normalize: approval-voting bars
 *     legitimately sum to >100% because each voter approves multiple options.
 *   maxBars?: number — optional cap to keep the card compact. When more
 *     options exist than maxBars, a "+N more" footer is shown. Defaults to
 *     no cap.
 *
 * Visual conventions: winner rows get the dark-navy emphasis used elsewhere
 * in the app (RCVSankeyChart final-column highlight, #1B3A5C).
 */
export default function MultiOptionResultBar({ options, maxBars }) {
  if (!Array.isArray(options) || options.length === 0) return null;

  const visible = typeof maxBars === 'number' ? options.slice(0, maxBars) : options;
  const overflow = typeof maxBars === 'number' ? options.length - visible.length : 0;

  return (
    <div className="space-y-1.5">
      {visible.map((o, i) => {
        const pct = Math.max(0, Math.min(100, Number(o.percentage) || 0));
        const isWinner = !!o.isWinner;
        return (
          <div key={`${o.label}-${i}`} className="space-y-0.5">
            <div className="flex items-baseline justify-between gap-3 text-xs">
              <span
                className={isWinner ? 'text-[#1B3A5C] font-semibold' : 'text-gray-700'}
                title={o.label}
              >
                {o.label}
              </span>
              <span
                className={isWinner ? 'text-[#1B3A5C] font-semibold tabular-nums' : 'text-gray-500 tabular-nums'}
              >
                {pct.toFixed(0)}%
              </span>
            </div>
            <div
              className={`h-2 rounded overflow-hidden bg-gray-100 ${
                isWinner ? 'ring-1 ring-[#1B3A5C]' : ''
              }`}
            >
              <div
                style={{ width: `${pct}%` }}
                className={isWinner ? 'h-full bg-[#1B3A5C]' : 'h-full bg-[#2E75B6]'}
              />
            </div>
          </div>
        );
      })}
      {overflow > 0 && (
        <p className="text-xs text-gray-400">+{overflow} more option{overflow === 1 ? '' : 's'}</p>
      )}
    </div>
  );
}
