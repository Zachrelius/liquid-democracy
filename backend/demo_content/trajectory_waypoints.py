"""
Trajectory Waypoints — Stage 6.5 Production

Structured trajectory data for all proposals in the Millbrook Demo.
Consumed by the technical agent's seed pipeline (Phase 23) to render
the support-trajectory chart for each proposal.

Format conventions:
- Each proposal has a Trajectory entry below.
- Waypoints are (hour, support_pct) tuples — hour 0 is voting open
  (or deliberation open for `deliberation` lifecycle proposals).
- SRR proposals have additional `events` list with annotation markers
  the chart renders alongside the support line.
- For proposals in `passed N days ago` / `failed N days ago` lifecycle
  states, waypoints span only the voting period (not the days-ago elapsed
  time).
- For proposals at `voting, hour H of V` at reset, waypoints span 0..H
  (the elapsed portion). The technical agent generates post-reset waypoints
  via the live voting mechanism, not from seed data.
- For proposals at `deliberation, hour H of D` at reset, no waypoints
  needed (deliberation has no support line until voting opens).

The technical agent should align this data to the `Trajectory` and
`TrajectoryEvent` dataclass shapes for the OrgBible Python module.
"""

from .schema import Waypoint, TrajectoryEvent, Trajectory


# -----------------------------------------------------------------------------
# Cedar Hollow trajectories
# -----------------------------------------------------------------------------

P_H_01 = Trajectory(
    proposal_id='P-H-01',
    voting_method='binary',
    duration_hours=72,
    waypoints=[
        Waypoint(0, 45),
        Waypoint(6, 48),
        Waypoint(12, 52),
        Waypoint(18, 54),
        Waypoint(24, 53),
        Waypoint(36, 51),
        Waypoint(48, 55),
        Waypoint(60, 57),
        Waypoint(72, 58),
    ],
    events=[
        TrajectoryEvent(0, 'voting_open'),
        TrajectoryEvent(72, 'voting_close', label='Passed 58-42'),
    ],
    final_result='58-42 passed',
)

P_H_02 = Trajectory(
    proposal_id='P-H-02',
    voting_method='binary',
    duration_hours=72,
    waypoints=[
        Waypoint(0, 28),
        Waypoint(6, 32),
        Waypoint(12, 38),
        Waypoint(24, 42),
        Waypoint(36, 42),
        Waypoint(48, 41),
        Waypoint(60, 39),
        Waypoint(72, 38),
    ],
    events=[
        TrajectoryEvent(0, 'voting_open'),
        TrajectoryEvent(72, 'voting_close', label='Failed 38-62'),
    ],
    final_result='38-62 failed',
)

P_H_03 = Trajectory(
    proposal_id='P-H-03',
    voting_method='approval',
    duration_hours=72,
    # For approval: support_pct per option, top-line is the highest-approved option.
    # Per-item waypoints would be a separate structure; using top-line for chart display.
    waypoints=[
        Waypoint(0, 70),    # Items 1-3 lead from the start
        Waypoint(12, 72),
        Waypoint(24, 73),
        Waypoint(48, 74),
        Waypoint(72, 75),
    ],
    events=[
        TrajectoryEvent(0, 'voting_open'),
        TrajectoryEvent(72, 'voting_close', label='Top 4 items approved'),
    ],
    final_result='Items 1-4 approved (1: 75%, 2: 73%, 3: 71%, 4: 58%); items 5-6: 55%, 52%; items 7-8: 38%, 32%',
    notes='Per-item waypoint data should be seeded separately by the technical agent if the chart displays per-option trajectories. Top-line shown here.',
)

P_H_04 = Trajectory(
    proposal_id='P-H-04',
    voting_method='approval',
    duration_hours=72,
    # Approval vote with tie between options D and E.
    waypoints=[
        Waypoint(0, 65),    # Option C leads from start
        Waypoint(12, 65),
        Waypoint(24, 66),
        Waypoint(48, 65),
        Waypoint(72, 65),
    ],
    events=[
        TrajectoryEvent(0, 'voting_open'),
        TrajectoryEvent(72, 'voting_close', label='C: 65%, A: 40%, D: 32%, E: 32% (tie); B: 28%. D selected via broader_approval_base'),
    ],
    final_result='C approved (65%), D approved via broader_approval_base tie-break',
    notes='Phase 17 tie-resolution showcase. Per-option approval percentages: C=65%, A=40%, D=32%, E=32%, B=28%. Tie between D and E resolved by broader_approval_base (D shared more approvers with C than E did).',
)

P_H_05 = Trajectory(
    proposal_id='P-H-05',
    voting_method='binary',
    duration_hours=72,
    # Failed quorum — flat low participation throughout
    waypoints=[
        Waypoint(0, 78),
        Waypoint(24, 78),
        Waypoint(48, 78),
        Waypoint(72, 78),
    ],
    events=[
        TrajectoryEvent(0, 'voting_open'),
        TrajectoryEvent(72, 'failed_quorum', label='Failed quorum (25% turnout, 35% threshold)'),
    ],
    final_result='Failed quorum',
    notes='Of those who voted, 78% supported. Participation never crossed 25%. The chart should show participation as separate metric and flag the quorum failure clearly.',
)

# === SRR clean-close exemplar ===
P_H_06 = Trajectory(
    proposal_id='P-H-06',
    voting_method='binary',
    duration_hours=48,                              # voting open period + stable window
    waypoints=[
        Waypoint(0, 50),
        Waypoint(6, 52),
        Waypoint(12, 54),
        Waypoint(18, 54),
        Waypoint(24, 53),
        Waypoint(30, 54),
        Waypoint(36, 54),
        Waypoint(42, 53),
        Waypoint(48, 54),
    ],
    events=[
        TrajectoryEvent(0, 'voting_open'),
        TrajectoryEvent(12, 'stable_window_open',
                       label='Stable window opens',
                       note='Support entered stable above-threshold range; SRR stable window starts.'),
        TrajectoryEvent(48, 'voting_close',
                       label='Stable close, 54-46',
                       note='Stable window held to expiration. No destabilization, no extension. Clean close.'),
    ],
    final_result='54-46 passed (SRR clean-close)',
    notes='SRR clean-close exemplar. The chart shows the stable window annotation but no extension flags. Pass threshold: 52% (50% + 2% margin). Stable window duration: 36 hours.',
)

P_H_07 = Trajectory(
    proposal_id='P-H-07',
    voting_method='rcv',
    duration_hours=168,                             # 7-day voting window
    waypoints=[],                                   # Empty — proposal is in deliberation at reset
    events=[],
    final_result='In deliberation at reset; voting opens 132 hours after reset',
    notes='Expected first-choice support when voting opens: Janet 50-55%, Don 25-30%, Patty 15-20%. RCV cascade favors Janet on second round if no first-round majority. Don/Patty transfers heavily favor each other.',
)

P_H_08 = Trajectory(
    proposal_id='P-H-08',
    voting_method='approval',
    duration_hours=72,
    waypoints=[
        Waypoint(0, 60),       # Vendor B (top option) at voting open
        Waypoint(6, 60),
        Waypoint(12, 60),
        Waypoint(18, 60),      # reset moment falls here
    ],
    events=[
        TrajectoryEvent(0, 'voting_open'),
    ],
    final_result='In progress at reset; Vendor B leads 60% / C 45% / A 25% / D 22%',
    notes='Routine procurement, flat trajectory. Voting at reset hour 18 of 72.',
)

P_H_09 = Trajectory(
    proposal_id='P-H-09',
    voting_method='binary',
    duration_hours=72,
    waypoints=[
        Waypoint(0, 80),
        Waypoint(12, 84),
        Waypoint(24, 87),
        Waypoint(48, 88),
        Waypoint(72, 89),
    ],
    events=[
        TrajectoryEvent(0, 'voting_open'),
        TrajectoryEvent(72, 'voting_close', label='Passed 89-11'),
    ],
    final_result='89-11 passed',
)


# Phase 30 C1 — three new active Cedar Hollow proposals.
# P_H_10 is in deliberation; no trajectory entry (snapshots only
# generate for voting-state proposals).

P_H_11 = Trajectory(
    proposal_id='P-H-11',
    voting_method='approval',
    duration_hours=96,
    waypoints=[
        Waypoint(hour=0, support_pct=0.0),
        Waypoint(hour=6, support_pct=12.0),
        Waypoint(hour=12, support_pct=22.0),
        Waypoint(hour=24, support_pct=35.0),
        Waypoint(hour=36, support_pct=44.0),
        Waypoint(hour=48, support_pct=52.0),
        Waypoint(hour=60, support_pct=58.0),
        Waypoint(hour=72, support_pct=64.0),
        Waypoint(hour=84, support_pct=68.0),
        Waypoint(hour=96, support_pct=72.0),
    ],
    events=[
        TrajectoryEvent(0, 'voting_open', label='Voting opens'),
        TrajectoryEvent(96, 'voting_close', label='Voting closes'),
    ],
    final_result='Option B (deep navy) chosen with 58% approval',
    notes='Approval voting; Option B leads throughout, A second.',
)

P_H_12 = Trajectory(
    proposal_id='P-H-12',
    voting_method='binary',
    duration_hours=72,
    waypoints=[
        Waypoint(hour=0, support_pct=0.0),
        Waypoint(hour=4, support_pct=58.0),
        Waypoint(hour=8, support_pct=54.0),
        Waypoint(hour=12, support_pct=51.0),
        Waypoint(hour=18, support_pct=49.0),
        Waypoint(hour=24, support_pct=52.0),
        Waypoint(hour=30, support_pct=50.0),
        Waypoint(hour=36, support_pct=51.0),
        Waypoint(hour=42, support_pct=49.0),
        Waypoint(hour=48, support_pct=52.0),
        Waypoint(hour=54, support_pct=53.0),
        Waypoint(hour=60, support_pct=54.0),
        Waypoint(hour=66, support_pct=53.0),
        Waypoint(hour=72, support_pct=53.0),
    ],
    events=[
        TrajectoryEvent(0, 'voting_open', label='Voting opens'),
        TrajectoryEvent(72, 'voting_close', label='Voting closes'),
    ],
    final_result='53-47 passed (narrow)',
    notes=(
        'Contested proposal showcasing a 50/50 trajectory. '
        'Pool-using households favor; non-pool-using households resist. '
        'Demonstrates the platform handling a genuinely close vote.'
    ),
)


# -----------------------------------------------------------------------------
# Local 4021 trajectories
# -----------------------------------------------------------------------------

P_L_01 = Trajectory(
    proposal_id='P-L-01',
    voting_method='binary',
    duration_hours=96,
    waypoints=[
        Waypoint(0, 75),
        Waypoint(12, 80),
        Waypoint(24, 83),
        Waypoint(48, 85),
        Waypoint(72, 86),
        Waypoint(96, 87),
    ],
    events=[
        TrajectoryEvent(0, 'voting_open'),
        TrajectoryEvent(96, 'voting_close', label='Passed 87-13'),
    ],
    final_result='87-13 passed',
)

P_L_02 = Trajectory(
    proposal_id='P-L-02',
    voting_method='binary',
    duration_hours=72,
    waypoints=[
        Waypoint(0, 88),
        Waypoint(24, 91),
        Waypoint(48, 93),
        Waypoint(72, 94),
    ],
    events=[
        TrajectoryEvent(0, 'voting_open'),
        TrajectoryEvent(72, 'voting_close', label='Passed 94-6'),
    ],
    final_result='94-6 passed',
)

P_L_03 = Trajectory(
    proposal_id='P-L-03',
    voting_method='binary',
    duration_hours=96,
    waypoints=[
        Waypoint(0, 72),
        Waypoint(12, 70),    # Sam's "multiple fronts" comment lands
        Waypoint(18, 68),    # dip continues briefly
        Waypoint(24, 71),    # Dana's substantive reply
        Waypoint(36, 74),    # Walt's historical comment
        Waypoint(48, 76),
        Waypoint(72, 77),
        Waypoint(96, 78),
    ],
    events=[
        TrajectoryEvent(0, 'voting_open'),
        TrajectoryEvent(96, 'voting_close', label='Passed 78-22 (Library sub-org)'),
    ],
    final_result='78-22 passed (Library sub-org only)',
    notes='Library-sub-org-scoped vote. Brief dip mid-vote when Sam questioned multi-front capacity; recovery after Dana and Walt comments.',
)

P_L_04 = Trajectory(
    proposal_id='P-L-04',
    voting_method='rcv',
    duration_hours=96,                              # 4-day voting window
    waypoints=[
        Waypoint(0, 54),       # Aisha first-choice lead
        Waypoint(6, 54),
        Waypoint(12, 55),
        Waypoint(18, 55),
        Waypoint(24, 55),
        Waypoint(30, 55),      # reset moment
    ],
    events=[
        TrajectoryEvent(0, 'voting_open'),
    ],
    final_result='In progress at reset; Aisha 55% / Marisol 45% first-choice; 2 candidates so winner = first-choice majority',
    notes='RCV with 2 candidates — degenerate but showcases tally surface. Steady trajectory.',
)

P_L_05 = Trajectory(
    proposal_id='P-L-05',
    voting_method='binary',
    duration_hours=96,
    waypoints=[
        Waypoint(0, 38),
        Waypoint(12, 44),
        Waypoint(24, 51),    # Walt's pre-1990s strike fund comment circulates
        Waypoint(36, 49),
        Waypoint(40, 47),    # Frank's "we left money on the table" comment lands
        Waypoint(48, 49),
        Waypoint(60, 52),
        Waypoint(72, 53),
        Waypoint(96, 54),
    ],
    events=[
        TrajectoryEvent(0, 'voting_open'),
        TrajectoryEvent(96, 'voting_close', label='Passed 54-46'),
    ],
    final_result='54-46 passed',
    notes='Close vote, substantive both sides. Frank changed vote during voting after Walt\'s comment.',
)

P_L_06 = Trajectory(
    proposal_id='P-L-06',
    voting_method='stv',
    duration_hours=120,                             # 5-day voting window
    waypoints=[
        Waypoint(0, 28),       # First-choice leader (Candidate 1) at voting open
        Waypoint(12, 28),
        Waypoint(24, 28),
        Waypoint(36, 28),
        Waypoint(42, 28),      # reset moment
    ],
    events=[
        TrajectoryEvent(0, 'voting_open'),
    ],
    final_result='In progress at reset; first-choice distribution: C1: 28%, C2: 22%, C3: 18%, C4: 17%, C5: 15%',
    notes='STV with 5 candidates, 3 seats. Sankey visualization is the showcase. Third-seat contention between C3 and C4 in cascade. Per-candidate trajectories should be seeded separately; top-line shown here is C1 (front-runner).',
)

# === SRR extended-then-closed-early exemplar ===
P_L_07 = Trajectory(
    proposal_id='P-L-07',
    voting_method='binary',
    duration_hours=144,                             # initial 48h voting + up to 3 extensions × 24h + 24h buffer; actual close earlier
    waypoints=[
        # Initial voting period
        Waypoint(0, 58),       # voting opens
        Waypoint(6, 60),       # Sam's contract-citing argument circulates
        Waypoint(12, 64),      # above pass threshold (52%)
        Waypoint(14, 64),      # STABLE WINDOW OPENS
        Waypoint(20, 63),
        Waypoint(26, 62),
        Waypoint(32, 63),
        Waypoint(34, 60),      # Frank's destabilizing comment lands
        Waypoint(36, 53),      # support drops fast
        Waypoint(38, 47),      # below pass threshold — STABLE WINDOW DESTABILIZES
        # Extension 1 begins
        Waypoint(40, 47),      # extension 1 hour 2; Keisha's response begins
        Waypoint(42, 50),      # Sam's response
        Waypoint(48, 55),      # Aisha's careful support
        Waypoint(54, 60),
        Waypoint(58, 61),      # re-entering stable territory
        Waypoint(60, 61),      # SLIDING WINDOW STABILITY CHECK BEGINS
        Waypoint(72, 61),
        Waypoint(86, 61),      # RESET MOMENT — proposal is in extension 1 hour 14 of 24
        # Post-reset (technical agent generates via live voting mechanism, not seed data):
        Waypoint(94, 62),      # sliding window stability confirmed — VOTING CLOSES EARLY
    ],
    events=[
        TrajectoryEvent(0, 'voting_open'),
        TrajectoryEvent(14, 'stable_window_open',
                       label='Stable window opens',
                       note='Support stable above pass threshold (52%); SRR stable window starts.'),
        TrajectoryEvent(38, 'stable_window_destabilize',
                       label='Destabilized: Frank\'s comment',
                       note='Support fell below threshold after Frank Boczek\'s hour-34 comment circulated. Extension 1 triggered.'),
        TrajectoryEvent(38, 'extension_grant',
                       label='Extension 1 (24h)',
                       note='SRR grants 24-hour extension; voting continues with sliding-window stability check.'),
        TrajectoryEvent(60, 'sliding_check_begin',
                       label='Sliding stability check',
                       note='Support back above threshold; sliding 8-hour stability check begins.'),
        TrajectoryEvent(94, 'voting_close',
                       label='Closed early on stability',
                       note='Sliding window stability confirmed at extension 1 hour 22; voting closes early. Final 61-39.'),
    ],
    final_result='61-39 passed (SRR extended-then-closed-early)',
    notes=(
        'SRR extended-then-closed-early exemplar. Load-bearing for the demo. '
        'Pass threshold: 52% (50% + 2% margin). Stable window duration: 20 hours. '
        'Reset moment is at hour 86 (extension 1 hour 14 of 24). '
        'Post-reset waypoints (hour 94) represent the expected close; '
        'technical agent should validate via live voting mechanism after reset.'
    ),
)

P_L_08 = Trajectory(
    proposal_id='P-L-08',
    voting_method='binary',
    duration_hours=72,
    waypoints=[
        Waypoint(0, 75),
        Waypoint(24, 78),
        Waypoint(48, 80),
        Waypoint(72, 81),
    ],
    events=[
        TrajectoryEvent(0, 'voting_open'),
        TrajectoryEvent(72, 'voting_close', label='Passed 81-19 (DPW sub-org)'),
    ],
    final_result='81-19 passed (DPW sub-org only)',
)

P_L_09 = Trajectory(
    proposal_id='P-L-09',
    voting_method='binary',
    duration_hours=72,
    waypoints=[
        Waypoint(0, 65),
        Waypoint(24, 72),
        Waypoint(48, 75),
        Waypoint(72, 76),
    ],
    events=[
        TrajectoryEvent(0, 'voting_open'),
        TrajectoryEvent(72, 'voting_close', label='Passed 76-24'),
    ],
    final_result='76-24 passed',
)

P_L_10 = Trajectory(
    proposal_id='P-L-10',
    voting_method='binary',
    duration_hours=72,
    waypoints=[
        Waypoint(0, 89),
        Waypoint(24, 90),
        Waypoint(48, 91),
        Waypoint(72, 91),
    ],
    events=[
        TrajectoryEvent(0, 'voting_open'),
        TrajectoryEvent(72, 'voting_close', label='Passed 91-9'),
    ],
    final_result='91-9 passed',
)


# -----------------------------------------------------------------------------
# Coalition trajectories
# -----------------------------------------------------------------------------

P_C_01 = Trajectory(
    proposal_id='P-C-01',
    voting_method='binary',
    duration_hours=96,
    waypoints=[
        Waypoint(0, 48),
        Waypoint(12, 52),
        Waypoint(24, 56),
        Waypoint(36, 52),    # Maya's response thread, Hector's "who benefits" lands
        Waypoint(48, 53),
        Waypoint(50, 55),    # Will's question and Priya's response circulate
        Waypoint(60, 55),
        Waypoint(68, 56),    # reset moment
    ],
    events=[
        TrajectoryEvent(0, 'voting_open'),
        # No voting_close at reset — proposal still in voting; closes 28h after reset
    ],
    final_result='In progress at reset; trending 56-44, narrow passage expected (28h remaining)',
    notes='Most substantive deliberation surface in the demo. Intentionally non-SRR for contrast with P-L-07 and P-C-04. Real uncertainty about close result.',
)

P_C_02 = Trajectory(
    proposal_id='P-C-02',
    voting_method='binary',
    duration_hours=72,
    waypoints=[
        Waypoint(0, 48),
        Waypoint(12, 47),
        Waypoint(24, 46),
        Waypoint(36, 45),    # Priya's "agree on substance, disagree on tactic" thread circulates
        Waypoint(48, 43),
        Waypoint(60, 42),
        Waypoint(72, 41),
    ],
    events=[
        TrajectoryEvent(0, 'voting_open'),
        TrajectoryEvent(72, 'voting_close', label='Failed 41-59'),
    ],
    final_result='41-59 failed',
    notes='Failure shaped P-C-01 deliberation tone — many no votes were "reluctant," agreeing with underlying point but on tactic.',
)

P_C_03 = Trajectory(
    proposal_id='P-C-03',
    voting_method='stv',
    duration_hours=168,                             # 7-day voting window
    waypoints=[
        Waypoint(0, 22),       # Priya first-choice lead at voting open
        Waypoint(12, 22),
        Waypoint(24, 22),
        Waypoint(36, 22),
        Waypoint(48, 22),
        Waypoint(54, 22),      # reset moment
    ],
    events=[
        TrajectoryEvent(0, 'voting_open'),
    ],
    final_result='In progress at reset; first-choice distribution: Priya 22%, Maya 19%, others 12-16% each',
    notes='STV with 6 candidates, 3 seats. Third-seat contention between Jordan Park (YIMBY-leaning) and Sandra Brooks (anti-development-leaning) reflects the YIMBY/anti-development split. Per-candidate trajectories should be seeded separately; top-line is Priya as front-runner.',
)

# === SRR force-close exemplar ===
P_C_04 = Trajectory(
    proposal_id='P-C-04',
    voting_method='binary',
    duration_hours=144,                             # initial voting + 3 extensions × 24h = max possible
    waypoints=[
        # Initial voting period
        Waypoint(0, 60),       # voting opens — Direct Action group rallied early
        Waypoint(6, 64),
        Waypoint(12, 66),
        Waypoint(18, 67),
        Waypoint(24, 65),      # STABLE WINDOW OPENS (12h after threshold first crossed)
        Waypoint(30, 64),
        Waypoint(36, 65),
        Waypoint(38, 60),      # Will's hour-38 doxing concern lands
        Waypoint(40, 56),
        Waypoint(42, 52),      # below pass threshold — DESTABILIZE #1
        # Extension 1 begins (24h)
        Waypoint(42, 52),
        Waypoint(46, 55),      # Hector's receptive response
        Waypoint(50, 58),      # Maya's protocol drafting
        Waypoint(56, 61),
        Waypoint(60, 63),      # recovery
        Waypoint(66, 63),      # extension 1 hour 24 — re-stabilizing
        # Brief re-entry to stable window (~12h)
        Waypoint(72, 63),      # re-entered stable territory
        Waypoint(84, 62),
        Waypoint(92, 56),      # Renée's hour-92 capacity concern lands
        Waypoint(94, 54),      # DESTABILIZE #2
        # Extension 2 begins (24h)
        Waypoint(94, 54),
        Waypoint(100, 58),     # Dana's capacity assessment
        Waypoint(108, 62),
        Waypoint(112, 64),     # brief stability hint
        Waypoint(114, 58),     # late-engagement affordability objections
        Waypoint(116, 56),     # DESTABILIZE #3
        # Extension 3 begins (final 24h — exhausts budget)
        Waypoint(118, 58),
        Waypoint(124, 60),
        Waypoint(130, 62),
        Waypoint(136, 61),
        Waypoint(140, 62),
        Waypoint(144, 62),     # FORCE-CLOSE at extension 3 end
    ],
    events=[
        TrajectoryEvent(0, 'voting_open'),
        TrajectoryEvent(24, 'stable_window_open',
                       label='Stable window opens',
                       note='Support stable above threshold; SRR stable window starts.'),
        TrajectoryEvent(42, 'stable_window_destabilize',
                       label='Destabilized #1: Will\'s doxing concern',
                       note='Will Sutherland\'s hour-38 substantive concern about doxing risk circulated; support dropped below threshold.'),
        TrajectoryEvent(42, 'extension_grant',
                       label='Extension 1 (24h)',
                       note='SRR grants extension 1. During extension, Maya drafts tenant-protection protocols.'),
        TrajectoryEvent(94, 'stable_window_destabilize',
                       label='Destabilized #2: Renée\'s capacity concern',
                       note='Renée Castille\'s hour-92 concern about Member Defense enforcement capacity; support dropped again.'),
        TrajectoryEvent(94, 'extension_grant',
                       label='Extension 2 (24h)',
                       note='SRR grants extension 2. Dana posts capacity assessment.'),
        TrajectoryEvent(116, 'stable_window_destabilize',
                       label='Destabilized #3: late affordability objections',
                       note='Cluster of late-engagement members raised affordability-mandate-style objections; support dipped.'),
        TrajectoryEvent(116, 'extension_grant',
                       label='Extension 3 (final, 24h)',
                       note='SRR grants extension 3 — the final allowed extension. Budget exhausted.'),
        TrajectoryEvent(144, 'force_close',
                       label='Force-closed 62-38',
                       note='Extension budget exhausted; SRR force-closes at extension 3 hour 24. Final 62-38.'),
    ],
    final_result='62-38 passed (SRR force-close)',
    notes=(
        'SRR force-close exemplar. Load-bearing for the demo. '
        'Three destabilizations, three extensions, force-close at extension 3 end. '
        'Pass threshold: 52%. Stable window duration: 18 hours. Max extensions: 3 × 24h. '
        'The chart should clearly show all three extension annotations and the force-close marker. '
        'Demonstrates SRR doesn\'t let contentious proposals sit unresolved indefinitely.'
    ),
)

P_C_05 = Trajectory(
    proposal_id='P-C-05',
    voting_method='binary',
    duration_hours=96,
    waypoints=[
        Waypoint(0, 82),
        Waypoint(24, 85),
        Waypoint(48, 87),
        Waypoint(72, 88),
        Waypoint(96, 88),
    ],
    events=[
        TrajectoryEvent(0, 'voting_open'),
        TrajectoryEvent(96, 'voting_close', label='Passed 88-12'),
    ],
    final_result='88-12 passed',
)

P_C_06 = Trajectory(
    proposal_id='P-C-06',
    voting_method='binary',
    duration_hours=96,                              # voting period; not yet open
    waypoints=[],                                   # in deliberation at reset
    events=[],
    final_result='In deliberation at reset; voting opens 54 hours after reset',
    notes='Expected support when voting opens: ~70% initial, climbing to ~78-82% as debate refines without dividing.',
)

P_C_07 = Trajectory(
    proposal_id='P-C-07',
    voting_method='binary',
    duration_hours=72,
    waypoints=[
        Waypoint(0, 90),
        Waypoint(24, 93),
        Waypoint(48, 95),
        Waypoint(72, 96),
    ],
    events=[
        TrajectoryEvent(0, 'voting_open'),
        TrajectoryEvent(72, 'voting_close', label='Passed 96-4'),
    ],
    final_result='96-4 passed',
)

P_C_08 = Trajectory(
    proposal_id='P-C-08',
    voting_method='approval',
    duration_hours=72,
    waypoints=[
        Waypoint(0, 70),       # Quarterly (top option) at voting open
        Waypoint(24, 71),
        Waypoint(48, 71),
        Waypoint(72, 72),
    ],
    events=[
        TrajectoryEvent(0, 'voting_open'),
        TrajectoryEvent(72, 'voting_close', label='Quarterly: 72%, Monthly: 55%, Bi-weekly: 32%, Ad-hoc: 28%'),
    ],
    final_result='Quarterly approved (72%); Monthly also above approval threshold but lower base',
)

P_C_09 = Trajectory(
    proposal_id='P-C-09',
    voting_method='binary',
    duration_hours=72,
    waypoints=[
        Waypoint(0, 68),
        Waypoint(24, 71),
        Waypoint(48, 73),
        Waypoint(72, 74),
    ],
    events=[
        TrajectoryEvent(0, 'voting_open'),
        TrajectoryEvent(72, 'voting_close', label='Passed 74-26'),
    ],
    final_result='74-26 passed',
)

P_C_10 = Trajectory(
    proposal_id='P-C-10',
    voting_method='binary',
    duration_hours=72,
    waypoints=[
        Waypoint(0, 75),       # voting opens
        Waypoint(6, 76),
        Waypoint(8, 77),       # reset moment
    ],
    events=[
        TrajectoryEvent(0, 'voting_open'),
    ],
    final_result='In progress at reset; non-contentious; expected close ~80% passed',
)

P_C_11 = Trajectory(
    proposal_id='P-C-11',
    voting_method='binary',
    duration_hours=72,
    waypoints=[
        Waypoint(0, 92),
        Waypoint(24, 95),
        Waypoint(48, 97),
        Waypoint(72, 98),
    ],
    events=[
        TrajectoryEvent(0, 'voting_open'),
        TrajectoryEvent(72, 'voting_close', label='Passed 98-2'),
    ],
    final_result='98-2 passed (near-unanimous formalization of P-C-04 protocols)',
)


# -----------------------------------------------------------------------------
# Drafts at reset — no trajectory data (drafts have no support history)
# -----------------------------------------------------------------------------

# P-H-NEW-D1, P-L-NEW-D1, P-C-NEW-D1 are in `draft` state at reset.
# They have no waypoints or events. The draft UI surface shows them as drafts
# in the proposer's profile.


# -----------------------------------------------------------------------------
# Index for technical agent consumption
# -----------------------------------------------------------------------------

ALL_TRAJECTORIES = [
    P_H_01, P_H_02, P_H_03, P_H_04, P_H_05, P_H_06, P_H_07, P_H_08, P_H_09,
    P_H_11, P_H_12,  # Phase 30 C1
    P_L_01, P_L_02, P_L_03, P_L_04, P_L_05, P_L_06, P_L_07, P_L_08, P_L_09, P_L_10,
    P_C_01, P_C_02, P_C_03, P_C_04, P_C_05, P_C_06, P_C_07, P_C_08, P_C_09, P_C_10, P_C_11,
]

SRR_EXEMPLARS = {
    'clean_close': P_H_06,
    'extended_then_closed_early': P_L_07,
    'force_close': P_C_04,
}


# -----------------------------------------------------------------------------
# Integration notes for the technical agent
# -----------------------------------------------------------------------------
"""
NOTES FOR PHASE 23 INTEGRATION:

1. SRR threshold defaults used in this data:
   - Pass threshold: 50% + 2% margin = 52% (binary proposals)
   - Stable window duration: varies per proposal (typically 18-36 hours)
   - Sliding window stability check: 8 hours of holding above threshold during extension
   - Max extensions: 3 per proposal (one per destabilization, then force-close)
   - Extension duration: 24 hours each

2. Per-option waypoints for approval/STV proposals:
   This file shows top-line trajectory (typically the leading option/candidate).
   For approval votes where the chart should display per-option support
   (P-H-03, P-H-04, P-C-08), and STV votes where per-candidate trajectories
   matter for the cascade visualization (P-L-06, P-C-03), the technical agent
   should generate per-option waypoint structures from the final-result
   distributions noted above. The shape of each per-option trajectory follows
   the same arc as the top-line but at the option's settling level.

3. Reset-moment vs. post-reset waypoints:
   For proposals in `voting` state at reset:
   - Waypoints up to reset hour are seeded directly from this data.
   - Post-reset waypoints (e.g., P-L-07's hour 94) are illustrative of
     expected behavior; the live voting mechanism generates actual post-reset
     trajectories.
   - The technical agent should treat post-reset hours noted here as
     guidance, not as seed data.

4. Failed quorum:
   P-H-05 shows participation pattern as quorum-relevant. The chart should
   show participation as a separate trace alongside support, with the quorum
   threshold (35%) visible. Of-voters support (78%) should not be the primary
   display — the failure pattern is what the demo viewer needs to see.

5. Tie resolution:
   P-H-04 has a tie between options D and E at 32% approval each. Resolved
   via broader_approval_base (D shared more approvers with C than E did).
   The chart should annotate the tie clearly and show the tie-break audit trail.

6. Trajectory data shape:
   The Trajectory / Waypoint / TrajectoryEvent dataclasses above are
   illustrative. The technical agent should align to the actual dataclass
   shapes in the OrgBible Python module. This file's data is the source of
   truth for the values; the technical agent translates the values into
   whatever container shape the seed pipeline expects.
"""
