# Tech Debt Audit — 2026-05

Audit date: 2026-05-04 (Phase 12.8). Scope: PROGRESS.md from Phase 9 forward, codebase TODO/FIXME/HACK/XXX/BUG/NOTE comment grep (backend + frontend), `future_improvements_roadmap.md` Known Issues. Per spec §A1.5, items are classified into three lanes (TECH_DEBT / Z_ACTION_PENDING / MANUAL_VERIFICATION_GAP) before tier-assignment.

**Edit history:**
- 2026-05-05 (Phase 13.2 W-DEPLOY-3 closeout): Item 22 (NotificationBadge default-org coarse routing) marked RESOLVED — Phase 13.2's three-deploy bisection delivered the notification system with `org_id` as a first-class column on the `Notification` table; click-through routing uses `notification.org_slug` looked up server-side from `org_id`, never first-parent fallback. Account-level notifications (no `org_id`) route to `/notifications` rather than guessing an org. Entry retained with RESOLVED status for traceability rather than deleted; `future_improvements_roadmap.md` Known Issues had its corresponding bullet removed alongside this audit-doc edit. (The earlier 2026-05-04 attempt at retirement under "Phase 13 closeout" was reverted with the failed Phase 13 deploy; this is the durable retirement that lives with the actually-shipped Phase 13.2 W-DEPLOY-3 surface.)
- 2026-05-06 (Phase 13.3 closeout): Phase 13's global `User.digest_cadence` column retired in favor of per-event cadence (the `email` channel split into `email_immediate` / `email_daily` / `email_weekly`, each independently togglable per event). `sustained_majority.floor_approached` event type deleted from registry — the underlying detection logic was never wired in `sustained_majority_service.py` and the dead checkbox confused the friend-pilot dogfooder; orphaned `notification_preferences` rows cleaned up inline in migration `b9e2f4a17c83`. Phase 13 learning #7 (pg_smoke gap) was exercised for the first time on this pass: a new `backend/scripts/phase13_3_actual_upgrade_path_check.py` stamps a fresh PG at the prior revision with sample data, then runs `alembic upgrade head` directly without `create_all` bootstrapping — the actual upgrade path that would have caught Phase 13's boolean-default datatype mismatch. Worth promoting to a standard pg_smoke mode in a future cleanup pass.
- 2026-05-06 (Phase 14 closeout): Phase 14 introduced public org landing pages and the four-value `Organization.join_policy` enum (`invite_only_secret` / `invite_only_public` / `approval_required` / `open`). Migration `c0a3e5d12f4a` renames legacy `invite_only` → `invite_only_secret` to preserve current behavior on existing orgs. Phase 13 learning #7's actual-upgrade-path mode applied again via `backend/scripts/phase14_actual_upgrade_path_check.py` — strengthens the case for promoting it to a standard pg_smoke mode (now exercised on two consecutive passes). One small spec inaccuracy surfaced and was patched in the same pass: the dispatch claimed `?next=` Login redirect support was "Phase 9-era functionality" — it wasn't; frontend dev added minimal same-origin-relative-path-only support as part of Cluster F. OrgSelector empty-state copy updated to mention "joinable public organizations" alongside the existing "create an org / wait for invitation" guidance.
- 2026-05-06 (Phase 15 Cluster G1): Item 33 (help page back-link destination) RESOLVED — a shared `frontend/src/components/HelpBackLink.jsx` component now uses `window.history.back()` with `/orgs` fallback (when `window.history.length <= 1`) across PolisHelp, VotingMethodsHelp, SustainedMajorityHelp, RolePermissionsHelp, NotificationsHelp, and OrganizationsHelp. The static `<Link to="/orgs">← Back</Link>` pattern is gone from all six pages.
- 2026-05-06 (Phase 15 Cluster G6b): Phase 14 tech debt #3 (defensive client-side `invite_only` → `invite_only_secret` coercion in OrgSettings.jsx hydration) RESOLVED — same Z gate waiver as G6a applies; single-save behavior already persists the value in the new four-policy form, and the backend B1 migration renamed all legacy rows. The four-policy radio group still loads + saves all four values cleanly without the coercion (browser-verified in closeout).
- 2026-05-06 (Phase 15 Cluster G6a): Items 26-27 (cache-safety role-tier fallbacks in Nav.jsx + AdminRoute.jsx + AdminOnlyRoute.jsx) RESOLVED. Z waived the 7-day cached-cutover gate for this pass based on single-user reality (the cached-bundle population the gate was designed to protect is effectively zero); the convention itself is preserved as institutional discipline for future passes. Cache-safety fallback branches removed from all three files (`legacyIsAdmin` derivation + `userPerms === null` branches gone); strict permission-driven gating throughout. Items 28-29 are scoped to OrgSettings.jsx (`'owner'` Danger Zone visibility) and the RolePermissionsPage `canEdit` derivation; both are cosmetic UX gates rather than security-bearing route guards, so they were left for a future cleanup pass to keep the diff focused on the load-bearing surfaces.
- 2026-05-04 (Phase 16 Clusters G1 + G2): Items 28-29 RESOLVED — finishing the cleanup arc started in Phase 15 G6a. Item 28: `OrgSettings.jsx` Danger Zone gate tightened from `(user_role === 'steward' \|\| user_role === 'owner')` to `currentOrg?.user_role === 'steward'`; the rationale comment for the legacy `'owner'` branch was trimmed since the cached-cutover protection is no longer load-bearing. Item 29: `RolePermissionsPage.jsx` `canEdit` now derives from `useHasPermission('role_permissions.edit')` instead of a hardcoded `(steward \|\| admin \|\| owner)` tier shortcut — the matrix self-administers (anyone granted `role_permissions.edit` via the matrix UI can edit the matrix). Both changes are UX gates, not security-bearing route guards (backend `org.delete` 403 remains as defense in depth; backend B2 still enforces `role_permissions.edit` on PATCH).
- 2026-05-09 (Phase 17 closeout): Removed the dead-tier-but-actually-live admin-resolves system (B6). The Phase 17 spec premise was that `TieResolutionRequest` schema in `backend/schemas.py` was a Phase 6 dead artifact; investigation during the pass found a live POST `/api/orgs/{slug}/proposals/{id}/resolve-tie` endpoint, 3 backend tests, and 2 frontend POST callsites (`ProposalDetail.jsx`, `RCVResultsPanel.jsx`). Z elected Option A: full removal — schema, route, tests, and UI all deleted. The new auto-resolution path (B4) makes the manual endpoint structurally unreachable anyway (it requires `tie_resolution IS NULL` AND `status = passed`, and B4 atomically writes `tie_resolution` at the same code-path moment status flips to `passed`). Spec/reality discrepancy noted in the closeout for spec-writer attention on future passes — assumptions about "dead artifacts" need verification before they become spec-load-bearing.
- 2026-05-10 (Phase 18.5 closeout — infrastructure: actual-upgrade gate + DELETE 503 fix + spec convention):
  - **Phase 15 G5 escalation RESOLVED.** `pg_smoke.py --mode actual-upgrade` now exists as a real flag with a `--sample-data-script` hook supporting `reshape(engine)` / `seed(engine)` / `verify(engine)` modules. Closes the deferred-promotion call-outs from Phase 13.3 closeout ("Worth promoting to a standard pg_smoke mode in a future cleanup pass") and Phase 14 closeout ("strengthens the case for promoting it to a standard pg_smoke mode"). The Phase 15 G5 PROGRESS claim that the flag had landed was inaccurate (Phase 17 + Phase 18 closeouts independently surfaced the gap); Phase 18.5 actually lands it. Verified against three invocations: `--prior-revision e9419ee5906f` (Phase 18b head, zero migrations to traverse — mechanical "flag works"), `--prior-revision d2a17cb3e45c` (Phase 17 head, real chain traversal), and `--prior-revision b9e2f4a17c83 --sample-data-script seed_phase14_actual_upgrade.py` (full end-to-end with seed + reshape + upgrade + verify). One-off scripts `phase13_3_actual_upgrade_path_check.py` and `phase14_actual_upgrade_path_check.py` deleted (superseded by the flag); the three `seed_phase*_actual_upgrade.py` modules retained as canonical sample-data examples (`seed_phase15_*` was already tracked; `seed_phase13_3_*` and `seed_phase14_*` promoted from untracked-on-disk to tracked).
  - **DELETE delegation intent 503 bug RESOLVED.** Phase 18 QA report observation #1 ("DELETE `/api/orgs/demo/delegations/intents/{id}` returned 503 while UI showed Cancel as successful, intent state correctly transitioned to cancelled") fixed in `routes/delegations.py::cancel_intent` by switching from implicit `return None` (FastAPI default emits a 204 with stray `content-type: application/json` header that Cloudflare/Railway's edge proxy rejects per RFC 7230) to explicit `return Response(status_code=204)` — same pattern already used by `routes/organizations.py::cancel_join_request`. Regression coverage in new `backend/tests/test_phase_18_5_infrastructure.py` (3 tests; the load-bearing one asserts both HTTP-shape — status 204, empty body, NO content-type header — and the DB side-effect of `intent.status = 'cancelled'` + audit row written).
  - **NEW Item 47: implicit-None pattern on `status_code=204` routes — broader latent risk.** `cancel_intent` was the only endpoint Phase 18 QA hit, but the same "implicit None return on a 204-decorated route" pattern is present at multiple other DELETE endpoints (`revoke_relationship` in `follows.py`, `revoke_delegation` and `cancel_intent`-pre-fix in `delegations.py`, `deactivate_delegate_profile` in `delegates.py`, `delete_avatar` in `avatars.py`, `delete_org_logo` in `org_logos.py`, `delete_organization` / `remove_member` / `revoke_invitation` / `delete_org_topic` in `organizations.py`, `delete_sub_org` in `sub_organizations.py`, `retract_vote` in `votes.py`). They produce the same malformed 204-with-JSON-content-type response locally. Whether they trip the Cloudflare/Railway 503 in prod depends on edge-proxy heuristics that may treat them differently than intents/DELETE for reasons we haven't fully characterized. Tier 2 audit item; cleanup pass should sweep all remaining 204 routes to use `return Response(status_code=204)` — a 1-line per-route change. Phase 18.5 deliberately scoped narrow (D3 lock) to fix only the QA-observed endpoint.
  - **CLAUDE.md updated for the Phase 19+ merged spec convention** (D1). Reading-order section now puts the phase doc at position 1 with "read FIRST and FULL" framing; new "Spec format convention (Phase 19+)" section locks the underscore-not-dot filename rule (`phaseXX_Y_*`), documents the dispatch+spec doc structure (verification matrix as a dedicated table, dispatch framing on top, spec body on bottom), deprecates the pre-Phase-19 separate-chat-dispatch-prompt pattern, and points at `phase19_public_delegate_pages_spec.md` + `phase18_5_infrastructure_spec.md` as worked examples. CLAUDE.md still under the 200-line cap (152 lines).
  - **No migration; PG smoke not required** for the pass surface itself — but the new flag was exercised against three real prior revisions as the natural proof-of-functionality, so the `--mode actual-upgrade` regression coverage exists incidentally.

- 2026-05-10 (Phase 18 closeout — **Phase 4c retrofit-completeness CLOSED**): Phase 18 retrofitted `org_id` (and `sub_org_id` where applicable) onto the four relationship tables that the original Phase 4c migration skipped — `Delegation`, `DelegationIntent`, `FollowRelationship`, `FollowRequest`. Two-phase alembic migration: `219205801d2c` (B1a) added nullable columns + ran a three-sweep backfill (topic-scoped via `topics.org_id`; globals where parties share exactly one org; multi-shared-org globals via "more-recently-active org by delegate's most recent vote" heuristic with INFO-level audit logging of chosen + alternative orgs); `1cc8f3f27717` (B3 followup) updated `FollowRelationship` and `FollowRequest` unique constraints to include `org_id`. Read-side filtering applied at all 15+ `db.query(models.Delegation)` call sites enumerated in `delegation_org_scoping_diagnostic_2026-05.md` §3. Write-side org plumbing in CRUD endpoints. Routes moved to `/api/orgs/{slug}/delegations/*` and `/api/orgs/{slug}/follows/*` (clean break, no compat aliases). `graph_store` partitioned by org with cycle detection per-org. New audit event `delegation.org_id_backfilled` per backfilled row. Backend test count 1076 → 1105 (29 new in `test_phase_18_delegation_org_scoping.py` + 12 existing test files updated for new URL surface and constructor shapes). Frontend bundle 361.81 → 362.24 kB gzipped (+0.43 kB) — Delegations.jsx rebuilt around per-org concept; DelegateModal sub-org fan-out collapsed to single-row write for "Only [SubOrg]" path; follow surfaces under org prefix. The misleading comment in `test_delegation_scope.py:263` ("No special path. No new pure-layer code is required.") replaced with Phase-18-anchored copy + meta-test (`test_phase_8_5_test_comment_updated`) guarding against re-introduction. **The Phase 4c retrofit-completeness pattern that was tracked across Phase 12 and Phase 17 closeouts is now closed.** Future relationship tables added to the schema must carry `org_id` from day one or document a deliberate exemption with rationale (added to CLAUDE.md operational lessons).
- 2026-05-10 (Phase 19 closeout — Public Delegate Pages): no items resolved this pass (additive feature work only; no in-scope cleanup of prior audit items). Six new audit items logged from frontend agent's API-gap report (4 deferred to follow-up; 1 fixed inline pre-merge by the lead via gap-fill commit `83bab63`; 1 structural-fragility note from the spec/reality reconciliation):
  - **Item 48 (Tier 3): No public-read endpoint for transparent-only delegates was missing pre-merge.** Resolved inline by lead via gap-fill commit `83bab63` (added `GET /api/orgs/{slug}/delegates/{handle_or_username}` with `effective_page_visibility` auth gate so anonymous viewers receive the page when effective visibility is `public`, approved followers when `private_delegators` or higher, and everyone else gets 404). Logged for posterity; the Phase 19 frontend agent flagged 5 API gaps total during F-cluster build (4 deferred; this one resolved in-pass).
  - **Item 49 (Tier 2): No list endpoint for pending delegate applications.** Phase 19 F5 (approver dashboard) is structured around topic-picker + per-topic approve/deny because no endpoint surfaces all pending applications across topics/applicants. Approvers don't see a "queue of N waiting" view — they need the `delegate_application_submitted` notification to know to come look. Acceptable for v1 given low expected volume on the friend pilot. **Suggested Phase 19.5 follow-up:** add `GET /api/orgs/{slug}/delegate-applications-pending` returning `{topic_id, topic_name, applicant: UserOut, submitted_at}` rows; rebuild F5 around the queue view. Effort: ~2 hours (endpoint + permission gate + pagination + frontend cutover + tests).
  - **Item 50 (Tier 3): No origin info on incoming-delegations endpoint.** Phase 19 F1's hard-revert dialog needs to enumerate ONLY public-origin delegators (those that will be revoked when a topic flips to `private`) but the `/api/orgs/{slug}/delegations/network` personal-network endpoint doesn't expose origin per edge. The dialog currently falls back to showing all incoming-delegation names on the topic with an "approximate" copy note acknowledging the imprecision. **Suggested:** add `origin: 'public' | 'private'` enrichment field on `/api/orgs/{slug}/delegations/network` edges (preferred — minimal surface change) OR a dedicated `GET /api/orgs/{slug}/delegate-profile/topics/{topic_id}/public-delegators` endpoint returning the public-origin delegator list per (delegate, topic, org). Effort: ~1 hour for the enrichment-field option; ~2.5 hours for a dedicated endpoint.
  - **Item 51 (Tier 3): MyVoteStatus shape doesn't include vote_id.** F3's `MyVoteRationaleBox` currently does an extra query to resolve vote_id from (proposal_id, current_user) before it can call the rationale CRUD endpoints. **Suggested:** enrich `MyVoteStatus` with `vote_id: Optional[str]` (set when the user has cast a vote on the proposal). Effort: ~30 minutes (schema field + serializer wire-up + frontend simplification + 1-2 tests).
  - **Item 52 (Tier 2): VoteFlowGraph rationale icons missing.** Per spec line 273, the vote graph should surface rationale presence per delegate vote so a viewer can spot at a glance "this delegate explained their vote, this one didn't." Backend graph response doesn't carry vote-side metadata; requires backend enrichment of the graph response. Rationales **are** still surfaced via F2 (the public delegate page groups them by topic), so users can find them — they're just not flagged on the graph. **Suggested:** enrich the `/api/proposals/{id}/vote-graph` response with `has_rationale: bool` per delegate-vote node OR per edge; frontend renders a small icon indicator (e.g., a quote glyph) on nodes with `has_rationale=True`. Effort: ~2 hours (backend enrichment + permission gate so private-topic rationale doesn't leak via the bool + frontend icon rendering + tests).
  - **Item 53 (Tier 3): `Delegation.delegation_intent_id` column not added.** Phase 18 + Phase 19 specs both referenced `Delegation.delegation_intent_id` as the canonical public-vs-private origin marker; the column was never added to the model. Phase 19 Wave 2 substituted **DelegationIntent-row-existence-based detection** (a delegation is private-origin iff an activated `DelegationIntent` row matches its `(delegator, delegate, org, sub_org, topic)` shape; otherwise it's public-origin). Works correctly for the spec/test cases today but is structurally fragile: if intent rows were ever cleanup-deleted (some future maintenance pass, soft-delete migration, etc.), the proxy would break and previously-private delegations would be misclassified as public on the next hard-revert and erroneously revoked. **Suggested:** add the FK column in a future cleanup pass (`ALTER TABLE delegations ADD COLUMN delegation_intent_id`); backfill existing rows via the same DelegationIntent-matching logic the helper uses today; switch `_revoke_public_origin_delegations_on_topic` to filter on `delegation_intent_id IS NULL` directly; remove the proxy. Effort: ~3 hours (alembic migration with reversibility test + backfill + helper switch + reseed tests + PG smoke).

- 2026-05-10 (Phase 19 incident + hotfix addendum): The original Phase 19 deploy (merge `7ede628`) crashed prod with `UndefinedObject: type "delegate_profile_visibility" does not exist` on the `ALTER TABLE delegate_profiles ADD COLUMN visibility` statement. Backend was 502 for ~20 minutes. Lead reverted (`0573664` — `git revert -m 1`) to restore service, diagnosed root cause, applied hotfix (`2941aa0` — explicit `delegate_profile_visibility_enum.create(bind, checkfirst=True)` before the batch_op.add_column that uses it), re-merged via `cc2b552`. Two NEW items logged from the incident:
  - **Item 54 (Tier 1): `pg_smoke.py --mode actual-upgrade` has a structural blind spot when migrations add columns that `_create_all` also creates.** The flag's pipeline is `_create_all` (today's full schema) → `stamp prior` → `seed?` → `upgrade head`. When `_create_all` already creates a new column + its enum type, the migration's `_maybe_add_column` guard skips the ADD path entirely. The CREATE-TYPE-then-ADD-COLUMN path is never exercised against real prior-schema PG, so PG-specific enum issues escape detection. **Same shape as Phase 13's boolean-default datatype mismatch.** This is the second pass where the gate ran "PASS" but prod failed on the migration code path the gate was meant to catch. Tier 1 because the gate's value proposition is undermined and the cost of the next missed migration is real prod downtime. **Suggested fix:** restructure the actual-upgrade pipeline to skip `_create_all` for any tables/columns the new migrations will create. Two implementation directions worth considering: (a) introspect the migrations between `--prior-revision` and head, identify their `op.create_table` / `op.add_column` operations, and skip those table/column creations in `_create_all` (complex; alembic operation introspection isn't friendly); (b) replace `_create_all` with `alembic upgrade <prior>` from base — but the chain's base revision (`58de3df8727f`) ALTERs the `users` table assuming `users` already exists (alembic was added post-hoc to a Phase 1/2 schema that wasn't alembic-managed at creation), so `alembic upgrade <prior>` from base fails on a fresh PG. The cleanest path is probably (c) seed the prior-revision schema via a generated SQL dump (one-time per phase, like `pg_dump --schema-only` against a known-good prior-state PG), then `alembic upgrade head` against that. Effort: ~half a pass (design + implementation + verification across 2-3 historical migrations). Until landed, **the hot signal is to also run a manual prod-snapshot Docker round-trip pre-merge for migration-heavy passes** — Phase 18 used this pattern, Phase 19 should have. The merged spec convention's verification matrix should add "prod-snapshot Docker round-trip" as a required check for any pass that adds a migration touching existing tables.
  - **Item 55 (Tier 3): F4 delegate card in-page click navigation broken.** QA agent found the browse page (`/{slug}/delegates`) lists delegates correctly, but clicking a card doesn't navigate to F2 (`/{slug}/delegates/{handle}`). Direct URL navigation works. Likely a React Router setup issue or click handler not propagating to the `<Link>` wrapper. Low-priority cosmetic UX bug — the page is reachable, just not via the intuitive interaction. **Suggested:** small frontend fix in `frontend/src/pages/Delegates.jsx`. Effort: ~15 minutes once located.

- 2026-05-10 (Phase 20 closeout — Stable Result Required redesign): scope-narrowing pass that removes the binary floor mechanic entirely and unifies binary + multi-option result-stability under one mechanic with sliding-window check during extensions. **One prior audit item RESOLVED via deletion** — Phase 12.8 Item 5 (sustained-majority `floor_breached` inconsistency in `build_status`) is gone because the floor concept is gone. Production code net negative (~340 lines removed; tests +1500 to absorb removal of legacy floor tests + add new sliding-window coverage). New audit items logged:
  - **Item 56 (Tier 3): Snapshot retention policy.** Per spec D17, snapshots stay in `VoteSnapshot` table after proposal close. At ~288 snapshots/day per active proposal × proposal lifecycle, ~50-100 MB/year per 100 proposals/year. Plausibly fine at near-term scale; flagged for future audit if real scale surfaces a problem. Cleanup or downsampling is a separate future pass.
  - **Item 57 (Tier 3): One-pass backwards-compat aliases on `StableResultStatus` JSON key + `SustainedMajorityStatus` Python alias + `proposal.sustained_majority` results-payload key.** Phase 20 backend agent kept `SustainedMajorityStatus = StableResultStatus` and the `sustained_majority` JSON key in the `/results` payload to avoid breaking the FE mid-deploy. The FE now reads the new shape but still under the old key. **Suggested cleanup:** rename the JSON key to `stable_result` in a future pass; remove the Python alias. Effort: ~1 hour (backend rename + frontend grep + test update).
  - **Item 58 (Tier 3): `sustained_majority_*.py` filename rename deferred.** `backend/sustained_majority.py`, `_service.py`, `_worker.py` keep their legacy filenames per spec line 376 to avoid disruption in this pass. Internal exports renamed to `StableResult*`. **Suggested cleanup:** rename files to `stable_result_*.py` in a future audit-refresh pass. Effort: ~30 minutes (file moves + import updates + test imports).
  - **Spec D4 worked-example contradiction surfaced and resolved with judgment call.** The formal definition "non-empty intersection" diverges from the prose worked example `{A,B} → {B,C}` labeled UNSTABLE (intersection `{B}` is non-empty, so naive intersection rule would say STABLE). Backend agent implemented **subset-or-superset** semantics (one set must contain or be contained by the other) which matches all 8 worked examples. Documented in `winner_set_overlaps` docstring + tests cover all 8 cases. Spec writer should reconcile D4's formal text in any future revision (the worked examples are the load-bearing intent; the prose description should be updated to match).
  - **`original_voting_end` reconstruction via audit-log walk.** Per spec line 308 the spec writer offered "audit-log walk OR new column on proposal." Backend agent chose audit-log walk (no second migration; existing `proposal.window_extended` audit events with `extension_seconds` are already written). Trade-off: each worker tick does one extra audit-log query per active proposal (negligible at current scale). If scale grows or the audit-log table grows large, switch to a new `Proposal.original_voting_end` column.
  - **Phase 20 verification gate execution:** the spec required prod-snapshot Docker round-trip per Item 54 lesson; this pass exercised that pattern as the load-bearing migration verification (alongside the standard PG smoke + actual-upgrade flag). Result: PASS — see Phase 20 PROGRESS entry.

- 2026-05-11 (Phase 21 closeout — Delegate Action & Voting Deadline Notifications + Preference Presets): five new notification events added (`delegate.voted`, `delegate.vote_changed`, `delegate.posted_rationale`, `voting.halfway_delegate_silent`, `voting.halfway_you_havent_voted`) plus a preset selector for one-click preferences stamping (High / Medium / Low engagement). **No items resolved this pass** (additive feature; no in-scope cleanup). **D17 audit of EVENT_REGISTRY for dead-checkbox events**: walked every event in the post-Phase-21 EVENT_REGISTRY and confirmed each has an active emission site or scheduler hook. Phase 13.3's deletion of `sustained_majority.floor_approached` from the registry was the last documented dead-checkbox event in this category; D17 finds none currently. New audit items logged:
  - **Item 59 (Tier 3): Halfway-event scheduler runs outside request context — `email_immediate` channel forfeit.** The `run_halfway_deadline_check` task passes a fresh `BackgroundTasks()` to `emit_notification` whose task list is never executed (no request lifecycle to flush it). In-app rows insert correctly, and digest channels (`email_daily` / `email_weekly`) pick them up at the next tick. But a user with `email_immediate` enabled on `voting.halfway_*` will NOT receive an instant email for those events — only an in-app row + (optionally) inclusion in their next digest. The spec is silent on this trade-off; D11 defaults email ON for halfway events but doesn't specify which email channel. Acceptable for v1: most users want batched, and halfway-deadline isn't time-critical (the user has at least half the voting period remaining). **Suggested:** if a real-pilot signal asks for instant emails on halfway events, restructure the scheduler to use a proper email-send path (call `send_event_email` directly from the scheduler, parallel to the digest's `render_and_send_digest` pattern). Effort: ~1 hour (refactor + tests).
  - **Item 60 (Tier 3): Dedup check has a small race window for concurrent vote writes.** `should_emit_with_dedup` queries committed `Notification` rows; two concurrent vote-write requests for the same delegator/delegate/proposal could both pass the dedup check before either commits a row. Worst-case impact: 2 notifications instead of 1 within the 1-hour window — never worse, never duplicate-firing across hours. Documented in wave-2 backend agent's closeout. **Suggested:** if real signal asks for stricter dedup, switch to a SELECT-FOR-UPDATE-style lock on the dedup-check or add a unique constraint `(user_id, event_type, target_id, hour_bucket)` with collision handling. Effort: ~1.5 hours. Tolerable for v1.
  - **Item 61 (Tier 3): CTA URLs for the new email templates fall back to `/notifications` because emission payloads don't populate `org_slug`.** Matches the pre-existing pattern at all other emission sites (comments, proposals, etc.) — `_build_event_template_vars` resolves `org_slug` from payload, and no current emission path includes it. The Phase 13 in-app surface resolves slug server-side via `_bulk_org_slug_lookup` in `routes/notifications.py`, so click-through routing works on the in-app surface; only the email CTA falls back. **Suggested cleanup sweep across all emission sites:** add `org_slug` to every `emit_notification` payload that fires from an org-scoped event (a 1-line addition per call site after a single `org_slug` lookup). Effort: ~1.5 hours; affects ~12-15 emission sites in `routes/comments.py`, `routes/proposals.py`, `routes/votes.py`, `routes/organizations.py`, etc. Pre-existing gap, not a Phase 21 regression.

- 2026-05-12 (Phase 23 closeout — Demo Daily Reset Infrastructure): demo bibles moved to `backend/demo_content/` with extracted `schema.py`; migration `c7e8a3d419f5` adds 8 columns (5 demo + 3 branding) + `User.headshot_url` + `ix_organizations_is_demo` index; `demo_reset_job.run_demo_reset_if_due` orchestrates wipe-then-seed in a transaction; snapshot generator emits Phase-22-shape JSON; filler-member generator (PRNG-seeded per org_slug) produces ~55 members per org with deterministic identity + delegation patterns; cross-org user mapping (Marcus/Dana/Janet → single User row each, two OrgMemberships) resolved at seed time per Stage 8 §5; Janet's 8 Local votes hardcoded in seed_pipeline.py; `GET /api/orgs/demo` public directory endpoint with Cache-Control max-age=60 and DST-aware next_reset_at; `POST /api/auth/demo-login` extended with `org_slug` for per-org persona allowlist (legacy `{username}`-only path preserved through transition); manual-trigger `POST /api/admin/demo/reset` for ops; frontend DemoOrgBanner + Demo.jsx three-org rewrite; **no items resolved this pass** (additive infrastructure). New audit items logged:
  - **Item 65 (Tier 3): Multi-option (approval/RCV/STV) snapshot generation uses a heuristic per-option distribution** rather than parsing the trajectory's free-text `final_result` string. Snapshots get the right Phase 22 shape (`option_totals` present) so the trajectory chart renders meaningfully, but per-option tallies don't precisely reproduce bible-specified values like "Items 1: 75%, 2: 73%". Pragmatic fallback documented in `demo_snapshot_generator.py` per spec D6 update + Stage 8 §7. **Suggested:** add structured per-option result data to `Trajectory` schema (e.g., `final_per_option: dict[option_id, percent]`) so the generator can interpolate to real targets. Effort: ~2 hours bible-side + ~30 min generator-side. Defer until real-pilot signal asks for precise per-option trajectories.
  - **Item 66 (Tier 3): Persona descriptions default to `role` because bibles don't carry the Stage 8 §6 descriptions as Python data yet.** Amendment D specified a `quick_login_descriptions: dict[user_id, str]` map; the bibles haven't added this. The seed pipeline uses `description = m.role` as fallback (logs a warning). **Suggested:** content agent adds `quick_login_descriptions` to each bible as a top-level constant; seed pipeline already wired to consume it (just change the default branch). Effort: ~15 min seed-side + content agent's writing time. Defer to next bible touch-up pass.
  - **Item 67 (Tier 3): 5 notification event_types in bibles not in Amendment A's template table.** `srr_extension_granted`, `srr_destabilization`, `new_comments`, `author_comment`, `follower_feedback`. Seed pipeline falls back to `"{event_type}: {note}"` and logs warnings. **Suggested:** expand Amendment A's table OR rename bible event_types to match existing keys. Effort: ~30 min (decide + edit table + verify warnings disappear). Defer.
  - **Item 68 (Tier 3): Filler multi-option vote allocation does not aim at trajectory final tally.** Binary fillers hit the parsed `(yes_pct, no_pct)` split within ±2 votes (B5#31 verified). Approval/RCV/STV fillers vote a random subset (approval: 1-2 options) or shallow ranking (RCV/STV: 2-4 deep) without convergence to the trajectory's first-choice distribution. **Suggested:** when Item 65 lands (structured per-option result), pipe the same data into `allocate_filler_votes` to converge multi-option ballots. Effort: ~1 hour. Same defer trigger as Item 65.
  - **Item 69 (Tier 3): Filler comments (Amendment C) deferred to scope-tighten "skip if needed" path.** Bible has named-character substantive comments; fillers contribute only votes + delegations. Comment density may feel thin on browsing demo pages. **Suggested:** add a `light_filler_comments=True` flag to seed_pipeline that emits ~5% of fillers with one-line "voting yes/no" comments. Effort: ~45 min. Defer until browser verification surfaces "comments feel sparse" feedback.

- 2026-05-11 (Phase 22 closeout — Support Trajectory Chart): universal VoteSnapshot capture (was: SRR-only) + per-option vote counts in existing `multi_option_winners` JSON payload + new `GET /api/proposals/{id}/trajectory` endpoint with downsampling + recharts-based chart component with SRR annotation overlay on proposal results page. **No items resolved this pass** (additive feature; no in-scope cleanup). New audit items logged:
  - **Item 62 (Tier 3): Snapshot growth at scale.** At plausible scale (100 concurrent voting proposals × 288 snapshots/day × 365 days × ~300 bytes/row), ~3 GB/year. Manageable for Postgres at near-term scale but worth tracking. **Suggested:** if storage growth reaches alert thresholds (~30+ GB or DB size approaches Railway's plan cap), implement snapshot TTL/downsampling at the DB level (separate from the API-layer downsampling that Phase 22 already provides). Per-proposal: keep all snapshots while voting; downsample to ~500 retained snapshots once closed (or keep originals for 90 days then downsample). Effort: ~2-3 hours (DB-side downsampling script + cron task + alembic migration if retention metadata needed). Tier 3 — defer until real scale signal.
  - **Item 63 (Tier 3): Org-config gate for proposal_chart_enabled (D14) not implemented.** Phase 22 spec D14 specifies an org-level toggle to disable charts; not shipped this pass (no `proposal_chart_enabled` field in `Organization.settings` JSON yet). Frontend renders the trajectory toggle unconditionally for v1. **Suggested:** add the JSON-settings field with default true; surface in Org Settings UI as a checkbox; frontend reads `currentOrg?.settings?.proposal_chart_enabled ?? true` (gate already noted in the SupportTrajectoryChart component's parent). Effort: ~1 hour (backend pydantic field + frontend toggle + tests). Defer until an org actually requests disabling charts.
  - **Item 64 (Tier 3): Keyboard navigation for chart tooltips inherited from recharts defaults, not separately wired.** F4 a11y shipped: aria-label, hidden aria-live summary, "Show as data table" toggle with semantic `<table>`. But keyboard navigation through data points (arrow keys move focus indicator through points, Enter to show tooltip) was a soft-requirement in the spec; what shipped is whatever recharts provides by default. **Suggested:** if accessibility audit surfaces this as a gap, wire custom keyboard handlers on the chart container; recharts has an `onMouseMove`/`activeTooltipIndex` pattern that can be driven from keyboard events. Effort: ~1.5 hours. Defer pending accessibility audit signal.

- **F2 incidentals from Phase 18 diagnostic — added as new audit items (Tier 3, deferred):**
  - **Item 43: `graph_store.add_delegation` race window between DB commit and graph mutation.** `graph_store` is mutated incrementally on every delegation add/remove route call; the route flushes/commits to DB then calls `graph_store.add_delegation(...)`. Small race window if two requests interleave; not load-bearing now (rebuild from DB on every startup), but worth a `with transaction.atomic()`-shaped fix at scale. Source: diagnostic §8 F2.
  - **Item 44: `routes/admin.py::system_delegation_graph_all_orgs` long-term shape.** Phase 18 kept the cross-org admin endpoint as `system_delegation_graph_all_orgs` (HTTP path unchanged) for forensic admin work, plus a sibling `/api/admin/orgs/{slug}/delegation_graph` for org-scoped admin queries. Whether the cross-org default is the right long-term shape (admins might prefer per-org tools by default) is worth a future design conversation. Source: diagnostic §8 F2.
  - **Item 45: Phase 8.5 "Only parent-org topics" fan-out — known-suboptimal.** Post-Phase-18, the "Only [SubOrg]" radio path produces a single `(org_id=parent, sub_org_id=Y, topic_id=NULL)` row, but the "Only parent-org topics" path still fans out to N per-topic rows because the data model doesn't currently express "scope-by-parent-only-topics" as a single row. A clean single-row representation would require a new `scope_modifier` column on `Delegation`. Out of scope for Phase 18; documented inline in `DelegateModal.jsx` and here. Source: diagnostic §8 F2.
  - **Item 46: `UnderstandingDelegationsHelp.jsx` not added in Phase 18.** Spec called for a brief help-page section explaining "global within an org" semantics and the per-org delegation pattern. Deferred from Phase 18 because the existing help-page surface requires nav-link integration + routing wiring for discoverability, expanding scope beyond housekeeping. Add when a help-page nav refresh or related help-area pass naturally cycles. Frontend agent shipped per-org copy on Delegations.jsx ("Your delegation network in {OrgName}") which provides immediate UX reinforcement; the help-page is for users who want the model explained explicitly.

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

### Item 5: Sustained-majority `floor_breached` inconsistency in `build_status` — RESOLVED in Phase 20 (2026-05-10)
- Source: PROGRESS.md Phase 9.8 tech debt #2
- Resolution: Phase 20 deleted the entire binary floor mechanism (`is_above_floor`, `is_approaching_floor`, `support_ever_established`, `evaluate_binary`, `failure_mode`, `floor_breached`, `approaching_floor`, `distance_to_floor`, `STABLE_RESULT_FRACTION` constant, `FLOOR_APPROACH_DELTA`, `floor` config field, `failure_mode` config field, `ALLOWED_FAILURE_MODES`, `extension_window_for`, `should_trigger_failure`, `evaluate_multi_option`). The inconsistency is gone because the floor concept is gone. The redesigned mechanic uses unified result-stability in a stable window (final fraction of voting period; sliding-window check during extensions; `original_voting_duration × max_extension_fraction` budget cap). See Phase 20 PROGRESS entry + `phase20_stable_result_required_spec.md` for the full mechanic. Item retained with RESOLVED status for traceability.

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

### Item 28: F7 legacy `'owner'` acceptance in OrgSettings.jsx — RESOLVED (Phase 16 Cluster G1)
- Source: PROGRESS.md Phase 12 Stage 2 tech debt #3
- Description: Defensive 'owner' branch in OrgSettings.jsx D4 hardcoded gate (Danger Zone visibility). Tighten to strict `'steward'` after age-out.
- Status: RESOLVED in Phase 16 Cluster G1 — `isSteward` derivation in `OrgSettings.jsx` reduced to `currentOrg?.user_role === 'steward'` (legacy `'owner'` branch removed; rationale comment trimmed since the cached-cutover protection is no longer load-bearing).

### Item 29: Tier-shortcuts on Permissions nav link visibility + F6 read-only detection — RESOLVED (Phase 16 Cluster G2)
- Source: PROGRESS.md Phase 12 Stage 2 tech debt #1, #2
- Description: Two places where the nav-link / read-only detection uses tier shortcut even though Phase 12.5 B4 already exposes `user_permissions` in `currentOrg`.
- Status: RESOLVED in Phase 16 Cluster G2 — `RolePermissionsPage.jsx` `canEdit` now uses `useHasPermission('role_permissions.edit')`, so the matrix self-administers (anyone granted that permission via the matrix UI can edit it).

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

### Item 42: Frontend test framework absent
- Source: PROGRESS.md Phase 17 closeout (logged 2026-05-09)
- Description: `frontend/package.json` declares no test runner — no vitest, jest, RTL, or jsdom devDeps; `frontend/src/` contains zero `*.test.*` files. Phase 17's F4 cluster (frontend unit tests for OrgSettings tie-resolution dropdowns + ApprovalResultsPanel/RCVResultsPanel banner rendering) was specced assuming a test framework existed and ended up DEFERRED at dispatch time when the frontend agent discovered nothing was installed. Browser verification covered the load-bearing F1 + F2 surfaces; the F4 unit tests would have been belt-and-suspenders, not primary verification.
- Recommendation: TIER_3 — bootstrap a vitest + jsdom + @testing-library/react harness as its own dedicated pass. Includes: devDep additions + lockfile + `vitest.config.js` + `setupTests.js` + first-wave tests across already-shipped surfaces (Phase 16 F1 form gating, Phase 17 F1 dropdowns + F2 banner, possibly older OrgSettings sections). Treating it as a real cluster of work — not a rider on a feature pass — avoids the Phase 17 mid-pass scope-creep risk again. **When a future feature pass touches frontend in a way where unit tests would meaningfully reduce regression risk, this entry is the trigger to bootstrap the harness in the same pass.**
- Effort: ~half a pass (infra setup + first-wave tests).
- Carries forward Phase 17's deferred F4 scope: tests for OrgSettings tie-resolution dropdown rendering + save shape; ApprovalResultsPanel + RCVResultsPanel banner-presence-when-tie / banner-absent-when-no-tie; method-specific copy.

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
