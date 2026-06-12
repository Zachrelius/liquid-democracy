// Election-aware option display labels (Phase 67 W3).
//
// Election proposals (proposal.is_election) carry one option per
// candidate where `option.label` is the candidate's raw user-id UUID
// (the engine's stable key) and `option.description` is the candidate's
// human display name. Every option-rendering surface must therefore
// show `description` as the primary text for elections — never the
// UUID. Non-election proposals are untouched: `label` is the authored
// display text and `description` stays the optional secondary line.
//
// One rule, used everywhere: description when is_election && description
// present, else label.

export function optionDisplayLabel(proposal, option) {
  if (!option) return '';
  if (proposal?.is_election && option.description) return option.description;
  return option.label ?? '';
}

/**
 * Build an { option_id: display_label } map. `fallbackLabels` is an
 * optional { id: label } map (e.g. tally.option_labels) used for ids
 * that don't appear in proposal.options; for elections the
 * proposal.options display names take precedence over the fallback
 * (which carries the raw UUID labels).
 */
export function optionLabelMap(proposal, fallbackLabels = null) {
  const m = {};
  if (fallbackLabels) {
    Object.entries(fallbackLabels).forEach(([id, lbl]) => {
      if (lbl) m[id] = lbl;
    });
  }
  (proposal?.options || []).forEach((o) => {
    const lbl = optionDisplayLabel(proposal, o);
    if (lbl && (proposal?.is_election || !m[o.id])) m[o.id] = lbl;
  });
  return m;
}

/**
 * Lookup-function form of optionLabelMap: returns (id) => display label,
 * falling back to the raw id when unknown.
 */
export function optionLabelOf(proposal, fallbackLabels = null) {
  const m = optionLabelMap(proposal, fallbackLabels);
  return (id) => m[id] ?? id;
}
