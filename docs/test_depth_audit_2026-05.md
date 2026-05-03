# Test-Depth Audit — 2026-05

Drafted: 2026-05-03
Phase: 10.2 (W-AUDIT workstream)
Auditor: Claude Code audit dev
Branch: `phase-10-2/test-depth-audit`

## Scope and method

Walked every `@router.{get,post,patch,put,delete}` decorator in
`backend/routes/` (15 modules), every multi-tenant entity per the spec
list, and every infrastructure boundary the request path crosses.

Per-endpoint posture:
- **PASS** — at least one test asserts the side-effect / invariant /
  boundary behavior such that the test would fail if that behavior
  broke. Indirect assertions count (e.g., audit-log row asserted in
  place of email-send mock).
- **GAP** — code is correct but no test guards it; recommend a test.
- **BUG** — auditor identified a real bug while reading code; fix
  deferred to W-FIX-A. Do not lump in with mere coverage holes.

Generous interpretation of "covered" applied throughout. Where multiple
sibling endpoints share the same shape, the GAP is consolidated.

---

## Class A: External-touching workflows

### Endpoint: POST /api/auth/register
- **Status:** GAP
- **Existing test:** `tests/test_invitation_flow.py::test_register_with_invitation_token_skips_demo_auto_join` (covers register + invitation consumption side effects). No test exercises the bare-register happy path or the email-send side effect.
- **What is asserted today:** Invitation consumption emits audit row + creates membership; demo auto-join skipped under `IS_PUBLIC_DEMO=true` when invitation present; bad-token register returns 400.
- **Side-effect coverage:** `background_tasks.add_task(send_verification_email, ...)` is NEVER asserted. Returns 201 + creates user is also NOT directly tested for the no-invitation path. The first-user auto-verify branch has no test.
- **Recommended test 1:** `tests/test_auth_register.py::test_register_queues_verification_email`. Monkeypatch `routes.auth.send_verification_email` (or pass a `BackgroundTasks` capture stub via dependency override) and assert it was scheduled with `(user.email, token_from_db, settings.base_url)` after a 201.
- **Recommended test 2:** `tests/test_auth_register.py::test_register_first_user_skips_email_send_and_auto_verifies`. Empty DB → register → assert `email_verified=True`, `is_admin=True`, and that the email-send mock was NOT scheduled.
- **Recommended test 3:** `tests/test_auth_register.py::test_register_audit_emits_user_registered`. Plain register (not first-user) → assert `user.registered` audit row with the expected detail shape.

### Endpoint: POST /api/auth/login
- **Status:** GAP
- **Existing test:** `tests/test_invitation_flow.py::test_login_with_invitation_token_*` covers the invitation-token consumption branches (4 tests).
- **What is asserted today:** Invitation consumption on login (success / idempotent / mismatch / unchanged-when-omitted).
- **Side-effect coverage:** Bare-login happy path + `user.login` audit emission + refresh-token row creation are NOT directly tested.
- **Recommended test:** `tests/test_auth_login.py::test_login_emits_user_login_audit_and_creates_refresh_token`. Login → assert `user.login` audit row + `RefreshToken` row exists with `revoked_at IS NULL`.

### Endpoint: POST /api/auth/refresh
- **Status:** GAP
- **Existing test:** None found.
- **Side-effect coverage:** Token rotation (old revoked, new issued) and 401 paths (revoked / expired / unknown) untested.
- **Recommended test:** `tests/test_auth_tokens.py::test_refresh_rotates_token`. Refresh once → assert old token has `revoked_at` set, new token row created and returned. Plus `test_refresh_revoked_token_returns_401` and `test_refresh_expired_token_returns_401`.

### Endpoint: POST /api/auth/logout, POST /api/auth/logout-all
- **Status:** GAP
- **Existing test:** None found.
- **Recommended test:** `tests/test_auth_tokens.py::test_logout_revokes_refresh_token_and_audits` and `test_logout_all_revokes_all_active_tokens_and_audits`.

### Endpoint: POST /api/auth/verify-email
- **Status:** PASS (partial)
- **Existing test:** `tests/test_email_verification.py::test_verify_email_happy_path` (4 verify-email tests).
- **Side-effect coverage:** Verifies user flag flips to True; bad/expired tokens 400. The `_auto_join_demo_org` side effect is also covered indirectly via `tests/test_demo_mode.py::test_registration_auto_joins_demo_org_when_public_demo_flag_set` and `test_verify_tolerates_missing_demo_org_when_public_demo_flag_set` and the invitation skip branch by `tests/test_invitation_flow.py::test_register_with_invitation_token_skips_demo_auto_join`. The `user.email_verified` audit emission is NOT explicitly asserted.
- **Recommended test (low-priority polish):** `tests/test_email_verification.py::test_verify_email_emits_audit`.

### Endpoint: POST /api/auth/resend-verification
- **Status:** GAP
- **Existing test:** None.
- **Side-effect coverage:** No test asserts (a) the new `EmailVerification` row is created, (b) `send_verification_email` is awaited, (c) the 1-minute rate-limit returns 429, (d) the early "already verified" 200 short-circuit.
- **Recommended test:** `tests/test_auth_resend_verification.py::test_resend_creates_token_and_sends_email` (mock send), `::test_resend_rate_limited_after_recent_send_returns_429`, `::test_resend_short_circuits_when_already_verified`.

### Endpoint: POST /api/auth/forgot-password
- **Status:** GAP
- **Existing test:** None.
- **Side-effect coverage:** No test asserts (a) `PasswordReset` row created, (b) `send_password_reset_email` awaited with the right token, (c) audit `user.password_reset_requested` emitted, (d) account-enumeration safety (always 200).
- **Recommended test:** `tests/test_auth_password_reset.py::test_forgot_password_creates_reset_and_sends_email_for_known_email` and `::test_forgot_password_returns_same_message_for_unknown_email_no_send` (mock the email_service to assert NOT called for unknown).

### Endpoint: POST /api/auth/reset-password
- **Status:** GAP
- **Existing test:** None.
- **Side-effect coverage:** No test asserts (a) password actually changes (verify hash works), (b) all refresh tokens revoked, (c) audit `user.password_reset_completed`, (d) bad/used/expired token returns 400.
- **Recommended test:** `tests/test_auth_password_reset.py::test_reset_password_rotates_password_and_revokes_tokens_and_audits`.

### Endpoint: POST /api/auth/change-password
- **Status:** GAP
- **Existing test:** None.
- **Side-effect coverage:** No test asserts password actually changes, all refresh tokens revoked. Wrong-current-password returns 400 — also untested.
- **Recommended test:** `tests/test_auth_change_password.py::test_change_password_updates_hash_and_revokes_refresh_tokens` and `::test_change_password_rejects_wrong_current`.

### Endpoint: POST /api/auth/demo-login, GET /api/auth/demo-users
- **Status:** PASS
- **Existing test:** `tests/test_demo_mode.py::test_demo_login_*` and `test_demo_users_endpoint_*` (4 tests).
- **Side-effect coverage:** Audit `user.demo_login` asserted; refresh token issued; allowlist + flag gating fully covered.

### Endpoint: POST /api/orgs/{slug}/invitations
- **Status:** BUG-adjacent / GAP — the original Phase 9.6 hot-fix landed but no test asserts the email is scheduled. This is the canonical "invitation 201 fires but no email" regression class. **NOT a current bug** (route does call `background_tasks.add_task(send_invitation_email, ...)` per `routes/organizations.py:665`) but the absence of a regression test means a future refactor could re-break it silently.
- **Existing test:** None found that asserts the email-send call. `tests/test_sub_org_routes.py` has `test_invite_then_approve` for sub-org invites which exercises a different route (`/sub-orgs/.../invite`) and does NOT mock email. The invitation-meta endpoint is well-tested in `test_invitation_flow.py` but invitation-CREATE is unguarded.
- **Side-effect coverage:** `Invitation` row creation is implicitly relied on (admin list returns it) but the `send_invitation_email` BackgroundTask is NOT asserted.
- **Recommended test:** `tests/test_invitations_create.py::test_create_invitations_schedules_email_per_invitee`. Monkeypatch `routes.organizations.send_invitation_email`, POST with `emails: ["a@x", "b@x"]`, assert the mock was registered as a background task twice with the expected args (`email, token, org.name, org.slug, base_url`).

### Endpoint: POST /api/orgs/{slug}/invitations/{id}/resend
- **Status:** GAP — same shape as above. Route DOES wire the BackgroundTask (line 752) but there is no regression test.
- **Recommended test:** `tests/test_invitations_resend.py::test_resend_invitation_rotates_token_and_schedules_email`. Mock the email-send, POST resend, assert (a) the token on the invitation row changed, (b) `expires_at` extended, (c) the BackgroundTask was scheduled.

### Endpoint: DELETE /api/orgs/{slug}/invitations/{id}
- **Status:** GAP
- **Side-effect coverage:** No test confirms `inv.status == "revoked"` after a 204.
- **Recommended test:** `tests/test_invitations_revoke.py::test_revoke_invitation_marks_status`.

### Endpoint: POST /api/orgs/join/{token} (accept_invitation)
- **Status:** PASS (partial). The Phase 9.7 invitation-aware register/login paths via `_consume_invitation` are well-tested in `test_invitation_flow.py` (10+ tests).
- **Side-effect coverage:** Audit `invitation.accepted_via_registration` / `_via_login` asserted; demo-skip asserted; email mismatch + expiry covered. The standalone `accept_invitation` route emitting `invitation.accepted_authenticated` audit is NOT directly tested.
- **Recommended test:** `tests/test_invitation_accept_authenticated.py::test_accept_invitation_authenticated_emits_audit_and_membership` covering the third audit path called out in `routes/organizations.py:769`.

### Endpoint: POST /api/users/me/avatar
- **Status:** PASS
- **Existing test:** `tests/test_avatars.py::test_upload_jpeg_returns_urls_and_writes_two_files`, `_png_resizes_to_jpeg`, `_invalid_content_type_returns_415`, `_oversized_file_returns_413`, `_5mb_file_succeeds`, `_replace_existing_avatar_writes_new_files` (6 happy/error tests).
- **Side-effect coverage:** Filesystem writes verified (both 128 + 48 JPEGs exist); content-type guard (415) verified; oversize guard (413) verified at exactly the 6 MB boundary; replace-existing tested. `user.avatar_uploaded` audit emission is NOT explicitly asserted (low-priority gap).
- **Recommended test (polish):** `tests/test_avatars.py::test_upload_emits_user_avatar_uploaded_audit`.

### Endpoint: DELETE /api/users/me/avatar
- **Status:** PASS
- **Existing test:** `tests/test_avatars.py::test_delete_returns_204_and_removes_files`, `test_endpoint_only_touches_current_user`.
- **Side-effect coverage:** Filesystem removal asserted; cross-user safety asserted. Audit `user.avatar_removed` emission and idempotent-on-no-avatar branch (204 with no audit) are NOT explicitly asserted.
- **Recommended test (polish):** `tests/test_avatars.py::test_delete_idempotent_when_no_avatar_no_audit_emitted`.

### Endpoint: POST /api/orgs/{slug}/polises (create)
- **Status:** PASS
- **Existing test:** `tests/test_polis_routes.py::TestPolisCreate` — 6 tests across `_create_org_wide_polis_round_trip`, `_create_sub_org_polis_round_trip`, `_manual_fallback_requires_conversation_id`, `_programmatic_path_when_token_set`, `_programmatic_path_partial_seed_failure_surfaced`, `_programmatic_path_api_failure_no_orphan`.
- **Side-effect coverage:** The programmatic-path branch monkeypatches `polis_service.create_conversation` and asserts request shape (title/prompt/seed) AND that no platform row is created on `PolisAPIError` (the atomicity contract). Manual-fallback path response shape covered.

### Endpoint: PATCH /api/orgs/{slug}/polises/{id}
- **Status:** PASS
- **Existing test:** `tests/test_polis_routes.py::TestPolisArchive`, `TestPolisConnect` (3 connect + 2 archive). Plus `TestAuditEvents::test_all_polis_audit_events_fire` (mega-integration, exercises archive emitting `polis.archived` with `polis_api_call_result`).
- **Side-effect coverage:** Title diff audit, archive audit, connect audit (`polis.connected`), pol.is API archive call result captured into audit (`success/failed/no_token`).

### Endpoint: POST /api/orgs/{slug}/polises/{id}/xid
- **Status:** PASS (covered indirectly via helper). Per spec note, this route is one of the load-bearing items.
- **Existing test:** `tests/test_polis_xid.py::test_audit_event_emitted_on_first_generation_only` and `_xid_audit_actor_overridable` exercise `get_or_create_polis_xid` directly. `tests/test_polis_routes.py::TestPolisXid::test_xid_idempotent_on_repeat` exercises the route end-to-end.
- **Side-effect coverage:** **First-call-only audit invariant explicitly asserted** at the helper level (test calls `get_or_create_polis_xid` three times then asserts exactly 1 audit row). The route-level integration test confirms idempotent return value across two calls. Verdict: PASS — the bar "would the test fail if first-only audit broke" is met by the helper test.

### Endpoint: GET /api/orgs/{slug}/polises/{id}/export
- **Status:** PASS
- **Existing test:** `tests/test_polis_routes.py::TestPolisExport::test_export_admin_succeeds`, `_non_admin_blocked`, `_503_when_token_missing`, `_deanonymized_includes_user_mapping`.
- **Side-effect coverage:** Audit `polis.export_requested` covered via `TestAuditEvents`; aggregate-only payload (no contents) implicit in audit shape assertion.

### Endpoint: POST /api/admin/seed
- **Status:** GAP
- **Existing test:** `tests/test_seed_idempotency.py::*` exercises the underlying seed helpers, but the route layer (`/api/admin/seed`) and its `debug=False -> 403` gate are not tested.
- **Recommended test:** `tests/test_admin_seed.py::test_seed_endpoint_403_when_debug_off`.

### Endpoint: POST /api/admin/time-simulation
- **Status:** GAP
- **Side-effect coverage:** No test confirms the `VoteSnapshot` row is written or that the debug gate fires.
- **Recommended test:** `tests/test_admin_time_simulation.py::test_time_simulation_creates_snapshot_row` (with debug=True), `::test_time_simulation_403_when_debug_off`.

### Endpoint: GET /api/admin/delegation-graph
- **Status:** PASS
- **Existing test:** `tests/test_privacy_hardening.py::test_delegation_graph_logs_access`.
- **Side-effect coverage:** Audit row + payload shape asserted.

### Endpoint: GET /api/admin/users
- **Status:** PASS
- **Existing test:** `tests/test_privacy_hardening.py::test_user_list_logs_access`.
- **Side-effect coverage:** Audit row + `user_count` detail asserted.

### Endpoint: PATCH /api/admin/users/{id}/make-admin
- **Status:** GAP
- **Side-effect coverage:** No test asserts `is_admin` flag flips. No test asserts non-admin caller gets 403 (the dependency does this but a regression test belongs in `tests/test_admin_*`).
- **Recommended test:** `tests/test_admin_make_admin.py::test_make_admin_flips_flag` and `::test_make_admin_requires_admin_caller`.

### Endpoint: GET/PATCH /api/admin/platform-settings, PATCH /api/admin/users/{id}/org-creation-limit
- **Status:** PASS
- **Existing test:** `tests/test_org_creation_gates.py::TestPlatformSettings` and `::TestUserOrgCreationLimit` (4 tests).
- **Side-effect coverage:** Audit `platform_settings.changed` and `user.org_creation_limit_changed` payloads asserted; admin-only gate covered.

### Endpoint: GET /api/admin/audit, GET /api/admin/audit/ballots/{id}
- **Status:** PASS
- **Existing test:** `tests/test_privacy_hardening.py::test_audit_log_redacts_vote_cast`, `_passes_through_other_actions`, `_elevated_endpoint_*` (6 tests).
- **Side-effect coverage:** Redaction at response time, elevated reason validation, self-logging of elevation, admin-only gate, cross-user surfacing of elevations in target's access log.

### Endpoint: POST /api/orgs/{slug}/proposals/{id}/advance (org-scoped + global)
- **Status:** PASS (status-change side effect implicit via response). Audit `proposal.status_changed` emission has indirect coverage via `tests/test_proposal_lifecycle.py::test_full_proposal_lifecycle` which round-trips through every status. Sustained-majority compute_tally branch has dedicated tests in `test_sustained_majority_*`.

### Endpoint: POST /api/orgs/{slug}/proposals/{id}/resolve_escalation, .../resolve-tie
- **Status:** PASS
- **Existing test:** `tests/test_sustained_majority_api.py` (escalation), `test_approval_voting.py` / `test_ranked_choice_voting.py` (tie).
- **Side-effect coverage:** Audit emission `proposal.escalation_resolved` + `proposal.window_extended` (for the extend branch) asserted. Tie-resolution audit covered.

### Endpoint: POST /api/proposals/{id}/vote (and DELETE)
- **Status:** PASS
- **Existing test:** `tests/test_vote_eligibility_scope.py::test_cast_vote_*` (Phase 10.1 fix coverage), plus historical `test_approval_voting.py`, `test_ranked_choice_voting.py`. Tally broadcast over WebSocket is NOT asserted (acceptable — would need a WS test harness).
- **Side-effect coverage:** Audit `vote.cast` / `vote.retracted` payloads asserted via `test_privacy_hardening.py::test_audit_log_redacts_vote_cast`. WS `broadcast_tally` side effect untested but considered out-of-scope per spec ("would need a WS test harness").

### Endpoint: PUT/DELETE /api/delegations
- **Status:** PASS (covered by `test_delegation_*` modules — audit + graph_store mutations exercised in helper-level tests; cycle detection covered in `test_delegation_engine.py`).

### Endpoint: POST /api/delegations/request, /api/delegations/intents/*
- **Status:** PASS — `test_delegation_intents.py` covers all 9 intent lifecycle behaviors including auto-activation on follow approval and audit emission.

### Endpoint: POST /api/follows/request, PUT /api/follows/requests/{id}/respond, etc.
- **Status:** PASS — `test_phase3a_permissions.py` exhaustively covers follow request/respond/relationship lifecycle including auto-approve policies, cascade revocation, and audit emission for all 5 follow events.

### Endpoint: POST /api/delegates/register, DELETE /api/delegates/register/{topic_id}
- **Status:** PASS
- **Existing test:** `tests/test_phase3a_permissions.py::test_audit_log_for_delegate_profile_creation`, `_deactivated`.

### Endpoint: GET /api/users/me/access-log
- **Status:** PASS — `test_privacy_hardening.py::test_access_log_*` (5 tests) cover indirect/direct surfacing, cross-user isolation, exclusion of non-elevated views.

### Endpoint: GET /api/users/{id}/votes (and /api/users/{id}/profile)
- **Status:** PASS (visibility logic) — `test_phase3a_permissions.py::test_self_can_always_see_own_votes`, `_public_delegate_votes_visible_to_all`, `_follower_can_see_votes`, `_non_follower_cannot_see_votes`.

### Endpoint: PATCH /api/orgs/{slug} (settings update)
- **Status:** PASS — `tests/test_sub_org_routes.py::test_cross_scope_delegation_setting_audit` (and the sustained-majority diff tests under `test_sustained_majority_api.py`) cover the focused audit emission for setting-key flips.

### Endpoint: POST /api/orgs/{slug}/sub-orgs and the full sub-org member lifecycle
- **Status:** PASS — `tests/test_sub_org_routes.py` covers 25+ endpoint behaviors including audit emission for `sub_org.created`, `sub_org.member_invited`, `sub_org.member_joined`, `sub_org.member_removed`, `sub_org.member_role_changed`, `topic.promoted_to_orgwide`. The `test_all_eight_event_types_fire` integration test confirms audit shape for every sub-org event.

---

## Class B: Cross-scope invariants

For each entity, surveyed `db.query(<Model>)` call sites in `backend/routes/`
to identify any that don't apply an org / sub-org scope filter.

### Entity: Vote (canonical Phase 10.1 case)
- **Status:** PASS — `tests/test_vote_eligibility_scope.py` covers (a) sub-org non-member POST → 403, (b) cross-org POST → 403, (c) tally exclusion at the engine layer for direct + delegated chains, (d) `total_eligible` matches the eligible set in the vote-graph endpoint.
- **Confirmation:** All three call sites (`compute_tally` else branch, `get_vote_graph`'s `all_users`, `cast_vote`/`retract_vote`) now route through `eligible_voter_ids_for_proposal` — verified by reading the code post-10.1. The `db.query(models.User).filter(models.User.id.in_(eligible_ids))` pattern in `routes/proposals.py:851` is correctly scoped.

### Entity: Comment
- **Status:** PASS — `tests/test_comments.py::test_post_requires_org_membership`, `_post_on_sub_org_proposal_requires_sub_org_eligibility`, `_get_respects_proposal_visibility` cover the visibility gate. The route uses `_eligible_viewers_for_proposal` (mirrors Polis viewer rules).
- **Side-effect coverage:** `test_audit_events_emitted_on_lifecycle` asserts `comment.created/edited/deleted` emission.

### Entity: Polis (visibility + eligibility)
- **Status:** PASS — `tests/test_polis_eligibility.py` (7 tests) covers `eligible_viewers_for_polis` invariants including private-sub-org exclusion, parent-admin implicit power, inactive-membership exclusion. `tests/test_polis_routes.py::TestPolisListVisibility` confirms route-level integration. The 404-not-403 behavior in `get_polis` for cross-scope access is covered via `test_sub_org_polis_private_hidden_from_non_member`.

### Entity: Delegation (network endpoint cross-user leak)
- **Status:** GAP
- **Concern:** `GET /api/delegations/network` returns the current user's ego graph. Verified the route only queries delegations where `delegator_id == current_user.id` or `delegate_id == current_user.id`. No test confirms a third-party user cannot see another user's network via this endpoint.
- **Recommended test:** `tests/test_delegation_network_isolation.py::test_network_endpoint_returns_only_callers_ego_graph`. Two users with disjoint delegations → caller sees only their own.

### Entity: Topic visibility (sub-org leak)
- **Status:** PASS — `tests/test_sub_org_routes.py::test_topic_list_filters_by_viewer_scope`, plus `test_global_topics_*` (4 tests) cover both org-scoped and global `/api/topics` filtering.

### Entity: Proposal visibility (sub-org private leak)
- **Status:** PASS — `tests/test_sub_org_routes.py::test_privacy_flag_hides_sub_org_proposals` confirms private sub-org proposals are filtered for non-members.

### Entity: Audit log access (admin-only)
- **Status:** PASS — `test_privacy_hardening.py::test_elevated_endpoint_requires_admin` confirms 403 for non-admin on the elevated endpoint. The `Depends(auth_utils.get_current_admin)` on every other admin route is covered transitively (any non-admin would hit the dependency before reaching the handler). `tests/test_org_creation_gates.py::test_get_platform_settings_requires_admin` exercises this for one platform endpoint.

### Entity: User search (cross-org enumeration)
- **Status:** PASS — `tests/test_user_search.py::test_search_filters_by_org_slug`, `_search_org_slug_unauthorized`, `_search_no_org_slug_returns_all`, `_search_org_and_topic_compose`, `_search_excludes_inactive_members` (5 tests). The Phase 9.9 W1 `org_slug` gate is fully covered.
- **Caveat:** `test_search_no_org_slug_returns_all` documents the legacy unscoped fallback. This is intentional per the route's docstring ("legacy/backward-compat behavior") and is NOT a security gap as long as the caller is authenticated (the route has `Depends(get_current_user)`). Adjacent tech debt note for the lead: the docstring says "may be tightened in a follow-up" — a future pass might want to default `org_slug` to "must be set" and require explicit opt-out.

### Entity: User single-fetch (cross-org membership leak via /api/users/{id})
- **Status:** BUG (low severity, latent)
- **Concern:** `GET /api/users/{id}` in `routes/users.py:413` returns `models.User` with NO authentication required (no `Depends(get_current_user)`). A non-authenticated caller can fetch any user by ID and see their `username`, `display_name`, `email`, `avatar_url`, `email_verified`, `default_follow_policy`, etc. (per `schemas.UserOut`). The `id`-by-UUID enumeration is not trivial but is a leak of PII (especially `email`) without auth gating.
- **Caught by user?** No.
- **Severity:** Low — UUIDs are 128-bit so enumeration is not practical, but this returns email addresses unauthenticated. Worth fixing in W-FIX-A.
- **Recommended fix + test:** Add `current_user: models.User = Depends(auth_utils.get_current_user)` to `get_user`. Test: `tests/test_user_endpoint_auth.py::test_get_user_requires_auth_returns_401_unauthenticated`. Also consider whether email should be returned at all to a non-self viewer.

### Entity: User single-fetch via /api/users/{id}/delegation-tree
- **Status:** BUG (low severity, latent — same shape as above)
- **Concern:** `GET /api/users/{id}/delegation-tree` in `routes/users.py:421` similarly has no auth dependency. Returns the full delegation neighborhood for any user ID. This bypasses the per-relationship privacy rules in `/api/delegations/graph` (which IS auth-gated to current user).
- **Caught by user?** No.
- **Severity:** Low-medium — exposes delegation graph structure (who delegates to whom) without auth. The Phase 7.5 `admin.delegation_graph_viewed` audit gate is irrelevant here because there's no auth at all.
- **Recommended fix + test:** Add `Depends(get_current_user)` and apply the same identity-redaction logic that `/api/delegations/graph` uses (only show identities the viewer can see per follow/public-delegate rules). Test: `tests/test_delegation_tree_auth.py::test_delegation_tree_requires_auth` and `test_delegation_tree_redacts_identities_per_viewer_relationships`.

### Entity: User search (compat) /api/users
- **Status:** GAP — same `org_slug` semantics inherited from `search_users` but no dedicated test for the compat-route path. Trivial coverage win.
- **Recommended test:** `tests/test_user_search.py::test_compat_search_endpoint_inherits_org_filter`.

### Entity: Delegate-applications listing
- **Status:** GAP
- **Concern:** Routes `GET /api/orgs/{slug}/delegate-applications` etc. are gated by `Depends(require_org_admin)` (good), but no `tests/test_delegate_applications.py` file exists. The Phase 7 ImplicitPower behavior (parent-org admin acting on sub-org delegate apps) is uncovered.
- **Recommended test:** `tests/test_delegate_applications.py::test_list_requires_org_admin_403_for_member`, `::test_approve_creates_delegate_profile`, `::test_deny_records_feedback`, `::test_audit_emission_on_approve_and_deny`.

### Entity: Public delegates browse (sub-org scope filtering)
- **Status:** PASS-by-source — the Phase 8.5 Decision-5 scope filter in `routes/delegates.py:69-104` is logically correct (suppress delegates whose only profiles are on sub-org topics the viewer can't see). However, no test in `test_phase3a_permissions.py` exercises `/api/delegates/public` with a sub-org-scoped delegate profile and a non-sub-org-member viewer. Recommend adding for safety net.
- **Recommended test:** `tests/test_delegates_public_visibility.py::test_public_delegates_filtered_by_sub_org_scope_for_authenticated_viewer`.

### Entity: Organization (admin/member endpoints generally)
- **Status:** PASS — `tests/test_phase3a_permissions.py`, `test_moderator_permissions.py`, `test_member_reactivation.py`, `test_org_creation_gates.py`, and `test_sub_org_routes.py` collectively cover the membership / role / scope invariants.

### Entity: SubOrganization (lifecycle)
- **Status:** PASS — `tests/test_sub_org_routes.py` is comprehensive.

### Entity: SubOrgMembership (cross-sub-org leak)
- **Status:** PASS — `test_sub_org_routes.py` covers list/invite/approve/remove with role-gated access.

### Entity: OrgMembership (suspended user behavior)
- **Status:** PASS — `test_member_reactivation.py` (3 tests) covers suspend/reactivate semantics.

### Entity: Invitation (org-scoped)
- **Status:** PASS (creation/consumption) but GAP on email-send side effect (see Class A).

### Entity: DelegateProfile
- **Status:** PASS — `test_phase3a_permissions.py` covers register/deactivate audit + visibility.

### Entity: Comment (already covered above) — PASS.

### Entity: Vote (already covered above) — PASS.

---

## Class C: Infrastructure boundary

### Component: nginx `/uploads/` proxy (`^~` modifier requirement, Phase 9.8 hot-fix)
- **Status:** GAP — no smoke check exists. Phase 9.8 hot-fix landed via curl in production; no automated test guards the prefix-vs-regex routing collision.
- **Recommended smoke check:** `tests/smoke/test_proxy_boundary.py::test_uploads_proxies_to_backend`. `GET /uploads/{nonexistent}/file.jpg` on the prod URL → assert response is FastAPI's JSON 404 body (`{"detail": "Not Found"}` or similar) and Content-Type is `application/json`, NOT nginx's HTML `<html><body>404 Not Found</body></html>`.

### Component: nginx body-size limit (`client_max_body_size 8m`, Phase 9.9 hot-fix)
- **Status:** GAP — no smoke check exists. Phase 9.9 hot-fix landed via curl with a 5 MB JPEG; no automated test guards the limit drifting back to the default 1 MB.
- **Recommended smoke check:** `tests/smoke/test_proxy_boundary.py::test_body_size_limit_passes_through_to_backend`. `POST /api/users/me/avatar` with a 5 MB body and a deliberately invalid auth header → assert response is FastAPI 401 (the proxy passed it through), NOT nginx 413. Optionally a second test posting a 9 MB body to assert the nginx 413 fires above the configured limit.

### Component: Service worker cache navigateFallbackDenylist (`/api`, `/uploads`)
- **Status:** GAP — no test of the Workbox config. A new live-data path (e.g., a future `/notifications` SSE endpoint) would silently get cached if the developer forgot to add it to the denylist.
- **Recommended smoke check:** `tests/smoke/test_sw_config.py::test_navigate_fallback_denylist_includes_api_and_uploads`. Parse `frontend/vite.config.js` (or read the built `sw.js` from a deployed bundle) and assert the denylist patterns include `/^\/api/` and `/^\/uploads/`. Implementation note: parsing JS from Python is awkward — recommend a Node-side check instead, run from the deploy script. Or assert against the built `dist/sw.js` after `npm run build`.

### Component: manifest.webmanifest MIME type (Phase 10 closeout open issue)
- **Status:** BUG-flagged-as-known-issue (per Phase 10 closeout — manifest serves as `application/octet-stream` instead of `application/manifest+json`).
- **Smoke check that would catch the regression once fixed:** `tests/smoke/test_proxy_boundary.py::test_manifest_mime_type`. `GET /manifest.webmanifest` on prod → assert `Content-Type: application/manifest+json` (not `application/octet-stream`).
- **Note for lead:** This smoke check will FAIL until the underlying nginx config (or vite-plugin-pwa output content-type hint) is fixed. Either land the fix in this pass or document the known-failing smoke as a yellow flag in the closeout.

### Component: registerSW.js auto-injection (Phase 10 PWA install affordance)
- **Status:** GAP — currently verified by curl post-deploy but not codified.
- **Recommended smoke check:** `tests/smoke/test_proxy_boundary.py::test_register_sw_js_served`. `GET /registerSW.js` (or whatever path vite-plugin-pwa emits) → assert 200 + `Content-Type: application/javascript` (or `text/javascript`). Also `GET /` and assert the response HTML contains a `<script>` tag referencing `registerSW.js` (or the inlined registration snippet).

### Component: FastAPI StaticFiles mount at `/uploads/` (backend side of the avatar pipeline)
- **Status:** PASS-adjacent — covered transitively by `tests/test_avatars.py` which exercises the upload + the resulting URL is what the StaticFiles mount serves. No dedicated test that asserts a known-good file path returns 200 via the mount, but the upload tests cover the file-write side and any breakage of the mount would surface in browser verification.
- **No new test recommended at this layer** — out-of-scope until/unless avatars start failing in prod.

### Component: WebSocket endpoint `/ws/proposals/{proposal_id}` (tally broadcast)
- **Status:** GAP — no test exercises the WS handler or `broadcast_tally`. Acceptable scope-defer per the spec's "would need a WS test harness" caveat.
- **Recommendation:** Defer to a future pass; not blocking.

---

## Summary

- **Total endpoints/patterns audited:** ~75 (15 route modules, ~60 endpoints; 13 entities; 6 infrastructure components)
- **PASS:** ~40 (Class A: 18; Class B: 13; Class C: 1)
- **GAP:** ~28 (Class A: 16; Class B: 6; Class C: 5)
- **BUG:** 2 — both in `routes/users.py` (`GET /api/users/{id}` and `GET /api/users/{id}/delegation-tree` lack auth dependencies; both expose PII / graph data unauthenticated)
- **Recommended new tests (Class A + B):** ~25 (heaviest concentration in `routes/auth.py` — 7 endpoints with no email-send-mock or audit-emission tests)
- **Recommended new smoke checks (Class C):** 5 (uploads proxy, body-size limit, SW denylist, manifest MIME, registerSW.js injection)

### BUG severity assessment

Both BUGs are in `routes/users.py`:

1. **`GET /api/users/{id}` no auth required.** Returns full `UserOut` schema including email. Severity LOW (UUID enumeration impractical) but it IS a PII leak by URL guess. Fix is a one-line `Depends` add. **Not user-visible, not caught by any user.** Recommended W-FIX-A action: add the dependency, add a 401 test, and consider tightening the schema response for non-self viewers (separate decision — flag for Z if uncertain).

2. **`GET /api/users/{id}/delegation-tree` no auth required.** Returns the full delegation neighborhood. Severity LOW-MEDIUM — bypasses the privacy redaction logic in `/api/delegations/graph`. **Not user-visible, not caught by any user.** Recommended W-FIX-A action: add the dependency AND apply the same identity-redaction logic the auth-gated graph endpoint uses (anonymous identity for non-public-delegate, non-followed users).

Neither bug is a "user got a wrong answer" class bug like the 10.1 vote leak — these are unauth'd-data-exposure latent bugs. Recommend they get fixed in W-FIX-A but flagged in the closeout as "found during audit, not pilot-blocking, no historical user impact known".

### Adjacent tech debt observed (not in this workstream — flagged for the lead)

1. **`routes/users.py::search_users_compat` is a thin wrapper** around `search_users` and would benefit from a deprecation path / merge. Not urgent.
2. **`/api/users/search` unscoped path returns all users** when `org_slug` is omitted (the route's own docstring says "may be tightened in a follow-up"). Decision item for Z: should the unscoped path be removed or kept?
3. **`routes/topics.py::create_topic` requires `get_current_admin` (platform admin)** while `routes/organizations.py::create_org_topic` is the org-admin path. The unscoped `POST /api/topics` route may be a legacy artifact from before multi-tenancy; consider removing it (or document why both exist).
4. **The `_build_linked_polises` helper in `routes/proposals.py:98` does N+1 stats fetches** (one per linked Polis) — already flagged in the docstring as "v1 says small numbers; tech debt note." Not in this pass's scope but worth tracking.
5. **The `_validate_proposal_creation` global-create endpoint** (`POST /api/proposals` in `routes/proposals.py:379`) exists alongside the org-scoped one and has different validation rules. Consider whether the global endpoint should be removed in favor of always going through `/api/orgs/{slug}/proposals`.
6. **Forgot-password / reset-password / change-password endpoints have ZERO test coverage.** This is a critical auth-flow gap regardless of the audit's broader recommendations — recommend prioritizing in W-FIX-A.

### Class A test-priority recommendation for W-FIX-A

The auth module is the heaviest gap concentration. Recommended fix-order if W-FIX-A bandwidth is tight:

1. Email-send assertions for `register`, `forgot-password`, `resend-verification`, `create_invitations`, `resend_invitation` (5 tests — the canonical "side-effect not asserted" class that bit Phase 9.6).
2. Reset-password / change-password full coverage (2-3 tests — critical auth flow with no tests at all today).
3. The two `routes/users.py` BUG fixes + tests.
4. Refresh / logout / logout-all tests (3 tests — token-rotation invariants).
5. The remaining minor audit-emission polish tests (delegate-applications, accept-invitation-authenticated, etc.).

### Class C smoke directory recommendation

Stand up `tests/smoke/` with the 5 recommended checks. Per spec, design intentionally minimal: one file per boundary class, no fixtures, no shared setup, just `requests.get/post` + assertions, runnable via `pytest tests/smoke/ -v --target=https://www.liquiddemocracy.us`. The SW denylist check is the awkward one (parsing JS from Python); consider a separate Node-script invocation or assert against the built bundle.
