"""Phase 109 method registry and server-owned, versioned draw rules.

Planned methods are deliberately separate from released methods and defaults.
Never serialize stored voting_rules directly: use public_voting_rules.
"""
from copy import deepcopy
import hashlib
import json
import re
import secrets
from uuid import UUID

LEGACY_VOTING_METHODS = (
    "binary", "approval", "ranked_choice", "budget_allocation", "budget_project",
)
EXPERIMENTAL_VOTING_METHODS = ("star", "score", "ranked_pairs", "majority_judgment")
DEFAULT_ENABLED_VOTING_METHODS = LEGACY_VOTING_METHODS
RELEASED_EXPERIMENTAL_METHODS: tuple[str, ...] = ()
GRADE_LABELS = ("Reject", "Poor", "Acceptable", "Good", "Very good", "Excellent")
RULE_IDS = {
    "star": "star_0_5_v1",
    "score": "score_0_5_sum_v1",
    "ranked_pairs": "ranked_pairs_margins_v1",
    "majority_judgment": "majority_judgment_lower_median_v1",
}


def available_voting_methods() -> tuple[str, ...]:
    return LEGACY_VOTING_METHODS + RELEASED_EXPERIMENTAL_METHODS


def _canonical_id(value: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 200:
        raise ValueError("Invalid identifier")
    try:
        return str(UUID(value))
    except ValueError:
        return value  # Symbolic identifiers are supported by pure counter fixtures.


def _encode(values: list[str]) -> bytes:
    return json.dumps(values, ensure_ascii=True, separators=(",", ":")).encode("ascii")


def _metadata(method: str, proposal_id: str) -> dict:
    if method not in RULE_IDS:
        raise ValueError("Method does not use experimental rules")
    return {
        "method": method,
        "rule_id": RULE_IDS[method],
        "proposal_id": _canonical_id(proposal_id),
        "scale": (list(GRADE_LABELS) if method == "majority_judgment" else
                  None if method == "ranked_pairs" else [0, 1, 2, 3, 4, 5]),
        "omission_policy": ("unranked_last" if method == "ranked_pairs" else
                            "reject" if method == "majority_judgment" else "zero"),
        "priority_rule": "sha256_tuple_v1",
    }


def new_voting_rules(method: str, proposal_id: str) -> dict:
    """Only creation/draft transition calls this; reads/retries never redraw."""
    rules = _metadata(method, proposal_id)
    seed = secrets.token_hex(32)
    rules.update(tie_seed=seed, tie_commitment=hashlib.sha256(bytes.fromhex(seed)).hexdigest())
    return rules


def validate_voting_rules(rules: dict, method: str, proposal_id: str) -> None:
    if not isinstance(rules, dict):
        raise ValueError("Missing experimental voting rules")
    expected = _metadata(method, proposal_id)
    if any(rules.get(key) != value for key, value in expected.items()):
        raise ValueError("Incompatible experimental voting rules")
    seed = rules.get("tie_seed")
    if not isinstance(seed, str) or re.fullmatch(r"[0-9a-f]{64}", seed) is None:
        raise ValueError("Invalid tie seed")
    commitment = hashlib.sha256(bytes.fromhex(seed)).hexdigest()
    if rules.get("tie_commitment") != commitment:
        raise ValueError("Tie commitment does not match seed")


def public_voting_rules(rules: dict | None) -> dict | None:
    """Allowlist projection; NEVER reveals seed, even after close.

    The finalized aggregate record is the sole seed-reveal surface, protected
    by result visibility. Rules metadata can be visible while results are not.
    """
    if rules is None:
        return None
    validate_voting_rules(rules, rules.get("method"), rules.get("proposal_id"))
    keys = (*_metadata(rules["method"], rules["proposal_id"]), "tie_commitment")
    return {key: deepcopy(rules[key]) for key in keys}


def candidate_priority(rules: dict, proposal_id: str, option_id: str) -> tuple[str, str]:
    validate_voting_rules(rules, rules.get("method"), proposal_id)
    canonical_id = _canonical_id(option_id)
    encoded = _encode(["candidate_priority_v1", rules["tie_seed"],
                       _canonical_id(proposal_id), canonical_id])
    return hashlib.sha256(encoded).hexdigest(), canonical_id


def option_set_version(option_ids) -> str:
    ids = [_canonical_id(value) for value in option_ids]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate option IDs")
    return hashlib.sha256(_encode(["option_set_v1", *sorted(ids)])).hexdigest()
