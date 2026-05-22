"""Phase 35 A3 — synthetic 5x bible generator.

Programmatically produces an OrgBible ~5x the Cedar Hollow scale:
  - ~400 members (vs Cedar Hollow's 76)
  - ~30 proposals (vs ~14)
  - ~100 declared delegations (vs ~10)
  - ~50 public delegate pages
  - ~20 follow relationships

Audit-only: doesn't ship to the demo landing. Run this when you want to
seed a fresh test environment for load testing:

    python scripts/phase35_synthetic_5x_bible.py | python -c "
        import json, sys
        bible_dict = json.load(sys.stdin)
        # ... feed into seed_pipeline.seed_org_from_bible ...
    "

OR import + use directly:

    from scripts.phase35_synthetic_5x_bible import build_5x_bible
    from demo_content.seed_pipeline import seed_org_from_bible
    bible = build_5x_bible()
    seed_org_from_bible(db, bible, {})
"""
from __future__ import annotations

import sys
from pathlib import Path

# Allow running from the project root or backend dir.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from demo_content.schema import (
    Member,
    Proposal,
    DelegatePage,
    TopicVisibility,
    PositionStatement,
    PersonaDelegationSpec,
    PrivateDelegationSeed,
    FollowSeed,
    OrgBible,
)


_FIRST_NAMES = [
    "Alex", "Jordan", "Taylor", "Morgan", "Casey", "Riley", "Quinn", "Avery",
    "Cameron", "Drew", "Emerson", "Finley", "Hayden", "Jaime", "Kelly", "Logan",
    "Madison", "Noel", "Parker", "Reese", "Sage", "Tracy", "Vivian", "Whitney",
    "Bailey", "Carmen", "Dakota", "Ellis", "Frankie", "Gray", "Harper", "Indigo",
    "Jules", "Kai", "Lane", "Marley", "Nico", "Oakley", "Phoenix", "Quincy",
]
_LAST_NAMES = [
    "Anderson", "Brown", "Carter", "Davis", "Evans", "Fisher", "Garcia",
    "Hill", "Ingram", "Johnson", "King", "Lopez", "Miller", "Nguyen",
    "Owens", "Patel", "Quintero", "Reed", "Smith", "Taylor", "Underwood",
    "Vega", "Wong", "Xu", "Young", "Zhang",
]

_TOPICS = ["Budget", "Bylaws", "Maintenance", "Events", "Membership", "Elections"]


def _member(i: int, *, role: str = "Member") -> Member:
    first = _FIRST_NAMES[i % len(_FIRST_NAMES)]
    last = _LAST_NAMES[(i // len(_FIRST_NAMES)) % len(_LAST_NAMES)]
    return Member(
        user_id=f"syn_{i:04d}",
        display_name=f"{first} {last} #{i:04d}",
        quick_login=False,
        role=role,
        notification_preset="medium",
        platform_role="member",
    )


def build_5x_bible() -> OrgBible:
    """Build the synthetic OrgBible. Same shape as production demo bibles
    so it routes through seed_pipeline.seed_org_from_bible unchanged."""
    members: list[Member] = [_member(0, role="Steward")]
    members[0].platform_role = "steward"
    members[0].quick_login = True
    # 1 admin
    admin = _member(1, role="Admin")
    admin.platform_role = "admin"
    members.append(admin)
    # 2 moderators
    for i in range(2, 4):
        m = _member(i, role="Moderator")
        m.platform_role = "moderator"
        members.append(m)
    # ~395 plain members → ~400 total
    for i in range(4, 400):
        members.append(_member(i))

    # Delegate pages: first ~50 members are public delegates with two
    # topics each (round-robin).
    delegate_pages: list[DelegatePage] = []
    for i in range(50):
        topic_a = _TOPICS[i % len(_TOPICS)]
        topic_b = _TOPICS[(i + 2) % len(_TOPICS)]
        delegate_pages.append(DelegatePage(
            member_user_id=members[i].user_id,
            intro=f"Synthetic delegate #{i:04d} for load-test audit.",
            topics=[
                TopicVisibility(topic_a, "public_accepting"),
                TopicVisibility(topic_b, "public"),
            ],
            position_statements=[
                PositionStatement(topic=topic_a, text=f"Position on {topic_a}."),
            ],
        ))

    # 30 proposals — mix of binary / approval / ranked_choice.
    proposals: list[Proposal] = []
    voting_methods = ["binary", "approval", "rcv"]
    states = [
        "voting, day 3 of 7",
        "deliberation, day 5 of 14",
        "passed, 14 days ago (58-42)",
    ]
    for i in range(30):
        method = voting_methods[i % 3]
        state = states[i % 3]
        prop = Proposal(
            proposal_id=f"P-SYN-{i:02d}",
            title=f"Synthetic proposal #{i:02d} ({method})",
            proposer_user_id=members[i % 50].user_id,
            voting_method=method,
            state_at_reset=state,
            body=f"Body for synthetic proposal #{i:02d}. Load-test audit only.",
            topics=[_TOPICS[i % len(_TOPICS)]],
        )
        if method != "binary":
            prop.options = [f"Option A", f"Option B", f"Option C"]
        proposals.append(prop)

    # 20 follows (every fifth member follows a delegate).
    follows: list[FollowSeed] = []
    for i in range(20):
        delegator_idx = 50 + i * 5  # past the delegate range
        followed_idx = i  # one of the delegates
        if delegator_idx >= len(members):
            break
        follows.append(FollowSeed(
            follower_user_id=members[delegator_idx].user_id,
            followed_user_id=members[followed_idx].user_id,
            status="approved",
            permission_level="delegation_allowed",
        ))

    # ~100 private delegations on Budget topic (approved-follow-gated).
    private_delegations: list[PrivateDelegationSeed] = []
    for f in follows[:20]:
        private_delegations.append(PrivateDelegationSeed(
            delegator_user_id=f.follower_user_id,
            delegate_user_id=f.followed_user_id,
            topic="Budget",
        ))

    # Plus persona delegations on the steward + admin so the resolver
    # exercises strict_precedence + relevance_weighted code paths under
    # load.
    persona_delegations = [
        PersonaDelegationSpec(
            delegator_user_id=members[0].user_id,
            delegation_strategy="relevance_weighted",
            delegations=[
                ("Budget", members[2].user_id),  # to a moderator
                ("Bylaws", members[3].user_id),
            ],
            topic_precedence=["Budget", "Bylaws"],
        ),
        PersonaDelegationSpec(
            delegator_user_id=members[1].user_id,
            delegation_strategy="strict_precedence",
            delegations=[
                ("Maintenance", members[5].user_id),
                ("Events", members[6].user_id),
            ],
            topic_precedence=["Maintenance", "Events"],
        ),
    ]

    return OrgBible(
        slug="synthetic-5x-audit",
        display_name="Synthetic 5x Load Test Org",
        charter="Programmatically generated bible for Phase 35 scalability audit.",
        tone_notes="N/A — synthetic.",
        recent_history="N/A — synthetic.",
        voting_methods_used=["binary", "approval", "rcv"],
        # Hide from demo listing — this is audit-only.
        is_demo=False,
        members=members,
        delegate_pages=delegate_pages,
        proposals=proposals,
        follows=follows,
        private_delegations=private_delegations,
        persona_delegations=persona_delegations,
    )


if __name__ == "__main__":
    bible = build_5x_bible()
    print(f"Synthetic 5x bible built:")
    print(f"  slug: {bible.slug}")
    print(f"  members: {len(bible.members)}")
    print(f"  delegate_pages: {len(bible.delegate_pages)}")
    print(f"  proposals: {len(bible.proposals)}")
    print(f"  follows: {len(bible.follows)}")
    print(f"  private_delegations: {len(bible.private_delegations)}")
    print(f"  persona_delegations: {len(bible.persona_delegations)}")
