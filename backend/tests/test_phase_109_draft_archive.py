"""Draft method transitions and archive serialization regression boundaries."""
import pytest

from tests.test_ranked_choice_voting import test_db, client, _auth_header
from tests.test_phase_109_star_routes import star


@pytest.mark.parametrize("explicit_count", [True, False])
def test_stv_draft_can_switch_to_star_with_one_winner(client, test_db, star, explicit_count):
    user, org, proposal, _ = star
    proposal.status = "draft"
    proposal.voting_method = "ranked_choice"
    proposal.num_winners = 2
    proposal.voting_rules = None
    test_db.commit()
    payload = {"voting_method": "star"}
    if explicit_count:
        payload["num_winners"] = 1
    response = client.patch(f"/api/proposals/{proposal.id}", headers=_auth_header(user), json=payload)
    assert response.status_code == 200, response.text
    assert response.json()["num_winners"] == 1
    assert response.json()["voting_rules"]["rule_id"] == "star_0_5_v1"
    assert proposal.voting_rules["tie_seed"]


def test_star_draft_can_switch_back_to_multiwinner_rcv(client, test_db, star):
    user, org, proposal, _ = star
    proposal.status = "draft"
    org.settings = {**org.settings, "allowed_voting_methods": ["star", "ranked_choice"]}
    test_db.commit()
    response = client.patch(f"/api/proposals/{proposal.id}", headers=_auth_header(user),
                            json={"voting_method": "ranked_choice", "num_winners": 2})
    assert response.status_code == 200, response.text
    assert response.json()["num_winners"] == 2
    assert proposal.voting_rules is None and proposal.final_method_result is None


def test_star_archive_locks_before_reading_state(client, test_db, star, monkeypatch):
    from routes import proposals
    user, _, proposal, _ = star
    called = []
    def concurrent_archive(db, row):
        called.append(row.id)
        # Model the refreshed row after another transaction archived it first.
        row.status = "withdrawn"
        db.flush()
        return row
    monkeypatch.setattr(proposals, "lock_proposal", concurrent_archive)
    response = client.post(f"/api/proposals/{proposal.id}/archive", headers=_auth_header(user))
    assert called == [proposal.id]
    assert response.status_code == 409, response.text


def test_archive_preserves_existing_frozen_star_result(client, test_db, star):
    user, _, proposal, options = star
    headers = _auth_header(user)
    path = f"/api/proposals/{proposal.id}"
    assert client.post(path+"/vote", headers=headers, json={"scores": {options[0].id: 5}}).status_code == 200
    assert client.post(path+"/advance", headers=headers, json={}).status_code == 200
    final = proposal.final_method_result
    assert client.post(path+"/archive", headers=headers).status_code == 200
    assert proposal.status == "withdrawn" and proposal.final_method_result == final
    result = client.get(path+"/results", headers=headers)
    assert result.status_code == 200, result.text
    assert result.json()["method_result"]["finalized"] is True
    assert result.json()["winners"] == [options[0].id]
