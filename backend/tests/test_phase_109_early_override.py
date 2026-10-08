"""Early direct rating ballots override delegation even when results are hidden."""
import pytest

import models
from tests.test_ranked_choice_voting import (
    test_db, client, _auth_header, _create_user, _create_membership,
)
from tests.test_phase_109_star_routes import star


@pytest.mark.parametrize("neutral", [True, False])
def test_early_direct_ballot_overrides_delegate_without_public_results(
    client, test_db, star, neutral,
):
    voter, org, proposal, options = star
    delegate = _create_user(test_db, "early-delegate")
    _create_membership(test_db, org, delegate, role="member")
    proposal.status = "deliberation"
    proposal.allow_pre_voting = True
    proposal.show_votes_during_deliberation = False
    test_db.add(models.Delegation(
        org_id=org.id, delegator_id=voter.id, delegate_id=delegate.id,
        chain_behavior="accept_sub",
    ))
    test_db.commit()
    path = f"/api/proposals/{proposal.id}"
    headers = _auth_header(voter)
    delegate_scores = {options[0].id: 1, options[1].id: 5}
    response = client.post(path + "/vote", headers=_auth_header(delegate),
                           json={"scores": delegate_scores})
    assert response.status_code == 200, response.text
    before = client.get(path + "/my-vote", headers=headers)
    assert before.status_code == 200, before.text
    assert before.json()["is_direct"] is False
    assert before.json()["scores"] == delegate_scores

    own_scores = {} if neutral else {options[0].id: 5, options[1].id: 1}
    response = client.post(path + "/vote", headers=headers, json={"scores": own_scores})
    assert response.status_code == 200, response.text
    stored = test_db.query(models.Vote).filter_by(
        proposal_id=proposal.id, user_id=voter.id,
    ).one()
    assert stored.is_direct and stored.ballot == {"scores": own_scores}
    # This 404 is expected and must not prevent a client refreshing my-vote.
    assert client.get(path + "/results", headers=headers).status_code == 404
    after = client.get(path + "/my-vote", headers=headers)
    assert after.status_code == 200, after.text
    assert after.json()["is_direct"] is True
    assert after.json()["scores"] == own_scores
    assert after.json()["abstain"] is False

    removed = client.delete(path + "/vote", headers=headers)
    assert removed.status_code == 204, removed.text
    restored = client.get(path + "/my-vote", headers=headers)
    assert restored.status_code == 200, restored.text
    assert restored.json()["is_direct"] is False
    assert restored.json()["scores"] == delegate_scores
