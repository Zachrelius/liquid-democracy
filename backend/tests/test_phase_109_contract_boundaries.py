"""Public contracts remain closed until each complete method is released."""
import uuid

import pytest
from pydantic import ValidationError

import schemas
from delegation_engine import ProposalContext, compute_tally_pure


@pytest.mark.parametrize("field", ["scores", "grades"])
@pytest.mark.parametrize("bad", [True, False, "3", 3.0, 1.5, -1, 6, None])
def test_ratings_reject_coercion(field, bad):
    with pytest.raises(ValidationError):
        schemas.VoteCast(**{field: {str(uuid.uuid4()): bad}})


@pytest.mark.parametrize("expression", [
    {"scores": {}, "grades": {}}, {"scores": {}, "vote_value": "yes"},
    {"scores": {}, "abstain": True}, {"abstain": "true"},
    {"abstain": 1}, {"rank_groups": [[]]},
    {"scores": {"not-a-uuid": 5}},
])
def test_incompatible_or_invalid_ballots(expression):
    with pytest.raises(ValidationError):
        schemas.VoteCast(**expression)


def test_duplicate_across_rank_groups_rejected():
    oid = str(uuid.uuid4())
    with pytest.raises(ValidationError):
        schemas.VoteCast(rank_groups=[[oid], [oid]])


@pytest.mark.parametrize("expression", [{"scores": {}}, {"grades": {}},
                                           {"rank_groups": []}, {"abstain": True}])
def test_neutral_expression_and_explicit_abstention_preserved(expression):
    ballot = schemas.VoteCast(**expression)
    for key, value in expression.items():
        assert getattr(ballot, key) == value


def test_unknown_method_does_not_count_as_binary():
    context = ProposalContext([], {}, {}, {}, voting_method="unimplemented")
    with pytest.raises(ValueError, match="No tally handler"):
        compute_tally_pure([], context)


def test_fresh_org_default_methods_remain_legacy():
    from routes.organizations import DEFAULT_ORG_SETTINGS
    assert DEFAULT_ORG_SETTINGS["allowed_voting_methods"] == [
        "binary", "approval", "ranked_choice", "budget_allocation", "budget_project",
    ]
