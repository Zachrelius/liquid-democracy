/**
 * IssuancePreview — Phase 90e.
 *
 * Renders the dilution/impact preview for a vote-gated issuance proposal
 * prominently BEFORE the ballot (spec §3.2): what changes, who authorizes, and
 * the dilution line. The `preview` object is the 90d preview-builder output
 * surfaced on ProposalOut.issuance_preview (one source of truth for both the
 * ratification UI and this page). After close it also states whether the
 * authorized change actually executed (honest drift reporting).
 */
export default function IssuancePreview({ preview, executed, status }) {
  if (!preview) return null;
  const d = preview.dilution;
  const unit = (d && d.unit_label) || preview.unit_label || 'shares';
  const closed = status === 'passed' || status === 'failed';
  return (
    <div className="mb-4 rounded-xl border border-indigo-200 bg-indigo-50/60 p-4">
      <div className="flex items-center gap-2 mb-1">
        <span className="text-xs font-semibold uppercase tracking-wide text-indigo-700">
          Share issuance
        </span>
      </div>
      <p className="text-sm text-gray-800 font-medium">{preview.summary}</p>

      {d && (d.outstanding_before != null) && (
        <div className="mt-2 text-sm text-gray-700">
          <div>
            Outstanding: <span className="font-semibold">{Number(d.outstanding_before).toLocaleString()}</span>
            {' → '}
            <span className="font-semibold">
              {Number(d.outstanding_after ?? d.outstanding_after_first_period ?? d.outstanding_before).toLocaleString()}
            </span>{' '}{unit}
            {d.change_pct ? <span className="text-gray-500"> ({d.change_pct})</span> : null}
          </div>
          <p className="text-xs text-gray-500 mt-0.5">
            If you hold {unit}, your proportional stake changes accordingly.
          </p>
          {d.authorized_total != null && (
            <p className="text-xs text-gray-500 mt-0.5">
              Within the authorized cap of {Number(d.authorized_total).toLocaleString()} {unit}.
            </p>
          )}
        </div>
      )}

      {closed && (
        <p className={`mt-2 text-xs font-medium ${executed ? 'text-emerald-700' : 'text-amber-700'}`}>
          {status === 'passed' && executed === true && 'Passed — the change was applied.'}
          {status === 'passed' && executed === false && 'Passed, but the change could not be applied at close (nothing was issued).'}
          {status === 'failed' && 'Did not pass — nothing was issued.'}
        </p>
      )}
    </div>
  );
}
