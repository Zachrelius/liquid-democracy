"""One-shot API QA scoped to the Phase 109 bootstrap org and accounts only.

Requires explicit execution flag and runtime passwords. No reset, deletion,
identity-provider calls, existing account changes, or secret output.
"""
import argparse
from copy import deepcopy
import json
import os
from pathlib import Path
import sys
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.phase109_release_qa_bootstrap import ACCOUNTS, SLUG

METHODS = ("star", "score", "ranked_pairs", "majority_judgment")


def allowed_url(value):
    parsed = urlsplit(value)
    local = parsed.scheme == "http" and parsed.hostname in ("localhost", "127.0.0.1")
    production = value == "https://www.liquiddemocracy.us"
    if not (local or production) or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in ("", "/"):
        raise ValueError("URL must be localhost HTTP or exactly https://www.liquiddemocracy.us")
    return value.rstrip("/")


def run(client, owner_password, member_password, save_manifest=lambda value: None):
    if not __debug__:
        raise RuntimeError("QA driver requires assertions; do not run Python with -O")
    tokens = {}
    users = {}
    manifest = {"org_slug": SLUG, "open_proposals": {}, "closed_proposals": {}, "checks": []}
    def call(actor, method, path, payload=None, expected=200):
        headers = {"Authorization": "Bearer " + tokens[actor]} if actor in tokens else {}
        body_arg = {"data": payload} if path == "/api/auth/login" else {"json": payload}
        response = client.request(method, path, headers=headers, **body_arg)
        if response.status_code != expected:
            # Do not echo response bodies: authentication/errors can contain
            # sensitive fields. The bounded path and status are sufficient.
            raise RuntimeError(f"QA failed: {method} {path}: expected {expected}, got {response.status_code}")
        return response.json() if response.content else None
    for actor, account, password in zip(("owner", "member"), ACCOUNTS, (owner_password, member_password)):
        login = call(None, "POST", "/api/auth/login", {"username": account[0], "password": password})
        tokens[actor] = login["access_token"]
        users[actor] = call(actor, "GET", "/api/auth/me")
        assert users[actor]["username"] == account[0] and not users[actor]["is_admin"]
        assert users[actor]["email"] == account[0] + "@demo.example"
    root = f"/api/orgs/{SLUG}"
    org = call("owner", "GET", root)
    assert org["slug"] == SLUG and org["discoverability"] == "hidden"
    assert org["join_policy"] == "invite" and org["activity_visibility"] == "members_only"
    assert call("member", "GET", root)["id"] == org["id"]
    members = call("owner", "GET", root + "/members")
    assert {row["user_id"] for row in members} == {user["id"] for user in users.values()}
    assert call("owner", "GET", root + "/proposals") == [], "Refusing an org with pre-existing proposals"
    assert call("owner", "GET", root + "/topics") == [], "Refusing an org with pre-existing topics"
    assert call("owner", "GET", root + "/sub-orgs") == [], "Refusing an org with pre-existing sub-orgs"
    call(None, "GET", root, expected=401)
    manifest.update(org_id=org["id"], accounts={actor: user["id"] for actor, user in users.items()})
    save_manifest(manifest)
    topic = call("owner", "POST", root + "/topics", {"name": "Phase 109 synthetic API verification"}, 201)
    manifest["topic_id"] = topic["id"]
    save_manifest(manifest)
    call("member", "PATCH", root + f"/delegate-profile/topics/{topic['id']}", {"visibility": "public"})
    delegation = call("owner", "POST", root + "/delegations/request",
                      {"delegate_id": users["member"]["id"], "topic_id": topic["id"], "chain_behavior": "accept_sub"})
    assert delegation["status"] == "delegated", "Expected immediate scoped delegation"
    manifest["checks"].append("private_org_and_scoped_delegation")

    def expression(method, ids, neutral=False):
        if method == "ranked_pairs":
            return {"rank_groups": [] if neutral else [[ids[0]], [ids[1]]]}
        return {"grades" if method == "majority_judgment" else "scores": {} if neutral else {ids[0]: 5, ids[1]: 2}}
    def body(method, title, early=True):
        return {"title": title, "body": "Isolated synthetic release QA; no real decision.",
                "voting_method": method, "num_winners": 1, "topics": [topic["id"]],
                "options": [{"label": "Synthetic A"}, {"label": "Synthetic B"}],
                "quorum_threshold": 0, "deliberation_days": 1 if early else 0,
                "allow_pre_voting": True, "show_votes_during_deliberation": False,
                "allow_write_in_options": True, "allow_write_ins_during_voting": True,
                "stable_result_required": False}
    # Creation gating: only alter settings of the verified isolated org.
    settings = deepcopy(org["settings"])
    try:
        call("owner", "PATCH", root, {"settings": {**settings, "allowed_voting_methods": ["binary", "approval", "ranked_choice", "budget_allocation", "budget_project"]}})
        for method in METHODS:
            call("owner", "POST", root + "/proposals", body(method, "Must be refused"), 400)
    finally:
        call("owner", "PATCH", root, {"settings": settings})
    manifest["checks"].append("all_optional_methods_disabled_gate")

    sub_slug = "phase109-release-sub-20261008"
    sub = call("owner", "POST", root + "/sub-orgs", {"name": "Synthetic QA subgroup", "slug": sub_slug}, 201)
    manifest["sub_org_id"] = sub["id"]
    save_manifest(manifest)
    sub_path = root + "/sub-orgs/" + sub_slug
    call("owner", "PATCH", sub_path, {"settings": {"allowed_voting_methods": ["binary"]}})
    for method in METHODS:
        call("owner", "POST", root + "/proposals", {**body(method, "Subgroup must refuse"), "sub_org_id": sub["id"]}, 400)
    call("owner", "PATCH", sub_path, {"settings": {"allowed_voting_methods": list(METHODS)}})
    sub_draft = call("owner", "POST", root + "/proposals", {**body("star", "Subgroup enabled draft"), "sub_org_id": sub["id"]}, 201)
    manifest["sub_org_proposal_id"] = sub_draft["id"]
    manifest["checks"].append("subgroup_override_gate")
    save_manifest(manifest)

    for method in METHODS:
        proposal = call("owner", "POST", root + "/proposals", body(method, f"Release QA {method} open"), 201)
        pid = proposal["id"]
        manifest["open_proposals"][method] = pid
        save_manifest(manifest)
        assert call("owner", "GET", root + "/proposals/" + pid)["id"] == pid
        assert "tie_seed" not in proposal["voting_rules"]
        path = f"/api/proposals/{pid}"
        state = call("owner", "POST", path + "/advance", {})
        assert state["status"] == "deliberation"
        ids = [option["id"] for option in proposal["options"]]
        call("member", "POST", path + "/vote", expression(method, ids))
        assert call("owner", "GET", path + "/my-vote")["is_direct"] is False
        call("owner", "POST", path + "/vote", expression(method, ids, neutral=True))
        own = call("owner", "GET", path + "/my-vote")
        field = next(iter(expression(method, ids)))
        assert own["is_direct"] is True and own[field] == expression(method, ids, neutral=True)[field]
        call("owner", "GET", path + "/results", expected=404)
        call("owner", "POST", path + "/vote", {"abstain": True})
        assert call("owner", "GET", path + "/my-vote")["abstain"]
        call("owner", "DELETE", path + "/vote", expected=204)
        assert call("owner", "GET", path + "/my-vote")["is_direct"] is False
        assert call("owner", "POST", path + "/advance", {})["status"] == "voting"
        late = call("owner", "POST", path + "/options", {"label": "Synthetic late option"}, 201)
        result = call("owner", "GET", path + "/results")["method_result"]
        if method in ("star", "score"):
            assert result["scores"][late["id"]] == "0"
        elif method == "majority_judgment":
            assert result["grade_histograms"][late["id"]][0] == "2"
        else:
            assert result["pairwise"][ids[0]][late["id"]] == "2"
        call("owner", "POST", path + "/vote", expression(method, [late["id"], ids[0]]))
        assert call("owner", "GET", path + "/my-vote")["is_direct"] is True
        # Keep this proposal open, with a direct ballot, for rendered QA.
        closed = call("owner", "POST", root + "/proposals", body(method, f"Release QA {method} frozen", early=False), 201)
        manifest["closed_proposals"][method] = closed["id"]
        save_manifest(manifest)
        cpath = f"/api/proposals/{closed['id']}"
        assert closed["status"] == "voting"
        cids = [option["id"] for option in closed["options"]]
        call("owner", "POST", cpath + "/vote", expression(method, cids))
        call("owner", "POST", cpath + "/advance", {})
        final = call("owner", "GET", cpath + "/results")
        assert final["method_result"]["finalized"] and final["method_result"]["tie_seed"]
        assert call("owner", "GET", cpath + "/results") == final
        call("owner", "POST", cpath + "/vote", {"abstain": True}, 400)
        manifest["checks"].append(method + ":early_privacy_neutral_delegate_abstain_retract_writein_revote_close_freeze")
        save_manifest(manifest)
    manifest["worker_close"] = "NOT RUN: use a new proposal in this org; invoke evaluate_proposal only for its exact verified ID after its deadline, with a scoped session and commit. Never invoke the global worker tick."
    manifest["completed"] = True
    save_manifest(manifest)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--confirm-isolated-release-qa", action="store_true")
    args = parser.parse_args()
    if not args.confirm_isolated_release_qa:
        parser.error("Explicit confirmation is required; no requests performed")
    base = allowed_url(args.base_url)
    output = Path(args.manifest)
    if output.exists():
        parser.error("Manifest already exists; refusing a repeated QA run")
    passwords = [os.environ.get(name) for name in ("PHASE109_QA_OWNER_PASSWORD", "PHASE109_QA_MEMBER_PASSWORD")]
    if not all(passwords):
        parser.error("Both runtime QA passwords are required")
    import httpx
    with httpx.Client(base_url=base, follow_redirects=False, timeout=45) as client:
        run(client, *passwords, save_manifest=lambda result: output.write_text(json.dumps(result, indent=2), encoding="utf-8"))
    print("Isolated QA completed; non-secret IDs saved to the supplied manifest.")


if __name__ == "__main__":
    main()
