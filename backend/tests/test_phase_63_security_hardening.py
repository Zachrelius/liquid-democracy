"""Phase 63 — security-hardening regression tests.

Covers the six just-implemented changes:

  1. Vote-graph eligibility gate (routes/proposals.py::get_vote_graph):
     non-eligible authenticated users get 404; eligible members and
     platform admins still get 200.
  2. Vote-graph opaque node ids: identity-redacted nodes carry a
     per-request ``anon_`` id (never the real user_id); visible nodes
     (self, public delegates) keep their real id; edges stay mapping-
     consistent with the node list; anon ids are unlinkable across
     requests (per-request salt).
  3. Elections candidacy org binding (routes/elections.py::
     _proposal_or_404 now takes org_id): cross-org candidacy
     POST/GET/DELETE return 404; same-org flow unchanged.
  4. Email HTML escaping (email_service._prepare_org_email) +
     strict-hex primary-color validation
     (email_service._resolve_org_primary_color).
  5. voting_end deadline enforcement (routes/votes.py::
     _require_voting_open): status='voting' with a past voting_end
     rejects new votes with 400.
  6. Refresh-token reuse detection (routes/auth.py::refresh_token):
     presenting an already-revoked token returns 401, revokes the
     user's whole active token family, and emits an
     'auth.refresh_token_reuse_detected' audit row.

Plus source-level assertions that the new slowapi decorators are
present on /api/auth/register (10/hour) and /api/demo/trigger-reset
(6/hour) — the limiter key_func bypasses counting under test settings
(rate_limit_utils.bypass_or_remote_address with settings.debug), so
exercising a real 429 in-process is impractical; asserting the
decorator line is the pragmatic, explicit alternative.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import StaticPool

import auth as auth_utils
import email_service
import models
from database import Base, get_db
from main import app
from tests.conftest import make_user, make_org_membership


_BACKEND_DIR = Path(__file__).resolve().parents[1]


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


# ---------------------------------------------------------------------------
# Fixtures (mirrors test_vote_graph_privacy.py / test_auth_tokens.py)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="function")
def test_db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False)
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)


@pytest.fixture(scope="function")
def client(test_db):
    def override_get_db():
        try:
            yield test_db
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app)
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _auth(user: models.User) -> dict:
    return {"Authorization": f"Bearer {auth_utils.create_access_token(user.id)}"}


def _make_org(db: Session, slug: str, settings: dict | None = None) -> models.Organization:
    org = models.Organization(
        name=slug.title(),
        slug=slug,
        description="",
        join_policy="open",
        settings=settings or {},
    )
    db.add(org)
    db.flush()
    return org


def _make_topic(db: Session, org: models.Organization, name: str) -> models.Topic:
    t = models.Topic(name=name, color="#abcabc", org_id=org.id)
    db.add(t)
    db.flush()
    return t


def _make_voting_proposal(
    db: Session,
    author: models.User,
    org: models.Organization,
    *,
    topic: models.Topic | None = None,
    voting_end: datetime | None = None,
) -> models.Proposal:
    p = models.Proposal(
        title="P63 Proposal",
        body="",
        author_id=author.id,
        status="voting",
        voting_method="binary",
        org_id=org.id,
        voting_end=voting_end,
    )
    db.add(p)
    db.flush()
    if topic is not None:
        db.add(models.ProposalTopic(proposal_id=p.id, topic_id=topic.id))
        db.flush()
    return p


def _cast_binary(db: Session, user: models.User, proposal: models.Proposal, value: str) -> models.Vote:
    v = models.Vote(
        proposal_id=proposal.id,
        user_id=user.id,
        vote_value=value,
        is_direct=True,
        cast_by_id=user.id,
    )
    db.add(v)
    db.flush()
    return v


# ===========================================================================
# 1 — Vote-graph eligibility gate
# ===========================================================================

class TestVoteGraphEligibilityGate:
    def _setup(self, db: Session):
        org_a = _make_org(db, "p63-graph-a")
        org_b = _make_org(db, "p63-graph-b")
        author = make_user(db, "p63-graph-author")
        member = make_user(db, "p63-graph-member")
        outsider = make_user(db, "p63-graph-outsider")
        make_org_membership(db, org_id=org_a.id, user_id=author.id, role="member")
        make_org_membership(db, org_id=org_a.id, user_id=member.id, role="member")
        # The outsider is authenticated and a member of a DIFFERENT org.
        make_org_membership(db, org_id=org_b.id, user_id=outsider.id, role="member")
        p = _make_voting_proposal(db, author, org_a)
        db.commit()
        return p, member, outsider

    def test_non_eligible_authenticated_user_gets_404(self, client, test_db):
        """Phase 63: pre-fix any logged-in user could pull the per-voter
        ballot list of any org's proposal. Now a member of a different
        org gets 404 (not 403 — don't confirm the proposal exists)."""
        p, _member, outsider = self._setup(test_db)
        resp = client.get(f"/api/proposals/{p.id}/vote-graph", headers=_auth(outsider))
        assert resp.status_code == 404, resp.text

    def test_eligible_org_member_still_gets_200(self, client, test_db):
        p, member, _outsider = self._setup(test_db)
        resp = client.get(f"/api/proposals/{p.id}/vote-graph", headers=_auth(member))
        assert resp.status_code == 200, resp.text

    def test_platform_admin_still_gets_200(self, client, test_db):
        p, _member, _outsider = self._setup(test_db)
        admin = make_user(test_db, "p63-graph-platadmin")
        admin.is_admin = True
        test_db.commit()
        resp = client.get(f"/api/proposals/{p.id}/vote-graph", headers=_auth(admin))
        assert resp.status_code == 200, resp.text


# ===========================================================================
# 2 — Vote-graph opaque node ids
# ===========================================================================

class TestVoteGraphOpaqueNodeIds:
    def _setup(self, db: Session):
        """Org with: viewer (member, no votes), a public delegate who
        votes directly, and a redacted stranger who delegates to the
        public delegate (so a visible edge exists with a redacted
        source)."""
        org = _make_org(db, "p63-anon")
        topic = _make_topic(db, org, "P63 Anon Topic")
        viewer = make_user(db, "p63-anon-viewer")
        delegate = make_user(db, "p63-anon-delegate", "Public Delegate")
        stranger = make_user(db, "p63-anon-stranger", "Secret Stranger")
        for u in (viewer, delegate, stranger):
            make_org_membership(db, org_id=org.id, user_id=u.id, role="member")
        # Public delegate profile on the proposal's topic — identity visible
        # to every viewer per the existing privacy semantics.
        db.add(models.DelegateProfile(
            user_id=delegate.id,
            topic_id=topic.id,
            org_id=org.id,
            bio="",
            visibility="public_accepting",
        ))
        p = _make_voting_proposal(db, viewer, org, topic=topic)
        # Stranger delegates to the public delegate on the topic; the
        # delegate votes directly, so the stranger's vote resolves via
        # delegation and produces a visible edge (target is public).
        db.add(models.Delegation(
            delegator_id=stranger.id,
            delegate_id=delegate.id,
            org_id=org.id,
            topic_id=topic.id,
            chain_behavior="accept_sub",
        ))
        _cast_binary(db, delegate, p, "yes")
        db.commit()
        return p, viewer, delegate, stranger

    def test_redacted_nodes_get_anon_ids_visible_nodes_keep_real_ids(self, client, test_db):
        p, viewer, delegate, stranger = self._setup(test_db)
        resp = client.get(f"/api/proposals/{p.id}/vote-graph", headers=_auth(viewer))
        assert resp.status_code == 200, resp.text
        nodes = resp.json()["nodes"]
        ids = {n["id"] for n in nodes}

        # Visible identities keep their real user_id.
        assert viewer.id in ids, "self node must keep its real id"
        assert delegate.id in ids, "public-delegate node must keep its real id"

        # The redacted stranger's real id must NOT appear anywhere.
        assert stranger.id not in ids, (
            "redacted voter's real user_id leaked into the graph — it is a "
            "stable join key against the members endpoint"
        )
        anon_nodes = [n for n in nodes if n["label"] == "" and not n["is_current_user"]]
        assert len(anon_nodes) == 1
        anon = anon_nodes[0]
        assert anon["id"].startswith("anon_"), anon["id"]
        real_ids = {viewer.id, delegate.id, stranger.id}
        assert anon["id"] not in real_ids

    def test_edges_reference_existing_node_ids(self, client, test_db):
        """Mapping consistency: every edge endpoint must resolve to a
        node id in the same response — including anon_ ids."""
        p, viewer, delegate, stranger = self._setup(test_db)
        resp = client.get(f"/api/proposals/{p.id}/vote-graph", headers=_auth(viewer))
        assert resp.status_code == 200, resp.text
        data = resp.json()
        node_ids = {n["id"] for n in data["nodes"]}
        edges = data["edges"]
        # The stranger→public-delegate edge is visible to all viewers.
        assert len(edges) >= 1
        for e in edges:
            assert e["source"] in node_ids, f"edge source {e['source']!r} not in nodes"
            assert e["target"] in node_ids, f"edge target {e['target']!r} not in nodes"
        # The redacted delegator's edge uses the opaque id, not the real one.
        anon_sources = [e for e in edges if e["source"].startswith("anon_")]
        assert len(anon_sources) == 1
        assert anon_sources[0]["target"] == delegate.id
        assert all(e["source"] != stranger.id for e in edges)

    def test_anon_ids_unlinkable_across_requests(self, client, test_db):
        """Per-request salt: the same redacted voter gets a DIFFERENT
        anon id on every request, so responses can't be joined."""
        p, viewer, _delegate, _stranger = self._setup(test_db)

        def _anon_ids() -> set[str]:
            resp = client.get(f"/api/proposals/{p.id}/vote-graph", headers=_auth(viewer))
            assert resp.status_code == 200, resp.text
            return {n["id"] for n in resp.json()["nodes"] if n["id"].startswith("anon_")}

        first = _anon_ids()
        second = _anon_ids()
        assert first and second
        assert first.isdisjoint(second), (
            f"anon ids reused across requests: {first & second}"
        )


# ===========================================================================
# 3 — Elections candidacy org binding
# ===========================================================================

def _make_election_org(db: Session, slug: str) -> tuple[models.Organization, models.OrgTitle]:
    """Mirror of test_phase_48_stage1_elections._make_org +
    _set_steward_title_electable."""
    org = models.Organization(
        name=slug.title(),
        slug=slug,
        description="",
        join_policy="open",
        settings={
            "default_deliberation_days": 3,
            "default_voting_days": 7,
            "default_pass_threshold": 0.50,
            "default_quorum_threshold": 0.0,
            "allowed_voting_methods": ["binary"],
            "elections": {"enabled": True},
        },
    )
    db.add(org)
    db.flush()
    from org_titles import seed_system_titles_for_org
    from role_seed import seed_default_roles_for_org
    seed_default_roles_for_org(db, org.id)
    seed_system_titles_for_org(db, org.id)
    steward_title = db.query(models.OrgTitle).filter_by(
        org_id=org.id, name="Steward",
    ).one()
    steward_title.fill_method = "both"
    db.commit()
    return org, steward_title


class TestElectionsCandidacyOrgBinding:
    def _setup(self, db: Session, client: TestClient, slug_prefix: str):
        """Org A (attacker's org) + org B (holds the election).
        Returns (org_a, member_a, org_b, member_b, election_pid)."""
        org_a, _ = _make_election_org(db, f"{slug_prefix}-a")
        org_b, title_b = _make_election_org(db, f"{slug_prefix}-b")
        member_a = make_user(db, f"{slug_prefix}-member-a")
        admin_b = make_user(db, f"{slug_prefix}-admin-b")
        member_b = make_user(db, f"{slug_prefix}-member-b")
        make_org_membership(db, org_id=org_a.id, user_id=member_a.id, role="member")
        make_org_membership(db, org_id=org_b.id, user_id=admin_b.id, role="admin")
        make_org_membership(db, org_id=org_b.id, user_id=member_b.id, role="member")
        db.commit()
        r = client.post(
            f"/api/orgs/{org_b.slug}/elections",
            headers=_auth(admin_b),
            json={"title_id": title_b.id},
        )
        assert r.status_code == 201, r.text
        return org_a, member_a, org_b, member_b, r.json()["id"]

    def test_cross_org_candidacy_post_get_delete_all_404(self, client, test_db):
        """Phase 63: a member of org A acting through org A's slug on
        org B's election proposal gets 404 (not 403 — don't confirm the
        proposal exists) for declare, list, and withdraw."""
        org_a, member_a, _org_b, _member_b, pid = self._setup(
            test_db, client, "p63xorg",
        )
        r_post = client.post(
            f"/api/orgs/{org_a.slug}/elections/{pid}/candidacies",
            headers=_auth(member_a),
        )
        assert r_post.status_code == 404, r_post.text

        r_get = client.get(
            f"/api/orgs/{org_a.slug}/elections/{pid}/candidacies",
            headers=_auth(member_a),
        )
        assert r_get.status_code == 404, r_get.text

        r_del = client.request(
            "DELETE",
            f"/api/orgs/{org_a.slug}/elections/{pid}/candidacies",
            headers=_auth(member_a),
        )
        assert r_del.status_code == 404, r_del.text

    def test_same_org_candidacy_flow_still_works(self, client, test_db):
        """The legitimate same-org flow is unchanged: declare 201, the
        roster lists the candidate, withdraw 204."""
        _org_a, _member_a, org_b, member_b, pid = self._setup(
            test_db, client, "p63legit",
        )
        r_post = client.post(
            f"/api/orgs/{org_b.slug}/elections/{pid}/candidacies",
            headers=_auth(member_b),
        )
        assert r_post.status_code == 201, r_post.text

        r_get = client.get(
            f"/api/orgs/{org_b.slug}/elections/{pid}/candidacies",
            headers=_auth(member_b),
        )
        assert r_get.status_code == 200, r_get.text
        assert any(c["user_id"] == member_b.id for c in r_get.json())

        r_del = client.request(
            "DELETE",
            f"/api/orgs/{org_b.slug}/elections/{pid}/candidacies",
            headers=_auth(member_b),
        )
        assert r_del.status_code == 204, r_del.text


# ===========================================================================
# 4 — Email HTML escaping + primary-color validation
# ===========================================================================

class TestEmailHtmlEscaping:
    def test_prepare_org_email_escapes_template_vars(self, test_db):
        """A malicious display name must render inert (HTML-escaped) in
        the email body — pre-fix it rendered as live markup from the
        platform's own sending domain (phishing vector)."""
        user = make_user(test_db, "p63-email-recipient")
        test_db.commit()
        evil = '<a href="https://evil.example">click</a>'
        prepared = email_service._prepare_org_email(
            test_db,
            user.id,
            None,
            "comment.posted_on_your_proposal",
            {
                "actor_display_name": evil,
                "proposal_title": "Safe Title",
                "body_excerpt": "hello",
                "cta_url": "https://app.test/proposal/1",
                "prefs_url": "https://app.test/prefs",
                "unsubscribe_url": "https://app.test/unsub",
            },
        )
        assert prepared is not None
        _recipient, _subject, html_body = prepared
        assert '<a href="https://evil.example"' not in html_body, (
            "raw attacker markup survived into the rendered email body"
        )
        assert "&lt;a href=&quot;https://evil.example&quot;&gt;click&lt;/a&gt;" in html_body
        # And the benign values are still present.
        assert "Safe Title" in html_body

    def test_resolve_org_primary_color_rejects_css_injection(self, test_db):
        """A non-hex value (e.g. a CSS-injection payload that reached
        settings through some non-validated path) falls back to the
        platform default — the color is interpolated into inline CSS
        without escaping."""
        org = _make_org(test_db, "p63-color-evil", settings={
            "branding": {"primary_color": "red; } body { display:none"},
        })
        assert (
            email_service._resolve_org_primary_color(org)
            == email_service.PLATFORM_DEFAULT_PRIMARY_COLOR
        )

    def test_resolve_org_primary_color_accepts_strict_hex(self, test_db):
        org = _make_org(test_db, "p63-color-ok", settings={
            "branding": {"primary_color": "#aabbcc"},
        })
        assert email_service._resolve_org_primary_color(org) == "#aabbcc"


# ===========================================================================
# 5 — voting_end deadline enforcement
# ===========================================================================

class TestVotingEndDeadlineEnforcement:
    def _setup(self, db: Session, slug: str, voting_end: datetime | None):
        org = _make_org(db, slug)
        author = make_user(db, f"{slug}-author")
        voter = make_user(db, f"{slug}-voter")
        make_org_membership(db, org_id=org.id, user_id=author.id, role="member")
        make_org_membership(db, org_id=org.id, user_id=voter.id, role="member")
        p = _make_voting_proposal(db, author, org, voting_end=voting_end)
        db.commit()
        return p, voter

    def test_vote_rejected_when_voting_end_in_past(self, client, test_db):
        """Phase 63: the deadline is now enforced at cast time — pre-fix
        votes were accepted for up to one worker tick (~300s) past the
        official voting_end while status was still 'voting'."""
        p, voter = self._setup(
            test_db, "p63-deadline-past", _now() - timedelta(hours=1),
        )
        resp = client.post(
            f"/api/proposals/{p.id}/vote",
            json={"vote_value": "yes"},
            headers=_auth(voter),
        )
        assert resp.status_code == 400, resp.text
        assert "closed" in resp.json()["detail"].lower()

    def test_vote_accepted_when_voting_end_in_future(self, client, test_db):
        p, voter = self._setup(
            test_db, "p63-deadline-future", _now() + timedelta(hours=1),
        )
        resp = client.post(
            f"/api/proposals/{p.id}/vote",
            json={"vote_value": "yes"},
            headers=_auth(voter),
        )
        assert resp.status_code == 200, resp.text

    def test_vote_accepted_when_voting_end_is_null(self, client, test_db):
        p, voter = self._setup(test_db, "p63-deadline-null", None)
        resp = client.post(
            f"/api/proposals/{p.id}/vote",
            json={"vote_value": "yes"},
            headers=_auth(voter),
        )
        assert resp.status_code == 200, resp.text


# ===========================================================================
# 6 — Refresh-token reuse detection
# ===========================================================================

def _make_refresh_token(
    db: Session, user: models.User, *, token: str, expires_in_days: int = 7,
) -> models.RefreshToken:
    rt = models.RefreshToken(
        user_id=user.id,
        token=token,
        expires_at=_now() + timedelta(days=expires_in_days),
        revoked_at=None,
    )
    db.add(rt)
    db.flush()
    return rt


class TestRefreshTokenReuseDetection:
    def test_reuse_of_rotated_token_revokes_family_and_audits(self, client, test_db):
        """Replay of an already-rotated (revoked) refresh token is the
        stolen-token signal: 401 + the whole active family revoked
        (including the legitimately-issued successor) + audit row."""
        user = make_user(test_db, "p63-reuse-user")
        _make_refresh_token(test_db, user, token="p63-original-token")
        test_db.commit()

        # 1. Legitimate refresh — rotates: original revoked, new issued.
        r1 = client.post(
            "/api/auth/refresh",
            json={"refresh_token": "p63-original-token"},
        )
        assert r1.status_code == 200, r1.text
        new_refresh = r1.json()["refresh_token"]
        assert new_refresh and new_refresh != "p63-original-token"

        # 2. Replay the OLD (now revoked) token → 401, same body as any
        #    invalid token (no detection oracle).
        r2 = client.post(
            "/api/auth/refresh",
            json={"refresh_token": "p63-original-token"},
        )
        assert r2.status_code == 401, r2.text

        # 3. The whole active family is revoked: the NEW token's row is
        #    revoked too.
        test_db.expire_all()
        new_rt = test_db.query(models.RefreshToken).filter(
            models.RefreshToken.token == new_refresh,
        ).first()
        assert new_rt is not None
        assert new_rt.revoked_at is not None, (
            "family revocation missed the rotated successor token"
        )
        active = test_db.query(models.RefreshToken).filter(
            models.RefreshToken.user_id == user.id,
            models.RefreshToken.revoked_at.is_(None),
        ).count()
        assert active == 0

        # 4. Audit row emitted.
        audit = test_db.query(models.AuditLog).filter(
            models.AuditLog.action == "auth.refresh_token_reuse_detected",
            models.AuditLog.target_id == user.id,
        ).first()
        assert audit is not None

        # 5. And the revoked successor now also fails with 401.
        r3 = client.post(
            "/api/auth/refresh",
            json={"refresh_token": new_refresh},
        )
        assert r3.status_code == 401, r3.text


# ===========================================================================
# Rate-limit decorators — source-level presence assertions
# ===========================================================================

class TestRateLimitDecoratorsPresent:
    """The limiter key_func (rate_limit_utils.bypass_or_remote_address)
    returns a unique-per-request key under test settings (settings.debug),
    so the limits never trip in-process. Assert the decorator lines are
    present and attached directly to the route functions instead."""

    def test_register_has_10_per_hour_limit(self):
        src = (_BACKEND_DIR / "routes" / "auth.py").read_text(encoding="utf-8")
        assert '@limiter.limit("10/hour")\nasync def register(' in src, (
            "@limiter.limit(\"10/hour\") is no longer attached directly to "
            "routes/auth.py::register"
        )

    def test_demo_trigger_reset_has_6_per_hour_limit(self):
        src = (_BACKEND_DIR / "routes" / "demo_reset.py").read_text(encoding="utf-8")
        assert '@limiter.limit("6/hour")\ndef trigger_demo_reset_via_token(' in src, (
            "@limiter.limit(\"6/hour\") is no longer attached directly to "
            "routes/demo_reset.py::trigger_demo_reset_via_token"
        )
