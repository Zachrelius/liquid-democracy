/**
 * Phase 8 — Sustained-majority status panel for ProposalDetail.
 *
 * Renders three things when sustained-majority is active for a proposal:
 *   1. Floor-approach banner (only when current support is within 5pp of floor
 *      and the user's effective ballot contributes — caller passes `myVoteContributes`).
 *   2. Support-vs-floor indicator: a horizontal bar with the floor marked as a
 *      red zone and the current support level as a tick.
 *   3. Historical support chart over the voting window (binary only — uses
 *      the existing /results time_series snapshot data).
 *
 * For approval / ranked_choice the panel shows the "stable result lock"
 * indicator instead of the support bar, since floor doesn't map cleanly.
 */

import {
  ResponsiveContainer,
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  ReferenceLine,
  ReferenceArea,
} from 'recharts';

function formatPct(x) {
  if (x == null) return '—';
  return `${(x * 100).toFixed(1)}%`;
}

function SupportBar({ support, floor, threshold }) {
  // Bar from 0 to 100%. Red zone covers 0 → floor; an arrow marks current support.
  const supportPct = support != null ? Math.max(0, Math.min(1, support)) : 0;
  const floorPct = Math.max(0, Math.min(1, floor));
  const thresholdPct = Math.max(0, Math.min(1, threshold));

  return (
    <div className="space-y-1">
      <div className="relative h-6 bg-gray-100 rounded-md overflow-visible">
        {/* Red zone (sub-floor) */}
        <div
          className="absolute top-0 left-0 h-full bg-red-100 border-r border-red-300 rounded-l-md"
          style={{ width: `${floorPct * 100}%` }}
          title={`Floor: ${formatPct(floor)}`}
        />
        {/* Threshold dashed line */}
        <div
          className="absolute top-0 h-full border-l border-dashed border-blue-400"
          style={{ left: `${thresholdPct * 100}%` }}
          title={`Threshold: ${formatPct(threshold)}`}
        />
        {/* Current support tick */}
        {support != null && (
          <div
            className="absolute top-0 h-full"
            style={{ left: `${supportPct * 100}%` }}
            title={`Current support: ${formatPct(support)}`}
          >
            <div className="w-0.5 h-full bg-[#1B3A5C]" />
            <div className="absolute -top-2 -translate-x-1/2 text-[10px] font-medium text-[#1B3A5C] bg-white px-1 rounded whitespace-nowrap">
              {formatPct(support)}
            </div>
          </div>
        )}
      </div>
      <div className="flex justify-between text-[10px] text-gray-400">
        <span>0%</span>
        <span className="text-red-500">↑ floor {formatPct(floor)}</span>
        <span className="text-blue-500">↑ threshold {formatPct(threshold)}</span>
        <span>100%</span>
      </div>
    </div>
  );
}

function HistoricalChart({ timeSeries, floor, threshold }) {
  if (!timeSeries || timeSeries.length < 2) return null;
  const data = timeSeries.map(s => {
    const cast = s.yes + s.no + s.abstain;
    return {
      t: new Date(s.simulated_time).getTime(),
      label: new Date(s.simulated_time).toLocaleString([], {
        month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit',
      }),
      support: cast > 0 ? s.yes / cast : 0,
    };
  });
  return (
    <div className="h-32 -mx-2">
      <ResponsiveContainer>
        <LineChart data={data} margin={{ top: 5, right: 10, left: 0, bottom: 0 }}>
          <XAxis dataKey="label" tick={{ fontSize: 10 }} />
          <YAxis
            domain={[0, 1]}
            tickFormatter={v => `${Math.round(v * 100)}%`}
            tick={{ fontSize: 10 }}
            width={36}
          />
          <Tooltip
            formatter={(v) => formatPct(v)}
            labelStyle={{ fontSize: 11 }}
          />
          <ReferenceArea y1={0} y2={floor} fill="#FEE2E2" fillOpacity={0.6} />
          <ReferenceLine y={threshold} stroke="#3B82F6" strokeDasharray="3 3" />
          <ReferenceLine y={floor} stroke="#DC2626" strokeDasharray="3 3" />
          <Line type="monotone" dataKey="support" stroke="#1B3A5C" strokeWidth={2} dot={false} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

export default function SustainedMajorityPanel({ tally, proposal, myVote }) {
  const sm = tally?.sustained_majority;
  if (!sm || !sm.active) return null;

  const isMultiOption = proposal.voting_method !== 'binary';

  // Floor-approach banner: shown when binary support is within 5pp of floor and
  // the user's effective vote is on the at-risk side (yes for binary — that's
  // the side whose support is dropping). A no voter or non-voter doesn't get
  // the banner — the proposal failing isn't bad news for them, and they can't
  // act on it the way a yes voter / inheriting delegator can.
  const myVoteContributesYes = !!(
    myVote
    && (myVote.is_direct === true || myVote.is_direct === false)
    && myVote.vote_value === 'yes'
  );
  const showApproachBanner = (
    !isMultiOption
    && sm.approaching_floor
    && !sm.floor_breached
    && myVoteContributesYes
  );

  return (
    <div className="space-y-4">
      {/* Floor-approach banner */}
      {showApproachBanner && (
        <div className="bg-amber-50 border border-amber-200 rounded-lg p-3 text-sm">
          <p className="font-medium text-amber-900">
            ⚠ Support is approaching the floor
          </p>
          <p className="text-xs text-amber-800 mt-1">
            Your effective vote is contributing to this proposal. If support drops
            below {formatPct(sm.floor)}, the configured failure mode (
            <strong>{sm.failure_mode}</strong>) will trigger.
          </p>
          <div className="mt-2 flex gap-3">
            <a
              href="#vote-panel"
              className="text-xs text-amber-900 underline hover:text-amber-700"
            >
              Review your vote
            </a>
            <a
              href="/delegations"
              className="text-xs text-amber-900 underline hover:text-amber-700"
            >
              Review your delegation
            </a>
          </div>
        </div>
      )}

      {/* Floor-breached banner — proposal is in trouble or has been escalated */}
      {sm.floor_breached && (
        <div className="bg-red-50 border border-red-200 rounded-lg p-3 text-sm">
          <p className="font-medium text-red-900">⛔ Floor breached</p>
          <p className="text-xs text-red-800 mt-1">
            Current support ({formatPct(sm.current_support)}) is below the floor
            ({formatPct(sm.floor)}). Failure mode: <strong>{sm.failure_mode}</strong>.
          </p>
        </div>
      )}

      {/* Body */}
      <div className="bg-blue-50 border border-blue-200 rounded-xl p-4 space-y-3">
        <div className="flex items-baseline justify-between">
          <h3 className="text-sm font-semibold text-[#1B3A5C]">
            Sustained-Majority Status
          </h3>
          <a
            href="/help/sustained-majority"
            target="_blank"
            rel="noreferrer"
            className="text-xs text-[#2E75B6] hover:underline"
          >
            What is this?
          </a>
        </div>

        {!isMultiOption ? (
          <>
            <SupportBar
              support={sm.current_support}
              floor={sm.floor}
              threshold={sm.threshold}
            />
            <HistoricalChart
              timeSeries={tally.time_series}
              floor={sm.floor}
              threshold={sm.threshold}
            />
          </>
        ) : (
          <div className="text-sm text-gray-700 space-y-2">
            {sm.in_stable_result_window ? (
              <div className="flex items-center gap-2">
                <span
                  className="inline-block w-2.5 h-2.5 rounded-full bg-green-500"
                  title="Stable-result lock active"
                />
                <span className="text-xs">
                  <strong>Stable-result lock active</strong> — final stretch of the voting window.
                  A change to the computed winner now triggers the failure mode.
                </span>
              </div>
            ) : (
              <p className="text-xs text-gray-500">
                Stable-result lock activates in the final 25% of the voting window.
              </p>
            )}
            {sm.current_winners && sm.current_winners.length > 0 && (
              <p className="text-xs">
                Current winner{sm.current_winners.length > 1 ? 's' : ''}: {' '}
                <span className="font-medium">
                  {sm.current_winners
                    .map(id => proposal.options?.find(o => o.id === id)?.label || id)
                    .join(', ')}
                </span>
              </p>
            )}
          </div>
        )}

        <div className="text-[11px] text-gray-500 grid grid-cols-2 gap-x-4 gap-y-0.5 pt-2 border-t border-blue-100">
          <span>Threshold: <span className="font-medium">{formatPct(sm.threshold)}</span></span>
          <span>Floor: <span className="font-medium">{formatPct(sm.floor)}</span></span>
          <span>Failure mode: <span className="font-medium">{sm.failure_mode}</span></span>
          <span>
            Extensions: <span className="font-medium">{sm.extension_count ?? 0}</span>
          </span>
        </div>
      </div>
    </div>
  );
}
