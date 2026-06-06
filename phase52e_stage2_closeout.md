# Phase 52e Stage 2 — Closeout

**Status:** SHIPPED + DEPLOYED 2026-06-06.
**Branch:** `phase-52e/verification-modes-stage2` (merged --no-ff).
**Master:** `3e8ba0e` (merge commit).
**Migration:** `c4d5e6f7a8b9` (down_revision `b3c4d5e6f7a8`, hex-prefix). Applied on prod.
**Bundle:** `index-Whi8M5-k.js` → `index-DEX08R8a.js` (live).
**Spec:** `phase52e_verification_modes_spec.md`.
**Greater-Phase context:** Stage 1 (E1 + E1b extractor rewrite + purge fix) shipped 2026-06-05 with the same branch family. This stage closes E2–E5 against Z's mid-pass grounding re-verify (PG-verified 2026-06-06 morning — hashes wrote, state escalated to `address_on_id`/`MA`, idempotency held, counter incremented).

## Re-grounding summary (per Z's instruction)

- **Phase 55** added `/explore` — a public ORG listing (not a delegate listing). Projection deliberately excludes user-level fields. The Stage 2 verified badge lives on member-list + delegate-specific surfaces (`OrgMemberOut.is_org_verified`); /explore is untouched, no conflict.
- **Phase 56** added Topic columns (`purpose`, `category`) + org settings (`topic_guidance`, `topic_categories_enabled`). Did NOT touch the membership join paths or the `public_accepting` lifecycle. Stage 2 stacks cleanly on the current shape of `request_join` / `create_join_request` / `accept_invitation` / `submit_public_accepting`.
- **No multi-head detected.** Head before this stage: `b3c4d5e6f7a8` (Phase 56). Head after: `c4d5e6f7a8b9` (this stage).

## What shipped (per the E2-E5 sequence)

### E2 — three verification modes over existing approval infrastructure

The modes are config combinations, not new infrastructure. Each rides anchors that already exist in the codebase:

- **Mode 1 — verification-to-join.** Shipped membership floor (Phase 52 Stage 1 `SETTING_MEMBERSHIP_FLOOR` + `check_membership_floor_for_join`) + the new flagged-applicant routing into `OrgMembership.status='pending_approval'` (E4 dependency).
- **Mode 2 — verification-to-act.** Shipped per-proposal floor (`Proposal.verification_floor` + `check_vote_floor_for_proposal`) + role-grant floor (`SETTING_ROLE_FLOORS` + `check_role_grant_floor`) + the NEW `submit_public_accepting` delegate-promotion gate (E3).
- **Mode 3 — none.** Settings unset → byte-for-byte today's behavior. `TestMode3UnsetIsAdditiveLayer` proves this against `OrgMembership.status='active'` on an open-join no-floor no-flag path with a non-verified user.

### E3 — derived `is_org_verified` predicate + unified capability config + delegate-promotion gate

- `verification_flags.is_org_verified(user, org, db) -> bool`. NEVER stored. True iff:
  1. `verification.user_satisfies_floor(user, ...)` against the org's membership floor.
  2. No OPEN high-confidence (`name_dob_address`) duplicate flag in this org against the user. Low-confidence flags do NOT invalidate.
- `OrgMemberOut.is_org_verified: bool = False` (new field). Populated by `routes/organizations.list_members` per-row. `Members.jsx` renders an emerald "Verified" badge inline with the member's name when True.
- Unified capability config keys live on `Organization.settings`:
  - `verification_required_for_public_delegate: bool` (E3-new). Default False.
  - Proposal floor and role floor are the shipped per-proposal / per-role keys (no new keys for those gates — the unified surface is the same OrgSettings panel rendering them coherently).
- `submit_public_accepting` (`routes/delegate_profiles.py` line ~813) gates on `is_org_verified` when the org setting is True. Structured 403 `verification_required` body — same shape as the proposal-floor / role-grant gates so the FE renders the prompt uniformly. Scope label `"role"` reused (no schema change; the structured-403 FE `ctaCopyForVerificationRequired` was extended with a `delegate` scope label for future use).
- **Cardinality-floor invariant.** The verification gate fires at GRANT time only. A verification state change (or a flag raised against a seated steward post-grant) flips the derived `is_org_verified` value to False but NEVER auto-strips the seated role. `TestCardinalityFloorInvariant::test_seated_steward_keeps_role_when_flagged_post_grant` raises a flag against an already-seated steward + asserts (a) the derived predicate is now False, (b) `OrgMembership.status` is still `active`, (c) the `Role` row pointed to by `role_id` still has `system_key='steward'`. The seated role survives the flag — the admin handles it manually.

### E4 — org-scoped name-based flags routed into existing approval gates

- **`OrgDuplicateFlag` table.** id, org_id, user_a_id, user_b_id (stored in lexical order so the unique constraint catches `(a,b)` and `(b,a)` as the same pair), confidence (`name_dob_address` or `name_dob`), status (`open` / `resolved_distinct` / `resolved_same`), resolved_by_id (nullable FK), resolved_at (nullable), created_at. UNIQUE constraint on `(org_id, user_a_id, user_b_id, confidence)`. NO PII stored — only the user_ids.
- **Detection.** `verification_flags.evaluate_duplicate_flags_for_org` walks the org's active members + the candidate. Two tiers checked:
  - High-confidence `name_dob_address_hash` match → `confidence=name_dob_address`. Math (per the arc backlog) shows near-zero false collisions at 1M users.
  - Low-confidence `name_dob_hash` match → `confidence=name_dob`. Only raised when high-confidence didn't match (high subsumes low).
- **Same-org only.** Evaluation runs ONLY for the org the candidate is joining / promoting in. Cross-org matches are computed-but-ignored at the call layer; `TestCrossOrgMatchDoesNotCreateFlagInEither` proves no flag is created in either org when the matching pair never share a membership.
- **Routing (Mode 1 wiring).**
  - High-confidence + `verification_high_confidence_flag_action='pending_approval'` (the **default**) → `OrgMembership.status='pending_approval'` regardless of `join_policy='open'`. The flag is a REASON the membership defaults to pending, surfaced in the org's existing approval queue.
  - High-confidence + `verification_high_confidence_flag_action='review_only'` → flag created + audit row written; membership status unchanged (admin opts out of the auto-routing).
  - Low-confidence → ALWAYS review-only regardless of setting. NEVER drives an automatic block (birthday-paradox math at scale).
- **Wired into all three join paths:** `create_join_request`, `request_join`, `accept_invitation`. Invitations evaluate flags but don't change routing (explicit admin endorsement bypasses while the flag is still recorded). The Stage 2 commit added `request: Request` to `request_join`'s signature for IP capture into the flag-audit (FastAPI auto-injects — no caller change).
- **Idempotent re-evaluation.** Same pair, same confidence → existing flag returned, no duplicate row. `TestIdempotentFlagDoesNotDupeOnReEvaluation` proves.
- **Adjudication endpoints** under `/api/orgs/{slug}/duplicate-flags/`:
  - `GET /open` (org-admin only) — lists open flags newest-first. Each entry exposes `confidence`, `status`, `created_at`, `resolved_at`, and `member_a` / `member_b` (each carrying only `user_id`, `display_name`, `username`). **Zero PII fields surfaced** — `TestAdminListsOpenFlag` asserts the absence of `name_dob_address_hash`, `name_dob_hash`, `doc_number_hash`, `verification_nullifier`, `date_of_birth`, `address` on both the row and the member sub-objects.
  - `POST /{flag_id}/resolve` — accepts `{"resolution": "resolved_distinct"}` (suppresses re-flagging the pair) or `{"resolution": "resolved_same"}` (records the verdict; v1 does NOT auto-enforce — admin uses the existing approve/deny endpoints to act on a confirmed-same membership). Idempotent on second call; non-admin refused; admin in a DIFFERENT org refused (404, no cross-org leakage).
- **No platform-admin / cross-org PII access.** Endpoints are scoped to `/api/orgs/{slug}/...` with `require_org_admin` — platform admin gate (`is_admin`) is not the auth here. `TestAdminInOtherOrgCannotResolve` proves a 404 when an org-B admin tries to resolve an org-A flag via the org-B URL.

### E5 — user-facing copy (the honest layer)

- `UP_FRONT_ONE_IDENTITY_COPY` (new exported constant): "You can verify only one account per person. Each verified identity is tied to a single account." Rendered in `Settings.jsx` immediately above the Start Verification button.
- `DOC_HARD_BLOCK_MESSAGE` (new exported constant): "We couldn't complete identity verification for this account. If you think this is a mistake, please contact support." Deliberately NEUTRAL — never reveals "an existing account" exists, preserves privacy on the duplicate-block path.
- `ctaCopyForVerificationRequired` extended with a `delegate` scope label for future structured-403 payloads if a backend scope distinction is added later.
- `OrgSettings.jsx` gets two new controls in the "Identity verification gates" section: a "Require verified members to be promoted to public delegate" toggle (E3 capability) and an "Action on high-confidence duplicate flag" dropdown (E4 routing default — `pending_approval` recommended; `review_only` alternative).
- **Privacy / non-retention copy NOT shipped this stage.** Still gated on the E1b purge proof — Mara hasn't replied yet; the candidate-walker is still 404'ing all paths in prod (`approved_purge_failed` bookkeeping status). When the deletion endpoint is confirmed, the privacy claim ships in a follow-up FE-only pass alongside an updated honest-scope org-facing copy.

## Verification matrix

| Check | Required | Result |
|---|---|---|
| Predicate purity + flag-invalidates-only-high-confidence | ✅ | 6 cases in `TestIsOrgVerifiedPredicate` |
| Delegate-promotion gate (E3) | ✅ | 3 cases in `TestPublicDelegateGate` — unverified blocked w/ structured 403; verified passes; org-not-requiring skips gate |
| Cardinality-floor invariant | ✅ | `TestCardinalityFloorInvariant::test_seated_steward_keeps_role_when_flagged_post_grant` |
| Flag detection at join — same-org high routes to pending | ✅ | `TestFlagDetectionAtJoin::test_same_org_name_dob_address_match_creates_high_flag_and_routes_pending` |
| Low-confidence NEVER auto-blocks | ✅ | `test_low_confidence_match_does_not_route_pending_on_open_join` |
| High-confidence + review_only setting NOT auto-block | ✅ | `test_high_confidence_with_review_only_setting_does_not_route_pending` |
| Cross-org match → no flag | ✅ | `test_cross_org_match_does_not_create_flag_in_either` |
| Idempotent flag detection | ✅ | `test_idempotent_flag_does_not_dupe_on_re_evaluation` |
| Adjudication state machine (resolve_distinct, resolve_same, invalid input) | ✅ | 6 cases in `TestAdminAdjudication` |
| No PII / no cross-org leakage in adjudication | ✅ | `test_admin_lists_open_flag` (negative-field asserts) + `test_admin_in_other_org_cannot_resolve` |
| Mode 3 (no settings) — byte-for-byte parity | ✅ | `TestMode3UnsetIsAdditiveLayer` |
| `OrgMemberOut.is_org_verified` surfaced correctly | ✅ | `TestMemberListVerifiedBadge` |
| Serializer guard — hashes still NEVER on UserOut | ✅ | `TestSerializerGuard` |
| Migration cycle (SQLite) | ✅ | 2 cases — upgrade adds table; downgrade-upgrade cycle round-trips |
| PG smoke fresh + upgrade-from-`b3c4d5e6f7a8` | ✅ | PASS both modes |
| Adjacent regression | ✅ | **547/547 PASS** in 4:17 (521 baseline + 26 new) |
| FE build clean | ✅ | Bundle `index-DEX08R8a.js`, 1.6MB / 414KB gzipped |
| Deploy + migration on prod | ✅ | `Running upgrade b3c4d5e6f7a8 -> c4d5e6f7a8b9, phase 52e stage 2 — org_duplicate_flags table` + Startup complete (2026-06-06 14:51:13 UTC) |
| Prod schema confirmed | ✅ | Direct PG query: `org_duplicate_flags` (9 columns) present + alembic head = `c4d5e6f7a8b9` + 0 open flags (no real verifications since deploy) |
| Endpoints live + auth-gated | ✅ | `/api/orgs/{slug}/duplicate-flags/open` returns 401 unauth (route mounted + admin gate firing) |
| `bash start.sh` prod-mimic | N/A | No start.sh / worker / scheduled tick change |

## Test count delta

- Phase 52b baseline: 521
- Stage 2 additions: +26
- **547 / 547 PASS** in 4:17

## Files added / modified

**Backend (10)**
- A `backend/verification_flags.py` — derived predicate + flag detection + adjudication state machine + settings reads
- A `backend/routes/duplicate_flags.py` — admin adjudication endpoints (`GET /open`, `POST /{flag_id}/resolve`)
- A `backend/migrations/versions/c4d5e6f7a8b9_phase_52e_stage2_org_duplicate_flags.py`
- A `backend/tests/test_phase_52e_stage2_modes_and_flags.py` (26 cases)
- A `backend/tests/test_phase_52e_stage2_migration_cycle.py` (2 cases)
- M `backend/models.py` — `OrgDuplicateFlag` model
- M `backend/schemas.py` — `OrgMemberOut.is_org_verified` field
- M `backend/main.py` — mount `duplicate_flags_routes.router`
- M `backend/routes/organizations.py` — flag eval wired into all three join paths; `request: Request` injected into `request_join`; `is_org_verified` populated on `list_members`
- M `backend/routes/delegate_profiles.py` — E3 delegate-promotion gate in `submit_public_accepting`

**Frontend (4)**
- M `frontend/src/pages/admin/Members.jsx` — emerald "Verified" badge
- M `frontend/src/pages/admin/OrgSettings.jsx` — two new controls (require-verified-delegate toggle, high-confidence flag action dropdown)
- M `frontend/src/pages/Settings.jsx` — UP_FRONT_ONE_IDENTITY_COPY rendered above Start Verification
- M `frontend/src/verificationLabels.js` — DOC_HARD_BLOCK_MESSAGE constant + UP_FRONT_ONE_IDENTITY_COPY constant + `delegate` scope label

## Deploy verification

- Master `3e8ba0e` pushed; backend redeployed.
- Backend log: `Running upgrade b3c4d5e6f7a8 -> c4d5e6f7a8b9, phase 52e stage 2 — org_duplicate_flags table` + Startup complete at 14:51:13 UTC.
- FE bundle flipped from `index-Whi8M5-k.js` to `index-DEX08R8a.js`.
- Direct PG schema query: `org_duplicate_flags` table present with all 9 columns; alembic head = `c4d5e6f7a8b9`; 0 open flags.
- Adjudication endpoint `/api/orgs/{slug}/duplicate-flags/open` returns 401 to unauthenticated — route mounted + admin gate firing.

## Open follow-ups (NOT 52e — backlog)

1. **E5 privacy copy still gated on the purge fix.** Mara's reply remains pending. When the correct Didit deletion endpoint lands, prepend it to `DIDIT_SESSION_DELETE_PATHS` env on Railway and re-verify a session disappears from the portal. THEN ship the honest non-retention copy in the org-facing OrgSettings + Settings strings.
- **Admin UI surface for the adjudication endpoints.** The backend `GET /open` + `POST /{id}/resolve` are wired but no admin page renders the open-flags list. Z (or any org admin) can `curl` it with their token for now; a small admin page lands as a follow-up. Tracked.
- **Notification on flag-raised.** Spec recommended notifying org admins when a flag is raised. v1 just writes the audit row + the flag — no email/notification fan-out yet. Admins notice flags via the open-flags list when they look. The fan-out is a small follow-up if Z wants admins paged proactively.
- **Pre-existing test failures (34).** Unchanged from Phase 55/56 closeouts — these are Topic-field test-fixture issues unrelated to Phase 52e. Tracked separately; not a Phase 52e regression.

## For Z review (design choices)

1. **Cross-org matches deliberately ignored.** The arc backlog locks this: harm is org-scoped (one human with two accounts only distorts outcomes if both participate in the same org). Stage 2 implements this by ONLY running `evaluate_duplicate_flags_for_org` for the org the candidate is joining / promoting in. There is no platform-wide flag table; if you ever want one for fraud-detection across orgs, it's a separate phase with its own privacy posture.
2. **`resolved_same` records only — no auto-enforcement.** The admin verdict "these ARE the same person" v1 just writes the resolved row; the membership status is unchanged. The admin then uses the existing `/{slug}/join/deny/{user_id}` to deny the pending application, or any of the existing role/membership controls to restrict the confirmed-same account. This is the spec values lock: confidence determines scope (auto block) vs. human action.
3. **Low-confidence flag never invalidates `is_org_verified`.** Birthday-paradox math at 100k+ users makes false collisions on `name_dob` alone near-certain — invalidating verified status on a low-confidence match would wall innocents at scale. The flag is still recorded (admin can review) but the badge stays True.
4. **`OrgMemberOut.is_org_verified` computed per-row.** For orgs with hundreds of active members the per-row predicate evaluates two DB reads (settings + flag lookup). At today's volumes this is fine. If a future org has thousands of members + the Members page becomes slow, a per-org cache is a small follow-up (the spec notes "Cache only if list-perf needs it; derived stays source of truth").

## Branch state

- `phase-52e/verification-modes-stage2` merged via `3e8ba0e` (--no-ff); safe to delete at next cleanup.
- master at `3e8ba0e`, pushed to origin, Railway deployed.

## Arc status

The verification arc — Phase 51 (state model foundation) → 52 Stage 1 (enforcement) → 52a (Didit) → 52b (free-pool metering) → 52c (PII-safe payload capture) → 52d (hash dedup infrastructure) → 52e Stage 1 (extractor rewrite + purge fix) → **52e Stage 2 (modes + flags)** — is now structurally complete. Remaining items are operational:

- Mara's deletion-endpoint reply → E1b purge confirmation → E5 privacy copy.
- Optional admin UI for the open-flags adjudication surface.
- Phase 52f (per-org display names + display-name-match) and Phase 52g (age-gating) remain future-phase candidates per the backlog.
- Phase 53 (org billing) is entity-gated — blocked on a legal-entity dependency, not a code dependency.

The metering + dedup + modes + flag routing + verified badge + admin adjudication that make verification a real org-facing feature are all live.
