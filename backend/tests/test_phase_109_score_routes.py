"""Score's real storage/API boundary, separate from STAR's runoff fixtures."""
import pytest

import models
import voting_methods
from experimental_voting import initialize_rules
from tests.test_phase_109_star_routes import star
from tests.test_ranked_choice_voting import (test_db, client, _auth_header,
                                            _create_user, _create_membership)


@pytest.fixture
def score(test_db, star, monkeypatch):
    user, org, proposal, options = star
    monkeypatch.setattr(voting_methods, "RELEASED_EXPERIMENTAL_METHODS", ("star", "score"))
    org.settings = {**org.settings, "allowed_voting_methods": ["binary", "star", "score"]}
    proposal.voting_method = "score"
    initialize_rules(proposal)
    test_db.commit()
    return user, org, proposal, options


@pytest.mark.parametrize("org_close", [False, True])
def test_score_weighted_sum_not_runoff_and_frozen_close(client, test_db, score, org_close):
    user, org, proposal, options = score
    other = _create_user(test_db, "score-other")
    _create_membership(test_db, org, other)
    for uid, weight in ((user.id, 3), (other.id, 2)):
        test_db.query(models.OrgMembership).filter_by(org_id=org.id, user_id=uid).one().voting_weight = weight
    org.settings = {**org.settings, "weighted_voting": {"enabled": True, "unit_label": "shares"}}
    test_db.commit()
    a, b, c = [o.id for o in options]
    path = f"/api/proposals/{proposal.id}"
    for actor, ratings in ((user, {a: 5, b: 4}), (other, {b: 4, c: 5})):
        response = client.post(path + "/vote", headers=_auth_header(actor), json={"scores": ratings})
        assert response.status_code == 200, response.text
    live = client.get(path + "/results", headers=_auth_header(user)).json()["method_result"]
    assert live["winner"] == b
    assert live["scores"] == {a: "15", b: "20", c: "10"}
    assert live["preference_weight"] == "5"
    assert not ({"runoff", "finalists", "five_star_counts", "equal_preference"} & live.keys())
    assert "tie_seed" not in live
    close = f"/api/orgs/{org.slug}/proposals/{proposal.id}/advance" if org_close else path + "/advance"
    assert client.post(close, headers=_auth_header(user), json={}).status_code == 200
    final = client.get(path + "/results", headers=_auth_header(user)).json()
    assert final["method_result"]["finalized"]
    assert final["method_result"]["rules"]["rule_id"] == "score_0_5_sum_v1"
    assert final["method_result"]["tie_seed"]
    options[1].label = "Post-close label"
    test_db.query(models.Vote).filter_by(proposal_id=proposal.id).delete()
    test_db.query(models.OrgMembership).filter_by(org_id=org.id).update({"voting_weight": 1})
    test_db.commit()
    assert client.get(path + "/results", headers=_auth_header(user)).json() == final
    assert client.post(path + "/vote", headers=_auth_header(user), json={"abstain": True}).status_code == 400
    assert client.post(path + "/options", headers=_auth_header(user), json={"label": "Closed"}).status_code == 400


@pytest.mark.parametrize("route", ["/api/proposals", "/api/orgs/star-test/proposals"])
def test_score_create_import_and_disable_contract(client, test_db, score, route):
    user, org, _, _ = score
    headers = _auth_header(user)
    payload = {"title": "Score creation", "body": "Synthetic", "voting_method": "score",
               "options": [{"label": "A"}, {"label": "B"}]}
    response = client.post(route, headers=headers, json=payload)
    if route == "/api/proposals":
        assert response.status_code == 400
        return
    assert response.status_code == 201, response.text
    assert response.json()["voting_rules"]["rule_id"] == "score_0_5_sum_v1"
    assert "tie_seed" not in response.json()["voting_rules"]
    preview = client.post(f"/api/orgs/{org.slug}/proposals/import-preview", headers=headers, json=payload)
    assert preview.status_code == 200, preview.text
    org.settings = {**org.settings, "allowed_voting_methods": ["binary", "star"]}
    test_db.commit()
    assert client.post(route, headers=headers, json=payload).status_code == 400
    assert client.post(f"/api/orgs/{org.slug}/proposals/import-preview", headers=headers, json=payload).status_code == 422


def test_score_late_option_removal_preserves_neutral_ballot(client, test_db, score):
    user, org, proposal, options = score
    path = f"/api/proposals/{proposal.id}"
    headers = _auth_header(user)
    assert client.post(path + "/vote", headers=headers, json={"scores": {options[0].id: 4}}).status_code == 200
    response = client.post(path + "/options", headers=headers, json={"label": "Late score option"})
    assert response.status_code == 201, response.text
    late = response.json()["id"]
    result = client.get(path + "/results", headers=headers).json()["method_result"]
    assert result["scores"][late] == "0"
    assert late not in test_db.query(models.Vote).filter_by(proposal_id=proposal.id).one().ballot["scores"]
    assert client.post(path + "/vote", headers=headers, json={"scores": {late: 5}}).status_code == 200
    assert client.delete(path + "/options/" + late, headers=headers).status_code == 204
    assert test_db.query(models.Vote).filter_by(proposal_id=proposal.id).one().ballot == {"scores": {}}
    result = client.get(path + "/results", headers=headers).json()["method_result"]
    assert result["no_result_reason"] == "all_bottom_ratings"
    assert result["total_ballots_cast"] == "1"


def test_score_hidden_early_ballot_and_disabled_existing_method(client, test_db, score):
    user, org, proposal, options = score
    proposal.status = "deliberation"
    proposal.allow_pre_voting = True
    proposal.show_votes_during_deliberation = False
    org.settings = {**org.settings, "allowed_voting_methods": ["binary"]}
    test_db.commit()
    path = f"/api/proposals/{proposal.id}"
    headers = _auth_header(user)
    assert client.post(path + "/vote", headers=headers, json={"scores": {}}).status_code == 200
    own = client.get(path + "/my-vote", headers=headers).json()
    assert own["is_direct"] is True and own["scores"] == {}
    for surface in ("results", "vote-graph", "trajectory"):
        assert client.get(path + "/" + surface, headers=headers).status_code == 404
    assert client.post(path + "/vote", headers=headers, json={"abstain": True}).status_code == 200
    assert client.get(path + "/my-vote", headers=headers).json()["abstain"]


@pytest.mark.parametrize("payload", [{"grades": {}}, {"rank_groups": []}, {"scores": {}, "abstain": True}])
def test_score_incompatible_ballots_rejected(client, score, payload):
    user, _, proposal, _ = score
    assert client.post(f"/api/proposals/{proposal.id}/vote", headers=_auth_header(user), json=payload).status_code in (400, 422)


def test_score_foreign_option_and_unauthorized_result(client, test_db, score):
    from uuid import uuid4
    user, _, proposal, _ = score
    path = f"/api/proposals/{proposal.id}"
    assert client.post(path + "/vote", headers=_auth_header(user), json={"scores": {str(uuid4()): 5}}).status_code == 400
    outsider = _create_user(test_db, "score-outsider")
    test_db.commit()
    assert client.get(path + "/results", headers=_auth_header(outsider)).status_code == 404
    assert client.post(path + "/vote", headers=_auth_header(outsider), json={"scores": {}}).status_code == 403


def test_score_profile_summary_has_no_raw_private_ballot(client, score):
    user, _, proposal, options = score
    assert client.post(f"/api/proposals/{proposal.id}/vote", headers=_auth_header(user),
                       json={"scores": {options[0].id: 5}}).status_code == 200
    own = client.get(f"/api/users/{user.id}/votes", headers=_auth_header(user)).json()
    assert own[0]["voting_method"] == "score"
    assert own[0]["ballot_summary"] == "Score ratings submitted"
    assert "ballot" not in own[0]
    assert client.get(f"/api/users/{user.id}/votes").json() == []


@pytest.mark.parametrize("neutral", [False, True])
def test_score_feed_keeps_neutral_participation_and_no_public_individual_ballot(client, test_db, score, neutral):
    user, org, proposal, options = score
    org.activity_visibility = "public"
    test_db.commit()
    ratings = {} if neutral else {options[0].id: 5}
    headers = _auth_header(user)
    assert client.post(f"/api/proposals/{proposal.id}/vote", headers=headers, json={"scores": ratings}).status_code == 200
    response = client.get(f"/api/orgs/{org.slug}/proposal-feed", headers=headers)
    assert response.status_code == 200, response.text
    item = next(row for row in response.json()["items"] if row["proposal"]["id"] == proposal.id)
    assert item["viewer_vote"]["has_effective_vote"] is True
    assert item["viewer_vote"]["is_direct"] is True
    assert item["viewer_vote"]["selection_count"] == len(ratings)
    public = client.get(f"/api/orgs/{org.slug}/public/proposal-feed")
    assert public.status_code == 200
    assert all(row["viewer_vote"] is None for row in public.json()["items"])
