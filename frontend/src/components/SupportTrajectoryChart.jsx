/**
 * Phase 22 F1+F2+F4 — Support Trajectory Chart.
 *
 * Renders the support trajectory for a proposal using recharts. Two
 * variants based on `voting_method` from the backend response:
 *
 *   - Binary: single smoothed support_fraction line over time with a
 *     pass_threshold reference line and a translucent area fill.
 *   - Multi-option (approval, ranked_choice): one line per top-N option
 *     by final tally (default top-5; "show all" toggle expands to all
 *     options that appear in any snapshot's option_totals). Below the
 *     line chart, a winner-over-time ribbon (raw SVG) reads each
 *     snapshot's `winners` list and colors segments by the winning
 *     option's color, matching the line chart's palette. Tied moments
 *     render a secondary thin stacked bar showing all tied options.
 *
 * SRR overlay (F2): when `srr_annotations` is non-null, vertical
 * <ReferenceLine>s mark stable-window opening, extension grants, and
 * destabilization events. A <ReferenceDot> at voting_end signals the
 * close trigger.
 *
 * Accessibility (F4): aria-live summary on data load, "Show as data
 * table" toggle exposes raw snapshot data as a semantic <table>.
 *
 * Backend response shape per Phase 22 B2 (see
 * phase22_support_trajectory_chart_spec.md §D3). Old-shape snapshots
 * (option_totals === null) degrade gracefully: per-option lines are
 * suppressed, but the winner bar still renders from the `winners`
 * field.
 *
 * Props:
 *   - proposalId (string, required): the proposal whose trajectory to
 *     fetch.
 *   - expanded (bool, required): when false, renders nothing (parent
 *     toggles this to collapse and unmount per D9 + spec line 388).
 *   - optionLabels ({id: label}, optional): label map for multi-option
 *     chart legend / tooltips. Parent supplies from tally.option_labels.
 *   - proposal (object, optional): the proposal record. Used for
 *     pass_threshold reference line on binary charts.
 *   - onError ((err) => void, optional): callback invoked on fetch
 *     failure for parent-level reporting.
 */
import { useState, useEffect, useMemo } from 'react';
import {
  LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer,
  ReferenceLine, ReferenceDot, Area, ComposedChart, Legend,
} from 'recharts';
import api from '../api';
import { colorForOption, OPTION_PALETTE } from './voteFlowGraphUtils';

// SRR overlay color tokens — per spec F2 section.
const SRR_COLORS = {
  stableWindow: '#9CA3AF',   // gray
  extension: '#2563EB',      // blue
  destabilization: '#D97706',// amber
  achieved: '#2D8A56',       // green
  forceClose: '#C0392B',     // red
  voteEnd: '#9CA3AF',        // gray (admin / generic close)
};

// Format an ISO timestamp into a compact x-axis tick label. Picks
// "HH:MM" for windows under a day, "MMM D HH:MM" for multi-day windows.
function formatTickLabel(ts, spanMs) {
  const d = new Date(ts);
  if (Number.isNaN(d.getTime())) return '';
  if (spanMs < 24 * 60 * 60 * 1000) {
    return d.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
  }
  return d.toLocaleString([], {
    month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit',
  });
}

function formatFullTimestamp(ts) {
  const d = new Date(ts);
  if (Number.isNaN(d.getTime())) return ts || '';
  return d.toLocaleString([], {
    month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit',
  });
}

// Cycle through OPTION_PALETTE for a stable color per option id.
// Mirrors voteFlowGraphUtils.colorForOption but takes a list-derived
// index when we don't have the option's display_order (e.g. when the
// option only appears in option_totals keys, not in proposal.options).
function colorForOptionId(optionId, idxFallback, optionsById) {
  const opt = optionsById?.[optionId];
  if (opt) return colorForOption(opt);
  const i = idxFallback ?? 0;
  return OPTION_PALETTE[i % OPTION_PALETTE.length];
}

function Spinner() {
  return (
    <div className="flex items-center gap-2 text-sm text-gray-500 py-6">
      <svg className="animate-spin h-4 w-4 text-gray-400" viewBox="0 0 24 24" fill="none">
        <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
        <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z" />
      </svg>
      <span>Loading trajectory…</span>
    </div>
  );
}

function ErrorState({ message, onRetry }) {
  return (
    <div className="bg-red-50 border border-red-200 rounded-lg p-3 text-sm text-red-700 flex items-center justify-between gap-3">
      <span>Could not load trajectory: {message}</span>
      <button
        onClick={onRetry}
        className="px-2 py-1 text-xs border border-red-300 rounded hover:bg-red-100 transition-colors shrink-0"
      >
        Retry
      </button>
    </div>
  );
}

function EmptyState() {
  return (
    <div className="text-sm text-gray-500 py-6 text-center">
      No trajectory data yet — snapshots are captured every 5 minutes during voting.
    </div>
  );
}

// Custom tooltip for the binary line chart.
function BinaryTooltip({ active, payload }) {
  if (!active || !payload || !payload.length) return null;
  const p = payload[0].payload;
  return (
    <div className="bg-white border border-gray-200 rounded-lg shadow-md p-2 text-xs">
      <div className="font-medium text-gray-700">{formatFullTimestamp(p.captured_at)}</div>
      <div className="text-gray-600 mt-0.5">
        Support: <span className="font-semibold">{(p.support_fraction * 100).toFixed(1)}%</span>
      </div>
      <div className="text-gray-500">
        {p.votes_cast} vote{p.votes_cast === 1 ? '' : 's'} cast
      </div>
    </div>
  );
}

// Custom tooltip for the multi-option line chart.
function MultiOptionTooltip({ active, payload, optionLabels }) {
  if (!active || !payload || !payload.length) return null;
  const p = payload[0].payload;
  // Filter to entries that have non-null option keys (recharts passes
  // every <Line>'s dataKey).
  const rows = payload
    .filter((row) => row && row.dataKey && row.dataKey.startsWith('opt:'))
    .sort((a, b) => (b.value || 0) - (a.value || 0));
  return (
    <div className="bg-white border border-gray-200 rounded-lg shadow-md p-2 text-xs max-w-xs">
      <div className="font-medium text-gray-700">{formatFullTimestamp(p.captured_at)}</div>
      <ul className="mt-1 space-y-0.5">
        {rows.map((row) => {
          const id = row.dataKey.slice(4);
          const label = optionLabels?.[id] || id;
          return (
            <li key={id} className="flex items-center gap-2">
              <span
                className="inline-block w-2 h-2 rounded-full shrink-0"
                style={{ backgroundColor: row.color }}
              />
              <span className="text-gray-700 truncate">{label}</span>
              <span className="text-gray-500 ml-auto font-medium">{row.value ?? 0}</span>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

// Winner-over-time ribbon (multi-option only). Renders below the line
// chart, sharing horizontal margins via the outer ResponsiveContainer.
function WinnerOverTimeBar({ snapshots, optionsById, optionLabels, height, leftMargin, rightMargin }) {
  // Hooks must be called unconditionally before any early returns.
  const data = useMemo(() => {
    if (!snapshots || snapshots.length === 0) return null;
    const tMin = new Date(snapshots[0].captured_at).getTime();
    const tMax = new Date(snapshots[snapshots.length - 1].captured_at).getTime();
    const span = Math.max(1, tMax - tMin);
    return { tMin, tMax, span };
  }, [snapshots]);

  if (!snapshots || snapshots.length === 0 || !data) return null;
  const { tMin, span } = data;

  // Build a stable color lookup via option index in the optionLabels
  // ordering (falls back to OPTION_PALETTE by index).
  const ids = optionLabels ? Object.keys(optionLabels) : [];
  const idxOf = (id) => {
    const i = ids.indexOf(id);
    return i === -1 ? 0 : i;
  };
  const colorOf = (id) => colorForOptionId(id, idxOf(id), optionsById);

  // Render via raw SVG inside a ResponsiveContainer so we can use the
  // chart's px width at render time.
  return (
    <div style={{ width: '100%', height }}>
      <ResponsiveContainer width="100%" height={height}>
        <svg width="100%" height={height} role="img" aria-label="Winner over time">
          {/* recharts passes width/height to children; using a custom
              render lets us position rects via 100%-relative widths */}
          {snapshots.map((snap, i) => {
            const t = new Date(snap.captured_at).getTime();
            const nextT = i < snapshots.length - 1
              ? new Date(snapshots[i + 1].captured_at).getTime()
              : t + span / Math.max(1, snapshots.length - 1);
            const leftPct = ((t - tMin) / span) * 100;
            const widthPct = Math.max(0.1, ((nextT - t) / span) * 100);
            const winners = Array.isArray(snap.winners) ? snap.winners : [];
            if (winners.length === 0) {
              return (
                <rect
                  key={`seg-${i}`}
                  x={`calc(${leftMargin}px + (100% - ${leftMargin + rightMargin}px) * ${leftPct / 100})`}
                  y={0}
                  width={`calc((100% - ${leftMargin + rightMargin}px) * ${widthPct / 100})`}
                  height={height}
                  fill="#E5E7EB"
                >
                  <title>{formatFullTimestamp(snap.captured_at)}: no winner yet</title>
                </rect>
              );
            }
            if (winners.length === 1) {
              const id = winners[0];
              const label = optionLabels?.[id] || id;
              return (
                <rect
                  key={`seg-${i}`}
                  x={`calc(${leftMargin}px + (100% - ${leftMargin + rightMargin}px) * ${leftPct / 100})`}
                  y={0}
                  width={`calc((100% - ${leftMargin + rightMargin}px) * ${widthPct / 100})`}
                  height={height}
                  fill={colorOf(id)}
                >
                  <title>{formatFullTimestamp(snap.captured_at)}: {label} winning</title>
                </rect>
              );
            }
            // Tied: stack tied options' colors vertically (each gets
            // an equal slice of height). Per D6, lean toward "omit"
            // the primary single-color bar — render only the tied
            // strip to make the tie visually distinct.
            const stripeH = height / winners.length;
            const tiedLabels = winners.map((id) => optionLabels?.[id] || id).join(', ');
            return (
              <g key={`seg-${i}`}>
                {winners.map((id, wi) => (
                  <rect
                    key={`seg-${i}-${id}`}
                    x={`calc(${leftMargin}px + (100% - ${leftMargin + rightMargin}px) * ${leftPct / 100})`}
                    y={wi * stripeH}
                    width={`calc((100% - ${leftMargin + rightMargin}px) * ${widthPct / 100})`}
                    height={stripeH}
                    fill={colorOf(id)}
                  >
                    <title>{formatFullTimestamp(snap.captured_at)}: tied — {tiedLabels}</title>
                  </rect>
                ))}
              </g>
            );
          })}
        </svg>
      </ResponsiveContainer>
    </div>
  );
}

// SRR overlay reference lines + close marker. Shared across binary
// and multi-option charts.
function srrReferenceElements(srr, yTop) {
  if (!srr) return [];
  const elements = [];
  if (srr.stable_window_starts_at) {
    const ts = new Date(srr.stable_window_starts_at).getTime();
    if (!Number.isNaN(ts)) {
      elements.push(
        <ReferenceLine
          key="srr-window-open"
          x={ts}
          stroke={SRR_COLORS.stableWindow}
          strokeDasharray="4 4"
          label={{ value: 'Stable window opens', position: 'top', fontSize: 10, fill: SRR_COLORS.stableWindow }}
        />
      );
    }
  }
  (srr.extensions || []).forEach((ext, i) => {
    const ts = new Date(ext.fired_at).getTime();
    if (Number.isNaN(ts)) return;
    elements.push(
      <ReferenceLine
        key={`srr-ext-${i}`}
        x={ts}
        stroke={SRR_COLORS.extension}
        label={{ value: 'Extension', position: 'top', fontSize: 10, fill: SRR_COLORS.extension }}
      />
    );
  });
  (srr.destabilization_events || []).forEach((d, i) => {
    const ts = new Date(d.fired_at).getTime();
    if (Number.isNaN(ts)) return;
    elements.push(
      <ReferenceLine
        key={`srr-destab-${i}`}
        x={ts}
        stroke={SRR_COLORS.destabilization}
        label={{ value: 'Destabilization', position: 'top', fontSize: 10, fill: SRR_COLORS.destabilization }}
      />
    );
  });
  // Close marker — placed at the last snapshot's x. Color reflects
  // the close trigger.
  if (srr.close_trigger) {
    const trigger = srr.close_trigger;
    const color = trigger === 'stable_result_achieved' ? SRR_COLORS.achieved
                : trigger === 'force_close_budget_exhausted' ? SRR_COLORS.forceClose
                : SRR_COLORS.voteEnd;
    elements.push(
      <ReferenceLine
        key="srr-close"
        x="__close__"
        stroke={color}
        strokeWidth={2}
        // The actual x is patched by caller — we render only when we
        // know voting_end is in range. Placeholder.
      />
    );
  }
  return elements;
}

function DataTable({ data, mode, optionLabels, optionIds }) {
  if (!data || data.length === 0) return null;
  if (mode === 'binary') {
    return (
      <table className="text-xs w-full border-collapse">
        <thead>
          <tr className="text-left border-b border-gray-200">
            <th className="py-1 pr-2 font-medium text-gray-600">Time</th>
            <th className="py-1 pr-2 font-medium text-gray-600">Support %</th>
            <th className="py-1 font-medium text-gray-600">Votes cast</th>
          </tr>
        </thead>
        <tbody>
          {data.map((s, i) => (
            <tr key={i} className="border-b border-gray-100">
              <td className="py-1 pr-2 text-gray-700">{formatFullTimestamp(s.captured_at)}</td>
              <td className="py-1 pr-2 text-gray-700">{(s.support_fraction * 100).toFixed(1)}%</td>
              <td className="py-1 text-gray-700">{s.votes_cast}</td>
            </tr>
          ))}
        </tbody>
      </table>
    );
  }
  // Multi-option
  return (
    <table className="text-xs w-full border-collapse">
      <thead>
        <tr className="text-left border-b border-gray-200">
          <th className="py-1 pr-2 font-medium text-gray-600">Time</th>
          <th className="py-1 pr-2 font-medium text-gray-600">Winners</th>
          {optionIds.map((id) => (
            <th key={id} className="py-1 pr-2 font-medium text-gray-600">
              {optionLabels?.[id] || id}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {data.map((s, i) => (
          <tr key={i} className="border-b border-gray-100">
            <td className="py-1 pr-2 text-gray-700">{formatFullTimestamp(s.captured_at)}</td>
            <td className="py-1 pr-2 text-gray-700">
              {(s.winners || []).map((w) => optionLabels?.[w] || w).join(', ') || '—'}
            </td>
            {optionIds.map((id) => (
              <td key={id} className="py-1 pr-2 text-gray-700">
                {s.option_totals ? (s.option_totals[id] ?? '—') : '—'}
              </td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export default function SupportTrajectoryChart({ proposalId, expanded, optionLabels, proposal, onError }) {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [data, setData] = useState(null);
  const [showAll, setShowAll] = useState(false);
  const [showTable, setShowTable] = useState(false);
  const [fetchTick, setFetchTick] = useState(0);

  useEffect(() => {
    if (!expanded || !proposalId) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    api.get(`/api/proposals/${proposalId}/trajectory`)
      .then((res) => {
        if (cancelled) return;
        setData(res);
      })
      .catch((err) => {
        if (cancelled) return;
        setError(err);
        if (onError) onError(err);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => { cancelled = true; };
  }, [proposalId, expanded, fetchTick, onError]);

  // Always declare all hooks; bail to null AFTER. (React hook rules.)
  // Prepare chart data (memoized).
  const isMultiOption = data?.voting_method === 'approval' || data?.voting_method === 'ranked_choice';
  const isBinary = data?.voting_method === 'binary';

  const snapshots = data?.snapshots || [];
  const span = useMemo(() => {
    if (snapshots.length < 2) return 0;
    const a = new Date(snapshots[0].captured_at).getTime();
    const b = new Date(snapshots[snapshots.length - 1].captured_at).getTime();
    return Math.max(0, b - a);
  }, [snapshots]);

  // Map proposal.options for color resolution.
  const optionsById = useMemo(() => {
    const out = {};
    (proposal?.options || []).forEach((o) => { out[o.id] = o; });
    return out;
  }, [proposal]);

  // For multi-option: determine which options to display.
  // - Find all option ids that appear in any snapshot's option_totals.
  // - Sort by final tally (latest snapshot's option_totals) desc.
  // - Default cap = top 5; "show all" expands.
  const { displayOptionIds, allOptionIds, hasAnyOptionTotals } = useMemo(() => {
    if (!isMultiOption) return { displayOptionIds: [], allOptionIds: [], hasAnyOptionTotals: false };
    const idSet = new Set();
    let anyTotals = false;
    snapshots.forEach((s) => {
      if (s.option_totals && typeof s.option_totals === 'object') {
        anyTotals = true;
        Object.keys(s.option_totals).forEach((id) => idSet.add(id));
      }
    });
    // Latest non-null option_totals for tally-based sort.
    let latestTotals = {};
    for (let i = snapshots.length - 1; i >= 0; i--) {
      if (snapshots[i].option_totals) { latestTotals = snapshots[i].option_totals; break; }
    }
    const all = Array.from(idSet).sort(
      (a, b) => (latestTotals[b] || 0) - (latestTotals[a] || 0)
    );
    const display = showAll ? all : all.slice(0, 5);
    return { displayOptionIds: display, allOptionIds: all, hasAnyOptionTotals: anyTotals };
  }, [isMultiOption, snapshots, showAll]);

  // Currently-winning options (latest snapshot's winners) — used for
  // heavier stroke weight.
  const currentWinners = useMemo(() => {
    const last = snapshots[snapshots.length - 1];
    return new Set(Array.isArray(last?.winners) ? last.winners : []);
  }, [snapshots]);

  // Transform snapshots for recharts. Each row has a numeric
  // `timestamp` for the x-axis plus the raw captured_at for tooltips.
  // For multi-option rows, each option's vote count gets its own
  // `opt:<id>` key.
  const chartData = useMemo(() => {
    return snapshots.map((s) => {
      const row = {
        captured_at: s.captured_at,
        timestamp: new Date(s.captured_at).getTime(),
        votes_cast: s.votes_cast,
        support_fraction: s.support_fraction ?? null,
      };
      if (s.option_totals && typeof s.option_totals === 'object') {
        Object.entries(s.option_totals).forEach(([id, count]) => {
          row[`opt:${id}`] = count;
        });
      }
      return row;
    });
  }, [snapshots]);

  // Build aria-live summary string (loads on data ready).
  const ariaSummary = useMemo(() => {
    if (!data || snapshots.length === 0) return '';
    if (isBinary) {
      const fracs = snapshots.map((s) => s.support_fraction).filter((f) => f != null);
      if (fracs.length === 0) return `Trajectory loaded: ${snapshots.length} data points.`;
      const min = Math.min(...fracs);
      const max = Math.max(...fracs);
      const days = span > 0 ? (span / 86400000).toFixed(1) : '0';
      return `Trajectory loaded: ${snapshots.length} data points, support range ${Math.round(min * 100)}% to ${Math.round(max * 100)}% over ${days} days.`;
    }
    return `Trajectory loaded: ${snapshots.length} data points across ${allOptionIds.length} options.`;
  }, [data, snapshots, isBinary, span, allOptionIds]);

  // Renders — early returns.
  if (!expanded) return null;
  if (loading) return <div aria-label="Support trajectory chart"><Spinner /></div>;
  if (error) {
    return (
      <div aria-label="Support trajectory chart">
        <ErrorState message={error.message || 'Unknown error'} onRetry={() => setFetchTick((t) => t + 1)} />
      </div>
    );
  }
  if (!data) return null;
  if (snapshots.length === 0) {
    return (
      <div aria-label="Support trajectory chart">
        <EmptyState />
      </div>
    );
  }

  // Heights — responsive: mobile 200, desktop 350.
  // Tailwind doesn't easily give us viewport-conditional heights for
  // recharts (it needs a number), so we use CSS classes + a wrapper
  // hint via two ResponsiveContainers (one shown on each breakpoint).
  const chartHeightDesktop = 350;
  const chartHeightMobile = 200;
  const winnerBarHeightDesktop = 24;
  const winnerBarHeightMobile = 16;

  // Recharts chart margins (left has room for y-axis labels)
  const chartMargin = { top: 24, right: 24, left: 24, bottom: 8 };

  const srr = data.srr_annotations;
  const votingEndTs = data.voting_end ? new Date(data.voting_end).getTime() : null;

  // Pass-threshold for binary chart. Fall back to 0.5 if proposal not
  // supplied.
  const passThreshold = typeof proposal?.pass_threshold === 'number'
    ? proposal.pass_threshold
    : 0.5;

  // Build SRR reference elements (vertical lines). The close marker
  // we render inline via ReferenceDot below since we need y coords.
  const srrLines = srr ? srrReferenceElements(srr, null).filter((e) => e.key !== 'srr-close') : [];

  // ---- Binary chart render ----
  const renderBinaryChart = (height) => (
    <ResponsiveContainer width="100%" height={height}>
      <ComposedChart data={chartData} margin={chartMargin}>
        <XAxis
          dataKey="timestamp"
          type="number"
          scale="time"
          domain={['dataMin', 'dataMax']}
          tickFormatter={(v) => formatTickLabel(v, span)}
          tick={{ fontSize: 11, fill: '#6B7280' }}
          stroke="#D1D5DB"
        />
        <YAxis
          domain={[0, 1]}
          tickFormatter={(v) => `${Math.round(v * 100)}%`}
          tick={{ fontSize: 11, fill: '#6B7280' }}
          stroke="#D1D5DB"
        />
        <Tooltip content={<BinaryTooltip />} />
        <ReferenceLine
          y={passThreshold}
          stroke="#6B7280"
          strokeDasharray="4 4"
          label={{ value: 'Pass threshold', position: 'right', fontSize: 10, fill: '#6B7280' }}
        />
        <Area
          type="monotone"
          dataKey="support_fraction"
          stroke="none"
          fill="var(--brand-primary, #1B3A5C)"
          fillOpacity={0.15}
          isAnimationActive={false}
        />
        <Line
          type="monotone"
          dataKey="support_fraction"
          stroke="var(--brand-primary, #1B3A5C)"
          strokeWidth={2}
          dot={false}
          activeDot={{ r: 4 }}
          isAnimationActive={false}
        />
        {srrLines}
        {srr && srr.close_trigger && votingEndTs && (
          <ReferenceDot
            x={votingEndTs}
            y={chartData[chartData.length - 1]?.support_fraction ?? passThreshold}
            r={6}
            fill={
              srr.close_trigger === 'stable_result_achieved' ? SRR_COLORS.achieved
              : srr.close_trigger === 'force_close_budget_exhausted' ? SRR_COLORS.forceClose
              : SRR_COLORS.voteEnd
            }
            stroke="white"
            strokeWidth={2}
          />
        )}
      </ComposedChart>
    </ResponsiveContainer>
  );

  // ---- Multi-option chart render ----
  const renderMultiOptionChart = (height) => (
    <ResponsiveContainer width="100%" height={height}>
      <LineChart data={chartData} margin={chartMargin}>
        <XAxis
          dataKey="timestamp"
          type="number"
          scale="time"
          domain={['dataMin', 'dataMax']}
          tickFormatter={(v) => formatTickLabel(v, span)}
          tick={{ fontSize: 11, fill: '#6B7280' }}
          stroke="#D1D5DB"
        />
        <YAxis
          tick={{ fontSize: 11, fill: '#6B7280' }}
          stroke="#D1D5DB"
          allowDecimals={false}
        />
        <Tooltip content={<MultiOptionTooltip optionLabels={optionLabels} />} />
        {displayOptionIds.map((id, idx) => {
          const isWinner = currentWinners.has(id);
          return (
            <Line
              key={id}
              type="monotone"
              dataKey={`opt:${id}`}
              name={optionLabels?.[id] || id}
              stroke={colorForOptionId(id, idx, optionsById)}
              strokeWidth={isWinner ? 3 : 2}
              dot={false}
              activeDot={{ r: 4 }}
              isAnimationActive={false}
              connectNulls
            />
          );
        })}
        {srrLines}
        {srr && srr.close_trigger && votingEndTs && (
          <ReferenceDot
            x={votingEndTs}
            y={Math.max(
              0,
              ...displayOptionIds.map((id) => chartData[chartData.length - 1]?.[`opt:${id}`] ?? 0)
            )}
            r={6}
            fill={
              srr.close_trigger === 'stable_result_achieved' ? SRR_COLORS.achieved
              : srr.close_trigger === 'force_close_budget_exhausted' ? SRR_COLORS.forceClose
              : SRR_COLORS.voteEnd
            }
            stroke="white"
            strokeWidth={2}
          />
        )}
      </LineChart>
    </ResponsiveContainer>
  );

  // ---- Render ----
  return (
    <div className="space-y-3" aria-label="Support trajectory chart">
      {/* Hidden aria-live summary announces on data load. */}
      <div className="sr-only" aria-live="polite">{ariaSummary}</div>

      {/* Binary: line chart */}
      {isBinary && (
        <>
          <div className="hidden sm:block">{renderBinaryChart(chartHeightDesktop)}</div>
          <div className="sm:hidden">{renderBinaryChart(chartHeightMobile)}</div>
        </>
      )}

      {/* Multi-option: line chart (gated on having any option_totals)
          + winner-over-time bar (always). */}
      {isMultiOption && hasAnyOptionTotals && (
        <>
          <div className="hidden sm:block">{renderMultiOptionChart(chartHeightDesktop)}</div>
          <div className="sm:hidden">{renderMultiOptionChart(chartHeightMobile)}</div>
        </>
      )}

      {isMultiOption && !hasAnyOptionTotals && (
        <div className="bg-amber-50 border border-amber-200 rounded-lg p-2 text-xs text-amber-800">
          Per-option trajectory not available for this proposal — only winner sequence shown below.
        </div>
      )}

      {/* Multi-option winner-over-time bar */}
      {isMultiOption && (
        <div className="space-y-1">
          <div className="text-[10px] text-gray-500 uppercase tracking-wide">Winner over time</div>
          <div className="hidden sm:block">
            <WinnerOverTimeBar
              snapshots={snapshots}
              optionsById={optionsById}
              optionLabels={optionLabels}
              height={winnerBarHeightDesktop}
              leftMargin={chartMargin.left}
              rightMargin={chartMargin.right}
            />
          </div>
          <div className="sm:hidden">
            <WinnerOverTimeBar
              snapshots={snapshots}
              optionsById={optionsById}
              optionLabels={optionLabels}
              height={winnerBarHeightMobile}
              leftMargin={chartMargin.left}
              rightMargin={chartMargin.right}
            />
          </div>
        </div>
      )}

      {/* Multi-option legend + show-all toggle */}
      {isMultiOption && hasAnyOptionTotals && (
        <div className="flex flex-wrap gap-x-3 gap-y-1 items-center text-xs">
          {displayOptionIds.map((id, idx) => {
            const isWinner = currentWinners.has(id);
            return (
              <span key={id} className="inline-flex items-center gap-1.5">
                <span
                  className="inline-block w-3 h-1.5 rounded-sm"
                  style={{
                    backgroundColor: colorForOptionId(id, idx, optionsById),
                    height: isWinner ? '3px' : '2px',
                  }}
                />
                <span className={isWinner ? 'text-gray-800 font-medium' : 'text-gray-600'}>
                  {optionLabels?.[id] || id}
                </span>
              </span>
            );
          })}
          {allOptionIds.length > 5 && (
            <button
              onClick={() => setShowAll((v) => !v)}
              className="text-[var(--brand-accent)] hover:underline ml-auto"
            >
              {showAll ? 'Show top 5 only' : `Show all (${allOptionIds.length})`}
            </button>
          )}
        </div>
      )}

      {/* SRR legend chips */}
      {srr && (
        <div className="flex flex-wrap gap-3 text-[10px] text-gray-500 border-t border-gray-100 pt-2">
          {srr.stable_window_starts_at && (
            <span className="inline-flex items-center gap-1">
              <span className="inline-block w-3 border-t border-dashed" style={{ borderColor: SRR_COLORS.stableWindow }} />
              Stable window opens
            </span>
          )}
          {(srr.extensions || []).length > 0 && (
            <span className="inline-flex items-center gap-1">
              <span className="inline-block w-3 border-t-2" style={{ borderColor: SRR_COLORS.extension }} />
              Extension granted ({srr.extensions.length})
            </span>
          )}
          {(srr.destabilization_events || []).length > 0 && (
            <span className="inline-flex items-center gap-1">
              <span className="inline-block w-3 border-t-2" style={{ borderColor: SRR_COLORS.destabilization }} />
              Destabilization ({srr.destabilization_events.length})
            </span>
          )}
          {srr.close_trigger && (
            <span className="inline-flex items-center gap-1">
              <span
                className="inline-block w-2 h-2 rounded-full"
                style={{
                  backgroundColor:
                    srr.close_trigger === 'stable_result_achieved' ? SRR_COLORS.achieved
                    : srr.close_trigger === 'force_close_budget_exhausted' ? SRR_COLORS.forceClose
                    : SRR_COLORS.voteEnd,
                }}
              />
              Close: {srr.close_trigger.replaceAll('_', ' ')}
            </span>
          )}
        </div>
      )}

      {/* Data table toggle (accessibility) */}
      <div className="pt-1">
        <button
          onClick={() => setShowTable((v) => !v)}
          className="text-xs text-[var(--brand-accent)] hover:underline"
        >
          {showTable ? 'Hide data table' : 'Show as data table'}
        </button>
        {showTable && (
          <div className="mt-2 overflow-x-auto">
            <DataTable
              data={snapshots}
              mode={isBinary ? 'binary' : 'multi'}
              optionLabels={optionLabels}
              optionIds={displayOptionIds}
            />
          </div>
        )}
      </div>
    </div>
  );
}
