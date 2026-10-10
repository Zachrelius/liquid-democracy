"""Phase 113 creation contracts. Planned capabilities are never release flags.

Stored proposals retain their frozen rules. This module authorizes NEW choices;
read/count paths must not retroactively apply an organization restriction.
"""
from dataclasses import dataclass

def _resolve(org, key, default):
    for current in _ancestors(org):
        value = (current.settings or {}).get(key)
        if value is not None:
            return value
    return default

MULTIWINNER_METHODS = ("score", "star", "majority_judgment", "ranked_pairs")
BUDGET_AGGREGATIONS = ("median", "trimmed_mean")
MAX_WINNERS = 120
# Advance only after the corresponding complete lifecycle/rendered gate passes.
RELEASED_MULTIWINNER_METHODS = frozenset({"score", "star", "majority_judgment"})
ALLOCATED_SCORE_RELEASED = False

@dataclass(frozen=True)
class MethodCapability:
    method: str
    rule_id: str
    minimum_winners: int
    proportional: bool = False

PLANNED_CAPABILITIES = {
    "score": MethodCapability("score", "score_0_5_top_n_v1", 2),
    "star": MethodCapability("star", "star_bloc_0_5_v1", 2),
    "majority_judgment": MethodCapability("majority_judgment", "majority_judgment_lower_median_top_n_v1", 2),
    "ranked_pairs": MethodCapability("ranked_pairs", "ranked_pairs_margins_top_n_v1", 2),
    "allocated_score": MethodCapability("allocated_score", "allocated_score_0_5_hare_v1", 2, True),
}


def validate_winner_count(value):
    if type(value) is not int or not 1 <= value <= MAX_WINNERS:
        raise ValueError(f"Winner count must be an integer from 1 to {MAX_WINNERS}")
    return value


def validate_choice_list(value, supported, key, *, nonempty=False):
    if (not isinstance(value, list) or any(type(v) is not str or v not in supported for v in value)
            or len(value) != len(set(value)) or (nonempty and not value)):
        raise ValueError(f"{key} must contain {'at least one ' if nonempty else ''}distinct supported choices")
    return [v for v in supported if v in value]


def _ancestors(org):
    seen = set()
    while org is not None:
        identity = id(org)
        if identity in seen or len(seen) >= 5:
            raise RuntimeError("Invalid organization inheritance chain")
        seen.add(identity)
        yield org
        if getattr(org, "parent_org_id", None) and getattr(org, "parent_org", None) is None:
            raise ValueError("Organization parent must be loaded for capability resolution")
        org = getattr(org, "parent_org", None)


def _source(org, key):
    for depth, current in enumerate(_ancestors(org)):
        if (current.settings or {}).get(key) is not None:
            return "self" if depth == 0 else "parent"
    return "legacy_default"


def effective_voting_capabilities(org):
    """Resolve effective preferences and provenance without mutating settings.

    New capabilities cannot broaden ANY parent's method/capability restriction.
    Existing single-winner override semantics remain intact for compatibility.
    Malformed new stored values fail loudly; absence has explicit legacy defaults.
    """
    methods = _resolve(org, "allowed_voting_methods", ["binary"])
    if not isinstance(methods, list) or any(type(v) is not str for v in methods):
        raise ValueError("Invalid allowed_voting_methods")
    preferred = validate_choice_list(_resolve(org, "allowed_multiwinner_methods", []),
        MULTIWINNER_METHODS, "allowed_multiwinner_methods")
    allowed_multi = set(preferred) & set(methods)
    for current in _ancestors(org):
        allowed_multi.intersection_update(_resolve(current, "allowed_voting_methods", ["binary"]))
        allowed_multi.intersection_update(validate_choice_list(
            _resolve(current, "allowed_multiwinner_methods", []),
            MULTIWINNER_METHODS, "allowed_multiwinner_methods"))
    aggregations = validate_choice_list(_resolve(org, "allowed_budget_aggregations", list(BUDGET_AGGREGATIONS)),
        BUDGET_AGGREGATIONS, "allowed_budget_aggregations", nonempty=True)
    for current in _ancestors(org):
        parent_choices = validate_choice_list(_resolve(current, "allowed_budget_aggregations", list(BUDGET_AGGREGATIONS)),
            BUDGET_AGGREGATIONS, "allowed_budget_aggregations", nonempty=True)
        overlap = [v for v in aggregations if v in parent_choices]
        # A later parent narrowing must not make the child unreadable.
        # Its new choices are bounded by the parent, while stored votes retain rules.
        aggregations = overlap or parent_choices
    return {
        "allowed_voting_methods": list(methods),
        "allowed_multiwinner_methods": [v for v in MULTIWINNER_METHODS if v in allowed_multi and v in RELEASED_MULTIWINNER_METHODS],
        "allowed_budget_aggregations": aggregations,
        "voting_capability_sources": {key: _source(org, key) for key in
            ("allowed_multiwinner_methods", "allowed_budget_aggregations")},
    }


def require_new_method_choice(org, method, winner_count):
    validate_winner_count(winner_count)
    effective = effective_voting_capabilities(org)
    if org is None or method not in effective["allowed_voting_methods"]:
        raise ValueError("Voting method is not enabled for this organization scope")
    if method == "allocated_score":
        if not ALLOCATED_SCORE_RELEASED or winner_count < 2:
            raise ValueError("Allocated Score is available only for multiple winners after its release gate")
        if any(method not in _resolve(current, "allowed_voting_methods", ["binary"]) for current in _ancestors(org)):
            raise ValueError("Allocated Score is restricted by a parent organization")
    elif method in MULTIWINNER_METHODS and winner_count > 1:
        if method not in effective["allowed_multiwinner_methods"]:
            raise ValueError("Multiple winners are not enabled for this method in this organization scope")
    elif method not in MULTIWINNER_METHODS:
        raise ValueError("No experimental capability for this voting method")
    return effective


def validate_settings_patch(org, patch):
    """Validate touched preferences only, preserving absent legacy defaults."""
    from types import SimpleNamespace
    merged = {**(org.settings or {}), **patch}
    for key, supported in (("allowed_budget_aggregations", BUDGET_AGGREGATIONS),
                           ("allowed_multiwinner_methods", tuple(RELEASED_MULTIWINNER_METHODS))):
        if key not in patch:
            continue
        if patch[key] is None and getattr(org, "parent_org_id", None):
            merged.pop(key, None)
        else:
            merged[key] = validate_choice_list(patch[key], supported, key, nonempty=key == "allowed_budget_aggregations")
    if getattr(org, "parent_org_id", None) and patch.get("allowed_voting_methods", "absent") is None:
        merged.pop("allowed_voting_methods", None)
    if getattr(org, "parent_org_id", None) and patch.get("allowed_budget_aggregations") is not None:
        parent_choices = effective_voting_capabilities(org.parent_org)["allowed_budget_aggregations"]
        if not any(v in parent_choices for v in merged["allowed_budget_aggregations"]):
            raise ValueError("Budget aggregation choices conflict with the parent restriction")
    projected = SimpleNamespace(settings=merged, parent_org=getattr(org, "parent_org", None),
        parent_org_id=getattr(org, "parent_org_id", None))
    effective_voting_capabilities(projected)
    return merged


def resolve_budget_creation(config, org, *, existing=None):
    """Resolve NEW allocation choice, or grandfather the same stored choice.

    An omitted aggregation chooses the permitted first value. Trusted historical
    reads never call this helper. Clones/imports do not receive existing config.
    """
    if config is None or config.get("mode") != "allocation":
        return config
    choices = effective_voting_capabilities(org)["allowed_budget_aggregations"]
    explicit = config.get("aggregation")
    choice = explicit if explicit is not None else choices[0]
    unchanged = existing is not None and choice == existing.get("aggregation", "median")
    if choice not in BUDGET_AGGREGATIONS or (choice not in choices and not unchanged):
        raise ValueError("Budget aggregation is not permitted by this organization scope")
    return {**config, "aggregation": choice}
