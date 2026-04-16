import { useRef, useEffect, useState, useCallback } from 'react';
import { Link } from 'react-router-dom';
import * as d3 from 'd3';

const VOTE_COLORS = {
  yes: '#2D8A56',
  no: '#C0392B',
  abstain: '#7F8C8D',
  null: '#BDC3C7',
};

const ZONE_COLORS = {
  yes: 'rgba(45, 138, 86, 0.06)',
  no: 'rgba(192, 57, 43, 0.06)',
  abstain: 'rgba(127, 140, 141, 0.06)',
};

function nodeRadius(d) {
  if (d.type === 'non_voter') return 4;
  return Math.max(6, Math.min(24, 6 + d.total_vote_weight * 2.5));
}

export default function VoteFlowGraph({ data, onNodeClick }) {
  const svgRef = useRef(null);
  const containerRef = useRef(null);
  const [tooltip, setTooltip] = useState(null);
  const [selectedNode, setSelectedNode] = useState(null);
  const [showNonVoters, setShowNonVoters] = useState(false);
  const [dimensions, setDimensions] = useState({ width: 800, height: 500 });
  const simulationRef = useRef(null);

  // Observe container resize
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const observer = new ResizeObserver(entries => {
      const { width } = entries[0].contentRect;
      if (width > 0) setDimensions({ width, height: Math.max(400, Math.min(600, width * 0.6)) });
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  const handleNodeClick = useCallback((event, d) => {
    event.stopPropagation();
    setSelectedNode(prev => prev?.id === d.id ? null : d);
    if (onNodeClick) onNodeClick(d);
  }, [onNodeClick]);

  useEffect(() => {
    if (!data || !svgRef.current) return;

    const { width, height } = dimensions;
    const svg = d3.select(svgRef.current);
    svg.selectAll('*').remove();

    // Deep-copy data so D3 mutation doesn't break React
    const allNodes = data.nodes.map(n => ({ ...n }));
    const nodes = showNonVoters ? allNodes : allNodes.filter(n => n.type !== 'non_voter');
    const edges = data.edges.map(e => ({ ...e }));

    // Deduplicate edges (same source-target pair)
    const edgeKey = e => `${e.source}-${e.target}`;
    const uniqueEdges = [];
    const seen = new Set();
    for (const e of edges) {
      const k = edgeKey(e);
      if (!seen.has(k)) { seen.add(k); uniqueEdges.push(e); }
    }

    // Create node map for edge linkage
    const nodeMap = new Map(nodes.map(n => [n.id, n]));

    // Filter edges to only those whose source/target exist
    const validEdges = uniqueEdges.filter(e => nodeMap.has(e.source) && nodeMap.has(e.target));

    // Zoom
    const zoom = d3.zoom()
      .scaleExtent([0.3, 4])
      .on('zoom', (event) => g.attr('transform', event.transform));
    svg.call(zoom);
    svg.on('click', () => setSelectedNode(null));

    const g = svg.append('g');

    // Defs: arrow markers
    const defs = svg.append('defs');

    // One marker per topic color
    const markerColors = new Set(validEdges.map(e => e.topic_color || '#95a5a6'));
    markerColors.forEach(color => {
      defs.append('marker')
        .attr('id', `arrow-${color.replace('#', '')}`)
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

    // Background zones — large half-planes that survive zoom/pan
    const BIG = 10000;
    const centerX = width / 2;
    const splitGap = 2; // px gap between yes/no regions
    const bottomZoneY = height * 0.78; // abstain/non-voter area starts here

    // Yes region (left half, upper area)
    g.append('rect')
      .attr('x', -BIG).attr('y', -BIG)
      .attr('width', centerX - splitGap + BIG).attr('height', bottomZoneY + BIG)
      .attr('fill', ZONE_COLORS.yes);
    g.append('text')
      .attr('x', centerX * 0.5).attr('y', 24)
      .attr('text-anchor', 'middle')
      .attr('fill', VOTE_COLORS.yes)
      .attr('font-size', 13).attr('font-weight', 600).attr('opacity', 0.35)
      .text('Yes');

    // No region (right half, upper area)
    g.append('rect')
      .attr('x', centerX + splitGap).attr('y', -BIG)
      .attr('width', BIG + centerX).attr('height', bottomZoneY + BIG)
      .attr('fill', ZONE_COLORS.no);
    g.append('text')
      .attr('x', centerX + centerX * 0.5).attr('y', 24)
      .attr('text-anchor', 'middle')
      .attr('fill', VOTE_COLORS.no)
      .attr('font-size', 13).attr('font-weight', 600).attr('opacity', 0.35)
      .text('No');

    // Simulation
    const simulation = d3.forceSimulation(nodes)
      .force('charge', d3.forceManyBody().strength(d => d.type === 'non_voter' ? -40 : -120))
      .force('link', d3.forceLink(validEdges).id(d => d.id).distance(60).strength(0.3))
      .force('x', d3.forceX()
        .x(d => {
          if (d.vote === 'yes') return width * 0.25;
          if (d.vote === 'no') return width * 0.75;
          if (d.vote === 'abstain') return width * 0.5;
          return width * 0.5;
        })
        .strength(0.15))
      .force('y', d3.forceY()
        .y(d => {
          if (d.vote === 'abstain' || d.vote === null) return height * 0.88;
          return height * 0.42;
        })
        .strength(d => (d.vote === 'abstain' || d.type === 'non_voter') ? 0.2 : 0.05))
      .force('collision', d3.forceCollide().radius(d => nodeRadius(d) + 6));

    simulationRef.current = simulation;

    // Edges
    const edgeG = g.append('g').attr('class', 'edges');
    const link = edgeG.selectAll('line')
      .data(validEdges)
      .join('line')
      .attr('stroke', d => d.topic_color || '#95a5a6')
      .attr('stroke-width', 1.2)
      .attr('stroke-opacity', 0.45)
      .attr('marker-end', d => `url(#arrow-${(d.topic_color || '#95a5a6').replace('#', '')})`);

    // Nodes
    const nodeG = g.append('g').attr('class', 'nodes');
    const node = nodeG.selectAll('g')
      .data(nodes)
      .join('g')
      .attr('cursor', 'pointer')
      .call(d3.drag()
        .on('start', (event, d) => {
          if (!event.active) simulation.alphaTarget(0.3).restart();
          d.fx = d.x; d.fy = d.y;
        })
        .on('drag', (event, d) => { d.fx = event.x; d.fy = event.y; })
        .on('end', (event, d) => {
          if (!event.active) simulation.alphaTarget(0);
          d.fx = null; d.fy = null;
        })
      );

    // Node circles
    node.append('circle')
      .attr('r', d => nodeRadius(d))
      .attr('fill', d => {
        if (d.type === 'non_voter') return '#ECF0F1';
        return 'white';
      })
      .attr('stroke', d => {
        if (d.is_current_user) return '#F39C12';
        return VOTE_COLORS[d.vote] || VOTE_COLORS.null;
      })
      .attr('stroke-width', d => {
        if (d.is_current_user) return 3;
        if (d.type === 'non_voter') return 1;
        return 2;
      })
      .attr('stroke-dasharray', d => d.type === 'non_voter' ? '2,2' : null)
      .attr('opacity', d => d.type === 'non_voter' ? 0.5 : 1);

    // Public delegate double ring
    node.filter(d => d.is_public_delegate)
      .append('circle')
      .attr('r', d => nodeRadius(d) + 4)
      .attr('fill', 'none')
      .attr('stroke', d => VOTE_COLORS[d.vote] || '#95a5a6')
      .attr('stroke-width', 1)
      .attr('stroke-dasharray', '3,2')
      .attr('opacity', 0.5);

    // Node labels
    node.append('text')
      .text(d => {
        if (d.type === 'non_voter' && !d.is_current_user) return '';
        // Mobile: use initials
        if (dimensions.width < 600) {
          return d.label.split(' ').map(w => w[0]).join('').slice(0, 2);
        }
        return d.label.length > 14 ? d.label.slice(0, 12) + '...' : d.label;
      })
      .attr('text-anchor', 'middle')
      .attr('dy', d => nodeRadius(d) + 14)
      .attr('font-size', d => d.is_current_user ? 11 : 9)
      .attr('font-weight', d => d.is_current_user ? 600 : 400)
      .attr('fill', '#2C3E50')
      .attr('pointer-events', 'none');

    // Hover and click
    node.on('mouseenter', (event, d) => {
      // Highlight connected edges
      link.attr('stroke-opacity', e =>
        (e.source.id || e.source) === d.id || (e.target.id || e.target) === d.id ? 0.9 : 0.08
      ).attr('stroke-width', e =>
        (e.source.id || e.source) === d.id || (e.target.id || e.target) === d.id ? 2.5 : 0.8
      );
      // Dim other nodes
      node.selectAll('circle').attr('opacity', n =>
        n.id === d.id ? 1 : 0.3
      );
      // Restore connected nodes
      validEdges.forEach(e => {
        const sid = e.source.id || e.source;
        const tid = e.target.id || e.target;
        if (sid === d.id || tid === d.id) {
          node.filter(n => n.id === sid || n.id === tid)
            .selectAll('circle').attr('opacity', 1);
        }
      });

      const rect = svgRef.current.getBoundingClientRect();
      setTooltip({
        x: event.clientX - rect.left,
        y: event.clientY - rect.top - 10,
        node: d,
      });
    })
    .on('mouseleave', () => {
      link.attr('stroke-opacity', 0.45).attr('stroke-width', 1.2);
      node.selectAll('circle').attr('opacity', d => d.type === 'non_voter' ? 0.5 : 1);
      setTooltip(null);
    })
    .on('click', handleNodeClick);

    // Tick — soft zone enforcement
    // Only enforce the left/right boundary for yes/no and the bottom boundary
    // for abstain/non-voters. Let the charge + collision forces handle 2D spread.
    simulation.on('tick', () => {
      nodes.forEach(d => {
        if (d.vote === 'yes') {
          // Keep in left half
          d.x = Math.min(d.x, centerX - splitGap - 4);
        } else if (d.vote === 'no') {
          // Keep in right half
          d.x = Math.max(d.x, centerX + splitGap + 4);
        } else {
          // Abstain / non-voter — nudge below the coloured zones
          if (d.y < bottomZoneY) d.y = bottomZoneY + 4;
        }
      });

      // Shorten edges so arrows land at the target node's border, not under it
      link.each(function(d) {
        const dx = d.target.x - d.source.x;
        const dy = d.target.y - d.source.y;
        const dist = Math.sqrt(dx * dx + dy * dy) || 1;
        const targetR = nodeRadius(d.target) + 3; // gap for arrowhead
        const ratio = (dist - targetR) / dist;

        d3.select(this)
          .attr('x1', d.source.x)
          .attr('y1', d.source.y)
          .attr('x2', d.source.x + dx * ratio)
          .attr('y2', d.source.y + dy * ratio);
      });
      node.attr('transform', d => `translate(${d.x},${d.y})`);
    });

    return () => { simulation.stop(); };
  }, [data, dimensions, handleNodeClick, showNonVoters]);

  function resetZoom() {
    if (!data || !svgRef.current) return;
    const svg = d3.select(svgRef.current);
    const { width, height } = dimensions;

    // Calculate bounding box of all visible nodes
    const allNodes = svg.selectAll('.nodes g').data();
    if (!allNodes.length) return;

    let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
    allNodes.forEach(n => {
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
    const scale = Math.min(width / bw, height / bh, 1.5); // cap at 1.5x
    const tx = width / 2 - scale * ((minX + maxX) / 2);
    const ty = height / 2 - scale * ((minY + maxY) / 2);

    const zoom = d3.zoom().scaleExtent([0.3, 4])
      .on('zoom', (event) => svg.select('g').attr('transform', event.transform));
    svg.transition().duration(500).call(
      zoom.transform,
      d3.zoomIdentity.translate(tx, ty).scale(scale)
    );
  }

  if (!data) return null;

  return (
    <div ref={containerRef} className="relative">
      <svg
        ref={svgRef}
        width={dimensions.width}
        height={dimensions.height}
        className="bg-white rounded-lg border border-gray-100"
        style={{ maxWidth: '100%' }}
      />

      {/* Controls */}
      <div className="absolute top-2 right-2 flex gap-1.5">
        {(() => {
          const nonVoterCount = data.nodes.filter(n => n.type === 'non_voter').length;
          return nonVoterCount > 0 && (
            <button
              onClick={() => setShowNonVoters(v => !v)}
              className={`text-xs px-2 py-1 border rounded shadow-sm transition-colors ${
                showNonVoters
                  ? 'bg-gray-100 border-gray-300 text-gray-700'
                  : 'bg-white border-gray-200 text-gray-500 hover:bg-gray-50'
              }`}
            >
              {showNonVoters ? 'Hide' : 'Show'} non-voters ({nonVoterCount})
            </button>
          );
        })()}
        <button
          onClick={resetZoom}
          className="text-xs px-2 py-1 bg-white border border-gray-200 rounded text-gray-500 hover:bg-gray-50 shadow-sm"
        >
          Reset view
        </button>
      </div>

      {/* Tooltip */}
      {tooltip && (
        <div
          className="absolute pointer-events-none bg-white border border-gray-200 rounded-lg shadow-lg px-3 py-2 text-xs z-10"
          style={{
            left: tooltip.x + 12,
            top: tooltip.y - 8,
            maxWidth: 220,
          }}
        >
          <div className="font-semibold text-[#1B3A5C]">{tooltip.node.label}</div>
          {tooltip.node.is_public_delegate && (
            <div className="text-green-600 text-[10px]">Public Delegate</div>
          )}
          <div className="mt-1">
            {tooltip.node.vote ? (
              <span className={`font-medium ${
                tooltip.node.vote === 'yes' ? 'text-[#2D8A56]'
                : tooltip.node.vote === 'no' ? 'text-[#C0392B]'
                : 'text-gray-500'
              }`}>
                {tooltip.node.vote.toUpperCase()}
                {tooltip.node.vote_source === 'delegation' ? ' (via delegation)' : ' (direct)'}
              </span>
            ) : (
              <span className="text-gray-400">Not voted</span>
            )}
          </div>
          {tooltip.node.delegator_count > 0 && (
            <div className="text-gray-500 mt-0.5">
              {tooltip.node.delegator_count} delegator{tooltip.node.delegator_count > 1 ? 's' : ''} ({tooltip.node.total_vote_weight} total weight)
            </div>
          )}
        </div>
      )}

      {/* Selected node detail panel */}
      {selectedNode && (
        <div className="absolute bottom-2 left-2 right-2 bg-white border border-gray-200 rounded-xl shadow-lg p-4 text-sm z-10 md:left-auto md:right-2 md:w-72 md:bottom-2">
          <div className="flex justify-between items-start mb-2">
            <div>
              <div className="font-semibold text-[#1B3A5C]">{selectedNode.label}</div>
              {selectedNode.is_public_delegate && (
                <span className="text-[10px] text-green-600 bg-green-50 px-1.5 py-0.5 rounded">Public Delegate</span>
              )}
            </div>
            <button onClick={() => setSelectedNode(null)} className="text-gray-400 hover:text-gray-600 text-lg leading-none">&times;</button>
          </div>
          <div className="space-y-1.5 text-gray-600">
            {selectedNode.vote ? (
              <p>
                Vote: <span className={`font-semibold ${
                  selectedNode.vote === 'yes' ? 'text-[#2D8A56]'
                  : selectedNode.vote === 'no' ? 'text-[#C0392B]'
                  : 'text-gray-500'
                }`}>{selectedNode.vote.toUpperCase()}</span>
                {selectedNode.vote_source === 'delegation' ? ' (via delegation)' : ' (direct)'}
              </p>
            ) : (
              <p className="text-gray-400">Has not voted on this proposal</p>
            )}
            {selectedNode.delegator_count > 0 && (
              <p>{selectedNode.delegator_count} user{selectedNode.delegator_count > 1 ? 's' : ''} delegate to this person (total weight: {selectedNode.total_vote_weight})</p>
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
