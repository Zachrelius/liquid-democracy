# Phase 7.5 — Privacy and Access Hardening

**Type:** Backend security/privacy work plus a small frontend feature.
**Dependencies:** Phase 7C complete (whatever state `master` is in when 7C ships, including any 7C cleanup).
**Goal:** Bring the platform's actual privileged-access behavior into line with the privacy claims on the public Security & Trust page, and give users a way to verify those claims for themselves. Specifically: redact ballot content from the default audit log endpoint, audit access to system-wide delegation data, document the platform-admin privilege explicitly, and add a user-facing access log so users can see when their data has been viewed by privileged operators. Frame the current demo deployment's institutional status honestly in deployment docs.

---

## Context

A 2026-04-26 audit of the draft Security & Trust page against the actual codebase found that platform-level admin access (`is_admin=True` users) is broader than what the page describes as "private by default — access requires consent." Three specific gaps were identified in the codebase audit, all in `backend/routes/admin.py`:

**Gap 1: `/api/admin/audit` returns ballot contents.**

The audit log is queried via `GET /api/admin/audit` with filtering by action, actor, target, and time range. Every entry returned includes the full `details` JSON payload. For `vote.cast` events specifically, that payload includes both `vote_value` (binary votes) and the full `ballot` object (`{"approvals": [...]}` or `{"ranking": [...]}` for multi-option votes). A platform admin can therefore read every individual ballot ever cast, with full identity attribution via `actor_id`. This is verified by reading `backend/routes/votes.py` lines 105-122 and 144-160 — both the `vote.cast` and update paths log the literal ballot.

**Gap 2: `/api/admin/delegation-graph` returns the full system-wide delegation graph and access isn't audited.**

A platform admin can call this endpoint and receive every user's delegate relationships across all topics, including from organizations they aren't a member of. The endpoint itself doesn't log audit events when accessed, so even the visibility of who-looked-at-the-graph is missing.

**Gap 3: The `is_admin` privilege isn't documented in code or in `SECURITY_REVIEW.md`.**

The role is implicit. Future contributors (or future planning agents) can't easily audit what platform admins can do because the boundaries aren't written down.

The Security & Trust page revision (sent to the content agent) acknowledges the current state honestly and points at this pass as the technical fix. Until 7.5 ships, the page can't fully claim consent-gated access; once 7.5 ships, it can.

This pass also adds a user-facing "who has accessed my data" view in account settings — the institutional-privacy claim that "all access is logged" is more credible when users can actually see those logs themselves.

The pass is intentionally narrow. Operator agreements, oversight bodies, encrypted ballot storage, and other deeper institutional changes are deferred (already documented in the roadmap's deferred-features section).

---

## Design Decisions Locked In Before Dispatch

### Decision 1: Two-tier audit log access, with elevation logged

The default `GET /api/admin/audit` endpoint redacts ballot content from response payloads. A platform admin viewing the audit log sees that a vote was cast (`action: "vote.cast"`, actor, timestamp, IP, target proposal) but **not** the ballot itself (`vote_value` and `ballot` fields in `details` are replaced with a redacted indicator).

A separate endpoint, `GET /api/admin/audit/ballots/{audit_log_id}`, returns the unredacted ballot content for a single audit entry. Calling this endpoint:
- Requires `is_admin=True` (same gating as the main audit endpoint)
- Itself logs an audit event (`admin.audit_ballot_viewed`) with the requesting admin's user ID, IP, the ID of the audit entry being viewed, and a reason field
- Requires the requesting admin to provide a `reason` parameter (free-text) explaining why they're elevating access — the reason is stored in the new audit event for retrospective review

The reason field is intentionally simple — there's no validation, no approval workflow, no "approved by another admin" gating. Stage 1 just logs the elevation; the audit trail enables retrospective accountability without adding governance machinery the platform isn't ready for. Stage 2 (multi-admin approval, etc.) is deferred to Phase 12 or later.

### Decision 2: Redact at response time, not at log time

The audit log entries themselves keep their full `details` payloads in the database — including ballot content. Only the `GET /api/admin/audit` endpoint redacts at response-serialization time. The unredacted endpoint reads the same underlying data and returns it.

Rationale: redacting at log time would lose information that's legitimately needed (the elevated endpoint, debugging, future migrations to stronger privacy tech like encrypted-at-rest ballots). Redaction at the response boundary is the standard pattern and keeps options open.

The redacted form should clearly indicate what was redacted, not look like the data was never there. Suggested format:

```json
"details": {
  "proposal_id": "...",
  "is_direct": true,
  "previous_value": "<redacted>",
  "vote_value": "<redacted>",
  "ballot": "<redacted>",
  "delegate_chain": null,
  "_redacted_fields": ["vote_value", "ballot", "previous_value"]
}
```

The `_redacted_fields` array makes redaction explicit so frontend consumers can render "this data exists but isn't shown in this view" rather than guessing.

### Decision 3: Redaction applies to all action types that contain ballot data

Currently, ballot content lives in `vote.cast` events. But the audit log is a JSON-payload table, and other actions might log ballot data in the future (vote-retraction, delegation-driven vote computation, etc.). Build the redaction as a per-action allowlist of which fields to redact for which action types, so future actions can be added by extending the allowlist, not by patching the endpoint each time.

Initial redaction map:

```python
REDACTED_DETAIL_FIELDS = {
    "vote.cast": ["vote_value", "ballot", "previous_value"],
    "vote.retracted": ["previous_value", "ballot", "previous_ballot"],
    # Other actions: no redaction by default
}
```

Other action types (`delegation.created`, `follow.requested`, etc.) don't currently contain ballot-style sensitive data and pass through unredacted. If future actions add sensitive fields, extend this map.

### Decision 4: Audit access to the delegation-graph endpoint

Add `log_audit_event` call to `GET /api/admin/delegation-graph` so each access generates an `admin.delegation_graph_viewed` audit entry. The entry includes:
- `actor_id`: the requesting admin
- `target_type`: `"system"` (since the graph is system-wide)
- `target_id`: a sentinel like `"system_delegation_graph"` (no real target row exists)
- `details`: `{"node_count": <int>, "edge_count": <int>}`
- `ip_address`: from request

This makes the access visible in the same audit log that admin-level access shouldn't be exempt from.

Apply the same pattern to `GET /api/admin/users` (returns full user list including admin-flagged users) — log access as `admin.user_list_viewed`.

The seed and time-simulation endpoints are already gated by `debug=False` and don't need additional logging — they're never reachable in production.

### Decision 5: User-facing access log in settings

Add a new section to the user's settings page: "Data access history." Shows a chronological list of times the user's data was accessed by anyone other than themselves.

Three categories of access surface in this view:

1. **Other users via standard visibility rules.** When another user viewed the current user's profile, voting record, or follow list — readable from existing audit events (`profile.viewed`, etc., if they exist; if not, this is a small instrumentation add).

2. **Org admins viewing analytics or member lists.** When org admins ran analytics or pulled member lists that included this user — readable from `analytics.viewed`, `members.listed`, etc.

3. **Platform admin access.** When platform admins viewed the audit log, delegation graph, or elevated-ballot endpoint in a way that touched this user's data — readable from `admin.audit_ballot_viewed`, `admin.delegation_graph_viewed`, `admin.user_list_viewed`. Note that platform admin access via the standard audit log endpoint **doesn't** appear in the user's view (because ballots are redacted there); only elevated access does.

The view shows: timestamp, accessor (user ID, role context — "Org admin of [Org Name]" or "Platform admin"), what was accessed (high-level — "Your voting record" or "Your delegation graph entry"), reason if provided.

Backend: new endpoint `GET /api/users/me/access-log` returns the user's access history. It queries `audit_log` for entries where the `details` payload references the current user (this requires deciding which audit events count as "accessing this user's data" — see scope notes below).

Frontend: new component in the settings page, similar pattern to existing settings sections.

### Decision 6: Documentation, not just code

Document the `is_admin` privilege explicitly in two places:

1. **In code**: a docstring at the top of `backend/auth.py`'s `get_current_admin` dependency function describing what `is_admin=True` permits. Plus a comment in `backend/routes/admin.py` listing the endpoints this role gates.

2. **In `SECURITY_REVIEW.md`**: a new "Privileged Access Tiers" section listing the platform admin role, what it can do, what it explicitly cannot do (e.g., it can't unilaterally change another user's password; it can't impersonate users; it can't bypass the elevation/audit requirement for ballot content), and the scope of the org admin role for contrast.

Documentation on its own doesn't change behavior, but it makes future audits straightforward and makes the security claims on the public page verifiable against a written reference.

### Decision 7: Frame the demo deployment in `DEPLOYMENT.md`

Add a section to `DEPLOYMENT.md` titled "Current Deployment Status" that describes:
- The `liquiddemocracy.us` deployment is a public demo run informally by the project's founder
- There is currently no operator agreement, no independent oversight, no separation between platform operations and the founder's individual access
- This is appropriate for the demo stage but would need to change before the platform is used for binding decisions by real organizations
- A pointer to the deferred-features roadmap items (formal operator agreements, independent oversight body) that describe the path forward

This is a documentation change, not a code change, but it puts the institutional state in writing where contributors and future planning agents can reference it.

---

## Scope

### Backend

**1. Audit log redaction (`backend/routes/admin.py`)**

Modify the `GET /api/admin/audit` endpoint to apply field-level redaction to the `details` payload of returned entries based on the per-action allowlist (Decision 3).

Implementation:
- Define `REDACTED_DETAIL_FIELDS` as a module-level constant in `backend/routes/admin.py` (or a dedicated `audit_redaction.py` if cleaner).
- After the query and before serialization, iterate over each entry. If the entry's `action` is in `REDACTED_DETAIL_FIELDS`, replace each listed field in `details` with the string `"<redacted>"` and add a `_redacted_fields` array listing which fields were redacted.
- Schema (`AuditLogOut` in `backend/schemas.py`) doesn't need to change — the `details` field is already a generic JSON column. The redacted form is still valid JSON.

**2. New elevated endpoint: `GET /api/admin/audit/ballots/{audit_log_id}`**

Returns the full unredacted entry for a single audit log row.

Implementation:
- New route in `backend/routes/admin.py`.
- Path parameter: `audit_log_id` (the UUID of the audit entry).
- Required query parameter: `reason` (string, non-empty, max 500 chars). Reject with 400 if missing or empty.
- Gated by `is_admin=True` via `Depends(auth_utils.get_current_admin)` (same as existing admin endpoints).
- Fetches the audit log row by ID. Returns the unredacted entry as `AuditLogOut`.
- Before returning, calls `log_audit_event` with:
  - `action`: `"admin.audit_ballot_viewed"`
  - `target_type`: `"audit_log"`
  - `target_id`: the audit_log_id being viewed
  - `actor_id`: the requesting admin's user ID
  - `details`: `{"reason": <reason>, "viewed_action": <the action of the entry being elevated>, "viewed_actor_id": <actor_id of the entry being elevated>}`
  - `ip_address`: from request
- The `viewed_actor_id` field in the details lets the affected user (the original voter) see in their access log that someone elevated to view their ballot.

**3. Audit access to system-wide endpoints**

Add `log_audit_event` calls to:
- `GET /api/admin/delegation-graph`: action `"admin.delegation_graph_viewed"`, target_type `"system"`, target_id `"system_delegation_graph"`, details `{"node_count": ..., "edge_count": ...}`.
- `GET /api/admin/users`: action `"admin.user_list_viewed"`, target_type `"system"`, target_id `"system_user_list"`, details `{"user_count": ...}`.

These log events themselves don't contain sensitive data, so they're fine appearing in the (now-redacted) audit log without further protection.

**4. User-facing access log endpoint**

New endpoint: `GET /api/users/me/access-log`

Implementation:
- Located in `backend/routes/users.py` (or wherever the existing `/users/me` endpoints live).
- Gated by standard authentication.
- Query parameters: `limit` (default 50, max 200), `offset` (default 0), optional `since` and `until` date filters.
- Returns audit log entries that represent access to the current user's data. The query needs to identify "data access" events:
  - Direct: `target_id == current_user.id` AND action in `["profile.viewed", "votes.viewed", ...]` (set TBD; see notes).
  - Indirect: action in `["admin.audit_ballot_viewed", "admin.delegation_graph_viewed", "admin.user_list_viewed", "analytics.viewed", "members.listed"]` AND the entry's details reference `current_user.id` (e.g., the elevated-ballot view's `viewed_actor_id` field equals current_user.id).

The exact set of "data access" actions is something the dev team needs to enumerate during implementation. Some are existing (profile views, votes lookups), some are new from this pass (admin elevations). Build a helper function `get_user_access_log(user_id, db, ...)` that encapsulates the query and is testable.

**Important scope note:** for the indirect category, the implementation queries the JSON `details` field for matching user IDs. SQLAlchemy + PostgreSQL handles JSON path queries cleanly; SQLite is more limited. The dev team should pick an approach that works in both backends (likely a Python-side filter after a coarser DB query, or a JSON-path query that degrades gracefully on SQLite). Test on both.

Response shape: list of `AccessLogEntry` objects with fields `timestamp`, `accessor_display_name` (or `"Platform admin"` / `"Org admin of [Org Name]"` based on role), `action_type` (high-level description like `"Viewed your voting record"`), `reason` (when provided, e.g., from elevated ballot views), `ip_address` (optional, hidden in display by default).

**5. Documentation updates**

- `backend/auth.py`: docstring on `get_current_admin` describing what `is_admin=True` enables.
- `backend/routes/admin.py`: top-of-file comment listing the endpoints this role gates and what they expose.
- `SECURITY_REVIEW.md`: new "Privileged Access Tiers" section per Decision 6.
- `DEPLOYMENT.md`: "Current Deployment Status" section per Decision 7.

**6. Backend tests**

New test file `backend/tests/test_privacy_hardening.py`. Coverage:

- **Audit log redaction:** call `GET /api/admin/audit` filtered to `vote.cast` events; assert returned entries have `vote_value` and `ballot` redacted and `_redacted_fields` populated.
- **Other actions pass through:** call `GET /api/admin/audit` filtered to `delegation.created` (or another non-redacted action); assert details are unredacted.
- **Elevated endpoint requires reason:** call `GET /api/admin/audit/ballots/{id}` without `reason`; assert 400. With empty `reason`; assert 400.
- **Elevated endpoint returns unredacted data:** call with valid `reason`; assert response includes original `vote_value` and `ballot`.
- **Elevated endpoint logs the elevation:** call with valid `reason`; assert a new `admin.audit_ballot_viewed` audit entry exists with the reason recorded.
- **Elevated endpoint requires admin:** call as non-admin; assert 403.
- **Delegation graph access logs an audit entry:** call `GET /api/admin/delegation-graph`; assert a new `admin.delegation_graph_viewed` entry exists.
- **User access log endpoint:** seed events touching a user's data (a profile view by another user, a delegation graph view by an admin, an elevated ballot view of one of the user's votes); call `GET /api/users/me/access-log`; assert all three categories appear correctly.
- **User access log doesn't include redacted-only access:** when a platform admin views the audit log without elevation, assert the user's access log doesn't show that view (because ballot content was redacted at the boundary).
- **Cross-user isolation:** user A's access log doesn't surface user B's events.

Target: 9-12 new tests. Combined with current 200, target ~210 backend tests.

### Frontend

**Settings page: data access history section**

New component (`AccessHistory.jsx` or similar) on the existing settings page, integrated into the settings layout pattern Phase 4d established.

- Fetches `GET /api/users/me/access-log` with default pagination
- Renders a chronological list of entries: each shows timestamp, accessor (with role context), what was accessed, reason if present
- Empty state: "No access events recorded. When other users, organization admins, or platform admins view your data, those events will appear here."
- Pagination: simple "Load more" button or page navigation
- Responsive layout consistent with existing settings sections

Optional polish (defer if scope creeps): filter by accessor type (others / org admin / platform admin), filter by date range, expandable details for each entry showing IP address.

**No changes to admin pages.** The redaction is server-side; the existing admin audit log viewer (if any) just renders the redacted data correctly because it reads `details` as opaque JSON. If the existing admin frontend tries to display fields like `vote_value` from the details payload, it'll show `"<redacted>"` — that's the intended behavior. If the rendering breaks (because it expects a string vote value and gets the redacted indicator), surface that as a tech debt fix in the same pass.

---

## Testing

### Backend tests

Per the scope section: ~9-12 new tests in `backend/tests/test_privacy_hardening.py`. Target combined backend test count of ~210.

### Browser tests — Suite O

Add a new suite to `browser_testing_playbook.md`. Suite N was used for Phase 7C; Suite O is the next available letter.

**O1: Admin audit log shows redacted ballots.** Log in as the platform admin. Navigate to the admin audit log view (whichever path exposes it). Filter to `vote.cast` events. Confirm the displayed entries don't show readable vote values or ballot content; the redaction indicator is visible.

**O2: Elevated ballot endpoint requires reason.** Call `GET /api/admin/audit/ballots/{some_id}` without a `reason` parameter (via the API docs page or a constructed URL). Confirm a 400 error response. Call with an empty reason — confirm 400.

**O3: Elevated ballot endpoint returns ballot when valid.** Call with a valid reason. Confirm the response includes the unredacted ballot.

**O4: Elevated access self-logs.** After O3, navigate to the audit log view filtered to `admin.audit_ballot_viewed`. Confirm the elevation just performed appears with the reason recorded.

**O5: Delegation graph access self-logs.** Call `GET /api/admin/delegation-graph`. Filter audit log to `admin.delegation_graph_viewed`. Confirm the access appears.

**O6: User access log shows other-user views.** As alice, view dr_chen's profile. Log in as dr_chen, navigate to settings → data access history. Confirm an entry appears showing alice viewed the profile.

**O7: User access log shows admin elevations.** As platform admin, elevate to view a vote ballot belonging to (say) carol. Log in as carol, navigate to settings → data access history. Confirm an entry appears showing the platform admin viewed the ballot, with the reason.

**O8: User access log empty state.** As a brand-new user with no access events, navigate to data access history. Confirm the empty state renders cleanly (not a broken layout or error).

**O9: User access log cross-user isolation.** As alice, view her own data access history. Confirm bob's access events don't appear.

**O10: Settings page integration.** Confirm the data access history section is visible on the settings page, properly styled, and consistent with other settings sections.

**O11: Regression — existing admin endpoints work.** As platform admin, verify `/api/admin/audit`, `/api/admin/delegation-graph`, `/api/admin/users` still return data. Verify the admin frontend pages that consume these endpoints still render.

### PostgreSQL smoke test

Same pattern as previous passes. Bring up docker-compose stack and verify:

1. Audit log redaction works against PostgreSQL-backed audit data (JSON field handling can differ between SQLite and PostgreSQL — this is a real risk).
2. User access log query works against PostgreSQL JSON-path lookups (Decision 5's "indirect" category specifically).
3. Elevated endpoint logs the elevation event.

Zero backend tracebacks. If any 500s occur, diagnose from logs.

### Production deploy verification

After merge to `master` and Railway auto-deploys:

- Verify `/api/admin/audit` responses on prod show redacted ballots when filtered to `vote.cast`.
- Verify the elevated endpoint works on prod (use a valid reason, view the result, then check that the elevation logged itself).
- Verify the user access history section on settings renders for at least one user on prod.

Capture screenshots of (a) redacted audit log entry, (b) successful elevated ballot view (showing both data and the reason captured), (c) user access history view with at least one entry. Save to `test_results/phase7_5_screenshots/` and commit.

---

## Definition of Done

- All six backend scope items implemented (audit redaction, elevated endpoint, system-endpoint audit logging, user access log endpoint, documentation updates, tests).
- Frontend data access history section live on settings page.
- All ~9-12 new backend tests pass. Combined backend test count ~210.
- Suite O (11 tests) all pass via Claude-in-Chrome.
- PostgreSQL smoke test passes — audit redaction and JSON queries work cleanly.
- `SECURITY_REVIEW.md` updated with "Privileged Access Tiers" section.
- `DEPLOYMENT.md` updated with "Current Deployment Status" section.
- `backend/auth.py` and `backend/routes/admin.py` have updated docstrings/comments.
- `PROGRESS.md` updated with Phase 7.5 section: what was built, what's now redacted, what the user-facing access log shows, screenshot path, any new tech debt.
- `future_improvements_roadmap.md` updated: Phase 7.5 marked complete.
- Production deploy via merge to `master`. Post-deploy verification confirms redaction and access log work on prod.
- Screenshots committed to `test_results/phase7_5_screenshots/`.

---

## Out of Scope

- **Multi-admin approval workflows** for elevated audit access. Stage 1 just logs elevation; multi-admin approval is deferred to Phase 12 or later.
- **Operator agreement legal frameworks** — aspirational, requires legal work, deferred.
- **Independent oversight body formation** — governance work, deferred.
- **Encrypted ballot storage** — Tier 3 cryptographic work, deferred (already in roadmap deferred section).
- **Org-admin scope tightening.** Org admins already only see their own org's data; this pass is specifically about platform-level admin access. If a separate org-admin issue surfaces during implementation, log it as tech debt.
- **Bulk redaction of historical audit entries.** Existing entries from before 7.5 still contain ballot data in their `details` payloads; the redaction at response time means they're no longer exposed, but the data is still in the database. Migrating historical entries to delete sensitive payloads is a one-time data migration that's out of scope (and arguably should not happen — the data being there but not exposed is the standard pattern).
- **Anonymizing IP addresses in audit log.** IP addresses are useful for abuse detection and are scoped to admin-only views. Anonymization would reduce utility for legitimate operations.
- **Removing `is_admin` privilege entirely** or splitting it into multiple sub-roles. The role exists for legitimate operations; this pass narrows what it implicitly grants, doesn't restructure the role itself. Stage 2 (Phase 12 territory) might introduce more granular privileges.
- **Rate limiting on the elevated endpoint** beyond what already exists on auth endpoints. Worth adding eventually but not in this pass.
- **E2E-verifiable voting integration** — Tier 3 future work.

If the dev team discovers adjacent issues during execution, log them as new tech debt rather than expanding this spec.

---

## Notes for the Dev Team

- **Read `backend/audit_utils.py` and `backend/routes/admin.py` first.** The current audit log structure is the foundation for everything in this spec. The redaction logic plugs into the response path of the existing `GET /api/admin/audit` endpoint; the elevated endpoint mirrors the same query plus a self-logging side effect.

- **The `_redacted_fields` array in the response is non-trivially useful.** It lets future frontend code render "this data exists but is redacted in this view" rather than rendering nothing or rendering unhelpful generic redaction indicators. Don't drop it as an unnecessary complication.

- **Decision 3 redaction map is intentionally extensible.** Don't hard-code the field names in conditional branches in the endpoint code. Use the lookup-table pattern so future actions can be added by extending the dict.

- **The user access log query is the trickiest part of this pass.** "What does it mean for an audit event to be access to a specific user's data?" is a small ontology question. Some events (`profile.viewed` with target_id == user_id) are obvious. Some (`admin.audit_ballot_viewed` where the elevated entry's `viewed_actor_id` == user_id) require reading nested JSON fields. SQLite vs PostgreSQL JSON support differs here. Build the query as a helper function, test on both backends, and don't over-engineer the matching rules — start with the obvious cases and extend if the spec's "data access events" list misses anything important.

- **Don't break existing admin endpoints.** The redaction is additive to the response — admins can still see actor, action, timestamp, target, IP. They just lose ballot content. Verify that any frontend admin views that consume `/api/admin/audit` still render correctly (possibly with the redacted indicator visible where ballot content used to render). The redaction should not introduce 500s or break pagination.

- **PostgreSQL JSON path query gotcha.** SQLAlchemy supports both SQLite JSON1 functions and PostgreSQL JSON operators, but the syntax differs. The user access log query that needs to look inside `details` for matching user IDs is exactly the kind of query that's prone to "works on SQLite, fails on PostgreSQL" or vice versa. Run the PostgreSQL smoke test specifically on this codepath. The Phase 6 cleanup pass found this same class of bug in another context — same lesson applies here.

- **The `_get_strategy` documentation pattern from `delegation_engine.py` is a good reference** for how to write privilege-tier docs in `SECURITY_REVIEW.md`. Concrete language about what's permitted and what isn't, not vague capability lists.

- **Suggested team structure:** Lead in delegate mode. Backend dev for the redaction, elevated endpoint, system-endpoint audit logging, user access log endpoint, all backend tests, and the documentation updates. Frontend dev for the data access history settings section. QA teammate for Suite O execution via Claude-in-Chrome, PostgreSQL smoke test, post-deploy verification, screenshots committed. The backend work is the bulk of this pass; frontend is comparatively small.

Report completion with: backend test count (~210 expected), Suite O results (X/11), PostgreSQL smoke result with specific note on whether the JSON-path queries worked on both backends, prod state after merge with confirmation that redaction is live, screenshot paths in repo, library decisions if any (likely none — this is pure backend logic + frontend rendering), any new tech debt found.
