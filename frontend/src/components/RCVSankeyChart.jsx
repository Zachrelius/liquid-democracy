import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import * as d3 from 'd3';
import { sankey as d3Sankey, sankeyLinkHorizontal } from 'd3-sankey';
import { colorForOption } from './voteFlowGraphUtils';

/**
 * RCVSankeyChart — Phase 7C round-by-round elimination Sankey for RCV/STV.
 *
 * Renders a column per round; each column has one slab per option still in
 * the running, sized by the option's count for that round. Links between
 * consecutive columns represent vote flow:
 *   - Carry-forward: the bulk of an option's count in round r flows from
 *     option-O-in-round-r to option-O-in-round-r+1.
 *   - Transfer: gains shown in round r+1's transfer_breakdown flow from the
 *     round r `transferred_from` option's slab to the gaining option's slab.
 *
 * STV note: when an option is elected and surplus transfers forward, the
 * transfer shows up via transfer_breakdown the same way; we render it
 * identically. Eliminated options have no outgoing carry-forward link
 * (their count drops to 0 in subsequent rounds).
 *
 * If round counts can't be reconciled (sum mismatch beyond rounding), we
 * fall through gracefully — render whatever we can, never throw. Fractional
 * counts (STV) are normal.
 *
 * Color consistency: all node colors come from colorForOption() so each
 * option has the same color across the network graph above and the Sankey
 * below.
 */

const ROUND_LABEL_PX = 30;
const ELIM_LABEL_PX = 18;
const PADDING = { top: 50, right: 16, bottom: 16, left: 16 };
const NODE_WIDTH = 15;
const NODE_PADDING = 10;
const RECONCILE_TOLERANCE = 0.01; // STV fractional rounding tolerance
const FLOAT_TOLERANCE = 1e-6; // tighter tolerance for "did this option drop?"
const HEIGHT = 360;

// Phase 7C.1: synthetic column indices used by Initial / Final nodes. They
// live OUTSIDE the rounds[] index space so we can render them as their own
// columns at the leftmost and rightmost ends of the Sankey.
const INITIAL_COL = -1;
// FINAL_COL is rounds.length (computed at use-site).

// Phase 7C.2: synthetic exhausted-ballot sink. Renders as a muted node in any
// column where the round-to-round transfer leaves volume unaccounted for
// (ballots whose remaining preferences are all already eliminated/elected).
const EXHAUSTED_OPT_ID = '__exhausted__';
const EXHAUSTED_COLOR = '#9CA3AF'; // muted gray, matches voter→option arrow color from 7B.1

function nodeKey(roundIdx, optionId) {
  // roundIdx may be -1 (Initial) or rounds.length (Final). String-keying
  // handles those uniformly.
  return `r${roundIdx}::${optionId}`;
}

/**
 * Derives the visible column list from observed option_counts transitions.
 * Returns an array of { rawRoundIdx, electedNames, eliminatedNames } for
 * rounds that have at least one observable event (election by quota crossing or
 * elimination by count drop to zero). Rounds with no event are omitted —
 * collapse no-event rounds, pyrankvote bundles events unevenly.
 *
 * rawRoundIdx maps back to tally.rounds[r].option_counts for slab math.
 *
 * quota: the election threshold (H-B = totalBallots / (numWinners + 1)).
 * For IRV, numWinners = 1, so quota = totalBallots / 2.
 */
export function deriveDisplayColumns(tally) {
  if (!tally || !Array.isArray(tally.rounds) || tally.rounds.length === 0) return [];
  const rounds = tally.rounds;
  const totalBallots = tally.total_ballots_cast || 0;
  const numWinners = tally.num_winners || 1;
  const quota = totalBallots > 0 ? totalBallots / (numWinners + 1) : Infinity;

  const crossedQuota = new Set(); // option IDs that have crossed quota in prior columns

  const result = [];

  for (let toIdx = 0; toIdx < rounds.length; toIdx++) {
    // For toIdx=0 (Round 0), prev = Round 0 itself (Initial mirrors it identically).
    const curCounts = rounds[toIdx].option_counts || {};
    const prevCounts = toIdx === 0 ? curCounts : rounds[toIdx - 1].option_counts || {};

    const eliminated = [];
    for (const [oid, prevVal] of Object.entries(prevCounts)) {
      const pv = prevVal || 0;
      const cv = (curCounts[oid] || 0);
      if (pv > FLOAT_TOLERANCE && cv <= FLOAT_TOLERANCE) {
        eliminated.push(oid);
      }
    }

    const elected = [];
    for (const [oid, curVal] of Object.entries(curCounts)) {
      const cv = curVal || 0;
      if (cv >= quota - FLOAT_TOLERANCE && !crossedQuota.has(oid)) {
        elected.push(oid);
        crossedQuota.add(oid);
      }
    }

    if (elected.length > 0 || eliminated.length > 0) {
      result.push({ rawRoundIdx: toIdx, elected, eliminated });
    }
  }

  return result;
}

/**
 * Pure helper: convert tally.rounds[] into d3-sankey nodes + links.
 *
 * Returns { nodes, links } or null if not enough data to build a chart.
 *
 * Each node: { id, roundIdx, optionId, count, kind?: 'initial'|'final' }
 * Each link: { source: nodeId, target: nodeId, value,
 *              kind: 'carry'|'transfer'|'initial'|'final' }
 *
 * Phase 7C.1: synthesizes an "Initial" column (roundIdx = -1) before round 0
 * and a "Final" column (roundIdx = rounds.length) after the last round.
 *   - Initial nodes mirror rounds[0].option_counts; one Initial→round-0 link
 *     per option, sized by that count.
 *   - Final nodes mirror rounds[last].option_counts (zero-count options
 *     skipped — already eliminated, no Final node). One last-round→Final
 *     link per surviving option.
 *   - For single-round IRV (rounds.length === 1), the Initial→round-0 carry
 *     and round-0→Final carry both render, giving two slim columns flanking
 *     a single round-0 column. (Round-0 column itself is still emitted; the
 *     visual middle "story" is empty but Initial + Final flank it.)
 */
export function buildSankeyData(tally) {
  if (!tally || !Array.isArray(tally.rounds) || tally.rounds.length === 0) return null;
  const rounds = tally.rounds;
  const FINAL_COL = rounds.length;

  // Build a node per (round, option) where the option has a non-zero count
  // in that round. Eliminated options drop out naturally because subsequent
  // rounds omit them from option_counts (or they appear with count 0).
  const nodes = [];
  const nodeIdx = new Map(); // key -> array index
  const liveOptionsByRound = []; // [Set<optionId>, ...] per round

  rounds.forEach((round, rIdx) => {
    const counts = round.option_counts || {};
    const live = new Set();
    for (const [oid, count] of Object.entries(counts)) {
      // Skip zero-count nodes — they clutter and produce zero-width slabs.
      if (count == null || count <= 0) continue;
      const k = nodeKey(rIdx, oid);
      nodeIdx.set(k, nodes.length);
      nodes.push({ id: k, roundIdx: rIdx, optionId: oid, count: Number(count) });
      live.add(oid);
    }
    liveOptionsByRound.push(live);
  });

  if (nodes.length === 0) return null;

  // ---- Phase 7C.1: Initial column ----
  // One node per option that had a non-zero count in round 0. Initial→round-0
  // link sized by that round-0 count.
  const round0Counts = rounds[0].option_counts || {};
  const initialLinks = [];
  for (const [oid, rawCount] of Object.entries(round0Counts)) {
    const count = Number(rawCount) || 0;
    if (count <= 0) continue;
    const initKey = nodeKey(INITIAL_COL, oid);
    if (!nodeIdx.has(initKey)) {
      nodeIdx.set(initKey, nodes.length);
      nodes.push({
        id: initKey,
        roundIdx: INITIAL_COL,
        optionId: oid,
        count,
        kind: 'initial',
      });
    }
    const targetKey = nodeKey(0, oid);
    if (nodeIdx.has(targetKey)) {
      initialLinks.push({
        source: initKey,
        target: targetKey,
        value: count,
        kind: 'initial',
      });
    }
  }

  // ---- Phase 7C.1: Final column ----
  // One node per option still alive (count > 0) in the last round. Skip
  // options that were already eliminated — visually they just stop earlier.
  const lastIdx = rounds.length - 1;
  const lastCounts = rounds[lastIdx].option_counts || {};
  const finalLinks = [];
  for (const [oid, rawCount] of Object.entries(lastCounts)) {
    const count = Number(rawCount) || 0;
    if (count <= 0) continue;
    const finKey = nodeKey(FINAL_COL, oid);
    if (!nodeIdx.has(finKey)) {
      nodeIdx.set(finKey, nodes.length);
      nodes.push({
        id: finKey,
        roundIdx: FINAL_COL,
        optionId: oid,
        count,
        kind: 'final',
      });
    }
    const sourceKey = nodeKey(lastIdx, oid);
    if (nodeIdx.has(sourceKey)) {
      finalLinks.push({
        source: sourceKey,
        target: finKey,
        value: count,
        kind: 'final',
      });
    }
  }

  // Build links between rounds r and r+1.
  // Synthetic Exhausted nodes are appended lazily — only when a round
  // actually has unaccounted volume.
  const links = [...initialLinks];

  for (let r = 0; r < rounds.length - 1; r++) {
    const cur = rounds[r];
    const nxt = rounds[r + 1];
    const curCounts = cur.option_counts || {};
    const nxtCounts = nxt.option_counts || {};
    const transferBreakdown = nxt.transfer_breakdown || {};
    const prevElected = Array.isArray(cur.elected) ? cur.elected : [];

    // Phase 7C.2: detect ALL options whose count dropped between r and r+1
    // (not just nxt.transferred_from, which pyrankvote 2.0.6 names only one
    // of when there are paired surplus+elimination events in the same round).
    // The drop volume is what flowed out; the breakdown is what flowed in to
    // survivors; the difference is exhausted ballots.
    const allOptionIds = new Set([
      ...Object.keys(curCounts),
      ...Object.keys(nxtCounts),
    ]);
    const drops = {}; // optionId -> drop amount (>0)
    let totalDropVolume = 0;
    for (const oid of allOptionIds) {
      const prev = Number(curCounts[oid]) || 0;
      const next = Number(nxtCounts[oid]) || 0;
      const d = prev - next;
      if (d > FLOAT_TOLERANCE) {
        drops[oid] = d;
        totalDropVolume += d;
      }
    }
    const droppedOpts = Object.keys(drops);
    const totalGainVolume = Object.values(transferBreakdown).reduce(
      (s, v) => s + (Number(v) || 0),
      0
    );
    const exhaustedVolume = Math.max(0, totalDropVolume - totalGainVolume);

    // 1) Carry links: each option that survives forward flows its retained
    //    portion (= min(prev, next)) from r to r+1. This is faithful even in
    //    the multi-source case — the carry is whatever the option already had.
    for (const oid of Object.keys(nxtCounts)) {
      const nxtCount = Number(nxtCounts[oid]) || 0;
      if (nxtCount <= 0) continue;
      const targetKey = nodeKey(r + 1, oid);
      if (!nodeIdx.has(targetKey)) continue;

      const prevCount = Number(curCounts[oid]) || 0;
      const carry = Math.max(0, Math.min(prevCount, nxtCount));
      const carrySourceKey = nodeKey(r, oid);
      if (carry > 0 && nodeIdx.has(carrySourceKey)) {
        links.push({
          source: carrySourceKey,
          target: targetKey,
          value: carry,
          kind: 'carry',
        });
      }
    }

    // 2) Transfer links — single-source vs. multi-source dispatch.
    if (droppedOpts.length === 0) {
      // No drops at all (rare but possible — e.g., a no-op round). Nothing to
      // transfer.
    } else if (droppedOpts.length === 1) {
      // Clean single-source round: emit links from the dropped option to each
      // gainer using the breakdown's exact values, plus a synthetic
      // "exhausted" link if breakdown sums to less than the drop.
      const [dropOpt] = droppedOpts;
      const isSurplus = prevElected.includes(dropOpt);
      const transferKind = isSurplus ? 'transfer-surplus' : 'transfer';
      const dropSourceKey = nodeKey(r, dropOpt);
      if (nodeIdx.has(dropSourceKey)) {
        for (const [gainOpt, gainRaw] of Object.entries(transferBreakdown)) {
          const gain = Number(gainRaw) || 0;
          if (gain <= 0) continue;
          if (gainOpt === dropOpt) continue; // defensive
          const tgtKey = nodeKey(r + 1, gainOpt);
          if (!nodeIdx.has(tgtKey)) continue;
          links.push({
            source: dropSourceKey,
            target: tgtKey,
            value: gain,
            kind: transferKind,
          });
        }
        if (exhaustedVolume > FLOAT_TOLERANCE) {
          const exKey = nodeKey(r + 1, EXHAUSTED_OPT_ID);
          if (!nodeIdx.has(exKey)) {
            nodeIdx.set(exKey, nodes.length);
            nodes.push({
              id: exKey,
              roundIdx: r + 1,
              optionId: EXHAUSTED_OPT_ID,
              count: 0, // accumulate as we add inbound links below
              kind: 'exhausted',
            });
          }
          nodes[nodeIdx.get(exKey)].count += exhaustedVolume;
          links.push({
            source: dropSourceKey,
            target: exKey,
            value: exhaustedVolume,
            kind: 'transfer-exhausted',
          });
        }
      }
    } else {
      // Multi-source round (Decision 1 fix): pyrankvote packed paired events
      // into one ElectionResultRound. Attribute breakdown proportionally to
      // each dropped option by its share of total drop volume. This is a
      // faithful summary of total flow, not an exact per-ballot trace —
      // tooltip copy uses "~" + "approximate" to disclose this honestly.
      for (const dropOpt of droppedOpts) {
        const dropAmt = drops[dropOpt];
        const share = totalDropVolume > 0 ? dropAmt / totalDropVolume : 0;
        const dropSourceKey = nodeKey(r, dropOpt);
        if (!nodeIdx.has(dropSourceKey)) continue;
        const isSurplus = prevElected.includes(dropOpt);
        const transferKind = isSurplus ? 'transfer-surplus' : 'transfer-multi-source';

        for (const [gainOpt, gainRaw] of Object.entries(transferBreakdown)) {
          const gain = Number(gainRaw) || 0;
          if (gain <= 0) continue;
          if (gainOpt === dropOpt) continue;
          const tgtKey = nodeKey(r + 1, gainOpt);
          if (!nodeIdx.has(tgtKey)) continue;
          const value = share * gain;
          if (value <= FLOAT_TOLERANCE) continue;
          links.push({
            source: dropSourceKey,
            target: tgtKey,
            value,
            kind: transferKind,
          });
        }

        if (exhaustedVolume > FLOAT_TOLERANCE) {
          const exVal = share * exhaustedVolume;
          if (exVal > FLOAT_TOLERANCE) {
            const exKey = nodeKey(r + 1, EXHAUSTED_OPT_ID);
            if (!nodeIdx.has(exKey)) {
              nodeIdx.set(exKey, nodes.length);
              nodes.push({
                id: exKey,
                roundIdx: r + 1,
                optionId: EXHAUSTED_OPT_ID,
                count: 0,
                kind: 'exhausted',
              });
            }
            nodes[nodeIdx.get(exKey)].count += exVal;
            links.push({
              source: dropSourceKey,
              target: exKey,
              value: exVal,
              kind: 'transfer-exhausted',
            });
          }
        }
      }
    }

    // Reconciliation check (best-effort, never throw): if total drop volume
    // doesn't match total gain + exhausted (within tolerance), we still
    // render. The exhausted sink absorbs the difference.
    if (
      Math.abs(totalDropVolume - (totalGainVolume + exhaustedVolume)) >
      RECONCILE_TOLERANCE * Math.max(1, totalDropVolume)
    ) {
      // Mismatch — float-rounding slop typically. We render as-is; the
      // exhausted node already absorbs the unaccounted volume.
    }
  }

  // Append Final links last so they sit at the right edge of the link list.
  for (const fl of finalLinks) links.push(fl);

  return { nodes, links };
}

export default function RCVSankeyChart({ tally, proposal }) {
  const containerRef = useRef(null);
  const svgRef = useRef(null);
  const [dimensions, setDimensions] = useState({ width: 800, height: HEIGHT });
  const [tooltip, setTooltip] = useState(null);

  // Build a label map for option IDs. Mirrors the pattern in RCVResultsPanel.
  const optionLabelMap = useMemo(() => {
    const m = {};
    const fromTally = Array.isArray(tally?.options) ? tally.options : [];
    fromTally.forEach((o) => {
      if (o?.id) m[o.id] = o.label || o.id;
    });
    if (tally?.option_labels) {
      Object.entries(tally.option_labels).forEach(([k, v]) => {
        m[k] = v;
      });
    }
    (proposal?.options || []).forEach((o) => {
      if (!m[o.id]) m[o.id] = o.label;
    });
    return m;
  }, [tally, proposal]);

  // Map option_id -> { id, display_order } for color lookup.
  const optionMeta = useMemo(() => {
    const m = new Map();
    (proposal?.options || []).forEach((o) => {
      m.set(o.id, { id: o.id, display_order: o.display_order ?? 0, label: o.label });
    });
    // Fallback for any option that appears in tally rounds but isn't in
    // proposal.options (shouldn't happen, but defensive).
    if (Array.isArray(tally?.options)) {
      tally.options.forEach((o, idx) => {
        if (o?.id && !m.has(o.id)) {
          m.set(o.id, { id: o.id, display_order: o.display_order ?? idx, label: o.label });
        }
      });
    }
    return m;
  }, [proposal, tally]);

  const labelOf = useCallback(
    (oid) => {
      if (oid === EXHAUSTED_OPT_ID) return 'Exhausted ballots';
      return optionLabelMap[oid] || oid;
    },
    [optionLabelMap]
  );
  const colorOf = useCallback(
    (oid) => {
      if (oid === EXHAUSTED_OPT_ID) return EXHAUSTED_COLOR;
      const meta = optionMeta.get(oid) || { id: oid, display_order: 0 };
      return colorForOption(meta);
    },
    [optionMeta]
  );
  const formatCount = (v) => (Number.isInteger(v) ? String(v) : Number(v).toFixed(2));

  // Resize observer.
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const observer = new ResizeObserver((entries) => {
      const { width } = entries[0].contentRect;
      if (width > 0) {
        setDimensions({ width, height: HEIGHT });
      }
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  const sankeyData = useMemo(() => buildSankeyData(tally), [tally]);
  const winners = useMemo(() => new Set(tally?.winners || []), [tally]);

  useEffect(() => {
    if (!svgRef.current) return;
    const svg = d3.select(svgRef.current);
    svg.selectAll('*').remove();
    if (!sankeyData) return;

    const { width, height } = dimensions;
    const innerWidth = Math.max(50, width - PADDING.left - PADDING.right);
    const innerHeight = Math.max(50, height - PADDING.top - PADDING.bottom);

    // Clone nodes/links because d3-sankey mutates them in place.
    const nodesCopy = sankeyData.nodes.map((n) => ({ ...n }));
    const linksCopy = sankeyData.links.map((l) => ({ ...l }));

    const sankeyGen = d3Sankey()
      .nodeId((d) => d.id)
      .nodeWidth(NODE_WIDTH)
      .nodePadding(NODE_PADDING)
      .extent([
        [PADDING.left, PADDING.top],
        [PADDING.left + innerWidth, PADDING.top + innerHeight],
      ]);

    let graph;
    try {
      graph = sankeyGen({
        nodes: nodesCopy,
        links: linksCopy,
      });
    } catch {
      // Defensive — d3-sankey can throw on degenerate data (e.g., a cycle
      // we don't expect to ever produce). Render nothing rather than crash.
      return;
    }

    const g = svg.append('g');

    // Column labels at the top of each column. Phase 7C.1 adds Initial
    // (roundIdx -1) and Final (roundIdx rounds.length) columns flanking the
    // round-by-round columns.
    const roundsCount = (tally?.rounds || []).length;
    const FINAL_COL_IDX = roundsCount;
    const allColIdxs = [-1, ...Array.from({ length: roundsCount }, (_, i) => i), FINAL_COL_IDX];
    const colXs = [];
    for (const r of allColIdxs) {
      const colNodes = graph.nodes.filter((n) => n.roundIdx === r);
      if (colNodes.length === 0) continue;
      const x = colNodes[0].x0;
      colXs.push({ r, x });
    }

    // Build a map from rawRoundIdx -> event label, derived from observed
    // option_counts transitions (not pyrankvote metadata).
    const displayCols = deriveDisplayColumns(tally);
    const eventByRound = new Map(
      displayCols.map(({ rawRoundIdx, elected, eliminated }) => {
        const parts = [];
        if (elected.length > 0) parts.push(`✓ ${elected.map(labelOf).join(', ')}`);
        if (eliminated.length > 0) parts.push(`✗ ${eliminated.map(labelOf).join(', ')}`);
        return [rawRoundIdx, { label: parts.join(' · '), hasElected: elected.length > 0, hasEliminated: eliminated.length > 0 }];
      })
    );

    const roundLabelG = g.append('g').attr('class', 'round-labels');
    colXs.forEach(({ r, x }) => {
      const cx = x + NODE_WIDTH / 2;

      // Initial and Final always render their title; intermediate rounds
      // render a title only if they have an observable event.
      if (r === -1) {
        roundLabelG
          .append('text')
          .text('Initial')
          .attr('x', cx)
          .attr('y', PADDING.top - ELIM_LABEL_PX - 8)
          .attr('text-anchor', 'middle')
          .attr('font-size', 11)
          .attr('font-weight', 600)
          .attr('fill', '#1B3A5C');
        return;
      }
      if (r === FINAL_COL_IDX) {
        roundLabelG
          .append('text')
          .text('Final')
          .attr('x', cx)
          .attr('y', PADDING.top - ELIM_LABEL_PX - 8)
          .attr('text-anchor', 'middle')
          .attr('font-size', 11)
          .attr('font-weight', 600)
          .attr('fill', '#1B3A5C');
        return;
      }

      const event = eventByRound.get(r);
      if (!event) return; // collapse no-event round: no column header rendered

      roundLabelG
        .append('text')
        .text(event.label)
        .attr('x', cx)
        .attr('y', PADDING.top - 8)
        .attr('text-anchor', 'middle')
        .attr('font-size', 10)
        .attr('font-weight', 500)
        .attr('fill', event.hasElected && !event.hasEliminated ? '#2D8A56' : event.hasEliminated && !event.hasElected ? '#C0392B' : '#1B3A5C')
        .attr('text-decoration', event.hasEliminated && !event.hasElected ? 'line-through' : null);
    });

    // Phase 7C.2: any transfer-flavored link kind gets the dashed
    // stroke + slightly higher opacity (vs. the carry-forward solid look).
    const isTransferKind = (k) =>
      k === 'transfer' ||
      k === 'transfer-surplus' ||
      k === 'transfer-multi-source' ||
      k === 'transfer-exhausted';

    // Links layer (under nodes).
    const linkG = g.append('g').attr('class', 'sankey-links').attr('fill', 'none');
    const link = linkG
      .selectAll('path')
      .data(graph.links)
      .join('path')
      .attr('d', sankeyLinkHorizontal())
      .attr('stroke', (d) => colorOf(d.source.optionId))
      .attr('stroke-width', (d) => Math.max(1, d.width))
      .attr('stroke-opacity', (d) => (isTransferKind(d.kind) ? 0.55 : 0.35))
      .attr('stroke-dasharray', (d) => (isTransferKind(d.kind) ? '4,2' : null))
      .style('mix-blend-mode', 'multiply');

    link
      .on('mouseenter', function (event, d) {
        link.attr('stroke-opacity', (l) => (l === d ? 0.9 : 0.08));
        const rect = svgRef.current.getBoundingClientRect();
        const srcLabel = labelOf(d.source.optionId);
        const tgtLabel = labelOf(d.target.optionId);
        setTooltip({
          x: event.clientX - rect.left,
          y: event.clientY - rect.top - 10,
          kind: 'link',
          srcLabel,
          tgtLabel,
          value: d.value,
          linkKind: d.kind,
        });
      })
      .on('mousemove', function (event) {
        const rect = svgRef.current.getBoundingClientRect();
        setTooltip((t) =>
          t ? { ...t, x: event.clientX - rect.left, y: event.clientY - rect.top - 10 } : t
        );
      })
      .on('mouseleave', function () {
        link.attr('stroke-opacity', (l) => (isTransferKind(l.kind) ? 0.55 : 0.35));
        setTooltip(null);
      });

    // Nodes layer.
    const nodeG = g.append('g').attr('class', 'sankey-nodes');
    const nodeSel = nodeG
      .selectAll('g')
      .data(graph.nodes)
      .join('g')
      .attr('class', 'sankey-node');

    nodeSel
      .append('rect')
      .attr('x', (d) => d.x0)
      .attr('y', (d) => d.y0)
      .attr('width', (d) => Math.max(1, d.x1 - d.x0))
      .attr('height', (d) => Math.max(1, d.y1 - d.y0))
      .attr('fill', (d) => colorOf(d.optionId))
      .attr('fill-opacity', (d) => {
        // In the Final column, dim non-winners so the winner(s) read clearly.
        // For STV multi-winner, every option in tally.winners gets the bright
        // treatment.
        if (d.roundIdx === FINAL_COL_IDX && !winners.has(d.optionId)) return 0.45;
        return 1;
      })
      .attr('stroke', (d) => {
        // Final-column winner(s) get the dark-navy emphasis stroke. STV with
        // multiple winners highlights every winner equivalently.
        if (d.roundIdx === FINAL_COL_IDX && winners.has(d.optionId)) return '#1B3A5C';
        return '#FFFFFF';
      })
      .attr('stroke-width', (d) => {
        if (d.roundIdx === FINAL_COL_IDX && winners.has(d.optionId)) return 3;
        return 1;
      });

    // Node labels — only on Initial (leftmost) and Final (rightmost) columns
    // to avoid clutter in middle elimination rounds.
    nodeSel
      .filter((d) => d.roundIdx === -1 || d.roundIdx === FINAL_COL_IDX)
      .append('text')
      .attr('x', (d) => (d.roundIdx === -1 ? d.x1 + 4 : d.x0 - 4))
      .attr('y', (d) => (d.y0 + d.y1) / 2)
      .attr('dy', '0.35em')
      .attr('text-anchor', (d) => (d.roundIdx === -1 ? 'start' : 'end'))
      .attr('font-size', 10)
      .attr('fill', '#2C3E50')
      .text((d) => {
        const lbl = labelOf(d.optionId);
        const truncated = lbl.length > 18 ? lbl.slice(0, 16) + '…' : lbl;
        return `${truncated} (${formatCount(d.count)})`;
      });

    // Phase 7C.2: label synthetic Exhausted nodes wherever they appear so
    // the user knows what the muted gray slab represents. Hovering still
    // shows the exact volume; the inline label is the at-a-glance cue.
    nodeSel
      .filter((d) => d.optionId === EXHAUSTED_OPT_ID)
      .append('text')
      .attr('x', (d) => d.x1 + 4)
      .attr('y', (d) => (d.y0 + d.y1) / 2)
      .attr('dy', '0.35em')
      .attr('text-anchor', 'start')
      .attr('font-size', 10)
      .attr('font-style', 'italic')
      .attr('fill', '#6B7280')
      .text((d) => `Exhausted (${formatCount(d.count)})`);

    // Hover on node — highlight incident links, dim others.
    nodeSel
      .on('mouseenter', function (event, d) {
        link.attr('stroke-opacity', (l) =>
          l.source === d || l.target === d ? 0.85 : 0.08
        );
        const rect = svgRef.current.getBoundingClientRect();
        let roundLabel;
        if (d.roundIdx === -1) roundLabel = 'Initial';
        else if (d.roundIdx === FINAL_COL_IDX) roundLabel = 'Final';
        else roundLabel = `Round ${d.roundIdx + 1}`;
        setTooltip({
          x: event.clientX - rect.left,
          y: event.clientY - rect.top - 10,
          kind: 'node',
          label: labelOf(d.optionId),
          roundLabel,
          value: d.count,
        });
      })
      .on('mousemove', function (event) {
        const rect = svgRef.current.getBoundingClientRect();
        setTooltip((t) =>
          t ? { ...t, x: event.clientX - rect.left, y: event.clientY - rect.top - 10 } : t
        );
      })
      .on('mouseleave', function () {
        link.attr('stroke-opacity', (l) => (isTransferKind(l.kind) ? 0.55 : 0.35));
        setTooltip(null);
      });
  }, [sankeyData, dimensions, tally, winners, labelOf, colorOf]);

  // Short-circuit: only render for ranked_choice proposals.
  if (!proposal || proposal.voting_method !== 'ranked_choice') return null;

  const inProgress = proposal.status === 'voting';
  const headerSuffix = inProgress ? ' (Provisional)' : '';
  const noData = !sankeyData;

  return (
    <div className="bg-white border border-gray-200 rounded-xl overflow-hidden">
      <div className="px-5 py-3 border-b border-gray-100">
        <h3 className="text-sm font-semibold text-gray-700 uppercase tracking-wide">
          Elimination Flow{headerSuffix}
        </h3>
        <p className="text-xs text-gray-500 mt-0.5">
          Each column is an elimination round. Slabs show option counts; flows show
          how votes carry forward and transfer between rounds.{' '}
          <Link to="/help/voting-methods" className="text-[#2E75B6] hover:underline">
            Learn more
          </Link>
        </p>
      </div>
      <div ref={containerRef} className="relative px-4 pb-4 pt-2">
        {noData ? (
          <p className="text-sm text-gray-400 italic py-8 text-center">
            Sankey will appear once ballots are cast.
          </p>
        ) : (
          <>
            <svg
              ref={svgRef}
              width={dimensions.width}
              height={dimensions.height}
              className="bg-white rounded-lg"
              style={{ maxWidth: '100%' }}
            />
            {tooltip && (
              <div
                className="absolute pointer-events-none bg-white border border-gray-200 rounded-lg shadow-lg px-3 py-2 text-xs z-10"
                style={{ left: tooltip.x + 12, top: tooltip.y - 8, maxWidth: 260 }}
              >
                {tooltip.kind === 'node' ? (
                  <>
                    <div className="font-semibold text-[#1B3A5C]">{tooltip.label}</div>
                    <div className="text-gray-500 mt-0.5">
                      {tooltip.roundLabel} · {formatCount(tooltip.value)} vote
                      {tooltip.value === 1 ? '' : 's'}
                    </div>
                  </>
                ) : tooltip.linkKind === 'transfer-surplus' ? (
                  <>
                    <div className="font-semibold text-[#1B3A5C]">
                      {tooltip.srcLabel} → {tooltip.tgtLabel}
                    </div>
                    <div className="text-gray-500 mt-0.5">
                      Surplus transfer: {formatCount(tooltip.value)} vote
                      {tooltip.value === 1 ? '' : 's'} (each ballot above threshold contributed a fractional vote to its next preference).
                    </div>
                  </>
                ) : tooltip.linkKind === 'transfer-multi-source' ? (
                  <>
                    <div className="font-semibold text-[#1B3A5C]">
                      {tooltip.srcLabel} → {tooltip.tgtLabel}
                    </div>
                    <div className="text-gray-500 mt-0.5">
                      Combined-round transfer: ~{formatCount(tooltip.value)} vote
                      {tooltip.value === 1 ? '' : 's'} (this round had multiple eliminations; share is approximate, not ballot-traced).
                    </div>
                  </>
                ) : tooltip.linkKind === 'transfer-exhausted' ? (
                  <>
                    <div className="font-semibold text-[#1B3A5C]">{tooltip.srcLabel}</div>
                    <div className="text-gray-500 mt-0.5">
                      Exhausted: {formatCount(tooltip.value)} vote
                      {tooltip.value === 1 ? '' : 's'} (no remaining preference on these ballots).
                    </div>
                  </>
                ) : (
                  <>
                    <div className="font-semibold text-[#1B3A5C]">
                      {tooltip.srcLabel} → {tooltip.tgtLabel}
                    </div>
                    <div className="text-gray-500 mt-0.5">
                      {tooltip.linkKind === 'transfer' ? 'Transfer' : 'Carried forward'}:{' '}
                      {formatCount(tooltip.value)} vote{tooltip.value === 1 ? '' : 's'}
                    </div>
                  </>
                )}
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}
