"""W0 contracts: default isolation, seed privacy, strict stored/input ballots."""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest
import sqlalchemy as sa

from experimental_ballots import validate_ballot
from voting_methods import (
    DEFAULT_ENABLED_VOTING_METHODS, EXPERIMENTAL_VOTING_METHODS,
    LEGACY_VOTING_METHODS, available_voting_methods, candidate_priority,
    new_voting_rules, option_set_version, public_voting_rules, validate_voting_rules,
)


def test_default_and_release_lists_do_not_opt_in_experiments():
    assert DEFAULT_ENABLED_VOTING_METHODS == (
        "binary", "approval", "ranked_choice", "budget_allocation", "budget_project")
    assert available_voting_methods() == LEGACY_VOTING_METHODS + ("star",)
    assert not set(DEFAULT_ENABLED_VOTING_METHODS) & set(EXPERIMENTAL_VOTING_METHODS)


@pytest.mark.parametrize("method", EXPERIMENTAL_VOTING_METHODS)
def test_rules_commitment_privacy_and_fresh_draw(method):
    rules = new_voting_rules(method, "proposal")
    validate_voting_rules(rules, method, "proposal")
    assert rules["tie_commitment"] == hashlib.sha256(bytes.fromhex(rules["tie_seed"])).hexdigest()
    assert new_voting_rules(method, "proposal")["tie_seed"] != rules["tie_seed"]
    rules["future_private_field"] = "private"
    projected = public_voting_rules(rules)
    assert "tie_seed" not in projected and "future_private_field" not in projected
    assert rules["tie_seed"] not in json.dumps(projected)
    if projected["scale"]:
        projected["scale"].append("client mutation")
        assert "client mutation" not in rules["scale"]


@pytest.mark.parametrize("field,value", [
    ("rule_id", "future_v2"), ("method", "score"), ("proposal_id", "other"),
    ("tie_seed", "00"), ("tie_commitment", "0" * 64), ("scale", [0, 100]),
    ("omission_policy", "ignore"), ("priority_rule", "client_choice"),
])
def test_corrupt_rules_fail_closed(field, value):
    rules = new_voting_rules("star", "proposal")
    rules[field] = value
    with pytest.raises(ValueError):
        validate_voting_rules(rules, "star", "proposal")


def test_priority_is_reproducible_canonical_and_independent_of_late_option():
    rules = new_voting_rules("star", "proposal")
    old = {key: candidate_priority(rules, "proposal", key) for key in ("a", "b")}
    candidate_priority(rules, "proposal", "c")
    assert old == {key: candidate_priority(deepcopy(rules), "proposal", key) for key in old}
    assert candidate_priority(rules, "proposal", "AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA") == candidate_priority(
        rules, "proposal", "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
    with pytest.raises(ValueError):
        candidate_priority(rules, "other proposal", "a")
    assert option_set_version(["b", "a"]) == option_set_version(["a", "b"])
    assert option_set_version(["a", "b"]) != option_set_version(["a", "b", "c"])
    with pytest.raises(ValueError):
        option_set_version(["a", "a"])


@pytest.mark.parametrize("method,field,empty", [
    ("star", "scores", {}), ("score", "scores", {}),
    ("majority_judgment", "grades", {}), ("ranked_pairs", "rank_groups", []),
])
def test_neutral_abstain_and_omitted_options_are_distinct(method, field, empty):
    assert validate_ballot(method, {field: empty}, ["a"]) == {field: empty}
    assert validate_ballot(method, {"abstain": True}, ["a"]) == {"abstain": True}
    with pytest.raises(ValueError):
        validate_ballot(method, {"abstain": True, field: empty})
    with pytest.raises(ValueError):
        validate_ballot(method, {})


@pytest.mark.parametrize("rating", [True, False, "5", 5.0, None, -1, 6, [], {}])
@pytest.mark.parametrize("method,field", [("star", "scores"), ("score", "scores"), ("majority_judgment", "grades")])
def test_ratings_strict_integer_types(method, field, rating):
    with pytest.raises(ValueError):
        validate_ballot(method, {field: {"a": rating}})


@pytest.mark.parametrize("payload", [
    {"rank_groups": [["a"], ["a"]]}, {"rank_groups": [["a", "a"]]},
    {"rank_groups": [[]]}, {"rank_groups": ["a"]}, {"rank_groups": {}},
    {"rank_groups": [[1]]}, {"rank_groups": [[""]]},
    {"rank_groups": [], "scores": {}}, {"rank_groups": [], "abstain": 0},
])
def test_invalid_ranked_ballots(payload):
    with pytest.raises(ValueError):
        validate_ballot("ranked_pairs", payload)


def test_rank_group_normalization_bounds_foreign_ids_and_late_omission():
    assert validate_ballot("ranked_pairs", {"rank_groups": [["b", "a"]]}, ["a", "b", "c"]) == {"rank_groups": [["a", "b"]]}
    assert validate_ballot("star", {"scores": {"a": 5}}, ["a", "b"]) == {"scores": {"a": 5}}
    for method, payload in [
        ("star", {"scores": {"foreign": 5}}),
        ("ranked_pairs", {"rank_groups": [["foreign"]]}),
    ]:
        with pytest.raises(ValueError, match="no longer available"):
            validate_ballot(method, payload, ["a"])
    for method, payload in [
        ("star", {"scores": {str(i): 1 for i in range(121)}}),
        ("ranked_pairs", {"rank_groups": [[str(i)] for i in range(121)]}),
    ]:
        with pytest.raises(ValueError):
            validate_ballot(method, payload)
    with pytest.raises(ValueError):
        validate_ballot("binary", {"scores": {"a": 1}})
    with pytest.raises(ValueError):
        validate_ballot("star", {"scores": {}, "grades": {}})
    assert len(validate_ballot("star", {"scores": {str(i): 1 for i in range(120)}})["scores"]) == 120


def test_phase_109_migration_cycle(tmp_path):
    """Run real subprocess upgrades over a full schema representing prior head."""
    from database import Base
    import models  # noqa: F401
    url = "sqlite:///" + str(tmp_path / "migration.db")
    engine = sa.create_engine(url)
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.exec_driver_sql("ALTER TABLE proposals DROP COLUMN voting_rules")
        connection.exec_driver_sql("ALTER TABLE proposals DROP COLUMN final_method_result")
    backend = Path(__file__).resolve().parents[1]
    env = {**os.environ, "DATABASE_URL": url}

    def run(*args):
        result = subprocess.run([sys.executable, "-m", "alembic", *args], cwd=backend,
                                env=env, capture_output=True, text=True, timeout=120)
        assert result.returncode == 0, result.stdout + result.stderr

    try:
        run("stamp", "f8a9b0c1d2e3")
        for command, target, expected in [
            ("upgrade", "a109b0c1d2e3", True),
            ("downgrade", "f8a9b0c1d2e3", False),
            ("upgrade", "a109b0c1d2e3", True),
        ]:
            run(command, target)
            cols = {column["name"]: column for column in sa.inspect(engine).get_columns("proposals")}
            for name in ("voting_rules", "final_method_result"):
                assert (name in cols) is expected
                if expected:
                    assert cols[name]["nullable"] is True
    finally:
        engine.dispose()
