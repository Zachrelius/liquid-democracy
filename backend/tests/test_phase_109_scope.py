"""Real stored ballots preserve org/sub-org eligibility and parent weights."""
import pytest

import models
from delegation_engine import DelegationService, DelegationGraphStore
from tests.conftest import make_user, make_org_membership, make_sub_org_membership
from voting_methods import new_voting_rules


@pytest.mark.parametrize("method", ["star", "score", "ranked_pairs", "majority_judgment"])
@pytest.mark.parametrize("count_mode", ["weighted", "one_per_member"])
def test_suborg_members_only_and_cross_org_delegation_ignored(db, method, count_mode):
    parent = models.Organization(name="Parent", slug="scope-parent", settings={
        "weighted_voting": {"enabled": True, "unit_label": "shares"}})
    other = models.Organization(name="Other", slug="scope-other", settings={})
    db.add_all([parent, other]); db.flush()
    child = models.Organization(name="Subgroup", slug="scope-child", parent_org_id=parent.id)
    db.add(child); db.flush()
    owner, delegate, outsider, parent_only = [make_user(db, name) for name in
                                            ("scope-owner", "scope-delegate", "scope-outsider", "scope-parent-only")]
    for user, weight in ((owner, 7), (delegate, 2), (parent_only, 100)):
        membership = make_org_membership(db, org_id=parent.id, user_id=user.id)
        membership.voting_weight = weight
    make_org_membership(db, org_id=other.id, user_id=outsider.id)
    for user in (owner, delegate):
        make_sub_org_membership(db, sub_org_id=child.id, user_id=user.id)
    proposal = models.Proposal(title="Scoped", body="", author_id=owner.id,
                               org_id=parent.id, sub_org_id=child.id, voting_method=method,
                               status="voting", count_mode=count_mode)
    db.add(proposal); db.flush()
    proposal.voting_rules = new_voting_rules(method, proposal.id)
    options = [models.ProposalOption(proposal_id=proposal.id, label=name) for name in ("A", "B")]
    db.add_all(options); db.flush()
    a, b = (option.id for option in options)
    def payload(oid):
        return {"rank_groups": [[oid]]} if method == "ranked_pairs" else {("grades" if method == "majority_judgment" else "scores"): {oid: 5}}
    for user, oid in ((delegate, a), (outsider, b), (parent_only, b)):
        db.add(models.Vote(proposal_id=proposal.id, user_id=user.id, cast_by_id=user.id,
                           is_direct=True, ballot=payload(oid)))
    # This unrelated org's delegation must not carry the owner's seven shares.
    db.add(models.Delegation(org_id=other.id, delegator_id=owner.id,
                             delegate_id=outsider.id, chain_behavior="accept_sub"))
    db.flush()
    service = DelegationService(DelegationGraphStore())
    before = service.compute_tally(proposal, db)
    assert before.total_eligible == (9 if count_mode == "weighted" else 2)
    assert before.total_ballots_cast == (2 if count_mode == "weighted" else 1)
    assert before.winners == [a]
    db.add(models.Delegation(org_id=parent.id, sub_org_id=child.id, delegator_id=owner.id,
                             delegate_id=delegate.id, chain_behavior="accept_sub"))
    db.flush()
    after = service.compute_tally(proposal, db)
    assert after.total_ballots_cast == after.total_eligible
    assert after.eligible_headcount == after.participating_headcount == 2
    if method == "ranked_pairs":
        assert after.method_result["pairwise"][a][b] == after.total_eligible
        assert after.method_result["pairwise"][b][a] == 0
    elif method == "majority_judgment":
        assert after.method_result["grade_histograms"][a] == [0, 0, 0, 0, 0, after.total_eligible]
        assert after.method_result["grade_histograms"][b] == [after.total_eligible, 0, 0, 0, 0, 0]
    else:
        assert after.method_result["scores"] == {a: 5 * after.total_eligible, b: 0}
