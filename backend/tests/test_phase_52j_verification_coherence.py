"""Phase 52j — verification UI coherence + org-level residency model.

Six clusters covered:
  J1 — org-level residency model + scope predicate
  J2 — backend ladder unchanged (stale value still resolves)
  J3 — org-level proposal verification policy
  J4 — name-match first-token fix + "either" mode
  J5 — copy fixes (covered as FE-source-review in closeout)
  J6 — display_name_for propagation (covered in adjacent tests)
"""
from __future__ import annotations

import os

import pytest
from fastapi import HTTPException
from sqlalchemy.orm import Session

import models
import verification


# ===========================================================================
# Test fixtures
# ===========================================================================


def _shim_org(settings: dict | None = None, *, jurisdiction=None):
    """Minimal Organization shim. Avoids DB churn for pure-logic
    predicate tests."""
    class _Shim:
        pass
    o = _Shim()
    o.id = "org-test"
    o.settings = settings or {}
    return o


def _shim_user(
    *,
    jurisdiction: str | None = None,
    locality_hash: str | None = None,
    legal_first: str | None = None,
    legal_last: str | None = None,
    legal_full: str | None = None,
):
    class _Shim:
        pass
    u = _Shim()
    u.verification_state = "address_on_id"
    u.verification_jurisdiction = jurisdiction
    u.verification_locality_hash = locality_hash
    u.legal_first_name = legal_first
    u.legal_last_name = legal_last
    u.legal_full_name = legal_full
    u.display_name = "User"
    return u


@pytest.fixture(autouse=True)
def _pepper():
    os.environ.setdefault("VERIFICATION_HASH_PEPPER", "test-pepper-52j")
    yield


# ===========================================================================
# J1 — residency scope predicate
# ===========================================================================


class TestResidencyScopePredicate:
    def test_empty_scope_is_true_for_anyone(self):
        org = _shim_org({})
        u = _shim_user()
        assert verification.user_satisfies_residency_scope(u, org) is True

    def test_state_only_entry_matches_jurisdiction(self):
        org = _shim_org({
            verification.SETTING_RESIDENCY_SCOPE: [{"state": "MA"}],
        })
        u_match = _shim_user(jurisdiction="MA")
        u_mismatch = _shim_user(jurisdiction="NH")
        assert verification.user_satisfies_residency_scope(u_match, org) is True
        assert verification.user_satisfies_residency_scope(u_mismatch, org) is False

    def test_state_match_is_case_insensitive(self):
        org = _shim_org({
            verification.SETTING_RESIDENCY_SCOPE: [{"state": "ma"}],
        })
        u = _shim_user(jurisdiction="MA")
        assert verification.user_satisfies_residency_scope(u, org) is True

    def test_or_match_across_entries(self):
        org = _shim_org({
            verification.SETTING_RESIDENCY_SCOPE: [
                {"state": "MA"},
                {"state": "NH"},
            ],
        })
        u = _shim_user(jurisdiction="NH")
        assert verification.user_satisfies_residency_scope(u, org) is True

    def test_no_user_jurisdiction_fails_set_scope(self):
        org = _shim_org({
            verification.SETTING_RESIDENCY_SCOPE: [{"state": "MA"}],
        })
        u = _shim_user(jurisdiction=None)
        assert verification.user_satisfies_residency_scope(u, org) is False

    def test_city_entry_hashes_with_state(self):
        """Phase 52i invariant preserved — state is IN the hash so
        cross-state Springfields don't collide."""
        import verification_hashing
        h_ma = verification_hashing.compute_locality_hash("Springfield", "MA")
        h_il = verification_hashing.compute_locality_hash("Springfield", "IL")
        assert h_ma and h_il and h_ma != h_il

        org = _shim_org({
            verification.SETTING_RESIDENCY_SCOPE: [
                {"state": "MA", "city": "Springfield"},
            ],
        })
        u_ma = _shim_user(locality_hash=h_ma)
        u_il = _shim_user(locality_hash=h_il)
        assert verification.user_satisfies_residency_scope(u_ma, org) is True
        assert verification.user_satisfies_residency_scope(u_il, org) is False

    def test_city_entry_requires_user_locality_hash(self):
        org = _shim_org({
            verification.SETTING_RESIDENCY_SCOPE: [
                {"state": "MA", "city": "Somerville"},
            ],
        })
        u = _shim_user(locality_hash=None, jurisdiction="MA")
        # State doesn't satisfy a city entry — independent levels.
        assert verification.user_satisfies_residency_scope(u, org) is False

    def test_state_entry_not_satisfied_by_city_alone(self):
        """52i lock: no subsumption. A user with a city hash matching
        a different scope (or no scope city at all) but the right
        state matches the state entry, NOT the city entry."""
        import verification_hashing
        h_somerville = verification_hashing.compute_locality_hash("Somerville", "MA")
        org = _shim_org({
            verification.SETTING_RESIDENCY_SCOPE: [
                {"state": "MA", "city": "Cambridge"},  # only Cambridge allowed
            ],
        })
        u = _shim_user(locality_hash=h_somerville, jurisdiction="MA")
        # Cambridge entry: user is in Somerville → mismatch.
        # No state-only entry; user's MA jurisdiction doesn't help.
        assert verification.user_satisfies_residency_scope(u, org) is False

    def test_mixed_state_and_city_entries_or(self):
        """A user can match a state-only entry OR a city entry.
        Independent levels, OR across entries."""
        import verification_hashing
        h_somerville = verification_hashing.compute_locality_hash("Somerville", "MA")
        org = _shim_org({
            verification.SETTING_RESIDENCY_SCOPE: [
                {"state": "MA", "city": "Somerville"},
                {"state": "NH"},  # also any NH resident
            ],
        })
        u_nh = _shim_user(jurisdiction="NH")
        u_somerville = _shim_user(locality_hash=h_somerville)
        assert verification.user_satisfies_residency_scope(u_nh, org) is True
        assert verification.user_satisfies_residency_scope(u_somerville, org) is True

    def test_malformed_scope_treated_as_empty(self):
        org = _shim_org({verification.SETTING_RESIDENCY_SCOPE: "not-a-list"})
        u = _shim_user()
        assert verification.user_satisfies_residency_scope(u, org) is True
        org = _shim_org({verification.SETTING_RESIDENCY_SCOPE: [123, None]})
        assert verification.user_satisfies_residency_scope(u, org) is True

    def test_entries_without_state_dropped(self):
        org = _shim_org({
            verification.SETTING_RESIDENCY_SCOPE: [
                {"city": "Boston"},  # no state — dropped
            ],
        })
        u = _shim_user(jurisdiction="MA")
        assert verification.user_satisfies_residency_scope(u, org) is True  # empty after drop


# ===========================================================================
# J1 — per-gate "require residency" booleans
# ===========================================================================


class TestRequireResidencyBooleans:
    def test_membership_require_residency_default_false(self):
        org = _shim_org({})
        assert verification.membership_requires_residency(org) is False

    def test_membership_require_residency_on(self):
        org = _shim_org({
            verification.SETTING_MEMBERSHIP_REQUIRE_RESIDENCY: True,
        })
        assert verification.membership_requires_residency(org) is True

    def test_role_require_residency_default_false(self):
        org = _shim_org({})
        assert verification.role_requires_residency(org, "steward") is False

    def test_role_require_residency_per_role(self):
        org = _shim_org({
            verification.SETTING_ROLE_REQUIRE_RESIDENCY: {
                "steward": True, "admin": False,
            },
        })
        assert verification.role_requires_residency(org, "steward") is True
        assert verification.role_requires_residency(org, "admin") is False
        assert verification.role_requires_residency(org, "moderator") is False


class TestMembershipResidencyCheck:
    def test_no_require_no_raise(self):
        org = _shim_org({
            verification.SETTING_RESIDENCY_SCOPE: [{"state": "MA"}],
        })
        u = _shim_user(jurisdiction="NH")
        # Even with a non-matching user, the check is a no-op when
        # require_residency is off.
        verification.check_membership_residency_for_join(u, org)

    def test_require_and_match_passes(self):
        org = _shim_org({
            verification.SETTING_RESIDENCY_SCOPE: [{"state": "MA"}],
            verification.SETTING_MEMBERSHIP_REQUIRE_RESIDENCY: True,
        })
        u = _shim_user(jurisdiction="MA")
        verification.check_membership_residency_for_join(u, org)

    def test_require_and_mismatch_raises_structured_403(self):
        org = _shim_org({
            verification.SETTING_RESIDENCY_SCOPE: [{"state": "MA"}],
            verification.SETTING_MEMBERSHIP_REQUIRE_RESIDENCY: True,
        })
        u = _shim_user(jurisdiction="NH")
        with pytest.raises(HTTPException) as exc:
            verification.check_membership_residency_for_join(u, org)
        assert exc.value.status_code == 403
        d = exc.value.detail
        assert d["error"] == "verification_required"
        assert d["scope"] == "residency_scope"
        assert d["residency_scope"] == [{"state": "MA", "city": None}]


class TestRoleResidencyCheck:
    def test_no_require_no_raise(self):
        org = _shim_org({
            verification.SETTING_RESIDENCY_SCOPE: [{"state": "MA"}],
        })
        u = _shim_user(jurisdiction="NH")
        verification.check_role_residency_for_grant(u, org, "steward")

    def test_require_and_mismatch_raises(self):
        org = _shim_org({
            verification.SETTING_RESIDENCY_SCOPE: [{"state": "MA"}],
            verification.SETTING_ROLE_REQUIRE_RESIDENCY: {"steward": True},
        })
        u = _shim_user(jurisdiction="NH")
        with pytest.raises(HTTPException) as exc:
            verification.check_role_residency_for_grant(u, org, "steward")
        assert exc.value.status_code == 403


# ===========================================================================
# J2 — backend ladder unchanged (Z-locked: relabel only)
# ===========================================================================


class TestBackendLadderIntact:
    def test_identity_unique_still_in_valid_states(self):
        # The dead-rung removal is deferred; the value must still
        # resolve cleanly for any org that stored it pre-J2.
        assert "identity_unique" in verification.VALID_STATES
        assert "residency_verified" in verification.VALID_STATES

    def test_order_unchanged(self):
        assert verification.ORDER == [
            "email_only", "identity", "identity_unique",
            "address_on_id", "residency_verified",
        ]

    def test_stale_stored_value_resolves_sanely(self):
        """An org somehow carrying ``identity_unique`` as a stored
        floor should still rank/subsume sanely — the FE just won't
        let the admin re-select the value."""
        org = _shim_org({
            verification.SETTING_MEMBERSHIP_FLOOR: "identity_unique",
        })
        floor, jurisdiction = verification.get_org_verification_floor(
            org, "membership",
        )
        assert floor == "identity_unique"

    def test_rank_not_renumbered(self):
        # If anyone removes the dead rung from ORDER, this fails so
        # the lesson is documented.
        assert verification.rank("identity_unique") == 2
        assert verification.rank("address_on_id") == 3
        assert verification.rank("residency_verified") == 4


# ===========================================================================
# J3 — proposal policy
# ===========================================================================


class TestProposalPolicy:
    def test_default_is_author(self):
        org = _shim_org({})
        assert verification.get_org_proposal_policy(org) == "author"

    def test_explicit_author(self):
        org = _shim_org({
            verification.SETTING_PROPOSAL_POLICY: "author",
        })
        assert verification.get_org_proposal_policy(org) == "author"

    def test_always(self):
        org = _shim_org({
            verification.SETTING_PROPOSAL_POLICY: "always",
        })
        assert verification.get_org_proposal_policy(org) == "always"

    def test_never(self):
        org = _shim_org({
            verification.SETTING_PROPOSAL_POLICY: "never",
        })
        assert verification.get_org_proposal_policy(org) == "never"

    def test_unknown_value_falls_back_to_author(self):
        org = _shim_org({
            verification.SETTING_PROPOSAL_POLICY: "bogus",
        })
        assert verification.get_org_proposal_policy(org) == "author"


class TestEffectiveProposalFloor:
    def _proposal(self, *, floor=None, jurisdiction=None):
        class _P:
            pass
        p = _P()
        p.verification_floor = floor
        p.verification_jurisdiction = jurisdiction
        return p

    def test_author_uses_proposal_floor(self):
        org = _shim_org({verification.SETTING_PROPOSAL_POLICY: "author"})
        p = self._proposal(floor="identity")
        assert verification.effective_proposal_floor(p, org) == ("identity", None)

    def test_author_with_no_floor_is_none(self):
        org = _shim_org({verification.SETTING_PROPOSAL_POLICY: "author"})
        p = self._proposal(floor=None)
        assert verification.effective_proposal_floor(p, org) == (None, None)

    def test_always_uses_org_floor(self):
        org = _shim_org({
            verification.SETTING_PROPOSAL_POLICY: "always",
            verification.SETTING_PROPOSAL_FLOOR: "identity",
        })
        p = self._proposal(floor=None)
        assert verification.effective_proposal_floor(p, org) == ("identity", None)

    def test_always_overrides_proposal_floor(self):
        org = _shim_org({
            verification.SETTING_PROPOSAL_POLICY: "always",
            verification.SETTING_PROPOSAL_FLOOR: "address_on_id",
            verification.SETTING_PROPOSAL_JURISDICTION: "MA",
        })
        # Proposal has its own (different) floor — under `always`,
        # the org floor wins.
        p = self._proposal(floor="identity")
        assert verification.effective_proposal_floor(p, org) == ("address_on_id", "MA")

    def test_always_with_no_org_floor_is_none(self):
        org = _shim_org({
            verification.SETTING_PROPOSAL_POLICY: "always",
        })
        p = self._proposal(floor="identity")
        assert verification.effective_proposal_floor(p, org) == (None, None)

    def test_never_ignores_proposal_floor(self):
        org = _shim_org({verification.SETTING_PROPOSAL_POLICY: "never"})
        p = self._proposal(floor="identity")
        assert verification.effective_proposal_floor(p, org) == (None, None)

    def test_check_vote_floor_uses_policy(self):
        """Under `always`, a user who doesn't satisfy the org floor
        gets a 403 even if the proposal has no per-proposal floor."""
        org = _shim_org({
            verification.SETTING_PROPOSAL_POLICY: "always",
            verification.SETTING_PROPOSAL_FLOOR: "identity",
        })
        p = self._proposal(floor=None)
        u = _shim_user()
        u.verification_state = "email_only"
        with pytest.raises(HTTPException) as exc:
            verification.check_vote_floor_for_proposal(u, p, org)
        assert exc.value.status_code == 403

    def test_check_vote_floor_never_ignores_stored_floor(self):
        """Under `never`, a stored proposal floor is ignored at
        vote time."""
        org = _shim_org({verification.SETTING_PROPOSAL_POLICY: "never"})
        p = self._proposal(floor="identity")
        u = _shim_user()
        u.verification_state = "email_only"
        # Should NOT raise.
        verification.check_vote_floor_for_proposal(u, p, org)


# ===========================================================================
# J4 — name-match first-token fix + "either" mode + full relaxed
# ===========================================================================


class TestNameMatchFirstTokenFix:
    """The observation-#5 regression case: legal_first "Zachary
    Michael" + display "Zachary" must MATCH under `first` mode."""

    def test_observation_5_regression_case_first_mode_matches(self):
        org = _shim_org({
            verification.SETTING_REQUIRE_NAME_MATCH: "first",
        })
        u = _shim_user(legal_first="Zachary Michael")
        assert verification.display_name_matches_legal("Zachary", u, org) is True

    def test_first_mode_token_match_against_legal_first_token(self):
        org = _shim_org({
            verification.SETTING_REQUIRE_NAME_MATCH: "first",
        })
        u = _shim_user(legal_first="Zachary Michael")
        # display has more tokens; first matches first → True
        assert verification.display_name_matches_legal("Zachary Smith", u, org) is True
        # different first token → False
        assert verification.display_name_matches_legal("Robert Smith", u, org) is False

    def test_last_mode_symmetric(self):
        org = _shim_org({
            verification.SETTING_REQUIRE_NAME_MATCH: "last",
        })
        u = _shim_user(legal_last="Smith Jones")
        # legal_last's LAST token is "jones" — display ending in
        # "Jones" matches; ending in "Smith" doesn't (the first
        # token of legal_last).
        assert verification.display_name_matches_legal("Alice Jones", u, org) is True
        assert verification.display_name_matches_legal("Alice Smith", u, org) is False


class TestEitherMode:
    def test_either_matches_if_first_matches(self):
        org = _shim_org({
            verification.SETTING_REQUIRE_NAME_MATCH: "either",
        })
        u = _shim_user(legal_first="Alice", legal_last="Robertson")
        assert verification.display_name_matches_legal("Alice Cooper", u, org) is True

    def test_either_matches_if_last_matches(self):
        org = _shim_org({
            verification.SETTING_REQUIRE_NAME_MATCH: "either",
        })
        u = _shim_user(legal_first="Alice", legal_last="Robertson")
        assert verification.display_name_matches_legal("Bob Robertson", u, org) is True

    def test_either_fails_if_neither_matches(self):
        org = _shim_org({
            verification.SETTING_REQUIRE_NAME_MATCH: "either",
        })
        u = _shim_user(legal_first="Alice", legal_last="Robertson")
        assert verification.display_name_matches_legal("Bob Smith", u, org) is False


class TestFullModeRelaxed:
    def test_relaxed_full_match_middle_name_tolerant(self):
        """The Z-default: legal "Zachary Michael Smith" + display
        "Zachary Smith" → match (middle-name dropped)."""
        org = _shim_org({
            verification.SETTING_REQUIRE_NAME_MATCH: "full",
        })
        u = _shim_user(
            legal_first="Zachary Michael",
            legal_last="Smith",
            legal_full="Zachary Michael Smith",
        )
        assert verification.display_name_matches_legal("Zachary Smith", u, org) is True

    def test_full_falls_back_to_whole_string_when_only_full_set(self):
        # When only legal_full is set (no first/last), fall back to
        # the pre-J4 exact whole-string equality.
        org = _shim_org({
            verification.SETTING_REQUIRE_NAME_MATCH: "full",
        })
        u = _shim_user(legal_full="Alice Q Robertson")
        assert verification.display_name_matches_legal("Alice Q Robertson", u, org) is True
        assert verification.display_name_matches_legal("Alice Robertson", u, org) is False

    def test_relaxed_full_fails_on_mismatched_first(self):
        org = _shim_org({
            verification.SETTING_REQUIRE_NAME_MATCH: "full",
        })
        u = _shim_user(legal_first="Alice", legal_last="Smith")
        assert verification.display_name_matches_legal("Bob Smith", u, org) is False

    def test_relaxed_full_requires_two_tokens(self):
        org = _shim_org({
            verification.SETTING_REQUIRE_NAME_MATCH: "full",
        })
        u = _shim_user(legal_first="Alice", legal_last="Smith")
        # Display with only one token can't satisfy first+last.
        assert verification.display_name_matches_legal("Alice", u, org) is False


class TestNameMatchModeRegistry:
    def test_either_in_valid_modes(self):
        assert "either" in verification._VALID_NAME_MATCH_MODES

    def test_get_org_name_match_mode_accepts_either(self):
        org = _shim_org({
            verification.SETTING_REQUIRE_NAME_MATCH: "either",
        })
        assert verification.get_org_name_match_mode(org) == "either"


# ===========================================================================
# Additive-layer parity — the load-bearing "no settings = no behavior"
# ===========================================================================


class TestAdditiveLayerParity:
    def test_no_settings_no_residency_gate(self):
        org = _shim_org({})
        u = _shim_user()
        # No residency scope → predicate True.
        assert verification.user_satisfies_residency_scope(u, org) is True
        # No require_residency → check is no-op (no raise).
        verification.check_membership_residency_for_join(u, org)
        verification.check_role_residency_for_grant(u, org, "steward")

    def test_no_settings_proposal_policy_is_author(self):
        org = _shim_org({})
        assert verification.get_org_proposal_policy(org) == "author"

    def test_no_settings_name_match_off(self):
        org = _shim_org({})
        assert verification.get_org_name_match_mode(org) == "off"
