"""Phase 21 — delegate action notifications + preference presets (wave 1).

This file holds the wave-1 (foundation) tests for Phase 21:

  * Registry assertions for the 5 new event keys (B1).
  * Signal-level classification check for every event in EVENT_REGISTRY (B6).
  * Preset-stamping helpers (``apply_preset_to_preferences``,
    ``detect_matching_preset``) — happy paths for each preset, always-on
    exemption, at-most-one-email-channel invariant, round-trip detection.
  * Endpoint tests for ``GET /api/notifications/registry`` (signal_level
    surfaced) and ``GET /api/notifications/preferences`` (matching_preset
    surfaced) and ``POST /api/notifications/preferences/apply_preset``.

Wave 2 (separate dispatch) covers:
  * Vote-cast / vote-change / rationale-post emission in routes/votes.py.
  * Halfway-deadline scheduler-driven events.
  * No-self-notify dedup tests.
  * Transaction-rollback safety on notification error.

Don't extend this file with wave-2 content — it lives in a sibling file
(``test_phase_21_wave_2_*`` or extension to this file in the wave-2
commit).
"""
from __future__ import annotations

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
    # always_on
    "invitation.accepted": "always_on",
    "delegate.application_decided": "always_on",
    "delegate_application_approved": "always_on",
    "follow.approved": "always_on",
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
