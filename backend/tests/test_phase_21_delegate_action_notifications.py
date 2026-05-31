"""Phase 21 — delegate action notifications + preference presets.

This file holds the Phase 21 tests:

  Wave 1 (foundation):
    * Registry assertions for the 5 new event keys (B1).
    * Signal-level classification check for every event in EVENT_REGISTRY (B6).
    * Preset-stamping helpers (``apply_preset_to_preferences``,
      ``detect_matching_preset``) — happy paths for each preset, always-on
      exemption, at-most-one-email-channel invariant, round-trip detection.
    * Endpoint tests for ``GET /api/notifications/registry`` (signal_level
      surfaced) and ``GET /api/notifications/preferences`` (matching_preset
      surfaced) and ``POST /api/notifications/preferences/apply_preset``.

  Wave 2 (this file, appended below):
    * Vote-cast / vote-change / rationale-post emission in routes/votes.py.
    * Halfway-deadline scheduler-driven events (run_halfway_deadline_check
      invoked directly with a synthetic ``now``).
    * No-self-notify (D14) and transaction-rollback safety on emission
      error (D15).
    * Mutual exclusivity of the two halfway events (D5/D6).
    * Scheduler idempotency (D9).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import auth as auth_utils
import models
from database import Base, get_db
from main import app
from notification_events import (
    EVENT_REGISTRY,
    EVENT_REGISTRY_BY_KEY,
    PRESET_STAMP_RULES,
    SIGNAL_LEVELS,
    apply_preset_to_preferences,
    detect_matching_preset,
)
from role_seed import seed_default_roles_for_org
from tests.conftest import make_org_membership


_DUMMY_HASH = "$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/lewrwKJuRxm5pJmJi"


# ---------------------------------------------------------------------------
# Shared test fixtures
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


def _make_user(db: Session, username: str) -> models.User:
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


def _auth(user: models.User) -> dict:
    return {"Authorization": f"Bearer {auth_utils.create_access_token(user.id)}"}


# Reference classification per spec D19 — used to verify each event's
# signal_level matches the locked decision. Keep in sync with the
# registry; the test will fail loudly if the registry drifts.
_EXPECTED_SIGNAL_LEVEL: dict[str, str] = {
    # critical
    "proposal.entered_voting.you_vote": "critical",
    "proposal.entered_voting.delegated_to_you": "critical",
    "proposal.closed": "critical",
    "proposal.extended_by_stability": "critical",
    "delegate.vote_changed": "critical",
    "voting.halfway_delegate_silent": "critical",
    "voting.halfway_you_havent_voted": "critical",
    "delegation_revoked_by_delegate": "critical",
    "delegate_application_denied": "critical",
    # standard
    "comment.replied": "standard",
    "proposal.entered_voting": "standard",
    "delegate.voted": "standard",
    "delegate.posted_rationale": "standard",
    "member.join_request": "standard",
    "delegate.applied": "standard",
    "delegate_application_submitted": "standard",
    "follow.requested": "standard",
    # ambient
    "comment.posted_on_your_proposal": "ambient",
    "polis.created": "ambient",
    # Phase 32 W7 / E5 — write-in + edit notifications.
    "proposal.option_added": "standard",
    "proposal.edited": "standard",
    # always_on
    "invitation.accepted": "always_on",
    "delegate.application_decided": "always_on",
    "delegate_application_approved": "always_on",
    "follow.approved": "always_on",
    # Phase 44 — multi-admin approval pending-action events.
    # All but expiry are critical (approver fan-out + initiator
    # decision/execute/fail outcomes); expiry is standard since the
    # initiator can also see the action staled by visiting the queue.
    "pending_action.submitted": "critical",
    "pending_action.executed": "critical",
    "pending_action.declined": "critical",
    "pending_action.expired": "standard",
    "pending_action.failed": "critical",
}


# Channel field names that presets stamp. Matches the registry's stamp
# rules and routes/notifications.py's _CHANNEL_FIELDS.
_CHANNELS = ("in_app", "email_immediate", "email_daily", "email_weekly")
_EMAIL_CHANNELS = ("email_immediate", "email_daily", "email_weekly")


# ---------------------------------------------------------------------------
# B1 — registry has the 5 new events
# ---------------------------------------------------------------------------

class TestRegistryHasFiveNewEvents:
    """The 5 Phase 21 events are present in the registry with the exact
    labels and categories from spec §B1."""

    def test_delegate_voted_present(self):
        ev = EVENT_REGISTRY_BY_KEY.get("delegate.voted")
        assert ev is not None, "delegate.voted must be in EVENT_REGISTRY"
        assert ev.label == "Your delegate cast a vote"
        assert ev.category == "Delegation"

    def test_delegate_vote_changed_present(self):
        ev = EVENT_REGISTRY_BY_KEY.get("delegate.vote_changed")
        assert ev is not None
        assert ev.label == "Your delegate changed their vote"
        assert ev.category == "Delegation"

    def test_delegate_posted_rationale_present(self):
        ev = EVENT_REGISTRY_BY_KEY.get("delegate.posted_rationale")
        assert ev is not None
        assert ev.label == "Your delegate posted a vote rationale"
        assert ev.category == "Delegation"

    def test_voting_halfway_delegate_silent_present(self):
        ev = EVENT_REGISTRY_BY_KEY.get("voting.halfway_delegate_silent")
        assert ev is not None
        assert ev.label == "Voting half-elapsed; your delegate hasn't voted"
        assert ev.category == "Delegation"

    def test_voting_halfway_you_havent_voted_present(self):
        ev = EVENT_REGISTRY_BY_KEY.get("voting.halfway_you_havent_voted")
        assert ev is not None
        assert ev.label == "Voting half-elapsed; you haven't voted"
        # D1: this one is the only Phase 21 event in the Proposals
        # category; the other 4 are in Delegation.
        assert ev.category == "Proposals"


# ---------------------------------------------------------------------------
# B6 — signal_level classifications
# ---------------------------------------------------------------------------

class TestSignalLevelClassifications:
    """Every event has a valid signal_level AND matches the D19 spec
    classification."""

    def test_every_event_has_valid_signal_level(self):
        for ev in EVENT_REGISTRY:
            assert ev.signal_level in SIGNAL_LEVELS, (
                f"{ev.key!r} has invalid signal_level {ev.signal_level!r}; "
                f"expected one of {SIGNAL_LEVELS}"
            )

    def test_classification_matches_d19(self):
        """Every event in the registry is in _EXPECTED_SIGNAL_LEVEL and
        the registry value matches the spec's locked classification.

        If this fails, either:
          (a) a new event was added without updating
              _EXPECTED_SIGNAL_LEVEL (update the test), or
          (b) an existing event's signal_level was changed away from
              D19 (revert or update D19 first).
        """
        registry_keys = {ev.key for ev in EVENT_REGISTRY}
        expected_keys = set(_EXPECTED_SIGNAL_LEVEL.keys())
        missing_from_expected = registry_keys - expected_keys
        assert not missing_from_expected, (
            f"Registry events not in _EXPECTED_SIGNAL_LEVEL: "
            f"{sorted(missing_from_expected)}. Update the test or D19."
        )
        for ev in EVENT_REGISTRY:
            expected_level = _EXPECTED_SIGNAL_LEVEL[ev.key]
            assert ev.signal_level == expected_level, (
                f"{ev.key!r} signal_level is {ev.signal_level!r}; "
                f"D19 expects {expected_level!r}"
            )


# ---------------------------------------------------------------------------
# B6 — apply_preset_to_preferences happy paths
# ---------------------------------------------------------------------------

class TestApplyPresetHigh:
    """High preset stamps in-app on for all 3 levels; email_immediate for
    critical; email_daily for standard; email_weekly for ambient."""

    def test_critical_event(self):
        result = apply_preset_to_preferences("high", {})
        # delegate.vote_changed is critical per D19.
        assert result["delegate.vote_changed"] == {
            "in_app": True,
            "email_immediate": True,
            "email_daily": False,
            "email_weekly": False,
        }

    def test_standard_event(self):
        result = apply_preset_to_preferences("high", {})
        # delegate.voted is standard.
        assert result["delegate.voted"] == {
            "in_app": True,
            "email_immediate": False,
            "email_daily": True,
            "email_weekly": False,
        }

    def test_ambient_event(self):
        result = apply_preset_to_preferences("high", {})
        # polis.created is ambient.
        assert result["polis.created"] == {
            "in_app": True,
            "email_immediate": False,
            "email_daily": False,
            "email_weekly": True,
        }

    def test_always_on_event_not_in_result(self):
        result = apply_preset_to_preferences("high", {})
        # invitation.accepted is always_on; preset doesn't touch it, so
        # starting from an empty current_prefs dict it stays absent.
        assert "invitation.accepted" not in result


class TestApplyPresetMedium:
    """Medium preset: critical in-app + email_daily; standard in-app +
    email_weekly; ambient all-off."""

    def test_critical_event(self):
        result = apply_preset_to_preferences("medium", {})
        assert result["delegate.vote_changed"] == {
            "in_app": True,
            "email_immediate": False,
            "email_daily": True,
            "email_weekly": False,
        }

    def test_standard_event(self):
        result = apply_preset_to_preferences("medium", {})
        assert result["delegate.voted"] == {
            "in_app": True,
            "email_immediate": False,
            "email_daily": False,
            "email_weekly": True,
        }

    def test_ambient_event(self):
        result = apply_preset_to_preferences("medium", {})
        assert result["polis.created"] == {
            "in_app": False,
            "email_immediate": False,
            "email_daily": False,
            "email_weekly": False,
        }

    def test_always_on_event_not_in_result(self):
        result = apply_preset_to_preferences("medium", {})
        assert "follow.approved" not in result


class TestApplyPresetLow:
    """Low preset: critical in-app + email_weekly only; standard +
    ambient all-off."""

    def test_critical_event(self):
        result = apply_preset_to_preferences("low", {})
        assert result["delegate.vote_changed"] == {
            "in_app": True,
            "email_immediate": False,
            "email_daily": False,
            "email_weekly": True,
        }

    def test_standard_event(self):
        result = apply_preset_to_preferences("low", {})
        assert result["delegate.voted"] == {
            "in_app": False,
            "email_immediate": False,
            "email_daily": False,
            "email_weekly": False,
        }

    def test_ambient_event(self):
        result = apply_preset_to_preferences("low", {})
        assert result["polis.created"] == {
            "in_app": False,
            "email_immediate": False,
            "email_daily": False,
            "email_weekly": False,
        }

    def test_always_on_event_not_in_result(self):
        result = apply_preset_to_preferences("low", {})
        assert "delegate.application_decided" not in result


class TestPresetsStampAtMostOneEmailChannel:
    """For each preset, every stamped event has at most one of the three
    email channels enabled. Property of the stamping logic, not an
    invariant enforced on user-edited preferences (D18)."""

    @pytest.mark.parametrize("preset", ["high", "medium", "low"])
    def test_at_most_one_email_channel_per_event(self, preset):
        result = apply_preset_to_preferences(preset, {})
        for ev_key, channels in result.items():
            n_email = sum(1 for c in _EMAIL_CHANNELS if channels.get(c))
            assert n_email <= 1, (
                f"Preset {preset!r} stamps {n_email} email channels on "
                f"{ev_key!r} (channels={channels}); presets must enable "
                f"at most one of {_EMAIL_CHANNELS} per event."
            )


class TestPresetDoesNotTouchAlwaysOn:
    """always_on events keep their pre-preset values regardless of which
    preset is applied (D18 — user-initiated-response events are exempt)."""

    @pytest.mark.parametrize("preset", ["high", "medium", "low"])
    def test_always_on_preserved(self, preset):
        # Pre-populate an always_on event with a unique signature so we
        # can verify the preset didn't overwrite it.
        sentinel = {
            "in_app": True,
            "email_immediate": True,
            "email_daily": True,
            "email_weekly": True,
        }
        current = {"invitation.accepted": dict(sentinel)}
        result = apply_preset_to_preferences(preset, current)
        assert result["invitation.accepted"] == sentinel, (
            f"Preset {preset!r} modified always_on event "
            f"invitation.accepted; got {result['invitation.accepted']}"
        )


class TestDetectMatchingPreset:
    """Round-trip: applying each preset to {} and detecting on the result
    returns the original preset name. A custom prefs dict returns None."""

    @pytest.mark.parametrize("preset", ["high", "medium", "low"])
    def test_round_trip(self, preset):
        stamped = apply_preset_to_preferences(preset, {})
        detected = detect_matching_preset(stamped)
        assert detected == preset, (
            f"Round-trip mismatch: applied {preset!r}, detected "
            f"{detected!r}"
        )

    def test_custom_prefs_returns_none(self):
        # Start from "high" and tweak one channel — should no longer match
        # any preset.
        custom = apply_preset_to_preferences("high", {})
        # delegate.vote_changed is critical — under high it's
        # in_app+email_immediate. Flip in_app off; that doesn't match any
        # preset's critical row.
        custom["delegate.vote_changed"] = {
            "in_app": False,
            "email_immediate": True,
            "email_daily": False,
            "email_weekly": False,
        }
        assert detect_matching_preset(custom) is None

    def test_empty_prefs_returns_none(self):
        # An all-False prefs dict matches none of the three presets
        # (every preset stamps at least one True channel on at least one
        # event).
        all_false = {
            ev.key: {c: False for c in _CHANNELS}
            for ev in EVENT_REGISTRY
            if ev.signal_level != "always_on"
        }
        assert detect_matching_preset(all_false) is None


# ---------------------------------------------------------------------------
# B6 — endpoint tests
# ---------------------------------------------------------------------------

class TestRegistryEndpointIncludesSignalLevel:
    """GET /api/notifications/registry returns signal_level on every event."""

    def test_all_events_have_signal_level(self, client, test_db):
        user = _make_user(test_db, "registry_signal_user")
        test_db.commit()
        resp = client.get("/api/notifications/registry", headers=_auth(user))
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert "events" in body
        for ev in body["events"]:
            assert "signal_level" in ev, (
                f"Event {ev.get('key')!r} missing signal_level in response"
            )
            assert ev["signal_level"] in list(SIGNAL_LEVELS), (
                f"Event {ev.get('key')!r} has invalid signal_level "
                f"{ev['signal_level']!r}"
            )


class TestGetPreferencesIncludesMatchingPreset:
    """GET /api/notifications/preferences returns matching_preset.

    With no prefs set → None (empty all-False dict matches no preset).
    After applying the "low" preset → "low".
    """

    def test_no_prefs_returns_none(self, client, test_db):
        user = _make_user(test_db, "match_pref_none")
        test_db.commit()
        resp = client.get("/api/notifications/preferences", headers=_auth(user))
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert "matching_preset" in body
        assert body["matching_preset"] is None

    def test_after_applying_low_preset_returns_low(self, client, test_db):
        user = _make_user(test_db, "match_pref_low")
        test_db.commit()
        # Apply the low preset.
        apply_resp = client.post(
            "/api/notifications/preferences/apply_preset",
            json={"preset": "low"},
            headers=_auth(user),
        )
        assert apply_resp.status_code == 200, apply_resp.text
        # Now GET should report matching_preset = "low".
        resp = client.get("/api/notifications/preferences", headers=_auth(user))
        assert resp.status_code == 200
        body = resp.json()
        assert body["matching_preset"] == "low", (
            f"Expected 'low'; got {body.get('matching_preset')!r}"
        )


class TestApplyPresetEndpoint:
    """POST /api/notifications/preferences/apply_preset.

    Valid preset → 200 + updated PreferencesOut with matching_preset
    matching the applied preset; preference rows are upserted in the DB.
    Invalid preset → 400.
    """

    def test_invalid_preset_returns_400(self, client, test_db):
        user = _make_user(test_db, "apply_bad_preset")
        test_db.commit()
        resp = client.post(
            "/api/notifications/preferences/apply_preset",
            json={"preset": "extreme"},
            headers=_auth(user),
        )
        assert resp.status_code == 400, resp.text

    def test_missing_preset_field_returns_validation_error(self, client, test_db):
        user = _make_user(test_db, "apply_missing_preset")
        test_db.commit()
        resp = client.post(
            "/api/notifications/preferences/apply_preset",
            json={},
            headers=_auth(user),
        )
        # FastAPI/Pydantic 422 for missing required body field.
        assert resp.status_code in (400, 422), resp.text

    @pytest.mark.parametrize("preset", ["high", "medium", "low"])
    def test_valid_preset_returns_updated_prefs(self, client, test_db, preset):
        user = _make_user(test_db, f"apply_{preset}_user")
        test_db.commit()
        resp = client.post(
            "/api/notifications/preferences/apply_preset",
            json={"preset": preset},
            headers=_auth(user),
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        # Response includes matching_preset = the applied preset.
        assert body["matching_preset"] == preset
        # And the per-event channels match what the preset stamps.
        expected = apply_preset_to_preferences(preset, {})
        for ev_key, channels in expected.items():
            assert ev_key in body["preferences"], (
                f"event {ev_key!r} missing from preferences response"
            )
            for ch in _CHANNELS:
                assert body["preferences"][ev_key][ch] == channels[ch], (
                    f"Preset {preset!r} on event {ev_key!r} channel {ch!r}: "
                    f"got {body['preferences'][ev_key][ch]}, "
                    f"expected {channels[ch]}"
                )

    def test_preset_persists_to_db(self, client, test_db):
        user = _make_user(test_db, "apply_persist_user")
        test_db.commit()
        resp = client.post(
            "/api/notifications/preferences/apply_preset",
            json={"preset": "high"},
            headers=_auth(user),
        )
        assert resp.status_code == 200
        # NotificationPreference rows exist for at least one of the events
        # the high preset stamps.
        rows = (
            test_db.query(models.NotificationPreference)
            .filter(models.NotificationPreference.user_id == user.id)
            .all()
        )
        assert len(rows) > 0, (
            "Expected NotificationPreference rows after apply_preset; "
            "found none"
        )
        # Spot-check: delegate.vote_changed in_app should be True under
        # high preset.
        keyed = {(r.event_type, r.channel): r.enabled for r in rows}
        assert keyed.get(("delegate.vote_changed", "in_app")) is True, (
            f"Expected (delegate.vote_changed, in_app)=True under high; "
            f"got {keyed.get(('delegate.vote_changed', 'in_app'))!r}"
        )


# ===========================================================================
# WAVE 2 — emission wiring + scheduler tests
# ===========================================================================

# ---------------------------------------------------------------------------
# Wave-2 fixtures + helpers
# ---------------------------------------------------------------------------

def _now_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _make_org(db: Session, slug: str) -> models.Organization:
    o = models.Organization(
        name=slug.replace("_", " ").title(),
        slug=slug,
        description="",
        settings={},
    )
    db.add(o)
    db.flush()
    seed_default_roles_for_org(db, o.id)
    return o


def _make_topic(db: Session, org: models.Organization, name: str = "T") -> models.Topic:
    t = models.Topic(name=name, color="#000000", org_id=org.id)
    db.add(t)
    db.flush()
    return t


def _make_voting_proposal(
    db: Session,
    author: models.User,
    org: models.Organization,
    *,
    topic: models.Topic | None = None,
    voting_start: datetime | None = None,
    voting_end: datetime | None = None,
) -> models.Proposal:
    vs = voting_start if voting_start is not None else _now_naive() - timedelta(days=1)
    ve = voting_end if voting_end is not None else _now_naive() + timedelta(days=1)
    p = models.Proposal(
        title="Test P",
        body="body",
        author_id=author.id,
        org_id=org.id,
        status="voting",
        voting_method="binary",
        voting_start=vs,
        voting_end=ve,
    )
    db.add(p)
    db.flush()
    if topic is not None:
        db.add(models.ProposalTopic(
            proposal_id=p.id, topic_id=topic.id, relevance=1.0,
        ))
        db.flush()
    return p


def _make_delegation(
    db: Session,
    delegator: models.User,
    delegate: models.User,
    org: models.Organization,
    *,
    topic: models.Topic | None = None,
) -> models.Delegation:
    d = models.Delegation(
        delegator_id=delegator.id,
        delegate_id=delegate.id,
        org_id=org.id,
        topic_id=topic.id if topic else None,
    )
    db.add(d)
    db.flush()
    return d


def _opt_in(
    db: Session,
    user: models.User,
    event_type: str,
    *,
    in_app: bool = True,
) -> None:
    if in_app:
        db.add(models.NotificationPreference(
            user_id=user.id, event_type=event_type,
            channel="in_app", enabled=True,
        ))
    db.flush()


def _notifications_for(
    db: Session, user_id: str, event_type: str, proposal_id: str | None = None,
) -> list[models.Notification]:
    q = db.query(models.Notification).filter(
        models.Notification.user_id == user_id,
        models.Notification.event_type == event_type,
    )
    if proposal_id is not None:
        q = q.filter(models.Notification.target_id == proposal_id)
    return q.all()


# ---------------------------------------------------------------------------
# B2 — TestDelegateVotedEvent
# ---------------------------------------------------------------------------

class TestDelegateVotedEvent:
    """delegate.voted fires to opted-in delegators when the delegate
    casts an initial vote. Payload carries proposal_id, proposal_title,
    delegate_user_id, delegate_display_name, vote_value, cast_at."""

    def test_initial_cast_fires_one_per_delegator(self, client, test_db):
        org = _make_org(test_db, "dv1")
        topic = _make_topic(test_db, org)
        delegate = _make_user(test_db, "dv1_delegate")
        delegator_a = _make_user(test_db, "dv1_delor_a")
        delegator_b = _make_user(test_db, "dv1_delor_b")
        for u in (delegate, delegator_a, delegator_b):
            make_org_membership(test_db, org_id=org.id, user_id=u.id, role="member")
        author = _make_user(test_db, "dv1_author")
        make_org_membership(test_db, org_id=org.id, user_id=author.id, role="admin")
        proposal = _make_voting_proposal(test_db, author, org, topic=topic)
        _make_delegation(test_db, delegator_a, delegate, org, topic=topic)
        _make_delegation(test_db, delegator_b, delegate, org, topic=topic)
        _opt_in(test_db, delegator_a, "delegate.voted")
        _opt_in(test_db, delegator_b, "delegate.voted")
        test_db.commit()

        resp = client.post(
            f"/api/proposals/{proposal.id}/vote",
            json={"vote_value": "yes"},
            headers=_auth(delegate),
        )
        assert resp.status_code == 200, resp.text

        for delegator in (delegator_a, delegator_b):
            rows = _notifications_for(test_db, delegator.id, "delegate.voted", proposal.id)
            assert len(rows) == 1, (
                f"expected 1 delegate.voted notification for {delegator.username}, "
                f"got {len(rows)}"
            )
            payload = rows[0].payload
            assert payload["proposal_id"] == proposal.id
            assert payload["proposal_title"] == proposal.title
            assert payload["delegate_user_id"] == delegate.id
            assert payload["delegate_display_name"] == delegate.display_name
            assert payload["vote_value"] == "yes"
            assert "cast_at" in payload

    def test_no_optin_no_notification(self, client, test_db):
        org = _make_org(test_db, "dv2")
        topic = _make_topic(test_db, org)
        delegate = _make_user(test_db, "dv2_delegate")
        delegator = _make_user(test_db, "dv2_delor")
        for u in (delegate, delegator):
            make_org_membership(test_db, org_id=org.id, user_id=u.id, role="member")
        author = _make_user(test_db, "dv2_author")
        make_org_membership(test_db, org_id=org.id, user_id=author.id, role="admin")
        proposal = _make_voting_proposal(test_db, author, org, topic=topic)
        _make_delegation(test_db, delegator, delegate, org, topic=topic)
        # NB: no opt-in for delegator
        test_db.commit()

        resp = client.post(
            f"/api/proposals/{proposal.id}/vote",
            json={"vote_value": "yes"},
            headers=_auth(delegate),
        )
        assert resp.status_code == 200, resp.text

        rows = _notifications_for(test_db, delegator.id, "delegate.voted", proposal.id)
        assert rows == []


# ---------------------------------------------------------------------------
# B2 — TestDelegateVotedDedup + TestDelegateVoteChangedPayload
# ---------------------------------------------------------------------------

class TestDelegateVotedDedup:
    """Initial cast -> delegate.voted (one per delegator). Update ->
    delegate.vote_changed (NOT a second delegate.voted). Two consecutive
    delegate.vote_changed within the dedup window collapse to one row
    per delegator."""

    def test_update_fires_vote_changed_not_voted_again(self, client, test_db):
        org = _make_org(test_db, "dd1")
        topic = _make_topic(test_db, org)
        delegate = _make_user(test_db, "dd1_delegate")
        delegator = _make_user(test_db, "dd1_delor")
        for u in (delegate, delegator):
            make_org_membership(test_db, org_id=org.id, user_id=u.id, role="member")
        author = _make_user(test_db, "dd1_author")
        make_org_membership(test_db, org_id=org.id, user_id=author.id, role="admin")
        proposal = _make_voting_proposal(test_db, author, org, topic=topic)
        _make_delegation(test_db, delegator, delegate, org, topic=topic)
        _opt_in(test_db, delegator, "delegate.voted")
        _opt_in(test_db, delegator, "delegate.vote_changed")
        test_db.commit()

        # Initial cast -> delegate.voted.
        r1 = client.post(
            f"/api/proposals/{proposal.id}/vote",
            json={"vote_value": "yes"},
            headers=_auth(delegate),
        )
        assert r1.status_code == 200, r1.text
        # Update -> delegate.vote_changed.
        r2 = client.post(
            f"/api/proposals/{proposal.id}/vote",
            json={"vote_value": "no"},
            headers=_auth(delegate),
        )
        assert r2.status_code == 200, r2.text

        voted = _notifications_for(test_db, delegator.id, "delegate.voted", proposal.id)
        changed = _notifications_for(test_db, delegator.id, "delegate.vote_changed", proposal.id)
        assert len(voted) == 1, f"expected exactly 1 delegate.voted; got {len(voted)}"
        assert len(changed) == 1, f"expected exactly 1 delegate.vote_changed; got {len(changed)}"

    def test_two_consecutive_changes_dedup_to_one(self, client, test_db):
        org = _make_org(test_db, "dd2")
        topic = _make_topic(test_db, org)
        delegate = _make_user(test_db, "dd2_delegate")
        delegator = _make_user(test_db, "dd2_delor")
        for u in (delegate, delegator):
            make_org_membership(test_db, org_id=org.id, user_id=u.id, role="member")
        author = _make_user(test_db, "dd2_author")
        make_org_membership(test_db, org_id=org.id, user_id=author.id, role="admin")
        proposal = _make_voting_proposal(test_db, author, org, topic=topic)
        _make_delegation(test_db, delegator, delegate, org, topic=topic)
        _opt_in(test_db, delegator, "delegate.voted")
        _opt_in(test_db, delegator, "delegate.vote_changed")
        test_db.commit()

        # Initial cast.
        client.post(
            f"/api/proposals/{proposal.id}/vote",
            json={"vote_value": "yes"},
            headers=_auth(delegate),
        )
        # First change.
        client.post(
            f"/api/proposals/{proposal.id}/vote",
            json={"vote_value": "no"},
            headers=_auth(delegate),
        )
        # Second change within dedup window.
        client.post(
            f"/api/proposals/{proposal.id}/vote",
            json={"vote_value": "abstain"},
            headers=_auth(delegate),
        )

        changed = _notifications_for(test_db, delegator.id, "delegate.vote_changed", proposal.id)
        assert len(changed) == 1, (
            f"expected dedup to 1 delegate.vote_changed within 1h window; got {len(changed)}"
        )


class TestDelegateVoteChangedPayload:
    """delegate.vote_changed payload includes previous_vote_value and
    changed_at on top of the delegate.voted shape."""

    def test_payload_has_previous_and_changed_at(self, client, test_db):
        org = _make_org(test_db, "dcp")
        topic = _make_topic(test_db, org)
        delegate = _make_user(test_db, "dcp_delegate")
        delegator = _make_user(test_db, "dcp_delor")
        for u in (delegate, delegator):
            make_org_membership(test_db, org_id=org.id, user_id=u.id, role="member")
        author = _make_user(test_db, "dcp_author")
        make_org_membership(test_db, org_id=org.id, user_id=author.id, role="admin")
        proposal = _make_voting_proposal(test_db, author, org, topic=topic)
        _make_delegation(test_db, delegator, delegate, org, topic=topic)
        _opt_in(test_db, delegator, "delegate.vote_changed")
        test_db.commit()

        client.post(
            f"/api/proposals/{proposal.id}/vote",
            json={"vote_value": "yes"},
            headers=_auth(delegate),
        )
        client.post(
            f"/api/proposals/{proposal.id}/vote",
            json={"vote_value": "no"},
            headers=_auth(delegate),
        )

        rows = _notifications_for(test_db, delegator.id, "delegate.vote_changed", proposal.id)
        assert len(rows) == 1
        payload = rows[0].payload
        assert payload["previous_vote_value"] == "yes"
        assert payload["vote_value"] == "no"
        assert "changed_at" in payload
        assert "cast_at" in payload
        assert payload["delegate_user_id"] == delegate.id


# ---------------------------------------------------------------------------
# B2 — TestDelegatePostedRationaleEvent
# ---------------------------------------------------------------------------

class TestDelegatePostedRationaleEvent:
    """delegate.posted_rationale fires ONCE per delegator on CREATE
    (not update) when the vote-owner has a DelegateProfile with
    visibility public or public_accepting on a proposal topic."""

    def _seed(self, test_db, slug_prefix: str, visibility: str = "public_accepting"):
        org = _make_org(test_db, f"{slug_prefix}_org")
        topic = _make_topic(test_db, org)
        vote_owner = _make_user(test_db, f"{slug_prefix}_owner")
        delegator = _make_user(test_db, f"{slug_prefix}_delor")
        author = _make_user(test_db, f"{slug_prefix}_author")
        for u in (vote_owner, delegator, author):
            role = "admin" if u is author else "member"
            make_org_membership(test_db, org_id=org.id, user_id=u.id, role=role)
        proposal = _make_voting_proposal(test_db, author, org, topic=topic)
        _make_delegation(test_db, delegator, vote_owner, org, topic=topic)
        # Vote-owner casts a vote first (rationale attaches to vote).
        vote = models.Vote(
            proposal_id=proposal.id,
            user_id=vote_owner.id,
            vote_value="yes",
            is_direct=True,
            cast_by_id=vote_owner.id,
        )
        test_db.add(vote)
        test_db.flush()
        # DelegateProfile with the requested visibility.
        dp = models.DelegateProfile(
            user_id=vote_owner.id,
            topic_id=topic.id,
            org_id=org.id,
            bio="",
            visibility=visibility,
        )
        if visibility == "public_accepting":
            dp.public_accepting_approved_at = _now_naive()
        test_db.add(dp)
        test_db.flush()
        _opt_in(test_db, delegator, "delegate.posted_rationale")
        test_db.commit()
        return org, topic, vote_owner, delegator, proposal, vote

    def test_fires_on_create_with_public_accepting(self, client, test_db):
        _org, _topic, owner, delegator, proposal, vote = self._seed(test_db, "rp1")
        resp = client.put(
            f"/api/votes/{vote.id}/rationale",
            json={"content": "Here's why I voted yes — extensive reasoning."},
            headers=_auth(owner),
        )
        assert resp.status_code == 200, resp.text
        rows = _notifications_for(test_db, delegator.id, "delegate.posted_rationale", proposal.id)
        assert len(rows) == 1
        payload = rows[0].payload
        assert payload["delegate_user_id"] == owner.id
        assert payload["proposal_id"] == proposal.id
        assert "rationale_excerpt" in payload
        assert payload["rationale_excerpt"].startswith("Here's why")
        assert "posted_at" in payload

    def test_update_does_not_fire_second_notification(self, client, test_db):
        _org, _topic, owner, delegator, proposal, vote = self._seed(test_db, "rp2")
        # First PUT (create).
        client.put(
            f"/api/votes/{vote.id}/rationale",
            json={"content": "Initial reasoning."},
            headers=_auth(owner),
        )
        # Second PUT (update) — must NOT emit a second notification.
        client.put(
            f"/api/votes/{vote.id}/rationale",
            json={"content": "Updated reasoning."},
            headers=_auth(owner),
        )
        rows = _notifications_for(test_db, delegator.id, "delegate.posted_rationale", proposal.id)
        assert len(rows) == 1, (
            f"expected only the create notification, not an update one; got {len(rows)}"
        )

    def test_excerpt_truncated_to_150_chars(self, client, test_db):
        _org, _topic, owner, delegator, proposal, vote = self._seed(test_db, "rp3")
        long_content = "x" * 500
        client.put(
            f"/api/votes/{vote.id}/rationale",
            json={"content": long_content},
            headers=_auth(owner),
        )
        rows = _notifications_for(test_db, delegator.id, "delegate.posted_rationale", proposal.id)
        assert len(rows) == 1
        assert len(rows[0].payload["rationale_excerpt"]) == 150


class TestDelegatePostedRationaleNoFireOnPrivateProfile:
    """When the vote-owner's DelegateProfile is `private`, the rationale
    isn't visible to delegators on the public page, so no notification
    should fire."""

    def test_private_visibility_suppresses_emit(self, client, test_db):
        org = _make_org(test_db, "rprv_org")
        topic = _make_topic(test_db, org)
        owner = _make_user(test_db, "rprv_owner")
        delegator = _make_user(test_db, "rprv_delor")
        author = _make_user(test_db, "rprv_author")
        for u in (owner, delegator, author):
            role = "admin" if u is author else "member"
            make_org_membership(test_db, org_id=org.id, user_id=u.id, role=role)
        proposal = _make_voting_proposal(test_db, author, org, topic=topic)
        _make_delegation(test_db, delegator, owner, org, topic=topic)
        vote = models.Vote(
            proposal_id=proposal.id, user_id=owner.id,
            vote_value="yes", is_direct=True, cast_by_id=owner.id,
        )
        test_db.add(vote)
        test_db.flush()
        dp = models.DelegateProfile(
            user_id=owner.id, topic_id=topic.id, org_id=org.id,
            bio="", visibility="private",
        )
        test_db.add(dp)
        test_db.flush()
        _opt_in(test_db, delegator, "delegate.posted_rationale")
        test_db.commit()

        resp = client.put(
            f"/api/votes/{vote.id}/rationale",
            json={"content": "Private reasoning."},
            headers=_auth(owner),
        )
        assert resp.status_code == 200
        rows = _notifications_for(
            test_db, delegator.id, "delegate.posted_rationale", proposal.id,
        )
        assert rows == [], (
            f"expected no notification for private DelegateProfile; got {len(rows)}"
        )


# ---------------------------------------------------------------------------
# B2 — D14 / D15 safety tests
# ---------------------------------------------------------------------------

class TestNoSelfNotificationOnVote:
    """A user who is their own delegate (self-delegation, edge case)
    must NOT receive a delegate.voted / delegate.vote_changed
    notification about their own vote (D14)."""

    def test_self_delegation_no_notification(self, client, test_db):
        org = _make_org(test_db, "self_d")
        topic = _make_topic(test_db, org)
        u = _make_user(test_db, "self_u")
        make_org_membership(test_db, org_id=org.id, user_id=u.id, role="member")
        author = _make_user(test_db, "self_author")
        make_org_membership(test_db, org_id=org.id, user_id=author.id, role="admin")
        proposal = _make_voting_proposal(test_db, author, org, topic=topic)
        # u is their own delegate.
        _make_delegation(test_db, u, u, org, topic=topic)
        _opt_in(test_db, u, "delegate.voted")
        _opt_in(test_db, u, "delegate.vote_changed")
        test_db.commit()

        resp = client.post(
            f"/api/proposals/{proposal.id}/vote",
            json={"vote_value": "yes"},
            headers=_auth(u),
        )
        assert resp.status_code == 200, resp.text

        rows_voted = _notifications_for(test_db, u.id, "delegate.voted", proposal.id)
        rows_changed = _notifications_for(test_db, u.id, "delegate.vote_changed", proposal.id)
        assert rows_voted == [], (
            "self-delegation must not produce a delegate.voted notification"
        )
        assert rows_changed == []


class TestVoteCommitDoesNotRollBackOnNotificationError:
    """D15 — vote write must succeed even if emit_notification raises.
    Patch emit_notification to raise; assert the Vote row is queryable."""

    def test_emit_failure_does_not_block_vote(self, client, test_db):
        org = _make_org(test_db, "rb1")
        topic = _make_topic(test_db, org)
        delegate = _make_user(test_db, "rb1_delegate")
        delegator = _make_user(test_db, "rb1_delor")
        for u in (delegate, delegator):
            make_org_membership(test_db, org_id=org.id, user_id=u.id, role="member")
        author = _make_user(test_db, "rb1_author")
        make_org_membership(test_db, org_id=org.id, user_id=author.id, role="admin")
        proposal = _make_voting_proposal(test_db, author, org, topic=topic)
        _make_delegation(test_db, delegator, delegate, org, topic=topic)
        _opt_in(test_db, delegator, "delegate.voted")
        test_db.commit()

        with patch(
            "routes.votes.emit_notification",
            side_effect=RuntimeError("simulated emit failure"),
        ):
            resp = client.post(
                f"/api/proposals/{proposal.id}/vote",
                json={"vote_value": "yes"},
                headers=_auth(delegate),
            )
            assert resp.status_code == 200, resp.text

        # Vote must still be in DB.
        v = (
            test_db.query(models.Vote)
            .filter(
                models.Vote.proposal_id == proposal.id,
                models.Vote.user_id == delegate.id,
            )
            .first()
        )
        assert v is not None, "vote write must persist even if notification emit raises"
        assert v.vote_value == "yes"


# ---------------------------------------------------------------------------
# B3 — halfway-deadline scheduler tests
# ---------------------------------------------------------------------------

class TestHalfwayDelegateSilentEvent:
    """voting.halfway_delegate_silent fires once per (user, proposal)
    when: voting is at >= 50% elapsed, the user has an active
    delegation on the topic, the delegate hasn't cast a vote. Re-running
    the check produces no duplicate notification."""

    def _seed(self, test_db, slug: str):
        from digest_scheduler import run_halfway_deadline_check  # noqa: F401
        org = _make_org(test_db, slug)
        topic = _make_topic(test_db, org)
        delegate = _make_user(test_db, f"{slug}_delegate")
        delegator = _make_user(test_db, f"{slug}_delor")
        for u in (delegate, delegator):
            make_org_membership(test_db, org_id=org.id, user_id=u.id, role="member")
        author = _make_user(test_db, f"{slug}_author")
        make_org_membership(test_db, org_id=org.id, user_id=author.id, role="admin")
        # Voting started 2 days ago, ends 2 days from now -> 50% elapsed.
        vs = _now_naive() - timedelta(days=2)
        ve = _now_naive() + timedelta(days=2)
        proposal = _make_voting_proposal(
            test_db, author, org, topic=topic,
            voting_start=vs, voting_end=ve,
        )
        _make_delegation(test_db, delegator, delegate, org, topic=topic)
        _opt_in(test_db, delegator, "voting.halfway_delegate_silent")
        test_db.commit()
        return org, topic, delegate, delegator, proposal

    def test_emits_on_first_run(self, test_db):
        from digest_scheduler import run_halfway_deadline_check
        _org, _topic, _delegate, delegator, proposal = self._seed(test_db, "hds1")
        counts = run_halfway_deadline_check(test_db)
        assert counts["halfway_delegate_silent"] >= 1
        rows = _notifications_for(
            test_db, delegator.id, "voting.halfway_delegate_silent", proposal.id,
        )
        assert len(rows) == 1
        payload = rows[0].payload
        assert payload["proposal_id"] == proposal.id
        assert payload["proposal_title"] == proposal.title
        assert payload["delegate_user_id"] is not None
        assert payload["delegate_display_name"] is not None
        assert "voting_end" in payload
        assert "percent_elapsed" in payload
        assert 0.4 <= payload["percent_elapsed"] <= 0.6

    def test_second_run_no_duplicate(self, test_db):
        from digest_scheduler import run_halfway_deadline_check
        _org, _topic, _delegate, delegator, proposal = self._seed(test_db, "hds2")
        run_halfway_deadline_check(test_db)
        # Second invocation: should not duplicate.
        run_halfway_deadline_check(test_db)
        rows = _notifications_for(
            test_db, delegator.id, "voting.halfway_delegate_silent", proposal.id,
        )
        assert len(rows) == 1, (
            f"expected idempotency: second run should not duplicate; got {len(rows)}"
        )

    def test_skips_when_delegate_has_voted(self, test_db):
        from digest_scheduler import run_halfway_deadline_check
        _org, _topic, delegate, delegator, proposal = self._seed(test_db, "hds3")
        # Delegate has voted -> no notification.
        v = models.Vote(
            proposal_id=proposal.id, user_id=delegate.id,
            vote_value="yes", is_direct=True, cast_by_id=delegate.id,
        )
        test_db.add(v)
        test_db.commit()

        run_halfway_deadline_check(test_db)
        rows = _notifications_for(
            test_db, delegator.id, "voting.halfway_delegate_silent", proposal.id,
        )
        assert rows == []


class TestHalfwayYouHaventVotedEvent:
    """voting.halfway_you_havent_voted fires once per (user, proposal)
    when: voting is at >= 50% elapsed, the user has no delegation on
    the topic, and they haven't voted. Re-running is a no-op."""

    def _seed(self, test_db, slug: str):
        org = _make_org(test_db, slug)
        topic = _make_topic(test_db, org)
        voter = _make_user(test_db, f"{slug}_voter")
        make_org_membership(test_db, org_id=org.id, user_id=voter.id, role="member")
        author = _make_user(test_db, f"{slug}_author")
        make_org_membership(test_db, org_id=org.id, user_id=author.id, role="admin")
        vs = _now_naive() - timedelta(days=2)
        ve = _now_naive() + timedelta(days=2)
        proposal = _make_voting_proposal(
            test_db, author, org, topic=topic,
            voting_start=vs, voting_end=ve,
        )
        _opt_in(test_db, voter, "voting.halfway_you_havent_voted")
        test_db.commit()
        return org, topic, voter, proposal

    def test_emits_for_undelegated_silent_voter(self, test_db):
        from digest_scheduler import run_halfway_deadline_check
        _org, _topic, voter, proposal = self._seed(test_db, "hys1")
        counts = run_halfway_deadline_check(test_db)
        assert counts["halfway_you_havent_voted"] >= 1
        rows = _notifications_for(
            test_db, voter.id, "voting.halfway_you_havent_voted", proposal.id,
        )
        assert len(rows) == 1
        payload = rows[0].payload
        assert payload["proposal_id"] == proposal.id
        assert "voting_end" in payload
        assert "percent_elapsed" in payload
        # No delegate_user_id on this variant (D12).
        assert "delegate_user_id" not in payload

    def test_second_run_no_duplicate(self, test_db):
        from digest_scheduler import run_halfway_deadline_check
        _org, _topic, voter, proposal = self._seed(test_db, "hys2")
        run_halfway_deadline_check(test_db)
        run_halfway_deadline_check(test_db)
        rows = _notifications_for(
            test_db, voter.id, "voting.halfway_you_havent_voted", proposal.id,
        )
        assert len(rows) == 1

    def test_skips_when_user_has_voted(self, test_db):
        from digest_scheduler import run_halfway_deadline_check
        _org, _topic, voter, proposal = self._seed(test_db, "hys3")
        v = models.Vote(
            proposal_id=proposal.id, user_id=voter.id,
            vote_value="yes", is_direct=True, cast_by_id=voter.id,
        )
        test_db.add(v)
        test_db.commit()
        run_halfway_deadline_check(test_db)
        rows = _notifications_for(
            test_db, voter.id, "voting.halfway_you_havent_voted", proposal.id,
        )
        assert rows == []


class TestHalfwayMutuallyExclusive:
    """A user with a delegation receives ONLY the silent variant,
    NEVER the havent_voted variant (D5/D6)."""

    def test_delegated_user_gets_silent_not_havent(self, test_db):
        from digest_scheduler import run_halfway_deadline_check
        org = _make_org(test_db, "hmx")
        topic = _make_topic(test_db, org)
        delegate = _make_user(test_db, "hmx_delegate")
        delegator = _make_user(test_db, "hmx_delor")
        for u in (delegate, delegator):
            make_org_membership(test_db, org_id=org.id, user_id=u.id, role="member")
        author = _make_user(test_db, "hmx_author")
        make_org_membership(test_db, org_id=org.id, user_id=author.id, role="admin")
        vs = _now_naive() - timedelta(days=2)
        ve = _now_naive() + timedelta(days=2)
        proposal = _make_voting_proposal(
            test_db, author, org, topic=topic,
            voting_start=vs, voting_end=ve,
        )
        _make_delegation(test_db, delegator, delegate, org, topic=topic)
        _opt_in(test_db, delegator, "voting.halfway_delegate_silent")
        _opt_in(test_db, delegator, "voting.halfway_you_havent_voted")
        test_db.commit()

        run_halfway_deadline_check(test_db)
        silent_rows = _notifications_for(
            test_db, delegator.id, "voting.halfway_delegate_silent", proposal.id,
        )
        havent_rows = _notifications_for(
            test_db, delegator.id, "voting.halfway_you_havent_voted", proposal.id,
        )
        assert len(silent_rows) == 1, (
            f"delegated user should get silent variant; got {len(silent_rows)}"
        )
        assert havent_rows == [], (
            f"delegated user must NOT get havent_voted variant; got {len(havent_rows)}"
        )


class TestHalfwayPercentElapsedThreshold:
    """A proposal at < 50% elapsed must NOT fire halfway events.
    A proposal at past 100% (voting already closed by clock; status
    still 'voting' due to no advance) must NOT fire either."""

    def test_below_50pct_no_fire(self, test_db):
        from digest_scheduler import run_halfway_deadline_check
        org = _make_org(test_db, "hpe1")
        topic = _make_topic(test_db, org)
        voter = _make_user(test_db, "hpe1_voter")
        make_org_membership(test_db, org_id=org.id, user_id=voter.id, role="member")
        author = _make_user(test_db, "hpe1_author")
        make_org_membership(test_db, org_id=org.id, user_id=author.id, role="admin")
        # 25% elapsed: started 1d ago, ends 3d from now -> 1/4 elapsed.
        vs = _now_naive() - timedelta(days=1)
        ve = _now_naive() + timedelta(days=3)
        proposal = _make_voting_proposal(
            test_db, author, org, topic=topic,
            voting_start=vs, voting_end=ve,
        )
        _opt_in(test_db, voter, "voting.halfway_you_havent_voted")
        test_db.commit()

        run_halfway_deadline_check(test_db)
        rows = _notifications_for(
            test_db, voter.id, "voting.halfway_you_havent_voted", proposal.id,
        )
        assert rows == [], (
            "proposal below 50% elapsed must not fire halfway notifications"
        )

    def test_above_100pct_no_fire(self, test_db):
        from digest_scheduler import run_halfway_deadline_check
        org = _make_org(test_db, "hpe2")
        topic = _make_topic(test_db, org)
        voter = _make_user(test_db, "hpe2_voter")
        make_org_membership(test_db, org_id=org.id, user_id=voter.id, role="member")
        author = _make_user(test_db, "hpe2_author")
        make_org_membership(test_db, org_id=org.id, user_id=author.id, role="admin")
        # Voting already over by clock: started 3 days ago, ended 1 day ago.
        vs = _now_naive() - timedelta(days=3)
        ve = _now_naive() - timedelta(days=1)
        proposal = _make_voting_proposal(
            test_db, author, org, topic=topic,
            voting_start=vs, voting_end=ve,
        )
        _opt_in(test_db, voter, "voting.halfway_you_havent_voted")
        test_db.commit()

        run_halfway_deadline_check(test_db)
        rows = _notifications_for(
            test_db, voter.id, "voting.halfway_you_havent_voted", proposal.id,
        )
        assert rows == [], (
            "proposal past voting_end must not fire halfway notifications"
        )

    def test_fires_after_clock_advances_past_50pct(self, test_db):
        """A proposal currently at 49% will not fire; same proposal
        evaluated with a later ``now`` (60% elapsed) does fire."""
        from digest_scheduler import run_halfway_deadline_check
        org = _make_org(test_db, "hpe3")
        topic = _make_topic(test_db, org)
        voter = _make_user(test_db, "hpe3_voter")
        make_org_membership(test_db, org_id=org.id, user_id=voter.id, role="member")
        author = _make_user(test_db, "hpe3_author")
        make_org_membership(test_db, org_id=org.id, user_id=author.id, role="admin")
        # voting window is 10 days. We pass synthetic `now` values to
        # exercise the threshold without time travel.
        vs = _now_naive() - timedelta(days=4)
        ve = vs + timedelta(days=10)
        proposal = _make_voting_proposal(
            test_db, author, org, topic=topic,
            voting_start=vs, voting_end=ve,
        )
        _opt_in(test_db, voter, "voting.halfway_you_havent_voted")
        test_db.commit()

        # synthetic_now1 = vs + 4.9 days -> 49% elapsed: no fire.
        synthetic_now1 = vs + timedelta(days=4, hours=21, minutes=36)
        run_halfway_deadline_check(test_db, now=synthetic_now1.replace(tzinfo=timezone.utc))
        rows = _notifications_for(
            test_db, voter.id, "voting.halfway_you_havent_voted", proposal.id,
        )
        assert rows == [], (
            f"49%-elapsed proposal must not fire; got {len(rows)} notifications"
        )

        # synthetic_now2 = vs + 6 days -> 60% elapsed: fires.
        synthetic_now2 = vs + timedelta(days=6)
        run_halfway_deadline_check(test_db, now=synthetic_now2.replace(tzinfo=timezone.utc))
        rows = _notifications_for(
            test_db, voter.id, "voting.halfway_you_havent_voted", proposal.id,
        )
        assert len(rows) == 1


class TestSchedulerIdempotency:
    """Running run_halfway_deadline_check twice in succession produces
    no duplicate notifications for any (user, proposal) pair. Covers
    both silent and havent_voted variants in one fixture."""

    def test_double_run_no_dupes(self, test_db):
        from digest_scheduler import run_halfway_deadline_check
        org = _make_org(test_db, "sidem")
        topic = _make_topic(test_db, org)
        delegate = _make_user(test_db, "sidem_delegate")
        delegator = _make_user(test_db, "sidem_delor")
        solo_voter = _make_user(test_db, "sidem_solo")
        for u in (delegate, delegator, solo_voter):
            make_org_membership(test_db, org_id=org.id, user_id=u.id, role="member")
        author = _make_user(test_db, "sidem_author")
        make_org_membership(test_db, org_id=org.id, user_id=author.id, role="admin")
        vs = _now_naive() - timedelta(days=2)
        ve = _now_naive() + timedelta(days=2)
        proposal = _make_voting_proposal(
            test_db, author, org, topic=topic,
            voting_start=vs, voting_end=ve,
        )
        _make_delegation(test_db, delegator, delegate, org, topic=topic)
        _opt_in(test_db, delegator, "voting.halfway_delegate_silent")
        _opt_in(test_db, solo_voter, "voting.halfway_you_havent_voted")
        test_db.commit()

        # Two consecutive runs.
        run_halfway_deadline_check(test_db)
        run_halfway_deadline_check(test_db)

        silent = _notifications_for(
            test_db, delegator.id, "voting.halfway_delegate_silent", proposal.id,
        )
        havent = _notifications_for(
            test_db, solo_voter.id, "voting.halfway_you_havent_voted", proposal.id,
        )
        assert len(silent) == 1, f"silent variant duplicated: {len(silent)}"
        assert len(havent) == 1, f"havent_voted variant duplicated: {len(havent)}"


# ---------------------------------------------------------------------------
# Bonus: D10 — public + private delegations both fire
# ---------------------------------------------------------------------------

class TestPrivateAndPublicDelegationsBothFire:
    """D10 — All five events fire regardless of delegation origin. A
    Delegation row with ``delegation_intent_id`` set (public-flow) and
    one without (follow-based private) both produce notifications.

    The schema's ``Delegation`` model has no ``delegation_intent_id``
    column directly (intent rows live in ``DelegationIntent``). For
    the conceptual case we verify that any Delegation row, regardless
    of how it was conceptually established, triggers the emit — i.e.
    we create two delegations with the same delegate from two distinct
    delegators and assert both delegators get notified.
    """

    def test_both_delegations_get_notified(self, client, test_db):
        org = _make_org(test_db, "pp1")
        topic = _make_topic(test_db, org)
        delegate = _make_user(test_db, "pp1_delegate")
        public_delegator = _make_user(test_db, "pp1_pub_delor")
        private_delegator = _make_user(test_db, "pp1_priv_delor")
        for u in (delegate, public_delegator, private_delegator):
            make_org_membership(test_db, org_id=org.id, user_id=u.id, role="member")
        author = _make_user(test_db, "pp1_author")
        make_org_membership(test_db, org_id=org.id, user_id=author.id, role="admin")
        proposal = _make_voting_proposal(test_db, author, org, topic=topic)
        # "Public-flow" delegation: just a Delegation row. Spec D10's
        # conceptual case — both kinds should fire.
        _make_delegation(test_db, public_delegator, delegate, org, topic=topic)
        # "Private/follow-based" delegation: another Delegation row from
        # a separate delegator. The notification path doesn't branch on
        # origin; both rows trigger emission.
        _make_delegation(test_db, private_delegator, delegate, org, topic=topic)
        _opt_in(test_db, public_delegator, "delegate.voted")
        _opt_in(test_db, private_delegator, "delegate.voted")
        test_db.commit()

        resp = client.post(
            f"/api/proposals/{proposal.id}/vote",
            json={"vote_value": "yes"},
            headers=_auth(delegate),
        )
        assert resp.status_code == 200, resp.text
        for delegator in (public_delegator, private_delegator):
            rows = _notifications_for(test_db, delegator.id, "delegate.voted", proposal.id)
            assert len(rows) == 1, (
                f"both delegation types must trigger emit; "
                f"{delegator.username} got {len(rows)} notifications"
            )
