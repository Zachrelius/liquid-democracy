# Liquid Democracy — Build Progress

This is the canonical state document for the platform. It carries full detail for the most recent ~6 phase entries (Phase 9 onwards) and brief summaries of everything before. For deeper reference on early-platform work (Phase 4-era multi-tenancy retrofitting, multi-option voting scaffolding, sub-organization data model decisions, etc.), see `docs/PROGRESS_archive_phase1-8.md`. Both files were extracted from the pre-split snapshot at `Archive/PROGRESS_5-3-26Full.md` on 2026-05-03.

---

## Phase 1 — Core Backend ✅ Complete

FastAPI + SQLAlchemy/SQLite, JWT auth, delegation engine (pure + service layers), audit log, security middleware, Alembic migrations. 36 tests. Foundation everything else builds on. See `docs/PROGRESS_archive_phase1-8.md` for full detail.

## Phase 2 — Frontend MVP ✅ Complete

React 18 + Vite + Tailwind. Three screens: Login/Register, Proposals list+detail, My Delegations with drag-to-reorder precedence and delegate search modal. See archive for detail.

## Phase 3a — Delegation Permissions Backend ✅ Complete

Public delegate profiles (per-topic, with bios). Consent-gated follow system with `view_only` and `delegation_allowed` permission levels and three default-policy options (`require_approval` / `auto_approve_view` / `auto_approve_delegate`). Cascade-revoke on follow deletion. New permission helpers `can_delegate_to`, `can_see_votes`. Backend tests 36 → 64.

## Phase 3b — Delegation Permissions Frontend ✅ Complete

`POST /api/delegations/request` smart-delegation endpoint (creates directly if permitted, otherwise queues `delegation_intent` linked to a follow request, auto-activated on follow approval). New DelegateModal with permission-aware result cards. New FollowRequests component, UserProfile page, NotificationBadge, user dropdown. 9 new delegation-intent tests. Backend tests 64 → 73.

## Phase 3c — Delegation Graph Visualization ✅ Complete

D3.js v7 SVG force-directed graphs. `VoteFlowGraph` per-proposal (yes/no/abstain clustering, vote weight node sizing, public-delegate dashed double-ring, anonymous-by-default for unfollowed users). `DelegationNetworkGraph` star/ego graph on My Delegations. Two new endpoints: `/api/proposals/{id}/vote-graph`, `/api/delegations/network`. Includes nine post-ship polish fixes (zone backgrounds, topic label dedup, follow-vs-delegation request distinction, action-button detail panels, fit-to-content reset zoom, non-voter toggle).

## Phase 3 Cleanup ✅ Complete

`UserLink` component for clickable user names everywhere. Settings page (`/settings`) with profile, follow/delegation preferences, public delegate registration, change-password sections. New `PATCH /api/auth/me` and `POST /api/auth/change-password`.

## Phase 4 (a/b/c/d) — Multi-Tenant Pilot Readiness ✅ Complete

The big lift to make the platform pilot-ready.
- **4a** — Docker (backend + frontend Dockerfiles, docker-compose with PostgreSQL 16), health endpoints, structured JSON logging, deployment guide. Required CRLF normalization and start.sh ordering fixes that have echoed through subsequent deploys.
- **4b** — Authentication hardening: email field on users, email verification flow (24h tokens), password reset (1h tokens, 3/hr rate limit, anti-enumeration), refresh tokens (7d), short-lived access tokens (15min, was 24h). Auto-refresh on frontend 401.
- **4c** — Multi-tenancy via Organizations (`Organization`, `OrgMembership`, `Invitation`, `DelegateApplication` + nullable `org_id` retrofit on Topics/Proposals/DelegateProfiles). 29 org-scoped endpoints. Six admin pages (settings, members, proposals, topics, delegate applications, analytics). 4-step SetupWizard for first-run.
- **4d** — OWASP Top 10 review (all PASS, see `SECURITY_REVIEW.md`). UI polish (Spinner, ErrorMessage, empty states). Demo quick-switch login. Privacy/Terms pages. Mobile responsive nav.

QA: 33/33 PASS across Suites E/F/G. Backend: 73/73.

## Phase 4 Cleanup ✅ Complete

Seven targeted fixes from manual admin testing. Org settings JSON mutation persistence (SQLAlchemy didn't detect in-place dict mutations — replaced with new-dict construction). Member reactivation endpoint. Minimal moderator powers via `require_org_moderator_or_admin` middleware. Proposal lifecycle frontend-route fix. Admin workflow audit (5 workflows). Email verification enforcement smoke test. Suite H 13/13. Backend tests 73 → 96 (+23).

## Phase 5 — Permission-Alignment + Dialog Replacement ✅ Complete

Four frontend fixes. `AdminOnlyRoute` distinguishing admin-only from moderator-accessible pages. Members fetch decoupling (initial fix incomplete; Phase 5.5 finished it). Disabled vote/delegate buttons for unverified users with explanation copy. Replaced 27 alert/confirm callsites with Toast (21) and ConfirmDialog (6). Suite I 11/11.

## Phase 5.5 — Bug Triage ✅ Complete

Three bugs from Phase 5 review. Members page empty for moderators (Phase 5 catch-block coupling fix completed). Email verification 500 (`TypeError: can't compare offset-naive and offset-aware datetimes`; SQLite strips timezone — fixed `_now()` across all route modules to return naive UTC). Registration auto-join "gap" — not a bug, registration is intentionally org-independent. Backend tests 96 → 101.

## Phase 6 — Multi-Option Voting (Approval) ✅ Complete

Full multi-option voting scaffolding shipped with approval voting as the first method. New `Proposal.voting_method` enum (binary/approval/ranked_choice), `Proposal.num_winners`, `ProposalOption` table, `Vote.ballot` JSON for `{"approvals": [option_id]}`. Method-aware vote casting, tabulation, results endpoint, delegation engine. Admin tie resolution endpoint (algorithm-free). New OptionsEditor, ApprovalBallot, ApprovalResultsPanel components. VotingMethodsHelp page. Backend tests 101 → 136 (+35). Suite J 14/15. PG smoke fixed two startup bugs (CRLF in start.sh; bootstrap migration ordering).

## Phase 6.5 — EA Demo Landing + Public Deployment ✅ Complete

Tactical insertion before EA events. Public landing surface (`/`, `/about`, `/demo`), persona quick-login, demo-org auto-join on email verify, idempotent `seed_if_empty.py`. Real Resend HTTP API integration after Gmail SMTP discovered blocked from Railway at TCP level (both 587 and 465). Live at `https://www.liquiddemocracy.us` via Railway + custom domain via GoDaddy + Let's Encrypt. Six deployment issues surfaced and fixed during bringup (port autodetect defaults, nginx 502 SNI, no Hobby-tier shell, SMTP timeout, Gmail block, `_railway-verify.www` DNS gotcha). Backend tests 136 → 145 (+9).

## Phase 7 — Multi-Option Voting (RCV/STV) ✅ Complete

Ranked-choice (IRV) and STV on top of Phase 6 scaffolding. `pyrankvote==2.0.6` pinned (algorithms are settled math, library well-tested, wrapped in service-layer for swappability). New `RankedBallot.jsx` (drag-to-rank UI), `RCVResultsPanel.jsx` (round-by-round breakdown, fractional STV transfers, tied-final-round banner). `MyVoteStatus.delegation_strategy_fallback` for the strict-precedence-only restriction on multi-option. Backend tests 145 → 191 (+46). Suite K 18/18.

## Phase 7B — Method-Aware Vote Network Visualization ✅ Complete

`VoteFlowGraph` made method-aware dispatcher. `BinaryVoteFlowGraph` (extracted unchanged) + new `OptionAttractorVoteFlowGraph` for approval/RCV with pinned options on a circle, custom `optionAttractorForce`, voter-voter charge, hover-to-isolate, per-option toggle legend. Shared `voteFlowGraphUtils.js`. Vote-graph endpoint extended with `voting_method`, `options[]`, per-voter `ballot`, method-aware `clusters`. `votes_cast` counter fix for RCV. Backend tests 191 → 200 (+9). Suite M 11/11. Bug surfaced post-deploy: React error #31 from clusters.not_cast back-compat dict-vs-int — fixed.

## Phase 7B.1 — Vote Network Polish ✅ Complete

Six polish items from Z's review. Toggle checkboxes wired (force removal). Voter-to-option arrows with RCV linear opacity decay (1.0/0.3/0). Drifting option attractors (replaced fx/fy pinning with spring `optionAnchorForce`). Pre-tick simulation (300 iterations before paint). "Currently winning"/"Currently passing" copy on in-progress proposals. Decision 6 (privacy fork) verified as data-not-bug (thin demo data — most voters correctly anonymous to default login). Suite M extension 8/8 → combined 19/19.

## Phase 7C — Round-by-Round Sankey + Phase 7B.2 Polish ✅ Complete

D3-Sankey RCVSankeyChart component reading directly from `tally.rounds`. Pure helper `buildSankeyData(tally)` constructing per-round nodes + carry/transfer links. Reuses `colorForOption` for visual consistency with network graph above. Provisional framing on in-voting RCV/STV. d3-sankey ^0.12.3 accepted under same algorithms-don't-change rationale as `pyrankvote==2.0.6`. Bundled Phase 7B.2 polish: delegator ballot-arrow suppression (caught `is_direct` vs `vote_source` field-name bug during QA), method-aware VoteGraphLegend. Suite N 8/9 PASS + 1 SKIP. Suite M ext 4/4. PG smoke skipped (frontend-only).

## Phase 7C.1 — Visualization Polish + Privacy Boundary Clarification + Demo Data Refresh ✅ Complete

Three workstreams. **Backend privacy boundary fix** decoupled ballot content from identity visibility — `get_vote_graph` no longer gates `ballot_obj` on `can_see_identity`; new framing is "we hide who voted what, not what was voted." Massive demo-side payoff: option-attractor visualization now shows whole population's voting pattern, not just the small subset of named voters. **Frontend visualization improvements:** Sankey Initial + Final columns, anonymous voter arrows + dashed-border treatment + privacy-explanation tooltip, inherited-abstain hover qualifier. **Seed refresh resolved deferred "Additive Idempotent Seed" tech debt** — every seed helper now skip-if-exists, voter list expanded from 13 placeholder names to 27 realistic ones, alice follows ~half (13/27) so privacy boundary is visible in the demo. Backend tests 200 → 209 (+9). PG smoke 3-run idempotency PASS. Suite N ext 3/4 PASS + 1 SKIP. Suite M ext 6/6.

## Phase 7.5 — Privacy and Access Hardening ✅ Complete

Real institutional-privacy work to align platform behavior with Security & Trust page claims. Audit log redaction via `REDACTED_DETAIL_FIELDS = {"vote.cast": ["vote_value", "ballot", "previous_value"], "vote.retracted": [...]}` allowlist gating ballot content out of default `GET /api/admin/audit`. New elevated endpoint `GET /api/admin/audit/ballots/{id}` requires non-empty `reason` query param and self-logs the elevation as `admin.audit_ballot_viewed`. System-wide endpoints `/api/admin/delegation-graph` and `/api/admin/users` now log access events. New `GET /api/users/me/access-log` and "Data Access History" panel on Settings. Documentation: `is_admin` privilege docstring in `auth.py`, top-of-file comment in `routes/admin.py`, "Privileged Access Tiers" section in `SECURITY_REVIEW.md`, "Current Deployment Status" section in `DEPLOYMENT.md`. Backend tests 209 → 221 (+12). PG smoke PASS — Python-side JSON filter approach structurally avoids SQLite/PostgreSQL JSON-path divergence. Suite O 9/11 PASS + 1 PASS-with-note + 1 SKIP-with-reason.

## Phase 7C.2 — Sankey Eliminated-Flow Bug + Small Polish ✅ Complete

Headline: Steering Committee STV Sankey rendered eliminated options as if their votes were still flowing forward. Diagnosed by dumping `tally.rounds` from prod first (lesson: dump JSON before fixing visualization bugs). Root cause: pyrankvote 2.0.6 packs paired surplus + elimination events into single round; `transferred_from` set to larger drop, smaller drop's volume silently merged into breakdown. Backend split unworkable (would require reimplementing transfer algorithm against raw ballot data). Path chosen: frontend robustness — `buildSankeyData` now detects multi-source rounds and attributes breakdown proportionally, plus emits synthetic `__exhausted__` sink for ballot volume that doesn't transfer. Tag distinguishes `transfer-surplus` (source elected previous round), `transfer-multi-source` (approximation explicitly disclosed in tooltip), `transfer-exhausted`. Anonymous voter tooltip trimmed to two-line form. Detail panel inherited-abstain copy aligned with hover form. Suite N ext N14-N15 PASS browser-driven (DOM inspection of rendered `<path>` data confirms exact pre-fix arithmetic). Suite M ext M31-M32 PASS-by-source (synthetic mouseenter unreliable on React-state-driven tooltips).

## Phase 8 — Sustained-Majority Voting Windows (opt-in) ✅ Complete

Fully configurable, default-off opt-in governance feature. Five org config keys (`sustained_majority_enabled_default`, `_per_proposal_override`, `_threshold`, `_floor`, `_failure_mode`), all default to off / threshold-equivalent / fail-safe — existing orgs see zero behavior change until admin flips a switch. Per-proposal override via `Proposal.sustained_majority_enabled` nullable boolean (null = inherit org default). New `unresolved` status enum value (only reachable via failure_mode=`escalate`). `VoteSnapshot.multi_option_winners` JSON for stable-result tracking on approval/RCV.

Pure module `sustained_majority.py` (39 unit tests). Service module `sustained_majority_service.py` with `validate_per_proposal_override`, `count_extensions`, `build_status`, `capture_snapshot`, `apply_failure_mode` (three branches: fail / extend / escalate, all atomic with audit event), `diff_sustained_majority_settings`. Background worker `sustained_majority_worker.py` running as side process to uvicorn, wakes every 300s, multi-instance protection via `SUSTAINED_MAJORITY_WORKER_INSTANCE_ID`, hard kill-switch `SUSTAINED_MAJORITY_WORKER_DISABLE`. SIGINT/SIGTERM finish current tick then exit cleanly. `--once` flag for tests.

Frontend: OrgSettings new section with toggles + sliders + radio + help link. ProposalManagement per-proposal override toggle visible only when allowed. EscalationResolutionPanel inline on `unresolved` proposals (4 actions, override requires reason). New `SustainedMajorityPanel.jsx` with binary support-vs-floor bar + Recharts LineChart of historical support / multi-option stable-result lock indicator. Floor-approach amber banner (only when `myVoteContributes`). New `/help/sustained-majority` route. Backend tests 221 → 288 (+67).

Note: Phase 8's floor activation logic had a deferred footgun where a single early no-vote with zero yes-votes could fire failure mode immediately (votes_cast=1, support_fraction=0.0 < floor=0.45). The UI was demoted to collapsed-by-default in Phase 9.6 W4 to keep it from being a footgun in pilots; the worker logic was properly fixed in Phase 9.8 C1 via the new `support_ever_established(snapshots, config)` helper.

## Phase 8.1 — Six-Item Tech Debt Cleanup ✅ Complete

Six independent items from Phase 7C.2/7C.3/8 closeouts. `/help/voting-methods` route gating fix (matched the public pattern from `/help/sustained-majority`). `count_extensions` actor-aware filter (worker entries are `actor_id IS NULL`; admin manual extensions shouldn't count toward the worker's "extension already used" guard rail). Sankey alphabetization for stable column ordering. Carbon Tax voter overrepresentation trim. Per-proposal override toggle defaults match org's `sustained_majority_enabled_default`. DEPLOYMENT.md "phantom socket on port 8001" troubleshooting note (uvicorn `--reload` watcher + stale process pattern). Backend tests 288 → 291 (+3).

## Phase 8.5 — Sub-Organizations ✅ Complete

Largest feature pass since Phases 6-7. Adds nested decision scopes — departments within companies, locals within unions, class years within schools, committees within councils. Single-org flows unchanged.

Two-level hierarchy via `Organization.parent_org_id` (nullable self-FK). Sub-org membership opt-in or admin-assigned (not automatic from parent). New `SubOrgMembership` table parallel to `OrgMembership`. `Topic.sub_org_id` and `Proposal.sub_org_id` nullable FKs. `Proposal.sub_org_private` boolean for opt-out of default visibility-to-parent-org. Migration `d41a8c92f3b1` idempotent + reversible.

Ten design decisions locked in before dispatch (two-level hierarchy, opt-in membership, scope-aware visibility for topics+proposals+delegations, parent-org-admin "Decision 6 implicit power" within own org family, per-key inherit/override surface in SubOrgSettings). Major nav rework: org hierarchy visible. New SubOrg* admin pages. Scope badges on topics/proposals/delegations.

15-minute 502 incident during first deploy: bootstrap migration `Base.metadata.create_all` + `alembic stamp head` ordering collided with new sub-org migration's CREATE TABLE statements. Hot-fixed mid-deploy by patching migration to be idempotent. Phase 8.6 Item 3 fixes the underlying ordering issue properly.

Backend tests 291 → 373 (+82). Multi-persona prod sanity PASS. All 10 design decisions implemented.

## Phase 8.6 — Phase 8.5 Carry-Forward Cleanup ✅ Complete

Four items from 8.5 closeout. Decision 3 topic visibility filter completeness (sub-org-scoped topics no longer leak to non-members in `/topics` browsing — backend extended with SubOrgMembership join + Decision 6 exception). Demo seed: voter02's Engineering Economy delegation row (one-line fix unblocking Suite R9 cross-scope demo flow). `start.sh` migration ordering fix: now runs `alembic upgrade head` first (handles fresh-DB stamp+upgrade OR existing-DB upgrade), then `seed_if_empty` only if `IS_PUBLIC_DEMO=true`. Eliminates the create_all+migration collision pattern. PG smoke `pg_smoke.py` rewrite: `--prior-revision <id>` argument, modes `fresh` (downgrade base then upgrade head) and `upgrade` (start from prior_revision then upgrade head). Both modes catch ordering collisions. Pattern adopted by all subsequent phases. Backend tests 373 → 378 (+5).

---

## Phase 9 — Polis Integration — Session 1 + Session 2 — 2026-04-30

(Session 1 = data layer foundation; Session 2 = backend service + admin endpoints. Both shipped on the long-running feature branch `phase-9/data-layer`. Sessions 3 + 4 follow.)

Sessions 1 and 2 established the Polis-as-first-class-artifact data model (`Polis`, `PolisXid` tables) and the backend service layer for the dual-path (programmatic when `POLIS_AUTH_TOKEN` is provisioned, manual-fallback when not). Out-of-band CompDemocracy contact requested no update; v1 ships against manual-fallback path on Session 4 deploy.

**Session 1 — Data layer foundation.** New `Polis` model: `id`, `org_id`, `sub_org_id` (nullable mirror semantics — null = parent-org-wide, non-null = sub-org-scoped, matches Topic/Proposal pattern), `title`, `prompt`, `polis_conversation_id` (nullable until manual-fallback paste), `intended_seed_statements` (JSON array stored platform-side for "paste into pol.is admin UI" reference), `linked_proposal_ids` (JSON array, editorial-only — proposals link Polises, not the other way around), `status` (active/archived), `created_at`, `created_by`. New `PolisXid` model for per-org pseudonymization: `id`, `org_id`, `user_id`, `polis_xid` (UUID generated server-side on first call, idempotent, audit `polis.xid_generated` fires once per user-per-org). `Proposal.linked_polis_ids` JSON array for editorial linking. Schema migration `e7b3f9a02c14_phase_9_polis_integration.py` reversible + idempotent.

Helper `eligible_viewers_for_polis` mirrors `eligible_viewers_for_proposal` semantics (parent-org-wide visible to all members; sub-org-scoped follows Decision 5 visibility from Phase 8.5). Audit events: `polis.created`, `polis.archived`, `polis.deanonymized_export`, `polis.connected` (Session 4), `polis.archive_reminder_logged`, `polis.title_edited`, `polis.xid_generated`. 26 integration tests in `test_polis_models.py`. Backend tests 378 → 421 (+43 across Sessions 1+2).

**Session 2 — Backend service + admin endpoints.** New `polis_service.py` wraps pol.is API client + manual-fallback paths. `polis_engine.py` exposes high-level operations (`create_polis`, `archive_polis`, `export_polis_data`, `connect_conversation_id`). Routes in `routes/polises.py`: 7 endpoints (CRUD + xid + export + connect). PATCH route accepts `title` and `status` only in Session 2; `polis_conversation_id` extension was the load-bearing API gap Session 4 closed. Deanonymized export shape ships `?deanonymize=true` query param + audit + output as single-file concatenation with `--- POLIS EXPORT ---` separator (v1-grade). Backend tests 421 → 459 (+38).

Tech debt logged across the two sessions: N+1 on `linked_polises` resolution (small per proposal — defer until usage spikes); N+1 on linked-from indicator in PolisDetail (FE filters proposal list client-side); manual-fallback archive doesn't surface "go close on pol.is" reminder in response (resolved Session 3 via `/api/public-config`); `org_config.get_org_config` walking `parent_org` ORM relationship may need explicit `db.refresh(sub)` after creation on SQLite-in-memory.

---

## Phase 9 — Polis Integration — Session 3: Frontend Admin — 2026-04-30

**Branch:** `phase-9/data-layer` (continuing). Session 3 stacks 7 commits on Sessions 1+2's 15. Branch still NOT merged to master at this point.

### What shipped (Session 3)

**Backend: `GET /api/public-config`** — small public endpoint (no auth) returning `{polis_token_configured: bool}` based on `settings.polis_auth_token`. Frontend reads at app boot to drive manual-fallback UX. Resolves Session 2 tech debt #3 (the manual-fallback archive reminder gap). 3 unit tests in `test_public_config.py`. Backend tests **459 → 462 passing (+3)**.

**Frontend admin pages — Phase 8.5 SubOrg* pattern:**
- New `frontend/src/PublicConfigContext.jsx` — lightweight context fetched once at boot. Future feature flags slot in cleanly.
- `Polises.jsx` — parent-org Polis list. Table: title, scope, status, creator, participation count (em-dash for null / `live_stats_unavailable`; "0" only when actually 0), created date. Filter row + status filter + "Create Polis" button gated to moderators+/admins.
- `SubOrgPolises.jsx` — sub-org admin Polis list scoped to one sub-org.
- `PolisDetail.jsx` — single component branching on URL param for parent vs sub-org scope. Header / participation stats panel / **embed-iframe placeholder div** carrying `data-conversation-id` + `data-xid` attributes (xid fetched lazily on mount via `POST .../xid` — idempotent, audit fires first call only). Session 4 swaps the placeholder for `<script async src="https://pol.is/embed.js">` + `className="polis"`. Admin controls (Manage on pol.is link, edit title inline, archive with confirm, download export with deanonymize toggle + privacy confirmation). "Linked from" indicator client-side filtering proposals by `linked_polis_ids.includes(polis_id)`.
- `CreatePolis.jsx` — single form with title, prompt, scope selector, seed statements multi-input. **Dual-path success state branches on `programmatic_path`:**
  - `true`: "Created — view conversation" + Go button + optional `partial_seed_failures` warning
  - `false`: VERBATIM SPEC COPY manual-fallback panel — "Almost done — finish on pol.is" with steps + seed statements with copy-each + copy-all buttons + conversation_id input + Save button
- **Manual-fallback workaround:** form requires `polis_conversation_id` BEFORE submit (pre-create paste). Success-panel Save button captures the field but TODO-toasts because Session 2 PATCH doesn't accept `polis_conversation_id` (API gap surfaced — see API gap section below).

**Archive flow:** confirmation dialog. Manual-fallback warning shown only when `polis_token_configured: false` — verbatim spec copy "Don't forget to close the conversation on pol.is". Follow-up toast after success when token unconfigured.

**Polises nav:** entry in admin dropdown (desktop + mobile, gated by moderator+/admin). Sub-org Polises link per sub-org row in `SubOrgList.jsx`.

**Routing (`App.jsx`):** 6 new routes. Parent: `/admin/polises`, `/admin/polises/create`, `/admin/polises/:polis_id`. Sub-org: `/admin/sub-orgs/:sub_slug/polises[/create|/:polis_id]`. Parent gated through `ProtectedRoute > OrgProvider > AdminRoute > Layout` (matches topic-create tier). Sub-org gated through `ProtectedRoute > OrgProvider > Layout` with permission via `SubOrgErrorState` inline 403/404 (mirrors `SubOrgTopics`).

**Deliberation settings (`OrgSettings.jsx` + `SubOrgSettings.jsx`):** new "Deliberation" section with `require_polis_for_new_proposals` toggle. Sub-org variant adds "Use parent default" checkbox per Phase 8.5 Decision 9 pattern — checked removes the key (so `get_org_config` walks up); unchecked saves explicit value.

**Suite S Preview** in `browser_testing_playbook.md` — S1-S12 verbatim for Session 4's QA teammate.

**CSP confirmation:** No `Content-Security-Policy` header is currently set anywhere (verified `frontend/nginx.conf` + absence of CSP middleware). Session 4's `<script src="https://pol.is/embed.js">` and iframe will load fine. Comment in `PolisDetail.jsx` placeholder div notes that if CSP is added later, `script-src https://pol.is` + `frame-src https://pol.is` are required. Session 1 tech debt #3 closed: documented, no action required.

**Bundle:** 1,158.56 → 1,200.70 kB JS (+42.14 kB raw); 314.46 → **324.71 kB gzipped** (+10.25 kB) — modest growth for 5 new admin pages.

### Multi-persona verification

Live in-browser verification not executed this session (admin-side build only, no fixture-mutation; full multi-persona test belongs in Session 4 prod sanity per dispatch). Source-review heuristic per persona (alice / dave / carol / voter02 / frank) confirms expected access and visibility. `AdminRoute` redirects non-moderator+ from `/admin/polises*`. Sub-org pages defer to backend 403 → `SubOrgErrorState` inline.

### API gap surfaced (load-bearing for Session 4)

Session 2's `PATCH /api/orgs/{slug}/polises/{polis_id}` only accepts `{title?, status?}`. The manual-fallback "Save conversation_id post-create" handoff needs PATCH to also accept `polis_conversation_id`. **Workaround shipped:** form requires `polis_conversation_id` BEFORE submit (pre-create paste required). Session 4 PATCH extension (Recommended Option 1) closed this.

### Session 4 prerequisites (voter UX team)

For the next (final) session — voter UX + Suite S + prod deploy. Voter-UX touchpoints with API contract notes covered: proposal-detail link cards (handle archived state + `live_stats_unavailable`), URL detection in proposal bodies (match `https://pol.is/<6-10 char token>`, render as inline link card), privacy disclosure modal (first-visit-per-Polis, localStorage key `polis_disclosed_<polis_id>`), public Polis page (`pages/Polis.jsx` non-admin member view), notification badge (drives off Session 1's `polis.created` audit), help page `/help/polis` (public route), embed script + iframe wiring, API gap fix.

### New tech debt logged (Session 3)

1. `is_polis_admin` not exposed on `PolisOut`. FE uses heuristic (creator OR moderator/admin OR sub-org admin) to show/hide admin controls; backend remains source of truth via 403 on PATCH/export.
2. Linked-from indicator is N+1 client-side. `PolisDetail.jsx` fetches the full proposal list per detail render.
3. Session 2 PATCH doesn't accept `polis_conversation_id` (above) — **resolved in Session 4** via `d9b66ed` extension.
4. PolisDetail's xid POST has no debounce on remount. Idempotent server-side, but a fast tab-flicker fires multiple POSTs. Cosmetic.
5. Lint warning on `PublicConfigContext.jsx` (`react-refresh/only-export-components`) — matches pre-existing pattern on AuthContext/OrgContext/ConfirmDialog/Toast. Splitting `usePublicConfig` into a sibling hook file would clear them all in one cleanup pass.

---

## Phase 9 — Polis Integration — Session 4: Voter UX + Suite S + Prod Deploy — 2026-05-02

**Branch closed: merged to master in commit `12ca189` (no-ff merge of 30 commits a3613d0..09f432f).** Phase 9 is **LIVE on prod** at `https://www.liquiddemocracy.us` on bundle `index-DeCwuXjM.js`.

### What shipped (Session 4)

**Backend gap fix (`d9b66ed`):** extended `PolisUpdate` schema to accept `Optional[polis_conversation_id]`. Route enforces one-shot connect (allowed only when current value is null; rejects 400 when already set or empty/whitespace). New `polis.connected` audit event. **8 polis.* audit event types total** now (7 from Sessions 1-2 + this). 3 tests in `TestPolisConnectConversationId`. Composite audit-coverage test extended. PG smoke `pg_smoke.py --mode both --prior-revision e72362fd7cd5` both modes PASS. Backend tests **462 → 465 passing (+3)**.

**Voter UX components (Decision 4 — the load-bearing UX of Phase 9):**

- `components/PolisEmbed.jsx` — shared embed component. Renders `<div className="polis" data-conversation_id data-xid>` + lazy-loads `<script async src="https://pol.is/embed.js">` once on first mount via module-level scriptLoaded flag. When conversation_id is null/empty (manual-fallback Polis pre-paste), renders friendly "Polis not yet connected" placeholder card.
- `components/PolisDisclosureModal.jsx` + `hooks/useShouldShowDisclosure.js` — verbatim Decision 4 spec copy ("About this conversation… per-org pseudonym, not your name…"). Per-Polis localStorage isolation via key `polis_disclosed_<polis_id>` — dismissing one Polis does NOT prevent another's modal from firing (each Polis has its own privacy considerations).
- `components/LinkedPolisCard.jsx` + `pages/ProposalDetail.jsx` integration — "Linked Deliberations" section with two trigger paths: (a) structured `proposal.linked_polises` array from server, (b) client-side URL detection (`detectPolisUrlsInBody` regex over markdown body). Detects raw `https://pol.is/<6-10 char>` and markdown link `[text](https://pol.is/<id>)`. Resolves against parent-org Polises list; visible Polises become cards; unresolved URLs fall back to plain links (silently passes through markdown renderer).
- `components/LinkedPolisesPicker.jsx` + admin proposal-create form integration — multi-select dropdown of in-scope Polises + "Create new Polis" inline mini-create form. Form validation blocks submission without at least one link when `require_polis_for_new_proposals` is true.
- `pages/Polis.jsx` (public voter Polis page at `/orgs/:slug/polises/:polis_id`) — header + privacy disclosure + PolisEmbed + "Linked from" indicator. Read-only treatment for sub-org non-members per Decision 7. Server-side `eligible_viewers_for_polis` returns 404/403 → friendly "Deliberation not available" / "Deliberation not found".
- `pages/PolisHelp.jsx` (`/help/polis`) — public route (no `ProtectedRoute`) per Phase 8.6 Item 1 pattern. Covers what Polis is, when to use it, privacy framing, linked Polises, 10:1 voter-to-commenter ratio note.
- `components/NotificationBadge.jsx` integration — per-parent-org poll of `/api/orgs/{slug}/polises` against `polis_last_seen_<slug>` localStorage timestamp. Single-shot per Polis. First-sign-in initializes timestamp without bumping (no historical noise). Click-through routes to `/orgs/{slug}/polises/{polis_id}` and updates last-seen.

**Iframe swap on `pages/admin/PolisDetail.jsx`:** Session 3's placeholder div replaced with `<PolisEmbed conversationId xid />`. xid plumbing already wired in Session 3.

**CreatePolis Save button wired** to the backend gap fix: success-panel `Save` button now calls `PATCH /api/orgs/{slug}/polises/{polis_id}` with `{polis_conversation_id}`. 200: refreshes success-panel state via new `onConnected` callback (input disappears once connected). 400: surfaces backend message ("already set" / "must be non-empty"). Removes Session 3's TODO toast.

**SECURITY_REVIEW.md** gains a new "Polis Identity Model" section covering pseudonymization via per-org `polis_xid`, platform-side deanonymization for moderation via `?deanonymize=true` export with audit, the verbatim Decision 4 disclosure copy as the user-facing privacy boundary, a "What pol.is sees vs what platform sees" table, and the threat model summary (asymmetry made explicit by the disclosure).

**Bundle:** 1,200.70 → 1,227.99 kB JS (+27.29 kB raw); 324.71 → **330.89 kB gzipped** (+6.18 kB).

### Production deploy

Merged `phase-9/data-layer` → `master` via `git merge --no-ff` at commit `12ca189`. Push triggered Railway auto-deploy. **Deploy applied cleanly with no 502 incident** (Phase 8.6's `start.sh` ordering fix held; the new `polises` and `polis_xids` tables came up via the migration's idempotent introspect-and-skip pattern with no collision). Backend healthy at 401 within ~6 minutes total. Bundle `index-DeCwuXjM.js` matches local build.

### Multi-persona prod sanity

Verified live as alice (parent admin, NOT Engineering member). Demo seed Polises propagated additively to prod (Demo Org — Annual Priorities for 2026 org-wide; Engineering Team — Tooling Priorities sub-org). alice exercised the load-bearing Decision 4 case: first-visit modal fires with verbatim spec copy → click "Got it" → modal dismisses, `polis_disclosed_<id>="true"` set in localStorage → navigate to second Polis → **modal RE-FIRES correctly** (per-Polis isolation), org-wide key persisted, Engineering key remained unset. PolisEmbed rendered with `data-conversation_id="demo-polis-org-wide"` and `data-xid="WJom1ncJdxUOW3bOry-Gsw"` (alice's `polis_xid` generated server-side via `POST .../xid`, audit `polis.xid_generated` fired on first call).

dave / carol / voter02 source-reviewed against the same code paths — full multi-persona browser exercise deferred since alice's load-bearing test closed the highest-risk surface.

### Suite S results

**Aggregate: 3 PASS browser-verified + 9 PASS-by-source.** Browser-verified: S3 (PolisDetail renders embed with correct data-xid), **S4 (privacy disclosure + per-Polis isolation — the load-bearing test)**, S12 (`/help/polis` accessible without auth). PASS-by-source: S1, S2, S5-S11 — backend integration tests (`test_polis_routes.py` + `test_polis_eligibility.py` + `test_polis_admin.py` + `test_proposal_linked_polises.py` + `test_polis_xid.py` + `test_polis_service.py` + `test_polis_models.py`) cover the underlying behavior; live admin-create / proposal-edit on prod was deliberately not exercised to avoid mutating live demo state for visitors. Source review per the Phase 8.5 Session 4 / Phase 8.6 precedent. Full test-by-test status table in `test_results/phase9_screenshots/session4_prod_sanity.md`.

### Phase 9 pass-summary

**SHIPPED: Phase 9 Polis Integration is LIVE on https://www.liquiddemocracy.us.**

| Metric | Phase 8.6 baseline | Phase 9 final |
|---|---|---|
| Backend tests | 378 | **465 (+87)** |
| Frontend bundle (gzip) | 317.65 kB | **330.89 kB (+13.24 kB)** |
| Backend endpoints | — | **+7 Polis routes (CRUD + xid + export + connect) + `/api/public-config`** |
| Audit event types | — | **+8 polis.* events** |
| Schema tables | — | **+2 (polises, polis_xids)** |
| Schema columns | — | **+5 (sub_org_id mirror semantics on polises, intended_seed_statements, linked_polis_ids, polis_xid storage)** |

**All 10 design decisions implemented and shipped:** Polis as first-class artifact (1); editorial-only linking (2); live during voting (3); per-org `polis_xid` pseudonymization with verbatim disclosure modal copy + per-Polis localStorage isolation (4 — verified browser-side); visibility mirrors topics/proposals via `eligible_viewers_for_polis` (5); same admin tier creates Polises as topics, Decision-6 implicit power (6); `require_polis_for_new_proposals` org config with sub-org override via `get_org_config` (7); independent active→archived lifecycle (8); moderation delegated to pol.is admin tools (9); in-app notification badge (10).

**Dual-path create + archive** is the v1 production reality. With no `POLIS_AUTH_TOKEN`, every Polis on prod uses the manual-fallback flow: operator pastes a `polis_conversation_id` they created on pol.is, intended seed statements stored platform-side for "paste into pol.is admin UI" reference, archive shows "close on pol.is" reminder.

**Single-org behavior bit-for-bit unchanged.** Existing single-org installs continue to work identically — no Polises until an admin creates one; proposal creation form's "Linked Deliberations" section is empty unless an org admin has created Polises and turned on `require_polis_for_new_proposals`; voter views unaffected for proposals without linked Polises.

### Deferred items (for the roadmap)

Per spec's "Out of Scope" section: self-hosted Polis (Tier 3.9), AI-suggested seed statements (defer to AI delegation/advisor phase), auto-generating proposal text from Polis bridging statements (deliberately not), cross-Polis analytics, public-with-link Polises beyond org membership, auto-archive tied to proposal lifecycle, statement-level moderation through the platform, email digest notifications (Phase 10 if it ships), CompDemocracy admin-token flip from manual-fallback to programmatic (out-of-band).

---

## Phase 9.5 — Org Creation Gap Fix — 2026-05-02

**Single-session focused pass.** 7 commits on `phase-9-5/org-creation`, no-ff merged to master at `3b0e19a`. **LIVE on prod** at `https://www.liquiddemocracy.us` on bundle `index-B-qpoTOu.js`.

The platform's `/orgs/create` page existed and worked, but no UI element linked to it; backend `POST /api/orgs` was gated only on authentication. Z's friend pilot was blocked. This pass closes both gaps: discovery surfaces giving authenticated users a UI path to org creation, plus a four-layer friction model on the create endpoint. **No approval gating** — the in-person pilot recruitment scenario depends on no admin bottleneck.

### What shipped

**Schema migration `373e1f066cc1` (down: `e72362fd7cd5`):**
- `users.org_creation_limit` — nullable Integer (null = use platform default of 3; can be set per-user via admin endpoint)
- `platform_settings` table (key String PK / value JSON / updated_at) seeded with `{key='org_creation_mode', value='open'}`
- Idempotent (b1ab5db pattern), reversible
- Mirror seed in `database._seed_platform_defaults()` from `create_tables()` so the fresh-deploy path (post-Phase 8.6 `start.sh` ordering fix) also gets the seeded row

**Four ordered gates on `POST /api/orgs`:**

| Order | Gate | Status | Detail |
|---|---|---|---|
| 1 | Platform mode (kill switch) | 403 | "Org creation is temporarily paused — please contact support@liquiddemocracy.us" |
| 2 | Email verification | 403 | "Please verify your email before creating an organization" |
| 3 | Per-user cap (default 3, override via column) | 403 | "You have created the maximum number of organizations (N). Contact support@liquiddemocracy.us if you need more." |
| 4 | Platform-wide rate limit (20/hr via audit-log count) | **429** | "The platform is processing many organization-creation requests right now — please try again in a few minutes." |

**Audit enrichment** on `org.created`:
- `creator_email_verified_age_seconds` (from `EmailVerification.verified_at`; None for legacy accounts)
- `platform_org_creation_hour_count` (the rate-limit count at moment of creation)
- `creator_user_agent` (from request headers)
- `ip_address` (existing capture via `request.client.host`)

**Three admin endpoints** (`is_admin=True` gated):
- `GET /api/admin/platform-settings` — returns dict of all rows
- `PATCH /api/admin/platform-settings` body `{key, value}` — upsert; audited as `platform_settings.changed`
- `PATCH /api/admin/users/{user_id}/org-creation-limit` body `{limit: int|null}` — audited as `user.org_creation_limit_changed`

**Three frontend discovery surfaces:**
- **OrgSwitcher dropdown (Nav.jsx, primary)** — divider + "+ Create new organization" entry below org list; visible to all authenticated users. Browser-verified.
- **OrgSelector empty-state (OrgSelector.jsx, secondary)** — centered CTA "You're not in any organizations yet" + "Create Organization" button.
- **User dropdown (Nav.jsx, tertiary)** — "Create Organization" link above "Sign out". Browser-verified.

All three route to **`/orgs/create`** (existing route — spec said `/create-org` but the actual path is `/orgs/create`; agent kept existing flow bit-for-bit unchanged).

**CreateOrg.jsx friendly error rendering** — `classifyError` helper pattern-matches status + detail-text to one of four scenarios:
- Email-not-verified → amber banner + "Resend verification email" button reusing `EmailVerificationBanner.jsx`'s flow
- Cap-reached → banner with N parsed from detail text + `support@liquiddemocracy.us` as plain text
- Platform-paused → banner with support email
- Rate-limited → banner explaining transient state

**Backend tests: 465 → 481 passing (+16).** `test_org_creation_gates.py` (15 tests covering each gate + per-user cap override paths + audit-enrichment field presence) plus `test_phase9_5_migration_cycle.py` (1 test exercising upgrade → downgrade → upgrade on SQLite via subprocess alembic).

**PG smoke: PASS both modes** via `pg_smoke.py --mode both --prior-revision e72362fd7cd5`. Spot-checks confirm `users.org_creation_limit` column, `platform_settings` table, seeded `org_creation_mode='open'` row.

**`DEPLOYMENT.md`** gains an "Org Creation Friction Model" section: four gates, audit fields, admin endpoint usage, direct SQL fallbacks (with the `'"approval_required"'` JSON-quoting gotcha), recovery path for mass-spam scenarios (kill switch first, audit log second, surgical response third, restore open last), and deferred monitoring items for Phase 9.7.

### Production verification (browser-driven on prod)

| Gate / Surface | Result | Evidence |
|---|---|---|
| Per-user cap (default 3) | **PASS browser-verified** | alice created 3 orgs successfully (201, 201, 201); 4th attempt → **403** with exact spec message including the literal "(3)" limit value |
| Kill switch | **PASS browser-verified** | `admin` user PATCH'd `org_creation_mode='approval_required'` → voter02's create attempt blocked with exact spec "Org creation is temporarily paused…" message → restored to `'open'` (prod NOT broken for visitors) |
| Admin endpoints | **PASS browser-verified** | GET platform-settings 200 returns `{org_creation_mode: 'open'}`; PATCH lifted alice's `org_creation_limit` to 100 then back to null (200 both); PATCH platform-settings 200 both flips |
| OrgSwitcher entry visible to non-admin auth user | **PASS browser-verified** | "Create new organization" text appears after org-switcher dropdown opened as alice |
| User dropdown entry | **PASS browser-verified** | "Create Organization" text appears in user dropdown |
| Email-verification gate | PASS-by-source | `test_org_creation_gates.py::test_email_not_verified_rejection` covers; would require an unverified prod account to live-trace |
| Rate-limit gate | PASS-by-source | `test_org_creation_gates.py` covers via mocked audit count; would require 20+ creations/hr to live-trace, not feasible without polluting prod |
| OrgSelector empty-state CTA | PASS-by-source | Would require a brand-new zero-org account; existing demo personas all have demo membership |
| Demo auto-join regression (Phase 6.5) | PASS-by-source | No code touched in the demo auto-join path; the new gates apply to org creation only |

Cleanup: 3 sanity test orgs (`phase-9-5-sanity-test-*`) DELETE'd 204 each; alice owned count back to 0; alice `org_creation_limit` restored to null; platform `org_creation_mode` confirmed `open` post-test. **Prod state is clean.**

### Z's cap-lift command (POST-DEPLOY ACTION)

When Z's account hits the default cap of 3 orgs, bump his cap via either path:

**Admin endpoint (preferred):**
```
PATCH /api/admin/users/{zachs_user_id}/org-creation-limit
Authorization: Bearer <admin token>
Content-Type: application/json

{"limit": 100}
```

**Direct SQL (emergency / no admin user):**
```sql
UPDATE users SET org_creation_limit = 100 WHERE username = 'zach';
-- or, to set unlimited (no cap):
UPDATE users SET org_creation_limit = 999999 WHERE username = 'zach';
-- or, to restore default 3:
UPDATE users SET org_creation_limit = NULL WHERE username = 'zach';
```

### New tech debt

1. **No `User.email_verified_at` column.** The audit-enrichment query falls back to `EmailVerification.verified_at`; legacy accounts predating the table get `None`.
2. **`audit_log` index gap.** Rate-limit query (`action='org.created' AND timestamp > now-1h`) has no composite index. Non-issue at current scale.
3. **Fresh-deploy seed mirror in `database.create_tables()`** is a band-aid for the create_all+stamp-head asymmetry from Phase 8.6's `start.sh` ordering fix. Worth revisiting when the alembic chain gets squashed.
4. **Spec route drift** — `phase9_5_org_creation_spec.md` says `/create-org`; actual route is `/orgs/create`.

### Pass-summary

**Phase 9.5 Org Creation Gap Fix shipped clean in a single session.** 7 commits + merge. Backend tests 465 → 481 (+16). Bundle gzip +0.94 kB. No deploy incident. All 3 browser-verified gates passed with exact spec messages. Prod state cleaned up post-test. **Z's friend pilot is unblocked.**

Default platform stance: **open with friction, not approval-gated.** The four-layer friction model protects against spam without introducing user-hostile friction; the in-person pilot recruitment scenario continues to work end-to-end.

---

## Phase 9.6 — Friend Pilot Unblockers — 2026-05-02

**Single-session focused pass.** 7 commits on `phase-9-6/pilot-unblockers`, no-ff merged to master at `ed647b1`. **LIVE on prod**, bundle `index-B30BW95j.js`. Closes the four bugs Z surfaced in his friend-pilot dry run after Phase 9.5 unblocked org creation.

### What shipped

**W1 (highest priority — friend pilot fully blocked) — Invitation emails actually send.** Initial hypothesis was Resend regression after the Cloudflare DNS migration, but root cause was much simpler: `POST /api/orgs/{slug}/invitations` and `POST .../invitations/{id}/resend` in `routes/organizations.py` created `Invitation` DB rows and committed them but never called `email_service.send_invitation_email()`. Wiring was missing since Phase 4c — the function existed (the docstring still said "Stub for Phase 4c" misleadingly; the body is real), the call site didn't. Fixed via `BackgroundTasks` matching the `auth.py` registration-verification pattern.

**W2 — Sub-org membership shortcuts.** Two backend changes in `routes/sub_organizations.py`:
- **Auto-add creator**: `POST /sub-orgs` now creates a `SubOrgMembership` row for the creator with `role='admin'`, `status='active'` in the same transaction as the sub-org row. Matches the org-creation pattern.
- **Direct-add endpoint**: new `POST /api/orgs/{parent_slug}/sub-orgs/{sub_slug}/members/add` body `{user_id, role?}` (role allowlist `member`/`moderator`/`admin`; `owner` deliberately excluded). Permission: parent-org admin OR sub-org admin. Validates target is an active parent-org member (400 with "must be added to the parent org first" if not) and isn't already a member (400 "Already a member"). Audited as `sub_org_member.added_directly`. Frontend `SubOrgMembers.jsx` gains a `DirectAddSection` above the existing `InviteSection`.

**W3 — SubOrgList loading-state jitter.** Z reported the page jittered constantly with a flashing message. Root cause exactly as the spec hypothesized: `OrgContext.fetchSubOrgsFor` had `subOrgsByParent` in its `useCallback` deps. Every successful fetch updated state → callback identity changed → `SubOrgList.load`'s `useCallback([..., fetchSubOrgsFor])` recomputed → its `useEffect([load])` retriggered → infinite loop. Fix: moved cache to `useRef` so `fetchSubOrgsFor` has stable identity (`useCallback(..., [])`).

**W4 — Sustained-majority UI demoted to collapsed-by-default.** OrgSettings.jsx replaces the always-expanded section with a single "Enable sustained-majority voting" toggle + verbatim spec helper text. Toggle OFF forces `sustained_majority_enabled_default: false` and hides the five controls; toggle ON expands them with previously-saved values (or sane defaults). **SubOrgSettings.jsx left alone** — its SM section uses a per-key inherit/override surface (Phase 8.5 Decision 9) which is a distinct UX pattern. **Backend `sustained_majority.py` deliberately untouched** — the floor-activation logic edge case (zero-votes + first-no-vote triggers floor) remains as known-issue tech debt (fixed in Phase 9.8 C1).

**Backfill script (`backend/scripts/phase9_6_backfill_sub_org_creator_memberships.py`).** Idempotent one-shot script that finds sub-orgs whose creator (per `sub_org.created` audit `actor_id`) doesn't have an active SubOrgMembership and inserts `(role='admin', status='active')` rows. Defensive branches: missing audit row → warn+skip; deleted creator → warn+skip; non-active existing membership → warn+skip (does NOT silently flip — conservative posture). 3 regression tests.

**Backend tests: 481 → 491 (+10)** (+7 sub-org membership tests, +3 backfill regression tests). No PG smoke required (no schema changes).

**Bundle: 1,200.70 → 1,235.38 kB JS / 324.71 → 332.35 kB gzipped (+7.64 kB).**

### Production verification

| Check | Result | Evidence |
|---|---|---|
| W1 invitation send queued | **PASS** | `POST /api/orgs/demo/invitations` body `{emails:[support@liquiddemocracy.us], role:member}` → 201 with `[{email, status:pending}]`. `BackgroundTasks` queues `send_invitation_email` post-commit. |
| W2 auto-add creator | **PASS** | Created sanity sub-org as alice → `GET .../members` → 1 member: alice with `role='admin'`, `status='active'`. |
| W2 direct-add (parent-org admin) | **PASS** | Added carol to sanity sub-org as alice → 200 with `{role:'moderator', status:'active', username:'carol'}`. |
| Cleanup | **PASS** | DELETE sanity sub-org → 204. Prod state clean. |
| W3 SubOrgList no jitter | PASS-by-source | OrgContext `useRef` fix shipped in bundle; mechanically eliminates the dep-loop. |
| W4 sustained-majority collapsed-by-default | PASS-by-source | OrgSettings.jsx ships in bundle; expanded-on-load only when `enabled_default=true` or any SM key non-default. |

### New tech debt

1. **Org invitation email-send had no end-to-end test.** Existing tests mocked at route-response level; the `send_invitation_email` call wasn't asserted. An httpx-mocked end-to-end send test would catch a similar regression at the suite level. Logged in roadmap.
2. **Sustained-majority floor activation logic edge case.** Zero votes cast + first vote "no" → fires failure mode immediately. UI demoted in 9.6 to keep it from being a footgun; behavior fix shipped in Phase 9.8 C1.
3. **`email_service.send_invitation_email` docstring still says "(Stub for Phase 4c)"** even though the body is real and now actually called. Tiny copy fix.
4. **Platform admin (`is_admin=True`) doesn't have implicit sub-org-admin power outside org families they're a member of.** Surfaced when lead tried to add Z to Gloomhaven on his behalf. Correct security posture, but creates friction for backfill / on-behalf-of workflows.

### Pass-summary

**Phase 9.6 shipped clean in a single session.** 7 commits + merge + closeout. **Friend pilot fully unblocked**: invitation emails actually send (W1), sub-org creators auto-become members + direct-add UI for fast-path member onboarding (W2), SubOrgList admin page no longer jitters (W3), sustained-majority demoted to advanced collapsed surface (W4).

---

## Phase 9.7 — Invitation Flow End-to-End Fix — 2026-05-02

**Single-session pass.** 9 commits on `phase-9-7/invitation-flow`, no-ff merged to master at `dcc4507`. **LIVE on prod**, bundle `index-De1ws2E6.js`. Closes the connected invitation-flow gaps that surfaced after Phase 9.6 made invitation emails actually send: the email link went to a route that didn't exist (fell through to homepage), and even if a user reached the registration page, the IS_PUBLIC_DEMO=true auto-join silently routed them to demo instead of their inviting org.

### Why this exists (the pattern)

Phase 4c shipped invitation creation/storage but never built the user-facing acceptance flow. Phase 9.6 fixed the missing email send (one wiring gap). Phase 9.7 fixes the missing user journey — multiple connected gaps across registration, login, frontend routing, and auto-join behavior. This is the second time in three weeks "feature works at the API layer but the end-to-end user flow was never built" surfaced from real-world pilot signal. Both are Phase 4-era code paths that passed their original API-contract tests. **W7 logs a recommended test-depth audit mini-pass** for any future feature involving an external-touching workflow.

### What shipped

**Backend (W1, W2, W5, audit parity fix):**
- `register` + `login` accept optional `invitation_token` field. New `_consume_invitation` helper validates (pending + not expired + email match), creates inviting-org `OrgMembership` (idempotent), marks invitation accepted, audits `invitation.accepted_via_registration` / `invitation.accepted_via_login`.
- **`_auto_join_demo_org` now skips when user is in any active non-demo org** — load-bearing fix. Auto-join runs at `verify_email` time (NOT `register` — surprise surfaced during implementation), so the gate is on persistent state rather than per-request flow. Naturally covers the invitation-via-register case because the inviting-org membership exists by the time verify-email runs.
- `accept_invitation` (existing route) now emits `invitation.accepted_authenticated` audit (was missing). All 3 paths now have audit parity.
- New `routes/invitations.py::GET /api/invitations/{token}/meta` — public, returns `{org_name, org_slug, invited_email, role, expires_at}`; 404 covers all "not consumable" outcomes (no state enumeration); rate-limited 30/min/IP via slowapi.
- Backfill script `phase9_7_backfill_orphaned_invitations.py` — idempotent, 4 branches.

**Frontend (W3, W4, W6, W8):**
- New `pages/InviteAccept.jsx` at route `/invite/:token` — 4 rendering states (unauth+new-email → register, unauth+existing-email → login, auth+match → accept, auth+mismatch → clear error with verbatim spec copy) + error states. User-exists detection: try-register-fall-back-to-login (avoids token-enumeration vector). State 4 inlined custom logout returns to `/invite/:token`. Hard-navigation post-success so AuthProvider re-mounts and OrgContext picks up the new membership.
- `email_service.py` link format → `/invite/{token}`. Misleading "(Stub for Phase 4c)" docstring replaced.
- **W6 DirectAddSection root cause = UX positioning (Outcome A).** Walked Z's case: he's parent-org owner of GameNights, the `/members` endpoint returns him correctly, candidates filter works correctly. Section was rendered AFTER Pending → Active → Suspended; on multi-member sub-orgs sat below the fold. Fix: moved above Active members.
- W8 `pages/Login.jsx` — wraps demo blocks in `{showDemo && (...)}`. Small grey "Just exploring? Try the demo →" trigger. Cold `/login` renders no demo blocks; click toggle reveals inline.

**Backend tests: 491 → 509 (+18).** Load-bearing test: `test_register_with_invitation_token_skips_demo_auto_join` mocks `IS_PUBLIC_DEMO=true`, registers with token, runs verify-email, asserts demo membership is `None` and inviting-org membership is active. No PG smoke required.

**Bundle: 1,235.38 → 1,245.90 kB JS / 332.35 → 334.25 kB gzipped (+1.90 kB).**

### Production verification

`/invite/:token` route exists (was missing pre-9.7) — **PASS browser-verified**: navigated to `/invite/totally-fake-token-...`; URL stays at `/invite/...` (NOT redirected to `/`); InviteAccept renders error state "Invitation unavailable / Invitation not found, expired, or already used." with "Go to sign in" link. Pre-9.7 the same URL hit the catch-all and bounced to homepage.

End-to-end real-Gmail flow: surface for Z. Z creates a test invitation in GameNights to a fresh email he controls, clicks the new `/invite/{token}` link, registers, lands in GameNights (not demo). Tests cover the full path; live verification needs Z's inbox.

### New tech debt

1. **Test-depth audit recommended (logged in roadmap Known Issues).** Phase 9.6 + Phase 9.7 each surfaced "feature works at API layer but user journey was never built" gaps from pilot signal. Both are Phase 4-era code paths.
2. **Backfill scripts (Phase 9.6 + Phase 9.7) accumulating in `backend/scripts/`.** A future cleanup pass could move them to `scripts/historical/`.

### Pass-summary

**Phase 9.7 shipped clean in a single session.** 9 commits + merge + closeout. **Friend pilot fully unblocked end-to-end** for any new invited user: emails send (9.6) + email link goes to a real React page handling 4 auth/email-match states with clear error states (W3) + register/login consume the invitation token + auto-join no longer steals invited users into demo (W1).

---

## Phase 9.8 — Tech Hygiene Bundle — 2026-05-02

**Single-session pass.** 8 commits on `phase-9-8/tech-hygiene` no-ff merged to master at `5c1ec64` + nginx hot-fix `61f74b4` directly on master. **LIVE on prod**, bundle `index-bC8vS3BN.js`. Three independent improvement clusters bundled because each is small, design-decision-free, and parallelizable: (A) profile pictures, (B) permission alignment trio, (C) sustained-majority floor activation logic.

### What shipped

**Cluster A — Profile pictures:**
- **A1 (backend):** new `users.avatar_url` nullable column + Alembic migration `a1c4e9d2f8b3` (idempotent introspect-and-skip), new `routes/avatars.py` with `POST /api/users/me/avatar` (multipart, content-type whitelist `image/jpeg|png|webp`, max 2 MB, Pillow resize to 128×128 + 48×48 both JPEG q=85) and `DELETE` (204 + on-disk cleanup). Audited as `user.avatar_uploaded` / `user.avatar_removed`. `Pillow==10.4.0` added. `StaticFiles` mount at `/uploads/...` in `main.py`. `avatar_url: Optional[str]` exposed on **11 user-shaped Pydantic schemas**. 8 new tests.
- **A2 (frontend):** new `components/Avatar.jsx` (`sm`/`md`/`lg` = 24/48/96 px) with deterministic-color initials fallback (`hue = (hash(id) * 137) % 360; bg = hsl(hue, 65%, 55%)`), `onError` defensive fallback, helper `resolveAvatarUrl` for the root-relative `/uploads/...` paths. **Settings.jsx Profile Picture section** above Profile Information with Upload/Replace/Remove buttons. Integrated into **7 sites**: Nav (sm), VoteFlowGraph + OptionAttractorVoteFlowGraph (SVG `<pattern>` per node, fill swap on existing main circle — minimal-touch, no DOM restructure), DelegationNetworkGraph (same pattern + center-"You" text suppression when avatar present), UserProfile header (lg), Members + SubOrgMembers admin pages (sm), DelegateModal search results (sm), FollowRequests cards (sm).
- **Tricky bit:** the frontend agent's nginx config block had `location /uploads/` without `^~`, which let the regex `~* \.(jpg|...)$` cache rule match first and serve the .jpg from the SPA build directory (frontend nginx 404). Hot-fix `61f74b4` added the `^~` prefix-precedence modifier directly on master after first deploy. **Declaration order does not determine nginx location precedence — only `=`, `^~`, regex, and prefix selectivity do.** Documented in the comment for future maintainers.

**Cluster B — Permission alignment trio:**
- **B1 (Members admin moderator visibility):** root cause was NOT a frontend filter — `Members.jsx` was unconditionally calling `/api/orgs/{slug}/invitations` which returns 403 for non-admins; the error was swallowed silently and any concurrent transient `/members` failure left the page rendered with `members=[]`. Fixed by gating the `/invitations` call behind `isAdmin`, surfacing members-fetch failures via `ErrorMessage` with retry, plus `isAdmin` gating audit on Reactivate + Deny-join-request buttons (both backend `require_org_admin`).
- **B2 (unverified vote/delegate buttons):** new `components/VerifyEmailInlineNote.jsx` (small inline note next to disabled controls, calls `/api/auth/resend-verification` + `AuthContext.refreshUser()` on success, "Verification email sent." confirmation). Replaced static "Verify your email to vote/delegate." text in ProposalDetail (BinaryBallot + ApprovalBallot panels), Delegations (page-level banner), and DelegateModal. Backend 403 stays as defense-in-depth.

**Cluster C — Sustained-majority floor activation logic:**
- **C1 (backend):** closes the deferred footgun where a single early no-vote (votes_cast=1, support_fraction=0.0 < floor=0.45) immediately fired the configured failure mode, before anyone could vote yes. New pure helper `support_ever_established(snapshots, config) -> bool` returns True iff any snapshot reached `support_fraction >= config.threshold`. `is_above_floor` takes a new `support_was_established: bool` argument; when False, returns True unconditionally. `evaluate_binary` and `should_trigger_failure` updated to compute establishment from the snapshot list and pass it down. **20 net new tests** (TestSupportEverEstablished helper coverage, TestFloorActivation gate covering the seven scenarios from the spec plus a long-stretch edge case, worker-level regression for the canonical bug, and parameterized failure-modes-after-establishment). **Existing-test review:** every test that exercised the bug (~10 tests across `test_sustained_majority.py` + `test_sustained_majority_worker.py`) was updated to seed an establishing snapshot first via the new `_seed_establishing_snapshot` helper, preserving original intent without relying on the buggy behavior.
- **C2 (frontend):** OrgSettings.jsx — dropped "(advanced)" suffix from header; replaced helper text with spec-mandated copy ("Off by default. Enable when your organization makes binding decisions that benefit from durable-consensus protection — proposals must maintain support throughout the voting window, not just at close.").

**Backend tests: 517 → 537 (+20)** (from 509 baseline before A1's +8 + C1's +20-ish, net +20 because the existing-test review consolidated some). Full backend suite green pre-merge. PG smoke PASS for both `fresh` and `upgrade` modes via `pg_smoke.py --mode both --prior-revision 373e1f066cc1`.

**Bundle: 1,245.90 → 1,252.51 kB JS / 334.25 → 335.86 kB gzipped (+1.61 kB).** Well under the spec's 10–15 kB budget — Avatar component is small and the SVG `<pattern>` integration approach added almost no per-file weight.

### Production verification

| Check | Result | Evidence |
|---|---|---|
| Avatar upload end-to-end | **PASS browser-verified** | Logged in as alice, generated 200×200 PNG via canvas, POSTed to `/api/users/me/avatar` → 200 with `{avatar_url: /uploads/avatars/{uuid}/128.jpg, avatar_url_small: .../48.jpg}`. `/api/auth/me` returned the new `avatar_url`. |
| Avatar in nav after upload | **PASS browser-verified** | Page reload showed `<img src=".../48.jpg" alt="Alice Voter" width=48 height=48>` in nav. |
| Avatar in delegation graph | **PASS browser-verified** | DelegationNetworkGraph SVG registered `<pattern id="net-avatar-{uuid}">` with `<image href="/uploads/.../128.jpg">` (visual swap inside the existing center-"You" circle). |
| Avatar delete | **PASS browser-verified** | DELETE 204, `/api/auth/me.avatar_url` flipped to null, `/uploads/.../128.jpg` 404'd. Prod state clean post-test. |
| `/uploads/` proxies to backend (after nginx hot-fix) | **PASS** | `curl /uploads/avatars/{nonexistent}/128.jpg` → `404 application/json` (FastAPI shape) instead of pre-fix `404 text/html` (frontend nginx shape). |
| Moderator member list visibility | PASS-by-source | Root cause fix in `Members.jsx::load()`. Backend route already permits moderators. |
| Unverified buttons disabled + resend note | PASS-by-source | `VerifyEmailInlineNote` imported in 3 components. |
| Sustained-majority floor activation (single early no-vote does NOT fail proposal) | PASS via test suite | `test_single_no_vote_without_establishment_does_not_fail` worker-level regression test exercises the canonical bug scenario; passes. Plus 12 supporting unit tests in `TestFloorActivation`. |

### Process notes — two agent flakes worth remembering

1. **Backend agent for C1 lost their work mid-session** because their bash got sandbox-restricted and they hallucinated a "system reverted my work" framing. Lead verified the actual file state (no commits, file unchanged from pre-9.8), then dispatched a fresh C1 agent who completed the work cleanly. Lesson: when an agent reports work-loss, verify against `git log` and `git diff` before accepting their framing.
2. **Frontend agent's nginx ordering comment was wrong** — they correctly placed `location /uploads/` BEFORE the regex `location ~* \.(jpg|...)$` block, but added a comment claiming declaration order matters. It doesn't — only the `^~` modifier promotes a prefix location to win against a competing regex. The bug surfaced via `curl` only after deploy (the test suite couldn't catch it because tests don't exercise nginx), so it's a candidate for a tiny prod-smoke test that verifies `/uploads/{nonexistent}` returns FastAPI's JSON 404 rather than nginx's HTML 404.

### New tech debt

1. **Avatar storage on Railway-ephemeral filesystem** (logged in roadmap Known Issues). Files persist within a deploy but are wiped on container restart. Acceptable for friend-pilot scale (5–15 users); migrate to Railway Volume or object storage (S3/R2) before broader pilot.
2. **`sustained_majority_service.build_status` UI banner inconsistency** — the `floor_breached` flag the UI consumes for the banner is computed independently of `support_ever_established`. One-line fix using the new helper; deferred to a follow-up.
3. **No prod smoke test for nginx `/uploads/` proxy** — the missing `^~` modifier deployed cleanly because no test exercises nginx routing. A tiny `tests/smoke/` script that hits known prod URLs after deploy and asserts content-type would catch this class of issue.

---

## Phase 9.9 — Pilot Bug Fixes — 2026-05-03

**Single-session pass.** 6 commits on `phase-9-9/pilot-bug-fixes` no-ff merged to master at `449d410` + nginx body-size hot-fix `0df5ceb` directly on master + closeout. **LIVE on prod**, bundle `index-BvCSF4-u.js`. Three real bugs from Z's wife's first session in GameNights after Phase 9.7 onboarded her successfully.

### What shipped

**W1 — Backend org-scoped delegate search:** `routes/users.py` — `GET /api/users/search` and `GET /api/users` accept new optional `org_slug` query parameter. When present, results are filtered to active `OrgMembership` members of that org via join. Caller must themselves be an active member of the org_slug or get **403 "You are not a member of this organization"** (defense in depth — endpoint can't be used to enumerate other orgs' membership). Self-exclusion preserved. `topic_id` filter composes cleanly. Backward compat preserved when `org_slug` is omitted (documented as a known limitation in the docstring + roadmap). 5 new tests in new `backend/tests/test_user_search.py`.

**W2 — Backend avatar size ceiling 2 MB → 6 MB:** `routes/avatars.py` — `MAX_UPLOAD_BYTES` raised from `2 * 1024 * 1024` to `6 * 1024 * 1024`. Module + route docstrings updated. The 413 detail string derives from the constant so it auto-reads "6 MB". 1 new test (5 MB body succeeds), 1 existing oversized test updated (6.1 MB body still rejected, asserts new "6 MB" detail). Defense-in-depth ceiling — real uploads will be ~30 KB after client-side resize.

**W3 — Frontend client-side resize:** new `frontend/src/utils/imageResize.js` exports `resizeImageFile(file, maxDim=256, quality=0.85)` — canvas-based, returns a `File` (so FormData and the backend content-type whitelist are happy). `Settings.jsx::handleAvatarUploadFile` calls it before constructing FormData. Defensive try/catch falls back to original file on resize error (corrupt image, no canvas support, etc.). Existing UI state (avatarBusy/avatarMsg/toast) unchanged. **Typical phone photo (5 MB) → ~30 KB upload after resize.**

**W4 — Frontend api.postFormData() with 401-refresh-and-retry:** `frontend/src/api.js` — new `requestFormData(path, formData)` mirrors the JSON `request()` flow: builds `Authorization: Bearer ${_token}` header WITHOUT setting Content-Type (browser sets multipart boundary), POSTs FormData. **Load-bearing 401 path:** on 401 calls `refreshAccessToken()`, retries once with the new token. If retry returns 401 (or refresh failed), dispatches `auth:unauthorized` event and throws `{message: 'Session expired. Please log in again.', status: 401}`. 204 → null. JSON or text per Content-Type. Non-OK throws `{message, status, raw}` matching existing shape. New `postFormData: (path, form) => requestFormData(path, form)` on default exported `api` object. `Settings.jsx::handleAvatarUploadFile` replaces plain `fetch(...)` with `await api.postFormData('/api/users/me/avatar', form)` — error/success structure unchanged. **Closes the cascade where a 413-then-troubleshoot-then-retry sequence hit token expiry and surfaced "could not validate credentials" instead of auto-refreshing.**

**W5 — Frontend DelegateModal org-scope search:** `DelegateModal.jsx:352` — only call site of `/api/users/search` in the frontend (verified via grep). Reads `currentOrg` from `useOrg()`, appends `&org_slug=${encodeURIComponent(currentOrg.slug)}` when truthy, falls back to no param when null. `useEffect` deps include `currentOrg`. `Delegations.jsx` does not call the endpoint directly.

**W6 — Documentation:** `future_improvements_roadmap.md` Known Issues gains entry on optional `org_slug` (low-priority follow-up to make required after rechecking callers). DEPLOYMENT.md untouched (no infra change).

**Hot-fix `0df5ceb` (master directly):** `frontend/nginx.conf` `client_max_body_size` raised from default `1m` to `8m`. Caught via curl prod sanity: 5 MB and 7 MB uploads both 413'd from `nginx/1.29.8` instead of getting 200 (5 MB) or backend's 413 (7 MB). The default 1 MB nginx limit silently blocked any upload >1 MB before it could reach FastAPI's MAX_UPLOAD_BYTES check, making W2's 6 MB ceiling moot for the defensive-fallback path. Set to 8 MB (small headroom over the 6 MB backend ceiling). In-app path was unaffected because client-side resize keeps real uploads ~30 KB; this hot-fix matters for the defensive fallback case + direct API users.

**Backend tests: 537 → 543 (+6).** No PG smoke required (no schema change).
**Bundle: 335.86 → 336.17 kB gzipped (+0.31 kB).**

### Production verification

| Check | Result | Evidence |
|---|---|---|
| Org-scoped search filters to org members | **PASS** | `GET /api/users/search?q=voter&org_slug=demo` as alice (demo admin) → 200 with results filtered to demo members |
| Org-scoped search 403 on cross-org | **PASS** | `GET /api/users/search?q=voter&org_slug=gamenights` as alice (NOT a GameNights member) → **403 "You are not a member of this organization"** |
| Backward compat when org_slug omitted | PASS | `GET /api/users/search?q=voter` returns global user list (existing behavior) |
| 5 MB upload succeeds end-to-end (was 413 pre-9.9) | **PASS** | curl POST 4,997,112-byte JPEG → **200** with `{avatar_url: /uploads/avatars/{uuid}/128.jpg, avatar_url_small: .../48.jpg}`. File served + cleanup via DELETE 204. |
| 7 MB upload 413's from FastAPI (not nginx) | **PASS** | curl POST 6,992,572-byte JPEG → **413** with FastAPI body `"Avatar exceeds 6 MB pre-resize limit."`, `server: railway-edge` (NOT nginx HTML). Confirms backend ceiling enforced. |
| nginx body-size hot-fix landed | **PASS** | 1.5 MB body POST returned **401 from railway-edge** (passed through to FastAPI auth check), no longer **413 from nginx/1.29.8**. |
| `postFormData` deployed in bundle | PASS | `curl /assets/index-BvCSF4-u.js | grep postFormData` → 2 occurrences (function definition + call site). |
| Token-expiry refresh-and-retry on upload | PASS-by-source | `api.js` diff committed in `abef82f` mirrors the existing JSON `request()` 401-refresh-retry. Bundle deployed. |
| In-app phone-photo upload via resize | PASS-by-source | `Settings.jsx::handleAvatarUploadFile` calls `resizeImageFile` before FormData construction; the 5 MB direct upload above proves the backend path works for the post-resize blob. |

### Process note — caught a real prod bug via curl-only sanity

The dispatch's "browser-verify on prod" plan would have caught the org-scoped search and the in-app phone-photo upload (which goes through client-side resize → ~30 KB body, well under the 1 MB nginx default), but **not** the defensive-fallback path where resize fails. The 1 MB nginx limit was invisible to in-app testing because real uploads after resize are ~30 KB. Direct `curl` of a 5 MB JPEG against `/api/users/me/avatar` exposed the issue immediately and the hot-fix landed within the same session. **Lesson:** future passes that change backend size/ceiling/limit constants should also smoke-test the proxy/edge layer with a body just above the previous limit, not just the in-app surface.

### New tech debt

1. **`/api/users/search` `org_slug` is optional** — backward-compat preserved for legacy/admin callers. Roadmap entry added; low-priority follow-up to require it once all callers are confirmed updated.
2. **`test_upload_5mb_file_succeeds` fragility cliff** (per backend agent's note) — uses random-noise canvas + JPEG COM-marker padding to deterministically land in the >2 MB / <6 MB window. If Pillow's JPEG encoder behavior changes, the noise canvas might overshoot.
3. **No prod smoke test for nginx body-size** — same shape as Phase 9.8's missing nginx-routing smoke. A tiny `tests/smoke/` script that POSTs a small body just above the previous limit and asserts FastAPI 401 (not nginx 413) would catch this class of issue. Candidate for the test-depth audit mini-pass already logged in the roadmap.

### Pass-summary

**Phase 9.9 shipped clean in a single session** — 6 commits on the branch + 1 hot-fix + closeout. **Friend pilot fully unblocked**: cross-org search no longer leaks demo users into GameNights delegate browsing, phone photos upload near-instantly via client resize (~30 KB upload from a 5 MB original), and token-expiry no longer cascades to "could not validate credentials" because the upload now flows through the api wrapper's 401 refresh-and-retry path. Tests 537 → 543 (+6). Bundle gzip +0.31 kB. One nginx default body-size limit caught via curl + hot-fixed same session.

---

## Phase 10 — Engagement Layer — 2026-05-03

**Single-session pass.** 6 commits on `phase-10/engagement-layer` no-ff merged to master at `563b5d1` + closeout. **LIVE on prod**, bundle `index-D8JU9FzM.js`. Two of the original three Phase-10 items (proposal comments + PWA configuration); the third (profile pictures) shipped earlier in Phase 9.8 and was dropped from this pass.

### What shipped

**W1 — Backend comments + audit + 17 tests:**
- New `Comment` model (proposal_id FK CASCADE, author_id FK CASCADE, parent_comment_id self-FK CASCADE nullable, body Text, created_at, updated_at, deleted_at). Migration `b2d5f1a3c7e4_phase_10_comments.py` (prior `a1c4e9d2f8b3`, idempotent introspect-and-skip, reversible). Cycle test `test_phase_10_migration_cycle` passes upgrade → downgrade → upgrade on SQLite.
- New `routes/comments.py`: `GET/POST /api/proposals/{id}/comments` + `PATCH/DELETE /api/comments/{id}`. Edit window 15 min server-side enforced via `(now - created_at)` check, **403 with "Edit window has expired"** otherwise. Soft-delete sets `deleted_at` + blanks body in DB and response; `body_deleted: true` flag on the wire so frontend can render `[deleted]` consistently without inspecting body content. One-level threading enforced at route layer (parent must exist + same proposal + itself top-level → 400 otherwise). `_sanitize_markdown` (nh3) at write time + post-trim length re-check rejects empty-after-sanitize payloads.
- New `_eligible_viewers_for_proposal` helper inlined in `routes/comments.py` mirroring `polis_engine.eligible_viewers_for_polis` for the Proposal artifact. Org-wide proposals visible to all active parent-org members; sub-org-scoped proposals add SubOrgMembership + parent-org admin implicit power (Decision 6) + Decision-7 default-visible-with-private-opt-out. Same gate for GET (read) and POST (write). Tech debt: should consolidate into a shared `scope.py` once a third caller arrives.
- Audit events: `comment.created` / `comment.edited` / `comment.deleted` with `{comment_id, proposal_id, parent_comment_id?, body_length}` shape. **Body content NEVER in `details`** — verified via `repr(details)` substring check in `test_audit_events_emitted_on_lifecycle`.
- 17 new tests in `test_comments.py` covering full lifecycle (create top-level, create reply, reject reply-to-reply 400, reject cross-proposal reply 400, list chronological with replies grouped, edit within window, edit after window 403, edit by non-author 403, soft-delete blanks body, soft-delete preserves replies), permissions (post requires email_verified, post requires org membership, sub-org eligibility, GET respects proposal visibility), **load-bearing XSS sanitization** (`test_xss_payload_sanitized_via_nh3` — POST `<script>alert(1)</script>some text`, assert NEITHER `<script>` NOR `alert(1)` substring appears in create response, GET response, OR DB row; legitimate "some text" preserved), and audit shape (lifecycle events fire, body content not in details).

**W2 — Frontend renderMarkdown extracted to shared utility:**
- `frontend/src/utils/renderMarkdown.js` — pure refactor of the existing inline regex renderer from `ProposalDetail.jsx`. JSDoc explains the escape-then-substitute strategy and the deliberate dependency-free choice (no react-markdown / marked). Supported syntax preserved byte-for-byte: h1, h2, h3, bold, italic, inline code, bullet list. Both consumers (ProposalDetail body + Comment body) use the same renderer.

**W3 — Frontend comment thread UI:**
- 3 new components: `CommentThread.jsx` (collapsible container, fetches on first expand, re-shapes chronological array into top-level + replies-immediately-below indented), `Comment.jsx` (Avatar sm + UserLink + relative timestamp + `(edited)` indicator + renderMarkdown body via shared util + author-only edit/delete affordances + 15-min client-side edit window check + soft-deleted "[deleted]" italic-gray treatment), `CommentComposer.jsx` (textarea + char counter X/5000 + Post button + Cmd/Ctrl+Enter submit + reply Cancel button + `VerifyEmailInlineNote` for unverified users with `action="comment"` + error toast preserves textarea content).
- Mounted in `ProposalDetail.jsx:1283` below the lg:grid 2-column block (gets full content width below LinkedDeliberations + VotePanel). Re-fetches on post/edit/delete. Reply affordance visible only on top-level comments. Replies indented via `border-l-2 border-gray-200 pl-4`. `useConfirm` before delete.

**W4 — PWA configuration:**
- `vite-plugin-pwa@1.2.0` added with `overrides` block (`"vite": "$vite"`) to relax its vite peer constraint (`^7.0.0` declared, we run `^8.0.4`). Avoids needing `--legacy-peer-deps` for future devs. Tech debt: revisit when vite-plugin-pwa officially declares vite-8 support.
- `vite.config.js` registers VitePWA with `registerType: 'autoUpdate'` + `injectRegister: 'auto'` + Workbox `globPatterns` for app-shell precaching + `navigateFallbackDenylist: [/^\/api/, /^\/uploads/]` (live data always goes to network, never cached by SW).
- Manifest: theme `#1B3A5C` (verified Tailwind brand navy from `Nav.jsx` — explicitly NOT the spec's `#4f46e5` placeholder), `display: 'standalone'`, `start_url: '/'`, `lang: 'en'`, `scope: '/'`, three icons (192, 512, maskable-512).
- 3 placeholder icons: "LD" white sans-serif on `#1B3A5C`, generated via `frontend/scripts/generate_pwa_icons.py` (Pillow). Maskable variant has ~10% padding so the inner mark fits inside any browser-applied circle/squircle/rounded-square mask. 1937 + 5347 + 4682 bytes.
- `frontend/public/offline.html` (1101 bytes) — minimal static page with brand color, retry button. Precached + served via Workbox `setCatchHandler` when navigation requests fail entirely.
- Offline-fallback strategy: runtimeCaching `NetworkFirst` (5s timeout) for navigation requests + `NavigationRoute` allowlist excluding `/api` and `/uploads`. Precached `offline.html` served via catch handler on full failure.

**W5 — Documentation:**
- `future_improvements_roadmap.md`: Phase 10 marked complete in sequence index + body collapsed (notification + WebSocket deferrals preserved).
- `DEPLOYMENT.md`: new "Service worker and PWA (Phase 10)" section covering shipped artifacts, cache rules, Cloudflare/Railway notes, curl-level verification recipes, icon-regeneration command.
- PROGRESS.md: this entry. **Coordination check held**: planning agent did NOT write to PROGRESS.md during the pass (per the spec's "Concurrent planning-agent work" warning); the file was unchanged from session-start until this closeout edit.

**Backend tests: 543 → 560 (+17).** Full suite green pre-merge. **PG smoke PASS both modes** (prior `a1c4e9d2f8b3`).
**Bundle: 336.17 → 338.21 kB gzipped (+2.04 kB)**, well under the 7-11 kB spec target. The W4 SW + Workbox library files (`sw.js` 2.2 KB + `workbox-*.js` 16 KB + `registerSW.js` 134 B) are separate files, not in the main bundle.

### Production verification

| Check | Result | Evidence |
|---|---|---|
| Comments API auth gate | **PASS** | GET + POST `/api/proposals/{id}/comments` without auth → 401 |
| POST top-level comment as alice | **PASS** | 201 on Engineering Team — Adopt Trunk-Based Development proposal |
| POST reply as voter02 | **PASS** | 201 with `parent_comment_id` set to top_id |
| POST reply-to-reply rejected | **PASS** | 400 `"Replies cannot themselves be replied to (only one level of threading is supported)."` |
| **XSS sanitization (LOAD-BEARING)** | **PASS** | POST body `<script>alert(1)</script>Legitimate text after script tag.` → returned body is `"Legitimate text after script tag."` (script tag stripped, alert(1) stripped, legitimate text preserved). Confirmed on POST response, GET list response, and inferred via DB consistency (sanitization at write time). |
| PATCH within window | **PASS** | 200 with body updated to "Edited within 15-min window." |
| Soft-delete preserves replies | **PASS** | DELETE → 204; GET shows top.deleted_at set + top.body blank + top.body_deleted=true; **reply still visible with intact body** |
| Edit-after-window 403 | PASS-by-source | `test_edit_after_window_expired_403` covers via DB clock manipulation; not exercised live (would require waiting 15 min or DB time-travel) |
| Non-org-member GET 403 | PASS-by-source | `test_get_respects_proposal_visibility` covers; alice can GET demo proposals because she IS a demo member (correct), so a curl-level negative test would need a fresh non-member account |
| `manifest.webmanifest` served | **PASS** | 200, 462 bytes, theme_color `#1B3A5C` confirmed in body, all 3 icons referenced |
| `sw.js` served | **PASS** | 200, 2203 bytes, application/javascript, references `offline.html` 2x (precache + setCatchHandler) |
| `registerSW.js` auto-injected | **PASS** | 200, 134 bytes |
| 3 icons served at correct sizes | **PASS** | 192.png 1937B / 512.png 5347B / maskable-512.png 4682B |
| `offline.html` served | **PASS** | 200, 1101 bytes, text/html — page renders standalone with brand color + retry button |
| PWA install affordance + offline render on real mobile | PASS-by-source | Workbox + manifest are settled paths per spec; manifest has all required fields. Real-device install + offline-render verification deferred to first user signal — spec explicitly allows this for the install affordance. |

### Phase 10 commit list

- `8fea3fa` W2 extract renderMarkdown to shared utility
- `e29e6ad` W1 Comment model + migration + cycle test
- `5e9a138` W1 Comment CRUD routes + schemas + main wiring
- `1742a5c` W4 PWA configuration — manifest + service worker + offline page
- `f6d282c` W3 comment thread UI
- `1a0c79d` W1 Comment route tests + Phase 9.8 cycle test pin
- `68c5255` W5 docs — roadmap mark complete + DEPLOYMENT service-worker section
- `563b5d1` Merge to master
- `f105b56` Closeout commit

### Process notes

1. **Multi-agent staging race-condition surfaced twice in this pass.** Backend agent's commit briefly absorbed frontend dev A's staged Comment*.jsx files; backend agent reset+re-committed with the correct backend-only fileset, frontend dev A re-staged and committed cleanly. Both agents independently noted the issue and ended in correct state. The implicit assumption that "staged-but-uncommitted state is owned by the agent that staged it" doesn't hold under concurrent `git add` + `git commit` calls in the same working tree. The parallel-dispatch model probably wants explicit per-agent index isolation (worktrees) at some point — flagging as a multi-agent infrastructure improvement worth considering.
2. **`vite-plugin-pwa@1.2.0` declares vite peer `^7.0.0`** but we're on `^8.0.4`. Used npm `overrides` (`"vite": "$vite"`) to relax the constraint — avoids `--legacy-peer-deps` (which had a side-effect of pruning `react-is` and breaking the build via `recharts`). Worth tracking when vite-plugin-pwa officially declares vite-8 support so the override can be removed.
3. **Brand color resolved correctly.** Spec flagged the `#4f46e5` placeholder in the example manifest as needing lookup. Lead grepped `Nav.jsx` and confirmed `#1B3A5C` (also used as Phase 7C winner highlight). All Phase 10 brand-color usages (manifest, icons, offline.html) use the verified value.

### New tech debt

1. **Comment-viewer eligibility helper inlined in `routes/comments.py`** — should consolidate into a shared `scope.py` (alongside `eligible_viewers_for_polis` and `eligible_voter_ids_for_proposal`) once a third caller arrives. Backend agent flagged.
2. **`vite-plugin-pwa` peer-version override** — see process note 2; remove the `overrides` block when vite-plugin-pwa supports vite 8 natively.
3. **`manifest.webmanifest` served as `application/octet-stream`** — nginx default in alpine doesn't include the `.webmanifest` MIME type. Browsers tolerate via content-sniffing (PWA install works), but `application/manifest+json` is the proper type. Low-priority polish; one-line nginx config change to add the MIME mapping. Caught via `curl -I`.
4. **Three `timeAgo` duplicates across components** (Comment.jsx + FollowRequests.jsx + DelegateModal.jsx). Frontend dev A flagged. Below the threshold to lift into `utils/timeAgo.js` in this pass; clean up in a future hygiene pass.
5. **Placeholder PWA icons only** — per design decision 13. Future pass will add a real platform brand mark + per-org logo upload (parallel to user avatar work from Phase 9.8). Don't block on logo design.

### Pass-summary

**Phase 10 shipped clean in a single session** — 6 commits on the branch + closeout, no hot-fixes needed. Comments work end-to-end on prod (post + reply + edit + soft-delete + XSS-stripped + reply-survives-parent-delete all verified via curl). PWA artifacts present + serving correctly. Tests 543 → 560 (+17). Bundle gzip +2.04 kB. PG smoke PASS both modes. Two coordination flakes (multi-agent staging race) self-recovered without lead intervention; flagged as infrastructure improvement candidate.

The friend pilot now has a place to discuss proposals beyond the static body text, and the platform installs as a home-screen app on iOS Safari + Android Chrome via the manifest + SW.

---

## Phase 10.1 — Tactical Polish + Cross-Scope Vote Leak Fix — 2026-05-03

**Single-session pass.** 7 commits on `phase-10-1/polish-and-scope-fix` no-ff merged to master at `8387991` + closeout. **LIVE on prod**, bundle `index-DyaIsLQN.js`. Five workstreams: one load-bearing correctness fix (W1) + four UX polish items surfaced from Phase 10 first-use signal. **NO migration, smoke not required** (W1 is logic-layer only).

### What shipped

**W1 — Backend cross-scope vote leak fix (LOAD-BEARING):** Real bug from Z's friend pilot: his wife is a parent-org member of GameNights but NOT a member of a sub-org within it; she delegates to Z; Z votes on a sub-org-scoped proposal he's eligible for; **her ballot was being counted in the tally** because the delegation chain resolved through her even though she has no eligibility. The bug surface was broader than just sub-org — `compute_tally`'s `else` branch and `get_vote_graph`'s `all_users` query also leaked across orgs entirely. Fixed all three surfaces in one pass:
- `routes/votes.py::cast_vote` + `retract_vote` — new eligibility gate via `eligible_voter_ids_for_proposal` returns 403 `"You are not eligible to vote on this proposal."` when caller isn't in the eligible set. Diagnostic comment block references the bug history for future maintainers.
- `delegation_engine.py::compute_tally` — the `if sub_org_id ... else iterate all users` block collapsed into a single `eligible_voter_ids_for_proposal` call covering all three scope cases (sub-org / org-wide / no-org). `sorted(eligible_ids)` preserves RCV/STV insertion-order determinism without the cross-org leak.
- `routes/proposals.py::get_vote_graph` — `all_users` now filtered by `eligible_ids`; `total_eligible=len(eligible_ids)` for explicit intent.
- `delegation_engine.py::DelegationService._build_context` — new optional `eligible_ids` parameter filters the direct-vote query, closing the leak through delegation chain resolution where a non-eligible user's pre-fix vote could otherwise surface as the chain's `direct_ballot`. When non-eligible delegate's vote is filtered out, the existing `chain_behavior` logic (`accept_sub` / `revert_direct` / `abstain`) fires correctly. `eligible_ids=None` keeps backward-compat for legacy callers.
- 8 new tests in `backend/tests/test_vote_eligibility_scope.py` covering: cast_vote (sub-org non-member 403, cross-org non-member 403, sub-org member 200, parent-org member 200), tally (excludes non-member direct vote, **excludes non-member delegated chain — Z's-wife scenario**, cross-org excludes), and vote-graph (`total_eligible` matches eligible set not all-users).
- 11 existing tests updated to stop relying on the cross-org leak (5 RCV voter-cast tests + 5 sustained-majority worker tests + helper). Each had created votes on org-scoped proposals without joining the voter as `OrgMembership`; pre-fix tally counted them anyway via the all-users `else` branch. Fixed by adding membership in fixtures (Phase 9.8 C1 existing-test review pattern). All updates are scope-correct: the tests describe what was always supposed to happen — eligible voters cast and are tallied. None changed an assertion.

**W2 — Comment thread discoverability:** `CommentThread.jsx` — `expanded` state initialized to `null` sentinel; eager fetch on mount (no longer gated on first expand); auto-expand when count > 0 via second useEffect with `expanded === null` guard so user toggles still win. Header treatment dropped `uppercase tracking-wide` (less section-divider, more "click me"); new `bg-gray-50 hover:bg-gray-100`, `text-gray-800 font-semibold`, `text-gray-500` chevron. Label number-first + plural-correct: `Comments` / `1 Comment` / `N Comments`.

**W3 — PWA install banner:** new `InstallPWABanner.jsx` mounted in `App.jsx`. Three render-skip conditions: `localStorage.pwa_install_dismissed === '1'`, `window.matchMedia('(display-mode: standalone)').matches`, `window.innerWidth >= 768` (mobile-only Tailwind `md:` breakpoint). Captures `beforeinstallprompt` for Android Chrome path; `installEvent.prompt()` + `userChoice` handling, dismisses regardless of accept/reject. iOS Safari path opens inline help popover with literal text "Tap the Share icon ⬆️ at the bottom of Safari, then choose Add to Home Screen." Dismiss × persists `localStorage.pwa_install_dismissed = '1'` forever (try/catch wrap for Safari private-mode safety). Uses `#1B3A5C` brand color.

**W4 — Stale-bundle controllerchange listener + toast:** `main.jsx` listens for `navigator.serviceWorker` `controllerchange`; first activation skipped via `initialController === null` sentinel; subsequent activations dispatch `app:bundle-updated` CustomEvent. New `BundleUpdateNotifier.jsx` mounted in `App.jsx` listens for the event and shows toast `"A new version is available."` with Refresh action that calls `window.location.reload()`, 30s auto-dismiss. **`Toast.jsx` extended** with new `toast.custom({ message, type, action, duration })` method (backward compatible — none of 22 existing call sites changed); action button renders inline with `bg-white/20 hover:bg-white/30` + white text; clicking invokes `onClick` then removes toast; background-click dismiss suppressed when action present (avoids race).

**W5 — Offline copy honesty:** `offline.html` `"You're offline. Reconnect to use the platform."` → `"We can't reach the server right now. Check your connection and try again."` (acknowledges user can't always tell whether they're offline or the server is down). `api.js` 5 occurrences of `"Network error — is the server running?"` (developer voice) → `"Couldn't reach the server. Check your connection and try again."` (user voice). `ErrorMessage.jsx` `"Unable to connect..."` → spec's user-voice copy verbatim + `includes()` check matches new api.js shape so the fallback message handler still triggers correctly.

**Backend tests: 560 → 568 (+8).** Full suite green pre-merge. **No migration, smoke not required.**
**Bundle: 338.21 → 339.23 kB gzipped (+1.02 kB)** — well under the 2-3 kB target.

### Production verification

| Check | Result | Evidence |
|---|---|---|
| **W1 alice (parent-org member, NOT Eng Team) POST vote on Eng Team sub-org proposal** | **PASS** | `HTTP 403` body `{"detail":"You are not eligible to vote on this proposal."}` — exactly what was silently accepted pre-fix |
| **W1 dave (Eng Team admin) POST vote on Eng Team sub-org proposal** | **PASS** | `HTTP 200` with vote shape; cleanup DELETE 204 |
| **W1 vote-graph `total_eligible` is scoped, not all-users** | **PASS** | Eng Team sub-org proposal: `total_eligible=4` (dave admin + carol/voter01/voter02 members), platform user count is much higher |
| **W1 results endpoint matches scoped tally** | **PASS** | `total_eligible=4, votes_cast=3` — same scoped value |
| W1 cross-org non-member 403 | PASS-by-source | `test_cast_vote_cross_org_non_member_403` covers; can't easily simulate from demo personas (all are demo-org members) |
| W1 Z's wife specific case | PASS-by-source | `test_tally_excludes_non_member_delegated_chain` is the same shape; alice vs Eng Team verified above is the same architecture |
| W2 default-open + new header CSS in deployed bundle | **PASS** | `bg-gray-50 hover:bg-gray-100` string present 1× in `index-DyaIsLQN.js` |
| W3 PWA banner localStorage key in deployed bundle | **PASS** | `pwa_install_dismissed` string present 1× in deployed bundle |
| W3 install banner on real iOS + Android | PASS-by-source | All 3 render-skip conditions wired + both Install paths (Android `prompt()`, iOS popover) implemented; spec explicitly allows PASS-by-source if device access prevented |
| W4 controllerchange CustomEvent in deployed bundle | **PASS** | `app:bundle-updated` string present 3× (dispatch + listen + ref) |
| W4 stale-bundle toast on real second deploy | PASS-by-source | Per spec; next deploy after this one will be the first real test |
| W5 user-voice copy in deployed bundle | **PASS** | `Couldn't reach the server` string present 4× (terser collapses identical literals from 6 source sites) |

### Phase 10.1 commit list

- `1f75b06` W5 offline copy honesty (lead, before agents finished)
- `a7b8047` W3 PWA install banner
- `0fdc023` W2 comment thread default-open + prominent header
- `0a8d15c` W4 stale-bundle controllerchange + update toast
- `97cd8da` W1 eligibility gate on cast_vote/retract_vote
- `682616f` W1 scope-aware tally + vote-graph + _build_context filter
- `976e49e` W1 tests for cross-scope vote leak fix
- `8387991` Merge to master
- closeout commit follows

### Process notes

1. **Multi-agent staging race avoided this pass** via explicit per-agent file-ownership boundaries in dispatch prompts and a "stage and commit ONLY your files; if you see other files in `git status`, do NOT `git add` them" warning. End state: all 7 commits clean, no rewrites needed. Improvement over Phases 9.8/9.9/10 where the race surfaced and self-recovered post-hoc. Worktree-based isolation remains a candidate longer-term improvement, but explicit prompt discipline closed the gap for this pass.
2. **Existing-test review pattern (Phase 9.8 C1) reused effectively.** 11 existing tests across 2 files needed scope-aware fixture updates because they were silently relying on the cross-org leak to populate tallies. Backend agent documented each kept/updated decision with rationale. None changed assertions; all updates added the missing `OrgMembership` rows that the tests should have had all along.
3. **Coordination check held**: planning agent did NOT write to PROGRESS.md during the pass. The post-Phase-10 restructure landed cleanly between Phase 10 closeout and Phase 10.1 dispatch (PROGRESS.md is now 640 lines down from ~2700); Phase 10.1 closeout appends to the new shape per spec's "the agent will adapt to whatever shape PROGRESS.md is in at that moment."

### New tech debt

1. **One-shot diagnostic script for pre-fix non-eligible votes** — out of scope per spec but worth filing. A small script that queries `Vote` rows where `user_id NOT IN eligible_voter_ids_for_proposal(proposal_id)` would let Z see what (if anything) was cast pre-fix that no longer counts. Logged here for retrospective review when convenient.
2. **`Toast.custom` background-click dismiss suppression** — intentional behavior delta when `action` is present (avoids race between background dismiss and action click). Not user-visible for current usage; flag if it surprises.

### Pass-summary

**Phase 10.1 shipped clean in a single session** — 7 commits + closeout, no hot-fixes. Cross-scope vote leak closed at all three surfaces (cast endpoint + tally + vote-graph + delegation-chain resolver) with 8 new targeted tests + 11 existing-test updates documenting that the prior tests were relying on the bug. Friend pilot is now correctness-correct: a non-eligible voter cannot cast, an existing non-eligible vote cannot leak through delegation chain resolution, and `total_eligible` matches the actual eligible set on every proposal. Polish items (W2 comment discoverability, W3 PWA install banner, W4 stale-bundle toast, W5 offline copy honesty) ship alongside. Tests 560 → 568 (+8). Bundle gzip +1.02 kB. No migration. No deploy incident. Multi-agent staging discipline held cleanly for the first pass since the issue surfaced in 9.8.
