// Shared utilities for VoteFlowGraph and its method-specific sub-components.
// Phase 7B: extracted from the original binary-only VoteFlowGraph so both
// BinaryVoteFlowGraph and OptionAttractorVoteFlowGraph share node sizing,
// edge dedup, marker generation, and zoom-fit logic.

export const VOTE_COLORS = {
  yes: '#2D8A56',
  no: '#C0392B',
  abstain: '#7F8C8D',
  null: '#BDC3C7',
};

export const ZONE_COLORS = {
  yes: 'rgba(45, 138, 86, 0.06)',
  no: 'rgba(192, 57, 43, 0.06)',
  abstain: 'rgba(127, 140, 141, 0.06)',
};

// Per-option palette for option-attractor layouts. Picked from the
// existing Tailwind palette + a few accents that read distinctly on white.
export const OPTION_PALETTE = [
  '#2E75B6', // accent blue
  '#1B3A5C', // primary navy
  '#2D8A56', // green
  '#C0392B', // red
  '#F39C12', // orange (current-user gold)
  '#8E44AD', // purple
  '#16A085', // teal
  '#D35400', // dark orange
  '#34495E', // slate
  '#E91E63', // pink
];

export function nodeRadius(d) {
  if (d.type === 'option') {
    // Option attractors get a fixed, prominent size that scales slightly
    // with how many ballots picked them so popular options read as bigger.
    const base = 14;
    const popularity = (d.approval_count || 0) + (d.first_pref_count || 0);
    return Math.min(28, base + Math.sqrt(popularity) * 1.5);
  }
  if (d.type === 'non_voter') return 4;
  return Math.max(6, Math.min(24, 6 + (d.total_vote_weight || 1) * 2.5));
}

// Deduplicate edges by source-target pair (keep first occurrence).
export function dedupeEdges(edges) {
  const seen = new Set();
  const out = [];
  for (const e of edges) {
    const k = `${e.source}-${e.target}`;
    if (!seen.has(k)) {
      seen.add(k);
      out.push(e);
    }
  }
  return out;
}

// Build a map of unique topic colors for arrow markers.
export function uniqueMarkerColors(edges) {
  return new Set(edges.map((e) => e.topic_color || '#95a5a6'));
}

export function markerId(color) {
  return `arrow-${color.replace('#', '')}`;
}

// Compute optionWeights for a voter ballot given the proposal's voting_method.
// Returns array of { optionId, weight } pairs.
//
// Approval: every approved option -> weight 1.0
// RCV: rank 1 -> 1.0, rank 2 -> 0.66, rank 3 -> 0.33, rank >= 4 -> floor 0.1
// Linear decay chosen for interpretability per spec Decision 3. The 0.1 floor
// keeps lower preferences visible without dominating layout.
export function computeOptionWeights(ballot, votingMethod) {
  if (!ballot) return [];
  if (votingMethod === 'approval') {
    if (!Array.isArray(ballot.approvals)) return [];
    return ballot.approvals.map((id) => ({ optionId: id, weight: 1.0 }));
  }
  if (votingMethod === 'ranked_choice') {
    if (!Array.isArray(ballot.ranking)) return [];
    return ballot.ranking.map((id, idx) => {
      let w;
      if (idx === 0) w = 1.0;
      else if (idx === 1) w = 0.66;
      else if (idx === 2) w = 0.33;
      else w = 0.1; // floor for ranks 4+
      return { optionId: id, weight: w };
    });
  }
  return [];
}

// Color for an option's pinned node — cycles through palette by display_order.
export function colorForOption(option) {
  const idx = (option.display_order ?? 0) % OPTION_PALETTE.length;
  return OPTION_PALETTE[idx];
}

// Compute fit-to-bounds zoom transform for a list of laid-out nodes.
// Returns { scale, tx, ty } or null if no positioned nodes.
export function fitTransform(positionedNodes, width, height, paddingPx = 40, maxScale = 1.5) {
  let minX = Infinity;
  let maxX = -Infinity;
  let minY = Infinity;
  let maxY = -Infinity;
  for (const n of positionedNodes) {
    if (n.x == null || n.y == null) continue;
    const r = nodeRadius(n);
    if (n.x - r < minX) minX = n.x - r;
    if (n.x + r > maxX) maxX = n.x + r;
    if (n.y - r < minY) minY = n.y - r;
    if (n.y + r > maxY) maxY = n.y + r;
  }
  if (!isFinite(minX)) return null;
  const bw = maxX - minX + paddingPx * 2;
  const bh = maxY - minY + paddingPx * 2;
  const scale = Math.min(width / bw, height / bh, maxScale);
  const tx = width / 2 - scale * ((minX + maxX) / 2);
  const ty = height / 2 - scale * ((minY + maxY) / 2);
  return { scale, tx, ty };
}

// Truncate option labels for display on pinned nodes.
export function truncateLabel(label, max = 18) {
  if (!label) return '';
  return label.length > max ? label.slice(0, max - 1) + '…' : label;
}
