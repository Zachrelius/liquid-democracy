"""Phase 24 — natural-close-on-voting-end worker integration tests.

Exercises the new ``evaluate_proposal`` branches introduced in Phase 24:

  - Non-SRR natural-close: proposal with ``stable_result_required = None``
    (or org default off) whose ``voting_end < now`` closes on the next
    worker tick with ``trigger=voting_end_reached``.
  - SRR-exhausted natural-close fallback: SRR-active proposal whose
    extension budget is exhausted and voting_end has passed runs SRR's
    destabilization-at-max path AND the new fallback closes the proposal
    naturally.

Uses real ``models.Proposal`` rows on an in-memory SQLite database per
Phase 17 lesson (no SimpleNamespace shims).
"""

from datetime import datetime, timedelta, timezone
from unittest import mock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import StaticPool

import models
import sustained_majority_worker as worker
from database import Base
from tests.conftest import make_org_membership


_DUMMY_HASH = "$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/lewrwKJuRxm5pJmJi"


@pytest.fixture(scope="function")
def db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _user(db: Session, username: str) -> models.User:
    u = models.User(
        username=username,
        display_name=username.title(),
        password_hash=_DUMMY_HASH,
        email=f"{username}@test.example",
        email_verified=True,
    )
    db.add(u)
    db.flush()
    return u


def _member(db: Session, org: models.Organization, user: models.User) -> None:
    make_org_membership(
        db,
        user_id=user.id, org_id=org.id, role="member", status="active",
    )
    db.flush()


def _non_srr_org(db: Session, slug_seed: str = "n") -> models.Organization:
    """Org with SRR disabled by default — exercises the Phase 24 non-SRR
    natural-close branch."""
    org = models.Organization(
        name="Org",
        slug=f"o-{slug_seed}-{id(slug_seed)}",
        description="",
        join_policy="open",
        settings={
            "stable_result_enabled_default": False,
            "stable_window_fraction": 0.25,
            "max_extension_fraction": 0.25,
        },
    )
    db.add(org)
    db.flush()
    return org


def _voting_proposal(
    db: Session,
    *,
    org: models.Organization,
    author: models.User,
    voting_method: str = "binary",
    voting_start: datetime | None = None,
    voting_end: datetime | None = None,
    pass_threshold: float = 0.5,
    quorum_threshold: float = 0.0,
    stable_result_required: bool | None = None,
) -> models.Proposal:
    now = _now()
    p = models.Proposal(
        title="P",
        body="",
        author_id=author.id,
        org_id=org.id,
        voting_method=voting_method,
        status="voting",
        stable_result_required=stable_result_required,
        voting_start=voting_start or (now - timedelta(hours=2)),
        voting_end=voting_end or (now - timedelta(hours=1)),  # default past
        pass_threshold=pass_threshold,
        quorum_threshold=quorum_threshold,
    )
    db.add(p)
    db.flush()
    return p


def _cast_binary(db: Session, user: models.User, proposal: models.Proposal, value: str):
    db.add(models.Vote(
        proposal_id=proposal.id,
        user_id=user.id,
        vote_value=value,
        is_direct=True,
        cast_by_id=user.id,
    ))
    db.flush()


def _option(db: Session, proposal: models.Proposal, label: str) -> models.ProposalOption:
    o = models.ProposalOption(
        proposal_id=proposal.id, label=label,
    )
    db.add(o)
    db.flush()
    return o


def _cast_approval(
    db: Session, user: models.User, proposal: models.Proposal,
    approved_option_ids: list[str],
) -> None:
    db.add(models.Vote(
        proposal_id=proposal.id,
        user_id=user.id,
        vote_value=None,
        ballot={"approvals": approved_option_ids},
        is_direct=True,
        cast_by_id=user.id,
    ))
    db.flush()


def _cast_rcv(
    db: Session, user: models.User, proposal: models.Proposal,
    ranking: list[str],
) -> None:
    db.add(models.Vote(
        proposal_id=proposal.id,
        user_id=user.id,
        vote_value=None,
        ballot={"ranking": ranking},
        is_direct=True,
        cast_by_id=user.id,
    ))
    db.flush()


def _enable_in_app_proposal_closed(db: Session, user: models.User) -> None:
    """Seed the in_app NotificationPreference for proposal.closed so that
    ``emit_notification`` writes a row in tests. Opt-in default elsewhere
    means a fresh user has no preference rows and would receive no in-app
    notification at all."""
    db.add(models.NotificationPreference(
        user_id=user.id,
        event_type="proposal.closed",
        channel="in_app",
        enabled=True,
    ))
    db.flush()


def _emitted_notifications(db: Session, proposal_id: str) -> list[models.Notification]:
    return (
        db.query(models.Notification)
        .filter(
            models.Notification.event_type == "proposal.closed",
            models.Notification.target_id == proposal_id,
        )
        .all()
    )


# ---------------------------------------------------------------------------
# Non-SRR natural-close branch (Phase 24 B1.2 — primary path)
# ---------------------------------------------------------------------------

class TestNaturalCloseBinaryPassed:
    """Non-SRR binary proposal past voting_end with yes-majority + quorum
    met -> evaluate_proposal returns 'closed_on_time' and sets status=passed.
    """

    def test_closes_passed(self, db):
        author = _user(db, "alice")
        bob = _user(db, "bob")
        carol = _user(db, "carol")
        org = _non_srr_org(db, "passed")
        proposal = _voting_proposal(
            db, org=org, author=author,
            voting_method="binary",
            quorum_threshold=0.3,
        )
        for u in (author, bob, carol):
            _member(db, org, u)
        _cast_binary(db, author, proposal, "yes")
        _cast_binary(db, bob, proposal, "yes")
        _cast_binary(db, carol, proposal, "no")
        db.commit()

        old_end = proposal.voting_end
        result = worker.evaluate_proposal(db, proposal)
        db.commit()

        assert result == "closed_on_time"
        assert proposal.status == "passed"
        # Phase 24 natural-close preserves the original voting_end (audit
        # trail of when voting was *meant* to close).
        assert proposal.voting_end == old_end
        # Audit row + trigger.
        rows = (
            db.query(models.AuditLog)
            .filter(
                models.AuditLog.action == "proposal.status_changed",
                models.AuditLog.target_id == proposal.id,
            )
            .all()
        )
        assert any(
            (r.details or {}).get("trigger") == worker.TRIGGER_VOTING_END_REACHED
            for r in rows
        )


class TestNaturalCloseBinaryFailed:
    """Non-SRR binary, voting_end past, no > yes, quorum met -> failed."""

    def test_closes_failed(self, db):
        author = _user(db, "alice")
        bob = _user(db, "bob")
        carol = _user(db, "carol")
        org = _non_srr_org(db, "failed")
        proposal = _voting_proposal(
            db, org=org, author=author,
            voting_method="binary",
            quorum_threshold=0.3,
        )
        for u in (author, bob, carol):
            _member(db, org, u)
        _cast_binary(db, author, proposal, "no")
        _cast_binary(db, bob, proposal, "no")
        _cast_binary(db, carol, proposal, "yes")
        db.commit()

        result = worker.evaluate_proposal(db, proposal)
        db.commit()
        assert result == "closed_on_time"
        assert proposal.status == "failed"


class TestNaturalCloseBinaryFailedQuorum:
    """Non-SRR binary, voting_end past, quorum NOT met -> failed +
    outcome_detail mentions quorum."""

    def test_closes_failed_quorum_with_notification_detail(self, db):
        author = _user(db, "alice")
        bob = _user(db, "bob")
        # Spectators so quorum threshold matters.
        for n in range(5):
            _user(db, f"spec{n}")
        org = _non_srr_org(db, "noq")
        proposal = _voting_proposal(
            db, org=org, author=author,
            voting_method="binary",
            quorum_threshold=0.9,  # need 90% of eligible to vote
        )
        # Only 2 of the 7 members vote -> 2/7 = 0.29 < 0.9.
        _member(db, org, author)
        _member(db, org, bob)
        for n in range(5):
            spec = db.query(models.User).filter(models.User.username == f"spec{n}").first()
            _member(db, org, spec)
        _cast_binary(db, author, proposal, "yes")
        _cast_binary(db, bob, proposal, "yes")
        _enable_in_app_proposal_closed(db, author)
        _enable_in_app_proposal_closed(db, bob)
        db.commit()

        result = worker.evaluate_proposal(db, proposal)
        db.commit()
        assert result == "closed_on_time"
        assert proposal.status == "failed"
        # Notification payload includes the quorum-aware outcome_detail.
        notifs = _emitted_notifications(db, proposal.id)
        assert notifs, "should have emitted at least one proposal.closed notification"
        details = [n.payload.get("outcome_detail") for n in notifs if n.payload]
        assert any("quorum not met" in (d or "") for d in details), (
            f"expected 'quorum not met' in outcome_detail; got {details}"
        )


class TestNaturalCloseApproval:
    """Non-SRR approval, voting_end past, quorum met, winner emerges ->
    closed_on_time with status=passed."""

    def test_closes_with_winner(self, db):
        author = _user(db, "alice")
        bob = _user(db, "bob")
        org = _non_srr_org(db, "appr")
        proposal = _voting_proposal(
            db, org=org, author=author,
            voting_method="approval",
            quorum_threshold=0.3,
        )
        for u in (author, bob):
            _member(db, org, u)
        opt_a = _option(db, proposal, "Option A")
        opt_b = _option(db, proposal, "Option B")
        _cast_approval(db, author, proposal, [opt_a.id])
        _cast_approval(db, bob, proposal, [opt_a.id, opt_b.id])
        _enable_in_app_proposal_closed(db, author)
        _enable_in_app_proposal_closed(db, bob)
        db.commit()

        result = worker.evaluate_proposal(db, proposal)
        db.commit()
        assert result == "closed_on_time"
        assert proposal.status == "passed"
        # outcome_detail names the winning option.
        notifs = _emitted_notifications(db, proposal.id)
        details = [n.payload.get("outcome_detail") for n in notifs if n.payload]
        assert any("Option A" in (d or "") for d in details), (
            f"expected winning option in outcome_detail; got {details}"
        )


class TestNaturalCloseRankedChoice:
    """Non-SRR RCV, voting_end past, quorum met -> closed_on_time."""

    def test_closes_with_winner(self, db):
        author = _user(db, "alice")
        bob = _user(db, "bob")
        carol = _user(db, "carol")
        org = _non_srr_org(db, "rcv")
        proposal = _voting_proposal(
            db, org=org, author=author,
            voting_method="ranked_choice",
            quorum_threshold=0.3,
        )
        for u in (author, bob, carol):
            _member(db, org, u)
        a = _option(db, proposal, "Tuesday")
        b = _option(db, proposal, "Wednesday")
        # First-choice: 2 for Tuesday, 1 for Wednesday => Tuesday wins.
        _cast_rcv(db, author, proposal, [a.id, b.id])
        _cast_rcv(db, bob, proposal, [a.id, b.id])
        _cast_rcv(db, carol, proposal, [b.id, a.id])
        db.commit()

        result = worker.evaluate_proposal(db, proposal)
        db.commit()
        assert result == "closed_on_time"
        assert proposal.status == "passed"


# ---------------------------------------------------------------------------
# Boundary cases
# ---------------------------------------------------------------------------

class TestNaturalCloseSkippedIfVotingNotEnded:
    """Non-SRR proposal with voting_end in the future: snapshot taken, but
    no close happens."""

    def test_future_voting_end_no_close(self, db):
        author = _user(db, "alice")
        bob = _user(db, "bob")
        org = _non_srr_org(db, "future")
        proposal = _voting_proposal(
            db, org=org, author=author,
            voting_end=_now() + timedelta(hours=4),
        )
        _member(db, org, author)
        _member(db, org, bob)
        _cast_binary(db, author, proposal, "yes")
        _cast_binary(db, bob, proposal, "yes")
        db.commit()

        result = worker.evaluate_proposal(db, proposal)
        db.commit()
        assert result is None
        assert proposal.status == "voting"
        # Snapshot was still taken (Phase 22 universal capture).
        snap_count = db.query(models.VoteSnapshot).filter(
            models.VoteSnapshot.proposal_id == proposal.id,
        ).count()
        assert snap_count == 1


class TestNaturalCloseSkippedIfAlreadyClosed:
    """A proposal already in status='passed' must not be re-closed by a
    second worker tick. Idempotency check."""

    def test_already_passed_idempotent(self, db):
        author = _user(db, "alice")
        org = _non_srr_org(db, "alreadyclosed")
        # Create as passed directly — represents the state after a prior
        # tick has closed it.
        proposal = _voting_proposal(
            db, org=org, author=author,
        )
        proposal.status = "passed"
        db.flush()
        db.commit()

        result = worker.evaluate_proposal(db, proposal)
        db.commit()
        # Worker skips: run_one_tick filters status='voting' upstream, but
        # if a caller passes a closed proposal directly evaluate_proposal
        # must not double-close. Verify the status didn't flip.
        assert proposal.status == "passed"
        # No status_changed audit was logged this tick (only the original
        # close).
        rows = (
            db.query(models.AuditLog)
            .filter(
                models.AuditLog.action == "proposal.status_changed",
                models.AuditLog.target_id == proposal.id,
            )
            .all()
        )
        assert len(rows) == 0
        # Idempotency: result is None — neither closed_on_time nor any
        # SRR action.
        assert result is None


# ---------------------------------------------------------------------------
# SRR interaction (B1.2 — fallback path)
# ---------------------------------------------------------------------------

def _srr_org(db: Session, slug_seed: str, max_ext_fraction: float = 0.25) -> models.Organization:
    org = models.Organization(
        name="Org",
        slug=f"o-{slug_seed}-{id(slug_seed)}",
        description="",
        join_policy="open",
        settings={
            "stable_result_enabled_default": True,
            "stable_window_fraction": 0.25,
            "max_extension_fraction": max_ext_fraction,
        },
    )
    db.add(org)
    db.flush()
    return org


def _seed_extension_audit(
    db: Session, proposal: models.Proposal, *, extension_seconds: int,
) -> None:
    from audit_utils import log_audit_event
    log_audit_event(
        db,
        action="proposal.window_extended",
        target_type="proposal",
        target_id=proposal.id,
        actor_id=None,
        details={
            "proposal_id": proposal.id,
            "extension_seconds": extension_seconds,
            "trigger": "stable_result_required",
        },
    )
    db.flush()


def _seed_binary_snapshot(
    db: Session, proposal: models.Proposal, *,
    yes: int, no: int, abstain: int = 0, total_eligible: int = 10,
    when: datetime | None = None,
) -> models.VoteSnapshot:
    snap = models.VoteSnapshot(
        proposal_id=proposal.id,
        simulated_time=when or _now(),
        yes_count=yes, no_count=no, abstain_count=abstain,
        not_cast_count=max(0, total_eligible - yes - no - abstain),
        total_eligible=total_eligible,
        multi_option_winners=None,
    )
    db.add(snap)
    db.flush()
    return snap


class TestSRRActiveProposalNotPreempted:
    """SRR-active proposal with voting_end past + extension budget remaining
    + sliding-window unstable -> SRR extends. Phase 24 fallback does NOT
    preempt — proposal stays in voting after a fresh extension."""

    def test_srr_extends_natural_close_no_op(self, db):
        author = _user(db, "alice")
        bob = _user(db, "bob")
        # max_extension_fraction = 0.50 -> budget = 50s. One prior 25s
        # extension -> 25s remaining -> fits another.
        org = _srr_org(db, "srrext", max_ext_fraction=0.50)
        start = _now() - timedelta(seconds=130)
        end = _now() - timedelta(seconds=5)  # past
        proposal = _voting_proposal(
            db, org=org, author=author,
            voting_start=start, voting_end=end,
        )
        _member(db, org, author)
        _member(db, org, bob)
        _seed_extension_audit(db, proposal, extension_seconds=25)
        # Unstable lookback -> sliding-window check fails.
        _seed_binary_snapshot(
            db, proposal, yes=2, no=8, total_eligible=10,
            when=_now() - timedelta(seconds=20),
        )
        _cast_binary(db, author, proposal, "no")
        _cast_binary(db, bob, proposal, "no")
        db.commit()

        old_end = proposal.voting_end
        result = worker.evaluate_proposal(db, proposal)
        db.commit()
        # SRR fired an extension; fallback saw new voting_end in the
        # future after apply_extension, so it did NOT close. Result is
        # "extended" (SRR's action), not closed_on_time_after_srr_exhausted.
        assert result == "extended"
        assert proposal.status == "voting"
        assert proposal.voting_end > old_end  # extended


class TestSRRExhaustedFallsThroughToNaturalClose:
    """SRR-active proposal, voting_end past, extension budget exhausted ->
    SRR's destabilization-at-max audit logged AND Phase 24 fallback fires,
    closing the proposal."""

    def test_destab_at_max_then_natural_close(self, db):
        author = _user(db, "alice")
        bob = _user(db, "bob")
        # max_extension_fraction = 0.25 -> budget = 25s; one prior 25s
        # extension exhausts the budget.
        org = _srr_org(db, "srrexh", max_ext_fraction=0.25)
        start = _now() - timedelta(seconds=130)
        end = _now() - timedelta(seconds=5)
        proposal = _voting_proposal(
            db, org=org, author=author,
            voting_start=start, voting_end=end,
        )
        _member(db, org, author)
        _member(db, org, bob)
        _seed_extension_audit(db, proposal, extension_seconds=25)
        _seed_binary_snapshot(
            db, proposal, yes=2, no=8, total_eligible=10,
            when=_now() - timedelta(seconds=20),
        )
        _cast_binary(db, author, proposal, "no")
        _cast_binary(db, bob, proposal, "no")
        db.commit()

        old_end = proposal.voting_end
        result = worker.evaluate_proposal(db, proposal)
        db.commit()
        # SRR-exhausted fallback closes the proposal.
        assert result == "closed_on_time_after_srr_exhausted"
        assert proposal.status in ("passed", "failed")
        # voting_end preserved (Phase 24 natural-close does NOT overwrite).
        assert proposal.voting_end == old_end
        # SRR's destab-at-max audit row exists.
        destab_rows = (
            db.query(models.AuditLog)
            .filter(
                models.AuditLog.action == "proposal.destabilization_at_max_extensions",
                models.AuditLog.target_id == proposal.id,
            )
            .all()
        )
        assert len(destab_rows) == 1
        # Status-changed audit with trigger=voting_end_reached also written.
        status_rows = (
            db.query(models.AuditLog)
            .filter(
                models.AuditLog.action == "proposal.status_changed",
                models.AuditLog.target_id == proposal.id,
            )
            .all()
        )
        assert any(
            (r.details or {}).get("trigger") == worker.TRIGGER_VOTING_END_REACHED
            for r in status_rows
        )


# ---------------------------------------------------------------------------
# Notification trigger string sanity
# ---------------------------------------------------------------------------

class TestNaturalCloseEmitsCorrectTriggerString:
    """The proposal.closed notification emitted by natural-close carries
    trigger='voting_end_reached' (NOT 'stable_result_achieved')."""

    def test_trigger_voting_end_reached(self, db):
        author = _user(db, "alice")
        bob = _user(db, "bob")
        org = _non_srr_org(db, "trig")
        proposal = _voting_proposal(
            db, org=org, author=author,
            quorum_threshold=0.3,
        )
        _member(db, org, author)
        _member(db, org, bob)
        _cast_binary(db, author, proposal, "yes")
        _cast_binary(db, bob, proposal, "yes")
        _enable_in_app_proposal_closed(db, author)
        _enable_in_app_proposal_closed(db, bob)
        db.commit()

        worker.evaluate_proposal(db, proposal)
        db.commit()

        notifs = _emitted_notifications(db, proposal.id)
        assert notifs, "natural-close should emit at least one proposal.closed notification"
        triggers = {n.payload.get("trigger") for n in notifs if n.payload}
        assert worker.TRIGGER_VOTING_END_REACHED in triggers
        assert worker.TRIGGER_STABLE_RESULT_ACHIEVED not in triggers
