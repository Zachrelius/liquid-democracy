/**
 * Phase 20 F2 — Stable Result Required status panel for ProposalDetail.
 *
 * Renamed from SustainedMajorityPanel and rewritten against the new
 * StableResultStatus payload shape (backend B3). The shipped Phase 8
 * panel rendered floor-breached banner / approaching-floor banner /
 * support-vs-floor bar / historical chart — all of those are gone in
 * Phase 20 because the floor mechanic itself is removed.
 *
 * The new panel renders:
 *   1. "Stable Result Required" badge whenever active=true.
 *   2. Stable-window timestamp display (start / end / duration).
 *   3. "In stable window" banner when in_stable_window=true.
 *   4. "In extension" banner when in_extension=true, with explanation of
 *      sliding-window close behavior.
 *   5. Extension-budget indicator: a horizontal bar showing
 *      extension_budget_used_seconds / extension_budget_total_seconds
 *      plus human-readable "X used of Y available" caption.
 *   6. Most-recent destabilization timestamp when present.
 *
 * The backend preserves the JSON key `sustained_majority` on the results
 * payload for one pass for backwards compat; we read it from there.
 */

function formatDurationSeconds(seconds) {
  if (seconds == null || Number.isNaN(seconds) || seconds < 0) return '—';
  const s = Math.round(seconds);
  if (s < 60) return `${s} second${s === 1 ? '' : 's'}`;
  if (s < 3600) {
    const m = Math.round(s / 60);
    return `${m} minute${m === 1 ? '' : 's'}`;
  }
  if (s < 86400) {
    const h = Math.floor(s / 3600);
    const m = Math.round((s % 3600) / 60);
    if (m === 0) return `${h} hour${h === 1 ? '' : 's'}`;
    return `${h}h ${m}m`;
  }
  const d = Math.floor(s / 86400);
  const h = Math.round((s % 86400) / 3600);
  if (h === 0) return `${d} day${d === 1 ? '' : 's'}`;
  return `${d}d ${h}h`;
}

function formatTimestamp(iso) {
  if (!iso) return null;
  try {
    const dt = new Date(iso);
    if (Number.isNaN(dt.getTime())) return null;
    return dt.toLocaleString([], {
      month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit',
    });
  } catch {
    return null;
  }
}

export default function StableResultPanel({ tally }) {
  // Backend backwards-compat alias: the JSON key is still
  // `sustained_majority` for one pass. See backend/sustained_majority_service.py
  // build_status. Switch to `stable_result` when the backend follow-up pass
  // renames the payload key.
  const sr = tally?.sustained_majority;
  if (!sr || !sr.active) return null;

  const stableStartLabel = formatTimestamp(sr.stable_window_starts_at);
  const votingEndLabel = formatTimestamp(sr.voting_end);
  const lastDestabilizationLabel = formatTimestamp(sr.last_destabilization_at);

  const budgetTotal = sr.extension_budget_total_seconds ?? 0;
  const budgetUsed = sr.extension_budget_used_seconds ?? 0;
  const budgetRemaining = sr.extension_budget_remaining_seconds
    ?? Math.max(0, budgetTotal - budgetUsed);
  // Bar fill % — guard against div-by-zero when max_extension_fraction
  // is 0 (in which case the bar should render fully gray since no
  // extensions are ever granted).
  const usedPct = budgetTotal > 0
    ? Math.max(0, Math.min(100, (budgetUsed / budgetTotal) * 100))
    : 0;

  // Stable-window duration: derive from the start/end pair if both
  // present; otherwise fall back to fraction * (voting_end - voting_start)
  // when the schema gives us enough to compute. The backend doesn't
  // surface voting_start in this payload, so when stable_window_starts_at
  // is null we just hide the duration line.
  let stableWindowDurationLabel = null;
  if (sr.stable_window_starts_at && sr.voting_end) {
    try {
      const start = new Date(sr.stable_window_starts_at).getTime();
      const end = new Date(sr.voting_end).getTime();
      if (!Number.isNaN(start) && !Number.isNaN(end) && end > start) {
        stableWindowDurationLabel = formatDurationSeconds((end - start) / 1000);
      }
    } catch { /* ignore */ }
  }

  return (
    <div className="space-y-3">
      <div className="bg-blue-50 border border-blue-200 rounded-xl p-4 space-y-3">
        <div className="flex items-baseline justify-between gap-3">
          <div className="flex items-center gap-2">
            <span className="inline-flex items-center text-xs bg-white text-[var(--brand-accent)] border border-blue-200 px-2 py-0.5 rounded font-medium">
              Stable Result Required
            </span>
            {sr.in_extension && (
              <span className="inline-flex items-center text-xs bg-amber-50 text-amber-700 border border-amber-200 px-2 py-0.5 rounded font-medium">
                In extension
              </span>
            )}
            {sr.in_stable_window && !sr.in_extension && (
              <span className="inline-flex items-center text-xs bg-green-50 text-green-700 border border-green-200 px-2 py-0.5 rounded font-medium">
                In stable window
              </span>
            )}
          </div>
          <a
            href="/help/stable-result"
            target="_blank"
            rel="noreferrer"
            className="text-xs text-[var(--brand-accent)] hover:underline shrink-0"
          >
            What is this?
          </a>
        </div>

        {/* Stable window timestamps */}
        {(stableStartLabel || votingEndLabel) && (
          <div className="text-xs text-gray-700">
            <span className="text-gray-500">Stable window:</span>{' '}
            <span className="font-medium">{stableStartLabel || '—'}</span>
            {votingEndLabel && (
              <>
                {' '}—{' '}
                <span className="font-medium">{votingEndLabel}</span>
              </>
            )}
            {stableWindowDurationLabel && (
              <span className="text-gray-500"> ({stableWindowDurationLabel})</span>
            )}
          </div>
        )}

        {/* In-stable-window banner */}
        {sr.in_stable_window && !sr.in_extension && (
          <div className="bg-white border border-green-200 rounded-lg p-3 text-xs text-gray-700">
            <p>
              <strong>You&apos;re in the stable window.</strong> The result
              must hold until close
              {votingEndLabel && <> at <strong>{votingEndLabel}</strong></>}.
              If the result destabilizes — binary support drops below the
              pass threshold, or a multi-option winner gets displaced — voting
              is automatically extended to give voters time to react.
            </p>
          </div>
        )}

        {/* In-extension banner */}
        {sr.in_extension && (
          <div className="bg-white border border-amber-200 rounded-lg p-3 text-xs text-gray-700">
            <p>
              <strong>Voting has been extended.</strong> Voting will close
              as soon as the result has been stable for the stable window&apos;s
              duration
              {stableWindowDurationLabel && <> ({stableWindowDurationLabel})</>}
              {votingEndLabel && (
                <>, or at <strong>{votingEndLabel}</strong> if stability
                isn&apos;t re-established</>
              )}.
            </p>
          </div>
        )}

        {/* Extension budget indicator */}
        <div className="space-y-1 pt-2 border-t border-blue-100">
          <div className="flex items-baseline justify-between gap-2">
            <span className="text-xs text-gray-600 font-medium">Extension budget</span>
            <span className="text-xs text-gray-500">
              {formatDurationSeconds(budgetUsed)} used of{' '}
              {formatDurationSeconds(budgetTotal)} available
            </span>
          </div>
          <div
            className="relative h-2 bg-gray-100 rounded-full overflow-hidden"
            title={`Extension time used: ${formatDurationSeconds(budgetUsed)} of ${formatDurationSeconds(budgetTotal)} available`}
          >
            <div
              className="absolute top-0 left-0 h-full bg-[var(--brand-accent)] rounded-full transition-all"
              style={{ width: `${usedPct}%` }}
            />
          </div>
          {budgetRemaining > 0 ? (
            <p className="text-[11px] text-gray-400">
              {formatDurationSeconds(budgetRemaining)} remaining for further
              extensions if needed.
            </p>
          ) : (
            <p className="text-[11px] text-gray-400">
              Extension budget exhausted. The proposal will close at its
              current deadline regardless of further destabilization.
            </p>
          )}
        </div>

        {/* Most-recent destabilization (single timestamp; full history would
            require an audit-log endpoint that doesn't exist here). */}
        {lastDestabilizationLabel && (
          <div className="text-[11px] text-gray-500 pt-2 border-t border-blue-100">
            Last destabilization: <span className="font-medium text-gray-600">{lastDestabilizationLabel}</span>
            {(sr.extension_count ?? 0) > 0 && (
              <span> · Extensions so far: <span className="font-medium text-gray-600">{sr.extension_count}</span></span>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
