"""Phase 90c — Per-proposal count_mode, weighted-UI sweep 4xx battery, register export.

Verification matrix (spec: phase90c_90e_corporate_completion_spec.md §1.4):
  * count_mode headcount-equivalence, one test per method: in a weighted org with
    UNEQUAL stored weights, a `one_per_member` proposal tallies byte-identical to
    the same votes cast in an unweighted org — binary, approval, RCV, both budget
    modes, cosign, election close, and a VoteSnapshot. The mechanism is the 88
    parity path reused as a feature: `_build_context` skips `ctx.user_weights`,
    so every downstream surface reduces to headcount with zero tally-code changes.
  * Draft-lock: count_mode editable in draft; changing it after draft → 400.
  * Org toggle off (`allow_per_member_proposals=False`) → one_per_member create 400.
  * Unweighted org → the column is ignored (stored NULL) even if supplied.
  * Weighted-only endpoint 4xx battery: weight PATCH, share-events, rules CRUD,
    transfer, register export all reject in an unweighted org.
  * Register export: CSV two-section shape, audited access row, permission-gate
    negative, weighted-only 400.
"""
from __future__ import annotations

import csv
import io
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
ON = {"enabled": True, "unit_label": "shares"}


# ===========================================================================
# Fixtures + helpers
# ===========================================================================

@pytest.fixture(scope="function")
def test_db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
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


def _auth(u):
    return {"Authorization": f"Bearer {auth_utils.create_access_token(u.id)}"}


def _user(db, n, *, is_admin=False):
    u = models.User(username=n, display_name=n, password_hash=_DUMMY_HASH,
                    email=f"{n}@t.ex", email_verified=True, is_admin=is_admin)
    db.add(u); db.flush(); return u


def _org(db, slug, *, weighted=None):
    s = {"default_voting_days": 7,
         "allowed_voting_methods": ["binary", "approval", "ranked_choice",
                                    "budget_allocation", "budget_project"]}
    if weighted is not None:
        s["weighted_voting"] = weighted
    o = models.Organization(name=slug.title(), slug=slug, description="", settings=s)
    db.add(o); db.flush(); seed_default_roles_for_org(db, o.id); return o


def _member(db, org, n, *, role="member", weight=1):
    u = _user(db, n)
    m = make_org_membership(db, org_id=org.id, user_id=u.id, role=role)
    m.voting_weight = weight
    db.flush()
    return u, m


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _binary(db, author, org, *, count_mode=None, quorum=0.0):
    p = models.Proposal(
        title="P", body="", author_id=author.id, org_id=org.id,
        voting_method="binary", num_winners=1, status="voting",
        count_mode=count_mode, voting_start=_now(),
        voting_end=_now() + timedelta(days=7), quorum_threshold=quorum,
        pass_threshold=0.5)
    db.add(p); db.flush(); return p


def _approval(db, author, org, labels=("A", "B"), *, count_mode=None,
              is_election=False, quorum=0.0):
    p = models.Proposal(
        title="AP", body="", author_id=author.id, org_id=org.id,
        voting_method="approval", num_winners=1, status="voting",
        count_mode=count_mode, is_election=is_election, voting_start=_now(),
        voting_end=_now() + timedelta(days=7), quorum_threshold=quorum,
        pass_threshold=0.5)
    db.add(p); db.flush()
    opts = []
    for i, lab in enumerate(labels):
        o = models.ProposalOption(proposal_id=p.id, label=lab, description="",
                                  display_order=i)
        db.add(o); opts.append(o)
    db.flush(); return p, opts


def _rcv(db, author, org, labels=("A", "B", "C"), *, count_mode=None):
    p = models.Proposal(
        title="RCV", body="", author_id=author.id, org_id=org.id,
        voting_method="ranked_choice", num_winners=1, status="voting",
        count_mode=count_mode, voting_start=_now(),
        voting_end=_now() + timedelta(days=7), quorum_threshold=0.0,
        pass_threshold=0.5)
    db.add(p); db.flush()
    opts = []
    for i, lab in enumerate(labels):
        o = models.ProposalOption(proposal_id=p.id, label=lab, description="",
                                  display_order=i)
        db.add(o); opts.append(o)
    db.flush(); return p, opts


def _alloc(db, author, org, labels=("A", "B"), *, count_mode=None):
    p = models.Proposal(
        title="AL", body="", author_id=author.id, org_id=org.id,
        voting_method="budget_allocation", num_winners=1, status="voting",
        count_mode=count_mode, voting_start=_now(),
        voting_end=_now() + timedelta(days=7), quorum_threshold=0.0,
        pass_threshold=0.5,
        budget_config={"mode": "allocation", "envelope": 100000,
                       "currency": "USD", "aggregation": "median"})
    db.add(p); db.flush()
    opts = []
    for i, lab in enumerate(labels):
        o = models.ProposalOption(proposal_id=p.id, label=lab, description="",
                                  display_order=i)
        db.add(o); opts.append(o)
    db.flush(); return p, opts


def _project(db, author, org, *, count_mode=None):
    p = models.Proposal(
        title="PR", body="", author_id=author.id, org_id=org.id,
        voting_method="budget_project", num_winners=1, status="voting",
        count_mode=count_mode, voting_start=_now(),
        voting_end=_now() + timedelta(days=7), quorum_threshold=0.0,
        pass_threshold=0.5,
        budget_config={"mode": "project", "envelope": 60000, "min_spend": 0,
                       "currency": "USD"})
    db.add(p); db.flush()
    opts = []
    for i, (lab, floor) in enumerate([("A", 50000), ("B", 50000)]):
        o = models.ProposalOption(proposal_id=p.id, label=lab, description="",
                                  display_order=i, budget_floor_amount=floor)
        db.add(o); opts.append(o)
    db.flush(); return p, opts


# ===========================================================================
# §1.4 — per-method headcount-equivalence. A weighted org with UNEQUAL weights
# + a one_per_member proposal must produce the SAME tally as the identical
# votes cast in an unweighted org (byte-identical on the salient fields).
# ===========================================================================

def test_binary_one_per_member_equals_headcount(client, test_db):
    org = _org(test_db, "w-bin", weighted=ON)
    author, _ = _member(test_db, org, "a", role="steward", weight=1)
    (v1, _) = _member(test_db, org, "v1", weight=9)
    (v2, _) = _member(test_db, org, "v2", weight=4)
    (v3, _) = _member(test_db, org, "v3", weight=7)
    p = _binary(test_db, author, org, count_mode="one_per_member")
    test_db.commit()
    client.post(f"/api/proposals/{p.id}/vote", headers=_auth(v1), json={"vote_value": "yes"})
    client.post(f"/api/proposals/{p.id}/vote", headers=_auth(v2), json={"vote_value": "yes"})
    client.post(f"/api/proposals/{p.id}/vote", headers=_auth(v3), json={"vote_value": "no"})
    t = delegation_engine.engine.compute_tally(p, test_db)
    # Headcount, not 9+4=13 vs 7.
    assert (t.yes, t.no, t.not_cast, t.total_eligible) == (2, 1, 1, 4)


def test_approval_one_per_member_equals_headcount(client, test_db):
    org = _org(test_db, "w-app", weighted=ON)
    author, _ = _member(test_db, org, "a", role="steward", weight=1)
    (v1, _) = _member(test_db, org, "v1", weight=7)
    (v2, _) = _member(test_db, org, "v2", weight=3)
    p, opts = _approval(test_db, author, org, count_mode="one_per_member")
    a, b = opts[0].id, opts[1].id
    test_db.commit()
    client.post(f"/api/proposals/{p.id}/vote", headers=_auth(v1), json={"approvals": [a]})
    client.post(f"/api/proposals/{p.id}/vote", headers=_auth(v2), json={"approvals": [b]})
    t = delegation_engine.engine.compute_tally(p, test_db)
    assert t.option_approvals[a] == 1  # headcount, not 7 shares
    assert t.option_approvals[b] == 1
    assert t.total_ballots_cast == 2


def test_rcv_one_per_member_equals_headcount(client, test_db):
    """A heavy voter cannot dominate an RCV round when one_per_member: two light
    voters for B out-count one heavy voter for A."""
    org = _org(test_db, "w-rcv", weighted=ON)
    author, _ = _member(test_db, org, "a", role="steward", weight=1)
    (v1, _) = _member(test_db, org, "v1", weight=20)  # heavy, ranks A
    (v2, _) = _member(test_db, org, "v2", weight=1)
    (v3, _) = _member(test_db, org, "v3", weight=1)
    p, opts = _rcv(test_db, author, org, count_mode="one_per_member")
    a, b, c = opts[0].id, opts[1].id, opts[2].id
    test_db.commit()
    client.post(f"/api/proposals/{p.id}/vote", headers=_auth(v1), json={"ranking": [a, b, c]})
    client.post(f"/api/proposals/{p.id}/vote", headers=_auth(v2), json={"ranking": [b, c, a]})
    client.post(f"/api/proposals/{p.id}/vote", headers=_auth(v3), json={"ranking": [b, c, a]})
    t = delegation_engine.engine.compute_tally(p, test_db)
    # Headcount: B has 2 first-choices vs A's 1 → B wins. Weighted would seat A.
    assert t.winners == [b]


def test_alloc_one_per_member_equals_headcount(client, test_db):
    org = _org(test_db, "w-al", weighted=ON)
    author, _ = _member(test_db, org, "a", role="steward", weight=1)
    (v1, _) = _member(test_db, org, "v1", weight=70)
    (v2, _) = _member(test_db, org, "v2", weight=30)
    p, opts = _alloc(test_db, author, org, count_mode="one_per_member")
    a, b = opts[0].id, opts[1].id
    test_db.commit()
    client.post(f"/api/proposals/{p.id}/vote", headers=_auth(v1),
                json={"allocations": {a: 100000, b: 0}})
    client.post(f"/api/proposals/{p.id}/vote", headers=_auth(v2),
                json={"allocations": {a: 0, b: 100000}})
    t = delegation_engine.engine.compute_tally(p, test_db)
    # Equal-weight median of {0, 100000} = 50000 per bucket (heavy voter does
    # NOT pin the median). total_ballots_cast is headcount.
    assert t.total_ballots_cast == 2
    assert t.amounts[a] == 50000
    assert t.amounts[b] == 50000


def test_project_one_per_member_equals_headcount(client, test_db):
    """Two light voters fund B out-rank one heavy voter for A when headcount."""
    org = _org(test_db, "w-pr", weighted=ON)
    author, _ = _member(test_db, org, "a", role="steward", weight=1)
    (v1, _) = _member(test_db, org, "v1", weight=50)  # heavy, ranks A first
    (v2, _) = _member(test_db, org, "v2", weight=1)
    (v3, _) = _member(test_db, org, "v3", weight=1)
    p, opts = _project(test_db, author, org, count_mode="one_per_member")
    a, b = opts[0].id, opts[1].id
    test_db.commit()
    client.post(f"/api/proposals/{p.id}/vote", headers=_auth(v1),
                json={"ranked": [{"option_id": a}, {"option_id": b}]})
    client.post(f"/api/proposals/{p.id}/vote", headers=_auth(v2),
                json={"ranked": [{"option_id": b}, {"option_id": a}]})
    client.post(f"/api/proposals/{p.id}/vote", headers=_auth(v3),
                json={"ranked": [{"option_id": b}, {"option_id": a}]})
    t = delegation_engine.engine.compute_tally(p, test_db)
    # Envelope 60000 funds one 50000 item; headcount favors B (2 vs 1).
    assert [f["option_id"] for f in t.funded] == [b]


def test_cosign_one_per_member_equals_headcount(client, test_db):
    from cosign import resolve_cosign_weight_for_signers
    org = _org(test_db, "w-co", weighted=ON)
    author, _ = _member(test_db, org, "a", role="steward", weight=1)
    (s1, _) = _member(test_db, org, "s1", weight=6)
    (s2, _) = _member(test_db, org, "s2", weight=2)
    p = _binary(test_db, author, org, count_mode="one_per_member")
    test_db.commit()
    # one_per_member proposal → cosign weight is headcount 2, not 8 shares.
    assert resolve_cosign_weight_for_signers(test_db, p, {s1.id, s2.id}) == 2


def test_election_one_per_member_equals_headcount(client, test_db):
    from elections import election_close_status
    org = _org(test_db, "w-el", weighted=ON)
    author, _ = _member(test_db, org, "a", role="steward", weight=1)
    (v1, _) = _member(test_db, org, "v1", weight=1)   # light, votes A
    (v2, _) = _member(test_db, org, "v2", weight=1)   # light, votes A
    (v3, _) = _member(test_db, org, "v3", weight=20)  # heavy, votes B
    p, opts = _approval(test_db, author, org, count_mode="one_per_member",
                        is_election=True, quorum=0.0)
    a, b = opts[0].id, opts[1].id
    test_db.commit()
    client.post(f"/api/proposals/{p.id}/vote", headers=_auth(v1), json={"approvals": [a]})
    client.post(f"/api/proposals/{p.id}/vote", headers=_auth(v2), json={"approvals": [a]})
    client.post(f"/api/proposals/{p.id}/vote", headers=_auth(v3), json={"approvals": [b]})
    t = delegation_engine.engine.compute_tally(p, test_db)
    # Headcount: A has 2 approvals vs B's 1 → A seats. Weighted would seat B (20).
    assert election_close_status(p, t) == "passed"
    assert t.winners == [a]


def test_snapshot_one_per_member_equals_headcount(client, test_db):
    """A VoteSnapshot recorded on a one_per_member proposal stores headcount
    counts, not share-denominated ones."""
    from sustained_majority_service import capture_snapshot
    org = _org(test_db, "w-sn", weighted=ON)
    author, _ = _member(test_db, org, "a", role="steward", weight=1)
    (v1, _) = _member(test_db, org, "v1", weight=9)
    (v2, _) = _member(test_db, org, "v2", weight=4)
    p = _binary(test_db, author, org, count_mode="one_per_member")
    test_db.commit()
    client.post(f"/api/proposals/{p.id}/vote", headers=_auth(v1), json={"vote_value": "yes"})
    client.post(f"/api/proposals/{p.id}/vote", headers=_auth(v2), json={"vote_value": "no"})
    snap = capture_snapshot(test_db, p)
    assert snap.yes_count == 1  # headcount, not 9
    assert snap.no_count == 1


# ===========================================================================
# §1.1 — count_mode column semantics: draft-lock, org toggle, unweighted ignore
# ===========================================================================

def _create_org_proposal(client, org, author, **body):
    payload = {"title": "T", "body": "b", "voting_method": "binary"}
    payload.update(body)
    return client.post(f"/api/orgs/{org.slug}/proposals", headers=_auth(author),
                       json=payload)


def test_count_mode_stored_on_weighted_create(client, test_db):
    org = _org(test_db, "cw", weighted=ON)
    author, _ = _member(test_db, org, "a", role="steward")
    test_db.commit()
    r = _create_org_proposal(client, org, author, count_mode="one_per_member")
    assert r.status_code in (200, 201), r.text
    assert r.json()["count_mode"] == "one_per_member"


def test_count_mode_invalid_value_400(client, test_db):
    org = _org(test_db, "civ", weighted=ON)
    author, _ = _member(test_db, org, "a", role="steward")
    test_db.commit()
    r = _create_org_proposal(client, org, author, count_mode="bogus")
    assert r.status_code == 400, r.text


def test_count_mode_ignored_in_unweighted_org(client, test_db):
    org = _org(test_db, "unw")  # no weighted section
    author, _ = _member(test_db, org, "a", role="steward")
    test_db.commit()
    r = _create_org_proposal(client, org, author, count_mode="one_per_member")
    assert r.status_code in (200, 201), r.text
    # Ignored → stored NULL, surfaced as None.
    assert r.json()["count_mode"] is None


def test_org_toggle_off_rejects_one_per_member(client, test_db):
    org = _org(test_db, "off",
               weighted={"enabled": True, "unit_label": "shares",
                         "allow_per_member_proposals": False})
    author, _ = _member(test_db, org, "a", role="steward")
    test_db.commit()
    r = _create_org_proposal(client, org, author, count_mode="one_per_member")
    assert r.status_code == 400, r.text
    # But an explicit 'weighted' (the org default) is fine.
    r2 = _create_org_proposal(client, org, author, count_mode="weighted")
    assert r2.status_code in (200, 201), r2.text


def test_count_mode_draft_lock(client, test_db):
    org = _org(test_db, "lock", weighted=ON)
    author, _ = _member(test_db, org, "a", role="steward")
    test_db.commit()
    # Create as draft (deliberation_days>0 keeps it in draft).
    r = _create_org_proposal(client, org, author, count_mode="one_per_member",
                             deliberation_days=1)
    assert r.status_code in (200, 201), r.text
    pid = r.json()["id"]
    # Editable while draft.
    r2 = client.patch(f"/api/proposals/{pid}", headers=_auth(author),
                      json={"count_mode": "weighted"})
    assert r2.status_code == 200, r2.text
    assert r2.json()["count_mode"] == "weighted"
    # Move to deliberation (still editable for OTHER fields), then a count_mode
    # CHANGE is rejected because it's draft-only.
    p = test_db.get(models.Proposal, pid)
    p.status = "deliberation"
    p.deliberation_start = _now()
    test_db.commit()
    r3 = client.patch(f"/api/proposals/{pid}", headers=_auth(author),
                      json={"count_mode": "one_per_member"})
    assert r3.status_code == 400, r3.text
    assert "count_mode" in r3.json()["detail"]
    # Re-submitting the SAME value out of draft is a no-op (no change → no 400).
    r4 = client.patch(f"/api/proposals/{pid}", headers=_auth(author),
                      json={"count_mode": "weighted"})
    assert r4.status_code == 200, r4.text


def test_results_weighted_flag_false_for_one_per_member(client, test_db):
    org = _org(test_db, "rf", weighted=ON)
    author, _ = _member(test_db, org, "a", role="steward", weight=1)
    (v1, _) = _member(test_db, org, "v1", weight=5)
    p = _binary(test_db, author, org, count_mode="one_per_member")
    test_db.commit()
    client.post(f"/api/proposals/{p.id}/vote", headers=_auth(v1), json={"vote_value": "yes"})
    r = client.get(f"/api/proposals/{p.id}/results", headers=_auth(author))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["weighted"] is False
    assert body["unit_label"] is None


# ===========================================================================
# §1.2 — weighted-only endpoint 4xx battery in an unweighted org
# ===========================================================================

def test_weighted_endpoints_reject_in_unweighted_org(client, test_db):
    org = _org(test_db, "plain")  # weighted off
    admin, _ = _member(test_db, org, "adm", role="steward")
    (m1, mem1) = _member(test_db, org, "m1")
    test_db.commit()
    h = _auth(admin)
    # Weight PATCH
    r = client.patch(f"/api/orgs/{org.slug}/members/{m1.id}/voting-weight",
                     headers=h, json={"voting_weight": 5})
    assert r.status_code >= 400, r.text
    # Share-events feed
    assert client.get(f"/api/orgs/{org.slug}/share-events", headers=h).status_code >= 400
    # Rule create
    rc = client.post(f"/api/orgs/{org.slug}/share-distribution-rules", headers=h,
                     json={"name": "r", "amount_per_period": 1, "period": "monthly",
                           "target": {"kind": "all"}})
    assert rc.status_code >= 400
    # Transfer
    rt = client.post(f"/api/orgs/{org.slug}/shares/transfer", headers=h,
                     json={"recipient_user_id": m1.id, "amount": 1})
    assert rt.status_code >= 400
    # Register export
    assert client.get(f"/api/orgs/{org.slug}/share-register/export",
                      headers=h).status_code >= 400


# ===========================================================================
# §1.3 — register + ledger export
# ===========================================================================

def test_register_export_shape_and_audit(client, test_db):
    org = _org(test_db, "exp", weighted=ON)
    admin, _ = _member(test_db, org, "adm", role="steward", weight=1)
    (m1, mem1) = _member(test_db, org, "alice", weight=5)
    (m2, mem2) = _member(test_db, org, "bob", weight=3)
    # A couple of ledger rows: an admin weight-set + a transfer.
    ev = models.ShareEvent(org_id=org.id, event_type="admin_set", user_id=m1.id,
                           delta=5, resulting_balance=5, actor_id=admin.id)
    test_db.add(ev)
    test_db.commit()

    r = client.get(f"/api/orgs/{org.slug}/share-register/export", headers=_auth(admin))
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("text/csv")
    assert "attachment" in r.headers.get("content-disposition", "")

    rows = list(csv.reader(io.StringIO(r.text)))
    # Section markers present.
    flat = [c for row in rows for c in row]
    assert "# REGISTER" in flat
    assert "# LEDGER" in flat
    # Register header + one row per member (3 members).
    reg_hdr = rows.index(["# REGISTER"]) + 1
    assert rows[reg_hdr] == ["display_name", "user_id", "voting_weight",
                             "share_start_date", "joined_at"]
    ledger_marker = rows.index(["# LEDGER"])
    reg_rows = rows[reg_hdr + 1:ledger_marker - 1]  # trailing blank line before LEDGER
    reg_rows = [r0 for r0 in reg_rows if r0]
    weights = {r0[0]: r0[2] for r0 in reg_rows}
    assert weights["alice"] == "5"
    assert weights["bob"] == "3"
    # Ledger has the admin_set row.
    ledger_body = [r0 for r0 in rows[ledger_marker + 2:] if r0]
    assert any(r0[2] == "admin_set" and r0[3] == "5" for r0 in ledger_body)

    # Audited elevated access naming the exporter.
    audit = test_db.query(models.AuditLog).filter(
        models.AuditLog.action == "share.register_exported").all()
    assert len(audit) == 1
    assert audit[0].actor_id == admin.id


def test_register_export_permission_gate(client, test_db):
    org = _org(test_db, "expg", weighted=ON)
    admin, _ = _member(test_db, org, "adm", role="steward", weight=1)
    (plain, _) = _member(test_db, org, "plain", weight=1)  # no set_voting_weight
    test_db.commit()
    r = client.get(f"/api/orgs/{org.slug}/share-register/export", headers=_auth(plain))
    assert r.status_code == 403, r.text
