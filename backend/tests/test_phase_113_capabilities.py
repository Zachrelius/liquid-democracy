"""W0 gates: unreleased isolation, strict seats and settings provenance."""
from types import SimpleNamespace
import pytest
import voting_capabilities as cap


def org(settings=None, parent=None):
    return SimpleNamespace(settings=settings or {}, parent_org=parent, parent_org_id="parent" if parent else None)


def test_absent_settings_keep_legacy_aggregations_and_no_multiwinner():
    value = cap.effective_voting_capabilities(org())
    assert value["allowed_budget_aggregations"] == ["median", "trimmed_mean"]
    assert value["allowed_multiwinner_methods"] == []
    assert value["voting_capability_sources"]["allowed_budget_aggregations"] == "legacy_default"


@pytest.mark.parametrize("value", [True, False, "2", 2.0, None, 0, -1, 121])
def test_strict_winner_bound(value):
    with pytest.raises(ValueError): cap.validate_winner_count(value)


@pytest.mark.parametrize("key,value", [("allowed_budget_aggregations", []),
    ("allowed_budget_aggregations", ["unknown"]), ("allowed_budget_aggregations", ["median", "median"]),
    ("allowed_multiwinner_methods", ["allocated_score"]), ("allowed_multiwinner_methods", True)])
def test_invalid_stored_settings_fail_loudly(key, value):
    with pytest.raises(ValueError): cap.effective_voting_capabilities(org({key:value}))


def test_parent_restrictions_and_inheritance(monkeypatch):
    monkeypatch.setattr(cap, "RELEASED_MULTIWINNER_METHODS", frozenset(cap.MULTIWINNER_METHODS))
    parent = org({"allowed_voting_methods":["score"], "allowed_multiwinner_methods":["score"], "allowed_budget_aggregations":["trimmed_mean"]})
    child = org(parent=parent)
    value = cap.effective_voting_capabilities(child)
    assert value["allowed_multiwinner_methods"] == ["score"]
    assert value["allowed_budget_aggregations"] == ["trimmed_mean"]
    assert set(value["voting_capability_sources"].values()) == {"parent"}
    child.settings = {"allowed_voting_methods":["score", "star"], "allowed_multiwinner_methods":["score", "star"], "allowed_budget_aggregations":["median", "trimmed_mean"]}
    assert cap.effective_voting_capabilities(child)["allowed_multiwinner_methods"] == ["score"]
    parent.settings["allowed_voting_methods"] = ["binary"]
    assert cap.effective_voting_capabilities(child)["allowed_multiwinner_methods"] == []
    assert child.settings["allowed_multiwinner_methods"] == ["score", "star"]


def test_parent_cannot_be_broadened_by_missing_setting_or_incompatible_override():
    parent = org({"allowed_budget_aggregations":["median"]})
    assert cap.effective_voting_capabilities(org(parent=parent))["allowed_budget_aggregations"] == ["median"]
    child = org({"allowed_budget_aggregations":["trimmed_mean"]}, parent)
    assert cap.effective_voting_capabilities(child)["allowed_budget_aggregations"] == ["median"]
    with pytest.raises(ValueError):
        cap.validate_settings_patch(child, {"allowed_budget_aggregations":["trimmed_mean"]})
    with pytest.raises(ValueError):
        cap.effective_voting_capabilities(SimpleNamespace(settings={}, parent_org_id="missing", parent_org=None))


@pytest.mark.parametrize("method", cap.MULTIWINNER_METHODS)
def test_planned_registry_entries_cannot_enable_unreleased_features(method, monkeypatch):
    monkeypatch.setattr(cap, "RELEASED_MULTIWINNER_METHODS", frozenset())
    scope = org({"allowed_voting_methods":[method], "allowed_multiwinner_methods":[method]})
    cap.require_new_method_choice(scope, method, 1)
    with pytest.raises(ValueError): cap.require_new_method_choice(scope, method, 2)


def test_allocated_score_is_independent_and_never_substitutes_at_one():
    scope = org({"allowed_voting_methods":["allocated_score", "score", "star"]})
    for count in (1, 2):
        with pytest.raises(ValueError): cap.require_new_method_choice(scope, "allocated_score", count)
    assert cap.PLANNED_CAPABILITIES["allocated_score"].proportional is True
    assert all(not cap.PLANNED_CAPABILITIES[m].proportional for m in cap.MULTIWINNER_METHODS)
