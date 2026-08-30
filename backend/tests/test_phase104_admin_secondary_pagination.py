"""Phase 104 backend pagination, exact-count, and compatibility regressions."""
from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
import re

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event

import auth
from database import get_db
from main import app
import models
from proposal_management import eligible_operations, is_structurally_eligible
from tests.conftest import make_org_membership, make_sub_org_membership, make_user


@pytest.fixture
def client(db):
    def override():
        yield db
    app.dependency_overrides[get_db] = override
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def _headers(user):
    return {"Authorization": f"Bearer {auth.create_access_token(user.id)}"}


def _org(db, slug, *, parent=None, private=False, public=False):
    org = models.Organization(
        name=slug.title(),
        slug=slug,
        parent_org_id=parent,
        settings={"private": private},
        discoverability="listed",
        activity_visibility="public" if public else "members_only",
    )
    db.add(org)
    db.flush()
    return org


def _proposal(
    db,
    org,
    author,
    title,
    *,
    status="draft",
    sub=None,
    when=None,
    cosign=False,
    links=None,
):
    when = when or datetime(2026, 8, 30, 12, 0)
    proposal = models.Proposal(
        title=title,
        body="X" * 20_000,
        author_id=author.id,
        org_id=org.id,
        sub_org_id=sub,
        status=status,
        voting_method="approval",
        num_winners=2,
        created_at=when,
        updated_at=when,
        deliberation_end=(when + timedelta(days=1) if status == "deliberation" else None),
        voting_start=(when if status == "voting" else None),
        voting_end=(when + timedelta(days=2) if status == "voting" else None),
        is_cosign_gated=cosign,
        linked_polis_ids=links,
    )
    db.add(proposal)
    db.flush()
    return proposal


def _polis(db, org, creator, title="Phase 104 Polis", *, sub=None):
    polis = models.Polis(
        org_id=org.id,
        sub_org_id=sub,
        title=title,
        prompt="Prompt",
        created_by=creator.id,
        status="active",
        polis_conversation_id="phase104-conversation",
    )
    db.add(polis)
    db.flush()
    return polis


def test_management_feed_all_statuses_compact_cursor_and_scope_visibility(client, db):
    member = make_user(db, "p104-management-member")
    sub_member = make_user(db, "p104-management-sub-member")
    admin = make_user(db, "p104-management-admin")
    author = make_user(db, "p104-management-author")
    org = _org(db, "p104-management")
    public_sub = _org(db, "p104-management-public-sub", parent=org.id)
    private_sub = _org(db, "p104-management-private-sub", parent=org.id, private=True)
    other = _org(db, "p104-management-other")
    for user, role in (
        (member, "member"), (sub_member, "member"),
        (admin, "admin"), (author, "member"),
    ):
        make_org_membership(db, org_id=org.id, user_id=user.id, role=role)
    make_sub_org_membership(db, sub_org_id=private_sub.id, user_id=sub_member.id)
    make_org_membership(db, org_id=other.id, user_id=author.id)
    statuses = (
        "draft", "deliberation", "voting", "passed", "failed",
        "withdrawn", "unresolved", "expired_unsigned",
    )
    expected = []
    tied = datetime(2026, 8, 30, 12, 0)
    for index, status in enumerate(statuses):
        expected.append(_proposal(
            db, org, author, f"status-{status}", status=status,
            when=tied + timedelta(minutes=index),
        ))
    public_row = _proposal(db, org, author, "public-sub", sub=public_sub.id, when=tied)
    private_row = _proposal(db, org, author, "private-sub", sub=private_sub.id, when=tied)
    _proposal(db, other, author, "cross-org", when=tied)

    seen = []
    cursor = None
    while True:
        suffix = f"&cursor={cursor}" if cursor else ""
        response = client.get(
            f"/api/orgs/{org.slug}/proposal-management-feed?limit=3{suffix}",
            headers=_headers(member),
        )
        assert response.status_code == 200
        payload = response.json()
        for item in payload["items"]:
            assert set(item) == {
                "id", "title", "status", "voting_method", "num_winners",
                "created_at", "sub_org_id", "deliberation_end",
                "voting_end_date", "voting_end", "is_cosign_gated",
                "eligible_operations",
            }
            assert "body" not in item and "linked_polis_ids" not in item
        seen.extend(item["id"] for item in payload["items"])
        if not payload["has_more"]:
            break
        cursor = payload["next_cursor"]
    assert len(seen) == len(set(seen)) == len(expected) + 1
    assert private_row.id not in seen
    assert public_row.id in seen
    assert {row.id for row in expected}.issubset(seen)

    parent_only = client.get(
        f"/api/orgs/{org.slug}/proposal-management-feed?parent_only=true&limit=100",
        headers=_headers(member),
    )
    assert {item["id"] for item in parent_only.json()["items"]} == {
        row.id for row in expected
    }

    admin_response = client.get(
        f"/api/orgs/{org.slug}/proposal-management-feed?sub_org_id={private_sub.id}",
        headers=_headers(admin),
    )
    assert [item["id"] for item in admin_response.json()["items"]] == [private_row.id]
    denied_scope = client.get(
        f"/api/orgs/{org.slug}/proposal-management-feed?sub_org_id={private_sub.id}",
        headers=_headers(member),
    )
    assert denied_scope.status_code == 404
    sub_member_scope = client.get(
        f"/api/orgs/{org.slug}/proposal-management-feed?sub_org_id={private_sub.id}",
        headers=_headers(sub_member),
    )
    assert [item["id"] for item in sub_member_scope.json()["items"]] == [private_row.id]
    conflict = client.get(
        f"/api/orgs/{org.slug}/proposal-management-feed?sub_org_id={public_sub.id}&parent_only=true",
        headers=_headers(member),
    )
    assert conflict.status_code == 422
    cross_scope = client.get(
        f"/api/orgs/{org.slug}/proposal-management-feed?sub_org_id={other.id}",
        headers=_headers(admin),
    )
    assert cross_scope.status_code == 404


def test_management_filters_literal_title_search_and_validation(client, db):
    viewer = make_user(db, "p104-search-viewer")
    org = _org(db, "p104-search")
    make_org_membership(db, org_id=org.id, user_id=viewer.id)
    percent = _proposal(db, org, viewer, "Budget 100% Ready", status="draft")
    underscore = _proposal(db, org, viewer, "literal_under_score", status="draft")
    unicode_row = _proposal(db, org, viewer, "Café Assembly", status="deliberation")
    _proposal(db, org, viewer, "Budget 1000 Ready", status="draft")
    headers = _headers(viewer)
    cases = (("%", percent.id), ("_", underscore.id), ("Café", unicode_row.id))
    for query, expected_id in cases:
        response = client.get(
            f"/api/orgs/{org.slug}/proposal-management-feed",
            params={"q": query},
            headers=headers,
        )
        assert response.status_code == 200
        assert [item["id"] for item in response.json()["items"]] == [expected_id]
    blank = client.get(
        f"/api/orgs/{org.slug}/proposal-management-feed",
        params={"q": "   "}, headers=headers,
    )
    assert len(blank.json()["items"]) == 4
    overlength = client.get(
        f"/api/orgs/{org.slug}/proposal-management-feed",
        params={"q": "x" * 101}, headers=headers,
    )
    assert overlength.status_code == 422
    bad_status = client.get(
        f"/api/orgs/{org.slug}/proposal-management-feed?status=archived",
        headers=headers,
    )
    assert bad_status.status_code == 422
    malformed = client.get(
        f"/api/orgs/{org.slug}/proposal-management-feed?cursor=!!!",
        headers=headers,
    )
    assert malformed.status_code == 422
    assert malformed.json()["detail"]["code"] == "invalid_management_cursor"


def test_structural_eligibility_parity_including_cosign_set_end(db):
    user = make_user(db, "p104-eligibility")
    org = _org(db, "p104-eligibility")
    rows = {
        "draft": _proposal(db, org, user, "draft", status="draft"),
        "ordinary": _proposal(db, org, user, "ordinary", status="deliberation"),
        "cosign": _proposal(
            db, org, user, "cosign", status="deliberation", cosign=True,
        ),
        "voting": _proposal(db, org, user, "voting", status="voting"),
        "closed": _proposal(db, org, user, "closed", status="passed"),
    }
    assert eligible_operations(rows["draft"]) == ["draft_to_deliberation"]
    assert eligible_operations(rows["ordinary"]) == [
        "deliberation_to_voting", "schedule_start", "set_end",
    ]
    assert eligible_operations(rows["cosign"]) == ["set_end"]
    assert eligible_operations(rows["voting"]) == ["set_end"]
    assert eligible_operations(rows["closed"]) == []
    for operation in (
        "draft_to_deliberation", "deliberation_to_voting", "schedule_start", "set_end",
    ):
        for proposal in rows.values():
            assert (operation in eligible_operations(proposal)) == is_structurally_eligible(
                proposal, operation,
            )


def test_management_eligible_filters_match_metadata_and_do_not_grant_actions(client, db):
    member = make_user(db, "p104-filter-member")
    org = _org(db, "p104-filter-org")
    make_org_membership(db, org_id=org.id, user_id=member.id)
    rows = [
        _proposal(db, org, member, "draft", status="draft"),
        _proposal(db, org, member, "ordinary", status="deliberation"),
        _proposal(db, org, member, "cosign", status="deliberation", cosign=True),
        _proposal(db, org, member, "voting", status="voting"),
        _proposal(db, org, member, "closed", status="passed"),
    ]
    headers = _headers(member)
    all_response = client.get(
        f"/api/orgs/{org.slug}/proposal-management-feed?limit=100",
        headers=headers,
    )
    metadata = {
        item["id"]: set(item["eligible_operations"])
        for item in all_response.json()["items"]
    }
    assert set(metadata) == {row.id for row in rows}
    for operation in (
        "draft_to_deliberation", "deliberation_to_voting", "schedule_start", "set_end",
    ):
        filtered = client.get(
            f"/api/orgs/{org.slug}/proposal-management-feed",
            params={"eligible_for": operation, "limit": 100},
            headers=headers,
        )
        filtered_ids = {item["id"] for item in filtered.json()["items"]}
        assert filtered_ids == {
            proposal_id
            for proposal_id, operations in metadata.items()
            if operation in operations
        }
        assert all(
            operation in item["eligible_operations"]
            for item in filtered.json()["items"]
        )
    # Listing structural eligibility is not an action grant: mutations still
    # enforce their permission keys and reload every ID.
    denied = client.post(
        f"/api/orgs/{org.slug}/proposals/bulk-advance-to-deliberation",
        json={"proposal_ids": [rows[0].id]},
        headers=headers,
    )
    assert denied.status_code == 403


def test_sub_org_deletion_impact_is_exact_authorized_and_race_safe(client, db):
    steward = make_user(db, "p104-delete-steward")
    member = make_user(db, "p104-delete-member")
    parent = _org(db, "p104-delete-parent")
    sub = _org(db, "p104-delete-child", parent=parent.id)
    make_org_membership(db, org_id=parent.id, user_id=steward.id, role="steward")
    make_org_membership(db, org_id=parent.id, user_id=member.id, role="member")
    path = f"/api/orgs/{parent.slug}/sub-orgs/{sub.slug}/deletion-impact"
    denied = client.get(path, headers=_headers(member))
    assert denied.status_code == 403
    initial = client.get(path, headers=_headers(steward))
    assert initial.status_code == 200
    assert initial.json() == {"topic_count": 0, "proposal_count": 0, "can_delete": True}

    archived = _proposal(
        db, parent, steward, "archived still blocks", status="withdrawn", sub=sub.id,
    )
    db.flush()
    impact = client.get(path, headers=_headers(steward))
    assert impact.json() == {"topic_count": 0, "proposal_count": 1, "can_delete": False}
    delete = client.delete(
        f"/api/orgs/{parent.slug}/sub-orgs/{sub.slug}", headers=_headers(steward),
    )
    assert delete.status_code == 409
    assert archived.id in {row.id for row in db.query(models.Proposal).all()}


def test_polis_proposal_links_exact_membership_visibility_and_cursor(client, db):
    member = make_user(db, "p104-polis-member")
    sub_member = make_user(db, "p104-polis-sub-member")
    admin = make_user(db, "p104-polis-admin")
    org = _org(db, "p104-polis")
    private_sub = _org(db, "p104-polis-private", parent=org.id, private=True)
    make_org_membership(db, org_id=org.id, user_id=member.id)
    make_org_membership(db, org_id=org.id, user_id=sub_member.id)
    make_sub_org_membership(db, sub_org_id=private_sub.id, user_id=sub_member.id)
    make_org_membership(db, org_id=org.id, user_id=admin.id, role="admin")
    polis = _polis(db, org, admin)
    hidden_polis = _polis(
        db, org, admin, title="Private Polis", sub=private_sub.id,
    )
    other_org = _org(db, "p104-polis-other")
    other_polis = _polis(db, other_org, admin, title="Other Polis")
    expected = []
    tied = datetime(2026, 8, 30, 12, 0)
    for index in range(27):
        expected.append(_proposal(
            db, org, admin, f"linked-{index}", status="deliberation",
            when=tied + timedelta(minutes=index),
            links=["other", polis.id] if index % 2 else [polis.id],
        ))
    hidden = _proposal(
        db, org, admin, "hidden-private", status="deliberation",
        sub=private_sub.id, links=[polis.id],
    )
    _proposal(db, org, admin, "lookalike-prefix", links=[polis.id + "suffix"])
    _proposal(db, org, admin, "lookalike-suffix", links=["prefix" + polis.id])
    headers = _headers(member)
    first = client.get(
        f"/api/orgs/{org.slug}/polises/{polis.id}/proposal-links?limit=25",
        headers=headers,
    )
    assert first.status_code == 200
    assert len(first.json()["items"]) == 25 and first.json()["has_more"] is True
    second = client.get(
        f"/api/orgs/{org.slug}/polises/{polis.id}/proposal-links",
        params={"limit": 25, "cursor": first.json()["next_cursor"]},
        headers=headers,
    )
    seen = [item["id"] for item in first.json()["items"] + second.json()["items"]]
    assert len(seen) == len(set(seen)) == 27
    assert set(seen) == {row.id for row in expected}
    assert hidden.id not in seen
    sub_member_page = client.get(
        f"/api/orgs/{org.slug}/polises/{polis.id}/proposal-links?limit=100",
        headers=_headers(sub_member),
    )
    assert hidden.id in {item["id"] for item in sub_member_page.json()["items"]}
    admin_page = client.get(
        f"/api/orgs/{org.slug}/polises/{polis.id}/proposal-links?limit=100",
        headers=_headers(admin),
    )
    assert hidden.id in {item["id"] for item in admin_page.json()["items"]}
    malformed = client.get(
        f"/api/orgs/{org.slug}/polises/{polis.id}/proposal-links?cursor=bad",
        headers=headers,
    )
    assert malformed.status_code == 422
    hidden_polis_response = client.get(
        f"/api/orgs/{org.slug}/polises/{hidden_polis.id}/proposal-links",
        headers=headers,
    )
    assert hidden_polis_response.status_code == 404
    visible_private_polis = client.get(
        f"/api/orgs/{org.slug}/polises/{hidden_polis.id}/proposal-links",
        headers=_headers(sub_member),
    )
    assert visible_private_polis.status_code == 200
    wrong_org = client.get(
        f"/api/orgs/{org.slug}/polises/{other_polis.id}/proposal-links",
        headers=headers,
    )
    assert wrong_org.status_code == 404


def test_legacy_arrays_are_bounded_stable_deprecated_and_visibility_first(client, db):
    member = make_user(db, "p104-legacy-member")
    admin = make_user(db, "p104-legacy-admin")
    org = _org(db, "p104-legacy", public=True)
    private_sub = _org(db, "p104-legacy-private", parent=org.id, private=True)
    make_org_membership(db, org_id=org.id, user_id=member.id)
    make_org_membership(db, org_id=org.id, user_id=admin.id, role="admin")
    private_row = _proposal(db, org, admin, "private-admin-visible", sub=private_sub.id)
    for index in range(60):
        _proposal(
            db, org, admin, f"legacy-{index}",
            when=datetime(2026, 8, 30, 12, 0) + timedelta(seconds=index),
        )
    db.flush()
    org_path = f"/api/orgs/{org.slug}/proposals?limit=50"
    first = client.get(org_path, headers=_headers(admin))
    assert first.status_code == 200 and len(first.json()) == 50
    assert first.headers["deprecation"] == "true"
    assert first.headers["x-has-more"] == "true"
    assert first.headers["x-next-offset"] == "50"
    assert 'rel="next"' in first.headers["link"]
    second = client.get(
        f"/api/orgs/{org.slug}/proposals?limit=50&offset=50",
        headers=_headers(admin),
    )
    ids = [row["id"] for row in first.json() + second.json()]
    assert len(ids) == len(set(ids)) == 61

    public = client.get(f"/api/orgs/{org.slug}/public/proposals?limit=50")
    assert public.status_code == 200 and len(public.json()) == 50
    assert public.headers["deprecation"] == "true"
    assert public.headers["x-has-more"] == "true"
    assert public.headers["x-next-offset"] == "50"
    public_second = client.get(
        f"/api/orgs/{org.slug}/public/proposals?limit=50&offset=50",
    )
    public_ids = [row["id"] for row in public.json() + public_second.json()]
    assert len(public_ids) == len(set(public_ids)) == 60
    assert public_second.headers["x-has-more"] == "false"
    global_page = client.get("/api/proposals?limit=50", headers=_headers(admin))
    assert global_page.status_code == 200 and len(global_page.json()) == 50
    assert global_page.headers["deprecation"] == "true"
    assert global_page.headers["x-has-more"] == "true"
    assert global_page.headers["x-next-offset"] == "50"
    next_global = client.get(
        "/api/proposals?limit=50&offset=50", headers=_headers(admin),
    )
    global_list = global_page.json() + next_global.json()
    global_ids = {row["id"] for row in global_list}
    assert len(global_list) == len(global_ids) == 61
    assert next_global.headers["x-has-more"] == "false"
    assert private_row.id in global_ids  # parent admin, no private-sub membership
    hidden_for_member = client.get(org_path, headers=_headers(member))
    assert private_row.id not in {row["id"] for row in hidden_for_member.json()}

    default_page = client.get(
        f"/api/orgs/{org.slug}/proposals", headers=_headers(admin),
    )
    assert len(default_page.json()) == 25
    assert client.get(
        f"/api/orgs/{org.slug}/proposals?limit=51", headers=_headers(admin),
    ).status_code == 422
    assert client.get(
        f"/api/orgs/{org.slug}/proposals?offset=-1", headers=_headers(admin),
    ).status_code == 422

    openapi = app.openapi()
    for path in (
        "/api/proposals",
        "/api/orgs/{org_slug}/proposals",
        "/api/orgs/{org_slug}/public/proposals",
    ):
        assert openapi["paths"][path]["get"]["deprecated"] is True


def test_phase104_route_query_budgets_and_compact_projection(client, db):
    steward = make_user(db, "p104-budget-steward")
    org = _org(db, "p104-budget")
    sub = _org(db, "p104-budget-sub", parent=org.id)
    make_org_membership(db, org_id=org.id, user_id=steward.id, role="steward")
    make_sub_org_membership(db, sub_org_id=sub.id, user_id=steward.id, role="steward")
    polis = _polis(db, org, steward, title="Budget Polis")
    for index in range(75):
        _proposal(
            db, org, steward, f"budget-{index}", status="deliberation",
            sub=sub.id if index % 2 else None,
            links=[polis.id] if index < 30 else None,
            when=datetime(2026, 8, 30, 12, 0) + timedelta(seconds=index),
        )
    db.flush()
    statements = []

    def count(_conn, _cursor, statement, _parameters, _context, _executemany):
        statements.append(statement)

    headers = _headers(steward)
    event.listen(db.bind, "before_cursor_execute", count)
    try:
        management = client.get(
            f"/api/orgs/{org.slug}/proposal-management-feed?limit=50",
            headers=headers,
        )
        management_count = len(statements)
        management_sql = list(statements)
        statements.clear()
        filtered = client.get(
            f"/api/orgs/{org.slug}/proposal-management-feed",
            params={
                "limit": 50,
                "status": "deliberation",
                "sub_org_id": sub.id,
                "q": "budget-",
                "eligible_for": "set_end",
            },
            headers=headers,
        )
        filtered_count = len(statements)
        statements.clear()
        impact = client.get(
            f"/api/orgs/{org.slug}/sub-orgs/{sub.slug}/deletion-impact",
            headers=headers,
        )
        impact_count = len(statements)
        statements.clear()
        links = client.get(
            f"/api/orgs/{org.slug}/polises/{polis.id}/proposal-links?limit=25",
            headers=headers,
        )
        links_count = len(statements)
    finally:
        event.remove(db.bind, "before_cursor_execute", count)

    assert management.status_code == 200 and len(management.json()["items"]) == 50
    assert management_count <= 10
    proposal_selects = [
        sql for sql in management_sql
        if "FROM proposals" in sql and "ORDER BY" in sql
    ]
    assert proposal_selects and all("proposals.body" not in sql for sql in proposal_selects)
    assert filtered.status_code == 200 and filtered_count <= 12
    assert impact.status_code == 200 and impact_count <= 6
    assert links.status_code == 200 and links_count <= 8
    print(
        "phase104 route SQL counts "
        f"management={management_count} filtered={filtered_count} "
        f"impact={impact_count} polis_links={links_count}"
    )


def test_frontend_has_no_legacy_proposal_array_gets():
    root = Path(__file__).resolve().parents[2] / "frontend" / "src"
    offenders = []
    legacy_get = re.compile(
        r"api\.get\(\s*([`'\"])"
        r"(?:/api/proposals|/api/orgs/\$\{[^}]+\}/(?:public/)?proposals)"
        r"(?:\?[^`'\"]*)?\1",
        re.MULTILINE,
    )
    for path in list(root.rglob("*.jsx")) + list(root.rglob("*.js")):
        source = path.read_text(encoding="utf-8")
        for match in legacy_get.finditer(source):
            line_number = source.count("\n", 0, match.start()) + 1
            offenders.append(f"{path.relative_to(root)}:{line_number}")
    assert offenders == [], f"legacy proposal-array GET callers remain: {offenders}"
