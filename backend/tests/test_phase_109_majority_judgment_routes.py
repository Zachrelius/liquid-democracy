"""Majority Judgment's real storage, grade semantics, privacy and lifecycle."""
import pytest

import models
import voting_methods
from experimental_voting import initialize_rules
from tests.test_phase_109_star_routes import star
from tests.test_ranked_choice_voting import (test_db, client, _auth_header,
                                            _create_user, _create_membership)


@pytest.fixture
def majority_judgment(test_db, star, monkeypatch):
    user, org, proposal, options = star
    monkeypatch.setattr(voting_methods, "RELEASED_EXPERIMENTAL_METHODS", ("star", "majority_judgment"))
    org.settings = {**org.settings, "allowed_voting_methods": ["binary", "star", "majority_judgment"]}
    proposal.voting_method = "majority_judgment"
    initialize_rules(proposal)
    test_db.commit()
    return user, org, proposal, options


@pytest.mark.parametrize("org_close", [False, True])
def test_mj_repeated_lower_median_and_frozen_original_distributions(client, test_db, majority_judgment, org_close):
    user, org, proposal, options = majority_judgment
    actors = [user, _create_user(test_db, "mj-second"), _create_user(test_db, "mj-third")]
    for actor in actors[1:]:
        _create_membership(test_db, org, actor)
    test_db.commit()
    a, b, c = [option.id for option in options]
    path = f"/api/proposals/{proposal.id}"
    headers = _auth_header(user)
    for actor, grades in zip(actors, ({a: 2}, {a: 2, b: 2}, {a: 5, b: 2})):
        response = client.post(path + "/vote", headers=_auth_header(actor), json={"grades": grades})
        assert response.status_code == 200, response.text
    live = client.get(path + "/results", headers=headers).json()["method_result"]
    assert live["winner"] == a
    assert live["majority_grades"] == {a: 2, b: 2, c: 0}
    assert live["grade_histograms"] == {
        a: ["0", "0", "2", "0", "0", "1"],
        b: ["1", "0", "2", "0", "0", "0"],
        c: ["3", "0", "0", "0", "0", "0"],
    }
    assert not live["priority_used"]
    assert live["tie_trace"]
    assert live["grade_labels"] == ["Reject", "Poor", "Acceptable", "Good", "Very good", "Excellent"]
    assert not ({"scores", "runoff", "finalists"} & live.keys())
    assert "tie_seed" not in live
    close = f"/api/orgs/{org.slug}/proposals/{proposal.id}/advance" if org_close else path + "/advance"
    assert client.post(close, headers=headers, json={}).status_code == 200
    final = client.get(path + "/results", headers=headers).json()
    assert final["method_result"]["finalized"]
    assert final["method_result"]["tie_seed"]
    assert final["method_result"]["grade_histograms"] == live["grade_histograms"]
    options[0].label = "Later label"
    test_db.query(models.Vote).filter_by(proposal_id=proposal.id).delete()
    test_db.commit()
    assert client.get(path + "/results", headers=headers).json() == final
    assert client.post(path + "/vote", headers=headers, json={"abstain": True}).status_code == 400
    assert client.delete(path + "/vote", headers=headers).status_code == 400
    assert client.post(path + "/options", headers=headers, json={"label": "Closed"}).status_code == 400


def test_mj_even_weight_lower_grade_and_private_graph(client, test_db, majority_judgment):
    user, org, proposal, options = majority_judgment
    other = _create_user(test_db, "mj-weighted-other")
    _create_membership(test_db, org, other)
    for actor in (user, other):
        test_db.query(models.OrgMembership).filter_by(org_id=org.id, user_id=actor.id).one().voting_weight = 10**12
    org.settings = {**org.settings, "weighted_voting": {"enabled": True, "unit_label": "shares"}}
    test_db.commit()
    a, b, _ = [option.id for option in options]
    path = f"/api/proposals/{proposal.id}"
    for actor, grade in ((user, 2), (other, 5)):
        assert client.post(path + "/vote", headers=_auth_header(actor), json={"grades": {a: grade, b: 3}}).status_code == 200
    result = client.get(path + "/results", headers=_auth_header(user)).json()["method_result"]
    assert result["winner"] == b
    assert result["majority_grades"][a] == 2
    assert result["majority_grades"][b] == 3
    assert result["preference_weight"] == "2000000000000"
    graph = client.get(path + "/vote-graph", headers=_auth_header(user))
    assert graph.status_code == 200, graph.text
    ballots = [node["ballot"] for node in graph.json()["nodes"] if node["ballot"] is not None]
    assert len(ballots) == 1 and ballots[0]["grades"] == {a: 2, b: 3}


@pytest.mark.parametrize("route", ["/api/proposals", "/api/orgs/star-test/proposals"])
def test_majority_judgment_create_import_and_disable_contract(client, test_db, majority_judgment, route):
    user, org, _, _ = majority_judgment
    headers = _auth_header(user)
    payload = {"title": "Majority Judgment creation", "body": "Synthetic", "voting_method": "majority_judgment",
               "options": [{"label": "A"}, {"label": "B"}]}
    response = client.post(route, headers=headers, json=payload)
    if route == "/api/proposals":
        assert response.status_code == 400
        return
    assert response.status_code == 201, response.text
    assert response.json()["voting_rules"]["rule_id"] == "majority_judgment_lower_median_v1"
    assert "tie_seed" not in response.json()["voting_rules"]
    preview = client.post(f"/api/orgs/{org.slug}/proposals/import-preview", headers=headers, json=payload)
    assert preview.status_code == 200, preview.text
    org.settings = {**org.settings, "allowed_voting_methods": ["binary", "star"]}
    test_db.commit()
    assert client.post(route, headers=headers, json=payload).status_code == 400
    assert client.post(f"/api/orgs/{org.slug}/proposals/import-preview", headers=headers, json=payload).status_code == 422


def test_majority_judgment_late_option_removal_preserves_neutral_ballot(client, test_db, majority_judgment):
    user, org, proposal, options = majority_judgment
    path = f"/api/proposals/{proposal.id}"
    headers = _auth_header(user)
    assert client.post(path + "/vote", headers=headers, json={"grades": {options[0].id: 4}}).status_code == 200
    response = client.post(path + "/options", headers=headers, json={"label": "Late majority_judgment option"})
    assert response.status_code == 201, response.text
    late = response.json()["id"]
    result = client.get(path + "/results", headers=headers).json()["method_result"]
    assert result["grade_histograms"][late] == ["1", "0", "0", "0", "0", "0"]
    assert late not in test_db.query(models.Vote).filter_by(proposal_id=proposal.id).one().ballot["grades"]
    assert client.post(path + "/vote", headers=headers, json={"grades": {late: 5}}).status_code == 200
    assert client.delete(path + "/options/" + late, headers=headers).status_code == 204
    assert test_db.query(models.Vote).filter_by(proposal_id=proposal.id).one().ballot == {"grades": {}}
    result = client.get(path + "/results", headers=headers).json()["method_result"]
    assert result["no_result_reason"] == "all_bottom_ratings"
    assert result["total_ballots_cast"] == "1"


def test_majority_judgment_hidden_early_ballot_and_disabled_existing_method(client, test_db, majority_judgment):
    user, org, proposal, options = majority_judgment
    proposal.status = "deliberation"
    proposal.allow_pre_voting = True
    proposal.show_votes_during_deliberation = False
    org.settings = {**org.settings, "allowed_voting_methods": ["binary"]}
    test_db.commit()
    path = f"/api/proposals/{proposal.id}"
    headers = _auth_header(user)
    assert client.post(path + "/vote", headers=headers, json={"grades": {}}).status_code == 200
    own = client.get(path + "/my-vote", headers=headers).json()
    assert own["is_direct"] is True and own["grades"] == {}
    for surface in ("results", "vote-graph", "trajectory"):
        assert client.get(path + "/" + surface, headers=headers).status_code == 404
    assert client.post(path + "/vote", headers=headers, json={"abstain": True}).status_code == 200
    assert client.get(path + "/my-vote", headers=headers).json()["abstain"]


@pytest.mark.parametrize("payload", [{"scores": {}}, {"rank_groups": []}, {"grades": {}, "abstain": True}])
def test_majority_judgment_incompatible_ballots_rejected(client, majority_judgment, payload):
    user, _, proposal, _ = majority_judgment
    assert client.post(f"/api/proposals/{proposal.id}/vote", headers=_auth_header(user), json=payload).status_code in (400, 422)


def test_majority_judgment_foreign_option_and_unauthorized_result(client, test_db, majority_judgment):
    from uuid import uuid4
    user, _, proposal, _ = majority_judgment
    path = f"/api/proposals/{proposal.id}"
    assert client.post(path + "/vote", headers=_auth_header(user), json={"grades": {str(uuid4()): 5}}).status_code == 400
    outsider = _create_user(test_db, "majority_judgment-outsider")
    test_db.commit()
    assert client.get(path + "/results", headers=_auth_header(outsider)).status_code == 404
    assert client.post(path + "/vote", headers=_auth_header(outsider), json={"grades": {}}).status_code == 403


def test_majority_judgment_profile_summary_has_no_raw_private_ballot(client, majority_judgment):
    user, _, proposal, options = majority_judgment
    assert client.post(f"/api/proposals/{proposal.id}/vote", headers=_auth_header(user),
                       json={"grades": {options[0].id: 5}}).status_code == 200
    own = client.get(f"/api/users/{user.id}/votes", headers=_auth_header(user)).json()
    assert own[0]["voting_method"] == "majority_judgment"
    assert own[0]["ballot_summary"] == "Grades submitted"
    assert "ballot" not in own[0]
    assert client.get(f"/api/users/{user.id}/votes").json() == []


@pytest.mark.parametrize("neutral", [False, True])
def test_majority_judgment_feed_keeps_neutral_participation_and_no_public_individual_ballot(client, test_db, majority_judgment, neutral):
    user, org, proposal, options = majority_judgment
    org.activity_visibility = "public"
    test_db.commit()
    ratings = {} if neutral else {options[0].id: 5}
    headers = _auth_header(user)
    assert client.post(f"/api/proposals/{proposal.id}/vote", headers=headers, json={"grades": ratings}).status_code == 200
    response = client.get(f"/api/orgs/{org.slug}/proposal-feed", headers=headers)
    assert response.status_code == 200, response.text
    item = next(row for row in response.json()["items"] if row["proposal"]["id"] == proposal.id)
    assert item["viewer_vote"]["has_effective_vote"] is True
    assert item["viewer_vote"]["is_direct"] is True
    assert item["viewer_vote"]["selection_count"] == len(ratings)
    public = client.get(f"/api/orgs/{org.slug}/public/proposal-feed")
    assert public.status_code == 200
    assert all(row["viewer_vote"] is None for row in public.json()["items"])
