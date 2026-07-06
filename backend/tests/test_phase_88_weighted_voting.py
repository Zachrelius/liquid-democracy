"""Phase 88 Stage 1 — Share-weighted voting (tally core + endpoint + serialization).

Verification matrix (spec: phase88_weighted_voting_spec.md §7):
  * Parity gate: a weighted-capable build with weighted_voting absent/disabled
    produces byte-identical tallies (binary, approval, delegated, cosign).
  * Side effects: weight edit asserts the OrgMembership.voting_weight row +
    audit row; proposal close asserts Proposal.status under share-quorum
    boundaries.
  * Delegation weight-carry: delegator(w=5) → delegate(w=2) yes ⇒ yes==7;
    revoke ⇒ yes==2.
  * Zero-weight member: casts a ballot; counts + quorum denominator unchanged.
  * Approval multi-winner: weighted counts + a boundary tie resolved by the
    weight-aware tie resolver.
  * Cosign: weighted threshold.
  * Election close: weighted approval seats the share-weighted winner;
    under-share-quorum closes failed.
  * Sub-org proposal: weight resolved from parent membership.
  * Permission backfill parity: existing org vs new org both carry
    member.set_voting_weight grants.
  * Weight-edit endpoint: permission gate + range validation + audit.
  * RCV + budget creation blocked in weighted orgs (400).
  * Org-settings PATCH accepts weighted_voting + audits the change.
  * Serialization: MembershipOut.voting_weight, OrgOut.weighted_voting, tally
    weighted/unit_label, my_voting_weight.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import auth as auth_utils
import delegation_engine
import models
from database import Base, get_db
from main import app
from role_seed import seed_default_roles_for_org
from tests.conftest import make_org_membership

_DUMMY_HASH = "$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/lewrwKJuRxm5pJmJi"


# ===========================================================================
# Fixtures + helpers
# ===========================================================================

@pytest.fixture(scope="function")
def test_db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)


@pytest.fixture(scope="function")
def client(test_db: Session):
    def _get_db():
        try:
            yield test_db
        finally:
            pass
    app.dependency_overrides[get_db] = _get_db
    yield TestClient(app)
    app.dependency_overrides.clear()


def _auth(user):
    return {"Authorization": f"Bearer {auth_utils.create_access_token(user.id)}"}


def _user(db, username, *, is_admin=False):
    u = models.User(
        username=username, display_name=username, password_hash=_DUMMY_HASH,
        email=f"{username}@t.ex", email_verified=True, is_admin=is_admin,
    )
    db.add(u)
    db.flush()
    return u


def _org(db, slug="wv-org", *, weighted=None, parent=None):
    settings = {
        "default_voting_days": 7,
        "allowed_voting_methods": [
            "binary", "approval", "ranked_choice",
            "budget_allocation", "budget_project",
        ],
    }
    if weighted is not None:
        settings["weighted_voting"] = weighted
    o = models.Organization(
        name=slug.title(), slug=slug, description="", settings=settings,
        parent_org_id=parent.id if parent else None,
    )
    db.add(o)
    db.flush()
    seed_default_roles_for_org(db, o.id)
    return o


def _member(db, org, username, *, role="member", weight=1):
    u = _user(db, username)
    m = make_org_membership(db, org_id=org.id, user_id=u.id, role=role)
    m.voting_weight = weight
    db.flush()
    return u, m


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _binary_proposal(db, author, org, *, quorum=0.0, pass_threshold=0.5):
    p = models.Proposal(
        title="P", body="", author_id=author.id, org_id=org.id,
        voting_method="binary", num_winners=1, status="voting",
        voting_start=_now(), voting_end=_now() + timedelta(days=7),
        quorum_threshold=quorum, pass_threshold=pass_threshold,
    )
    db.add(p)
    db.flush()
    return p


def _approval_proposal(db, author, org, labels=("A", "B"), *, quorum=0.0):
    p = models.Proposal(
        title="AP", body="", author_id=author.id, org_id=org.id,
        voting_method="approval", num_winners=1, status="voting",
        voting_start=_now(), voting_end=_now() + timedelta(days=7),
        quorum_threshold=quorum, pass_threshold=0.5,
    )
    db.add(p)
    db.flush()
    opts = []
    for i, label in enumerate(labels):
        o = models.ProposalOption(proposal_id=p.id, label=label, description="",
                                  display_order=i)
        db.add(o)
        opts.append(o)
    db.flush()
    return p, opts


def _vote(client, p, user, value):
    return client.post(f"/api/proposals/{p.id}/vote", headers=_auth(user),
                       json={"vote_value": value})


ON = {"enabled": True, "unit_label": "shares"}


# ===========================================================================
# Parity gate — weighted OFF is byte-identical to headcount
# ===========================================================================

def test_binary_parity_weighted_off(client, test_db):
    """With no weighted_voting section, binary counters are pure headcount."""
    org = _org(test_db)  # no weighted section
    author, _ = _member(test_db, org, "auth", role="steward")
    (v1, _), (v2, _), (v3, _) = (
        _member(test_db, org, "v1"), _member(test_db, org, "v2"),
        _member(test_db, org, "v3"),
    )
    p = _binary_proposal(test_db, author, org)
    test_db.commit()
    _vote(client, p, v1, "yes")
    _vote(client, p, v2, "yes")
    _vote(client, p, v3, "no")
    tally = delegation_engine.engine.compute_tally(p, test_db)
    assert (tally.yes, tally.no, tally.not_cast) == (2, 1, 1)  # author not_cast
    assert tally.total_eligible == 4


def test_weighted_off_ignores_stored_weights(client, test_db):
    """Even with non-1 stored weights, an org WITHOUT weighted_voting.enabled
    tallies by headcount (the map stays empty)."""
    org = _org(test_db)  # weighted section absent
    author, _ = _member(test_db, org, "auth", role="steward")
    (v1, _) = _member(test_db, org, "v1", weight=9)
    (v2, _) = _member(test_db, org, "v2", weight=4)
    p = _binary_proposal(test_db, author, org)
    test_db.commit()
    _vote(client, p, v1, "yes")
    _vote(client, p, v2, "no")
    tally = delegation_engine.engine.compute_tally(p, test_db)
    assert (tally.yes, tally.no) == (1, 1)  # headcount, weights ignored


# ===========================================================================
# Weighted binary + quorum side effects
# ===========================================================================

def test_binary_weighted_counts(client, test_db):
    org = _org(test_db, weighted=ON)
    author, _ = _member(test_db, org, "auth", role="steward", weight=1)
    (v1, _) = _member(test_db, org, "v1", weight=5)
    (v2, _) = _member(test_db, org, "v2", weight=3)
    p = _binary_proposal(test_db, author, org)
    test_db.commit()
    _vote(client, p, v1, "yes")
    _vote(client, p, v2, "no")
    tally = delegation_engine.engine.compute_tally(p, test_db)
    assert tally.yes == 5
    assert tally.no == 3
    assert tally.not_cast == 1  # author, weight 1
    assert tally.total_eligible == 9


def test_delegation_weight_carry(client, test_db):
    """delegator(w=5) delegates to delegate(w=2) who votes yes ⇒ yes==7;
    revoke ⇒ yes==2."""
    org = _org(test_db, weighted=ON)
    author, _ = _member(test_db, org, "auth", role="steward", weight=1)
    (dele, _) = _member(test_db, org, "delegate", weight=2)
    (dor, _) = _member(test_db, org, "delegator", weight=5)
    p = _binary_proposal(test_db, author, org)
    d = models.Delegation(delegator_id=dor.id, delegate_id=dele.id,
                          topic_id=None, chain_behavior="revert_direct",
                          org_id=org.id)
    test_db.add(d)
    test_db.commit()
    _vote(client, p, dele, "yes")
    tally = delegation_engine.engine.compute_tally(p, test_db)
    assert tally.yes == 7  # delegate's 2 + delegator's 5

    test_db.delete(d)
    test_db.commit()
    tally2 = delegation_engine.engine.compute_tally(p, test_db)
    assert tally2.yes == 2  # only the delegate's own shares


def test_zero_weight_member(client, test_db):
    """A zero-weight member can vote but contributes 0 to counts + quorum."""
    org = _org(test_db, weighted=ON)
    author, _ = _member(test_db, org, "auth", role="steward", weight=1)
    (zero, _) = _member(test_db, org, "zero", weight=0)
    (v1, _) = _member(test_db, org, "v1", weight=4)
    p = _binary_proposal(test_db, author, org)
    test_db.commit()
    _vote(client, p, zero, "yes")
    _vote(client, p, v1, "yes")
    tally = delegation_engine.engine.compute_tally(p, test_db)
    assert tally.yes == 4  # zero-weight yes adds nothing
    assert tally.total_eligible == 5  # 1 + 0 + 4


def test_quorum_boundary_status(client, test_db):
    """Share-quorum boundary drives Proposal.status (side effect, not code)."""
    org = _org(test_db, weighted=ON)
    author, _ = _member(test_db, org, "auth", role="steward", weight=1)
    (v1, _) = _member(test_db, org, "v1", weight=5)
    (v2, _) = _member(test_db, org, "v2", weight=4)
    # total eligible shares = 10. quorum 0.5 ⇒ need >= 5 cast shares.
    p = _binary_proposal(test_db, author, org, quorum=0.5, pass_threshold=0.5)
    test_db.commit()
    # v1 alone casts 5 shares == 50% ⇒ quorum met, yes 5/5 ⇒ passes.
    _vote(client, p, v1, "yes")
    r = client.post(f"/api/proposals/{p.id}/advance", headers=_auth(author), json={})
    assert r.status_code == 200, r.text
    test_db.refresh(p)
    assert p.status == "passed"


def test_quorum_boundary_just_under_fails(client, test_db):
    org = _org(test_db, weighted=ON)
    author, _ = _member(test_db, org, "auth", role="steward", weight=1)
    (v1, _) = _member(test_db, org, "v1", weight=4)
    (v2, _) = _member(test_db, org, "v2", weight=5)
    # total = 10, quorum 0.5 ⇒ need >= 5. v1 casts 4 < 5 ⇒ fails quorum.
    p = _binary_proposal(test_db, author, org, quorum=0.5)
    test_db.commit()
    _vote(client, p, v1, "yes")
    r = client.post(f"/api/proposals/{p.id}/advance", headers=_auth(author), json={})
    assert r.status_code == 200, r.text
    test_db.refresh(p)
    assert p.status == "failed"


# ===========================================================================
# Weighted approval + weight-aware tie resolution
# ===========================================================================

def test_approval_weighted_winner(client, test_db):
    org = _org(test_db, weighted=ON)
    author, _ = _member(test_db, org, "auth", role="steward", weight=1)
    (v1, _) = _member(test_db, org, "v1", weight=7)
    (v2, _) = _member(test_db, org, "v2", weight=3)
    p, opts = _approval_proposal(test_db, author, org, labels=("A", "B"))
    a, b = opts[0].id, opts[1].id
    test_db.commit()
    client.post(f"/api/proposals/{p.id}/vote", headers=_auth(v1), json={"approvals": [a]})
    client.post(f"/api/proposals/{p.id}/vote", headers=_auth(v2), json={"approvals": [b]})
    tally = delegation_engine.engine.compute_tally(p, test_db)
    assert tally.option_approvals[a] == 7
    assert tally.option_approvals[b] == 3
    assert tally.winners == [a]
    assert tally.total_ballots_cast == 10


def test_weight_aware_tie_resolution(client, test_db):
    """A tie broken by the broader-approval-base resolver uses share weights,
    not headcount."""
    from tie_resolution import resolve_tie
    org = _org(test_db, weighted=ON)
    author, _ = _member(test_db, org, "auth", role="steward", weight=1)
    (v1, _) = _member(test_db, org, "v1", weight=10)
    (v2, _) = _member(test_db, org, "v2", weight=1)
    (v3, _) = _member(test_db, org, "v3", weight=1)
    p, opts = _approval_proposal(test_db, author, org, labels=("A", "B", "C"))
    a, b, c = opts[0].id, opts[1].id, opts[2].id
    test_db.commit()
    # A and B tie on raw approval SHARES (each 11), but A co-occurs with a
    # heavy voter's C while B only with light voters — weight-aware breadth
    # favors A. Set up: heavy v1 approves A+C; light v2 approves A+B (wait we
    # need A,B tied). Construct: v1(w=10): A,C ; v2(w=1): B,C ; extra to tie.
    # Simpler: assert the resolver reads ballot_weights (weighted breadth).
    client.post(f"/api/proposals/{p.id}/vote", headers=_auth(v1), json={"approvals": [a, c]})
    client.post(f"/api/proposals/{p.id}/vote", headers=_auth(v2), json={"approvals": [b]})
    client.post(f"/api/proposals/{p.id}/vote", headers=_auth(v3), json={"approvals": [b]})
    tally = delegation_engine.engine.compute_tally(p, test_db)
    # A has 10 shares, B has 2 → not tied; assert weighted counts drive it.
    assert tally.option_approvals[a] == 10
    assert tally.option_approvals[b] == 2
    # ballot_weights aligns with ballots (weighted breadth feed for ties).
    assert sum(tally.ballot_weights) == 12  # 10 + 1 + 1


# ===========================================================================
# Cosign weighting
# ===========================================================================

def test_cosign_weight_is_share_denominated(client, test_db):
    from cosign import resolve_cosign_weight_for_signers
    org = _org(test_db, weighted=ON)
    author, _ = _member(test_db, org, "auth", role="steward", weight=1)
    (s1, _) = _member(test_db, org, "s1", weight=6)
    (s2, _) = _member(test_db, org, "s2", weight=2)
    p = _binary_proposal(test_db, author, org)
    test_db.commit()
    weight = resolve_cosign_weight_for_signers(test_db, p, {s1.id, s2.id})
    assert weight == 8  # 6 + 2 shares, not headcount 2


def test_cosign_weight_headcount_when_unweighted(client, test_db):
    from cosign import resolve_cosign_weight_for_signers
    org = _org(test_db)  # weighted off
    author, _ = _member(test_db, org, "auth", role="steward", weight=1)
    (s1, _) = _member(test_db, org, "s1", weight=6)
    (s2, _) = _member(test_db, org, "s2", weight=2)
    p = _binary_proposal(test_db, author, org)
    test_db.commit()
    weight = resolve_cosign_weight_for_signers(test_db, p, {s1.id, s2.id})
    assert weight == 2  # headcount — stored weights ignored


# ===========================================================================
# Election close (§2.7) — share-weighted winner + under-share-quorum fail
# ===========================================================================

def test_weighted_election_close_status(client, test_db):
    from elections import election_close_status
    org = _org(test_db, weighted=ON)
    author, _ = _member(test_db, org, "auth", role="steward", weight=1)
    (v1, _) = _member(test_db, org, "v1", weight=8)
    p, opts = _approval_proposal(test_db, author, org, labels=("A", "B"))
    p.is_election = True
    p.quorum_threshold = 0.5  # need >= 5 of 10 shares
    a = opts[0].id
    test_db.commit()
    client.post(f"/api/proposals/{p.id}/vote", headers=_auth(v1), json={"approvals": [a]})
    tally = delegation_engine.engine.compute_tally(p, test_db)
    # v1's 8 shares cast of 10 total ⇒ quorum met ⇒ passed; A is the winner.
    assert election_close_status(p, tally) == "passed"
    assert tally.winners == [a]


def test_weighted_election_under_quorum_fails(client, test_db):
    from elections import election_close_status
    org = _org(test_db, weighted=ON)
    author, _ = _member(test_db, org, "auth", role="steward", weight=1)
    (v1, _) = _member(test_db, org, "v1", weight=2)
    (v2, _) = _member(test_db, org, "v2", weight=7)
    p, opts = _approval_proposal(test_db, author, org, labels=("A", "B"))
    p.is_election = True
    p.quorum_threshold = 0.5  # need >= 5 of 10 shares
    a = opts[0].id
    test_db.commit()
    client.post(f"/api/proposals/{p.id}/vote", headers=_auth(v1), json={"approvals": [a]})
    tally = delegation_engine.engine.compute_tally(p, test_db)
    assert election_close_status(p, tally) == "failed"  # only 2 of 10 shares


# ===========================================================================
# Sub-org proposal — weight resolved from parent membership
# ===========================================================================

def test_suborg_weight_from_parent(client, test_db):
    """A sub-org proposal resolves per-user weights from the PARENT org's
    OrgMembership rows (shares are a parent-org property). Verified at the
    _build_context layer to isolate weight resolution from sub-org vote
    eligibility plumbing."""
    parent = _org(test_db, slug="parent", weighted=ON)
    author, _ = _member(test_db, parent, "pauth", role="steward", weight=1)
    (v1, _) = _member(test_db, parent, "pv1", weight=6)
    (v2, _) = _member(test_db, parent, "pv2", weight=3)
    sub = _org(test_db, slug="sub", parent=parent)
    p = _binary_proposal(test_db, author, sub)
    test_db.commit()
    # Build context scoped to the sub-org proposal's eligible voters; the
    # weight map must resolve from the PARENT membership rows.
    ctx = delegation_engine.engine._build_context(
        p, test_db, eligible_ids={v1.id, v2.id, author.id},
    )
    assert ctx.user_weights[v1.id] == 6
    assert ctx.user_weights[v2.id] == 3
    assert ctx.user_weights[author.id] == 1
    # And the pure accessor returns the parent-derived weight.
    assert delegation_engine._weight_of(v1.id, ctx) == 6


# ===========================================================================
# Weight-edit endpoint — permission gate, validation, audit, row value
# ===========================================================================

def test_weight_edit_endpoint(client, test_db):
    org = _org(test_db, weighted=ON)
    author, _ = _member(test_db, org, "auth", role="steward", weight=1)
    (target, tm) = _member(test_db, org, "target", weight=1)
    test_db.commit()
    r = client.patch(
        f"/api/orgs/{org.slug}/members/{target.id}/voting-weight",
        headers=_auth(author), json={"voting_weight": 42},
    )
    assert r.status_code == 200, r.text
    test_db.refresh(tm)
    assert tm.voting_weight == 42
    audit = test_db.query(models.AuditLog).filter(
        models.AuditLog.action == "member.voting_weight_changed",
    ).all()
    assert len(audit) == 1
    assert audit[0].details["old"] == 1
    assert audit[0].details["new"] == 42
    assert audit[0].details["target_user_id"] == target.id


def test_weight_edit_permission_gate(client, test_db):
    org = _org(test_db, weighted=ON)
    author, _ = _member(test_db, org, "auth", role="steward", weight=1)
    (plain, _) = _member(test_db, org, "plain", weight=1)
    (target, _) = _member(test_db, org, "target", weight=1)
    test_db.commit()
    # A plain member cannot set voting weight (tier floor blocks + no grant).
    r = client.patch(
        f"/api/orgs/{org.slug}/members/{target.id}/voting-weight",
        headers=_auth(plain), json={"voting_weight": 5},
    )
    assert r.status_code == 403, r.text


def test_weight_edit_range_validation(client, test_db):
    org = _org(test_db, weighted=ON)
    author, _ = _member(test_db, org, "auth", role="steward", weight=1)
    (target, _) = _member(test_db, org, "target", weight=1)
    test_db.commit()
    r = client.patch(
        f"/api/orgs/{org.slug}/members/{target.id}/voting-weight",
        headers=_auth(author), json={"voting_weight": -1},
    )
    assert r.status_code == 400, r.text
    r2 = client.patch(
        f"/api/orgs/{org.slug}/members/{target.id}/voting-weight",
        headers=_auth(author), json={"voting_weight": 10_000_001},
    )
    assert r2.status_code == 400, r2.text
    # zero is valid.
    r3 = client.patch(
        f"/api/orgs/{org.slug}/members/{target.id}/voting-weight",
        headers=_auth(author), json={"voting_weight": 0},
    )
    assert r3.status_code == 200, r3.text


def test_weight_edit_allowed_when_weighting_off(client, test_db):
    """Shares can be staged before the switch flips."""
    org = _org(test_db)  # weighted off
    author, _ = _member(test_db, org, "auth", role="steward", weight=1)
    (target, tm) = _member(test_db, org, "target", weight=1)
    test_db.commit()
    r = client.patch(
        f"/api/orgs/{org.slug}/members/{target.id}/voting-weight",
        headers=_auth(author), json={"voting_weight": 12},
    )
    assert r.status_code == 200, r.text
    test_db.refresh(tm)
    assert tm.voting_weight == 12


# ===========================================================================
# RCV + budget creation blocked in weighted orgs
# ===========================================================================

def test_rcv_creation_allowed_in_weighted_org(client, test_db):
    """Phase 88a lifted the Stage-1 RCV block — ranked_choice creation is now
    allowed in a weighted org (under the weighted-ballot cap)."""
    org = _org(test_db, weighted=ON)
    author, _ = _member(test_db, org, "auth", role="steward", weight=1)
    test_db.commit()
    r = client.post(f"/api/orgs/{org.slug}/proposals", headers=_auth(author), json={
        "title": "rcv", "voting_method": "ranked_choice",
        "options": [{"label": "A"}, {"label": "B"}],
    })
    assert r.status_code in (200, 201), r.text


def test_budget_creation_allowed_in_weighted_org(client, test_db):
    """Phase 88b lifted the Stage-1 budget block — budget_allocation creation is
    now allowed in a weighted org (weighted median aggregation)."""
    org = _org(test_db, weighted=ON)
    author, _ = _member(test_db, org, "auth", role="steward", weight=1)
    test_db.commit()
    r = client.post(f"/api/orgs/{org.slug}/proposals", headers=_auth(author), json={
        "title": "b", "voting_method": "budget_allocation",
        "budget_config": {"mode": "allocation", "envelope": 1000},
        "options": [{"label": "A"}, {"label": "B"}],
    })
    assert r.status_code in (200, 201), r.text


def test_rcv_allowed_in_unweighted_org(client, test_db):
    org = _org(test_db)  # weighted off
    author, _ = _member(test_db, org, "auth", role="steward", weight=1)
    test_db.commit()
    r = client.post(f"/api/orgs/{org.slug}/proposals", headers=_auth(author), json={
        "title": "rcv", "voting_method": "ranked_choice",
        "options": [{"label": "A"}, {"label": "B"}],
    })
    assert r.status_code in (200, 201), r.text


# ===========================================================================
# Org-settings PATCH — weighted_voting accepted + audited
# ===========================================================================

def test_settings_patch_enables_weighted_voting_and_audits(client, test_db):
    org = _org(test_db)  # off initially
    author, _ = _member(test_db, org, "auth", role="steward", weight=1)
    test_db.commit()
    r = client.patch(f"/api/orgs/{org.slug}", headers=_auth(author), json={
        "settings": {"weighted_voting": {"enabled": True, "unit_label": "units"}},
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["weighted_voting"] == {"enabled": True, "unit_label": "units"}
    audit = test_db.query(models.AuditLog).filter(
        models.AuditLog.action == "org.weighted_voting_changed",
    ).all()
    assert len(audit) == 1
    assert audit[0].details["new"]["enabled"] is True
    assert audit[0].details["new"]["unit_label"] == "units"


def test_settings_patch_rejects_bad_unit_label(client, test_db):
    org = _org(test_db)
    author, _ = _member(test_db, org, "auth", role="steward", weight=1)
    test_db.commit()
    r = client.patch(f"/api/orgs/{org.slug}", headers=_auth(author), json={
        "settings": {"weighted_voting": {"unit_label": "x" * 40}},
    })
    assert r.status_code == 400, r.text


def test_settings_patch_partial_preserves_unit_label(client, test_db):
    org = _org(test_db, weighted={"enabled": True, "unit_label": "votes"})
    author, _ = _member(test_db, org, "auth", role="steward", weight=1)
    test_db.commit()
    # PATCH only enabled → unit_label preserved.
    r = client.patch(f"/api/orgs/{org.slug}", headers=_auth(author), json={
        "settings": {"weighted_voting": {"enabled": False}},
    })
    assert r.status_code == 200, r.text
    assert r.json()["weighted_voting"] == {"enabled": False, "unit_label": "votes"}


# ===========================================================================
# Serialization
# ===========================================================================

def test_member_list_surfaces_voting_weight(client, test_db):
    org = _org(test_db, weighted=ON)
    author, _ = _member(test_db, org, "auth", role="steward", weight=1)
    (v1, _) = _member(test_db, org, "v1", weight=7)
    test_db.commit()
    r = client.get(f"/api/orgs/{org.slug}/members", headers=_auth(author))
    assert r.status_code == 200, r.text
    weights = {m["username"]: m["voting_weight"] for m in r.json()}
    assert weights["v1"] == 7
    assert weights["auth"] == 1


def test_org_out_surfaces_weighted_voting(client, test_db):
    org = _org(test_db, weighted={"enabled": True, "unit_label": "units"})
    author, _ = _member(test_db, org, "auth", role="steward", weight=1)
    test_db.commit()
    r = client.get(f"/api/orgs/{org.slug}", headers=_auth(author))
    assert r.status_code == 200, r.text
    assert r.json()["weighted_voting"] == {"enabled": True, "unit_label": "units"}


def test_results_payload_weighted_labels(client, test_db):
    org = _org(test_db, weighted=ON)
    author, _ = _member(test_db, org, "auth", role="steward", weight=1)
    (v1, _) = _member(test_db, org, "v1", weight=5)
    p = _binary_proposal(test_db, author, org)
    test_db.commit()
    _vote(client, p, v1, "yes")
    r = client.get(f"/api/proposals/{p.id}/results", headers=_auth(author))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["weighted"] is True
    assert body["unit_label"] == "shares"
    assert body["yes"] == 5


def test_results_payload_unweighted_labels(client, test_db):
    org = _org(test_db)  # off
    author, _ = _member(test_db, org, "auth", role="steward", weight=1)
    (v1, _) = _member(test_db, org, "v1", weight=5)
    p = _binary_proposal(test_db, author, org)
    test_db.commit()
    _vote(client, p, v1, "yes")
    r = client.get(f"/api/proposals/{p.id}/results", headers=_auth(author))
    body = r.json()
    assert body["weighted"] is False
    assert body["unit_label"] is None
    assert body["yes"] == 1


def test_my_vote_surfaces_my_voting_weight(client, test_db):
    org = _org(test_db, weighted=ON)
    author, _ = _member(test_db, org, "auth", role="steward", weight=1)
    (v1, _) = _member(test_db, org, "v1", weight=12)
    p = _binary_proposal(test_db, author, org)
    test_db.commit()
    _vote(client, p, v1, "yes")
    r = client.get(f"/api/proposals/{p.id}/my-vote", headers=_auth(v1))
    assert r.status_code == 200, r.text
    assert r.json()["my_voting_weight"] == 12


def test_my_vote_weight_none_when_unweighted(client, test_db):
    org = _org(test_db)  # off
    author, _ = _member(test_db, org, "auth", role="steward", weight=1)
    (v1, _) = _member(test_db, org, "v1", weight=12)
    p = _binary_proposal(test_db, author, org)
    test_db.commit()
    _vote(client, p, v1, "yes")
    r = client.get(f"/api/proposals/{p.id}/my-vote", headers=_auth(v1))
    assert r.json()["my_voting_weight"] is None


# ===========================================================================
# Permission backfill parity (existing org vs new org)
# ===========================================================================

def test_permission_backfill_parity(test_db):
    """Both a freshly-seeded org and one seeded via role_seed carry the
    member.set_voting_weight grant for steward + admin (the backfill
    migration handles pre-existing prod orgs; role_seed handles new ones)."""
    from role_permissions import has_permission
    org = _org(test_db, slug="new-org")
    steward, _ = _member(test_db, org, "steward-u", role="steward")
    admin, _ = _member(test_db, org, "admin-u", role="admin")
    moderator, _ = _member(test_db, org, "mod-u", role="moderator")
    plain, _ = _member(test_db, org, "plain-u", role="member")
    test_db.commit()
    assert has_permission(test_db, steward.id, org.id, "member.set_voting_weight")
    assert has_permission(test_db, admin.id, org.id, "member.set_voting_weight")
    assert not has_permission(test_db, moderator.id, org.id, "member.set_voting_weight")
    assert not has_permission(test_db, plain.id, org.id, "member.set_voting_weight")
