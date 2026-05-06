# Tech Debt Audit — 2026-05

Audit date: 2026-05-04 (Phase 12.8). Scope: PROGRESS.md from Phase 9 forward, codebase TODO/FIXME/HACK/XXX/BUG/NOTE comment grep (backend + frontend), `future_improvements_roadmap.md` Known Issues. Per spec §A1.5, items are classified into three lanes (TECH_DEBT / Z_ACTION_PENDING / MANUAL_VERIFICATION_GAP) before tier-assignment.

**Edit history:**
- 2026-05-05 (Phase 13.2 W-DEPLOY-3 closeout): Item 22 (NotificationBadge default-org coarse routing) marked RESOLVED — Phase 13.2's three-deploy bisection delivered the notification system with `org_id` as a first-class column on the `Notification` table; click-through routing uses `notification.org_slug` looked up server-side from `org_id`, never first-parent fallback. Account-level notifications (no `org_id`) route to `/notifications` rather than guessing an org. Entry retained with RESOLVED status for traceability rather than deleted; `future_improvements_roadmap.md` Known Issues had its corresponding bullet removed alongside this audit-doc edit. (The earlier 2026-05-04 attempt at retirement under "Phase 13 closeout" was reverted with the failed Phase 13 deploy; this is the durable retirement that lives with the actually-shipped Phase 13.2 W-DEPLOY-3 surface.)
- 2026-05-06 (Phase 13.3 closeout): Phase 13's global `User.digest_cadence` column retired in favor of per-event cadence (the `email` channel split into `email_immediate` / `email_daily` / `email_weekly`, each independently togglable per event). `sustained_majority.floor_approached` event type deleted from registry — the underlying detection logic was never wired in `sustained_majority_service.py` and the dead checkbox confused the friend-pilot dogfooder; orphaned `notification_preferences` rows cleaned up inline in migration `b9e2f4a17c83`. Phase 13 learning #7 (pg_smoke gap) was exercised for the first time on this pass: a new `backend/scripts/phase13_3_actual_upgrade_path_check.py` stamps a fresh PG at the prior revision with sample data, then runs `alembic upgrade head` directly without `create_all` bootstrapping — the actual upgrade path that would have caught Phase 13's boolean-default datatype mismatch. Worth promoting to a standard pg_smoke mode in a future cleanup pass.
- 2026-05-06 (Phase 14 closeout): Phase 14 introduced public org landing pages and the four-value `Organization.join_policy` enum (`invite_only_secret` / `invite_only_public` / `approval_required` / `open`). Migration `c0a3e5d12f4a` renames legacy `invite_only` → `invite_only_secret` to preserve current behavior on existing orgs. Phase 13 learning #7's actual-upgrade-path mode applied again via `backend/scripts/phase14_actual_upgrade_path_check.py` — strengthens the case for promoting it to a standard pg_smoke mode (now exercised on two consecutive passes). One small spec inaccuracy surfaced and was patched in the same pass: the dispatch claimed `?next=` Login redirect support was "Phase 9-era functionality" — it wasn't; frontend dev added minimal same-origin-relative-path-only support as part of Cluster F. OrgSelector empty-state copy updated to mention "joinable public organizations" alongside the existing "create an org / wait for invitation" guidance.
- 2026-05-06 (Phase 15 Cluster G1): Item 33 (help page back-link destination) RESOLVED — a shared `frontend/src/components/HelpBackLink.jsx` component now uses `window.history.back()` with `/orgs` fallback (when `window.history.length <= 1`) across PolisHelp, VotingMethodsHelp, SustainedMajorityHelp, RolePermissionsHelp, NotificationsHelp, and OrganizationsHelp. The static `<Link to="/orgs">← Back</Link>` pattern is gone from all six pages.
- 2026-05-06 (Phase 15 Cluster G6b): Phase 14 tech debt #3 (defensive client-side `invite_only` → `invite_only_secret` coercion in OrgSettings.jsx hydration) RESOLVED — same Z gate waiver as G6a applies; single-save behavior already persists the value in the new four-policy form, and the backend B1 migration renamed all legacy rows. The four-policy radio group still loads + saves all four values cleanly without the coercion (browser-verified in closeout).
- 2026-05-06 (Phase 15 Cluster G6a): Items 26-27 (cache-safety role-tier fallbacks in Nav.jsx + AdminRoute.jsx + AdminOnlyRoute.jsx) RESOLVED. Z waived the 7-day cached-cutover gate for this pass based on single-user reality (the cached-bundle population the gate was designed to protect is effectively zero); the convention itself is preserved as institutional discipline for future passes. Cache-safety fallback branches removed from all three files (`legacyIsAdmin` derivation + `userPerms === null` branches gone); strict permission-driven gating throughout. Items 28-29 are scoped to OrgSettings.jsx (`'owner'` Danger Zone visibility) and the RolePermissionsPage `canEdit` derivation; both are cosmetic UX gates rather than security-bearing route guards, so they were left for a future cleanup pass to keep the diff focused on the load-bearing surfaces.

## Summary

- Total items audited: 41 (after deduplication)
- TECH_DEBT lane: 32 (Tier 1: 5 fix-in-12.8, Tier 2: 14, Tier 3: 5 + 1 RESOLVED in 13, calendar-gated: 4, EXTENDS_10_2_AUDIT: 2, INTENTIONAL/STALE: 1)
- Z_ACTION_PENDING lane: 4
- MANUAL_VERIFICATION_GAP lane: 1
- NEEDS_Z_INPUT items: 4
- Items recommended for fix in 12.8: **5** (Tier 1) + **1 stale comment removal**
- Items deferred with estimate: 21 (Tier 2/3 + calendar-gated; was 22 pre-13, Item 22 resolved)
- Items flagged for Z input: 4
- Items already resolved (remove stale references): 5 + 1 (Item 22 resolved in Phase 13)

## Tier 1 — Fix in 12.8 (trivial)

### Item 1: Backend startup log warning for missing `/data/uploads/`
- Source: PROGRESS.md Phase 12.7 tech debt #2; spec F.1 item 2
- Description: Volume provisioning is a manual Z step; if `/data/uploads/` doesn't exist or isn't writable, uploads silently fall back to ephemeral container storage. Add a startup log warning so the misconfiguration is visible in Railway logs.
- Recommendation: FIX_IN_12_8
- Effort: ~15 minutes
- Rationale: Z is the only person who can fix the underlying provisioning gap; surfacing it in logs is a 10-line backend change that makes the silent fallback loud.
- Action: Add a startup warning in `backend/main.py` (or wherever the existing on_event("startup") lives) using the same `_resolve_uploads_base()` helper from `backend/routes/avatars.py` to detect ephemeral fallback and emit `logging.warning(...)`.

### Item 2: Stale TODO in CreatePolis.jsx
- Source: Frontend codebase grep (only marker found in `frontend/src/`)
- Description: `frontend/src/pages/admin/CreatePolis.jsx:11-29` carries a TODO block referring to a Phase 9 Session 2 PATCH-API limitation that was resolved in Phase 9 Session 4 (commit 95af3ff added `polis_conversation_id` to the PATCH endpoint).
- Recommendation: FIX_IN_12_8 (STALE_REMOVE_COMMENT_ONLY)
- Effort: ~5 minutes
- Rationale: The underlying gap is closed; the comment is now misleading.
- Action: Remove the obsolete TODO block; the `handleSaveConversationId()` function (lines 400-424) already wires the Save button correctly.

### Item 3: `OrgMembership.role_id` model nullable mismatch
- Source: PROGRESS.md Phase 12 Stage 1 tech debt #1
- Description: `backend/models.py:155` declares `role_id` as `Mapped[Optional[str]]` with `nullable=True` "temporarily so the migration can backfill before flipping NOT NULL — production schema is NOT NULL." The migration shipped 2026-05-03; the temporary should be removed.
- Recommendation: FIX_IN_12_8
- Effort: ~10 minutes (verify no constructor sites pass None, flip the model, run tests)
- Rationale: Production schema is NOT NULL; tests now use the conftest helper which always sets role_id; no production code path constructs OrgMembership without a role.
- Action: Change `Mapped[Optional[str]]` → `Mapped[str]`, `nullable=True` → `nullable=False`, drop the "temporarily" language from the comment, run the suite to confirm no fixture leans on the looseness.

### Item 4: timeAgo helper duplicated across 3 components
- Source: PROGRESS.md Phase 10 tech debt #4
- Description: `function timeAgo(dateStr)` is defined inline in `Comment.jsx:42`, `FollowRequests.jsx:6`, and `DelegateModal.jsx:11`. All three implementations are identical. Phase 10 deferred this consolidation as below-threshold; Phase 12.8 is the cleanup pass.
- Recommendation: FIX_IN_12_8
- Effort: ~30 minutes (extract helper, update 3 call sites, manual smoke that times still render)
- Rationale: Three identical implementations make the codebase harder to evolve; one helper is the canonical pattern.
- Action: Create `frontend/src/utils/timeAgo.js`, copy the implementation, replace in-component definitions with `import { timeAgo } from '../utils/timeAgo'` (path adjusted per file).

### Item 5: Sustained-majority `floor_breached` inconsistency in `build_status`
- Source: PROGRESS.md Phase 9.8 tech debt #2
- Description: `backend/sustained_majority_service.py:168-170` computes `breached = (sample.votes_cast > 0 and support < config.floor)` — does NOT consult `support_ever_established`, even though the worker (Phase 9.8 C1 fix) does. Result: the UI banner shown to users via `/results` says "floor breached" the moment a non-zero vote drops below the floor, even before any threshold-meeting consensus has ever existed in the window.
- Recommendation: FIX_IN_12_8
- Effort: ~45 minutes (load all snapshots in window, compute `support_ever_established`, gate `breached` on it; one new test asserting "no breach before establishment")
- Rationale: Same root fix as Phase 9.8 C1 but at the read path. One-line semantic change + helper invocation. Aligns the UI banner with the worker behavior so users don't see contradictory states.
- Action: In `build_status` binary branch, load all snapshots (not just latest) for the window, call `support_ever_established(snapshots, config)`, gate `breached` on the result. Add a test where snapshots show vote drop below floor without prior establishment → `floor_breached=False`.

## Tier 2 — Defer (small but the team chose not to take this pass)

### Item 6: `is_polis_admin` not exposed on PolisOut schema
- Source: PROGRESS.md Phase 9 Session 3 tech debt #1
- Description: Frontend uses heuristic (creator OR moderator/admin OR sub-org admin) to show/hide Polis admin controls. Backend remains source of truth via 403, but the heuristic is brittle and re-implements per-route auth logic.
- Recommendation: DEFER_WITH_ESTIMATE
- Effort: ~1.5 hours (add field + compute in PolisOut serializer + frontend update + 2-3 tests)
- Rationale: Multi-file backend + frontend; involves auth-context propagation through Pydantic serialization. Bundle with a future Polis cleanup pass.

### Item 7: PolisDetail linked-from indicator is N+1 client-side
- Source: PROGRESS.md Phase 9 Session 3 tech debt #2
- Description: `PolisDetail.jsx` fetches the full proposal list per detail render to find proposals that link this Polis.
- Recommendation: DEFER_WITH_ESTIMATE
- Effort: ~2 hours (new backend endpoint to query proposals by linked_polis_id + frontend cutover)
- Rationale: Real fix needs a backend endpoint addition; not in 12.8's autonomous scope.

### Item 8: Polis stats N+1 in `_resolve_linked_polises`
- Source: Backend codebase grep — `backend/routes/proposals.py:109-111`
- Description: Loop calls `polis_service.get_participation_stats` once per Polis ID. Documented as deferred at the comment level.
- Recommendation: DEFER_WITH_ESTIMATE
- Effort: ~2 hours (add batch query helper + refactor loop + test for batch case)
- Rationale: Documented constraint ("small number of linked Polises per proposal" per spec) means this is acceptable now. Pick up if a proposal grows enough linked Polises to surface measurable latency.

### Item 9: PublicConfigContext.jsx `react-refresh/only-export-components` lint warning
- Source: PROGRESS.md Phase 9 Session 3 tech debt #5
- Description: Lint warning matches the existing pattern on AuthContext / OrgContext / ConfirmDialog / Toast. Splitting the hook into a sibling file would clear all 5 in one cleanup pass.
- Recommendation: DEFER_WITH_ESTIMATE
- Effort: ~1.5 hours (5 hook splits + import updates + lint verification)
- Rationale: Touches all major contexts; risk of subtle import-order regressions; warrants a focused sweep rather than mid-pass cleanup.

### Item 10: `audit_log` composite index gap
- Source: PROGRESS.md Phase 9.5 tech debt #2
- Description: Rate-limit query (`action='org.created' AND timestamp > now-1h`) has no composite index. Non-issue at current scale.
- Recommendation: DEFER_WITH_ESTIMATE
- Effort: ~1 hour (new alembic migration + composite index + PG smoke)
- Rationale: Schema change requires a migration; not in 12.8's no-migration boundary. Pick up when audit_log table grows large enough to surface query latency.

### Item 11: `org_slug` parameter optional on `/api/users/search`
- Source: PROGRESS.md Phase 9.9 tech debt #1; roadmap Known Issues
- Description: Backward compat preserved when `org_slug` is omitted; legacy/admin tools or direct API users could still hit the unscoped path. All in-app callers were updated to pass `org_slug` per Phase 9.9.
- Recommendation: DEFER_WITH_ESTIMATE
- Effort: ~1.5 hours (audit all callers + flip required + handle 422 in frontend + test)
- Rationale: Need to audit external/admin tools first to avoid breaking existing scripts. Worth a dedicated cleanup once we're confident no external callers depend on the unscoped path.

### Item 12: `vite-plugin-pwa` peer-version override
- Source: PROGRESS.md Phase 10 tech debt #2
- Description: `overrides` block in `frontend/package.json` relaxes vite-plugin-pwa's vite-7 peer constraint while we run vite-8.
- Recommendation: DEFER_WITH_ESTIMATE
- Effort: ~5 minutes (one-line removal) when vite-plugin-pwa supports vite-8 natively
- Rationale: External dependency. Re-check with `npm outdated` periodically.

### Item 13: Comment-viewer eligibility helper inlined in `routes/comments.py`
- Source: PROGRESS.md Phase 10 tech debt #1
- Description: `_eligible_viewers_for_proposal` is a near-duplicate of `polis_engine.eligible_viewers_for_polis`. Should consolidate into a shared `scope.py` once a third caller arrives.
- Recommendation: DEFER_WITH_ESTIMATE
- Effort: ~1 hour (extract + adapt + tests for both call sites)
- Rationale: Only 2 callers exist; the documented bar for extraction is 3. Defer until the 3rd caller appears.

### Item 14: `slowapi.limiter.reset()` autouse fixture pattern
- Source: PROGRESS.md Phase 10.2 tech debt #3
- Description: Same fixture pattern in 2 test files; promote to `conftest.py` if a 3rd rate-limited endpoint test appears.
- Recommendation: DEFER_WITH_ESTIMATE
- Effort: ~20 minutes when 3rd test exists
- Rationale: Same threshold-of-3 rule as Item 13. Defer until trigger.

### Item 15: `poll_deploy.py` bundle-hash heuristic incomplete
- Source: PROGRESS.md Phase 10.2 tech debt #1
- Description: Only fires on JS source changes. nginx-only or backend-only deploys leave the bundle hash unchanged and the script times out.
- Recommendation: DEFER_WITH_ESTIMATE
- Effort: ~2 hours (add `--mode` flag and/or `/api/version` endpoint with deployed git SHA)
- Rationale: Manual smoke + direct curl works as a fallback today. Worth fixing before the script becomes load-bearing for some CI integration.

### Item 16: `tests/smoke/` requires backend `.venv` to be activated
- Source: PROGRESS.md Phase 10.2 tech debt #2
- Description: A CI env without backend deps installed can't run smoke. Either add httpx to a top-level requirements file or have the CI step install it.
- Recommendation: DEFER_WITH_ESTIMATE
- Effort: ~1 hour
- Rationale: Not currently needed (smoke runs locally + on the lead's machine). Pick up if smoke gets wired into CI.

### Item 17: Two intentional Stage-1-preserved tier checks
- Source: PROGRESS.md Phase 12 Stage 1 tech debt #2; locations `backend/routes/organizations.py:1525` and `backend/routes/proposals.py:580`
- Description: Moderators-may-only-advance-own-proposals enforced via tier check. Becomes configurable when a `manage_others_proposals` permission key is added to the registry.
- Recommendation: DEFER_WITH_ESTIMATE
- Effort: ~1.5 hours (registry addition + migration row insertion + tier-check replacement + tests)
- Rationale: Adding a permission-registry key + migration row qualifies as Tier 2 schema-adjacent work; spec disallowed migrations this pass.

### Item 18: AdminRoute and AdminOnlyRoute functionally indistinguishable
- Source: PROGRESS.md Phase 12.6 tech debt #2
- Description: Both gate on a passed-in permission list; the only distinction is the call-site rename. Could merge into one `PermissionRoute` component.
- Recommendation: DEFER_WITH_ESTIMATE
- Effort: ~1.5 hours (component merge + 10 route updates + manual smoke)
- Rationale: Touches every admin route; worth a focused diff rather than mid-pass surgery.

### Item 19: PWA placeholder icons
- Source: PROGRESS.md Phase 10 tech debt #5
- Description: Default placeholder icons; per design decision 13 a real platform brand mark is deferred. (Per-org logo upload shipped in Phase 12.7.)
- Recommendation: DEFER_WITH_ESTIMATE
- Effort: design-blocked (waiting on Z-provided platform brand)
- Rationale: Z's call on when to commission/produce the brand mark. Logged as a Z follow-up; not team-authorable.

## Tier 3 — Defer (real work)

### Item 20: `User.email_verified_at` column gap
- Source: PROGRESS.md Phase 9.5 tech debt #1
- Description: Audit-enrichment falls back to `EmailVerification.verified_at`; legacy accounts predating that table get None.
- Recommendation: DEFER_WITH_ESTIMATE
- Effort: ~3 hours (add column + backfill from EmailVerification + alembic migration + audit query update + tests)
- Rationale: Schema change + backfill + audit-query update; needs PG smoke. Tier 3 by Phase 12.8 boundary.

### Item 21: Fresh-deploy seed mirror in `database.create_tables()` band-aid
- Source: PROGRESS.md Phase 9.5 tech debt #3
- Description: Workaround for the create_all+stamp-head asymmetry from Phase 8.6's start.sh ordering fix. Worth revisiting when the alembic chain gets squashed.
- Recommendation: DEFER_WITH_ESTIMATE
- Effort: ~6 hours (alembic chain audit + squash design + migration test cycle on real DB)
- Rationale: Chain-wide refactor; needs careful PG smoke + a reset/re-deploy plan.

### Item 22: NotificationBadge default-org coarse routing — RESOLVED in Phase 13 (2026-05-04)
- Source: PROGRESS.md Phase 11 tech debt #2
- Description: Pre-13 the legacy `NotificationBadge.jsx` polled follow-requests / voting-proposals / new-Polises and routed click-through using the first parent org's slug because there were no real notification rows carrying org context. Multi-org users could land in the wrong org.
- Status: **RESOLVED.** Phase 13 ships a real `Notification` table with `org_id` as a first-class column from day one (B1 schema). The new notification center (`NotificationBadge.jsx` rewritten in Cluster F1) routes click-through purely on `notification.org_slug` (resolved server-side from `org_id`) — never on first-parent-org. Account-level notifications without an `org_id` route to `/notifications` rather than guessing an org. Verified end-to-end via the F7 multi-org routing test (a notification on Gloomhaven routes to `/gloomhaven/...`, not to GameNights).

### Item 23: `routes/proposals.py:578-580` flat path duplicates org-scoped advance endpoint
- Source: PROGRESS.md Phase 12 Stage 1 tech debt #5
- Description: Flat path duplicates org-scoped advance endpoint at `routes/organizations.py:1503-1525`. Consolidation tied to Phase 11 path-based-URL deprecation of legacy flat paths.
- Recommendation: DEFER_WITH_ESTIMATE
- Effort: ~3 hours (caller audit + deprecation period decision + cutover + tests)
- Rationale: Touches both routing layers; needs caller-audit and a deprecation strategy.

### Item 24: `org_middleware.py` coarse-tier dependencies retire candidate
- Source: PROGRESS.md Phase 12 Stage 1 tech debt #3
- Description: `require_org_admin` etc. coexist with the per-action `has_permission` model.
- Recommendation: DEFER_WITH_ESTIMATE
- Effort: ~3 hours (call-site audit + gradual replacement + permission-key additions where needed)
- Rationale: Wide-touching refactor; warrants its own pass once the API surface stabilizes around per-action permissions.

### Item 25: "Reset to defaults" button on permissions matrix
- Source: PROGRESS.md Phase 12 Stage 2 tech debt #5
- Description: Single button to revert org's matrix to registry's default-grant table. Spec called out-of-scope.
- Recommendation: DEFER_WITH_ESTIMATE
- Effort: ~3 hours (modal + bulk-PATCH semantics + audit event design + tests)
- Rationale: Real feature work; not pure cleanup.

## Calendar-gated cleanups (deferred until age-out window passes)

These items are correct fixes but blocked on cached responses ageing out. **Today is 2026-05-04. The 7-day window from Phase 12.5 (shipped 2026-05-03) closes 2026-05-10.** All four items below should be picked up no earlier than that date in a single small cleanup pass.

### Item 26: Cache-safety role-tier fallback in Nav.jsx + AdminRoute + AdminOnlyRoute — RESOLVED in Phase 15 (2026-05-06)
- Source: PROGRESS.md Phase 12.5 tech debt #3, Phase 12.6 tech debt #1; spec F.1 item 1
- Description: Nav.jsx (12.5 F1) and AdminRoute/AdminOnlyRoute (12.6 G2/G4) preserved admin/moderator nav visibility when `user_permissions` was absent (cached stale API responses during cutover).
- Status: **RESOLVED.** Phase 15 Cluster G6a removed the fallback branches in all three files. Z waived the 7-day calendar gate for this pass based on single-user reality (cached-bundle population the gate was protecting is effectively zero); the convention itself is preserved as institutional discipline for future passes.

### Item 27: Frontend rename defensive backward-compat (`'steward'` and `'owner'`) — partially RESOLVED in Phase 15 (2026-05-06)
- Source: PROGRESS.md Phase 12 Stage 1 tech debt #6
- Description: ~25 grep hits across OrgContext / Members / Nav / PolisDetail / OrgSelector / Demo.jsx accepted both `'steward'` (canonical) and `'owner'` (defensive cached-response handling).
- Status: Phase 15 Cluster G6a removed the `'owner'` legacy-string branches from the cache-safety fallback paths of Nav.jsx / AdminRoute.jsx / AdminOnlyRoute.jsx (those fallbacks are gone entirely). Other call sites that defensively accept `'owner'` for cosmetic role-display purposes (OrgSelector cards, profile-page role display, the OrgSwitcher tree's parent/sub admin checks) remain — they're cosmetic, not gating, and can be tidied in a future cleanup pass without security implications.

### Item 28: F7 legacy `'owner'` acceptance in OrgSettings.jsx
- Source: PROGRESS.md Phase 12 Stage 2 tech debt #3
- Description: Defensive 'owner' branch in OrgSettings.jsx D4 hardcoded gate (Danger Zone visibility). Tighten to strict `'steward'` after age-out.
- Recommendation: DEFER_WITH_ESTIMATE
- Effort: ~5 minutes (one-line tighten)
- Rationale: Phase 15 G6a's gate-waiver applied to the security-bearing fallbacks in Nav.jsx / AdminRoute / AdminOnlyRoute. Item 28's `'owner'` branch in OrgSettings.jsx is technically eligible for the same tightening but was scoped out of Cluster G6a to keep the diff focused on the route-guard / nav-visibility surfaces; left for future cleanup.

### Item 29: Tier-shortcuts on Permissions nav link visibility + F6 read-only detection
- Source: PROGRESS.md Phase 12 Stage 2 tech debt #1, #2
- Description: Two places where the nav-link / read-only detection uses tier shortcut even though Phase 12.5 B4 already exposes `user_permissions` in `currentOrg`.
- Recommendation: DEFER_WITH_ESTIMATE
- Effort: ~30 minutes (replace tier shortcuts with `useHasPermission('role_permissions.edit')` reads)
- Rationale: Phase 15 G6a kept its scope tight to the security-bearing nav/route-guard fallbacks. Item 29's tier shortcuts on the RolePermissionsPage `canEdit` derivation are cosmetic UX gates (read-only mode is the fallback when `canEdit` is false, not a 403; backend B2 still enforces `role_permissions.edit`), so the cutover here is style-only and was left for a future cleanup pass.

## Extends 10.2 audit (test-depth gaps that fit Phase 10.2's framework)

### Item 30: Pattern of "feature surface gated by role rather than permission" elsewhere
- Source: PROGRESS.md Phase 12.5 tech debt #6
- Description: Phase 12.5 F2 surfaced the high-value sites; other places (DelegationNetworkGraph admin badge, profile-page role display, etc.) still use role-tier gating cosmetically.
- Recommendation: EXTENDS_10_2_AUDIT
- Effort: ~3 hours for the audit pass that enumerates every role-comparison site and classifies fix-now vs. cosmetic-leave-alone
- Rationale: Same shape as Phase 10.2's test-depth audit but at the frontend gating layer. Worth a dedicated audit.

### Item 31: Route-guard family was a 12.5 audit gap
- Source: PROGRESS.md Phase 12.6 tech debt #3
- Description: 12.5's audit explicitly covered in-page controls + admin nav visibility but didn't audit route guards themselves. The bug class was "feature works at one layer, broken at adjacent layer" — same family as the Phase 10.2 framework but at the frontend-route layer.
- Recommendation: EXTENDS_10_2_AUDIT
- Effort: ~2 hours (extend `docs/test_depth_audit_2026-05.md` to cover frontend route guards as a documented class + recommend tests asserting render-not-redirect for permission-granted users)
- Rationale: Process / test-coverage pattern; not 12.8-fixable.

## Needs Z input

### Item 32: Demo-org slug=`demo` collision
- Source: PROGRESS.md Phase 11 tech debt #1
- Description: The seeded Demo Organization has `slug=demo`, which is also a reserved word per Phase 11 B1. Functionally harmless (bare `/demo` shows marketing per Phase 11 D4), but the collision exists.
- Question for Z: Rename the seed org's slug (e.g. `demo-org`) via direct DB UPDATE + Demo.jsx hardcoded references, or document the collision-is-harmless intent in DEPLOYMENT.md and leave?

### Item 33: Help page back-links destination — RESOLVED in Phase 15 (2026-05-06)
- Source: PROGRESS.md Phase 11 tech debt #3
- Description: PolisHelp / VotingMethodsHelp / SustainedMajorityHelp / RolePermissionsHelp / NotificationsHelp / OrganizationsHelp Back-to links pointed at `/orgs` (org context-free) regardless of where the visitor came from.
- Status: **RESOLVED.** Phase 15 Cluster G1 introduced a shared `HelpBackLink` component that calls `window.history.back()` with `/orgs` fallback when there's no in-app history (direct URL hit). All six help pages share the same component.

### Item 34: Old flat URLs catch-all behavior
- Source: PROGRESS.md Phase 11 tech debt #4
- Description: Per Phase 11 D5 "no redirect grace period," old flat URLs (`/proposals` etc.) land at `/`. Could be smarter ("you tried `/proposals` — pick an org and we'll take you there").
- Question for Z: Want the smarter fallback or leave the catch-all?

### Item 35: Platform admin (`is_admin=True`) sub-org-admin power scope
- Source: PROGRESS.md Phase 9.6 tech debt #4
- Description: Platform admins do not have implicit sub-org-admin power outside org families they're a member of. Surfaced when lead tried to add Z to Gloomhaven on his behalf. Correct security posture, but creates friction for backfill / on-behalf-of workflows.
- Question for Z: Should platform admin be "global override" (can add to any org without being a member) or stay scoped (current security posture)?

## Z action pending (not team-fixable; surfaced for tracking)

### Item 36: Volume provisioning via Railway dashboard
- Source: PROGRESS.md Phase 12.7 tech debt #2
- Description: `railway.toml` declares `[[volumes]] mountPath = "/data"`. Until Z provisions the Volume in the Railway dashboard, logo + avatar uploads fall back to ephemeral container storage (lost on redeploy). The 3-tier path resolver in `backend/routes/avatars.py` does the right thing functionally; the Volume is the persistent storage layer.
- What Z needs to do: Open Railway dashboard → service settings → Volumes → provision a Volume mounted at `/data`. Wait for the next redeploy to pick it up.

### Item 37: Run `phase12_7_migrate_uploads.py` after Volume provisioning
- Source: PROGRESS.md Phase 12.7 tech debt #2
- Description: One-shot idempotent migration of legacy `backend/uploads/avatars/*` → `/data/uploads/avatars/*`. Source-equals-destination check exits cleanly on local dev.
- What Z needs to do: After Volume provisioning + redeploy, run `railway ssh "cd /app && python scripts/phase12_7_migrate_uploads.py"`. Idempotent — safe to run multiple times.

### Item 38: F7 visual browser verification (Phase 12.7 cluster F)
- Source: PROGRESS.md Phase 12.7 tech debt #1; Phase 12.7 verification table
- Description: Logo upload → theme application → nav logo → OrgSelector cards → permission gate → clear-on-leave wasn't browser-verified during Phase 12.7 ship (browser extension not connected). PASS-by-source only.
- What Z needs to do: Log in as Steward on demo org → `/admin/settings` Branding section → upload PNG → set non-default primary color → save → navigate to `/{slug}/proposals` and confirm nav logo + brand-primary buttons match → `/orgs` confirm card branding inline → `/` confirm public landing renders with platform-default colors (no theme bleed).

### Item 39: Run Phase 10.2 W-DIAG diagnostic on prod
- Source: PROGRESS.md Phase 10.2 pass-summary
- Description: `phase10_2_diagnose_pre_fix_vote_leak.py` enumerates pre-Phase-10.1 votes that are no longer eligible. Awaiting Z's `railway run` for prod numbers.
- What Z needs to do: Run `railway run "cd /app && python scripts/phase10_2_diagnose_pre_fix_vote_leak.py"` and review output. If the leak is >1 row or affects a binding decision, that becomes Phase 10.3.

## Manual verification gap (not team-fixable; useful context)

### Item 40: Phase 12.7 F7 cluster — browser-verify-only items
- Source: PROGRESS.md Phase 12.7 verification table
- Description: Logo upload + theme application + Nav logo + OrgSelector cards + permission gate + clear-on-leave-org-scope are PASS-by-source only. (Same surface as Item 38 above; logged separately because it's about verification provenance, not Z's checklist.)
- Note: When the chrome extension is reliably available next session, the F7 checklist can be run by the QA teammate. Until then, debugging traces back to source review for these surfaces should know visual verification didn't run.

## Stale — comment removal only

(No backend stale comments. Frontend stale: see Tier 1 Item 2 above — `CreatePolis.jsx:11-29` TODO.)

## Already resolved — roadmap cleanup

The following items currently appear in `future_improvements_roadmap.md` Known Issues but have actually shipped. Cluster R removes them.

### Item 41a: Sustained-majority floor activation logic (resolved 9.8)
- Source: roadmap Known Issues bullet 1
- Description: Phase 9.8 C1 fixed the floor-breach detector via `support_ever_established`. The roadmap entry already says "(resolved in Phase 9.8)" but the bullet is still listed.
- Action: Remove from roadmap Known Issues.

### Item 41b: Org invitation email-send wiring (resolved 9.6)
- Source: roadmap Known Issues bullet 2
- Description: Phase 9.6 W1 fixed the missing `send_invitation_email` call. The follow-up note ("worth adding an httpx-mocked end-to-end send test") was satisfied by Phase 10.2 W-FIX-A (`test_create_invitations_schedules_email_per_invitee` + `test_resend_invitation_rotates_token_and_schedules_email`) and Phase 12.7 E (`test_create_invitations_threads_org_branding_primary_color`).
- Action: Remove from roadmap Known Issues.

### Item 41c: Avatar storage on Railway-ephemeral filesystem (resolved 12.7 code; Z action pending for provisioning)
- Source: roadmap Known Issues bullet 3
- Description: Phase 12.7 Cluster I shipped `railway.toml` Volume declaration + 3-tier path resolver + idempotent migration script. Code path is ready; Z just needs to provision the Volume + run the migration script (Items 36-37 above).
- Action: Remove from roadmap Known Issues; the Z-action items (36-37) live in the audit doc instead.

### Item 41d: Test depth audit recommended (resolved 10.2)
- Source: roadmap Known Issues bullet 5
- Description: Phase 10.2 shipped the dedicated test-depth audit (`docs/test_depth_audit_2026-05.md` + 45 new tests + 2 BUG fixes + 1 latent-bug fix).
- Action: Remove from roadmap Known Issues.

### Item 41e: `email_service.send_invitation_email` "(Stub for Phase 4c)" docstring
- Source: PROGRESS.md Phase 9.6 tech debt #3
- Description: The stale "Stub for Phase 4c" docstring was already cleaned up in Phase 12.7 Cluster E when `send_invitation_email` was extended for branded primary_color. Verified by grep: zero matches for "Stub" or "stub" in `email_service.py`.
- Action: Remove from any internal-reference notes; nothing to do in code.

## Intentional — leave alone

The backend audit identified 5 NOTE: comments documenting intentional architectural choices (legacy binary voting schema compat, seed voter-name stability, Phase 12 role-permissions migration downgrade caveat, sub-org API gate ordering, role-permissions edit gate explanation, delegation defensive fallback for org_id IS NULL). All five are intentional documentation, not debt. No action.

The PolisDetail.jsx + Polis.jsx xid POST `useRef` debounce (Phase 9 Session 3 #4) is intentional — server-side idempotent + cosmetic only on cross-mount; left as-is.

`Toast.custom` background-click dismiss suppression (Phase 10.1 #2) is intentional behavior delta when `action` is present — left as-is.

`Invitations.role` string column with `_INV_ROLE_TO_SYSTEM_KEY` mapping in 3 places (Phase 12 Stage 1 #4) — intentional per spec; defer centralization until 4th caller.

`ProposalUpdate.pass_threshold/quorum_threshold` new mutation surface (Phase 12.5 #5) — intentional observation, no code change recommended.

`role_seed.py` only inserts True grants (Phase 12 Stage 2 #4 / Phase 12.5 #4) — functionally identical via B1 default-False; tidiness-only; defer indefinitely.

Backend test count baseline pattern (Phase 11 #5) — process note for spec drafting, not a code fix. Already incorporated into how dispatches reference current state.
