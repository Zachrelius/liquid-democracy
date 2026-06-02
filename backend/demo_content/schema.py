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
    role: str = ''                                  # display label, e.g. "President", "Member-at-Large"
    notification_preset: Literal['high', 'medium', 'low'] = 'medium'
    # Phase 23.2 B1.2: which preset Role this member gets in their org.
    # Must match one of role_seed.PRESET_ROLES system_keys
    # ('steward', 'admin', 'moderator', 'member'). Defaults to 'member'
    # for backward compat with bibles that don't specify. Distinct from
    # `role` (narrative/display string) — `platform_role` drives the
    # actual permissions assignment in the seed pipeline.
    platform_role: Literal['steward', 'admin', 'moderator', 'member'] = 'member'


@dataclass
class TitleSeed:
    """Phase 49b — bible-declared Phase 47 title seeded into the org.

    Resolves to an ``OrgTitle`` row + (when ``holder_user_id`` is set)
    an ``OrgTitleAssignment`` row via the seed pipeline. ``bound_role``
    drives the title's role-binding semantics; when set, the holder's
    role is bumped to at least the bound tier (the existing Phase 47
    assignment path).
    """
    name: str                                       # display name, e.g. "President"
    bound_role: Optional[
        Literal['steward', 'admin', 'moderator', 'member']
    ] = None
    cardinality_mode: Literal['single', 'multi'] = 'single'
    fill_method: Literal['assigned', 'elected', 'both'] = 'assigned'
    holder_user_id: Optional[str] = None            # bible-internal uid; resolved via bible_uid_to_user
    display_order: int = 0
    # Phase 49 term knobs — opt-in. Setting term_length_days makes the
    # title participate in the scheduled-trigger path.
    term_length_days: Optional[int] = None
    election_lead_time_days: int = 7


@dataclass
class TopicVisibility:
    topic: str
    # Phase 30.3 D1 — followers_only added between private and public.
    state: Literal['private', 'followers_only', 'public', 'public_accepting']


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
    # Phase 30.3: page_visibility is accepted-and-ignored. The column it
    # used to back has been dropped; per-topic visibility on
    # ``TopicVisibility.state`` is the sole audience control. Kept here
    # for back-compat with existing bibles; new bibles can omit (default
    # empty string) or remove explicit values.
    page_visibility: str = ''
    intro: str = ''
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
    # Phase 23.2 B1.1: topics this proposal belongs to.
    # First entry is the PRIMARY topic — delegation engine resolves against
    # this one when a user has multiple topic delegations that overlap with
    # the proposal (ordering signal: ProposalTopic.relevance descending,
    # primary=1.0 and secondaries fall off).
    # Topic strings must match names declared in some delegate page's
    # TopicVisibility in the same org; the seed pipeline logs and skips
    # unknown topic names.
    topics: list[str] = field(default_factory=list)
    # Phase 23.2 B3 helper: STV proposals need to advertise winner count
    # to the tally engine. RCV/binary/approval all default to 1.
    num_winners: int = 1
    # Phase 32 — per-proposal overrides for the new deliberation-engagement
    # features. None = inherit the org-level default (or platform default
    # if the org doesn't set one). Set explicitly on demo proposals that
    # should exercise the feature in QA.
    allow_write_in_options: Optional[bool] = None
    allow_write_ins_during_voting: Optional[bool] = None
    max_write_ins: Optional[int] = None
    allow_pre_voting: Optional[bool] = None
    show_votes_during_deliberation: Optional[bool] = None
    edit_lockout_fraction: Optional[float] = None


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
class FollowSeed:
    """Phase 29 C4 — declarative follow relationship for the seed pipeline.

    follower → followed within a specific org. ``permission_level`` is
    optional only for ``status='pending'`` rows. ``status='approved'``
    rows MUST set permission_level (the seed helper rejects otherwise).
    """
    follower_user_id: str
    followed_user_id: str
    status: Literal['pending', 'approved']
    permission_level: Optional[Literal['view_only', 'delegation_allowed']] = None


@dataclass
class PrivateDelegationSeed:
    """Phase 29 C4 — declarative private delegation for the seed pipeline.

    The delegator must have an ``approved`` follow with permission_level
    ``delegation_allowed`` to the delegate (or the seed helper logs and
    skips the entry — same pattern as the topic-name resolver).
    """
    delegator_user_id: str
    delegate_user_id: str
    topic: str
    chain_behavior: Literal['accept_sub', 'revert_direct', 'abstain'] = 'accept_sub'


@dataclass
class PersonaDelegationSpec:
    """Phase 29.1 — declarative delegation pattern for a quick-login persona.

    Encodes the persona's delegation_strategy, their topic-scoped
    delegations, and their topic_precedence ordering. The seed pipeline
    validates that every delegated topic also appears in
    ``topic_precedence`` (lower index = higher priority) — strict
    enforcement, not warning, catches content-authoring mistakes at seed
    time rather than as silent runtime bugs.

    Don's "no delegations" case is represented as empty lists for both
    ``delegations`` and ``topic_precedence`` plus ``delegation_strategy
    = 'strict_precedence'``; that's the canonical "vote your own
    conscience" pattern, not a bug.
    """
    delegator_user_id: str
    delegation_strategy: Literal['relevance_weighted', 'strict_precedence']
    delegations: list[tuple[str, str]] = field(default_factory=list)
    topic_precedence: list[str] = field(default_factory=list)


@dataclass
class SubOrg:
    """Phase 34 — structured sub-org definition for the seed pipeline.

    A sub-org is a child Organization row under the parent (e.g., Cedar
    Court Condos under Cedar Hollow HOA). It has its own members (a
    subset of parent-org members), topics (declared by `topic_names`,
    seeded as Topic rows with sub_org_id pointing to this sub-org),
    proposals, optional admin (a member who gets 'admin' platform role
    on the sub-org), and optional persona delegations on sub-org topics.

    Sub-org members must also be parent-org members; the seed pipeline
    creates a separate OrgMembership for each declared member with
    org_id = sub-org. Quick-login persona delegations on sub-org topics
    are seeded with the parent persona's bible user_id and
    sub_org_id = this sub-org's id.

    Topics with `topic_names` are scoped to the sub-org (Topic.org_id =
    parent_org.id; Topic.sub_org_id = sub_org.id per the Phase 8.5
    model). Proposals declared here are scoped via Proposal.org_id =
    parent_org.id; Proposal.sub_org_id = sub_org.id.
    """
    slug: str
    name: str
    governance_type: str = ''
    description: str = ''
    member_user_ids: list[str] = field(default_factory=list)
    admin_user_id: Optional[str] = None
    topic_names: list[str] = field(default_factory=list)
    proposals: list['Proposal'] = field(default_factory=list)
    # Sub-org-scoped delegate-page topic visibilities. The seeded
    # DelegateProfile carries sub_org_id = this sub-org for these topics.
    # Format mirrors DelegatePage but only for sub-org topics.
    delegate_topic_visibilities: list[tuple[str, str, str]] = field(default_factory=list)
    # (member_user_id, topic_name, visibility_state)
    # Sub-org-scoped persona delegations. Each entry: (delegator_user_id,
    # delegate_user_id, topic_name). Topic must be in topic_names.
    delegations: list[tuple[str, str, str]] = field(default_factory=list)
    # Phase 34.4 D1 — when True, sub-org content is hidden from non-members
    # (Decision 7 in routes/sub_organizations.py). Parent-org admins can
    # still see private sub-orgs. Writes Organization.settings['private']
    # = True at seed time.
    private: bool = False


@dataclass
class OrgBible:
    slug: str
    display_name: str
    charter: str
    tone_notes: str
    recent_history: str
    # Phase 23-era: list[str] of sub-org name strings (informational only;
    # never wired). Phase 34 — sub_orgs_structured holds the seedable
    # SubOrg dataclasses. Both retained: keeping `sub_orgs` lets existing
    # bibles compile unchanged; only Cedar Hollow populates the new field
    # in Phase 34.
    sub_orgs: list[str] = field(default_factory=list)
    sub_orgs_structured: list[SubOrg] = field(default_factory=list)
    voting_methods_used: list[str] = field(default_factory=list)
    approval_tie_resolution: str = ''
    rcv_tie_resolution: str = ''
    quorum_threshold_default: float = 0.35          # 35% for non-financial proposals
    # Phase 29 C1: when False, the org still seeds (so cross-org users keep
    # their second membership and wipe/reset still validates the pipeline)
    # but is hidden from the /demo public listing. The flag is misnamed for
    # back-compat — despite the name it does NOT control Organization.is_demo
    # (the wipe boundary stays True for every bible-seeded org). The seed
    # pipeline writes the listing-visibility flag into
    # ``Organization.settings['hidden_from_demo_listing']`` so no schema
    # migration is required. Default True for back-compat.
    is_demo: bool = True
    # Phase 29 C5: hex color (e.g. "#3B5A3B") written to
    # Organization.settings['branding']['primary_color'] at seed time. None
    # leaves branding untouched.
    brand_color: Optional[str] = None
    # Phase 29.1 B3: root-relative path (e.g. "/demo_assets/cedar_hollow_logo.jpg")
    # written to Organization.settings['branding']['logo_url'] at seed time.
    # None leaves logo_url untouched. Frontend rendering of the value is
    # gated by B3.3's investigation.
    logo_path: Optional[str] = None
    members: list[Member] = field(default_factory=list)
    delegate_pages: list[DelegatePage] = field(default_factory=list)
    proposals: list[Proposal] = field(default_factory=list)
    drafts: list[Proposal] = field(default_factory=list)
    comments: list[Comment] = field(default_factory=list)
    notification_feeds: list[NotificationFeed] = field(default_factory=list)
    # Phase 29 C4 — seed-time follow + private-delegation declarations.
    # Empty defaults keep the existing bibles unchanged; only HOA
    # populates these in Phase 29.
    follows: list[FollowSeed] = field(default_factory=list)
    private_delegations: list[PrivateDelegationSeed] = field(default_factory=list)
    # Phase 29.1 B1 — quick-login persona delegations + per-user
    # delegation_strategy + topic precedence orderings. Validation in the
    # seed helper is strict: every delegated topic must also appear in
    # the matching topic_precedence list.
    persona_delegations: list[PersonaDelegationSpec] = field(default_factory=list)
    # Phase 49b — bible-declared Phase 47 titles. Empty by default for
    # back-compat with bibles that don't promote text-roles to real
    # titles yet. The seed pipeline creates ``OrgTitle`` rows + assigns
    # them via the Phase 47 path so bound roles flow through the
    # standard machinery (45a/45b floor + atomic-swap semantics).
    titles: list[TitleSeed] = field(default_factory=list)
    # Phase 49b B3 — bible-declared cosign-petition proposal that lives
    # in cosign-gathering state at seed time so a demo visitor sees the
    # signature UI in action. Mutually exclusive with normal Proposals
    # only by intent — the field carries a single proposal-shaped
    # tuple. None disables.
    cosign_petition: Optional["CosignPetitionSeed"] = None
    # Phase 49b B3 toggle — whether the seed sets
    # ``settings.allow_cosign_petition = True`` for this org. The
    # cosign-petition seed assumes this is True; leave None to leave
    # the toggle untouched.
    allow_cosign_petition: Optional[bool] = None
    # Phase 49b B2 — whether the seed flips
    # ``settings.elections.enabled = True`` so the elections UI is live
    # for the demo. None leaves the setting untouched.
    elections_enabled: Optional[bool] = None


@dataclass
class CosignPetitionSeed:
    """Phase 49b B3 — bible-declared mid-flight cosign petition.

    Resolves to a Proposal in ``deliberation`` status with
    ``is_cosign_gated=True``, plus a configurable number of
    ``ProposalCosignature`` rows from named demo personas (BELOW the
    threshold so the gathering UI is visible). The author is the
    first listed signer; additional ``signer_user_ids`` add real
    cosigners.
    """
    title: str
    body: str
    author_user_id: str
    signer_user_ids: list[str] = field(default_factory=list)
    cosign_threshold: int = 5
    cosign_expiry_hours: int = 168
    topic_names: list[str] = field(default_factory=list)


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
    'FollowSeed',
    'PrivateDelegationSeed',
    'PersonaDelegationSpec',
    'SubOrg',
    'OrgBible',
    # Trajectory dataclasses
    'Waypoint',
    'TrajectoryEvent',
    'Trajectory',
]
