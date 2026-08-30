"""Phase 76c — residency country capture + country-level residency gating.

Covers:
  * verification_provider._extract_country + map_decision_to_state country key.
  * verification._residency_scope_entries normalization with country.
  * verification.user_satisfies_residency_scope country matching (+ OR with
    existing state/city entries, precedence when both present).
  * _residency_payload carries country.
"""
from __future__ import annotations

from types import SimpleNamespace

import verification
import verification_provider as vp


# --------------------------------------------------------------------------
# Provider extraction
# --------------------------------------------------------------------------

def _passed_decision(*, region=None, country=None):
    pa = {}
    if region is not None:
        pa["region"] = region
    if country is not None:
        pa["country"] = country
    return {
        "status": "Approved",
        "id_verifications": [{"status": "Approved", "parsed_address": pa}],
        "session_id": "sess-1",
    }


def _passed_payload(*, region=None, country=None):
    return {
        "status": "Approved",
        "features": ["ID_VERIFICATION", "LIVENESS", "FACE_MATCH"],
        "decision": {
            **_passed_decision(region=region, country=country),
            "liveness_checks": [{"status": "Approved"}],
            "face_matches": [{"status": "Approved"}],
        },
    }


def test_extract_country_from_parsed_address():
    assert vp._extract_country(_passed_decision(country="US")) == "US"
    assert vp._extract_country(_passed_decision(country="ca")) == "CA"  # upcased


def test_extract_country_rejects_non_two_alpha():
    assert vp._extract_country(_passed_decision(country="USA")) is None  # 3-char
    assert vp._extract_country(_passed_decision(country="1")) is None
    assert vp._extract_country(_passed_decision(country="U1")) is None
    assert vp._extract_country(_passed_decision()) is None  # absent


def test_extract_country_legacy_paths():
    assert vp._extract_country({"id_verification": {"country": "GB"}}) == "GB"
    assert vp._extract_country(
        {"id_verification": {"address": {"country": "FR"}}}
    ) == "FR"
    assert vp._extract_country({"country": "DE"}) == "DE"


def test_mapper_includes_country_with_us_jurisdiction():
    mapped = vp.map_decision_to_state(
        _passed_payload(region="Massachusetts", country="US")
    )
    assert mapped["verification_state"] == verification.ADDRESS_ON_ID
    assert mapped["verification_jurisdiction"] == "MA"
    assert mapped["verification_country"] == "US"


def test_mapper_country_without_us_region_stays_identity():
    """A non-US address parses a country but no recognized US jurisdiction:
    state stays IDENTITY (the US-centric ladder doesn't escalate) but the
    country is still captured for country-scope gates."""
    mapped = vp.map_decision_to_state(
        _passed_payload(region="Ontario", country="CA")
    )
    assert mapped["verification_state"] == verification.IDENTITY
    assert mapped["verification_jurisdiction"] is None
    assert mapped["verification_country"] == "CA"


def test_mapper_failed_decision_country_none():
    mapped = vp.map_decision_to_state({"status": "Declined"})
    assert mapped["verification_state"] == verification.EMAIL_ONLY
    assert mapped["verification_country"] is None


# --------------------------------------------------------------------------
# Scope normalization
# --------------------------------------------------------------------------

def _org(scope):
    return SimpleNamespace(settings={"verification_residency_scope": scope})


def test_scope_entries_normalize_country():
    entries = verification._residency_scope_entries(
        _org([{"country": "ca"}, {"state": "ma", "city": "Boston"}])
    )
    assert entries[0] == {"country": "CA", "state": None, "city": None}
    assert entries[1] == {"country": None, "state": "MA", "city": "Boston"}


def test_scope_entry_dropped_without_state_or_country():
    entries = verification._residency_scope_entries(
        _org([{"city": "Nowhere"}, {"country": "US"}])
    )
    # city-only entry dropped; country entry kept
    assert entries == [{"country": "US", "state": None, "city": None}]


def test_scope_city_without_state_dropped():
    entries = verification._residency_scope_entries(
        _org([{"country": "CA", "city": "Toronto"}])
    )
    # city needs a state (US-only hashing) → city dropped, country kept
    assert entries == [{"country": "CA", "state": None, "city": None}]


# --------------------------------------------------------------------------
# Predicate
# --------------------------------------------------------------------------

def _user(*, jurisdiction=None, country=None, locality_hash=None):
    return SimpleNamespace(
        verification_jurisdiction=jurisdiction,
        verification_country=country,
        verification_locality_hash=locality_hash,
    )


def test_country_entry_matches_user_country():
    org = _org([{"country": "CA"}])
    assert verification.user_satisfies_residency_scope(_user(country="CA"), org)
    assert verification.user_satisfies_residency_scope(_user(country="ca"), org)
    assert not verification.user_satisfies_residency_scope(_user(country="US"), org)
    assert not verification.user_satisfies_residency_scope(_user(country=None), org)


def test_country_or_state_entries():
    """OR semantics across a country entry and a US state entry."""
    org = _org([{"country": "CA"}, {"state": "MA"}])
    assert verification.user_satisfies_residency_scope(_user(country="CA"), org)
    assert verification.user_satisfies_residency_scope(_user(jurisdiction="MA"), org)
    assert not verification.user_satisfies_residency_scope(
        _user(jurisdiction="NH", country="US"), org
    )


def test_us_country_gate_satisfied_by_backfilled_state_user():
    """A US-state-verified member (backfilled verification_country='US')
    satisfies a country-level US gate."""
    org = _org([{"country": "US"}])
    assert verification.user_satisfies_residency_scope(
        _user(jurisdiction="MA", country="US"), org
    )


def test_state_takes_precedence_when_both_present():
    """An entry carrying both country and state is matched as a state entry
    (the more specific level)."""
    org = _org([{"country": "US", "state": "MA"}])
    # jurisdiction MA matches; a US user in NH does not
    assert verification.user_satisfies_residency_scope(
        _user(jurisdiction="MA", country="US"), org
    )
    assert not verification.user_satisfies_residency_scope(
        _user(jurisdiction="NH", country="US"), org
    )


def test_empty_scope_is_parity_true():
    assert verification.user_satisfies_residency_scope(_user(), _org([]))
    assert verification.user_satisfies_residency_scope(
        _user(), SimpleNamespace(settings={})
    )


def test_residency_payload_includes_country():
    org = _org([{"country": "CA"}, {"state": "MA", "city": "Boston"}])
    payload = verification._residency_payload(org)
    assert payload["scope"] == "residency_scope"
    assert payload["residency_scope"][0] == {"country": "CA", "state": None, "city": None}
    assert payload["residency_scope"][1] == {
        "country": None, "state": "MA", "city": "Boston",
    }
