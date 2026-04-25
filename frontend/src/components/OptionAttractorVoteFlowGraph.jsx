import { useRef, useEffect, useState, useCallback, useMemo } from 'react';
import { Link } from 'react-router-dom';
import * as d3 from 'd3';
import {
  VOTE_COLORS,
  nodeRadius,
  dedupeEdges,
  uniqueMarkerColors,
  markerId,
  computeOptionWeights,
  colorForOption,
  truncateLabel,
} from './voteFlowGraphUtils';

/**
 * OptionAttractorVoteFlowGraph — option-attractor force layout for approval
 * and ranked-choice proposals (Phase 7B).
 *
 * Each option is pinned in a circle around the centre and pulls voters
 * toward itself with a per-option weight. Voters settle at force
 * equilibrium. Voter-voter repulsion + collide prevent overlap.
 *
 * Tunable force parameters (settled empirically against the seeded
 * proposals — Coffee Vendor 3 opt, Offsite 4 opt, Steering Committee 5 opt):
 *
 *   ATTRACTOR_STRENGTH      0.08  (per-option pull, scaled by voter weight & alpha)
 *   CHARGE_BASE             -180  (voter-voter repulsion)
 *   OPTION_CHARGE           -800  (extra repulsion at option attractors so
 *                                  voters don't pile on top of pinned options)
 *   CENTER_STRENGTH         0.02  (light recentring force)
 *   COLLIDE_PADDING_PX      6
 *
 * For 5+ options we boost repulsion and dampen attractors slightly so the
 * ring doesn't compress into the centre — see scaleByOptionCount() below.
 */
const ATTRACTOR_STRENGTH = 0.08;
const CHARGE_BASE = -180;
const OPTION_CHARGE = -800;
const CENTER_STRENGTH = 0.02;
const COLLIDE_PADDING_PX = 6;
const HOVER_ISOLATE_THRESHOLD = 0.5;

function scaleByOptionCount(n) {
  // Returns { attractor, charge } scaled for option count.
  // 3-4 options: defaults read well.
  // 5+ options: bump repulsion, dampen attractors.
  if (n <= 4) return { attractor: ATTRACTOR_STRENGTH, charge: CHARGE_BASE };
  if (n <= 6) return { attractor: ATTRACTOR_STRENGTH * 0.85, charge: CHARGE_BASE * 1.3 };
  return { attractor: ATTRACTOR_STRENGTH * 0.7, charge: CHARGE_BASE * 1.6 };
}

// Custom force: voters are pulled toward each option in their optionWeights.
function optionAttractorForce(strength, getNodeMap, isOptionEnabled) {
  let nodes;
  function force(alpha) {
    if (!nodes) return;
    const map = getNodeMap();
    for (const v of nodes) {
      if (v.type === 'option') continue;
      const weights = v.optionWeights || [];
      for (const { optionId, weight } of weights) {
        if (!isOptionEnabled(optionId)) continue;
        const opt = map.get(optionId);
        if (!opt || opt.x == null || opt.y == null) continue;
        v.vx += (opt.x - v.x) * weight * strength * alpha;
        v.vy += (opt.y - v.y) * weight * strength * alpha;
      }
    }
  }
  force.initialize = (n) => {
    nodes = n;
  };
  return force;
}

export default function OptionAttractorVoteFlowGraph({ data, onNodeClick }) {
  const svgRef = useRef(null);
  const containerRef = useRef(null);
  const [tooltip, setTooltip] = useState(null);
  const [selectedNode, setSelectedNode] = useState(null);
  const [showNonVoters, setShowNonVoters] = useState(false);
  const [hideAbstainers, setHideAbstainers] = useState(false);
  const [dimensions, setDimensions] = useState({ width: 800, height: 500 });
  // Toggle state per option — { [optionId]: bool }
  const [optionEnabled, setOptionEnabled] = useState({});
  const simulationRef = useRef(null);
  const enabledRef = useRef(optionEnabled); // d3 force closure reads via ref

  const votingMethod = data?.voting_method;
  const options = useMemo(() => data?.options || [], [data]);
  const optionMap = useMemo(() => {
    const m = new Map();
    options.forEach((o) => m.set(o.id, o));
    return m;
  }, [options]);

  // Initialize all options enabled when data changes.
  useEffect(() => {
    const init = {};
    for (const o of options) init[o.id] = true;
    setOptionEnabled(init);
    enabledRef.current = init;
  }, [options]);

  useEffect(() => {
    enabledRef.current = optionEnabled;
    // Wake the simulation when toggles change so voters re-equilibrate.
    if (simulationRef.current) simulationRef.current.alpha(0.6).restart();
  }, [optionEnabled]);

  // Resize observer.
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const observer = new ResizeObserver((entries) => {
      const { width } = entries[0].contentRect;
      if (width > 0) setDimensions({ width, height: Math.max(420, Math.min(640, width * 0.65)) });
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  const handleNodeClick = useCallback(
    (event, d) => {
      event.stopPropagation();
      if (d.type === 'option') return; // options are inert (no detail panel for now)
      setSelectedNode((prev) => (prev?.id === d.id ? null : d));
      if (onNodeClick) onNodeClick(d);
    },
    [onNodeClick]
  );

  useEffect(() => {
    if (!data || !svgRef.current) return;

    const { width, height } = dimensions;
    const svg = d3.select(svgRef.current);
    svg.selectAll('*').remove();

    // Compute option ring geometry.
    const cx = width / 2;
    const cy = height / 2;
    const R = Math.min(width, height) * 0.35;

    // Build option nodes (pinned).
    const sortedOptions = [...options].sort(
      (a, b) => (a.display_order ?? 0) - (b.display_order ?? 0)
    );
    const N = sortedOptions.length || 1;
    const optionNodes = sortedOptions.map((o, i) => {
      const angle = (i / N) * 2 * Math.PI - Math.PI / 2; // start at top
      return {
        id: o.id,
        type: 'option',
        label: o.label,
        display_order: o.display_order,
        approval_count: o.approval_count || 0,
        first_pref_count: o.first_pref_count || 0,
        x: cx + R * Math.cos(angle),
        y: cy + R * Math.sin(angle),
        fx: cx + R * Math.cos(angle),
        fy: cy + R * Math.sin(angle),
      };
    });

    // Voter nodes — copy + attach optionWeights.
    const voterNodesAll = data.nodes.map((n) => {
      const weights = computeOptionWeights(n.ballot, votingMethod);
      const isAbstainer = !n.ballot || weights.length === 0;
      return { ...n, optionWeights: weights, isAbstainer };
    });

    let voterNodes = showNonVoters
      ? voterNodesAll
      : voterNodesAll.filter((n) => n.type !== 'non_voter');
    if (hideAbstainers) {
      voterNodes = voterNodes.filter((n) => !(n.isAbstainer && n.type !== 'non_voter'));
    }

    const allSimNodes = [...voterNodes, ...optionNodes];
    const simNodeMap = new Map(allSimNodes.map((n) => [n.id, n]));

    // Edges (delegation) — only between voter nodes.
    const edges = data.edges.map((e) => ({ ...e }));
    const uniqueEdges = dedupeEdges(edges);
    const validEdges = uniqueEdges.filter(
      (e) =>
        simNodeMap.has(e.source) &&
        simNodeMap.has(e.target) &&
        simNodeMap.get(e.source).type !== 'option' &&
        simNodeMap.get(e.target).type !== 'option'
    );

    const zoom = d3
      .zoom()
      .scaleExtent([0.3, 4])
      .on('zoom', (event) => g.attr('transform', event.transform));
    svg.call(zoom);
    svg.on('click', () => setSelectedNode(null));

    const g = svg.append('g');

    const defs = svg.append('defs');
    uniqueMarkerColors(validEdges).forEach((color) => {
      defs
        .append('marker')
        .attr('id', markerId(color))
        .attr('viewBox', '0 -5 10 10')
        .attr('refX', 10)
        .attr('refY', 0)
        .attr('markerWidth', 7)
        .attr('markerHeight', 7)
        .attr('orient', 'auto')
        .append('path')
        .attr('d', 'M0,-5L10,0L0,5')
        .attr('fill', color)
        .attr('opacity', 0.7);
    });

    const { attractor, charge } = scaleByOptionCount(N);

    const simulation = d3
      .forceSimulation(allSimNodes)
      .force(
        'charge',
        d3.forceManyBody().strength((d) => (d.type === 'option' ? OPTION_CHARGE : charge))
      )
      .force(
        'collision',
        d3.forceCollide().radius((d) => nodeRadius(d) + COLLIDE_PADDING_PX)
      )
      .force('center', d3.forceCenter(cx, cy).strength(CENTER_STRENGTH))
      .force(
        'attract',
        optionAttractorForce(
          attractor,
          () => simNodeMap,
          (optionId) => enabledRef.current[optionId] !== false
        )
      )
      .force(
        'link',
        d3.forceLink(validEdges).id((d) => d.id).distance(50).strength(0.15)
      )
      .alpha(0.9)
      .alphaDecay(0.025);

    simulationRef.current = simulation;

    // Edges layer.
    const edgeG = g.append('g').attr('class', 'edges');
    const link = edgeG
      .selectAll('line')
      .data(validEdges)
      .join('line')
      .attr('stroke', (d) => d.topic_color || '#95a5a6')
      .attr('stroke-width', 1.2)
      .attr('stroke-opacity', 0.45)
      .attr('marker-end', (d) => `url(#${markerId(d.topic_color || '#95a5a6')})`);

    // Nodes layer.
    const nodeG = g.append('g').attr('class', 'nodes');
    const node = nodeG
      .selectAll('g')
      .data(allSimNodes)
      .join('g')
      .attr('cursor', (d) => (d.type === 'option' ? 'default' : 'pointer'))
      .call(
        d3
          .drag()
          .filter((event, d) => d.type !== 'option') // options are pinned, not draggable
          .on('start', (event, d) => {
            if (!event.active) simulation.alphaTarget(0.3).restart();
            d.fx = d.x;
            d.fy = d.y;
          })
          .on('drag', (event, d) => {
            d.fx = event.x;
            d.fy = event.y;
          })
          .on('end', (event, d) => {
            if (!event.active) simulation.alphaTarget(0);
            d.fx = null;
            d.fy = null;
          })
      );

    // Option attractor visuals: large filled circle in option color.
    const optionSel = node.filter((d) => d.type === 'option');
    optionSel
      .append('circle')
      .attr('r', (d) => nodeRadius(d))
      .attr('fill', (d) => colorForOption(d))
      .attr('stroke', '#1B3A5C')
      .attr('stroke-width', 1.5)
      .attr('opacity', 0.85);

    optionSel
      .append('text')
      .text((d) => truncateLabel(d.label, dimensions.width < 600 ? 10 : 22))
      .attr('text-anchor', 'middle')
      .attr('dy', (d) => nodeRadius(d) + 14)
      .attr('font-size', 11)
      .attr('font-weight', 600)
      .attr('fill', '#1B3A5C')
      .attr('pointer-events', 'none');

    // Voter visuals.
    const voterSel = node.filter((d) => d.type !== 'option');
    voterSel
      .append('circle')
      .attr('r', (d) => nodeRadius(d))
      .attr('fill', (d) => (d.type === 'non_voter' || d.isAbstainer ? '#ECF0F1' : 'white'))
      .attr('stroke', (d) => {
        if (d.is_current_user) return '#F39C12';
        if (d.isAbstainer || d.type === 'non_voter') return VOTE_COLORS.null;
        return '#2E75B6';
      })
      .attr('stroke-width', (d) => {
        if (d.is_current_user) return 3;
        if (d.type === 'non_voter') return 1;
        return 2;
      })
      .attr('stroke-dasharray', (d) => (d.type === 'non_voter' ? '2,2' : null))
      .attr('opacity', (d) => (d.type === 'non_voter' || d.isAbstainer ? 0.5 : 1));

    voterSel
      .filter((d) => d.is_public_delegate)
      .append('circle')
      .attr('r', (d) => nodeRadius(d) + 4)
      .attr('fill', 'none')
      .attr('stroke', '#2E75B6')
      .attr('stroke-width', 1)
      .attr('stroke-dasharray', '3,2')
      .attr('opacity', 0.5);

    voterSel
      .append('text')
      .text((d) => {
        if ((d.type === 'non_voter' || d.isAbstainer) && !d.is_current_user) return '';
        if (dimensions.width < 600) {
          return d.label
            .split(' ')
            .map((w) => w[0])
            .join('')
            .slice(0, 2);
        }
        return d.label.length > 14 ? d.label.slice(0, 12) + '...' : d.label;
      })
      .attr('text-anchor', 'middle')
      .attr('dy', (d) => nodeRadius(d) + 14)
      .attr('font-size', (d) => (d.is_current_user ? 11 : 9))
      .attr('font-weight', (d) => (d.is_current_user ? 600 : 400))
      .attr('fill', '#2C3E50')
      .attr('pointer-events', 'none');

    // Hover handlers.
    node
      .on('mouseenter', (event, d) => {
        if (d.type === 'option') {
          // Hover-to-isolate: highlight voters with weight >= threshold to this option.
          voterSel
            .selectAll('circle')
            .attr('opacity', (n) => {
              if (n.type === 'non_voter' || n.isAbstainer) return 0.15;
              const w = (n.optionWeights || []).find((x) => x.optionId === d.id);
              return w && w.weight >= HOVER_ISOLATE_THRESHOLD ? 1 : 0.2;
            });
          link.attr('stroke-opacity', 0.08);
        } else {
          // Voter hover: highlight delegations + the options pulling them.
          link
            .attr('stroke-opacity', (e) =>
              (e.source.id || e.source) === d.id || (e.target.id || e.target) === d.id ? 0.9 : 0.08
            )
            .attr('stroke-width', (e) =>
              (e.source.id || e.source) === d.id || (e.target.id || e.target) === d.id ? 2.5 : 0.8
            );
          const myOptionIds = new Set((d.optionWeights || []).map((w) => w.optionId));
          voterSel.selectAll('circle').attr('opacity', (n) => (n.id === d.id ? 1 : 0.25));
          // Restore connected voters.
          validEdges.forEach((e) => {
            const sid = e.source.id || e.source;
            const tid = e.target.id || e.target;
            if (sid === d.id || tid === d.id) {
              voterSel
                .filter((n) => n.id === sid || n.id === tid)
                .selectAll('circle')
                .attr('opacity', 1);
            }
          });
          optionSel
            .selectAll('circle')
            .attr('opacity', (n) => (myOptionIds.has(n.id) ? 0.95 : 0.25));
        }

        const rect = svgRef.current.getBoundingClientRect();
        setTooltip({
          x: event.clientX - rect.left,
          y: event.clientY - rect.top - 10,
          node: d,
        });
      })
      .on('mouseleave', () => {
        link.attr('stroke-opacity', 0.45).attr('stroke-width', 1.2);
        voterSel.selectAll('circle').attr('opacity', (d) =>
          d.type === 'non_voter' || d.isAbstainer ? 0.5 : 1
        );
        optionSel.selectAll('circle').attr('opacity', 0.85);
        setTooltip(null);
      })
      .on('click', handleNodeClick);

    simulation.on('tick', () => {
      link.each(function (d) {
        const dx = d.target.x - d.source.x;
        const dy = d.target.y - d.source.y;
        const dist = Math.sqrt(dx * dx + dy * dy) || 1;
        const targetR = nodeRadius(d.target) + 3;
        const ratio = (dist - targetR) / dist;
        d3.select(this)
          .attr('x1', d.source.x)
          .attr('y1', d.source.y)
          .attr('x2', d.source.x + dx * ratio)
          .attr('y2', d.source.y + dy * ratio);
      });
      node.attr('transform', (d) => `translate(${d.x},${d.y})`);
    });

    return () => {
      simulation.stop();
    };
    // optionEnabled handled via enabledRef so toggles don't rebuild the simulation.
  }, [data, dimensions, handleNodeClick, showNonVoters, hideAbstainers, options, votingMethod]);

  function resetZoom() {
    if (!data || !svgRef.current) return;
    const svg = d3.select(svgRef.current);
    const { width, height } = dimensions;
    const allNodes = svg.selectAll('.nodes g').data();
    if (!allNodes.length) return;

    let minX = Infinity,
      maxX = -Infinity,
      minY = Infinity,
      maxY = -Infinity;
    allNodes.forEach((n) => {
      if (n.x == null || n.y == null) return;
      const r = nodeRadius(n);
      minX = Math.min(minX, n.x - r);
      maxX = Math.max(maxX, n.x + r);
      minY = Math.min(minY, n.y - r);
      maxY = Math.max(maxY, n.y + r);
    });
    if (!isFinite(minX)) return;

    const padding = 40;
    const bw = maxX - minX + padding * 2;
    const bh = maxY - minY + padding * 2;
    const scale = Math.min(width / bw, height / bh, 1.5);
    const tx = width / 2 - scale * ((minX + maxX) / 2);
    const ty = height / 2 - scale * ((minY + maxY) / 2);

    const zoom = d3
      .zoom()
      .scaleExtent([0.3, 4])
      .on('zoom', (event) => svg.select('g').attr('transform', event.transform));
    svg.transition().duration(500).call(zoom.transform, d3.zoomIdentity.translate(tx, ty).scale(scale));
  }

  if (!data) return null;

  // Detail panel ballot rendering — method-aware.
  function renderBallotDetail(n) {
    const total = options.length;
    if (votingMethod === 'approval') {
      const approvals = n.ballot?.approvals || [];
      if (approvals.length === 0) {
        return <p>Abstained (no options selected)</p>;
      }
      const labels = approvals.map((id) => optionMap.get(id)?.label || id);
      return (
        <div>
          <p className="font-medium">
            Approved {approvals.length} of {total} options:
          </p>
          <ul className="list-disc list-inside text-xs mt-1 space-y-0.5">
            {labels.map((l, i) => (
              <li key={i}>{l}</li>
            ))}
          </ul>
        </div>
      );
    }
    if (votingMethod === 'ranked_choice') {
      const ranking = n.ballot?.ranking || [];
      if (ranking.length === 0) {
        return <p>Abstained (no options ranked)</p>;
      }
      return (
        <div>
          <p className="font-medium">
            Ranked {ranking.length} of {total} options:
          </p>
          <ol className="text-xs mt-1 space-y-0.5">
            {ranking.map((id, i) => (
              <li key={id}>
                <span className="text-gray-400 mr-1">{i + 1}.</span>
                {optionMap.get(id)?.label || id}
              </li>
            ))}
          </ol>
        </div>
      );
    }
    return null;
  }

  const nonVoterCount = data.nodes.filter((n) => n.type === 'non_voter').length;

  return (
    <div ref={containerRef} className="relative">
      <svg
        ref={svgRef}
        width={dimensions.width}
        height={dimensions.height}
        className="bg-white rounded-lg border border-gray-100"
        style={{ maxWidth: '100%' }}
      />

      {/* Top-right controls */}
      <div className="absolute top-2 right-2 flex flex-col gap-1.5 items-end">
        <div className="flex gap-1.5">
          {nonVoterCount > 0 && (
            <button
              onClick={() => setShowNonVoters((v) => !v)}
              className={`text-xs px-2 py-1 border rounded shadow-sm transition-colors ${
                showNonVoters
                  ? 'bg-gray-100 border-gray-300 text-gray-700'
                  : 'bg-white border-gray-200 text-gray-500 hover:bg-gray-50'
              }`}
            >
              {showNonVoters ? 'Hide' : 'Show'} non-voters ({nonVoterCount})
            </button>
          )}
          <button
            onClick={() => setHideAbstainers((v) => !v)}
            className={`text-xs px-2 py-1 border rounded shadow-sm transition-colors ${
              hideAbstainers
                ? 'bg-gray-100 border-gray-300 text-gray-700'
                : 'bg-white border-gray-200 text-gray-500 hover:bg-gray-50'
            }`}
          >
            {hideAbstainers ? 'Show' : 'Hide'} abstainers
          </button>
          <button
            onClick={resetZoom}
            className="text-xs px-2 py-1 bg-white border border-gray-200 rounded text-gray-500 hover:bg-gray-50 shadow-sm"
          >
            Reset view
          </button>
        </div>

        {/* Option toggles */}
        {options.length > 0 && (
          <div className="bg-white border border-gray-200 rounded shadow-sm p-2 max-w-[200px]">
            <p className="text-[10px] font-semibold text-gray-500 uppercase tracking-wide mb-1">
              Options
            </p>
            <div className="space-y-0.5">
              {options.map((o) => (
                <label key={o.id} className="flex items-center gap-1.5 text-[11px] cursor-pointer">
                  <input
                    type="checkbox"
                    checked={optionEnabled[o.id] !== false}
                    onChange={(e) =>
                      setOptionEnabled((prev) => ({ ...prev, [o.id]: e.target.checked }))
                    }
                    className="w-3 h-3"
                  />
                  <span
                    className="inline-block w-2.5 h-2.5 rounded-full shrink-0"
                    style={{ backgroundColor: colorForOption(o) }}
                  />
                  <span className="truncate text-gray-700" title={o.label}>
                    {o.label}
                  </span>
                </label>
              ))}
            </div>
          </div>
        )}
      </div>

      {/* Tooltip */}
      {tooltip && (
        <div
          className="absolute pointer-events-none bg-white border border-gray-200 rounded-lg shadow-lg px-3 py-2 text-xs z-10"
          style={{ left: tooltip.x + 12, top: tooltip.y - 8, maxWidth: 260 }}
        >
          {tooltip.node.type === 'option' ? (
            <>
              <div className="font-semibold text-[#1B3A5C]">{tooltip.node.label}</div>
              <div className="text-gray-500 mt-0.5">
                {votingMethod === 'approval'
                  ? `${tooltip.node.approval_count} approval${
                      tooltip.node.approval_count === 1 ? '' : 's'
                    }`
                  : `${tooltip.node.first_pref_count} first-preference vote${
                      tooltip.node.first_pref_count === 1 ? '' : 's'
                    }`}
              </div>
            </>
          ) : (
            <>
              <div className="font-semibold text-[#1B3A5C]">{tooltip.node.label}</div>
              {tooltip.node.is_public_delegate && (
                <div className="text-green-600 text-[10px]">Public Delegate</div>
              )}
              <div className="mt-1 text-gray-600">
                {tooltip.node.isAbstainer
                  ? votingMethod === 'approval'
                    ? 'Abstained (no options selected)'
                    : 'Abstained (no options ranked)'
                  : votingMethod === 'approval'
                  ? `${tooltip.node.ballot?.approvals?.length || 0} of ${
                      options.length
                    } options approved`
                  : `${tooltip.node.ballot?.ranking?.length || 0} of ${
                      options.length
                    } options ranked`}
              </div>
              {tooltip.node.delegator_count > 0 && (
                <div className="text-gray-500 mt-0.5">
                  {tooltip.node.delegator_count} delegator
                  {tooltip.node.delegator_count > 1 ? 's' : ''} ({tooltip.node.total_vote_weight}{' '}
                  total weight)
                </div>
              )}
            </>
          )}
        </div>
      )}

      {/* Detail panel — voters only */}
      {selectedNode && selectedNode.type !== 'option' && (
        <div className="absolute bottom-2 left-2 right-2 bg-white border border-gray-200 rounded-xl shadow-lg p-4 text-sm z-10 md:left-auto md:right-2 md:w-80 md:bottom-2">
          <div className="flex justify-between items-start mb-2">
            <div>
              <div className="font-semibold text-[#1B3A5C]">{selectedNode.label}</div>
              {selectedNode.is_public_delegate && (
                <span className="text-[10px] text-green-600 bg-green-50 px-1.5 py-0.5 rounded">
                  Public Delegate
                </span>
              )}
            </div>
            <button
              onClick={() => setSelectedNode(null)}
              className="text-gray-400 hover:text-gray-600 text-lg leading-none"
            >
              &times;
            </button>
          </div>
          <div className="space-y-1.5 text-gray-600">
            {selectedNode.ballot ? (
              <div>
                {renderBallotDetail(selectedNode)}
                {selectedNode.vote_source === 'delegation' && (
                  <p className="text-xs text-gray-400 mt-1">via delegation</p>
                )}
              </div>
            ) : (
              <p className="text-gray-400">Has not voted on this proposal</p>
            )}
            {selectedNode.delegator_count > 0 && (
              <p className="text-xs">
                {selectedNode.delegator_count} user
                {selectedNode.delegator_count > 1 ? 's' : ''} delegate to this person (total weight:{' '}
                {selectedNode.total_vote_weight})
              </p>
            )}
            {selectedNode.is_current_user && (
              <p className="text-[#2E75B6] font-medium text-xs mt-2">This is you.</p>
            )}
            {selectedNode.label && (
              <Link
                to={`/users/${selectedNode.id}`}
                className="inline-block mt-2 text-xs text-[#2E75B6] hover:underline"
              >
                View Profile
              </Link>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
