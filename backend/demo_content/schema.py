"""Phase 23 — shared dataclass shapes for the demo-content bibles.

This module is the single source of truth for the dataclasses that describe
the demo-org content set. Three bibles consume it:

- ``hoa_bible.py`` — Cedar Hollow HOA
- ``union_bible.py`` — AFSCME Local 4021
- ``activist_bible_part1.py`` / ``_part2.py`` / ``_part3.py`` —
  Westgate Tenants Coalition (assembled across three files)

Trajectory dataclasses (``Waypoint`` / ``TrajectoryEvent`` / ``Trajectory``)
are consumed by ``trajectory_waypoints.py`` plus the Phase 23 snapshot
generator.

Per Amendment H of the Phase 23 dispatch, these shapes were extracted from
``hoa_bible.py`` (top section) and ``trajectory_waypoints.py`` (inline
defs); the bibles now import their dataclasses from here rather than
defining them inline or importing from each other.

Field names / types / defaults are byte-identical to the content agent's
original layout — see commit ``Phase 23 B10: move bibles ...`` for the
pre-extraction state. Any field additions (governance_type, brand_color,
etc.) are seed-config or migration concerns, NOT bible-schema concerns.
"""

from dataclasses import dataclass, field
from typing import Literal, Optional


# =============================================================================
# Bible dataclasses (originally defined at the top of hoa_bible.py)
# =============================================================================


@dataclass
class Member:
    user_id: str                                    # stable identifier for seeding
    display_name: str
    quick_login: bool                               # is this one of the 6 quick-login characters
    is_cross_org: bool = False                      # appears in another org's cast
    role: str = ''                                  # e.g. "President", "Member-at-Large", "Member"
    notification_preset: Literal['high', 'medium', 'low'] = 'medium'


@dataclass
class TopicVisibility:
    topic: str
    state: Literal['private', 'public', 'public_accepting']


@dataclass
class PositionStatement:
    topic: str
    text: str


@dataclass
class VoteRationale:
    proposal_id: str
    vote: str                                       # 'yes', 'no', 'abstain', or approval/RCV-specific
    text: str


@dataclass
class DelegatePage:
    member_user_id: str
    page_visibility: Literal['private', 'private_delegators', 'public']
    intro: str
    topics: list[TopicVisibility] = field(default_factory=list)
    position_statements: list[PositionStatement] = field(default_factory=list)
    vote_rationales: list[VoteRationale] = field(default_factory=list)


@dataclass
class Comment:
    proposal_id: str
    author_user_id: str
    relative_timestamp: str                         # e.g. "deliberation hour 30", "voting hour 42"
    body: str


@dataclass
class Proposal:
    proposal_id: str
    title: str
    proposer_user_id: str
    voting_method: Literal['binary', 'approval', 'rcv', 'stv']
    state_at_reset: str                             # e.g. "passed, 14 days ago (58-42)"
    body: str                                       # proposer rationale / proposal description
    candidate_statements: dict[str, str] = field(default_factory=dict)  # user_id -> statement for RCV/STV proposals
    options: list[str] = field(default_factory=list)   # for approval, RCV, STV with named options


@dataclass
class NotificationEvent:
    event_type: str                                 # 'halfway_deadline', 'new_follow', 'delegator_rationale', 'delegator_vote_change', etc.
    related_proposal_id: Optional[str] = None
    related_member_user_id: Optional[str] = None
    note: str = ''


@dataclass
class NotificationFeed:
    member_user_id: str
    events: list[NotificationEvent] = field(default_factory=list)


@dataclass
class OrgBible:
    slug: str
    display_name: str
    charter: str
    tone_notes: str
    recent_history: str
    sub_orgs: list[str] = field(default_factory=list)
    voting_methods_used: list[str] = field(default_factory=list)
    approval_tie_resolution: str = ''
    rcv_tie_resolution: str = ''
    quorum_threshold_default: float = 0.35          # 35% for non-financial proposals
    members: list[Member] = field(default_factory=list)
    delegate_pages: list[DelegatePage] = field(default_factory=list)
    proposals: list[Proposal] = field(default_factory=list)
    drafts: list[Proposal] = field(default_factory=list)
    comments: list[Comment] = field(default_factory=list)
    notification_feeds: list[NotificationFeed] = field(default_factory=list)


# =============================================================================
# Trajectory dataclasses (originally defined inline in trajectory_waypoints.py)
# =============================================================================


@dataclass
class Waypoint:
    hour: float           # hours since voting open (or deliberation open for elections)
    support_pct: float    # percent supporting, 0-100
    # For approval/STV proposals where support_pct is per-option, see option_support below


@dataclass
class TrajectoryEvent:
    """
    Annotation event for the chart.

    event_type values:
    - 'stable_window_open'    — SRR: stable window begins
    - 'stable_window_destabilize' — SRR: support fell below threshold; extension triggered
    - 'extension_grant'       — SRR: extension N begins
    - 'sliding_check_begin'   — SRR: sliding-window stability check starts during extension
    - 'force_close'           — SRR: extension budget exhausted; force-close fires
    - 'voting_open'           — voting period begins (always at hour 0)
    - 'voting_close'          — voting period ends
    - 'failed_quorum'         — voting closed without meeting quorum
    """
    hour: float
    event_type: Literal[
        'stable_window_open',
        'stable_window_destabilize',
        'extension_grant',
        'sliding_check_begin',
        'force_close',
        'voting_open',
        'voting_close',
        'failed_quorum',
    ]
    label: str = ''       # short human-readable label for chart annotation
    note: str = ''        # longer note (optional, may not display on chart)


@dataclass
class Trajectory:
    proposal_id: str
    voting_method: Literal['binary', 'approval', 'rcv', 'stv']
    duration_hours: float                          # total voting period length
    waypoints: list[Waypoint] = field(default_factory=list)
    events: list[TrajectoryEvent] = field(default_factory=list)
    final_result: str = ''                         # e.g. "58-42 passed", "failed quorum"
    notes: str = ''                                # any clarifications for the technical agent


__all__ = [
    # Bible dataclasses
    'Member',
    'TopicVisibility',
    'PositionStatement',
    'VoteRationale',
    'DelegatePage',
    'Comment',
    'Proposal',
    'NotificationEvent',
    'NotificationFeed',
    'OrgBible',
    # Trajectory dataclasses
    'Waypoint',
    'TrajectoryEvent',
    'Trajectory',
]
