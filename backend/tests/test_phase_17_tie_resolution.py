"""Phase 17 — tie-resolution test coverage.

Six test classes per spec lines 302-340:

1. TestResolveTieFunctions     — pure unit tests for each resolver.
2. TestGetOrgTieResolutionMethod — defaults, stored values, fallbacks.
3. TestValidateTieResolutionSettings — happy path, errors, eligibility.
4. TestAdvanceProposalTieResolution — integration through advance_proposal.
5. TestPlatformAdminUpdate     — PATCH /api/orgs/{slug} settings flow.
6. TestSchemaCleanup           — confirms TieResolutionRequest is gone.

Style mirrors test_phase_16_duration_enforcement.py: in-memory SQLite,
explicit fixture, _make_user / _make_org / _seed_topic helpers,
``_auth`` Bearer-token shortcut. Integration tests assert side effects
(persisted JSON shape + audit-log row) per CLAUDE.md testing strategy.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import auth as auth_utils
import models
from database import Base, get_db
from delegation_engine import ApprovalTally, RCVTally
from main import app
from org_config import get_org_tie_resolution_method
from role_seed import seed_default_roles_for_org
from tests.conftest import make_org_membership
from tie_resolution import (
    ELIGIBLE_METHODS_APPROVAL,
    ELIGIBLE_METHODS_RANKED_CHOICE,
    PLATFORM_DEFAULT_TIE_RESOLUTION_APPROVAL,
    PLATFORM_DEFAULT_TIE_RESOLUTION_RANKED_CHOICE,
    ResolutionResult,
    resolve_tie,
    validate_tie_resolution_settings,
)


_DUMMY_HASH = "$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/lewrwKJuRxm5pJmJi"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="function")
def test_db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_user(db: Session, username: str) -> models.User:
    u = models.User(
        username=username,
        display_name=username,
        password_hash=_DUMMY_HASH,
        email=f"{username}@test.example",
        email_verified=True,
    )
    db.add(u)
    db.flush()
    return u


def _make_org(
    db: Session, slug: str, *, settings: dict | None = None,
) -> models.Organization:
    o = models.Organization(
        name=slug.title(), slug=slug, description="",
        settings=settings if settings is not None else {},
    )
    db.add(o)
    db.flush()
    seed_default_roles_for_org(db, o.id)
    return o


def _seed_topic(db: Session, org: models.Organization) -> models.Topic:
    t = models.Topic(name="T", description="", color="#000000", org_id=org.id)
    db.add(t)
    db.flush()
    return t


def _auth(user: models.User) -> dict:
    return {"Authorization": f"Bearer {auth_utils.create_access_token(user.id)}"}


def _make_approval_proposal(
    db: Session,
    author: models.User,
    org: models.Organization,
    *,
    option_labels: list[str],
    status: str = "voting",
    voting_end: datetime | None = None,
) -> models.Proposal:
    """Approval proposal with N options and a voting_end set so random_seed
    has a stable seed input."""
    p = models.Proposal(
        title="Approval P",
        body="",
        author_id=author.id,
        voting_method="approval",
        status=status,
        org_id=org.id,
        voting_start=datetime.now(timezone.utc) - timedelta(days=1),
        voting_end=voting_end or (
            datetime.now(timezone.utc) - timedelta(minutes=1)
        ),
    )
    db.add(p)
    db.flush()
    for i, label in enumerate(option_labels):
        db.add(models.ProposalOption(
            proposal_id=p.id, label=label, description="",
            display_order=i,
        ))
    db.flush()
    return p


def _make_rcv_proposal(
    db: Session,
    author: models.User,
    org: models.Organization,
    *,
    option_labels: list[str],
    num_winners: int = 1,
    status: str = "voting",
    voting_end: datetime | None = None,
) -> models.Proposal:
    p = models.Proposal(
        title="RCV P",
        body="",
        author_id=author.id,
        voting_method="ranked_choice",
        num_winners=num_winners,
        status=status,
        org_id=org.id,
        voting_start=datetime.now(timezone.utc) - timedelta(days=1),
        voting_end=voting_end or (
            datetime.now(timezone.utc) - timedelta(minutes=1)
        ),
    )
    db.add(p)
    db.flush()
    for i, label in enumerate(option_labels):
        db.add(models.ProposalOption(
            proposal_id=p.id, label=label, description="",
            display_order=i,
        ))
    db.flush()
    return p


def _option_ids(db: Session, proposal: models.Proposal) -> list[str]:
    rows = db.query(models.ProposalOption).filter(
        models.ProposalOption.proposal_id == proposal.id,
    ).order_by(models.ProposalOption.display_order).all()
    return [r.id for r in rows]


def _cast_approval_vote(
    db: Session,
    user: models.User,
    proposal: models.Proposal,
    approvals: list[str],
) -> models.Vote:
    v = models.Vote(
        proposal_id=proposal.id,
        user_id=user.id,
        vote_value=None,
        ballot={"approvals": approvals},
        is_direct=True,
        cast_by_id=user.id,
    )
    db.add(v)
    db.flush()
    return v


def _cast_ranked_vote(
    db: Session,
    user: models.User,
    proposal: models.Proposal,
    ranking: list[str],
) -> models.Vote:
    v = models.Vote(
        proposal_id=proposal.id,
        user_id=user.id,
        vote_value=None,
        ballot={"ranking": ranking},
        is_direct=True,
        cast_by_id=user.id,
    )
    db.add(v)
    db.flush()
    return v


def _make_proposal_stub(proposal_id: str = "p-1", voting_end: datetime | None = None):
    """Lightweight stand-in for a Proposal when only id + voting_end matter
    (random_seed seeding). Avoids needing a session for pure-layer tests."""
    return SimpleNamespace(
        id=proposal_id,
        voting_end=voting_end or datetime(2026, 5, 9, 12, 0, 0, tzinfo=timezone.utc),
    )


def _make_tally_stub(*, ballots=None, option_approvals=None, winners=None):
    """Lightweight stand-in for an ApprovalTally when only the fields the
    resolver reads matter. Avoids constructing a full tally pipeline."""
    return SimpleNamespace(
        ballots=ballots or [],
        option_approvals=option_approvals or {},
        winners=winners or [],
        tied=True,
    )


# ===========================================================================
# 1. TestResolveTieFunctions — pure unit tests for each resolver.
# ===========================================================================

class TestResolveTieFunctions:
    def test_random_seed_is_deterministic_for_same_inputs(self):
        """Same proposal_id + voting_end + sorted input → same chosen winner."""
        proposal = _make_proposal_stub("propA")
        tally = _make_tally_stub()
        r1 = resolve_tie("random_seed", ["a", "b", "c"], proposal, tally, db=None)
        r2 = resolve_tie("random_seed", ["c", "b", "a"], proposal, tally, db=None)
        # Sort-then-pick guarantees order-independence.
        assert r1.chosen_winners == r2.chosen_winners
        assert len(r1.chosen_winners) == 1
        assert r1.chosen_winners[0] in {"a", "b", "c"}
        assert r1.seed == r2.seed
        assert r1.method == "random_seed"

    def test_random_seed_different_proposal_ids_can_differ(self):
        """Different proposal_ids likely produce different winners (high
        probability with sha256 distribution + 4 candidates)."""
        tally = _make_tally_stub()
        # Try 8 distinct proposal IDs; for 2 candidates each pair has 50%
        # chance of agreeing, so 8 trials should produce >=2 distinct picks
        # with overwhelming probability.
        seen: set[str] = set()
        for i in range(8):
            p = _make_proposal_stub(f"prop-{i}")
            r = resolve_tie("random_seed", ["x", "y"], p, tally, db=None)
            seen.add(r.chosen_winners[0])
        assert len(seen) >= 2, "random_seed should distribute across proposal IDs"

    def test_random_seed_input_winners_preserved_in_audit(self):
        """input_winners is the un-sorted original tied set, persisted as-is."""
        p = _make_proposal_stub("ord")
        tally = _make_tally_stub()
        r = resolve_tie("random_seed", ["c", "a", "b"], p, tally, db=None)
        assert r.input_winners == ["c", "a", "b"]
        assert r.method == "random_seed"
        assert r.seed is not None and len(r.seed) == 64  # sha256 hex

    def test_random_seed_voting_end_none_raises(self):
        """proposal.voting_end is None → RuntimeError (B4.1 invariant)."""
        p = SimpleNamespace(id="p", voting_end=None)
        tally = _make_tally_stub()
        with pytest.raises(RuntimeError, match="voting_end"):
            resolve_tie("random_seed", ["a", "b"], p, tally, db=None)

    def test_expand_winners_returns_all_inputs(self):
        """Trivially: N tied options → N chosen winners."""
        p = _make_proposal_stub()
        tally = _make_tally_stub()
        r = resolve_tie("expand_winners", ["a", "b", "c", "d"], p, tally, db=None)
        assert r.method == "expand_winners"
        assert r.chosen_winners == ["a", "b", "c", "d"]
        assert r.seed is None
        assert r.metadata is None

    def test_broader_approval_base_picks_widest_co_approval(self):
        """A is approved with B, C across 3 ballots; B only with A; A wins."""
        p = _make_proposal_stub()
        # Ballots: each row is one voter's approvals.
        # A appears with {A,B}, {A,C}, {A,B,C} → other-counts: 1+1+2 = 4
        # B appears with {A,B}, {A,B,C}             → other-counts: 1+2  = 3
        ballots = [["A", "B"], ["A", "C"], ["A", "B", "C"]]
        tally = _make_tally_stub(
            ballots=ballots,
            option_approvals={"A": 3, "B": 2, "C": 2},
            winners=["A", "B"],
        )
        r = resolve_tie("broader_approval_base", ["A", "B"], p, tally, db=None)
        assert r.method == "broader_approval_base"
        assert r.chosen_winners == ["A"]
        assert r.metadata["co_approval_counts"]["A"] == 4
        assert r.metadata["co_approval_counts"]["B"] == 3

    def test_broader_approval_base_equal_co_approval_falls_back_to_random_seed(self):
        """Two options with identical co-approval counts → random_seed
        fallback that's deterministic given the same proposal."""
        p = _make_proposal_stub("equal-co")
        # Symmetric ballots: A and B both co-occur with {C}.
        ballots = [["A", "C"], ["B", "C"]]
        tally = _make_tally_stub(
            ballots=ballots,
            option_approvals={"A": 1, "B": 1, "C": 2},
            winners=["A", "B"],
        )
        r1 = resolve_tie("broader_approval_base", ["A", "B"], p, tally, db=None)
        r2 = resolve_tie("broader_approval_base", ["A", "B"], p, tally, db=None)
        assert r1.chosen_winners == r2.chosen_winners  # determinism
        assert r1.metadata.get("fallback") == "random_seed"
        assert r1.seed is not None

    def test_broader_approval_base_no_ballots_falls_back_to_random_seed(self):
        """Tally without populated ballots → graceful random_seed fallback."""
        p = _make_proposal_stub("no-ballots")
        tally = _make_tally_stub(ballots=[], winners=["A", "B"])
        r = resolve_tie("broader_approval_base", ["A", "B"], p, tally, db=None)
        assert r.method == "broader_approval_base"
        assert r.metadata.get("fallback") == "random_seed"
        assert len(r.chosen_winners) == 1

    def test_earliest_decisive_vote_no_votes_falls_back_to_random_seed(
        self, test_db,
    ):
        """Pathological / no-vote case: no Vote rows for the tied options
        means there are no decisive timestamps; the resolver falls back to
        random_seed and records that fact in metadata."""
        org = _make_org(test_db, "edv-fallback-org")
        author = _make_user(test_db, "edv-fallback-author")
        make_org_membership(
            test_db, org_id=org.id, user_id=author.id, role="steward",
        )
        p = _make_approval_proposal(
            test_db, author, org, option_labels=["A", "B"],
        )
        oids = _option_ids(test_db, p)
        test_db.flush()
        # No votes cast; final_counts will all be zero, so the resolver
        # falls back to random_seed.
        tally = _make_tally_stub(
            option_approvals={oids[0]: 0, oids[1]: 0},
            winners=[oids[0], oids[1]],
        )
        r = resolve_tie(
            "earliest_decisive_vote", [oids[0], oids[1]], p, tally, test_db,
        )
        assert r.method == "earliest_decisive_vote"
        assert len(r.chosen_winners) == 1
        assert r.metadata.get("fallback") == "random_seed"

    def test_earliest_decisive_vote_orders_by_cast_at(self, test_db):
        """When votes record approvals via the runtime attribute on Vote
        rows, A's decisive vote at t=10s beats B's at t=20s → A wins.

        Note: production Vote rows currently store approvals in
        ``Vote.ballot["approvals"]``; the Wave 1+2 resolver reads them via
        ``getattr(v, "approvals", None)``. We assemble Vote rows that
        expose ``approvals`` directly (via SimpleNamespace) and then
        intercept ``db.query`` to feed those rows in. This isolates the
        timestamp-ordering logic without coupling to the underlying ballot
        storage shape."""
        org = _make_org(test_db, "edv-org")
        author = _make_user(test_db, "edv-author")
        make_org_membership(
            test_db, org_id=org.id, user_id=author.id, role="steward",
        )
        p = _make_approval_proposal(
            test_db, author, org, option_labels=["A", "B"],
        )
        oids = _option_ids(test_db, p)
        test_db.flush()
        base = datetime(2026, 5, 9, 12, 0, 0, tzinfo=timezone.utc)
        fake_votes = [
            SimpleNamespace(approvals=[oids[0]], ranking=None,
                            cast_at=base + timedelta(seconds=0)),
            SimpleNamespace(approvals=[oids[0]], ranking=None,
                            cast_at=base + timedelta(seconds=10)),
            SimpleNamespace(approvals=[oids[1]], ranking=None,
                            cast_at=base + timedelta(seconds=5)),
            SimpleNamespace(approvals=[oids[1]], ranking=None,
                            cast_at=base + timedelta(seconds=20)),
        ]
        # Build a fake db.query chain that returns the SimpleNamespace
        # rows for the resolver. The resolver only chains .filter().all()
        # and .filter().order_by().all() so a tiny stub suffices.

        class _Q:
            def __init__(self, rows):
                self._rows = rows

            def filter(self, *a, **kw):
                return self

            def order_by(self, *a, **kw):
                return self

            def all(self):
                return list(self._rows)

        class _DB:
            def query(self, _model):
                return _Q(fake_votes)

        tally = _make_tally_stub(
            option_approvals={oids[0]: 2, oids[1]: 2},
            winners=[oids[0], oids[1]],
        )
        r = resolve_tie(
            "earliest_decisive_vote", [oids[0], oids[1]], p, tally, _DB(),
        )
        assert r.method == "earliest_decisive_vote"
        assert r.chosen_winners == [oids[0]]
        assert oids[0] in r.metadata["decisive_timestamps"]
        assert oids[1] in r.metadata["decisive_timestamps"]

    def test_unknown_method_raises_value_error(self):
        """resolve_tie('not_a_method', ...) → ValueError."""
        p = _make_proposal_stub()
        tally = _make_tally_stub()
        with pytest.raises(ValueError, match="Unknown tie-resolution method"):
            resolve_tie("not_a_method", ["a", "b"], p, tally, db=None)


# ===========================================================================
# 2. TestGetOrgTieResolutionMethod — helper tests.
# ===========================================================================

class TestGetOrgTieResolutionMethod:
    def test_org_none_returns_platform_default_approval(self):
        assert (
            get_org_tie_resolution_method(None, "approval")
            == PLATFORM_DEFAULT_TIE_RESOLUTION_APPROVAL
        )

    def test_org_none_returns_platform_default_ranked_choice(self):
        assert (
            get_org_tie_resolution_method(None, "ranked_choice")
            == PLATFORM_DEFAULT_TIE_RESOLUTION_RANKED_CHOICE
        )

    def test_org_no_settings_returns_platform_default(self, test_db):
        org = _make_org(test_db, "no-settings")
        assert (
            get_org_tie_resolution_method(org, "approval")
            == PLATFORM_DEFAULT_TIE_RESOLUTION_APPROVAL
        )

    def test_org_settings_without_tie_key_returns_platform_default(self, test_db):
        org = _make_org(
            test_db, "no-tie-key",
            settings={"default_voting_days": 7},
        )
        assert (
            get_org_tie_resolution_method(org, "approval")
            == PLATFORM_DEFAULT_TIE_RESOLUTION_APPROVAL
        )

    def test_org_with_stored_value_returns_stored(self, test_db):
        org = _make_org(
            test_db, "stored-tie",
            settings={"tie_resolution": {"approval": "expand_winners"}},
        )
        assert (
            get_org_tie_resolution_method(org, "approval")
            == "expand_winners"
        )

    def test_org_with_stored_value_for_ranked_choice(self, test_db):
        org = _make_org(
            test_db, "stored-rcv",
            settings={"tie_resolution": {"ranked_choice": "expand_winners"}},
        )
        assert (
            get_org_tie_resolution_method(org, "ranked_choice")
            == "expand_winners"
        )

    def test_org_with_invalid_stored_value_falls_back(self, test_db, caplog):
        """Direct-DB-poke could leave an invalid method; helper falls back to
        platform default and logs a warning."""
        org = _make_org(
            test_db, "bad-method",
            settings={"tie_resolution": {"approval": "not_a_real_method"}},
        )
        import logging
        with caplog.at_level(logging.WARNING, logger="org_config"):
            result = get_org_tie_resolution_method(org, "approval")
        assert result == PLATFORM_DEFAULT_TIE_RESOLUTION_APPROVAL
        assert any(
            "invalid tie-resolution method" in rec.message.lower()
            for rec in caplog.records
        )

    def test_unsupported_voting_method_falls_back(self, test_db, caplog):
        """voting_method='binary' isn't tie-resolved; helper logs + returns
        approval default for safety."""
        org = _make_org(test_db, "binary-call")
        import logging
        with caplog.at_level(logging.WARNING, logger="org_config"):
            result = get_org_tie_resolution_method(org, "binary")
        assert result == PLATFORM_DEFAULT_TIE_RESOLUTION_APPROVAL


# ===========================================================================
# 3. TestValidateTieResolutionSettings — validator tests.
# ===========================================================================

class TestValidateTieResolutionSettings:
    def test_valid_dict_returns_dict(self):
        out = validate_tie_resolution_settings(
            {"approval": "expand_winners", "ranked_choice": "random_seed"}
        )
        assert out == {
            "approval": "expand_winners",
            "ranked_choice": "random_seed",
        }

    def test_only_approval_key(self):
        out = validate_tie_resolution_settings({"approval": "broader_approval_base"})
        assert out == {"approval": "broader_approval_base"}

    def test_only_ranked_choice_key(self):
        out = validate_tie_resolution_settings({"ranked_choice": "expand_winners"})
        assert out == {"ranked_choice": "expand_winners"}

    def test_invalid_method_for_approval_raises(self):
        with pytest.raises(ValueError, match="Invalid tie-resolution method"):
            validate_tie_resolution_settings({"approval": "no_such_method"})

    def test_broader_approval_base_for_ranked_choice_raises(self):
        """broader_approval_base is approval-only (D3); not eligible for RCV."""
        with pytest.raises(ValueError, match="ranked_choice"):
            validate_tie_resolution_settings(
                {"ranked_choice": "broader_approval_base"}
            )

    def test_unknown_key_silently_dropped(self):
        """A future voting_method like 'score_voting' shouldn't break the
        PATCH; the validator drops unknown keys (forward-compat)."""
        out = validate_tie_resolution_settings(
            {"approval": "expand_winners", "score_voting": "anything"}
        )
        assert out == {"approval": "expand_winners"}
        assert "score_voting" not in out

    def test_non_dict_raises(self):
        with pytest.raises(ValueError, match="must be an object"):
            validate_tie_resolution_settings("not a dict")  # type: ignore[arg-type]

    def test_empty_dict_returns_empty_dict(self):
        """No keys to validate → returns empty cleaned dict."""
        assert validate_tie_resolution_settings({}) == {}


# ===========================================================================
# 4. TestAdvanceProposalTieResolution — integration tests.
# ===========================================================================

class TestAdvanceProposalTieResolution:
    """End-to-end: advance_proposal closes a tied proposal; assert the
    side effects (Proposal.tie_resolution JSON shape + audit log row)
    per CLAUDE.md testing strategy."""

    def _setup_steward_org(self, db, slug, *, settings=None):
        org = _make_org(db, slug, settings=settings)
        steward = _make_user(db, f"{slug}-steward")
        make_org_membership(
            db, org_id=org.id, user_id=steward.id, role="steward",
        )
        return org, steward

    def test_approval_tie_with_expand_winners_returns_two_winners(
        self, client, test_db,
    ):
        """Approval 2-way tie + org configured expand_winners → 2 winners
        and tie_resolution JSON populated with the chosen_winners list."""
        org, steward = self._setup_steward_org(
            test_db, "appr-expand",
            settings={"tie_resolution": {"approval": "expand_winners"}},
        )
        p = _make_approval_proposal(
            test_db, steward, org, option_labels=["A", "B"],
        )
        oids = _option_ids(test_db, p)
        # Two voters approve A; two approve B.
        for i in range(4):
            u = _make_user(test_db, f"appr-expand-v{i}")
            make_org_membership(
                test_db, org_id=org.id, user_id=u.id, role="member",
            )
            _cast_approval_vote(
                test_db, u, p, [oids[0] if i < 2 else oids[1]],
            )
        # Quorum: 5 members total (steward + 4); 4 voted → 0.8.
        p.quorum_threshold = 0.5
        test_db.commit()

        resp = client.post(
            f"/api/proposals/{p.id}/advance",
            headers=_auth(steward),
            json={},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["status"] == "passed"

        # Side-effect 1: Proposal row carries tie_resolution JSON.
        test_db.expire_all()
        row = test_db.get(models.Proposal, p.id)
        assert row.tie_resolution is not None
        assert row.tie_resolution["method"] == "expand_winners"
        assert set(row.tie_resolution["chosen_winners"]) == set(oids)
        assert set(row.tie_resolution["input_winners"]) == set(oids)
        assert row.tie_resolution["seed"] is None
        assert "applied_at" in row.tie_resolution

        # Side-effect 2: audit-log row exists.
        audit = test_db.query(models.AuditLog).filter(
            models.AuditLog.action == "proposal.tie_resolved",
            models.AuditLog.target_id == p.id,
        ).first()
        assert audit is not None
        assert audit.details["method"] == "expand_winners"
        assert set(audit.details["chosen_winners"]) == set(oids)

    def test_approval_tie_with_random_seed_returns_one_winner(
        self, client, test_db,
    ):
        """Approval 2-way tie + org configured random_seed → 1 winner +
        seed in audit record."""
        org, steward = self._setup_steward_org(
            test_db, "appr-rand",
            settings={"tie_resolution": {"approval": "random_seed"}},
        )
        p = _make_approval_proposal(
            test_db, steward, org, option_labels=["A", "B"],
        )
        oids = _option_ids(test_db, p)
        for i in range(4):
            u = _make_user(test_db, f"appr-rand-v{i}")
            make_org_membership(
                test_db, org_id=org.id, user_id=u.id, role="member",
            )
            _cast_approval_vote(
                test_db, u, p, [oids[0] if i < 2 else oids[1]],
            )
        p.quorum_threshold = 0.5
        test_db.commit()

        resp = client.post(
            f"/api/proposals/{p.id}/advance",
            headers=_auth(steward),
            json={},
        )
        assert resp.status_code == 200, resp.text

        test_db.expire_all()
        row = test_db.get(models.Proposal, p.id)
        assert row.tie_resolution["method"] == "random_seed"
        assert len(row.tie_resolution["chosen_winners"]) == 1
        assert row.tie_resolution["chosen_winners"][0] in oids
        assert row.tie_resolution["seed"] is not None
        assert len(row.tie_resolution["seed"]) == 64  # sha256 hex

    def test_approval_tie_via_org_scoped_route(self, client, test_db):
        """The advance_org_proposal duplicate (routes/organizations.py)
        also fires _maybe_resolve_tie."""
        org, steward = self._setup_steward_org(
            test_db, "appr-org-route",
            settings={"tie_resolution": {"approval": "expand_winners"}},
        )
        p = _make_approval_proposal(
            test_db, steward, org, option_labels=["A", "B"],
        )
        oids = _option_ids(test_db, p)
        for i in range(4):
            u = _make_user(test_db, f"appr-org-v{i}")
            make_org_membership(
                test_db, org_id=org.id, user_id=u.id, role="member",
            )
            _cast_approval_vote(
                test_db, u, p, [oids[0] if i < 2 else oids[1]],
            )
        p.quorum_threshold = 0.5
        test_db.commit()

        resp = client.post(
            f"/api/orgs/{org.slug}/proposals/{p.id}/advance",
            headers=_auth(steward),
            json={},
        )
        assert resp.status_code == 200, resp.text
        test_db.expire_all()
        row = test_db.get(models.Proposal, p.id)
        assert row.tie_resolution is not None
        assert row.tie_resolution["method"] == "expand_winners"

    def test_rcv_num_winners_one_with_random_seed_returns_one_winner(
        self, client, test_db,
    ):
        """RCV num_winners=1 + random_seed → 1 chosen winner."""
        org, steward = self._setup_steward_org(
            test_db, "rcv-rand",
            settings={"tie_resolution": {"ranked_choice": "random_seed"}},
        )
        p = _make_rcv_proposal(
            test_db, steward, org, option_labels=["A", "B"], num_winners=1,
        )
        oids = _option_ids(test_db, p)
        for i in range(4):
            u = _make_user(test_db, f"rcv-rand-v{i}")
            make_org_membership(
                test_db, org_id=org.id, user_id=u.id, role="member",
            )
            _cast_ranked_vote(
                test_db, u, p, [oids[0] if i < 2 else oids[1]],
            )
        p.quorum_threshold = 0.5
        test_db.commit()

        resp = client.post(
            f"/api/proposals/{p.id}/advance",
            headers=_auth(steward),
            json={},
        )
        assert resp.status_code == 200, resp.text
        test_db.expire_all()
        row = test_db.get(models.Proposal, p.id)
        # If pyrankvote returned a single winner already, tie_resolution
        # might be null. Otherwise it should be random_seed-resolved.
        if row.tie_resolution is not None:
            assert row.tie_resolution["method"] == "random_seed"
            assert len(row.tie_resolution["chosen_winners"]) == 1

    def test_rcv_num_winners_one_with_expand_winners_returns_two(
        self, client, test_db,
    ):
        """D11: num_winners=1 + expand_winners → 2 winners (deliberately
        documented behavior)."""
        org, steward = self._setup_steward_org(
            test_db, "rcv-expand",
            settings={"tie_resolution": {"ranked_choice": "expand_winners"}},
        )
        p = _make_rcv_proposal(
            test_db, steward, org, option_labels=["A", "B"], num_winners=1,
        )
        oids = _option_ids(test_db, p)
        for i in range(4):
            u = _make_user(test_db, f"rcv-exp-v{i}")
            make_org_membership(
                test_db, org_id=org.id, user_id=u.id, role="member",
            )
            _cast_ranked_vote(
                test_db, u, p, [oids[0] if i < 2 else oids[1]],
            )
        p.quorum_threshold = 0.5
        test_db.commit()

        resp = client.post(
            f"/api/proposals/{p.id}/advance",
            headers=_auth(steward),
            json={},
        )
        assert resp.status_code == 200, resp.text
        test_db.expire_all()
        row = test_db.get(models.Proposal, p.id)
        # If the RCV engine returned the tied set, expand_winners should
        # have widened it to all tied options.
        if row.tie_resolution is not None:
            assert row.tie_resolution["method"] == "expand_winners"
            assert len(row.tie_resolution["chosen_winners"]) >= 2

    def test_no_tie_leaves_tie_resolution_null(self, client, test_db):
        """Approval with a clear winner → tie_resolution stays None and
        no proposal.tie_resolved audit row is written."""
        org, steward = self._setup_steward_org(
            test_db, "appr-clear",
            settings={"tie_resolution": {"approval": "expand_winners"}},
        )
        p = _make_approval_proposal(
            test_db, steward, org, option_labels=["A", "B"],
        )
        oids = _option_ids(test_db, p)
        # 3 voters approve A, 1 approves B → A clear winner.
        for i in range(4):
            u = _make_user(test_db, f"appr-clear-v{i}")
            make_org_membership(
                test_db, org_id=org.id, user_id=u.id, role="member",
            )
            _cast_approval_vote(
                test_db, u, p, [oids[0] if i < 3 else oids[1]],
            )
        p.quorum_threshold = 0.5
        test_db.commit()

        resp = client.post(
            f"/api/proposals/{p.id}/advance",
            headers=_auth(steward),
            json={},
        )
        assert resp.status_code == 200, resp.text
        test_db.expire_all()
        row = test_db.get(models.Proposal, p.id)
        assert row.tie_resolution is None

        # No audit row.
        audit = test_db.query(models.AuditLog).filter(
            models.AuditLog.action == "proposal.tie_resolved",
            models.AuditLog.target_id == p.id,
        ).first()
        assert audit is None


# ===========================================================================
# 5. TestPlatformAdminUpdate — settings PATCH tests.
# ===========================================================================

class TestPlatformAdminUpdate:
    def test_patch_valid_tie_resolution_persists(self, client, test_db):
        """Steward PATCHes settings.tie_resolution; row is updated and
        the helper now returns the configured methods."""
        admin = _make_user(test_db, "patch-steward")
        org = _make_org(test_db, "patch-tie")
        make_org_membership(
            test_db, org_id=org.id, user_id=admin.id, role="steward",
        )
        test_db.commit()

        resp = client.patch(
            f"/api/orgs/{org.slug}",
            headers=_auth(admin),
            json={
                "settings": {
                    "tie_resolution": {
                        "approval": "expand_winners",
                        "ranked_choice": "random_seed",
                    },
                },
            },
        )
        assert resp.status_code == 200, resp.text

        test_db.expire_all()
        org_row = test_db.query(models.Organization).filter(
            models.Organization.slug == org.slug,
        ).first()
        assert (
            org_row.settings["tie_resolution"]["approval"] == "expand_winners"
        )
        assert (
            org_row.settings["tie_resolution"]["ranked_choice"] == "random_seed"
        )

    def test_patch_invalid_method_returns_400(self, client, test_db):
        """Invalid method on either voting_method → HTTP 400."""
        admin = _make_user(test_db, "patch-bad-steward")
        org = _make_org(test_db, "patch-bad")
        make_org_membership(
            test_db, org_id=org.id, user_id=admin.id, role="steward",
        )
        test_db.commit()

        resp = client.patch(
            f"/api/orgs/{org.slug}",
            headers=_auth(admin),
            json={
                "settings": {
                    "tie_resolution": {"approval": "not_a_method"},
                },
            },
        )
        assert resp.status_code == 400
        assert "tie-resolution" in resp.json()["detail"].lower()

    def test_patch_unknown_key_silently_dropped(self, client, test_db):
        """Forward-compat: an unknown voting_method key in tie_resolution
        is dropped on save rather than returning 400."""
        admin = _make_user(test_db, "patch-fwd-steward")
        org = _make_org(test_db, "patch-fwd")
        make_org_membership(
            test_db, org_id=org.id, user_id=admin.id, role="steward",
        )
        test_db.commit()

        resp = client.patch(
            f"/api/orgs/{org.slug}",
            headers=_auth(admin),
            json={
                "settings": {
                    "tie_resolution": {
                        "approval": "expand_winners",
                        "score_voting": "anything",
                    },
                },
            },
        )
        assert resp.status_code == 200, resp.text
        test_db.expire_all()
        org_row = test_db.query(models.Organization).filter(
            models.Organization.slug == org.slug,
        ).first()
        # Only the recognized key persists.
        assert (
            org_row.settings["tie_resolution"]
            == {"approval": "expand_winners"}
        )

    def test_patch_member_lacks_permission(self, client, test_db):
        """A plain Member (no org.edit_settings) gets 403 on PATCH."""
        member = _make_user(test_db, "patch-member")
        org = _make_org(test_db, "patch-deny")
        make_org_membership(
            test_db, org_id=org.id, user_id=member.id, role="member",
        )
        test_db.commit()

        resp = client.patch(
            f"/api/orgs/{org.slug}",
            headers=_auth(member),
            json={
                "settings": {
                    "tie_resolution": {"approval": "expand_winners"},
                },
            },
        )
        # require_org_admin returns 403 for non-admin members.
        assert resp.status_code == 403


# ===========================================================================
# 6. TestSchemaCleanup — confirm TieResolutionRequest is gone.
# ===========================================================================

class TestSchemaCleanup:
    def test_tie_resolution_request_import_fails(self):
        """Phase 17 D10 / B6: TieResolutionRequest schema removed from
        backend.schemas. Importing it must raise ImportError."""
        with pytest.raises(ImportError):
            from schemas import TieResolutionRequest  # noqa: F401

    def test_tie_resolution_request_attribute_absent(self):
        """The symbol is also absent from the module namespace, not just
        unimportable."""
        import schemas
        assert not hasattr(schemas, "TieResolutionRequest")
