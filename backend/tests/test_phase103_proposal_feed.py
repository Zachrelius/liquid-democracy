"""Phase 103 compact-feed, cursor, visibility, and batch-vote regressions."""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event

import auth
from database import get_db
from main import app
import models
from proposal_feed import build_feed, global_visibility, member_visibility
from tests.conftest import make_org_membership, make_sub_org_membership, make_user


@pytest.fixture
def client(db):
    def override():
        yield db
    app.dependency_overrides[get_db] = override
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def _org(db, slug, *, public=False, parent=None, private=False):
    row = models.Organization(
        name=slug.title(), slug=slug, parent_org_id=parent,
        discoverability="listed", activity_visibility="public" if public else "members_only",
        settings={"private": private},
    )
    db.add(row)
    db.flush()
    return row


def _proposal(db, org, author, title, *, status="voting", sub=None, when=None, method="binary"):
    when = when or datetime(2026, 8, 30, 12, 0)
    row = models.Proposal(
        title=title, body="detail body must not appear in feed", author_id=author.id,
        org_id=org.id, sub_org_id=sub, status=status, voting_method=method,
        created_at=when, updated_at=when, voting_start=when,
        voting_end=when + timedelta(days=1) if status == "voting" else None,
    )
    db.add(row)
    db.flush()
    return row


def _headers(user):
    return {"Authorization": f"Bearer {auth.create_access_token(user.id)}"}


def test_member_visibility_happens_before_limit_and_private_rows_never_shape_cursor(db):
    viewer = make_user(db, "feed-private-viewer")
    author = make_user(db, "feed-private-author")
    org = _org(db, "feed-private-parent")
    private = _org(db, "feed-private-child", parent=org.id, private=True)
    make_org_membership(db, org_id=org.id, user_id=viewer.id)
    make_org_membership(db, org_id=org.id, user_id=author.id)
    base = datetime(2026, 8, 30, 12, 0)
    # These sort ahead of the visible rows; post-pagination filtering would
    # produce an empty/short first page and leak their existence via cursors.
    for index in range(4):
        _proposal(db, org, author, f"private-{index}", sub=private.id, when=base + timedelta(minutes=index))
    visible = [
        _proposal(db, org, author, f"visible-{index}", when=base + timedelta(hours=index + 1))
        for index in range(3)
    ]
    out = build_feed(
        db, visibility=member_visibility(db, org, viewer, is_admin=False),
        limit=2, viewer=viewer,
    )
    assert len(out.items) == 2
    assert {item.proposal.id for item in out.items}.issubset({p.id for p in visible})
    assert out.has_more is True and out.next_cursor
    page2 = build_feed(
        db, visibility=member_visibility(db, org, viewer, is_admin=False),
        limit=2, cursor=out.next_cursor, viewer=viewer,
    )
    ids = [item.proposal.id for item in out.items + page2.items]
    assert len(ids) == len(set(ids)) == 3
    assert all("private" not in item.proposal.title for item in out.items + page2.items)


def test_direct_private_sub_org_feed_requires_sub_membership_or_parent_admin(client, db):
    parent_member = make_user(db, "feed-direct-private-parent-member")
    sub_member = make_user(db, "feed-direct-private-sub-member")
    parent_admin = make_user(db, "feed-direct-private-admin")
    author = make_user(db, "feed-direct-private-author")
    parent = _org(db, "feed-direct-private-parent")
    child = _org(db, "feed-direct-private-child", parent=parent.id, private=True)
    for user, role in ((parent_member, "member"), (sub_member, "member"), (parent_admin, "admin"), (author, "member")):
        make_org_membership(db, org_id=parent.id, user_id=user.id, role=role)
    make_sub_org_membership(db, sub_org_id=child.id, user_id=sub_member.id)
    proposal = _proposal(db, parent, author, "private-child", sub=child.id)
    db.flush()
    denied = client.get(f"/api/orgs/{child.slug}/proposal-feed", headers=_headers(parent_member))
    assert denied.status_code == 200 and denied.json()["items"] == []
    allowed = client.get(f"/api/orgs/{child.slug}/proposal-feed", headers=_headers(sub_member))
    assert [item["proposal"]["id"] for item in allowed.json()["items"]] == [proposal.id]
    admin = client.get(f"/api/orgs/{child.slug}/proposal-feed", headers=_headers(parent_admin))
    assert [item["proposal"]["id"] for item in admin.json()["items"]] == [proposal.id]


def test_cursor_is_stable_across_null_voting_deadlines_and_terminal_ties(db):
    viewer = make_user(db, "feed-cursor-viewer")
    org = _org(db, "feed-cursor-org")
    make_org_membership(db, org_id=org.id, user_id=viewer.id)
    tied = datetime(2026, 8, 30, 9, 0)
    rows = []
    for index in range(3):
        proposal = _proposal(db, org, viewer, f"null-voting-{index}", when=tied)
        proposal.voting_end = None
        rows.append(proposal)
    for index in range(3):
        rows.append(_proposal(db, org, viewer, f"closed-{index}", status="passed", when=tied))
    db.flush()
    seen = []
    cursor = None
    while True:
        page = build_feed(
            db, visibility=member_visibility(db, org, viewer, is_admin=False),
            limit=2, cursor=cursor, viewer=viewer,
        )
        seen.extend(item.proposal.id for item in page.items)
        if not page.has_more:
            break
        cursor = page.next_cursor
    assert len(seen) == len(set(seen)) == len(rows)
    assert set(seen) == {row.id for row in rows}


def test_batch_viewer_state_resolves_delegation_and_mixed_ballot_shapes(db):
    viewer = make_user(db, "feed-vote-viewer")
    delegate = make_user(db, "feed-vote-delegate", "Trusted Delegate")
    org = _org(db, "feed-votes")
    make_org_membership(db, org_id=org.id, user_id=viewer.id)
    delegate_membership = make_org_membership(db, org_id=org.id, user_id=delegate.id)
    delegate_membership.display_name = "Trusted Delegate In Org"
    db.add(models.Delegation(
        delegator_id=viewer.id, delegate_id=delegate.id, org_id=org.id,
        topic_id=None, chain_behavior="accept_sub",
    ))
    methods = {
        "binary": ("yes", None, None),
        "approval": (None, {"approvals": ["one", "two"]}, 2),
        "ranked_choice": (None, {"ranking": ["one"]}, 1),
        "budget_allocation": (None, {"allocations": {"one": 2.0}}, 1),
        "budget_project": (None, {"ranked": [{"option_id": "one", "tier_id": None}]}, 1),
    }
    expected = {}
    for method, (value, ballot, count) in methods.items():
        proposal = _proposal(db, org, delegate, method, method=method)
        db.add(models.Vote(
            proposal_id=proposal.id, user_id=delegate.id, cast_by_id=delegate.id,
            vote_value=value, ballot=ballot, is_direct=True,
        ))
        expected[proposal.id] = (value, count)
    db.flush()
    out = build_feed(
        db, visibility=member_visibility(db, org, viewer, is_admin=False),
        limit=25, viewer=viewer,
    )
    assert len(out.items) == 5
    for item in out.items:
        vote = item.viewer_vote
        value, count = expected[item.proposal.id]
        assert vote.has_effective_vote is True
        assert vote.is_direct is False
        assert vote.binary_value == value
        assert vote.selection_count == count
        assert vote.cast_by_display_name == "Trusted Delegate In Org"


def test_global_feed_delegations_are_partitioned_by_org_and_admin_nonmember_is_unvoted(db):
    viewer = make_user(db, "feed-global-viewer")
    delegate_a = make_user(db, "feed-global-a")
    delegate_b = make_user(db, "feed-global-b")
    admin = make_user(db, "feed-global-admin")
    admin.is_admin = True
    org_a = _org(db, "feed-global-org-a")
    org_b = _org(db, "feed-global-org-b")
    for org in (org_a, org_b):
        make_org_membership(db, org_id=org.id, user_id=viewer.id)
    make_org_membership(db, org_id=org_a.id, user_id=delegate_a.id)
    make_org_membership(db, org_id=org_b.id, user_id=delegate_b.id)
    db.add_all([
        models.Delegation(delegator_id=viewer.id, delegate_id=delegate_a.id, org_id=org_a.id, topic_id=None, chain_behavior="accept_sub"),
        models.Delegation(delegator_id=viewer.id, delegate_id=delegate_b.id, org_id=org_b.id, topic_id=None, chain_behavior="accept_sub"),
    ])
    p_a = _proposal(db, org_a, delegate_a, "org-a")
    p_b = _proposal(db, org_b, delegate_b, "org-b")
    db.add(models.Vote(
        proposal_id=p_a.id, user_id=delegate_a.id, cast_by_id=delegate_a.id,
        vote_value="yes", is_direct=True,
    ))
    db.flush()
    out = build_feed(db, visibility=global_visibility(db, viewer), viewer=viewer)
    states = {item.proposal.id: item.viewer_vote.has_effective_vote for item in out.items}
    assert states == {p_a.id: True, p_b.id: False}
    admin_out = build_feed(db, visibility=global_visibility(db, admin), viewer=admin)
    assert all(item.viewer_vote.has_effective_vote is False for item in admin_out.items)


def test_unvoted_filter_is_effective_vote_semantics_and_public_has_no_viewer_state(db):
    viewer = make_user(db, "feed-unvoted-viewer")
    delegate = make_user(db, "feed-unvoted-delegate")
    org = _org(db, "feed-unvoted", public=True)
    make_org_membership(db, org_id=org.id, user_id=viewer.id)
    make_org_membership(db, org_id=org.id, user_id=delegate.id)
    db.add(models.Delegation(
        delegator_id=viewer.id, delegate_id=delegate.id, org_id=org.id,
        topic_id=None, chain_behavior="accept_sub",
    ))
    voted = _proposal(db, org, delegate, "delegated-voted")
    pending = _proposal(db, org, delegate, "delegate-not-voted")
    db.add(models.Vote(
        proposal_id=voted.id, user_id=delegate.id, cast_by_id=delegate.id,
        vote_value="no", is_direct=True,
    ))
    db.flush()
    unvoted = build_feed(
        db, visibility=member_visibility(db, org, viewer, is_admin=False),
        status="unvoted", viewer=viewer,
    )
    assert [item.proposal.id for item in unvoted.items] == [pending.id]
    public = build_feed(
        db,
        visibility=(models.Proposal.org_id == org.id) & models.Proposal.sub_org_id.is_(None),
        public=True,
    )
    assert all(item.viewer_vote is None for item in public.items)
    with pytest.raises(Exception) as caught:
        build_feed(db, visibility=models.Proposal.org_id == org.id, public=True, status="unvoted")
    assert getattr(caught.value, "status_code", None) == 422


def test_endpoints_expose_compact_shape_and_reject_bad_cursor_as_typed_422(client, db):
    viewer = make_user(db, "feed-endpoint-viewer")
    org = _org(db, "feed-endpoint", public=True)
    make_org_membership(db, org_id=org.id, user_id=viewer.id)
    _proposal(db, org, viewer, "compact")
    db.flush()
    member = client.get(f"/api/orgs/{org.slug}/proposal-feed", headers=_headers(viewer))
    assert member.status_code == 200, member.text
    proposal = member.json()["items"][0]["proposal"]
    assert "body" not in proposal and "options" not in proposal and "option_count" in proposal
    public = client.get(f"/api/orgs/{org.slug}/public/proposal-feed?limit=5")
    assert public.status_code == 200 and public.json()["items"][0]["viewer_vote"] is None
    malformed = client.get(f"/api/orgs/{org.slug}/proposal-feed?cursor=!!!", headers=_headers(viewer))
    assert malformed.status_code == 422
    assert malformed.json()["detail"]["code"] == "invalid_feed_cursor"


def test_query_budgets_are_constant_for_page_and_250_candidate_unvoted(client, db):
    viewer = make_user(db, "feed-query-viewer")
    delegate = make_user(db, "feed-query-delegate")
    org = _org(db, "feed-query-org", public=True)
    make_org_membership(db, org_id=org.id, user_id=viewer.id)
    make_org_membership(db, org_id=org.id, user_id=delegate.id)
    db.add(models.Delegation(
        delegator_id=viewer.id, delegate_id=delegate.id, org_id=org.id,
        topic_id=None, chain_behavior="accept_sub",
    ))
    for index in range(250):
        proposal = _proposal(
            db, org, viewer, f"query-{index}",
            when=datetime(2026, 8, 30, 12, 0) + timedelta(seconds=index),
        )
        if index % 2 == 0:
            db.add(models.Vote(
                proposal_id=proposal.id, user_id=delegate.id, cast_by_id=delegate.id,
                vote_value="yes", is_direct=True,
            ))
    db.flush()
    statements = []

    def count(_conn, _cursor, statement, _parameters, _context, _executemany):
        statements.append(statement)

    event.listen(db.bind, "before_cursor_execute", count)
    try:
        normal = client.get(f"/api/orgs/{org.slug}/proposal-feed?limit=25", headers=_headers(viewer))
        normal_count = len(statements)
        statements.clear()
        public = client.get(f"/api/orgs/{org.slug}/public/proposal-feed?limit=25")
        public_count = len(statements)
        statements.clear()
        global_response = client.get("/api/proposal-feed?limit=25", headers=_headers(viewer))
        global_count = len(statements)
        statements.clear()
        unvoted = client.get(
            f"/api/orgs/{org.slug}/proposal-feed?status=unvoted&limit=25",
            headers=_headers(viewer),
        )
        unvoted_count = len(statements)
    finally:
        event.remove(db.bind, "before_cursor_execute", count)
    assert normal.status_code == 200 and len(normal.json()["items"]) == 25
    assert normal_count <= 30
    assert public.status_code == 200 and len(public.json()["items"]) == 25
    assert public_count <= 12
    assert global_response.status_code == 200 and len(global_response.json()["items"]) == 25
    assert global_count <= 30
    assert unvoted.status_code == 200 and len(unvoted.json()["items"]) == 25
    assert unvoted_count <= 40
    print(
        "phase103 route SQL counts "
        f"member={normal_count} public={public_count} global={global_count} unvoted250={unvoted_count}"
    )
    # Kept in the assertion message/output to make the exact evidence visible
    # without production SQL logging.


def test_access_filters_archived_mapping_and_public_404_posture(client, db):
    member = make_user(db, "feed-access-member")
    outsider = make_user(db, "feed-access-outsider")
    org = _org(db, "feed-access", public=False)
    make_org_membership(db, org_id=org.id, user_id=member.id)
    topic = models.Topic(name="Feed Topic", color="#123456", org_id=org.id)
    db.add(topic)
    active = _proposal(db, org, member, "active", status="deliberation")
    archived = _proposal(db, org, member, "archived", status="withdrawn")
    db.add_all([
        models.ProposalTopic(proposal_id=active.id, topic_id=topic.id, relevance=0.7),
        models.ProposalTopic(proposal_id=archived.id, topic_id=topic.id, relevance=1.0),
    ])
    db.flush()
    assert client.get(f"/api/orgs/{org.slug}/proposal-feed").status_code == 401
    assert client.get(f"/api/orgs/{org.slug}/proposal-feed", headers=_headers(outsider)).status_code == 403
    assert client.get(f"/api/orgs/{org.slug}/public/proposal-feed").status_code == 404
    all_feed = client.get(f"/api/orgs/{org.slug}/proposal-feed", headers=_headers(member)).json()
    assert [item["proposal"]["id"] for item in all_feed["items"]] == [active.id]
    assert all_feed["items"][0]["proposal"]["topics"][0]["topic"]["name"] == "Feed Topic"
    archived_feed = client.get(
        f"/api/orgs/{org.slug}/proposal-feed?status=archived&topic_id={topic.id}",
        headers=_headers(member),
    ).json()
    assert [item["proposal"]["id"] for item in archived_feed["items"]] == [archived.id]
    invalid = client.get(f"/api/orgs/{org.slug}/proposal-feed?status=bogus", headers=_headers(member))
    assert invalid.status_code == 422 and invalid.json()["detail"]["code"] == "invalid_feed_status"


def test_delegation_parity_direct_topic_precedence_two_hop_cycle_and_weighted_presence(db):
    viewer = make_user(db, "feed-parity-viewer")
    global_delegate = make_user(db, "feed-parity-global")
    topic_delegate = make_user(db, "feed-parity-topic")
    final_delegate = make_user(db, "feed-parity-final")
    org = _org(db, "feed-parity", public=False)
    org.settings = {"weighted_voting": {"enabled": True, "unit_label": "shares"}}
    memberships = {}
    for user in (viewer, global_delegate, topic_delegate, final_delegate):
        memberships[user.id] = make_org_membership(db, org_id=org.id, user_id=user.id)
    memberships[viewer.id].voting_weight = 9
    topic_a = models.Topic(name="Parity A", color="#111111", org_id=org.id)
    topic_b = models.Topic(name="Parity B", color="#222222", org_id=org.id)
    db.add_all([topic_a, topic_b])
    db.flush()
    db.add_all([
        models.Delegation(delegator_id=viewer.id, delegate_id=global_delegate.id, org_id=org.id, topic_id=None, chain_behavior="accept_sub"),
        models.Delegation(delegator_id=viewer.id, delegate_id=topic_delegate.id, org_id=org.id, topic_id=topic_a.id, chain_behavior="accept_sub"),
        models.Delegation(delegator_id=topic_delegate.id, delegate_id=final_delegate.id, org_id=org.id, topic_id=topic_a.id, chain_behavior="accept_sub"),
    ])
    direct = _proposal(db, org, viewer, "direct-wins")
    topic_chain = _proposal(db, org, viewer, "topic-two-hop")
    db.add(models.ProposalTopic(proposal_id=topic_chain.id, topic_id=topic_a.id, relevance=1.0))
    pending = _proposal(db, org, viewer, "pending-global")
    db.add_all([
        models.Vote(proposal_id=direct.id, user_id=viewer.id, cast_by_id=viewer.id, vote_value="no", is_direct=True),
        models.Vote(proposal_id=direct.id, user_id=global_delegate.id, cast_by_id=global_delegate.id, vote_value="yes", is_direct=True),
        models.Vote(proposal_id=topic_chain.id, user_id=final_delegate.id, cast_by_id=final_delegate.id, vote_value="yes", is_direct=True),
    ])
    db.flush()
    out = build_feed(db, visibility=member_visibility(db, org, viewer, is_admin=False), viewer=viewer)
    states = {item.proposal.title: item.viewer_vote for item in out.items}
    assert states["direct-wins"].is_direct is True and states["direct-wins"].binary_value == "no"
    assert states["topic-two-hop"].is_direct is False and states["topic-two-hop"].binary_value == "yes"
    assert states["pending-global"].has_effective_vote is False

    # Isolated org creates a true delegation cycle with no direct ballot.
    cycle_org = _org(db, "feed-parity-cycle")
    cycle_a = make_user(db, "feed-parity-cycle-a")
    cycle_b = make_user(db, "feed-parity-cycle-b")
    make_org_membership(db, org_id=cycle_org.id, user_id=cycle_a.id)
    make_org_membership(db, org_id=cycle_org.id, user_id=cycle_b.id)
    db.add_all([
        models.Delegation(delegator_id=cycle_a.id, delegate_id=cycle_b.id, org_id=cycle_org.id, topic_id=None, chain_behavior="accept_sub"),
        models.Delegation(delegator_id=cycle_b.id, delegate_id=cycle_a.id, org_id=cycle_org.id, topic_id=None, chain_behavior="accept_sub"),
    ])
    cycle_proposal = _proposal(db, cycle_org, cycle_a, "cycle")
    db.flush()
    cycle = build_feed(
        db, visibility=member_visibility(db, cycle_org, cycle_a, is_admin=False), viewer=cycle_a,
    )
    assert cycle.items[0].proposal.id == cycle_proposal.id
    assert cycle.items[0].viewer_vote.has_effective_vote is False
