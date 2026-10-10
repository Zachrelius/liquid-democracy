"""W1 production-shaped routes and stored JSON; expected aggregation is literal."""
import json
import pytest
import models, schemas
from tests.test_phase_73_budget_allocation import client, test_db, _setup, _auth
from voting_capabilities import effective_voting_capabilities, resolve_budget_creation, validate_settings_patch
from routes.organizations import DEFAULT_ORG_SETTINGS


def body(aggregation=None):
    config = {"mode":"allocation", "envelope":1000}
    if aggregation is not None: config["aggregation"] = aggregation
    return {"title":"Synthetic budget", "voting_method":"budget_allocation", "budget_config":config,
            "options":[{"label":"A"}, {"label":"B"}]}


def test_fresh_defaults_and_old_absence_are_distinct():
    assert DEFAULT_ORG_SETTINGS["allowed_budget_aggregations"] == ["median"]
    assert DEFAULT_ORG_SETTINGS["allowed_multiwinner_methods"] == []


@pytest.mark.parametrize("choice", ["median", "trimmed_mean"])
def test_create_exact_explicit_and_legacy_serializer(client, test_db, choice):
    org, author, *_ = _setup(test_db)
    response = client.post(f"/api/orgs/{org.slug}/proposals", headers=_auth(author), json=body(choice))
    assert response.status_code == 201, response.text
    assert response.json()["budget_config"]["aggregation"] == choice
    assert test_db.get(models.Proposal, response.json()["id"]).budget_config["aggregation"] == choice
    out = client.get(f"/api/orgs/{org.slug}", headers=_auth(author)).json()
    assert out["voting_capabilities"]["allowed_budget_aggregations"] == ["median", "trimmed_mean"]
    assert out["voting_capabilities"]["voting_capability_sources"]["allowed_budget_aggregations"] == "legacy_default"


def test_trimmed_only_omission_default_and_explicit_rejection(client, test_db):
    org, author, *_ = _setup(test_db)
    org.settings = {**org.settings, "allowed_budget_aggregations":["trimmed_mean"]};test_db.commit()
    ok = client.post(f"/api/orgs/{org.slug}/proposals", headers=_auth(author), json=body())
    assert ok.status_code == 201, ok.text
    assert ok.json()["budget_config"]["aggregation"] == "trimmed_mean"
    bad = client.post(f"/api/orgs/{org.slug}/proposals", headers=_auth(author), json=body("median"))
    assert bad.status_code == 400 and "not permitted" in bad.text


@pytest.mark.parametrize("choices", [[], ["mean"], ["median", "median"], "median", None])
def test_bad_settings_reject_atomically(client, test_db, choices):
    org, author, *_ = _setup(test_db)
    prior = dict(org.settings)
    response = client.patch(f"/api/orgs/{org.slug}", headers=_auth(author), json={"settings":{"allowed_budget_aggregations":choices}})
    assert response.status_code == 400, response.text
    test_db.expire_all()
    assert test_db.get(models.Organization, org.id).settings == prior


def test_unrelated_old_client_save_does_not_narrow_legacy_choices(client, test_db):
    org, author, *_ = _setup(test_db)
    response = client.patch(f"/api/orgs/{org.slug}", headers=_auth(author), json={"settings":{"default_voting_days":8}})
    assert response.status_code == 200, response.text
    assert "allowed_budget_aggregations" not in test_db.get(models.Organization, org.id).settings
    assert response.json()["voting_capabilities"]["allowed_budget_aggregations"] == ["median", "trimmed_mean"]


def test_draft_grandfathering_and_new_choice_enforcement(client, test_db):
    org, author, *_ = _setup(test_db)
    old = client.post(f"/api/orgs/{org.slug}/proposals", headers=_auth(author), json=body("trimmed_mean")).json()
    org.settings = {**org.settings, "allowed_budget_aggregations":["median"]};test_db.commit()
    config = {**old["budget_config"], "envelope":2000}
    saved = client.patch(f"/api/proposals/{old['id']}", headers=_auth(author), json={"budget_config":config})
    assert saved.status_code == 200, saved.text
    assert saved.json()["budget_config"]["aggregation"] == "trimmed_mean"
    assert client.post(f"/api/orgs/{org.slug}/proposals", headers=_auth(author), json=body("trimmed_mean")).status_code == 400
    config["aggregation"] = "median"
    assert client.patch(f"/api/proposals/{old['id']}", headers=_auth(author), json={"budget_config":config}).status_code == 200
    config["aggregation"] = "trimmed_mean"
    assert client.patch(f"/api/proposals/{old['id']}", headers=_auth(author), json={"budget_config":config}).status_code == 400


def test_import_preview_uses_same_permission_and_default(client, test_db):
    org, author, *_ = _setup(test_db)
    org.settings = {**org.settings, "allowed_budget_aggregations":["trimmed_mean"]};test_db.commit()
    for choice in (None, "median"):
        response = client.post(f"/api/orgs/{org.slug}/proposals/import-preview", headers=_auth(author),
            files={"file":("proposal.json", json.dumps(body(choice)), "application/json")})
        assert response.status_code == (200 if choice is None else 422), response.text
        value = response.json()
        if choice is None:
            assert value["proposal"]["budget_config"]["aggregation"] == "trimmed_mean"
        else:
            assert "budget_config" in value["errors"]


def test_service_creation_and_reset_to_parent(test_db):
    org, author, *_ = _setup(test_db)
    org.settings = {**org.settings, "allowed_budget_aggregations":["trimmed_mean"]}
    child = models.Organization(name="Child", slug="budget-child", parent_org=org,
        settings={"allowed_budget_aggregations":["trimmed_mean"]})
    test_db.add(child);test_db.flush()
    settings = validate_settings_patch(child, {"allowed_budget_aggregations":None})
    assert "allowed_budget_aggregations" not in settings
    assert child.settings == {"allowed_budget_aggregations":["trimmed_mean"]}
    child.settings = settings
    assert effective_voting_capabilities(child)["allowed_budget_aggregations"] == ["trimmed_mean"]
    from experimental_voting import initialize_rules
    p = models.Proposal(title="Direct seed",author_id=author.id,org_id=org.id,sub_org_id=child.id,voting_method="budget_allocation",budget_config={"mode":"allocation","envelope":1000})
    initialize_rules(p,test_db)
    assert p.budget_config["aggregation"] == "trimmed_mean"
    p.budget_config["aggregation"] = "median"
    with pytest.raises(ValueError): initialize_rules(p,test_db)


def test_parent_narrowing_keeps_child_readable_and_existing_rule(test_db):
    org, author, *_ = _setup(test_db)
    org.settings = {**org.settings, "allowed_budget_aggregations":["median", "trimmed_mean"]}
    child = models.Organization(name="Later narrowed",slug="later-narrowed",parent_org=org,settings={"allowed_budget_aggregations":["trimmed_mean"]})
    test_db.add(child);test_db.flush()
    org.settings = {**org.settings, "allowed_budget_aggregations":["median"]}
    assert effective_voting_capabilities(child)["allowed_budget_aggregations"] == ["median"]
    existing={"mode":"allocation","envelope":1000,"aggregation":"trimmed_mean"}
    assert resolve_budget_creation(existing,child,existing=existing)["aggregation"] == "trimmed_mean"
    with pytest.raises(ValueError): resolve_budget_creation(existing,child)
    assert validate_settings_patch(child,{"private":True})["allowed_budget_aggregations"] == ["trimmed_mean"]
