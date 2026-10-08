from datetime import datetime, timedelta, timezone

import pytest

import models
import voting_methods
from experimental_voting import initialize_rules
from tests.test_ranked_choice_voting import (test_db, client, _create_user,
                                            _create_org, _create_membership, _auth_header)


@pytest.fixture
def star(test_db, monkeypatch):
    monkeypatch.setattr(voting_methods, "RELEASED_EXPERIMENTAL_METHODS", ("star",))
    user = _create_user(test_db, "star-admin")
    user.is_admin = True
    org = _create_org(test_db, ["binary", "approval", "star"], slug="star-test")
    _create_membership(test_db, org, user)
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    proposal = models.Proposal(title="STAR test", body="A real model fixture", author_id=user.id,
                              org_id=org.id, voting_method="star", num_winners=1, status="voting",
                              voting_start=now, voting_end=now + timedelta(days=7),
                              quorum_threshold=0, allow_write_in_options=True,
                              allow_write_ins_during_voting=True)
    test_db.add(proposal)
    test_db.flush()
    initialize_rules(proposal)
    options = [models.ProposalOption(proposal_id=proposal.id, label=name, display_order=i)
               for i, name in enumerate(["A", "B", "C"])]
    test_db.add_all(options)
    test_db.commit()
    return user, org, proposal, options


def test_cast_close_frozen_result(client, test_db, star):
    user, org, proposal, options = star
    headers = _auth_header(user)
    path = f"/api/proposals/{proposal.id}"
    cast = client.post(path + "/vote", headers=headers, json={"scores": {options[0].id: 5, options[1].id: 3}})
    assert cast.status_code == 200, cast.text
    assert cast.json()["ballot"]["scores"][options[0].id] == 5
    detail = client.get(path, headers=headers)
    assert detail.status_code == 200, detail.text
    assert "tie_seed" not in detail.json()["voting_rules"]
    live = client.get(path + "/results", headers=headers)
    assert live.status_code == 200, live.text
    assert live.json()["method_result"]["scores"][options[0].id] == "5"
    closed = client.post(path + "/advance", headers=headers, json={})
    assert closed.status_code == 200, closed.text
    final = client.get(path + "/results", headers=headers).json()
    assert final["method_result"]["finalized"]
    assert final["method_result"]["tie_seed"]
    options[0].label = "Changed after close"
    test_db.query(models.Vote).filter_by(proposal_id=proposal.id).delete()
    test_db.commit()
    assert client.get(path + "/results", headers=headers).json() == final


@pytest.mark.parametrize("org_route", [False, True])
def test_manual_close_notification_failure_rolls_back_then_retry(client, test_db, star, monkeypatch, org_route):
    import proposal_lifecycle
    user, org, proposal, options = star
    headers = _auth_header(user)
    path = f"/api/proposals/{proposal.id}"
    assert client.post(path + "/vote", headers=headers, json={"scores": {options[0].id: 5}}).status_code == 200
    test_db.add(models.NotificationPreference(user_id=user.id, event_type="proposal.closed",
                                              channel="in_app", enabled=True))
    test_db.commit()
    advance = f"/api/orgs/{org.slug}/proposals/{proposal.id}/advance" if org_route else path + "/advance"
    real_emit = proposal_lifecycle.emit_notification
    def fail_after_staging(*args, **kwargs):
        real_emit(*args, **kwargs)
        raise RuntimeError("Injected close intent failure")
    monkeypatch.setattr(proposal_lifecycle, "emit_notification", fail_after_staging)
    with pytest.raises(RuntimeError, match="Injected close intent"):
        client.post(advance, headers=headers, json={})
    test_db.expire_all()
    assert proposal.status == "voting" and proposal.final_method_result is None
    assert test_db.query(models.Notification).filter_by(target_id=proposal.id, event_type="proposal.closed").count() == 0
    assert test_db.query(models.AuditLog).filter_by(target_id=proposal.id, action="proposal.status_changed").count() == 0
    monkeypatch.setattr(proposal_lifecycle, "emit_notification", real_emit)
    assert client.post(advance, headers=headers, json={}).status_code == 200
    assert test_db.query(models.Notification).filter_by(target_id=proposal.id, event_type="proposal.closed").count() == 1
    assert test_db.query(models.AuditLog).filter_by(target_id=proposal.id, action="proposal.status_changed").count() == 1
    assert client.post(advance, headers=headers, json={}).status_code == 400
    assert test_db.query(models.Notification).filter_by(target_id=proposal.id, event_type="proposal.closed").count() == 1
    assert client.post(path + "/vote", headers=headers, json={"abstain": True}).status_code == 400


def test_late_write_in_omission_and_remove(client, test_db, star):
    user, org, proposal, options = star
    headers = _auth_header(user)
    path = f"/api/proposals/{proposal.id}"
    assert client.post(path + "/vote", headers=headers, json={"scores": {options[0].id: 5}}).status_code == 200
    added = client.post(path + "/options", headers=headers, json={"label": "Late option"})
    assert added.status_code == 201, added.text
    late_id = added.json()["id"]
    live = client.get(path + "/results", headers=headers)
    assert live.status_code == 200, live.text
    assert live.json()["method_result"]["scores"][late_id] == "0"
    assert late_id not in test_db.query(models.Vote).filter_by(proposal_id=proposal.id).one().ballot["scores"]
    assert client.post(path + "/vote", headers=headers, json={"scores": {late_id: 5}}).status_code == 200
    deleted = client.delete(path + "/options/" + late_id, headers=headers)
    assert deleted.status_code == 204, deleted.text
    assert test_db.query(models.Vote).filter_by(proposal_id=proposal.id).one().ballot == {"scores": {}}


def test_org_close_and_abstention(client, star):
    user, org, proposal, options = star
    headers = _auth_header(user)
    path = f"/api/proposals/{proposal.id}"
    assert client.post(path + "/vote", headers=headers, json={"abstain": True}).status_code == 200
    status = client.get(path + "/my-vote", headers=headers)
    assert status.status_code == 200, status.text
    assert status.json()["abstain"]
    closed = client.post(f"/api/orgs/{org.slug}/proposals/{proposal.id}/advance", headers=headers, json={})
    assert closed.status_code == 200, closed.text
    assert closed.json()["status"] == "failed"


@pytest.mark.parametrize("route", ["/api/proposals", "/api/orgs/star-test/proposals"])
def test_both_create_paths(client, test_db, star, route):
    user, org, _, _ = star
    data = {"title": "New STAR", "body": "Options for everyone", "voting_method": "star",
            "options": [{"label": "A"}, {"label": "B"}], "org_id": org.id}
    response = client.post(route, headers=_auth_header(user), json=data)
    if route == "/api/proposals":
        assert response.status_code == 400
        assert "organization opt-in" in response.text
        return
    assert response.status_code == 201, response.text
    assert response.json()["voting_rules"]["method"] == "star"
    assert "tie_seed" not in response.json()["voting_rules"]
    assert len(response.json()["options"]) == 2


def test_preliminary_results_private(client, test_db, star):
    user, _, proposal, _ = star
    proposal.status = "deliberation"
    proposal.allow_pre_voting = True
    proposal.show_votes_during_deliberation = False
    test_db.commit()
    path = f"/api/proposals/{proposal.id}"
    assert client.post(path + "/vote", headers=_auth_header(user), json={"scores": {}}).status_code == 200
    assert client.get(path + "/results", headers=_auth_header(user)).status_code == 404
    assert client.get(path + "/vote-graph", headers=_auth_header(user)).status_code == 404
    assert client.get(path + "/trajectory", headers=_auth_header(user)).status_code == 404


def test_disabled_method_cannot_create_but_existing_can_vote(client, test_db, star):
    user, org, proposal, options = star
    org.settings = {**org.settings, "allowed_voting_methods": ["binary"]}
    test_db.commit()
    headers = _auth_header(user)
    created = client.post(f"/api/orgs/{org.slug}/proposals", headers=headers,
                          json={"title": "Disabled", "body": "test", "voting_method": "star",
                                "options": [{"label": "A"}, {"label": "B"}]})
    assert created.status_code == 400, created.text
    assert client.post(f"/api/proposals/{proposal.id}/vote", headers=headers,
                       json={"scores": {options[0].id: 4}}).status_code == 200


@pytest.mark.parametrize("payload", [{"approvals": []}, {"scores": {"00000000-0000-0000-0000-000000000000": 5}},
                                     {"grades": {}}, {"rank_groups": []}])
def test_wrong_ballot_or_foreign_option_rejected(client, star, payload):
    user, _, proposal, _ = star
    response = client.post(f"/api/proposals/{proposal.id}/vote", headers=_auth_header(user), json=payload)
    assert response.status_code == 400, response.text


def test_unreleased_methods_cannot_create_even_if_org_lists_them(client, test_db, star):
    user, org, _, _ = star
    org.settings = {**org.settings, "allowed_voting_methods": list(voting_methods.EXPERIMENTAL_VOTING_METHODS)}
    test_db.commit()
    for method in ("score", "ranked_pairs", "majority_judgment"):
        response = client.post(f"/api/orgs/{org.slug}/proposals", headers=_auth_header(user),
                               json={"title": "Not ready", "body": "test", "voting_method": method,
                                     "options": [{"label": "A"}, {"label": "B"}]})
        assert response.status_code == 422, response.text


def test_final_options_cannot_be_mutated(client, star):
    user, _, proposal, options = star
    headers = _auth_header(user)
    path = f"/api/proposals/{proposal.id}"
    assert client.post(path + "/vote", headers=headers, json={"scores": {options[0].id: 5}}).status_code == 200
    late = client.post(path + "/options", headers=headers, json={"label": "Late"}).json()
    assert client.post(path + "/advance", headers=headers, json={}).status_code == 200
    assert client.delete(path + "/options/" + late["id"], headers=headers).status_code == 400
    assert client.patch(path + "/options/" + options[0].id, headers=headers, json={"label": "Tampered"}).status_code == 400


def test_seed_hidden_on_direct_schema_validation(test_db, star):
    import schemas
    from routes.proposals import _build_proposal_out
    user, _, proposal, _ = star
    response = _build_proposal_out(proposal, test_db, viewer_id=user.id)
    data = response.model_dump()
    data["voting_rules"] = proposal.voting_rules
    assert "tie_seed" not in schemas.ProposalOut(**data).voting_rules


def test_draft_method_switch_to_star_initializes_new_rules(client, test_db, star):
    user, _, proposal, _ = star
    proposal.status = "draft"
    proposal.voting_method = "approval"
    proposal.voting_rules = None
    test_db.commit()
    response = client.patch(f"/api/proposals/{proposal.id}", headers=_auth_header(user),
                            json={"voting_method": "star"})
    assert response.status_code == 200, response.text
    assert response.json()["voting_rules"]["rule_id"] == "star_0_5_v1"


def test_import_roundtrip_drops_server_owned_fields_and_checks_opt_in(client, test_db, star):
    user, org, proposal, _ = star
    headers = _auth_header(user)
    payload = {"title": "Imported STAR", "body": "Synthetic", "voting_method": "star",
               "options": [{"label": "A"}, {"label": "B"}],
               "voting_rules": proposal.voting_rules, "final_method_result": {"winner": "fake"}}
    preview = client.post(f"/api/orgs/{org.slug}/proposals/import-preview", headers=headers, json=payload)
    assert preview.status_code == 200, preview.text
    assert "voting_rules" not in preview.json()["proposal"]
    assert "final_method_result" not in preview.json()["proposal"]
    created = client.post(f"/api/orgs/{org.slug}/proposals", headers=headers, json=preview.json()["proposal"])
    assert created.status_code == 201, created.text
    assert created.json()["voting_rules"]["tie_commitment"] != proposal.voting_rules["tie_commitment"]
    org.settings = {**org.settings, "allowed_voting_methods": ["binary"]}
    test_db.commit()
    assert client.post(f"/api/orgs/{org.slug}/proposals/import-preview", headers=headers, json=payload).status_code == 422


def test_suborg_override_controls_draft_method_transition(client, test_db, star):
    user, org, proposal, _ = star
    sub = models.Organization(name="Sub", slug="star-sub", parent_org_id=org.id,
                              settings={"allowed_voting_methods": ["binary", "approval"]})
    test_db.add(sub); test_db.flush()
    proposal.status = "draft"; proposal.sub_org_id = sub.id
    proposal.voting_method = "approval"; proposal.voting_rules = None
    test_db.commit()
    path = f"/api/proposals/{proposal.id}"
    assert client.patch(path, headers=_auth_header(user), json={"voting_method": "star"}).status_code == 400
    sub.settings = {"allowed_voting_methods": ["star"]}
    test_db.commit()
    response = client.patch(path, headers=_auth_header(user), json={"voting_method": "star"})
    assert response.status_code == 200, response.text


def test_preliminary_reset_needs_explicit_confirmation_and_records_side_effects(client, test_db, star):
    user, org, proposal, options = star
    headers = _auth_header(user); path = f"/api/proposals/{proposal.id}"
    assert client.post(path + "/vote", headers=headers, json={"scores": {options[0].id: 5}}).status_code == 200
    proposal.status = "draft"
    test_db.commit()
    assert client.patch(path, headers=headers, json={"voting_method": "approval"}).status_code == 409
    test_db.rollback()
    assert test_db.query(models.Vote).filter_by(proposal_id=proposal.id).count() == 1
    response = client.patch(path, headers=headers, json={"voting_method": "approval", "confirm_ballot_reset": True})
    assert response.status_code == 200, response.text
    assert test_db.query(models.Vote).filter_by(proposal_id=proposal.id).count() == 0
    audit = test_db.query(models.AuditLog).filter_by(target_id=proposal.id, action="proposal.preliminary_ballots_reset").one()
    assert audit.details["ballots_removed"] == 1


def test_public_results_respect_preliminary_visibility_and_final_snapshot(client, test_db, star):
    user, org, proposal, options = star
    org.activity_visibility = "public"
    test_db.commit()
    path = f"/api/orgs/{org.slug}/public/proposals/{proposal.id}/results"
    result = client.get(path)
    assert result.status_code == 200, result.text
    assert result.json()["method_result"]["scores"][options[0].id] == "0"
    proposal.status = "deliberation"
    proposal.show_votes_during_deliberation = False
    test_db.commit()
    assert client.get(path).status_code == 404


def test_cross_org_member_cannot_vote_or_read_private_results(client, test_db, star):
    _, _, proposal, options = star
    outsider = _create_user(test_db, "outsider")
    other_org = _create_org(test_db, ["star"], slug="other-org")
    _create_membership(test_db, other_org, outsider, role="member")
    test_db.commit()
    path = f"/api/proposals/{proposal.id}"
    headers = _auth_header(outsider)
    assert client.get(path + "/results", headers=headers).status_code == 404
    assert client.post(path + "/vote", headers=headers, json={"scores": {options[0].id: 5}}).status_code == 403
    assert test_db.query(models.Vote).filter_by(proposal_id=proposal.id).count() == 0


def test_large_weight_exact_across_api_and_freezes_with_rules(client, test_db, star):
    user, org, proposal, options = star
    org.settings = {**org.settings, "weighted_voting": {"enabled": True, "unit_label": "shares"}}
    member = test_db.query(models.OrgMembership).filter_by(org_id=org.id, user_id=user.id).one()
    member.voting_weight = 10 ** 16 + 1
    test_db.commit()
    headers = _auth_header(user); path = f"/api/proposals/{proposal.id}"
    assert client.post(path + "/vote", headers=headers, json={"scores": {options[0].id: 5}}).status_code == 200
    result = client.get(path + "/results", headers=headers).json()
    assert result["total_eligible"] == str(10 ** 16 + 1)
    assert result["method_result"]["scores"][options[0].id] == str(5 * (10 ** 16 + 1))
    assert client.get(path + "/my-vote", headers=headers).json()["my_voting_weight"] == str(10 ** 16 + 1)
    assert client.post(path + "/advance", headers=headers, json={}).status_code == 200
    final = client.get(path + "/results", headers=headers).json()
    assert final["method_result"]["rules"]["scale"] == [0, 1, 2, 3, 4, 5]
    member.voting_weight = 1
    org.settings = {**org.settings, "weighted_voting": {"enabled": False}}
    test_db.commit()
    assert client.get(path + "/results", headers=headers).json() == final


@pytest.mark.parametrize("visibility", ["public", "private"])
def test_delegate_vote_notification_respects_visibility_and_membership(client, test_db, star, visibility):
    user, org, proposal, options = star
    topic = models.Topic(name="STAR notification topic", org_id=org.id)
    test_db.add(topic); test_db.flush()
    test_db.add(models.ProposalTopic(proposal_id=proposal.id, topic_id=topic.id))
    test_db.add(models.DelegateProfile(user_id=user.id, org_id=org.id, topic_id=topic.id,
                                       bio="", visibility=visibility))
    recipients = {}
    for name in ("member", "former", "inactive", "other-subgroup"):
        recipient = _create_user(test_db, "star-notice-" + name)
        recipients[name] = recipient.id
        if name != "former":
            _create_membership(test_db, org, recipient, role="member")
        if name == "inactive":
            recipient.is_active = False
        sub_id = None
        if name == "other-subgroup":
            sub = models.Organization(name="Other subgroup", slug="notice-sub", parent_org_id=org.id)
            test_db.add(sub); test_db.flush()
            sub_id = sub.id
        test_db.add(models.Delegation(delegator_id=recipient.id, delegate_id=user.id, org_id=org.id,
                                      topic_id=topic.id, sub_org_id=sub_id))
        test_db.add(models.NotificationPreference(user_id=recipient.id, event_type="delegate.voted",
                                                  channel="in_app", enabled=True))
    test_db.commit()
    response = client.post(f"/api/proposals/{proposal.id}/vote", headers=_auth_header(user),
                           json={"scores": {options[0].id: 5}})
    assert response.status_code == 200, response.text
    notices = test_db.query(models.Notification).filter_by(target_id=proposal.id, event_type="delegate.voted").all()
    assert {n.user_id for n in notices} == ({recipients["member"]} if visibility == "public" else set())
    for notice in notices:
        assert notice.payload["vote_value"] == "STAR ballot submitted"
        assert options[0].id not in str(notice.payload)
