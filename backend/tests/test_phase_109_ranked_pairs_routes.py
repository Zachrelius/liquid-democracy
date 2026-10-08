"""Ranked Pairs API semantics, real JSON ballots and private history."""
import pytest

import models
import voting_methods
from experimental_voting import initialize_rules
from tests.test_phase_109_star_routes import star
from tests.test_ranked_choice_voting import (test_db, client, _auth_header,
                                            _create_user, _create_membership)


@pytest.fixture
def ranked_pairs(test_db, star, monkeypatch):
    user, org, proposal, options = star
    monkeypatch.setattr(voting_methods, "RELEASED_EXPERIMENTAL_METHODS", ("star", "score", "ranked_pairs"))
    org.settings = {**org.settings, "allowed_voting_methods": ["binary", "ranked_pairs"]}
    proposal.voting_method = "ranked_pairs"
    initialize_rules(proposal)
    test_db.commit()
    return user, org, proposal, options


@pytest.mark.parametrize("org_close", [False, True])
def test_ranked_pairs_cycle_locks_and_final_freeze(client, test_db, ranked_pairs, org_close):
    user, org, proposal, options = ranked_pairs
    a, b, c = [option.id for option in options]
    actors = [user, _create_user(test_db, "rp-second"), _create_user(test_db, "rp-third")]
    for actor in actors[1:]:
        _create_membership(test_db, org, actor)
    for actor, weight in zip(actors, [3, 2, 2]):
        test_db.query(models.OrgMembership).filter_by(org_id=org.id, user_id=actor.id).one().voting_weight = weight
    org.settings = {**org.settings, "weighted_voting": {"enabled": True, "unit_label": "shares"}}
    test_db.commit()
    path = f"/api/proposals/{proposal.id}"
    for actor, order in zip(actors, [[a,b,c], [b,c,a], [c,a,b]]):
        response = client.post(path + "/vote", headers=_auth_header(actor), json={"rank_groups": [[oid] for oid in order]})
        assert response.status_code == 200, response.text
    result = client.get(path + "/results", headers=_auth_header(user)).json()["method_result"]
    assert result["winner"] == a
    assert result["pairwise"][a][b] == "5" and result["pairwise"][b][a] == "2"
    assert result["pairwise"][b][c] == "5" and result["pairwise"][c][b] == "2"
    assert result["pairwise"][c][a] == "4" and result["pairwise"][a][c] == "3"
    assert {(edge["winner"], edge["loser"]) for edge in result["locked_edges"]} == {(a,b), (b,c)}
    assert [(edge["winner"],edge["loser"],edge["reason"]) for edge in result["skipped_edges"]] == [(c,a,"would_create_cycle")]
    assert not ({"scores", "runoff", "first_choice_counts"} & result.keys())
    close = f"/api/orgs/{org.slug}/proposals/{proposal.id}/advance" if org_close else path + "/advance"
    assert client.post(close, headers=_auth_header(user), json={}).status_code == 200
    final = client.get(path + "/results", headers=_auth_header(user)).json()
    assert final["method_result"]["finalized"] and final["method_result"]["tie_seed"]
    options[0].label = "Changed after final"
    test_db.query(models.Vote).filter_by(proposal_id=proposal.id).delete()
    test_db.commit()
    assert client.get(path + "/results", headers=_auth_header(user)).json() == final
    assert client.post(path + "/vote", headers=_auth_header(user), json={"rank_groups": []}).status_code == 400


def test_equal_groups_late_option_and_removal_keep_neutral_override(client, test_db, ranked_pairs):
    user, _, proposal, options = ranked_pairs
    a,b,c = [option.id for option in options]
    path = f"/api/proposals/{proposal.id}"
    headers = _auth_header(user)
    assert client.post(path + "/vote", headers=headers, json={"rank_groups": [[a,b]]}).status_code == 200
    own = client.get(path + "/my-vote", headers=headers).json()
    assert own["rank_groups"] == [sorted([a,b])] and own["is_direct"] is True
    result = client.get(path + "/results", headers=headers).json()["method_result"]
    assert result["pairwise"][a][b] == result["pairwise"][b][a] == "0"
    assert result["pairwise"][a][c] == result["pairwise"][b][c] == "1"
    late_response = client.post(path + "/options", headers=headers, json={"label": "Late ranking option"})
    assert late_response.status_code == 201, late_response.text
    late = late_response.json()["id"]
    after = client.get(path + "/results", headers=headers).json()["method_result"]
    assert after["pairwise"][a][late] == "1"
    assert after["pairwise"][c][late] == after["pairwise"][late][c] == "0"
    assert after["option_set_version"] != result["option_set_version"]
    assert test_db.query(models.Vote).filter_by(proposal_id=proposal.id).one().ballot == {"rank_groups": [sorted([a,b])]}
    assert client.post(path + "/vote", headers=headers, json={"rank_groups": [[late]]}).status_code == 200
    assert client.delete(path + "/options/" + late, headers=headers).status_code == 204
    assert test_db.query(models.Vote).filter_by(proposal_id=proposal.id).one().ballot == {"rank_groups": []}
    assert client.get(path + "/my-vote", headers=headers).json()["is_direct"] is True
    assert client.get(path + "/results", headers=headers).json()["method_result"]["winner"] is None


@pytest.mark.parametrize("payload", [{"scores": {}}, {"grades": {}}, {"rank_groups": [[]]}, {"rank_groups": [], "abstain": True}])
def test_ranked_pairs_rejects_wrong_ballot_shape(client, ranked_pairs, payload):
    user, _, proposal, _ = ranked_pairs
    assert client.post(f"/api/proposals/{proposal.id}/vote", headers=_auth_header(user), json=payload).status_code in (400,422)


def test_ranked_pairs_rejects_duplicate_or_foreign_option(client, ranked_pairs):
    from uuid import uuid4
    user, _, proposal, options = ranked_pairs
    path = f"/api/proposals/{proposal.id}/vote"
    for groups in ([[options[0].id], [options[0].id]], [[str(uuid4())]]):
        assert client.post(path, headers=_auth_header(user), json={"rank_groups": groups}).status_code in (400,422)


@pytest.mark.parametrize("route", ["/api/proposals", "/api/orgs/star-test/proposals"])
def test_ranked_pairs_create_import_opt_in_and_fresh_rules(client, test_db, ranked_pairs, route):
    user, org, proposal, _ = ranked_pairs
    headers = _auth_header(user)
    payload = {"title":"RP create", "body":"Synthetic", "voting_method":"ranked_pairs",
               "options":[{"label":"A"},{"label":"B"}], "voting_rules":proposal.voting_rules}
    response = client.post(route, headers=headers, json=payload)
    if route == "/api/proposals":
        assert response.status_code == 400
        return
    assert response.status_code == 201, response.text
    rules = response.json()["voting_rules"]
    assert rules["rule_id"] == "ranked_pairs_margins_v1"
    assert "tie_seed" not in rules and rules["tie_commitment"] != proposal.voting_rules["tie_commitment"]
    assert client.post(f"/api/orgs/{org.slug}/proposals/import-preview", headers=headers, json=payload).status_code == 200
    org.settings = {**org.settings, "allowed_voting_methods": ["binary"]}
    test_db.commit()
    assert client.post(route, headers=headers, json=payload).status_code == 400
    assert client.post(f"/api/orgs/{org.slug}/proposals/import-preview", headers=headers, json=payload).status_code == 422


def test_ranked_pairs_early_privacy_feed_and_profile(client, test_db, ranked_pairs):
    user, org, proposal, options = ranked_pairs
    proposal.status="deliberation"
    proposal.allow_pre_voting=True
    proposal.show_votes_during_deliberation=False
    test_db.commit()
    headers=_auth_header(user)
    path=f"/api/proposals/{proposal.id}"
    assert client.post(path+"/vote",headers=headers,json={"rank_groups":[[options[0].id,options[1].id]]}).status_code==200
    for surface in ("results","vote-graph","trajectory"):
        assert client.get(path+"/"+surface,headers=headers).status_code==404
    own=client.get(path+"/my-vote",headers=headers).json()
    assert own["rank_groups"]==[sorted([options[0].id,options[1].id])]
    history=client.get(f"/api/users/{user.id}/votes",headers=headers).json()
    assert history[0]["ballot_summary"]=="Ranked Pairs ballot submitted"
    assert client.get(f"/api/users/{user.id}/votes").json()==[]
    proposal.status="voting"
    test_db.commit()
    feed=client.get(f"/api/orgs/{org.slug}/proposal-feed",headers=headers)
    assert feed.status_code==200,feed.text
    assert feed.json()["items"][0]["viewer_vote"]["selection_count"]==2
    assert client.post(path+"/vote",headers=headers,json={"abstain":True}).status_code==200
    assert client.get(path+"/my-vote",headers=headers).json()["abstain"]


def test_ranked_pairs_graph_filters_other_ballots_and_existing_disabled_method_still_works(client, test_db, ranked_pairs):
    user, org, proposal, options = ranked_pairs
    other = _create_user(test_db, "rank-private-other")
    _create_membership(test_db, org, other)
    outsider = _create_user(test_db, "rank-outsider")
    org.settings = {**org.settings, "allowed_voting_methods": ["binary"]}
    test_db.commit()
    path = f"/api/proposals/{proposal.id}"
    for actor, groups in ((user, [[options[0].id]]), (other, [[options[1].id]])):
        assert client.post(path + "/vote", headers=_auth_header(actor), json={"rank_groups": groups}).status_code == 200
    graph = client.get(path + "/vote-graph", headers=_auth_header(user))
    assert graph.status_code == 200, graph.text
    visible_ballots = [node["ballot"] for node in graph.json()["nodes"] if node["ballot"] is not None]
    assert len(visible_ballots) == 1
    assert visible_ballots[0]["rank_groups"] == [[options[0].id]]
    assert client.get(path + "/results", headers=_auth_header(outsider)).status_code == 404
    assert client.post(path + "/vote", headers=_auth_header(outsider), json={"rank_groups": []}).status_code == 403
