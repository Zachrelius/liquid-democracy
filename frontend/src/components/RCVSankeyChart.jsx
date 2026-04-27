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
const HEIGHT = 360;

// Phase 7C.1: synthetic column indices used by Initial / Final nodes. They
// live OUTSIDE the rounds[] index space so we can render them as their own
// columns at the leftmost and rightmost ends of the Sankey.
const INITIAL_COL = -1;
// FINAL_COL is rounds.length (computed at use-site).

function nodeKey(roundIdx, optionId) {
  // roundIdx may be -1 (Initial) or rounds.length (Final). String-keying
  // handles those uniformly.
  return `r${roundIdx}::${optionId}`;
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
  const links = [...initialLinks];
  for (let r = 0; r < rounds.length - 1; r++) {
    const cur = rounds[r];
    const nxt = rounds[r + 1];
    const curCounts = cur.option_counts || {};
    const nxtCounts = nxt.option_counts || {};
    const transferBreakdown = nxt.transfer_breakdown || {};
    const transferFrom = nxt.transferred_from || cur.transferred_from || cur.eliminated || null;

    for (const [oid, nxtRaw] of Object.entries(nxtCounts)) {
      const nxtCount = Number(nxtRaw) || 0;
      if (nxtCount <= 0) continue;
      const targetKey = nodeKey(r + 1, oid);
      if (!nodeIdx.has(targetKey)) continue;

      const gain = Number(transferBreakdown[oid]) || 0;
      // Carry: own previous count flows forward, minus any "gain" that came
      // from elsewhere. (gain is the portion of nxtCount that originated
      // from transferFrom.)
      const carry = Math.max(0, nxtCount - gain);
      // Defend against gain > nxtCount due to float rounding.
      const transferAmt = Math.max(0, Math.min(nxtCount, gain));

      // Carry link from same option in previous round (only if it existed).
      const carrySourceKey = nodeKey(r, oid);
      if (carry > 0 && nodeIdx.has(carrySourceKey)) {
        links.push({
          source: carrySourceKey,
          target: targetKey,
          value: carry,
          kind: 'carry',
        });
      }

      // Transfer link from transferFrom -> oid.
      if (transferAmt > 0 && transferFrom && transferFrom !== oid) {
        const transferSourceKey = nodeKey(r, transferFrom);
        if (nodeIdx.has(transferSourceKey)) {
          links.push({
            source: transferSourceKey,
            target: targetKey,
            value: transferAmt,
            kind: 'transfer',
          });
        }
      }
    }

    // Reconciliation check (best-effort, never throw): if the eliminated
    // option's outgoing transfer total significantly mismatches its previous
    // count, we still render — the user may see the imbalance visually.
    if (transferFrom && curCounts[transferFrom] != null) {
      const elimCount = Number(curCounts[transferFrom]) || 0;
      const totalTransfer = Object.values(transferBreakdown).reduce(
        (s, v) => s + (Number(v) || 0),
        0
      );
      if (Math.abs(elimCount - totalTransfer) > RECONCILE_TOLERANCE * Math.max(1, elimCount)) {
        // Mismatch — likely exhausted ballots. Not an error; just note it.
        // We could surface this to the user, but for now we render as-is.
      }
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
    (oid) => optionLabelMap[oid] || oid,
    [optionLabelMap]
  );
  const colorOf = useCallback(
    (oid) => {
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

    const roundLabelG = g.append('g').attr('class', 'round-labels');
    colXs.forEach(({ r, x }) => {
      const cx = x + NODE_WIDTH / 2;
      let title;
      if (r === -1) title = 'Initial';
      else if (r === FINAL_COL_IDX) title = 'Final';
      else title = `Round ${r + 1}`;

      roundLabelG
        .append('text')
        .text(title)
        .attr('x', cx)
        .attr('y', PADDING.top - ELIM_LABEL_PX - 8)
        .attr('text-anchor', 'middle')
        .attr('font-size', 11)
        .attr('font-weight', 600)
        .attr('fill', '#1B3A5C');

      // Initial / Final columns don't carry round-level elimination/elected
      // annotations.
      if (r === -1 || r === FINAL_COL_IDX) return;

      const round = tally.rounds[r];
      const elimId = round?.eliminated;
      const electedIds = round?.elected || [];

      if (elimId) {
        roundLabelG
          .append('text')
          .text(`✗ ${labelOf(elimId)}`)
          .attr('x', cx)
          .attr('y', PADDING.top - 8)
          .attr('text-anchor', 'middle')
          .attr('font-size', 10)
          .attr('font-weight', 500)
          .attr('fill', '#C0392B')
          .attr('text-decoration', 'line-through');
      } else if (electedIds.length > 0) {
        roundLabelG
          .append('text')
          .text(`✓ ${electedIds.map(labelOf).join(', ')}`)
          .attr('x', cx)
          .attr('y', PADDING.top - 8)
          .attr('text-anchor', 'middle')
          .attr('font-size', 10)
          .attr('font-weight', 500)
          .attr('fill', '#2D8A56');
      }
    });

    // Links layer (under nodes).
    const linkG = g.append('g').attr('class', 'sankey-links').attr('fill', 'none');
    const link = linkG
      .selectAll('path')
      .data(graph.links)
      .join('path')
      .attr('d', sankeyLinkHorizontal())
      .attr('stroke', (d) => colorOf(d.source.optionId))
      .attr('stroke-width', (d) => Math.max(1, d.width))
      .attr('stroke-opacity', (d) => (d.kind === 'transfer' ? 0.55 : 0.35))
      .attr('stroke-dasharray', (d) => (d.kind === 'transfer' ? '4,2' : null))
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
        link.attr('stroke-opacity', (l) => (l.kind === 'transfer' ? 0.55 : 0.35));
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
        link.attr('stroke-opacity', (l) => (l.kind === 'transfer' ? 0.55 : 0.35));
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
