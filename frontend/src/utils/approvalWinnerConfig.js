// Multi-winner approval selection config helpers.
//
// The backend stores ONE generalized representation on the proposal:
//   approval_winner_config = {
//     min_winners: int >= 0,
//     max_winners: int >= 1 | null,   // null = no cap
//     approval_threshold: float in (0, 1] | null,  // fraction of ballots cast
//   } | null                          // null = legacy single winner
//
// The UI presents four presets (single / top_x / threshold / floor_extras)
// and writes the generalized form. These helpers are shared between the
// creation/edit form (ProposalManagement.jsx) and the results panel
// (ProposalDetail.jsx) so the plain-language phrasing stays identical in
// both places.

export const SINGLE_WINNER_SUMMARY =
  'A single winner — the most-approved option will be adopted.';

// Format a fraction (0-1] as a percent string, trimming float noise
// (0.6 * 100 === 60.00000000000001) to at most one decimal place.
export function formatThresholdPct(fraction) {
  const pct = Math.round(Number(fraction) * 1000) / 10;
  return String(pct);
}

/**
 * Detect which UI preset a stored config matches and return the full
 * form-state shape (mode + per-preset input values, with sensible
 * defaults for the inputs the matched preset doesn't use).
 *
 * Detection order:
 *   null                                  -> 'single'
 *   min > 0, max === min, threshold null  -> 'top_x'
 *   min === 0, max null, threshold set    -> 'threshold'
 *   anything else                         -> 'floor_extras' (generalized
 *     fallback — shows the raw values; '' means null/no-cap/no-threshold)
 */
export function detectApprovalWinnerPreset(config) {
  const defaults = {
    mode: 'single',
    topX: 2,
    thresholdPct: 50,
    floorMin: 1,
    floorMax: '',
    floorPct: 50,
  };
  if (!config || typeof config !== 'object') return defaults;
  const min = config.min_winners ?? 0;
  const max = config.max_winners ?? null;
  const thr = config.approval_threshold ?? null;
  if (thr == null && min >= 1 && max === min) {
    return { ...defaults, mode: 'top_x', topX: min };
  }
  if (thr != null && min === 0 && max == null) {
    return {
      ...defaults,
      mode: 'threshold',
      thresholdPct: Number(formatThresholdPct(thr)),
    };
  }
  return {
    ...defaults,
    mode: 'floor_extras',
    floorMin: min,
    floorMax: max == null ? '' : max,
    floorPct: thr == null ? '' : Number(formatThresholdPct(thr)),
  };
}

/**
 * Build the generalized wire config from form-state. Returns null for
 * the single-winner preset (legacy behavior).
 */
export function buildApprovalWinnerConfig(sel) {
  if (!sel || sel.mode === 'single') return null;
  if (sel.mode === 'top_x') {
    const x = Number(sel.topX);
    return { min_winners: x, max_winners: x, approval_threshold: null };
  }
  if (sel.mode === 'threshold') {
    return {
      min_winners: 0,
      max_winners: null,
      approval_threshold: Number(sel.thresholdPct) / 100,
    };
  }
  // floor_extras
  const hasCap = sel.floorMax !== '' && sel.floorMax != null;
  const hasPct = sel.floorPct !== '' && sel.floorPct != null;
  return {
    min_winners: Number(sel.floorMin),
    max_winners: hasCap ? Number(sel.floorMax) : null,
    approval_threshold: hasPct ? Number(sel.floorPct) / 100 : null,
  };
}

/**
 * Validate form-state, mirroring the backend's rules
 * (schemas._validate_approval_winner_config): min_winners int >= 0,
 * max_winners int >= 1 or empty, threshold percent in (0, 100] or empty,
 * max >= min when both set, and non-vacuous (min > 0 or threshold set).
 * Returns an error string, or null when valid.
 */
export function validateApprovalWinnerSelection(sel) {
  if (!sel || sel.mode === 'single') return null;
  if (sel.mode === 'top_x') {
    const x = Number(sel.topX);
    if (sel.topX === '' || !Number.isInteger(x) || x < 1) {
      return 'Number of winners must be a whole number (at least 1).';
    }
    return null;
  }
  if (sel.mode === 'threshold') {
    const p = Number(sel.thresholdPct);
    if (sel.thresholdPct === '' || Number.isNaN(p) || p < 1 || p > 100) {
      return 'Approval threshold must be between 1% and 100%.';
    }
    return null;
  }
  // floor_extras
  const y = Number(sel.floorMin);
  if (sel.floorMin === '' || !Number.isInteger(y) || y < 0) {
    return 'Guaranteed winners must be a whole number.';
  }
  const hasCap = sel.floorMax !== '' && sel.floorMax != null;
  if (hasCap) {
    const z = Number(sel.floorMax);
    if (!Number.isInteger(z) || z < 1) {
      return 'Total winners cap must be a whole number (at least 1).';
    }
    if (z < y) {
      return 'Total winners cap must be at least the number of guaranteed winners.';
    }
  }
  const hasPct = sel.floorPct !== '' && sel.floorPct != null;
  if (hasPct) {
    const c = Number(sel.floorPct);
    if (Number.isNaN(c) || c < 1 || c > 100) {
      return 'Extras approval must be between 1% and 100%.';
    }
  }
  if (y === 0 && !hasPct) {
    return 'Set at least 1 guaranteed winner or an approval percent for extra winners.';
  }
  return null;
}

/**
 * Plain-language one-liner for a stored (generalized) config. Returns
 * null for a null config — callers render SINGLE_WINNER_SUMMARY (or
 * nothing) for the legacy single-winner case.
 */
export function describeApprovalWinnerRule(config) {
  if (!config || typeof config !== 'object') return null;
  const min = config.min_winners ?? 0;
  const max = config.max_winners ?? null;
  const thr = config.approval_threshold ?? null;
  const minPlural = min === 1 ? '' : 's';
  if (thr == null) {
    // Floor only — max is irrelevant without a threshold; effectively Top N.
    if (min < 1) return null;
    return `Top ${min} most-approved option${minPlural} will be adopted.`;
  }
  const pct = formatThresholdPct(thr);
  if (min === 0) {
    if (max == null) {
      return `Every option approved by at least ${pct}% of ballots will be adopted.`;
    }
    return `Every option approved by at least ${pct}% of ballots will be adopted, up to ${max} total.`;
  }
  if (max == null) {
    return `At least ${min} winner${minPlural} will be seated; additional options that reach ${pct}% approval will also be seated.`;
  }
  return `At least ${min} winner${minPlural} will be seated; up to ${max} total if they reach ${pct}% approval.`;
}

/**
 * Merge tie-resolution picks into the winner set for display. A closed
 * proposal's live tally is recomputed on every results read, so options
 * seated by the close-time tie resolver appear only in the persisted
 * tie_resolution record (and in winner_seats), not in tally.winners.
 */
export function effectiveApprovalWinners(tally) {
  const winners = Array.isArray(tally?.winners) ? [...tally.winners] : [];
  const boundary = new Set(tally?.boundary_tied || []);
  const chosen = Array.isArray(tally?.tie_resolution?.chosen_winners)
    ? tally.tie_resolution.chosen_winners
    : [];
  for (const id of chosen) {
    if (boundary.has(id) && !winners.includes(id)) winners.push(id);
  }
  return winners;
}

// Concise seat-attribution chip copy keyed by the backend's
// winner_seats values.
export const SEAT_CHIP_LABELS = {
  floor: 'guaranteed seat',
  threshold: 'met threshold',
  tie_resolution: 'tie-break',
};
