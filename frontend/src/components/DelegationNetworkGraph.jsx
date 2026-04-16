import { useRef, useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import * as d3 from 'd3';

function nodeRadius(d) {
  if (d._isCenter) return 22;
  return Math.max(10, Math.min(20, 10 + (d.total_delegators || 0) * 0.5));
}

export default function DelegationNetworkGraph({ data, onChangeDelegate, onRemoveDelegate }) {
  const svgRef = useRef(null);
  const containerRef = useRef(null);
  const [tooltip, setTooltip] = useState(null);
  const [selectedNode, setSelectedNode] = useState(null);
  const [dimensions, setDimensions] = useState({ width: 700, height: 360 });

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const observer = new ResizeObserver(entries => {
      const { width } = entries[0].contentRect;
      if (width > 0) setDimensions({ width, height: Math.max(280, Math.min(400, width * 0.45)) });
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    if (!data || !svgRef.current) return;

    const { width, height } = dimensions;
    const svg = d3.select(svgRef.current);
    svg.selectAll('*').remove();

    // Build nodes: center + delegates + delegators
    const centerNode = {
      id: data.center.id,
      label: data.center.label,
      _isCenter: true,
      relationship: 'self',
      topics: [],
      is_public_delegate: false,
      total_delegators: 0,
    };

    const nodes = [centerNode, ...data.nodes.map(n => ({ ...n, _isCenter: false }))];
    const edges = data.edges.map(e => ({ ...e }));

    // Zoom
    const zoom = d3.zoom()
      .scaleExtent([0.4, 3])
      .on('zoom', (event) => g.attr('transform', event.transform));
    svg.call(zoom);

    const g = svg.append('g');

    // Arrow defs
    const defs = svg.append('defs');
    const edgeColors = new Set();
    edges.forEach(e => e.topics.forEach(t => edgeColors.add(t.color)));
    edgeColors.add('#95a5a6');
    edgeColors.forEach(color => {
      defs.append('marker')
        .attr('id', `net-arrow-${color.replace('#', '')}`)
        .attr('viewBox', '0 -5 10 10')
        .attr('refX', 22)
        .attr('refY', 0)
        .attr('markerWidth', 5)
        .attr('markerHeight', 5)
        .attr('orient', 'auto')
        .append('path')
        .attr('d', 'M0,-5L10,0L0,5')
        .attr('fill', color)
        .attr('opacity', 0.6);
    });

    // Flatten edges into individual lines per topic
    const flatEdges = [];
    edges.forEach(e => {
      const topicList = e.topics.length ? e.topics : [{ name: 'Global', color: '#95a5a6' }];
      topicList.forEach((t, i) => {
        flatEdges.push({
          source: e.source,
          target: e.target,
          topic_name: t.name,
          topic_color: t.color,
          direction: e.direction,
          offset: i * 3, // offset for multiple edges between same pair
        });
      });
    });

    // Pre-compute topic grouping per node (used by collision + labels)
    const topicsByNode = new Map();
    flatEdges.forEach(e => {
      const otherId = e.direction === 'outgoing' ? e.target : e.source;
      if (!topicsByNode.has(otherId)) topicsByNode.set(otherId, []);
      const list = topicsByNode.get(otherId);
      if (!list.some(t => t.name === e.topic_name)) {
        list.push({ name: e.topic_name, color: e.topic_color });
      }
    });

    // Simulation
    const simulation = d3.forceSimulation(nodes)
      .force('charge', d3.forceManyBody().strength(-300))
      .force('center', d3.forceCenter(width / 2, height / 2))
      .force('link', d3.forceLink(flatEdges).id(d => d.id).distance(110).strength(0.5))
      .force('x', d3.forceX()
        .x(d => {
          if (d._isCenter) return width / 2;
          if (d.relationship === 'delegate') return width * 0.75;
          return width * 0.25;
        })
        .strength(0.2))
      .force('y', d3.forceY(height / 2).strength(0.1))
      .force('collision', d3.forceCollide().radius(d => {
        if (d._isCenter) return nodeRadius(d) + 10;
        const topicCount = topicsByNode.get(d.id)?.length || 0;
        return nodeRadius(d) + 12 + Math.min(topicCount, 3) * 6;
      }));

    // Edges
    const link = g.append('g').selectAll('line')
      .data(flatEdges)
      .join('line')
      .attr('stroke', d => d.topic_color)
      .attr('stroke-width', 1.5)
      .attr('stroke-opacity', 0.5)
      .attr('marker-end', d => `url(#net-arrow-${d.topic_color.replace('#', '')})`);

    // Nodes
    const node = g.append('g').selectAll('g')
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
        if (d._isCenter) return '#1B3A5C';
        if (d.relationship === 'delegate') return '#EBF5FB';
        return '#FEF9E7';
      })
      .attr('stroke', d => {
        if (d._isCenter) return '#F39C12';
        if (d.is_public_delegate) return '#2D8A56';
        if (d.relationship === 'delegate') return '#2E75B6';
        return '#F39C12';
      })
      .attr('stroke-width', d => d._isCenter ? 3 : 2);

    // Public delegate double ring
    node.filter(d => d.is_public_delegate && !d._isCenter)
      .append('circle')
      .attr('r', d => nodeRadius(d) + 4)
      .attr('fill', 'none')
      .attr('stroke', '#2D8A56')
      .attr('stroke-width', 1)
      .attr('stroke-dasharray', '3,2')
      .attr('opacity', 0.5);

    // Labels
    node.append('text')
      .text(d => {
        if (dimensions.width < 500) {
          return d.label.split(' ').map(w => w[0]).join('').slice(0, 2);
        }
        return d.label.length > 12 ? d.label.slice(0, 10) + '..' : d.label;
      })
      .attr('text-anchor', 'middle')
      .attr('dy', d => nodeRadius(d) + 14)
      .attr('font-size', d => d._isCenter ? 11 : 9)
      .attr('font-weight', d => d._isCenter ? 700 : 400)
      .attr('fill', d => d._isCenter ? '#1B3A5C' : '#2C3E50')
      .attr('pointer-events', 'none');

    // Center label inside the node
    node.filter(d => d._isCenter)
      .append('text')
      .text('You')
      .attr('text-anchor', 'middle')
      .attr('dy', 4)
      .attr('font-size', 10)
      .attr('font-weight', 700)
      .attr('fill', 'white')
      .attr('pointer-events', 'none');

    // Topic labels stacked below each non-center node (uses topicsByNode computed above)
    const topicLabelG = g.append('g').attr('class', 'topic-labels');
    const topicLabels = [];
    topicsByNode.forEach((topics, nodeId) => {
      const display = topics.length > 2
        ? [...topics.slice(0, 2), { name: `+${topics.length - 2} more`, color: '#95a5a6' }]
        : topics;
      display.forEach((t, i) => {
        topicLabels.push({ nodeId, text: t.name, color: t.color, offset: i });
      });
    });

    const topicLabelEls = topicLabelG.selectAll('text')
      .data(topicLabels)
      .join('text')
      .attr('font-size', 7)
      .attr('fill', d => d.color)
      .attr('text-anchor', 'middle')
      .attr('pointer-events', 'none')
      .attr('opacity', 0.8)
      .text(d => d.text);

    // Hover
    node.on('mouseenter', (event, d) => {
      if (d._isCenter) return;
      link.attr('stroke-opacity', e =>
        (e.source.id || e.source) === d.id || (e.target.id || e.target) === d.id ? 0.9 : 0.1
      );
      const rect = svgRef.current.getBoundingClientRect();
      setTooltip({
        x: event.clientX - rect.left,
        y: event.clientY - rect.top - 10,
        node: d,
      });
    })
    .on('mouseleave', () => {
      link.attr('stroke-opacity', 0.5);
      setTooltip(null);
    })
    .on('click', (event, d) => {
      if (d._isCenter) return;
      event.stopPropagation();
      setSelectedNode(prev => prev?.id === d.id ? null : d);
    });

    svg.on('click', () => setSelectedNode(null));

    // Build a quick lookup from node id to simulation node for label positioning
    const nodeById = new Map(nodes.map(n => [n.id, n]));

    // Tick
    simulation.on('tick', () => {
      link
        .attr('x1', d => d.source.x)
        .attr('y1', d => d.source.y)
        .attr('x2', d => d.target.x)
        .attr('y2', d => d.target.y);
      node.attr('transform', d => `translate(${d.x},${d.y})`);
      topicLabelEls.each(function(d) {
        const n = nodeById.get(d.nodeId);
        if (!n) return;
        const baseY = nodeRadius(n) + 26; // below node name label
        d3.select(this)
          .attr('x', n.x)
          .attr('y', n.y + baseY + d.offset * 11);
      });
    });

    return () => { simulation.stop(); };
  }, [data, dimensions]);

  if (!data || (data.nodes.length === 0)) return null;

  return (
    <div ref={containerRef} className="relative">
      <svg
        ref={svgRef}
        width={dimensions.width}
        height={dimensions.height}
        className="bg-white rounded-lg border border-gray-100"
        style={{ maxWidth: '100%' }}
      />

      {/* Tooltip */}
      {tooltip && !selectedNode && (
        <div
          className="absolute pointer-events-none bg-white border border-gray-200 rounded-lg shadow-lg px-3 py-2 text-xs z-10"
          style={{ left: tooltip.x + 12, top: tooltip.y - 8, maxWidth: 200 }}
        >
          <div className="font-semibold text-[#1B3A5C]">{tooltip.node.label}</div>
          {tooltip.node.is_public_delegate && (
            <div className="text-green-600 text-[10px]">Public Delegate</div>
          )}
          <div className="mt-1 text-gray-500">
            {tooltip.node.relationship === 'delegate'
              ? `You delegate to them on: ${[...new Set(tooltip.node.topics)].join(', ')}`
              : `Delegates to you on: ${[...new Set(tooltip.node.topics)].join(', ')}`}
          </div>
          {tooltip.node.total_delegators > 0 && (
            <div className="text-gray-400 mt-0.5">
              {tooltip.node.total_delegators} total delegator{tooltip.node.total_delegators > 1 ? 's' : ''}
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
          <div className="text-gray-500 text-xs mb-2">
            {selectedNode.relationship === 'delegate'
              ? `You delegate to them on: ${[...new Set(selectedNode.topics)].join(', ')}`
              : `Delegates to you on: ${[...new Set(selectedNode.topics)].join(', ')}`}
          </div>
          {selectedNode.total_delegators > 0 && (
            <p className="text-xs text-gray-400 mb-2">
              {selectedNode.total_delegators} total delegator{selectedNode.total_delegators > 1 ? 's' : ''}
            </p>
          )}
          {selectedNode.relationship === 'delegate' && (
            <div className="flex gap-2 mt-2">
              <button
                onClick={() => { setSelectedNode(null); onChangeDelegate?.(selectedNode); }}
                className="text-xs px-3 py-1.5 border border-[#2E75B6] text-[#2E75B6] rounded-lg hover:bg-[#2E75B6] hover:text-white transition-colors"
              >
                Change delegate
              </button>
              <button
                onClick={() => { setSelectedNode(null); onRemoveDelegate?.(selectedNode); }}
                className="text-xs px-3 py-1.5 border border-red-300 text-red-500 rounded-lg hover:bg-red-50 transition-colors"
              >
                Remove delegation
              </button>
            </div>
          )}
          {selectedNode.relationship === 'delegator' && (
            <p className="text-xs text-gray-400 italic">You cannot change someone else's delegation.</p>
          )}
          <Link
            to={`/users/${selectedNode.id}`}
            className="inline-block mt-2 text-xs text-[#2E75B6] hover:underline"
          >
            View Profile
          </Link>
        </div>
      )}
    </div>
  );
}
