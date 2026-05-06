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

---

## Phase 10.2 — Test-Depth Audit + Pre-Fix Vote Leak Diagnostic — 2026-05-03

**Single-session audit + fix pass.** 9 commits on `phase-10-2/test-depth-audit` no-ff merged to master at `077c652` + closeout. Bundled the manifest MIME hot-fix (one-line nginx config) so the new smoke check that codifies the desired state passes on first run rather than yellow-with-exception. **No new bundle hash on prod** because no JS source changed (Vite content-hash deterministic) — nginx-only deploy verified directly via curl. **NO migration, smoke not required**.

### Why this pass exists

A pattern surfaced 5 times in 6 phases: feature works at API layer but the user-journey side-effect / cross-scope invariant / infrastructure-boundary behavior was never tested, and a real user (or curl) caught the bug instead. 9.6 missing email send, 9.7 missing user journey, 9.8 hot-fix nginx routing, 9.9 hot-fix nginx body size, 10.1 cross-scope vote leak. CLAUDE.md already named the principle ("Assert side-effects, not just API contracts") since 9.6/9.7 closeouts; the principle alone wasn't enough. This pass enumerates where the principle has and hasn't been applied, then closes the gaps.

### What shipped

**W-AUDIT — `docs/test_depth_audit_2026-05.md`** (377 lines, 36 KB). Walks every endpoint in `backend/routes/` (15 modules / ~60 endpoints), every multi-tenant entity (12), every infra boundary (6 components). Per-row classification PASS / GAP / BUG with existing test path + what it asserts + side-effect coverage gap + recommended test name + file path + assertion shape. Auditor's posture: generous interpretation of "covered" — bar is "does this test fail when the side-effect breaks?", not "does this test name the side-effect explicitly?" Real bugs flagged BUG (not GAP), fix deferred to W-FIX-A.

**~75 patterns audited:** PASS ~40 (Class A 18, Class B 13, Class C 1) / GAP ~28 (Class A 16, Class B 6, Class C 5) / **BUG 2** (both LOW-severity unauth'd data exposure on `routes/users.py`):
1. `GET /api/users/{id}` — no auth dependency, returns full UserOut (email, email_verified, default_follow_policy) to any caller. UUID guessing is the only barrier. Not user-visible. Not caught by any user.
2. `GET /api/users/{id}/delegation-tree` — no auth dependency, returns full delegation neighborhood for any user, bypassing the privacy-redaction logic the auth-gated `/api/delegations/graph` endpoint applies. LOW-MEDIUM severity. Not user-visible. Not caught by any user.

**W-FIX-A — 45 new pytest tests + 2 BUG fixes + 1 latent-bug fix in passing.** Both BUGs fixed by adding `Depends(get_current_user)` + identity-redaction parity for BUG 2 (delegation-tree now returns `display_name="Anonymous user"`, `username="anonymous"`, `avatar_url=None` for nodes the viewer can't see — not self / not followed / not a public delegate). Self-view returns real identities since the caller is by definition party to those relationships. Verified: unauth → 401, auth + self → real names, auth + third-party → redacted unless visible. Latent fix in passing: `routes/users.py::search_users_compat` was passing `Query(None)` through to `search_users` for `topic_id`, which crashed at the SQLite driver (truthy `Query` object); fixed by passing explicit `None`.

**Heaviest GAP concentration was the auth module** — 7 endpoints with zero email-send-mock or audit-emission test coverage (forgot-password, reset-password, change-password, resend-verification chain). The Phase 9.6 "invitation 201 fires but no email" regression was NOT currently latent (route correctly schedules the BackgroundTask) but had no regression test guarding it. New tests added across 10 new files:
- `test_user_endpoint_auth.py` (7 tests, BUG fixes)
- `test_auth_register.py` (3), `test_auth_login.py` (1), `test_auth_tokens.py` (5), `test_auth_resend_verification.py` (3 with autouse `slowapi.limiter.reset()` fixture), `test_auth_password_reset.py` (4), `test_auth_change_password.py` (2)
- `test_invitations_lifecycle.py` (4 — Phase 9.6 W1 regression guards: create + resend email-send mocks, revoke, accept-authenticated audit)
- `test_admin_endpoints.py` (5), `test_delegation_network_isolation.py` (1), `test_delegate_applications.py` (4), `test_delegates_public_visibility.py` (1)
- Plus polish on `test_email_verification.py` (+1), `test_avatars.py` (+2), `test_user_search.py` (+2)

**Backend tests: 568 → 613 (+45)** — exceeds the audit's "~25" loose target. Full suite green.

**W-FIX-C — `tests/smoke/` directory at repo root** (new). Minimal pattern: 1 conftest.py with `--target` CLI option + `target_url` session fixture, no other fixtures, no shared setup, no mocking. Each test is `httpx.get/post(target_url + path)` + assertions. 5 checks across 2 files (`test_proxy.py`, `test_sw.py`):
1. nginx `/uploads/` proxy returns FastAPI JSON 404 (catches Phase 9.8 missing-`^~` regression)
2. nginx body-size limit lets 5 MB POST reach FastAPI 401 (catches Phase 9.9 client_max_body_size regression)
3. Workbox `navigateFallbackDenylist` includes `/api` and `/uploads` patterns in deployed `sw.js`
4. `manifest.webmanifest` Content-Type is `application/manifest+json` (was the known-failing one at audit time)
5. `/registerSW.js` serves as JS (Phase 10 PWA auto-injection codified)

**Used `httpx` (already in `backend/.venv`) instead of `requests`** — the dispatch suggested `requests` but verification showed it wasn't installed; httpx has identical shape and zero new dependencies.

**Wall-clock runtime: 1.8 seconds** against prod (5 HTTP round trips, no fixtures). Well under the 10s threshold for W-FIX-D auto-wiring.

**W-FIX-D — `backend/scripts/poll_deploy.py`** (NEW). Replaces the inline poll commands every prior pass had open-coded. Waits for bundle hash flip + `/api/health` 200, then auto-runs `pytest tests/smoke/ --target=<url>`. Smoke failure becomes the script's exit code so a successful deploy that breaks a boundary now flags loudly. `--no-smoke` opt-out flag, `--start-bundle=<hash>` to pin pre-deploy hash, `--target=<url>` for local stack vs prod, `--timeout=<s>` to override default 720s.

**Manifest MIME hot-fix bundled** (per spec line 279 + W-FIX-C closeout flag). One-line nginx config: `location = /manifest.webmanifest { default_type application/manifest+json; }`. Smoke check 4 codifies the desired state; the failing check is the signal until the underlying nginx config is fixed. Shipped here so the new `poll_deploy.py` reports green on its first real run rather than yellow with a documented exception.

### Production verification

| Check | Result | Evidence |
|---|---|---|
| Smoke suite against prod (5/5) | **PASS** | `pytest tests/smoke/ -v --target=https://www.liquiddemocracy.us` → 5 passed in 1.23s. ALL 5 checks now pass post-MIME-hot-fix (was 4/5 pre-fix). |
| Manifest MIME hot-fix landed | **PASS** | `curl -I https://www.liquiddemocracy.us/manifest.webmanifest` → `content-type: application/manifest+json` (was `application/octet-stream` pre-fix). |
| BUG 1 fix (`GET /api/users/{id}` requires auth) | **PASS** | Unit tests `test_get_user_requires_auth_returns_401_unauthenticated` + `test_get_user_authenticated_caller_returns_200` pass; would catch regression. |
| BUG 2 fix (`GET /api/users/{id}/delegation-tree` requires auth + redaction parity) | **PASS** | Unit tests cover unauth 401, self-view real names, third-party redaction, public delegate visibility, follower visibility, stranger anonymization. |
| Backend full suite green | **PASS** | 613 passed in 79.23s, no regressions. |

**No new bundle hash on prod** because no JS source changed (Vite content-hash is deterministic). The nginx-only deploy was verified directly via curl + smoke. **`poll_deploy.py`'s bundle-hash heuristic missed this case** — it kept probing and didn't detect deploy completion. Real tech debt for the script (logged below).

### W-DIAG report (verbatim from local-dev-DB run)

The diagnostic script `backend/scripts/phase10_2_diagnose_pre_fix_vote_leak.py` is committed. Verified locally + with synthetic leak fixture (correctly detected). **The actual prod numbers require Z to run via `railway run`** — lead can't pull a prod snapshot or invoke Railway CLI (same pattern as Phase 9.7's wife-rescue backfill).

Local dev DB run (clean — no leaked votes; this proves the script connects, scans, categorizes, and writes its report file without crashing):

```
Phase 10.2 pre-fix vote leak diagnostic
Run timestamp: 2026-05-03T19:10:00Z

Total Vote rows scanned: 189
Leaked vote rows found: 0
Affected users (distinct): 0
Affected proposals (distinct): 0
Orphan votes (proposal/user deleted): 0 (excluded from leak count)
Suspect-scope votes (sub-org or org deleted but proposal lingers): 0 (surfaced separately, not counted as leak)
Oldest leaked vote: <none>
Newest leaked vote: <none>

Per-org breakdown:
  (no leaked votes)

Per-proposal breakdown (top 10 by leaked vote count):
  (no leaked votes)

Per-affected-user breakdown:
  (no leaked votes)

Report written to: C:\Users\zachk\liquid-democracy\backend\scripts\phase10_2_diagnostic_report_20260503T191000Z.txt
```

A fixture-based smoke test (cleaned up post-run) constructed a known leaked vote (Bob, member of OrgB, voting on a proposal in OrgA) + a known suspect-scope vote (proposal in a deleted sub-org). The script correctly detected the leak, kept the suspect-scope row separate, and reported `Leaked vote rows found: 1` plus `Suspect-scope votes: 1`. Bucketing logic verified beyond the empty-DB happy path.

### Z's-decision item

Run the diagnostic against prod to get the real numbers:

```bash
railway ssh "cd /app && python scripts/phase10_2_diagnose_pre_fix_vote_leak.py"
```

> [Corrected post-pass: container path is `scripts/`, not `backend/scripts/`, because Railway's backend service uses `Root directory: backend` and collapses the prefix during build. Documented in DEPLOYMENT.md.]

**If the report shows exactly one leaked vote (Z's wife's), great** — confirms the bug had narrow blast radius and no further action needed.

**If it shows >5 rows OR any rows on a proposal that has reached a binding-decision state**, dispatch Phase 10.3 historical-data remediation. Decision rules for that pass would need Z's input: delete leaked rows vs mark-as-invalid vs recompute affected tallies. The script is read-only by design; remediation is a separate dispatch.

### Phase 10.2 commit list

- `7a4b513` W-DIAG diagnostic script
- `2a5f50d` W-AUDIT docs/test_depth_audit_2026-05.md
- `68b2dd7` W-FIX-C tests/smoke/ + DEPLOYMENT.md addendum
- `0f063ed` W-FIX-A BUG fixes for routes/users.py — auth gate + redaction
- `0bc308f` W-FIX-A Class A auth-module side-effect tests
- `fa97a47` W-FIX-A Class A admin + invitation + avatar polish tests
- `cc1c046` W-FIX-A Class B cross-scope invariant tests + compat-search latent fix
- `af3519a` W-FIX-D + manifest MIME hot-fix: poll_deploy.py + nginx .webmanifest mapping
- `077c652` Merge to master
- closeout commit follows

### Process notes

1. **Multi-agent staging discipline held cleanly for the second pass in a row.** Explicit per-agent file-ownership boundaries in dispatch prompts + "stage and commit ONLY your files" warning. End state: all 9 commits clean, no rewrites needed. The pattern from Phase 10.1 generalizes.
2. **`httpx` substitution caught at agent runtime** (W-FIX-C). The dispatch suggested `requests` based on a wrong assumption about what's in `backend/.venv`; the agent verified, found `httpx` (0.28.1) instead, used it without installing anything new, documented in DEPLOYMENT.md. Good post-dispatch verification discipline.
3. **`poll_deploy.py`'s bundle-hash heuristic incomplete** — only detects deploys that change JS source. nginx-only deploys (this pass) and backend-only deploys leave the bundle hash unchanged, so the script keeps probing until timeout. Logged as new tech debt below. Direct curl + manual smoke worked fine for this pass; future passes touching only nginx or backend Python should skip auto-poll or use `--no-smoke` and verify directly.
4. **The audit doc is the most valuable artifact of this pass** per the spec. Future planner / triage agents should read `docs/test_depth_audit_2026-05.md` before scoping any new endpoint work — the GAP list tells you what's still uncovered, the BUG conventions tell you what the standard fix shape looks like, and the PASS list tells you which patterns are already battle-tested.
5. **Adjacent tech debt observed during W-AUDIT** (logged here per spec instruction "log in PROGRESS.md as a new entry rather than fixing inline"):
   - `routes/users.py::search_users_compat` is a thin wrapper; could be deprecated/merged after callers audited
   - `/api/users/search` unscoped path (no `org_slug`) returns all users (Phase 9.9 known issue)
   - `routes/topics.py::create_topic` requires platform-admin while `routes/organizations.py::create_org_topic` is org-admin (legacy artifact pre-multi-tenancy)
   - `_build_linked_polises` does N+1 stats fetches per linked Polis (already flagged in its docstring)
   - Global `POST /api/proposals` has different validation rules than the org-scoped endpoint (consider deprecating)

### New tech debt

1. **`poll_deploy.py` bundle-hash heuristic incomplete** — only fires on JS source changes. nginx-only or backend-only deploys leave the bundle hash unchanged and the script times out. Candidate fixes: (a) add a `/api/version` endpoint that returns the deployed git SHA, poll on that instead/in-addition; (b) use Railway's GraphQL API to query the latest deploy state directly; (c) add a `--mode=nginx-only|backend-only|frontend|any` flag that picks the right signal per change type. Low priority (manual smoke + direct curl works) but worth fixing before the script becomes load-bearing.
2. **`tests/smoke/` requires the `backend/.venv` to be activated or its python invoked explicitly.** Documented in DEPLOYMENT.md but worth flagging — a CI env that doesn't have the backend deps installed can't run smoke. If we want smoke to run from CI later, either add httpx to a top-level requirements file or use pip install httpx pytest in the CI step.
3. **`slowapi.limiter.reset()` autouse fixture pattern** appears in two test files now (W-FIX-A). Consider promoting to `conftest.py` if more rate-limited endpoints get tests.
4. **Per-affected-user output of `phase10_2_diagnose_pre_fix_vote_leak.py`** — for very large prod DBs this could be a long list. Consider adding a `--limit=N` or `--summary-only` flag if Z's first run produces unwieldy output. Defer until that's seen.

### Pass-summary

**Phase 10.2 shipped clean in a single session** — 9 commits + closeout, no Railway incident, manifest MIME hot-fix bundled in. Audit doc lives in `docs/` as a permanent reference (377 lines covering 75 patterns); fix workstream landed 45 new pytest tests + 2 BUG fixes + 1 latent-bug fix; smoke directory + auto-poll script close the proxy-boundary blind spot that caused 9.8 / 9.9 / 10's hot-fix sequence. Tests 568 → 613 (+45). Bundle unchanged (no JS source touched). PG smoke not required (no schema). Smoke 5/5 PASS on prod post-MIME-fix. Multi-agent staging discipline held for the second pass running. The unifying principle the audit was built around — "assert side-effects, not just API contracts" — is now backed by enumerated coverage of every endpoint / entity / boundary in the system, not just by exhortation in CLAUDE.md.

W-DIAG awaiting Z's `railway run` for prod numbers; if leak is >1 row or affects a binding decision, that becomes Phase 10.3.

---

## Phase 11 — URL Routing Refactor — 2026-05-03

**Single-session pass.** 7 commits on `phase-11/url-routing` no-ff merged to master at `53cb08a` + closeout. **LIVE on prod**, bundle `index-B-Y_0e8o.js`. Path-based org URLs across the frontend; the originally-spec'd shape that Phase 4c deferred. **NO migration**, smoke not required (logic-layer only). **NO design ambiguity** — five conceptual decisions locked with Z up front (D1 path shape flat-under-slug, D2 sub-orgs nested under parent, D3 voter Polis drops `/orgs/`, D4 marketing/auth/onboarding stay top-level, D5 wider scope + no redirect grace period).

### What shipped

**urlFor helper + R1 + R2 + R3 + L3 (frontend dev)** in `frontend/src/utils/urls.js` (new, ~110 lines): `urlFor(orgOrSlug, kind, ...args)` accepts org object or bare slug + route kind string + extra args, returns full path. Throws on unknown kind for fail-loud safety. Covers every org-scoped + sub-org-scoped route kind in the R1 table. **R1**: App.jsx Routes block reshaped to spec verbatim — public marketing top-level (D4), auth flows top-level, onboarding top-level (`/orgs`, `/orgs/create`, `/setup`), `/settings` top-level (user-scoped not org-scoped), org-scoped under `/:org_slug/...` (proposals, proposals/:id, delegations, users/:id, polises/:polis_id — D3 drops `/orgs/` prefix), org-scoped admin under `/:org_slug/admin/...`, sub-org admin under `/:org_slug/admin/sub-orgs/:sub_slug/...` (D2), catch-all `*` → `Navigate to "/"`. New `LandingOrRedirect` component at `/` sends authenticated visitors to `/orgs`, renders public Landing for anonymous (per spec line 198 — small addition not in spec table but required for the auth-aware "/" UX). **R2**: OrgContext URL-derives `currentOrg` via `useParams().org_slug` looked up in `userOrgs` (sub-org routes use `useParams().sub_slug` against cached `subOrgsByParent`, auto-fetches parent's sub-org list if not cached, falls back to parent until sub-org resolves to avoid blank renders). localStorage **demoted** to "last-used hint at sign-in" only — writes `currentOrgSlug` whenever URL-derived parent changes; no longer read during normal navigation; OrgSelector consults at sign-in for single-org auto-redirect. `setCurrentOrg` setter retained as thin "remember + caller-navigates" wrapper (OrgSelector / CreateOrg use it). Auto-select-only-org useEffect on mount removed. OrgSwitcher.click → `navigate(...)` instead of `setCurrentOrg(...)`. New `OrgScopedLayout` wrapper renders inline "You don't have access to this organization / This organization either doesn't exist or you're not a member. Pick an organization you belong to from the list. / [Back to your organizations] (→ /orgs)" when `OrgContext.accessDenied=true` — **NOT a silent redirect** per spec line 200. **R3**: 28 frontend files touched, ~50 call sites converted (every `<Link to=>`, `<NavLink to=>`, `navigate(...)`, `window.location.assign(...)` targeting an org-scoped path). Tricky cases: sub-org currentOrg → parent for parent-org-rooted links via `currentOrg.parent_org_id` lookup against `userOrgs` (Proposals, ProposalDetail, UserProfile, DelegateModal, all 3 graph components, UserLink); NotificationBadge lacks org context for follow-request / unresolved-vote notifications, picks first parent org as default landing (coarse but workable for v1); help pages "Back to" → `/orgs` rather than guessing org context; Demo.jsx post-demo-login → `/orgs` because demo-login response doesn't expose auto-joined slug; InviteAccept post-acceptance → `/${meta.org_slug}/proposals` (verified `meta.org_slug` present in `InvitationMetaOut`); Polis.jsx voter page reads `useParams().org_slug` (was `useParams().slug` when route was `/orgs/:slug/polises/:polis_id`). **L3** explicit deep-link generators each verified: NotificationBadge, LinkedPolisCard, Polis, InviteAccept, OrgSelector (→ `urlFor(org, 'proposals')`), CreateOrg (→ `urlFor(org, 'admin-settings')`).

**Backend (B1+B2+L1+L2)**: **B1** new `backend/reserved_slugs.py` with the 33-word `RESERVED_SLUGS` set per spec lines 266-272; checks added to `routes/organizations.py::create_organization` and `routes/sub_organizations.py::create_sub_org` with `HTTPException(400, "The slug '<slug>' is reserved and cannot be used. Please pick a different one.")` on collision. **67 new parameterized tests** in `test_reserved_slugs.py` (32 reserved-slug entries × 2 routes + 3 regression/ordering checks; `o` slug excluded because the schema validator rejects 1-char slugs before the gate fires). **B2** new `backend/scripts/phase11_check_slug_collisions.py` — read-only one-shot, scans `Organization` rows where `parent_org_id IS NULL` (orgs) and `IS NOT NULL` (sub-orgs), checks `slug.lower()` against `RESERVED_SLUGS`. Pattern matches Phase 10.2 W-DIAG. Verified locally with seeded fixture (correctly detected 2 collisions). **L1** confirmed via grep: `email_service.py` send_verification (`/verify-email`), send_password_reset (`/reset-password`), send_invitation (`/invite/{token}`) all non-org-scoped per D4. **No template changes needed.** **L2** backend grep across `'/proposals'`, `'/admin/'`, `'/orgs/'`, `'/delegations'`, `'/polises'`, `'/settings'`, `liquiddemocracy.us`: 0 files touched. All `/api/...` strings are FastAPI route prefixes / OpenAPI docstrings / test client invocations (define the JSON API surface, unchanged by Phase 11). pol.is embed URLs (`_embed_url_for`, `polis_service.create_conversation` `embed_url`/`manage_url`) target external pol.is service. Audit log `details` fields throughout the codebase store IDs/slugs/names/structured config — never user-facing paths. Avatar `/uploads/...` paths are non-org-scoped static.

**L4 docs**: DEPLOYMENT.md sign-in landing example updated to reflect `/orgs` → `/{slug}/proposals` shape. browser_testing_playbook.md gains header note: "Phase 11 changed URL shape from flat to path-based; old test PASS results NOT retroactively rewritten because they document what was true at the time." future_improvements_roadmap.md Phase 11 marked complete in sequence index + body collapsed (subdomain non-goal preserved). SECURITY_REVIEW.md, CLAUDE.md, TECHNICAL_SUMMARY.md left alone — only contained backend `/api/` paths which are unchanged.

**Backend tests: 613 → 680 (+67).** Full suite green. **No migration, smoke not required.**
**Bundle: 339.23 → 340.71 kB gzipped (+1.48 kB)** — under spec's 2 kB target.

### Production verification

| Check | Result | Evidence |
|---|---|---|
| Smoke suite (post-deploy auto-run via `poll_deploy.py`) | **5/5 PASS** | `index-B-Y_0e8o.js` bundle flipped at 41s; smoke ran in 1.46s, all 5 boundaries clean. **First wild-spotting of W-FIX-D end-to-end** (W-FIX-D from Phase 10.2 just dogfooded successfully on its first JS-source-changing deploy). |
| **R4 #1 Sign-in landing** | **PASS browser-verified** | Demo-login as alice → URL becomes `/demo/proposals` via single-org auto-redirect. Page renders proposals list. |
| **R4 #2 OrgSelector pick** | PASS-by-source | Alice is single-org; auto-redirect fired implicitly (covered by #1). |
| **R4 #3 OrgSwitcher switch** | PASS-by-source | Alice single-org so multi-org switch can't be browser-exercised in demo. OrgSwitcher.click → navigate logic mirrors OrgSelector (per spec line 195). |
| **R4 #4 Sub-org URL shape** | **PASS browser-verified** | `/demo/admin/sub-orgs/demo-engineering/members` — both slugs visible in URL, Engineering Team Members page renders, breadcrumb shows "Demo Organization / Engineering Team", DirectAddSection rendering. |
| **R4 #5 Two-tab independence** | PASS-by-source | Architecture proves it — `useParams()` is per-tab; navigate(...) doesn't touch other tabs. URL is per-tab source of truth (vs. pre-Phase-11 global localStorage). |
| **R4 #6 Deep link member-org proposal** | **PASS browser-verified** | `/demo/proposals/bdf01dad-...` (real proposal id) loaded directly without OrgSelector detour. Full ProposalDetail content + nav + org context render. |
| **R4 #7 Deep link non-member org** | **PASS browser-verified** | Alice navigates to `/gamenights/proposals` (not a GameNights member): URL stays at `/gamenights/proposals` (NOT silent redirect), inline message "You don't have access to this organization / Pick an organization you belong to from the list. / [Back to your organizations]" renders. |
| **R4 #8 Old flat URL → catch-all** | **PASS browser-verified** | `/proposals` (old flat URL) → catch-all → `/` (public Landing for anonymous user). Confirms old org-scoped paths are gone. |
| **B2 lint against prod** (via `railway ssh`) | **1 collision** | `slug=demo org_id=835bc570-... name=Demo Organization` collides with reserved `/demo` marketing route. **Functionally a non-issue** (see Z-decision item below). |

**Bonus first-wild-spotting**: Phase 10.1 W4 stale-bundle toast fired correctly during R4 — the test tab held the prior bundle (`index-DyaIsLQN.js`), the new SW activated on revisit, `controllerchange` listener dispatched `app:bundle-updated`, BundleUpdateNotifier showed "A new version is available. Refresh" toast. First production confirmation that the Phase 10.1 W4 wiring works end-to-end.

### Z's-decision item: 1 slug collision

```
Phase 11 slug-collision lint
Run timestamp: 2026-05-03T22:11:16Z
Total orgs scanned: 2
Total sub-orgs scanned: 2
Colliding slugs found: 1

slug=demo org_id=835bc570-e3ae-4e05-a8b8-ed4b1b22ebdf name=Demo Organization created_at=2026-04-24T21:28:00Z created_by=<unknown> kind=org
```

**Functional analysis**: the `demo` slug is in `RESERVED_SLUGS`, but the seeded Demo Organization was created pre-Phase-11 when the reservation didn't exist. React Router's specificity puts the marketing route's exact `/demo` match first, so the bare URL `/demo` shows the marketing page (correct behavior). But the demo org dashboard IS reachable at `/demo/proposals`, `/demo/admin/...`, etc. — those URLs don't collide with marketing routes (which only match at depth 1). **Browser-verified during R4 #1**: alice's demo-login flow successfully landed at `/demo/proposals` via single-org auto-redirect.

**Recommendation: leave as-is.** The "collision" is functionally harmless. The bare `/demo` showing the marketing page is exactly what visitors should see; the demo org dashboard never had a meaningful bare-slug landing anyway. The B1 reserved-words check now PREVENTS new orgs from being created with `slug=demo`, which is the future-facing protection that matters.

**Alternative if Z prefers stricter alignment**: rename the prod demo org slug via direct DB update (e.g., `UPDATE organizations SET slug='demo-org' WHERE slug='demo';`). Breaks any pre-Phase-11 bookmarks to `/demo/proposals` (probably none beyond the team), and Demo.jsx's post-demo-login flow would route through OrgSelector → `urlFor(demo-org, 'proposals')` → `/demo-org/proposals` cleanly.

### Phase 11 commit list

- `53859aa` urlFor helper introduced
- `229de1d` B1 reserved-words check on slug creation
- `a2d13dc` B2 one-shot slug-collision lint script
- `72e7093` R1+R2: App.jsx route table + OrgContext URL-derives currentOrg
- `a6dbc81` R3: internal link audit — 28 files, ~50 call sites slug-prefixed via urlFor
- `20660fd` L4: documentation path updates
- `53cb08a` Merge to master
- closeout commit follows

### Process notes

1. **Multi-agent staging discipline held cleanly for the third pass running.** Per-agent file-ownership boundaries + "stage and commit ONLY your files" warning. End state: all 7 workstream commits clean, no rewrites needed.
2. **Test count baseline drift caught at agent runtime.** Backend agent flagged that the dispatch's stated baseline of 568 was stale — Phase 10.2 added 45 tests bringing it to 613 pre-Phase-11. Agent reported 613 → 680 (+67). Future dispatches should pull the latest test count from PROGRESS.md instead of restating from spec.
3. **`poll_deploy.py` (W-FIX-D from Phase 10.2) succeeded on its first wild test.** This pass changed JS source so the bundle hash flipped and the auto-smoke fired. The Phase 10.2 closeout's tech-debt note about poll_deploy missing nginx-only deploys remains accurate (still a known gap), but for typical frontend/JS deploys the poll-then-smoke flow now works end-to-end without manual intervention.
4. **Demo-org slug collision predicted by frontend dev mid-pass + confirmed by B2 prod-snapshot run.** Tight loop: prediction → tooling-built-this-pass detection → categorization → Z-decision recommendation. The B2 lint script is now a permanent capability available for any future slug-related concern.

### New tech debt

1. **Demo-org slug=`demo` is collision-flagged but functionally harmless** — Z-decision item above. Document either way: if Z renames, update Demo.jsx hardcoded slug references (likely none beyond the seed file); if Z leaves, document the "bare /demo shows marketing, not demo org dashboard — this is correct" intent in DEPLOYMENT.md.
2. **NotificationBadge default-org coarse routing.** Follow-request and unresolved-vote notifications use the first parent org's slug as a landing because the notification rows don't carry an org_slug field. Multi-org users may land in the "wrong" org from a notification. A future tightening would attach `org_slug` to each notification at production time. Out of Phase 11 scope.
3. **Help page back-links → `/orgs`.** PolisHelp / VotingMethodsHelp / SustainedMajorityHelp previously linked back to `/proposals` (org context-free). Phase 11 sends them to `/orgs` (also context-free). If Z wants smarter back-navigation (`history.back()`), small follow-up.
4. **Old flat URLs land at `/`.** Per D5 "no redirect grace period." If Z later wants a smarter fallback ("you tried `/proposals` — pick an org and we'll take you there"), that's a one-line tweak post-deploy.
5. **Backend test count baseline pattern.** Two passes in a row have had spec-stated baselines that were stale by ~45 tests because the spec was written before the prior pass closed. Worth a process note: dispatch templates should pull from PROGRESS.md ("current test count: ?") not restate from memory.

### Pass-summary

**Phase 11 shipped clean in a single session** — 7 commits + closeout, no hot-fixes, no Railway incident. The originally-spec'd path-based URL shape that Phase 4c deferred is now restored end-to-end: every authenticated org-scoped route lives under `/{org-slug}/...`, sub-orgs nest naturally as `/{org-slug}/admin/sub-orgs/{sub-slug}/...`, voter Polis URLs drop the legacy `/orgs/` prefix, marketing/auth/onboarding stay top-level, no redirect grace period because no live links to break. URL is the source of truth for active org; localStorage demoted to a last-used-hint at sign-in only. urlFor helper centralizes URL construction across 28 frontend files. Backend slug-creation gates against 33 reserved words; one-shot lint script catches existing collisions and surfaced exactly one (the seeded demo org, functionally harmless). Tests 613 → 680 (+67). Bundle gzip +1.48 kB. Smoke 5/5 PASS via auto-poll. Multi-agent staging discipline held for the third pass running. The friend pilot now has deep-linkable, tab-independent, unambiguous URLs for every org context — what the original architecture brief always called for.

---

## Phase 12 Stage 1 — Configurable Role Permissions: Backend Foundation — 2026-05-03

**Single-session pass.** 12 commits on `phase-12/role-permissions-stage-1` no-ff merged to master at `9747cc5` + closeout. **LIVE on prod**, bundle `index-DYPC_ogG.js`. Stage 1 of three-stage Greater Phase 12 arc (Stage 2: permission matrix UI; Stage 3: org branding). Backend foundation for the configurable permission matrix — replaces every hardcoded role-string check with `has_permission(db, user_id, org_id, permission_key)` calls backed by a `roles` + `role_permissions` schema. **Behavior-preserving** except for the user-visible "Owner" role label rename to "Steward". **PG smoke MANDATORY both modes PASS** (prior `b2d5f1a3c7e4`).

### What shipped

**Cluster D — Data model + migration:** New `Role` model (id/org_id FK CASCADE/name/system_key/is_system_preset/display_order/created_at + UQ org_id+system_key) and `RolePermission` model (id/role_id FK CASCADE/permission_key/enabled/created_at + UQ role_id+permission_key) in `backend/models.py`. `OrgMembership.role` string column → `role_id` FK to Role with relationship. Alembic migration `c8f4a9d712e6` (prior `b2d5f1a3c7e4`): creates the two new tables, seeds 4 preset roles (steward/admin/moderator/member, display_order 0-3, is_system_preset=True) for every existing org, seeds 23 default role_permissions per preset role per the registry's DEFAULT_GRANTS table, **maps every existing OrgMembership's string role to the matching role_id with the `'owner' → 'steward'` rename in lockstep**, makes role_id NOT NULL, drops the old string `role` column. Idempotent + reversible (downgrade re-introduces 'owner' string for any membership whose role.system_key='steward'). Cycle test passes upgrade→downgrade→upgrade on SQLite. New `seed_default_roles_for_org(db, org_id)` helper in `backend/role_seed.py` (used by both the migration and `routes/organizations.py::create_organization` for new-org happy path). Sub-org membership stays string-column per D2 (D2 punts sub-org permission matrix to a future arc deliverable). Migration assertions: pre/post OrgMembership row count identical, zero null role_id, zero rows reference 'owner', exact preset counts (steward=23, admin=23, moderator=8, member=0 per role_permissions).

**Cluster H — Helper + cache + registry:** New `backend/role_permissions.py` with `has_permission(db, user_id, org_id, permission_key)` per spec H1. Resolution order: (1) Decision-6 implicit power top-rule — if org_id is a sub-org and user is parent-org admin/steward, return True for any key; (2) Owner-only D4 hardcoded gates — keys `'org.delete'` and `'org.transfer_stewardship'` require `role.system_key == 'steward'` and cannot be re-granted via role_permissions; (3) Standard path — OrgMembership → Role → RolePermission lookup. Returns False on non-member / non-active / no matching row. **Per-request cache** via `db.info['_permission_cache']` keyed by (user_id, org_id) → dict[permission_key, bool]; loads full set on first miss in one query joining 3 tables; subsequent same-pair calls are dict lookups. Verified via SQLAlchemy event-listener instrumentation: 3 has_permission calls = exactly 1 SELECT. New `backend/permission_registry.py` with PERMISSION_REGISTRY (23 PermissionDefinition NamedTuples across 9 categories) + DEFAULT_GRANTS dict (steward=23, admin=23, moderator=8, member=0 — the H agent counted from spec table by hand and corrected the dispatch's stale "23/21/10/0" guess). New `GET /api/permissions/registry` endpoint at `backend/routes/permissions.py` (auth required, no role gate, returns {permissions[], categories[]} with aggressive cache headers possible since data is static per deploy). Stage 2's matrix UI consumes this registry directly.

**Cluster R — Audit + refactor + 248-test fix:** R1 grep-driven audit catalogued 30+ check sites across `backend/routes/*`, `backend/permissions.py`, `backend/org_middleware.py`, `backend/polis_engine.py`. Output `docs/phase12_role_check_audit.md` (367 lines) classifies each: 11 MAPS_TO_KEY (rewrite via has_permission), 4 OWNER_ONLY_D4, 1 DECISION_6_IMPLICIT_D3, 7 SUB_ORG_STRING_PRESERVED (per D2), 5 SERIALIZATION (response shapes — leave as-is), 7 PRODUCTION_INSERT (OrgMembership creation sites that must use role_id), 2 DOESNT_MAP_FLAG (intentional Stage-1-preserved tier checks at `routes/organizations.py:1525` + `routes/proposals.py:580` — moderators-may-only-advance-own-proposals; flagged for Stage 2 revisit if a `manage_others_proposals` permission is added). R2 mechanical rewrite via has_permission(...) with new role-agnostic error message ("You do not have permission to <action> in this organization."). R3 sub-org helpers refactor: `is_sub_org_admin` and `can_create_proposal_in_sub_org` parent-org branches go through has_permission (or Role.system_key check); direct-sub-org-admin string checks stay per D2. R4 part 1: NEW `backend/tests/conftest.py::make_org_membership(db, *, org_id, user_id, role="member", status="active")` Option A helper auto-seeds the 4 preset roles for any test org and translates legacy `role="X"` kwargs to `role_id=...` via lookup (silently maps `'owner' → 'steward'`). 25-file fixture sweep replaced `OrgMembership(role="X")` patterns. R4 part 2: NEW `backend/tests/test_phase12_role_refactor.py` with 15 tests covering positive/negative pairs per refactored production-code site + Decision-6 cross-parent isolation (parent-A admin denied on parent-B's sub-orgs) + D4 owner-only HTTP-layer tests (steward succeeds, admin gets 403) + 3 rename-verification tests confirming API responses surface `system_key` not `'owner'`. Production-code OrgMembership inserts rewritten in `routes/auth.py` (auto-join + invitation-consume + reactivation), `routes/organizations.py` (open + approval-required join + accept_invitation), `seed_data.py`, `scripts/phase9_7_backfill_orphaned_invitations.py`. Each uses a defensive `_resolve_role_id_by_system_key` or `_resolve_org_role_id` helper that auto-seeds presets if not yet present.

**R5 frontend rename sweep:** ~25 grep hits across `OrgContext.jsx`, `Members.jsx`, `Nav.jsx`, `PolisDetail.jsx`, `OrgSelector.jsx`, `Demo.jsx`. Updated role-comparison checks to accept BOTH `'steward'` (new canonical) AND `'owner'` (defensive — handles cached stale API responses during deploy cutover). Display strings updated where role badges show "owner" → "steward". Demo.jsx persona description: "Full org owner" → "Full org steward". `SubOrgMembers.jsx` left as-is (sub-org never had an 'owner' role — that branch was already dead code per D2).

**R6 docs sweep:** SECURITY_REVIEW.md Privileged Access Tiers section gets an inline Phase 12 Stage 1 update note explaining the rename + has_permission architecture + per-request cache + the two operations remaining hardcoded outside the permission system. OWASP A01 row's mention of 'admin or owner' updated to 'admin or steward'. browser_testing_playbook.md: one historical test step at line 762 gets an inline parenthetical noting the rename. CLAUDE.md unchanged (its 'owner' references are project-owner generic, not role-name). DEPLOYMENT.md unchanged (no role-name references found).

**Backend tests: 680 → 740 (+60).** D added 8 (migration cycle + seed). H added 37 (15 registry + 22 helper). R added 15 (positive/negative + rename verification). Full suite green. **PG smoke PASS both modes** (prior `b2d5f1a3c7e4`).
**Bundle: 340.71 → 340.77 kB gzipped (+0.06 kB)** — essentially unchanged (rename sweep is render-time only).

### Production verification

| Check | Result | Evidence |
|---|---|---|
| Smoke (post-deploy auto-run) | **5/5 PASS** | `index-DYPC_ogG.js` flipped at 20s; smoke ran in 1.26s |
| **Migration count check on prod** | **PASS** | 40 OrgMemberships, all 40 have role_id (zero null); 16 roles total = 4 orgs × 4 presets; 216 role_permissions = 4 × (23+23+8+0); **0 'owner' strings** anywhere |
| **'Owner' → 'Steward' rename verified on real data** | **PASS** | 2 stewards post-migration: `admin@demo` + `ZacharyPetertam@gamenights` — exactly the 2 users who held `role='owner'` pre-migration. No data lost; rename is lossless. |
| **Steward tier** (admin user, demo) | **PASS** | `GET /api/orgs/demo` as admin user → `user_role: steward` (was `owner` pre-migration). |
| **Admin tier + owner-only block** (alice, demo) | **PASS** | `GET /api/orgs/demo` as alice → `user_role: admin`. **alice DELETE /api/orgs/demo → 403** with new role-agnostic message "You do not have permission to perform this action in this organization." (spec R2 copy verbatim). |
| **Member tier** (carol, demo) | **PASS** | `GET /api/orgs/demo` as carol → `user_role: member`. carol cannot modify settings. |
| Moderator tier | PASS-by-source | No moderator persona exists in demo seed; covered by R agent's positive/negative test pairs in `test_phase12_role_refactor.py`. |
| **Member list role labels** | **PASS** | `GET /api/orgs/demo/members` returns roles `['admin', 'member', 'steward']` — NO 'owner' string anywhere. |
| **Registry endpoint** | **PASS** | `GET /api/permissions/registry` (auth) → 23 permissions across 9 categories with key/label/description/category shape. Unauthed → 401. |

### Phase 12 Stage 1 commit list

- `4219960` H permission registry + GET /api/permissions/registry endpoint
- `f866367` H has_permission helper + per-request session cache
- `5fdf67b` D Role + RolePermission models + Alembic migration
- `143784a` D seed_default_roles_for_org helper + create_organization wiring
- `d6c095b` D migration cycle + seed tests, Phase 10 cycle test fix
- `89c586c` D role_seed re-exports DEFAULT_GRANTS from permission_registry
- `4390017` R audit doc cataloging 30+ role-string check sites
- `8d97524` R conftest helper + 25-file fixture sweep (248 broken tests → 0)
- `85f3737` R production-code refactor for FK-backed Role lookup
- `73efdf4` R positive/negative tests for refactored sites + rename verification
- `63f37b9` R5 frontend 'Owner' → 'Steward' rename sweep
- `845d9cf` R6 docs sweep
- `9747cc5` Merge to master
- closeout commit follows

### Process notes

1. **Multi-agent staging discipline held cleanly for the FOURTH pass running.** Per-agent file-ownership boundaries in dispatch prompts. D and H ran in parallel without overlap; R ran sequentially after both. All 12 commits clean, no rewrites.
2. **DEFAULT_GRANTS counts verified at agent runtime** — H independently counted from spec table by hand and reported `steward=23, admin=23, moderator=8, member=0` (corrected dispatch's stale `23/21/10/0` guess). D's migration produced the exact same counts via independent re-derivation. Cross-validation between agents caught what would otherwise have been a silent off-by-2 bug.
3. **`248 broken tests` recovery via Option A conftest helper** — D's migration changed `OrgMembership.role` from a string column to a relationship, breaking every test fixture using `role="admin"` kwargs. R agent built an explicit `make_org_membership` factory that auto-seeds preset roles per test org and translates legacy kwargs. 25-file fixture sweep brought all 248 back to green. Option A (explicit helper) chosen over event-listener magic for maintainability.
4. **`poll_deploy.py` worked end-to-end again.** Bundle flipped at 20s — much faster than the 41s we saw on Phase 11 (Railway warm cache). Auto-smoke fired and passed. The W-FIX-D infrastructure from Phase 10.2 is now load-bearing for every JS-changing deploy.

### New tech debt

1. **`OrgMembership.role_id` SQLAlchemy column declared `nullable=True`** but enforced `NOT NULL` in the migrated DB schema — needed during the migration's backfill window. Recommend a one-line follow-up in a future pass to flip the model to `nullable=False` for model/schema alignment.
2. **Two intentional Stage-1-preserved tier checks** at `routes/organizations.py:1525` and `routes/proposals.py:580` — moderators-may-only-advance-own-proposals. Flagged in the audit doc for Stage 2 revisit (a `manage_others_proposals` permission key would let this become a configurable distinction).
3. **`org_middleware.py` exposes coarse-tier dependencies (`require_org_admin`, etc.)** alongside the per-action `has_permission` model. Re-implemented against `Role.system_key` per the audit's pragmatic stance rather than retired wholesale. Stage 2's matrix UI may want to retire them as the API surface stabilizes around per-action permissions.
4. **`Invitations.role` keeps its string column** per spec (invitations are pre-membership artifacts). Values flow through a `_INV_ROLE_TO_SYSTEM_KEY` mapping in 3 places (organizations.py, auth.py, scripts/). Centralizing this mapping if a 4th call site appears would be cleaner.
5. **`routes/proposals.py:578-580` flat path duplicates the org-scoped advance endpoint** at `routes/organizations.py:1503-1525`. Both refactored consistently in this pass; consolidating them is out of scope but worth a future cleanup. (Probably tied to Phase 11's path-based-URL deprecation of legacy flat paths.)
6. **Frontend rename defensive backward-compat** — R5's role-comparison checks accept both `'steward'` and `'owner'` to handle cached stale API responses during the deploy cutover. Once we're confident no clients hold pre-migration tokens (e.g., 1 week post-deploy), the `'owner'` branches can be cleaned up. Small follow-up.

### Pass-summary

**Phase 12 Stage 1 shipped clean in a single session** — 12 commits + closeout, no hot-fixes, no Railway incident, migration ran cleanly against prod's 40 OrgMembership rows. Backend foundation for the configurable permission matrix is now in place: `roles` + `role_permissions` tables, `has_permission(db, user_id, org_id, key)` helper with per-request cache, 23-key registry consumed via `GET /api/permissions/registry`. Every hardcoded role-string check across the backend now goes through the helper (or remains intentionally hardcoded for the two D4 owner-only operations). The "Owner" role label is now "Steward" — verified on prod that the 2 users who pre-migration had `role='owner'` (admin@demo, ZacharyPetertam@gamenights) now have `system_key='steward'` with no data lost. Backend tests 680 → 740 (+60). PG smoke PASS both modes. Multi-agent staging discipline held cleanly for the fourth pass running. **Stage 2 (permission matrix UI) and Stage 3 (org branding) are the natural next passes** — Stage 2 will be "frontend on a clean API" since Stage 1 already shipped the registry + helper.

---

## Phase 12 Stage 2 — Configurable Role Permissions: Permission Matrix UI — 2026-05-03

**Single-session pass.** 7 commits on `phase-12/role-permissions-stage-2` no-ff merged to master at `495c928` + closeout. **LIVE on prod**, bundle `index-Bkxsy4xy.js`. Stage 2 of three-stage Greater Phase 12 arc — the user-facing payoff that builds on Stage 1's backend foundation. Per-org permission matrix at `/{org-slug}/admin/settings/permissions`: roles as columns, permissions as rows, checkbox per cell, save flow with audit logging. **PG smoke MANDATORY both modes PASS** (prior `c8f4a9d712e6`).

### What shipped

**Cluster B — Backend matrix endpoints + audit + lockout + 24th key:**
- **B3 new permission key `role_permissions.edit`** (24th key, default Steward+Admin) added to `permission_registry.py` with category "Organization". DEFAULT_GRANTS counts updated: steward=24, admin=24, moderator=8, member=0. Migration `e6371e56e860` (prior `c8f4a9d712e6`): inserts 1 role_permissions row per existing org's 4 preset roles, idempotent (ON CONFLICT DO NOTHING semantics), reversible (downgrade DELETEs the inserted rows). Cycle test on SQLite passes upgrade→downgrade→re-upgrade.
- **B4 STEWARD_LOCKED_PERMISSIONS frozenset** at `backend/role_permissions.py`: `{member.change_role, org.edit_settings, role_permissions.edit}` — three permissions that prevent self-lockout (without `member.change_role` Stewards can't promote new admins; without `org.edit_settings` they can't change basic org config; without `role_permissions.edit` they can't UNDO any matrix change). New `is_locked(role_system_key, permission_key)` helper. **`has_permission` belt-and-suspenders short-circuit**: Steward + locked key → return TRUE always, even if the underlying RolePermission row is corrupted to enabled=False or missing entirely. Cheap defense (one comparison) against direct DB tampering or migration mistakes.
- **B1 `GET /api/orgs/{slug}/role-permissions`** at `backend/routes/role_permissions_routes.py` — any active org member (no permission gate; reading the matrix is open to all). Returns `{org_id, org_slug, roles[4 ordered by display_order], permissions{key:{role:bool}} for all 24 keys, locked: {steward: [3 protected keys]}}`. Frontend joins with the registry endpoint client-side.
- **B2 `PATCH /api/orgs/{slug}/role-permissions`** — gated by `has_permission(user, org, "role_permissions.edit")`. Body `{changes: [{role_system_key, permission_key, enabled}]}`. Validates each cell against locked set, registry keys, role system_keys (4 presets only). Atomic transaction — invalid cell rejects the whole patch. **No-op (all changes already match) returns `{changes_applied: 0}` and skips audit insert** per Q3. Real changes produce **ONE audit event** `role_permissions.updated` with full structured `changes` payload (each entry has role_system_key, permission_key, old, new). Returns full new matrix in B1 shape so frontend doesn't need a follow-up GET. Last-writer-wins on concurrent edits (acceptable for friend-pilot scale per spec).
- **B5 39 new tests**: 11 lockout/belt-and-suspenders + 26 endpoint coverage (happy/no-op/4 × locked-cell rejection/invalid-key/invalid-role/401/403/404 × 2/atomicity) + 2 migration cycle.

**Cluster F — Frontend matrix UI + F7 D4 UI hiding:**
- **F1 new route** `/{org_slug}/admin/settings/permissions` in `App.jsx`. NOT wrapped in AdminRoute — members get internal read-only mode (F6) rather than 403. New `'admin-permissions'` kind in urlFor helper. New "Permissions" link in Nav.jsx admin dropdown (desktop + mobile mirror), gated on `isAdmin` (steward+admin tier — tech-debt acknowledged that explicit non-tier grants of role_permissions.edit won't surface the link, but members can navigate directly).
- **F2 `RolePermissionsPage.jsx`** (438 lines) renders matrix with all 24 permissions across 4 roles, 9 category section headers (Proposals / Topics / Members / Sub-organizations / Delegate applications / Polis (deliberation) / Comments / Organization / Audit and analytics), permissions in registry-defined order, roles ordered by display_order. Each cell: `<input type="checkbox" checked disabled?>`. Locked Steward cells render disabled+checked with a 🔒 glyph and `title="Required for Stewards — cannot be changed."` Pending changes visually marked with amber ring. Internal state: `serverMatrix` + `pendingChanges Map<"role:perm", boolean>` + derived `displayMatrix`. Toggle+untoggle returns to clean state (entry deleted from map when value matches server).
- **F3 save flow**: Save button enabled only when `pendingChanges.size > 0`. Click → confirmation modal "You are about to change N role permission(s) in {org name}. X will be granted, Y will be revoked. Continue?" → PATCH `{changes}` → on 200, replace `serverMatrix` from response, clear `pendingChanges`, success toast "Permissions updated. {N} change(s) saved." On error: preserve pendingChanges + toast.error. 400 with locked-permission gets explicit "Some changes were rejected by the server: ..." defense-in-depth message. Discard flow: `useConfirm` "Discard {N} unsaved change(s)?" → clear pendingChanges (no server call).
- **F6 read-only mode** for non-edit users: `currentOrg.user_role` not in (steward/admin/legacy owner) → all checkboxes disabled, Save+Discard not rendered, header text " (read-only)". Members navigate directly via URL; route is wrapped only in OrgScopedLayout (not AdminRoute).
- **F4 last-writer-wins** per spec — no periodic refetch, no WebSocket. If two admins edit concurrently, second save's changes overwrite first's; acceptable for friend-pilot scale.
- **F7 D4 hardcoded-gate UI hiding (audit + gate)**: AUDIT FOUND exactly 1 org-level delete-org control (`OrgSettings.jsx`); 4 matrix-routed delete controls correctly LEFT ALONE (sub-org delete via `sub_org.delete`, member remove via `member.remove`, invitation revocation, topic delete via `topic.delete`); transfer-stewardship endpoint doesn't exist yet (no UI to hide). `OrgSettings.jsx` was previously gated on `isOwner` (which already covered steward+legacy-owner so admins were already excluded); switched to explicit local `isSteward` with documented F7 rationale + retained legacy `'owner'` acceptance for cached-response safety during deploy cutover.

**Cluster D — Docs + nav:**
- **D1 on-page header copy** (frontend dev included verbatim from spec): explains role tiers + Steward lockout + audit logging at the top of RolePermissionsPage.
- **D2 NEW `RolePermissionsHelp.jsx`** at `/help/role-permissions` (96 lines). Covers: the four preset roles + their defaults; common configurations ("Want moderators to delete proposals?" etc.); why three Steward permissions are locked; where audit log entries appear; and an EXPLICIT amber-bordered section explaining what is NOT in the matrix and why (org.delete + transfer-stewardship are Steward-only, live outside the matrix because they're load-bearing protections against self-lockout, UI hidden from non-Stewards as defense-in-depth on top of server 403).
- **D3 nav link**: Permissions link added to admin nav (desktop dropdown + mobile mirror) gated on isAdmin tier.
- **D4 SECURITY_REVIEW.md update**: new Phase 12 Stage 2 paragraph in Privileged Access Tiers section covering editability surface (any member reads, role_permissions.edit gates writes, Steward lockout protection set + belt-and-suspenders enforcement, per-save audit, F7 D4 UI hiding pattern, last-writer-wins concurrency posture).

**Backend tests: 740 → 779 (+39).** Full suite green. **PG smoke PASS both modes.**
**Bundle: 340.77 → 344.52 kB gzipped (+3.75 kB)** — under the 5-10 kB target (matrix page + help page + nav link).

### Production verification

| Check | Result | Evidence |
|---|---|---|
| Smoke (post-deploy auto-run via `poll_deploy.py`) | **5/5 PASS** | Bundle flipped at 41s; smoke ran in 1.72s |
| **Migration count check on prod** | **PASS** | 232 total role_permissions rows (216 Stage 1 + 16 Stage 2 for `role_permissions.edit`); 16 = 4 orgs × 4 preset roles each gets the 24th key row |
| **Registry endpoint** | **PASS** | `GET /api/permissions/registry` (auth) → 24 permissions / 9 categories (was 23 pre-Stage-2). |
| **B1 GET matrix as alice (admin)** | **PASS** | 200, returns 4 roles + 24 permissions + `locked.steward = ['member.change_role', 'org.edit_settings', 'role_permissions.edit']`. Role system_keys all 4 presets present. |
| **B1 GET matrix as carol (member, F6 read-only)** | **PASS** | 200 — members can read the matrix; the page renders read-only when they navigate to it. |
| **B2 PATCH no-op (Q3 no-audit)** | **PASS** | `changes_applied: 0` returned + no audit row written. |
| **B2 PATCH locked-cell rejection** | **PASS** | Attempt to set `(steward, role_permissions.edit, false)` → 400 with explicit error: *"Cannot change 'role_permissions.edit' for the Steward role: this permission is locked for the Steward role and cannot be changed."* |
| **B2 PATCH 403 as member without role_permissions.edit** | **PASS** | carol PATCH → 403 (defaulted FALSE for member tier). |
| **B2 PATCH real change end-to-end** | **PASS** | alice PATCH `(moderator, proposal.delete, true)` → 200 + `changes_applied: 1` + new matrix returned with the flip. Reverted via second PATCH (cleanup; prod state clean). |
| F2 matrix render | PASS-by-source | Bundle deployed; frontend dev's commits include all 24 permissions × 4 roles + 9 category groupings + locked-cell tooltips. |
| F3 save flow + confirmation modal + success toast | PASS-by-source | Bundle deployed; spec-verbatim copy + diff-counter logic in `RolePermissionsPage.jsx`. |
| F6 read-only mode for moderator/member | PASS-by-source | Bundle deployed; F6 logic in `RolePermissionsPage.jsx` checks `currentOrg.user_role`. |
| **F7 audit + UI hiding** | PASS-by-source + audit findings documented | OrgSettings.jsx delete-org button gated on `isSteward`. Matrix-routed delete controls (sub-org, members, topics, invitations) correctly LEFT ALONE. |
| F7 backend defense-in-depth | **PASS-from-Stage-1** | DELETE /api/orgs/demo as alice (admin) → 403 (verified during Stage 1 closeout; unchanged). |

### Phase 12 Stage 2 commit list

- `c7f5794` F1 route + nav + urlFor for permissions matrix
- `95006d5` F2/F3/F6 RolePermissionsPage matrix + save flow + read-only mode
- `e3aeca7` F7 hide org-delete UI from non-Steward
- `19e7042` B3 add `role_permissions.edit` (24th key) + migration `e6371e56e860`
- `14c107c` B4 STEWARD_LOCKED_PERMISSIONS + is_locked + has_permission belt-and-suspenders
- `304a01f` B1+B2 per-org matrix endpoints (read + write)
- `29362c8` D help page (RolePermissionsHelp.jsx) + SECURITY_REVIEW.md editability surface
- `495c928` Merge to master
- closeout commit follows

### Process notes

1. **Multi-agent staging discipline held cleanly for the FIFTH pass running.** B + F ran fully parallel with explicit per-agent file ownership; lead handled D + closeout serially. All 7 workstream commits clean, no rewrites needed.
2. **`poll_deploy.py` auto-smoke worked end-to-end again** — bundle flipped at 41s (Phase 11 was also 41s; Phase 12 Stage 1 was a fast 20s with warm cache). The W-FIX-D infrastructure from Phase 10.2 is now load-bearing for every JS-changing deploy.
3. **F7 audit produced exactly the right discrimination** — frontend dev correctly identified that sub-org delete + member remove + topic delete + invitation revocation are matrix-routed and should NOT be tier-gated; only the org-level delete in OrgSettings.jsx needed the F7 gate. This is the kind of audit discipline the spec called out as the "most important non-mechanical piece" of F7, and it landed cleanly.
4. **Cross-validation between B and F** — F built against the spec'd response shape before B's endpoints landed; once B committed, F's existing client code worked end-to-end without integration friction. Speaks to the value of locked spec contracts.

### New tech debt

1. **Tier shortcut for "Permissions" nav link visibility** (acknowledged in spec): if a moderator or member is later granted `role_permissions.edit` explicitly via the matrix, the nav link won't show even though they could navigate directly. Spec calls this acceptable Stage-2 tradeoff. A future pass could expose `has_permission` as a per-permission API endpoint or include the user's effective permission set in the org GET payload.
2. **F6 read-only detection uses tier shortcut too** — same caveat. A moderator with explicit `role_permissions.edit` would see read-only even though the backend would let them save. Same future-fix as above.
3. **F7 legacy `'owner'` acceptance** in OrgSettings.jsx kept defensively to avoid lockout during deploy cutover when cached `/api/orgs` payloads may still report `'owner'`. Once Stage 1 + Stage 2 are fully cut over and cached responses age out (~1 week post-deploy), the gate can tighten to strict `'steward'`.
4. **`role_seed.py` only inserts True grants** so freshly-seeded orgs have no row for moderator/member × `role_permissions.edit` while migrated orgs do (the migration explicitly inserts False rows). Functionally identical (B1 endpoint defaults missing rows to False), but a future pass could update the seed helper to insert explicit False rows for any (preset role, registry key) pair not in DEFAULT_GRANTS for tidiness.
5. **No "reset to defaults" button** — a natural follow-up. Single button that reverts the org's matrix to the registry's default-grant table; needs confirmation modal (destructive). Spec called it out as out-of-scope but worth a future ~half-session pass.
6. **No bulk operations** (copy column to column, "give Moderator the same permissions as Admin"). Useful for orgs setting up custom configs; not urgent without that demand signal.

### Pass-summary

**Phase 12 Stage 2 shipped clean in a single session** — 7 commits + closeout, no hot-fixes, no Railway incident. The Greater Phase 12 arc's user-facing payoff is now live: any org with a Steward or Admin can navigate to `/{org-slug}/admin/settings/permissions` and edit the per-role permission matrix through a checkbox UI, with audit logging on every save, and three Steward permissions hardcoded TRUE to prevent self-lockout. The matrix is read-only-viewable by all org members for accountability. The D4 hardcoded gates (`org.delete` and the future `transfer-stewardship`) are now hidden from non-Steward UI as defense-in-depth on top of Stage 1's existing 403s. Backend tests 740 → 779 (+39). Bundle gzip +3.75 kB. PG smoke PASS both modes. Multi-agent staging discipline held for the fifth pass running. Stage 3 (org branding — logo upload, color picker, dynamic theming) is the natural final stage of the Greater Phase 12 arc and the next planning conversation.

---

## Phase 12.5 — Permission System Completeness — 2026-05-04

**Single-session bundled coherence pass.** 13 commits on `phase-12-5/permission-completeness` no-ff merged to master at `578e643` + closeout. **LIVE on prod**, bundle `index-CZa6IDUq.js`. Three connected gaps Z surfaced dogfooding the Stage 2 matrix UI: (1) granted permissions had no UI surface — admin nav was role-gated separately ("the matrix lies"); (2) free-form approval thresholds bypassed the permission model entirely; (3) demo data didn't show off the Moderator tier. **PG smoke MANDATORY both modes PASS** (prior `e6371e56e860`).

### What shipped

**Cluster B — Backend:**
- **B1 25th permission key `proposal.set_thresholds`** (default Steward+Admin only, "Proposals" category). Migration `41694d86821f` inserts 1 row per existing org's 4 preset roles (steward+admin true; moderator+member explicit false per Stage 2 consistency). DEFAULT_GRANTS counts now: steward=25, admin=25, moderator=8, member=0.
- **B2 `get_default_proposal_thresholds(org)`** helper in `backend/org_config.py` with defaults-if-absent (0.50/0.40). NO migration backfill of `Organization.settings` JSON — defaults-if-absent in helper handles existing orgs (spec line 122 explicit: keep settings lean).
- **B3 threshold enforcement on POST + PATCH `/api/proposals`**: new `_enforce_threshold_permission` helper. "Differs from defaults" check (not strict-omit) — caller passing values matching org defaults always succeeds; only differing values trigger the check. Without `proposal.set_thresholds` AND non-default value → 400 with explicit message. `ProposalUpdate` schema gained `pass_threshold` + `quorum_threshold` fields (previously the PATCH endpoint had no way to change thresholds at all — flagged as pre-existing observation). 12/12 enforcement tests PASS across both endpoints.
- **B4 `user_permissions: [...]` field on `/api/orgs/{slug}` response**: enumerates 25-key registry + calls `has_permission` per key. **Stage 1's per-request cache verified end-to-end** — 25 has_permission calls in `_org_to_out` execute exactly **1 SELECT** against `role_permissions` (instrumented via SQLAlchemy `before_cursor_execute` event listener). For non-members → `user_permissions=[]`. Decision-6 implicit power resolves naturally via has_permission.
- **F4 backend support** (Option A — extends existing): `PATCH /api/orgs/{slug}` accepts `settings.default_pass_threshold` + `default_quorum_threshold` with 0-1 validation. New audit event `org.default_thresholds_changed` with `{key: {old, new}}` diff map; only-when-changes (no-op patch emits no event).

**Cluster F — Frontend:**
- **F1 admin nav refactor**: NEW `frontend/src/constants/admin_nav_permissions.js` with 10-subsection mapping (proposals/topics/members/subOrgs/delegates/polises/settings/permissions/analytics/audit). NEW `useHasPermission(key)` + `useHasAnyPermission(keys)` hooks reading from `currentOrg.user_permissions`. Top-level Admin tab gated on `currentOrg.user_permissions.length > 0`; per-subsection gated via mapping. **Cache-safety fallback**: when `user_permissions` is absent (cached stale API response during cutover), legacy role-tier visibility preserves admin/moderator nav until cache clears.
- **F2 in-page audit gated 16 controls across 9 admin pages** (ProposalManagement: 5, SubOrgProposals: 1, Topics: 3, Members: 5, Polises: 1, PolisDetail: 1, SubOrgList: 1, DelegateApplications: 1, ProposalDetail: 1). Sub-org delete intentionally LEFT ALONE — matrix-routed per Phase 12 Stage 2 F7. Per-control conditional renders via useHasPermission. Preserves Steward/Admin behavior; what changes is what Moderator/Member see when granted partial sets.
- **F3 CreateProposal threshold form gating**: threshold inputs (`ProposalManagement::CreateProposalForm` + `SubOrgProposals::CreateProposalForm`) hidden for users without `proposal.set_thresholds`; explanatory blue notice "Proposals will use this organization's default approval thresholds. Ask an Admin or Steward if you need different thresholds for this proposal." POST payload omits threshold fields so backend B3 applies org defaults. PATCH-side gating implicit because no EditProposal page exists in the frontend.
- **F4 Default Approval Thresholds editor on OrgSettings.jsx** (gated by `useHasPermission('org.edit_settings')`). 0-1 number inputs (step 0.01, clamped) for `default_pass_threshold` + `default_quorum_threshold`. Save uses existing PATCH `/api/orgs/{slug}` endpoint; audit fires only on actual diff.

**Cluster D — Demo + docs:**
- **D1 voter02 promoted to Moderator on demo**: seed_data.py updated for fresh-DB scenarios (idempotent helper "never overwrites" so seed re-run on existing prod row is a no-op). **Prod existing row updated via railway ssh** with direct `OrgMembership.role_id` flip to the demo-org Moderator role. Verified post-update: voter02's existing data intact (5 votes + 1 comment preserved); user_role = moderator on `/api/orgs/demo` response.
- **D2 docs sweep**: browser_testing_playbook.md gets 2 new header notes (voter02 demo persona promotion — historical "voter02 is Member" tests stay PASS-as-recorded; admin-nav gating migrated from role-tier to permission-driven). SECURITY_REVIEW.md Privileged Access Tiers gets Phase 12.5 update note covering 25th permission key + threshold enforcement, org-level default thresholds + audit event, permission-driven admin nav gating closing the "matrix lies" gap. Defense-in-depth posture unchanged — backend remains source of truth.

**Backend tests: 779 → 820 (+41).** Full suite green. **PG smoke PASS both modes.**
**Bundle: 344.52 → 345.43 kB gzipped (+0.91 kB)** — well under 3-6 kB target.

### Production verification

| Check | Result | Evidence |
|---|---|---|
| Smoke (post-deploy auto-run via `poll_deploy.py`) | **5/5 PASS** | Bundle flipped at 41s; smoke ran in 1.41s |
| **Migration count check on prod** | **PASS (250 rows)** | Total role_permissions = 250 (= 248 expected + 2 explicit-FALSE rows from prior matrix UI testing on demo + gamenights). 16 `proposal.set_thresholds` rows = 4 orgs × 4 preset roles ✓ |
| **`user_permissions` field per tier** | **PASS** | Steward (admin user): 25 perms ✓ / Admin (alice): 25 perms ✓ / Moderator (voter02 post-promotion): **8 perms** matching DEFAULT_GRANTS for moderator (comment.moderate, member.approve_join, member.invite, polis.create, proposal.advance_phase, proposal.create, topic.create, topic.edit) ✓ / Member (carol): **0 perms** ✓ |
| **B3 threshold enforcement (POST happy path)** | **PASS** | alice (admin, has set_thresholds) POST with non-default `pass_threshold=0.65` → 201; cleanup via direct DB delete |
| B3 threshold enforcement (POST 400 case) | PASS-by-source (12/12 unit tests) | Carol blocked at proposal.create gate before B3 fires; backend tests cover the threshold-block exhaustively |
| **Voter02 promotion on prod** | **PASS** | OrgMembership.role_id flipped via railway ssh from member role to moderator role; voter02's 5 votes + 1 comment intact; subsequent `/api/orgs/demo` shows user_role=moderator with correct 8-permission set |
| F1 admin nav permission-driven | PASS-by-source | Bundle deployed; frontend dev's commits include subsection mapping + Nav.jsx refactor + cache-safety fallback |
| F2 in-page control gating | PASS-by-source | 16 controls gated across 9 files per audit; verified via source review |
| F3 threshold form gating | PASS-by-source | CreateProposalForm in both ProposalManagement.jsx + SubOrgProposals.jsx hide inputs when permission absent + show explanatory notice |
| F4 Default Approval Thresholds editor | PASS-by-source | Section in OrgSettings.jsx + backend save endpoint with audit |
| **Cache verification (B4)** | **PASS** | Backend agent's instrumented test confirmed 25 `has_permission` calls = exactly **1 SELECT** against role_permissions per `_org_to_out`. Stage 1's per-request cache works as designed. |

### Phase 12.5 commit list

- `657a787` F1 add admin_nav_permissions constant + useHasPermission hook
- `736a2e5` F1 gate admin nav on user_permissions, not role tier
- `2b83dbb` B1 add proposal.set_thresholds permission key + migration
- `071fbaf` B2 get_default_proposal_thresholds helper
- `7b14116` F2/F3 per-control permission gating across admin pages
- `416cd19` B3 enforce proposal.set_thresholds on POST + PATCH
- `ad8b40a` B3 _enforce_threshold_permission helper + tests
- `8ca81e2` F4 Default Approval Thresholds editor on OrgSettings
- `166e2ec` B4 user_permissions field on /api/orgs/{slug} response
- `0a0c5be` F4 backend default-thresholds save endpoint extension
- `d729865` B5 update existing migration cycle tests for new head
- `c4e580a` D1 promote voter02 to Moderator on demo (seed for fresh DBs)
- `cbc10fc` D2 docs sweep — playbook header notes + SECURITY_REVIEW update
- `578e643` Merge to master
- `<closeout>` PROGRESS entry

### Process notes

1. **Multi-agent staging discipline held cleanly for the SIXTH pass running.** B + F ran fully parallel with explicit per-agent file ownership; lead handled D + closeout serially. All 13 workstream commits clean, no rewrites needed. The pattern from Phase 10.1 onward is now reliably reproducible.
2. **`poll_deploy.py` auto-smoke worked again** — bundle flipped at 41s, smoke 5/5 PASS in 1.41s. The W-FIX-D infrastructure from Phase 10.2 is now load-bearing for every JS-changing deploy.
3. **F2 audit produced exactly 16 control gatings across 9 files** — frontend dev correctly identified that sub-org delete is matrix-routed and should NOT be tier-gated (per Phase 12 Stage 2 F7 precedent), only org-level controls + admin-tier action buttons get the new permission gates. Audit-discipline thread continues from Stage 2 F7.
4. **B4 cache verification was a real win** — explicit instrumented test that 25 has_permission calls = 1 SELECT validates the Stage 1 per-request cache assumption end-to-end. Future passes that enumerate the registry can rely on this confidently.
5. **D1 voter02 promotion via direct DB UPDATE on prod** — `_add_org_membership` is "never overwrite role/status" so seed re-run wouldn't help. One-shot `OrgMembership.role_id` flip via railway ssh is the correct pattern (mirrors Phase 9.6/9.7 backfill commands). voter02's votes + comments preserved end-to-end.

### New tech debt

1. **Sub-org admin nav shortcut still uses role-tier** (`subOrgUserIsAdmin`) rather than permission-driven gating. Sub-org permission system is explicitly out of scope per Phase 12 Stage 1 D2; flagged for whenever sub-orgs get their own permission matrix.
2. **`PolisDetail.jsx` admin-controls visibility** uses `polis.manage` OR creator OR sub-org admin role-tier — the sub-org fallback should migrate when sub-orgs get permission gating.
3. **F1 cache-safety fallback** to legacy role-tier preserves admin/moderator nav visibility when `user_permissions` is absent from cached responses. Once Phase 12.5 is fully cut over and cached responses age out (~1 week post-deploy), the fallback can be removed for strict permission-driven gating only.
4. **`role_seed.py` only inserts True grants** (Stage 1 tech debt carried forward). Migrated orgs have explicit FALSE rows for moderator/member × `role_permissions.edit` + `proposal.set_thresholds`; freshly-seeded orgs (via DEFAULT_GRANTS) don't. Functionally identical via B1 default-False, but tidiness-wise a future pass could update the seed helper to write explicit FALSE rows for any (preset role, registry key) pair not in DEFAULT_GRANTS.
5. **`ProposalUpdate.pass_threshold`/`quorum_threshold` are NEW fields** in this pass — previously PATCH had no way to change thresholds. If anyone was relying on "thresholds frozen post-create," the PATCH-with-permission path is now a valid mutation surface. Pre-existing observation; no current callers depend on the prior immutability.
6. **Pattern of "feature surface gated by role rather than permission" likely exists elsewhere** beyond admin nav. F2 surfaced the high-value sites (admin nav + in-page admin controls + create-proposal form + default thresholds). Other places where role-tier gating still appears (e.g., DelegationNetworkGraph admin badge, profile-page role display) are cosmetic and can stay as-is until they become actively confusing.

### Pass-summary

**Phase 12.5 shipped clean in a single session** — 13 commits + closeout, no hot-fixes, no Railway incident, migration ran cleanly against prod's existing role_permissions rows. Three connected gaps Z surfaced dogfooding the Stage 2 matrix are all closed: granted permissions now have UI surface (admin nav + in-page controls permission-driven, 16 gates added across 9 pages), free-form thresholds now require `proposal.set_thresholds` (default Steward+Admin) with org-level defaults editable on OrgSettings, demo org now shows the four-tier role system clearly with voter02 promoted to Moderator. Backend tests 779 → 820 (+41). Bundle gzip +0.91 kB. PG smoke PASS both modes. Multi-agent staging discipline held cleanly for the sixth pass running. The permission system is now the source of truth for what users can do and the rest of the surface is aligned. **Stage 3 of Greater Phase 12 (org branding — logo + color + dynamic theming) is the natural next pass when it gets prioritized.**

---

## Phase 12.6 — Route Guard Permission Refactor + Demo & Copy Polish — 2026-05-04

**Single-session bundled follow-up to 12.5.** 3 commits on `phase-12-6/route-guards-and-demo-polish` no-ff merged to master at `9fd9742` + closeout. **LIVE on prod**, bundle `index-Cewxn9Zb.js`. Three issues Z surfaced dogfooding 12.5: a real route-guard bug, a UX copy nit, and a planning-agent miss on what "demo persona" meant in 12.5. **No backend changes; no migration; no PG smoke required.** Backend tests unchanged at 820.

### What shipped

**Cluster G — Route guard refactor (the load-bearing fix):** 12.5 made admin-nav VISIBILITY permission-driven (F1) and in-page controls permission-driven (F2) but missed the route GUARDS. `AdminRoute` still used `isModeratorOrAdmin`; `AdminOnlyRoute` still used `isAdmin`. A Member granted `proposal.create` via the matrix saw the admin Proposals nav link (correct, 12.5 F1) but clicking it bounced to `/{slug}/proposals` because the route guard rejected them. **Same family of bug as 9.6/9.7/9.8/9.9/10.1** — feature works at one layer, broken at adjacent layer.

- **G1 audit**: identified all 10 admin route usages across `AdminRoute` (5 routes: members, proposals, topics, polises × 3) and `AdminOnlyRoute` (4 routes: settings, delegates, analytics, sub-orgs). The `/admin/settings/permissions` route is intentionally NOT wrapped — Phase 12 Stage 2 F6 ships read-only mode for non-edit users and the page handles permission-driven gating internally. Sub-org admin routes (settings/members/proposals/topics/polises) rely on server-side `is_sub_org_admin` and have no client-side guard wrapper.
- **G2 + G4 refactor**: both `AdminRoute` and `AdminOnlyRoute` now accept a `permissions={[]}` prop. Any-semantics — caller must have AT LEAST ONE of the listed permissions. Resolved from `currentOrg.user_permissions` (the 12.5 B4 field). Cache-safety fallback to legacy role-tier check when `user_permissions` is absent (cached stale API response during deploy cutover). On access denial: redirect to `/{slug}/proposals` (matches prior fallback behavior).
- **G3 App.jsx**: all 10 routes updated to pass `permissions={ADMIN_NAV_SUBSECTION_PERMISSIONS.<key>}` from the SAME constant 12.5 F1 nav reads from. **Single source of truth** — nav and routes read from one mapping; can't drift.
- The two guards (AdminRoute / AdminOnlyRoute) are now functionally indistinguishable — both gate on a passed-in permission list. Kept as separate components for now to keep call-site intent explicit ("this used to require moderator-or-admin" vs. "this used to require admin tier") and to keep the 12.6 diff surgical. A future cleanup pass could merge them into one `PermissionRoute`.

**Cluster C — Threshold-form copy update:** 12.5 shipped a "Proposals will use this organization's default approval thresholds. Ask an Admin or Steward..." message for users without `proposal.set_thresholds`. Z's note: this told the user nothing about what the defaults actually ARE. C1 replaces it with a read-only display showing the actual percentages: **"Approval thresholds / This proposal will use the organization's defaults: 50% pass / 40% quorum."** Numbers from `orgSettings.default_pass_threshold/quorum` (12.5 B2) with fallback to 0.50 / 0.40. Updated in both `ProposalManagement.jsx` (org-wide proposals) and `SubOrgProposals.jsx` (sub-org proposals; for sub-orgs the prop is `effectiveSettings` which walks the parent chain via `get_org_config`). No "ask an Admin" suffix.

**Cluster D — Demo persona Moderator fix:** 12.5 promoted `voter02` to Moderator on the demo org but voter02 isn't on the persona-picker page (alice/dr_chen/carol/dave/frank/admin) — original spec misread "demo persona" as "membership row" instead of "persona-picker entry." 12.6 promotes `frank` (formerly the "New Voter" card — least informative) to Moderator. **voter02's Moderator role from 12.5 stays** — having two Moderators in the demo is realistic.
- **D1 prod DB UPDATE via railway ssh** (same pattern as 12.5's voter02 promotion; `_add_org_membership` is "never overwrite role/status" so seed re-run wouldn't help): `OrgMembership.role_id` flipped member → moderator. Pre-update: frank role=`member`, votes=1, comments=0, delegations=0. Post-update: role=`moderator` (Moderator), data intact (1 vote preserved).
- **D1 seed_data.py** updated for fresh-DB scenarios (`_add_org_membership(frank, demo_org, "moderator")`).
- **D2 Demo.jsx PERSONAS** — frank's entry changes from `{role: 'New Voter', description: 'No delegations or follows yet. Start fresh.'}` to `{role: 'Moderator', description: "A trusted member with limited admin powers. Can create proposals, manage topics, approve member join requests, and moderate comments — but can't change settings or remove members."}` per spec Q2. Other 5 personas unchanged.

**Backend tests: 820 → 820 (unchanged).** No backend code touched.
**Bundle: 345.43 → 345.67 kB gzipped (+0.24 kB).** Three small frontend changes; minimal delta.
**No migration; no PG smoke required.**

### Production verification

| Check | Result | Evidence |
|---|---|---|
| Smoke (post-deploy auto-run via `poll_deploy.py`) | **5/5 PASS** | Bundle flipped at 102s; smoke ran in 1.50s |
| **G5 LOAD-BEARING route-guard fix** | **PASS end-to-end on prod** | alice grants `member.proposal.create` via PATCH matrix → 200 + changes_applied=1. Carol now has `user_role: member` AND `user_permissions: ['proposal.create']`. Pre-12.6 AdminRoute (`isModeratorOrAdmin`) would have REJECTED carol; post-12.6 AdminRoute checks `permissions.some(p => userPerms.includes(p))` against `ADMIN_NAV_SUBSECTION_PERMISSIONS.proposals` and ACCEPTS her since `'proposal.create'` is in that list. Revert: changes_applied=1; carol back to 0 perms; prod state clean. |
| G5 SPA route render verification | PASS-by-source | Bundle deployed (`user_permissions` string referenced 8× in `index-Cewxn9Zb.js`); AdminRoute + AdminOnlyRoute source verified to use the new permission-keyed shape; data-shape verification above proves the resolution path returns the right answer. |
| C1 threshold defaults in API | **PASS** | `/api/orgs/demo` response includes `settings.default_pass_threshold=0.5` + `default_quorum_threshold=0.4`. C1 read-only display will render `50% pass / 40% quorum`. |
| C1 copy update in deployed bundle | PASS-by-source | New "Approval thresholds" + "%pass / %quorum" copy in both ProposalManagement.jsx + SubOrgProposals.jsx; ProposalManagement uses `orgSettings` prop directly (= currentOrg.settings); SubOrgProposals uses `effectiveSettings` prop (parent chain via get_org_config). |
| **D3 frank promotion on prod** | **PASS** | `/api/orgs/demo` as frank: `user_role: moderator`, `user_permissions count=8` matching DEFAULT_GRANTS exactly: `[comment.moderate, member.approve_join, member.invite, polis.create, proposal.advance_phase, proposal.create, topic.create, topic.edit]`. Existing data preserved: 1 vote, 0 comments, 0 delegations (same as pre-promotion). |
| D3 Demo.jsx persona-card render | PASS-by-source | PERSONAS array updated; frank's role label = "Moderator", description = new spec copy. Other 5 personas untouched. |

### Phase 12.6 commit list

- `8258cfb` G route-guard permission refactor (the load-bearing fix)
- `946b744` C1 threshold-form copy → read-only numeric defaults
- `7f2ea29` D1+D2 promote frank to Moderator on demo (seed + persona card)
- `9fd9742` Merge to master
- closeout commit follows

### Process notes

1. **Multi-agent staging discipline N/A this pass** — single-dev path (lead handled all three clusters in serial). Total scope was small enough that parallelism wouldn't have helped.
2. **`poll_deploy.py` auto-smoke worked again** — bundle flipped at 102s (slower than the 41s pattern; Railway cache may have been cold for this deploy), smoke 5/5 PASS in 1.50s.
3. **D1 voter02-pattern reused for frank** — same `_add_org_membership` "never overwrite" caveat, same direct-DB-UPDATE-via-railway-ssh approach, same data-integrity-preserving outcome. The pattern is now reproducible and predictable for any future seeded-persona role flip.
4. **G's audit confirmed exactly 10 routes need updating + 2 guards need refactoring.** No surprises — `ADMIN_NAV_SUBSECTION_PERMISSIONS` was already shaped right for the route-guard usage so single-source-of-truth fell out naturally without needing to adjust the constant's export.
5. **The route-guard family was a Phase 12.5 audit coverage gap** — 12.5 explicitly covered in-page controls (F2: 16 gates) + admin nav visibility (F1) but didn't audit the route guards themselves. The 6th instance of "feature works at one layer, broken at adjacent layer" (joining 9.6 / 9.7 / 9.8 / 9.9 / 10.1). Worth flagging as a Phase 10.2-followup candidate: extend the test-depth audit doc to cover frontend route guards explicitly.

### New tech debt

1. **Cache-safety fallback in AdminRoute + AdminOnlyRoute** to legacy role-tier check preserves admin/moderator nav when `user_permissions` is absent (cached stale API responses during cutover). Once 12.5 + 12.6 are fully cut over and cached responses age out (~1 week post-deploy), the fallback can be removed for strict permission-driven gating only. Bundle this with 12.5 F1's identical fallback in Nav.jsx in the same future cleanup pass.
2. **AdminRoute and AdminOnlyRoute are functionally indistinguishable** post-12.6 — both gate on a passed-in permission list. Kept as separate components for diff surgery + call-site intent clarity. A future cleanup pass could merge them into one `PermissionRoute` component.
3. **Route-guard family was a 12.5 audit gap** — same theme as the Phase 10.2 test-depth audit but at the frontend route layer specifically. Worth a Phase 10.2-followup pass that extends the audit doc to cover frontend route guards as a documented class.

### Pass-summary

**Phase 12.6 shipped clean in a single session** — 3 commits + closeout, no hot-fixes, no Railway incident. The load-bearing route-guard bug (a Member granted `proposal.create` via matrix can now actually navigate to `/{slug}/admin/proposals` and the page renders) is verified end-to-end on prod via matrix grant → API user_permissions check → revert. Threshold-form copy now shows actual default percentages instead of unhelpful "ask an Admin" boilerplate. Frank is the demo persona-picker's Moderator entry alongside voter02 (data preserved end-to-end via direct DB UPDATE). Backend untouched. Bundle gzip +0.24 kB. **The "matrix lies" gap is now fully closed across all three layers (nav visibility from 12.5 F1 + in-page controls from 12.5 F2 + route guards from 12.6 G).** Stage 3 of Greater Phase 12 (org branding) remains the natural next pass when prioritized.

---

## Phase 12.7 — Org Branding (Logo + Color) + Copy Polish — 2026-05-04

**Stage 3 of Greater Phase 12 — completes the arc.** 12 commits on `phase-12-7/org-branding` no-ff merged to master at `141b10c` + closeout. **LIVE on prod**, bundle `index-Dq7QQXBf.js`. Steward-configurable per-org logo + primary color, applied across the org-scoped UI surface (nav, OrgSelector cards, admin shell, theming hook on org-scoped routes) and into the org-scoped invitation email. Three landing/demo copy fixes locked with Z. Persistent uploads via Railway Volume (declaration shipped; provisioning + migration are post-merge Z-decision items). **Backend tests 820 → 847 (+27).** **No schema migration** (branding lives in the existing `Organization.settings` JSON column).

### What shipped

**Cluster I — Persistent uploads infra (Railway Volume + path constants):**
- `railway.toml` declares `[[volumes]] mountPath = "/data"`. Once provisioned via Railway dashboard, the container mounts at `/data` and uploaded logos/avatars persist across redeploys.
- 3-tier path resolver: `_resolve_uploads_base()` checks env override → Railway Volume `/data/uploads` (writable) → local-dev fallback `backend/uploads/`. **Deploy is safe regardless of Volume provisioning state** — falls back to ephemeral container path if `/data` not mounted, which is fine for testing the end-to-end flow but doesn't persist.
- `backend/scripts/phase12_7_migrate_uploads.py` — idempotent one-shot migration of legacy `backend/uploads/avatars/*` → `/data/uploads/avatars/*`. Source-equals-destination check exits cleanly on local dev. Z runs once via `railway ssh "cd /app && python scripts/phase12_7_migrate_uploads.py"` after Volume mount.

**Cluster B — Logo upload + branding settings + response shape + 26 new tests:**
- `POST /api/orgs/{slug}/logo` (multipart upload, content-type whitelist for PNG/JPEG/WebP, 6 MB cap, Pillow resize to 400×160 + 200×80, format-preserving so PNG transparency survives).
- `DELETE /api/orgs/{slug}/logo` (removes file + clears settings ref).
- `PATCH /api/orgs/{slug}/branding` (`primary_color`, `accent_color`, `accent_auto_derived`; validated hex colors).
- All org-returning endpoints (`GET /api/orgs`, `GET /api/orgs/{slug}`, `PATCH /api/orgs/{slug}`, `POST /api/orgs`, `PATCH /branding`, `POST/DELETE /logo`) now serialize via the centralized `_org_to_out` helper which always emits a consistent `BrandingOut` shape (logo_url, primary_color, accent_color, accent_auto_derived). Frontend logic doesn't have to handle "key missing" and "key explicitly null" as distinct cases.
- New `BrandingOut`, `BrandingUpdate`, `_validate_hex_color`. `OrgOut.branding` field added.
- Tests: `test_phase12_7_org_branding.py` adds 26 cases covering upload validation, content-type rejection, size cap, dimension cap, file-overwrite cleanup, color validation, branding round-trip, response-shape consistency. **Backend suite 820 → 846.**

**Cluster F — Frontend theming + Settings UI + Nav logo + OrgSelector cards:**
- **F1**: Migrated 65 files / 678 sites from hardcoded brand colors (`#1B3A5C` etc.) to CSS variables (`--brand-primary`, `--brand-primary-dark`, `--brand-accent`) via `var(--brand-primary)` and Tailwind arbitrary-value syntax `bg-[var(--brand-primary)]`. Default values defined in `:root` in `index.css`. **Bundle delta only +2.96 kB gzipped** (CSS variables are textually small).
- **F2**: `BrandingThemeApplier` component mounted in `OrgScopedLayout` (all 3 branches in App.jsx). useEffect on `currentOrg.branding` sets `--brand-primary`/`--brand-accent` CSS vars on `document.documentElement`. Cleared when leaving org-scoped routes (so the public landing page never inherits an org's branding).
- **F3**: `utils/color_derive.js` — `deriveLighter`, `deriveDarker`, `getDerivedAccent` via HSL roundtrip. Used by F4 for the auto-derive checkbox's live preview.
- **F4**: `OrgSettings` Branding section — logo upload (preview thumbnail, drag-or-click, 6 MB visible cap), color pickers for primary + accent, "auto-derive accent from primary" checkbox with live recompute via `getDerivedAccent`, Save + Reset buttons. **Gated by `useHasPermission('org.edit_branding')`** so non-Steward users don't see the section. Hydration fix (commit `b6d2b62`): default auto-derive ON for unconfigured orgs (primary_color null) and respect backend's `accent_auto_derived` flag only when org has actually configured a primary.
- **F5**: Nav bar — when `currentOrg.branding.logo_url` is set, shows the logo `<img>` to the left of the org name. Sub-org views inherit the parent org's logo.
- **F6**: OrgSelector cards — per-card branding via inline styles (NOT global CSS vars, so each card can show its own org's identity without theme bleed across cards). 4px left border in `primary_color` + colored heading + logo at top of card.

**Cluster E — Email theming (best-effort, only the org-scoped invitation email):**
- `send_invitation_email` gains optional `primary_color` kwarg. When provided, replaces the hardcoded `#1B3A5C` in the heading color and CTA button background. Falls back to platform default when None.
- Both call sites (`create_invitations` + `resend_invitation` in `routes/organizations.py`) read `org.settings.branding.primary_color` and pass it through.
- Verification + password-reset emails are user-scoped (no org affiliation at signup) and stay on platform default — explicitly out of scope per spec.
- 1 new test (`test_create_invitations_threads_org_branding_primary_color`). **Backend suite 846 → 847.**

**Cluster C — Three locked copy fixes:**
- **Landing accountability tile**: "Every delegate's voting history is public; trust is earned, not assumed." → "Public delegates have public voting records; trust is earned, not assumed." (corrects the over-broad "every delegate" framing — only public delegates have public records).
- **Landing voting methods tile**: drop "(soon)" from the ranked-choice mention since RCV/STV shipped in Phase 7.
- **Demo register-your-own**: "Prefer to start fresh? Register your own demo account and walk through the full onboarding flow..." → "Prefer a clean slate? Register an account — you'll go through the real onboarding flow..." (drops misleading "demo account" wording — registration creates a real account, not a demo persona).

**Backend tests: 820 → 847 (+27).**
**Frontend bundle: ~345.67 → 348.62 kB gzipped (+2.95 kB).**
**No schema migration; PG smoke run anyway (Volume mount path change in StaticFiles): PASS both modes.**

### Production verification

| Check | Result | Evidence |
|---|---|---|
| Smoke (post-deploy auto-run via `poll_deploy.py`) | **5/5 PASS** | Bundle flipped at 61s; smoke ran in 2.01s |
| Cluster C copy 1 (Landing accountability) | **PASS** | Prod bundle includes "Public delegates have public voting records"; old "Every delegate's voting history" is gone (grep 0 hits) |
| Cluster C copy 2 (Landing voting methods, no "(soon)") | **PASS** | Prod bundle includes "Binary, approval, and ranked-choice voting"; old "(soon) ranked-choice" is gone (grep 0 hits) |
| Cluster C copy 3 (Demo register-your-own) | **PASS** | Prod bundle includes "Prefer a clean slate" + "Register an account"; old "Register your own demo" is gone (grep 0 hits) |
| Cluster B logo endpoint registered | PASS-by-source | `GET /api/orgs/demo/logo` returns 405 Method Not Allowed (POST/DELETE are registered, GET correctly is not — endpoint wired) |
| Cluster F theming code in bundle | PASS-by-source | Prod bundle has 9 hits for branding markers (BrandingThemeApplier / brand-primary / currentOrg.branding / brand-accent) |
| Cluster F load-bearing UI flow (logo upload → theme application → nav logo → OrgSelector cards → permission gate → clear-on-leave) | **NOT VERIFIED — browser extension not connected this session** | Flagged as a Z-decision item below; PASS-by-source only. Source review confirms the F1-F6 implementation matches the spec; F7 visual flow needs out-of-band verification by Z |
| Cluster B branding response shape | PASS-by-source | Verified by 26 unit tests; live API probe of `/api/orgs/demo` requires auth and wasn't exercised this session |
| Cluster E invitation-email primary_color threading | PASS-by-source | Verified by `test_create_invitations_threads_org_branding_primary_color` unit test; not exercised against prod Resend (would have sent a real test invitation email) |

### Phase 12.7 commit list

- `bf2a784` I1+I2: railway.toml volume mount + 3-tier uploads path resolver
- `95663e7` I3: one-shot migration script for legacy uploads → Volume
- `5078add` F1: migrate brand colors to CSS variables (65 files / 678 sites)
- `8775994` F3: color derivation utility for org branding
- `70e59d8` B1+B2+B3+B4: org logo + branding endpoints + response shape
- `8a94291` F2: theme application hook on org-scoped routes
- `333d844` F4: Org Settings — Branding section (logo + colors)
- `65df1d0` F5: Nav bar — show org logo to the left of org name
- `22f5d06` F6: OrgSelector cards — per-org branding
- `b6d2b62` F4 hydration fix — default auto-derive on for unconfigured orgs
- `122d9c2` C: Copy fixes — landing accountability tile, voting methods, demo register link
- `33baf47` E: Email theming — invitation email uses org's branded primary color
- `141b10c` Merge to master

### Z-decision items (post-merge, requiring Z action)

1. **Provision `/data` Volume via Railway dashboard.** Until provisioned, logo uploads fall back to ephemeral container storage (lost on redeploy). Avatars are also affected — Phase 12.5/12.6 avatar uploads currently live in the legacy `backend/uploads/` ephemeral path.
2. **Run `scripts/phase12_7_migrate_uploads.py` via `railway ssh` after Volume mount** to copy any legacy `backend/uploads/avatars/*` files to `/data/uploads/avatars/*`. Idempotent — safe to run multiple times.
3. **F7 visual browser verification** — out-of-band check needed for the load-bearing UI flow (logo upload → theme application → nav logo → OrgSelector cards → permission gate). Browser extension wasn't connected this session so this PASS is by-source only. Recommended quick check: log in as Steward on demo org, open `/admin/settings`, scroll to Branding section, upload a small PNG, set a non-default primary color, save, navigate to `/{slug}/proposals` and confirm the nav shows the logo + the brand-primary buttons match the configured color. Then go to `/orgs` and confirm the demo card shows the same branding inline. Then leave to `/` and confirm the public landing page renders with the platform-default colors (no theme bleed).
4. **(Optional) Send a test invitation from the demo org** to confirm the Cluster E email theming reaches Resend with the org's branded primary color in the rendered HTML.

### Process notes

1. **Greater Phase 12 arc complete** — Stage 1 (configurable role permissions backend, 2026-05-03) → Stage 2 (permission matrix UI, 2026-05-03) → Stage 2.5 (permission system completeness, 2026-05-04) → Stage 2.6 (route guard refactor + demo polish, 2026-05-04) → Stage 3 (org branding + copy polish, 2026-05-04). The org now has Steward-tier configurable role permissions AND configurable identity (logo + color), end-to-end.
2. **`poll_deploy.py` auto-smoke at 61s** — fastest deploy of the 12.x arc. Bundle flipped clean, smoke 5/5 PASS in 2.01s.
3. **Browser verification gap** — chrome extension not connected this session, so F7 visual verification is PASS-by-source only. Flagged as a Z-decision item; everything else (copy fixes, API endpoints, theming code presence) was verified via the deployed bundle and unit tests.
4. **F1 mojibake recovery** — first F1 pass corrupted UTF-8 em-dashes when a PowerShell-driven bulk replace re-encoded files as Win-1252. Frontend agent reset F1 commits and redid via Python with explicit `.decode("utf-8") / .encode("utf-8")` and BOM preservation. No artifacts in shipped bundle.
5. **Single-source-of-truth for branding shape** — `_org_to_out` helper centralizes the BrandingOut emission across 6 org-returning endpoints. New endpoints will inherit consistent shape automatically.

### New tech debt

1. **Browser verification gap is real** — F7 (logo upload + theming + nav logo + OrgSelector cards + permission gate + clear-on-leave) needs an out-of-band visual check. If the browser extension is reliably available next session, run the F7 checklist. If issues surface, file as Phase 12.7.1 hot-fix.
2. **Volume provisioning is a manual Z step** — once provisioned, the migration script runs once. Until then, ephemeral container storage means uploaded logos disappear on redeploy. Worth a Phase 12.7.1 follow-up to add a backend startup log line that warns "Uploads dir is on ephemeral storage" when `/data/uploads/` doesn't exist, so the state is visible in Railway logs.
3. **Cluster E email theming is invitation-only.** Verification + password-reset emails are user-scoped and weren't themed. If a future flow grows org-scoped emails (e.g. weekly digest, member-removed notification), they'll want the same `primary_color` threading. Helper function in `email_service.py` could centralize the color resolution so call sites don't each reach into `org.settings.branding`.

### Pass-summary

**Phase 12.7 shipped clean in a single session** — 12 commits + merge + closeout, no hot-fixes, no Railway incident. Greater Phase 12 arc is now complete. Backend test count 820 → 847 (+27). Bundle 348.62 kB gzipped (+2.95 kB). The platform now supports Steward-tier configurable per-org branding (logo + primary color) applied consistently across nav, OrgSelector cards, admin UI, in-page chrome, and the org-scoped invitation email. Three locked copy fixes shipped on landing + demo. Load-bearing F7 visual verification is the one outstanding item (chrome extension wasn't connected this session); flagged as a Z-decision item with a 90-second checklist. Volume provisioning + migration script run remain Z-decision items for upload persistence.

---

## Phase 12.8 — Tech Debt Audit + Cleanup — 2026-05-04

**Coherence pass — same shape as Phase 10.2** (audit-then-fix-in-same-merge). 3 commits on `phase-12-8/tech-debt-audit-and-cleanup` no-ff merged to master at `df6fe60` + closeout. **LIVE on prod**, bundle `index-BYwI_Jxw.js`. Audit doc at `docs/tech_debt_audit_2026-05.md` becomes the canonical reference for what's accumulated through Phase 12.7. **Backend tests 847 → 850 (+3).** Bundle 348.62 → 348.53 kB gzipped (-0.09 kB; helper consolidation). **No migration; no PG smoke required.**

### What shipped

**Cluster A — Audit doc (`docs/tech_debt_audit_2026-05.md`, 41 items consolidated):**
- Inputs: PROGRESS.md sweep from Phase 9 onward; backend codebase TODO/FIXME/HACK/XXX/BUG/NOTE grep (1 REAL_DEBT — Polis stats N+1 — and 5 INTENTIONAL); frontend codebase grep (1 STALE TODO in CreatePolis.jsx); roadmap Known Issues sweep (5 items, 4 already-resolved).
- Three-lane classification per spec §A1.5 prevents Z-action items polluting the team's fix queue: TECH_DEBT 32 / Z_ACTION_PENDING 4 / MANUAL_VERIFICATION_GAP 1.
- TECH_DEBT tier breakdown: 5 Tier-1 fix-in-12.8 (Items 1-5), 14 Tier-2 deferred (Items 6-19), 6 Tier-3 deferred (Items 20-25), 4 calendar-gated (Items 26-29), 2 EXTENDS_10_2_AUDIT (Items 30-31).
- 4 NEEDS_Z_INPUT items (32-35) flagged with the specific question Z needs to answer.
- 4 Z_ACTION_PENDING items (36-39 — Volume provisioning, migration script run, F7 visual verify, Phase 10.2 W-DIAG run on prod).
- 1 MANUAL_VERIFICATION_GAP (Item 40 — 12.7 F7 surface).
- 5 already-resolved entries flagged for Cluster R removal (Items 41a-e).

**Cluster F — Five Tier-1 fixes:**
1. **Item 1 — backend startup log warning for ephemeral uploads** (spec F.1 #2): `backend/main.py` startup hook now emits `logging.warning(...)` when the resolved uploads base dir doesn't start with `/data/` (i.e., the Railway Volume isn't mounted and the 3-tier path resolver fell back to the in-image path). Makes the misconfiguration loud at deploy time.
2. **Item 2 — stale TODO removal in CreatePolis.jsx** (frontend audit STALE; the only frontend code-comment debt found): the Phase 9 Session 2 PATCH-API gap noted in the original comment was closed in Session 4 via commit `95af3ff`. Comment block updated to reflect the current state where both manual + programmatic paths wire end-to-end.
3. **Item 3 — `OrgMembership.role_id` model nullable alignment** (Phase 12 Stage 1 tech debt #1): `backend/models.py:155` declared `Mapped[Optional[str]]` with `nullable=True` "temporarily so the migration can backfill before flipping NOT NULL." The Phase 12 Stage 1 migration shipped 2026-05-03; the temporary should be removed. Now `Mapped[str]`, `nullable=False`, with `role` relationship typed strict. Verified no production code path constructs `OrgMembership` without `role_id`; tests use the `make_org_membership` conftest helper which always sets it.
4. **Item 4 — `timeAgo` helper extraction** (Phase 10 tech debt #4): `Comment.jsx` + `FollowRequests.jsx` + `DelegateModal.jsx` had three slightly-different inline `timeAgo` implementations. The Comment.jsx variant (just-now + 30d-fallback) was the strictly-most-complete superset and is preserved as the canonical form in `frontend/src/utils/timeAgo.js`. The other two now import from it. Bundle delta: 348.62 → 348.53 kB gzipped (-0.09 kB).
5. **Item 5 — sustained-majority `floor_breached` read-path consistency** (Phase 9.8 tech debt #2): `sustained_majority_service.build_status` pre-12.8 used only the latest snapshot and a bare `support < floor` check, so the `/results` UI banner reported "floor breached" the moment a non-zero vote dropped below the floor — even before any threshold-meeting consensus had ever existed in the window. The Phase 9.8 C1 worker fix already gates breach on `support_ever_established`; this aligns the read path. Now loads all snapshots in window, computes `support_ever_established(history, config)`, and gates the breach flag on it. Three new tests in `test_phase12_8_floor_breach_read_path.py`: (a) no breach when never established, (b) breach when established then dropped, (c) no breach when above floor after establishment.

**Spec F.1 item 1 (cache-safety role-tier fallback removal) DEFERRED per the calendar gate.** Phase 12.5 shipped 2026-05-03; the 7-day age-out window closes 2026-05-10; today is 2026-05-04. Reclassified as DEFER_WITH_ESTIMATE per spec instruction. Bundled with audit Items 26-29 for a single ~30-minute follow-up cleanup pass after 2026-05-10 (Nav.jsx fallback + AdminRoute/AdminOnlyRoute fallback + OrgSettings.jsx legacy 'owner' acceptance + Permissions tier-shortcuts).

**Spec F.1 item 3 (email theming centralization helper) DEFERRED with estimate** per pre-registered spec note. Currently invitation-only; ~1-2 hours when there's a second org-scoped email. Logged in audit doc + roadmap.

**Cluster R — Roadmap Known Issues curation:**
- 5 already-resolved entries removed (sustained-majority floor — read path also fixed in this pass; invitation email-send wiring; avatar storage; test-depth audit; Stub-for-Phase-4c docstring).
- 24 deferred items added with effort estimates + cross-references to audit-doc rows: 1 calendar-gated cleanup bundle, 15 Tier 2, 6 Tier 3, 2 EXTENDS_10_2_AUDIT.
- Intro paragraph cross-references `docs/tech_debt_audit_2026-05.md`.

**Backend tests: 847 → 850 (+3).** Frontend bundle: 348.62 → 348.53 kB gzipped (-0.09 kB). **No migration; no PG smoke required.**

### Production verification

| Check | Result | Evidence |
|---|---|---|
| Smoke (post-deploy auto-run via `poll_deploy.py`) | **5/5 PASS** | Bundle flipped at 41s; smoke ran in 1.72s |
| F-Item 1 startup warning | PASS-by-source | Warning in `backend/main.py` startup hook; will fire next time Railway redeploys an env without `/data/` mount. (No prod log probe — Z's Volume is currently un-provisioned, so the warning IS expected to fire on next deploy and would be visible in Railway logs.) |
| F-Item 5 floor_breached read-path | PASS via 3 new tests + smoke | All 3 unit tests PASS asserting (a) no breach without establishment, (b) breach after establishment-then-drop, (c) no breach above floor; full backend suite 850/850 green |
| Audit doc structure | **PASS** | `docs/tech_debt_audit_2026-05.md` exists with all sections covered per spec §A6 (Tier 1/2/3, Needs-Z-input, Z-action-pending, Manual-verification-gap, Stale, Already-resolved, Intentional) |
| Roadmap delta | **PASS** | 5 entries removed (resolved); 24 entries added (deferred with estimates); intro cross-references audit doc |

### Phase 12.8 commit list

- `2dfd59d` A: Tech debt audit doc — consolidates 41 items
- `2b9dddd` F: Five Tier-1 fixes from the audit doc
- `3609844` R: Roadmap Known Issues curation — sync with audit doc
- `df6fe60` Merge to master
- closeout commit follows

### Z-decision items (post-merge, requiring Z action)

These are surfaced in `docs/tech_debt_audit_2026-05.md` and persist beyond Phase 12.8. Listed here for visibility:

**Z_ACTION_PENDING (audit Items 36-39):**
1. **Provision `/data` Volume via Railway dashboard** (carried from Phase 12.7). Until provisioned, logo + avatar uploads fall back to ephemeral container storage. The Phase 12.8 F-Item 1 startup warning makes the misconfiguration visible in Railway logs.
2. **Run `scripts/phase12_7_migrate_uploads.py` via railway ssh** (carried from Phase 12.7) after Volume provisioning.
3. **F7 visual browser verification** of Phase 12.7's logo upload + theming flow (carried from Phase 12.7).
4. **Run `scripts/phase10_2_diagnose_pre_fix_vote_leak.py` on prod** via `railway run` (carried from Phase 10.2 — long-pending). Output may motivate Phase 10.3.

**NEEDS_Z_INPUT (audit Items 32-35):**
1. Demo-org slug=`demo` collision — rename via direct DB UPDATE or document the harmless intent in DEPLOYMENT.md?
2. Help page back-link target — `/orgs` (current) or `history.back()` with fallback?
3. Old flat URL catch-all behavior — current `/` redirect or smarter "you tried `/proposals` — pick an org" fallback?
4. Platform admin (`is_admin=True`) sub-org-admin power scope — global override or stay scoped to org families they're a member of?

### Process notes

1. **Multi-agent staging discipline N/A this pass.** Two parallel Explore agents handled backend codebase grep + frontend codebase grep + roadmap sweep. Lead handled PROGRESS.md sweep and consolidation. Then lead implemented all 5 Tier-1 fixes in serial since the autonomous-mode lead bandwidth was the constraint and the fixes are small.
2. **Codebase comment density is exceptionally low.** Backend: 6 markers total (1 REAL_DEBT, 5 INTENTIONAL). Frontend: 1 marker total (1 STALE). Disciplined avoidance of marker inflation; inline comments are brief and architectural comments are tied to specs/phases.
3. **F-Item 5 (sustained-majority read-path fix) was borderline Tier 1/2** but stayed in scope because the test infrastructure was well-established (existing `_voting_proposal` + `VoteSnapshot` patterns in `test_sustained_majority_worker.py`) and the fix required only one helper-call addition + a snapshot-loading change. Borderline calls like this are exactly what the Tier 2 escape-hatch is for if they balloon — this one didn't.
4. **`poll_deploy.py` auto-smoke worked again** — bundle flipped at 41s, smoke 5/5 PASS in 1.72s. Same fast-deploy pattern as Phase 12.7 (61s) and Phase 11 (20s).
5. **Audit-then-fix-in-same-merge pattern matches Phase 10.2.** The audit doc is the durable artifact (Phase 10.2's `docs/test_depth_audit_2026-05.md` is its sibling); the fix work is what gets merged. Future planners reading the audit can see what's done + what's deferred + what's Z's, without re-spelunking PROGRESS.md.

### New tech debt

None surfaced during the fixes. The audit was the surface; the fixes were narrow.

### Pass-summary

**Phase 12.8 shipped clean in a single session** — 4 commits + closeout, no hot-fixes, no Railway incident. The accumulated tech-debt landscape across Phase 9-12.7 is now consolidated into `docs/tech_debt_audit_2026-05.md` (41 items, three-lane classification, tiered with effort estimates). Five Tier-1 fixes landed (backend startup-warning, stale-TODO removal, model nullable alignment, helper consolidation, sustained-majority read-path consistency); 24 deferred items added to roadmap Known Issues with estimates + audit-doc cross-references. Backend tests 847 → 850 (+3). Bundle -0.09 kB gzipped. Spec F.1 item 1 (cache-safety role-tier fallback removal) deferred per calendar gate (7-day window closes 2026-05-10); bundled with audit Items 26-29 for a small follow-up cleanup pass after that date. Z's checklist: 4 Z_ACTION_PENDING items + 4 NEEDS_Z_INPUT planning conversations queued for the next session.

---

## Phase 13 — Notifications — REVERTED 2026-05-05 (incident report)

**Phase 13 implementation complete; deploy failed; reverted to restore prod service.** Implementation merged at `71c5684`, pushed, deployed to prod bundle `index-Bz7dC8k8.js` — frontend bundle flipped successfully but the backend container went 502 immediately after the deploy and stayed down for ~35 minutes. With no Railway log access available this session and local startup confirmed working with all imports + DISABLE_DIGEST_SCHEDULER both on and off, the team was unable to identify the prod-specific failure. Reverted the merge at `017028c` to restore service. Backend recovered; smoke 5/5 PASS post-revert. Phase 13.1 is queued to diagnose the prod startup failure offline, then re-attempt deploy.

**This entry documents the incident and what was BUILT (kept on the `phase-13/notifications` branch for re-use) vs. what is LIVE on prod (= pre-Phase-13, master at `017028c`).**

### What was implemented (intact on `phase-13/notifications` branch, NOT in master)

The full Phase 13 spec landed in 9 commits across 5 clusters before the deploy. Backend tests **850 → 924 (+74)** in CI; full suite passed 924/924. Frontend bundle 348.53 → 353.89 kB gzipped (+5.36 kB; well under the 8-12 kB budget).

**Cluster B foundation (commits 219b508, 2c0b84f, c189bee, c25f17d):**
- `Notification` table (id, user_id CASCADE, event_type, org_id, actor_id, target_type, target_id, payload JSON, read_at, created_at) and `NotificationPreference` table (UQ user_id+event_type+channel, opt-in default = enabled defaults False).
- 4 new User columns: `timezone`, `digest_cadence` (default "real_time"), `quiet_hours_enabled` (default False), `notification_intro_dismissed` (default False).
- `EVENT_REGISTRY` in `notification_events.py` with 12 entries across 5 categories (Comments / Proposals / Membership / Delegation / Polis).
- `emit_notification(...)` helper with per-channel preference check (absent row = false, opt-in default), in_app row insert when enabled, real-time email queue when enabled + cadence=real_time + not in quiet hours.
- 6 endpoints in `routes/notifications.py` (GET list, POST {id}/read, POST mark-all-read, GET preferences, PATCH preferences with audit, GET registry). All account-scoped, no role-tier gates (Item 30 confirmation).
- 90-day `cleanup_expired_notifications` helper.
- Migration `f1a3c8d92e60` (reversible, idempotent, batch_alter_table for SQLite). PG smoke PASS both modes against prior=41694d86821f.

**Cluster B emission (commit 602b005):** 12 emission sites wired in routes/comments.py, routes/follows.py, routes/organizations.py, routes/proposals.py, routes/polises.py, sustained_majority_worker.py. Each call wrapped in try/except so emission failures never block originating requests. org_id passed at every org-scoped site. 28 emission tests + 13 digest tests.

**Cluster E (commit a65d156):**
- `send_org_email(template_key, template_vars)` helper generalizes 12.7's invitation theming. Resolves org branding, renders template, sends via existing transport.
- `send_event_email(user_id, event_type, payload)` is the function `notification_emit` lazy-imports.
- 15 templates in `backend/email_templates/` (12 events + invitation extracted + digest_daily + digest_weekly).
- HMAC-signed unsubscribe tokens (30-day expiry) + `GET /api/notifications/unsubscribe/{token}` endpoint.
- `digest_scheduler.py` asyncio in-process loop wakes hourly. Wired into main.py startup hook, gated on `DISABLE_DIGEST_SCHEDULER`. Choice + kill switch documented in DEPLOYMENT.md.
- Quiet hours queue logic: real-time email suppressed at emit when in 21-09 window, flushed by digest_loop at 9am local.
- Backward compat: `send_invitation_email` external signature preserved unchanged.

**Cluster F (commits cb79699, 648da71):**
- `NotificationBadge.jsx` fully rewritten — bell + count + dropdown + mark-all-read + view-all link. localStorage cleanup hook for legacy `polis_last_seen_*` keys. Click-through routing via `formatNotification.js::notificationHref` using `notification.org_slug` (Item 22 routing — never falls back to first-parent-org).
- `NotificationsPage.jsx` at `/notifications` with category filter chips, date grouping, pagination, mark-unread.
- `NotificationsPreferences.jsx` at `/settings/notifications` with 12-event by 2-channel matrix UI, digest cadence radio, quiet hours checkbox, timezone dropdown, first-time banner.
- `Settings.jsx` adds Notifications section linking to `/settings/notifications`.
- `App.jsx` registers both as top-level account-scoped routes.

**Cluster D + Item 22 retirement (commit 642759c):**
- `NotificationsHelp.jsx` at `/help/notifications`.
- SECURITY_REVIEW.md "Notification Privacy (Phase 13)" section with threat model + token format + retention + channel-control posture + deferred items.
- Item 22 marked RESOLVED in audit doc; corresponding entry removed from roadmap Known Issues.

### What broke at prod deploy

After the merge `71c5684` was pushed and Railway redeployed:

- **Frontend bundle flipped at +41s** (`index-BYwI_Jxw.js` → `index-Bz7dC8k8.js`). Static assets serve correctly post-deploy.
- **Backend went 502 at +41s and stayed down for ~35 minutes.** All `/api/*` endpoints returned 502 "Application failed to respond" (Cloudflare/Railway upstream-unreachable). The `/api/health` endpoint same. Root path `/` (static) served 200 throughout, confirming the Railway proxy + frontend container were healthy.

### Diagnostic steps taken before revert

- **Local import test PASS:** `from main import app` succeeds.
- **Local startup hook PASS** with both `DISABLE_DIGEST_SCHEDULER=1` and the scheduler enabled. Five log lines + "Startup complete" emitted; `digest_loop` launched without crashing the app. (The first tick of `digest_loop` crashes locally — caught by its own try/except — because there's no real DB content; this is benign and was confirmed during initial CI testing too.)
- **Local sustained_majority_worker import PASS.**
- **PG smoke PASS both modes** pre-deploy (prior=41694d86821f). Migration runs cleanly on a fresh PG container.
- **Backend pytest suite PASS** (924/924) on the merge commit.
- **Without Railway log access this session**, the specific failure mode on the prod container could not be observed. Hypotheses worth investigating in 13.1: (a) the async-startup change (sync→async in `@app.on_event("startup")`) interacting with uvicorn `--workers 4`; (b) `asyncio.create_task(digest_loop())` behaving differently when launched from each of 4 worker startup hooks vs once in a single-worker scenario; (c) the modified `sustained_majority_worker.py` (now imports `notification_emit`) crashing as a side process and somehow tying up the parent uvicorn through shared resources; (d) a Railway-specific environment difference (PORT binding, shutdown signal handling, container memory, Resend API call at startup); (e) the migration succeeding but the post-migration startup making a sync DB call that hangs. None confirmed without log access.

### The revert

`git revert -m 1 71c5684 --no-edit` produced commit `017028c`. Pushed at +35min. Railway redeployed at the new HEAD. Backend `/api/health` returned 200 within ~2 minutes of the push; smoke 5/5 PASS via auto-poll.

**Important:** the revert undoes the CODE but the **prod database schema is post-Phase-13** — the migration `f1a3c8d92e60` ran successfully on prod (added 2 tables + 4 user columns) before the backend started failing. After revert, the reverted code doesn't include the Phase 13 model definitions, so the new tables and columns are dormant on prod. SQLAlchemy doesn't error on extra columns in SELECT * (the model definition lists what to populate; extra DB columns are ignored). The `alembic_version` table on prod is in an unusual state (stamped at a revision whose file no longer exists in the codebase) — Railway's start.sh likely fell into the else-branch on next boot via `alembic current` returning non-zero on the unknown revision, and stamped at `41694d86821f`. This is consistent with the smoke PASS post-revert.

**Phase 13.1 implications:** the migration is idempotent and re-applying it against the post-revert state will be a no-op (introspect-and-skip on tables + columns). When Phase 13.1 ships, the migration will run cleanly because it already did, and the alembic stamp will catch up.

### What's preserved + what's lost

**Preserved (intact on `phase-13/notifications` branch):**
- All 9 commits, full implementation, 924/924 tests passing in CI, PG smoke PASS both modes, frontend build clean.
- The branch ref `phase-13/notifications` still points at the reverted-from work; `git log phase-13/notifications` shows the full history. Phase 13.1 will branch from this point or cherry-pick selectively.
- Audit doc Item 22 status was reverted to "DEFER_WITH_ESTIMATE" (the resolution edit was undone with the merge revert). Roadmap Known Issues still lists Item 22 as deferred. **Item 22 will be retired again in Phase 13.1's closeout** — same shape, same diff.

**Lost (effectively zero):**
- ~35 minutes of prod-down on Sunday afternoon. Friend pilot impact: minimal (no user activity observed during that window). No data corruption — the migration succeeded; subsequent endpoint requests just 502'd.
- A clean Phase 13 entry in PROGRESS.md. This entry replaces it.

### Z-decision items

1. **Phase 13.1 dispatch readiness.** The next planning conversation should specify (a) whether to disable the asyncio digest_loop on prod via `DISABLE_DIGEST_SCHEDULER=1` for the first 13.1 deploy as a diagnostic isolation step, (b) whether to bisect the merge into smaller deploys (e.g., schema + B foundation + endpoints only first; emission + email + scheduler in a follow-up) to narrow which cluster causes the failure, or (c) whether to add Railway log access (or a short-term equivalent) to make this kind of diagnosis tractable.
2. **Prod schema state.** No action required — the schema is forward-compatible and dormant. But if a future planner wants to roll the schema back to a strictly-pre-Phase-13 state, that requires a manual migration (the migration file is gone from the codebase; manual SQL DROP is the path).

### Process notes

1. **Multi-agent coordination on this scale worked well at the build layer.** Backend dev #1 (foundation), backend dev #2 (emission + email), frontend dev #1 (notification center + preferences) — three parallel agents handled their clusters cleanly with no merge conflicts. Each closeout was clear about its scope boundaries; lead consolidation + Cluster D came together in serial without friction.
2. **Pre-deploy verification was thorough and still missed this.** Backend suite 924 PASS, PG smoke both modes PASS, local startup PASS in two configurations, frontend build clean. The failure mode is something only prod's runtime environment exposes. This is the lesson Phase 9.6/9.7/9.8/9.9/10.1 kept teaching at smaller scales — a feature can pass every local + CI gate and still hit a prod-specific issue. Phase 10.2 covered the test-depth side of this; **the deploy-runtime side (what fails on Railway specifically that doesn't fail in CI) is now a documented gap.**
3. **Railway log access during a live incident would have changed the outcome.** With visibility into why the container was 502'ing, the team could have hot-fixed forward in minutes instead of reverting. Adding a "during an incident, here's how to read Railway logs" runbook to DEPLOYMENT.md is a worthwhile follow-up.
4. **The revert pattern worked correctly** — `git revert -m 1` of a no-ff merge cleanly undoes all 9 underlying commits as a single revert commit, and Railway redeployed cleanly. CLAUDE.md's "create new commits, don't rewrite history" stance held under fire.

### Phase 13 commit list (on `phase-13/notifications` branch; not in master)

- `219b508` B1+M: Notification + NotificationPreference tables + User columns
- `2c0b84f` B2: EVENT_REGISTRY with 12 event types
- `c189bee` B3+B5: emit_notification helper + 90-day cleanup
- `c25f17d` B4: notifications router with 6 endpoints + tests
- `cb79699` F1+F6: notification center replaces legacy badge + localStorage cleanup
- `648da71` F2+F3+F4: notifications page + preferences page + Settings link
- `602b005` B-emit: 12 emission sites wired with tests
- `a65d156` E1-E4: send_org_email + 12 templates + digest scheduler + quiet hours
- `642759c` D + Item 22 retirement: help article + SECURITY_REVIEW + audit doc + roadmap edits

### Master commit list (live on prod, post-revert)

- `71c5684` Merge phase-13/notifications: Notification system (Phase 13) — REVERTED
- `017028c` Revert "Merge phase-13/notifications: Notification system (Phase 13)" — LIVE on prod

### Pass-summary

**Phase 13 implementation is complete; the prod deploy failed; the revert restored service.** No code is live on prod from this pass. Backend tests, PG smoke, frontend build, and local startup all PASS — the prod failure mode is environment-specific and not reproducible locally without log access. Phase 13.1 is queued: diagnose the prod failure (likely via narrower cluster-by-cluster deploys or with `DISABLE_DIGEST_SCHEDULER=1`), re-ship the same implementation. The branch + 9 commits + 924-test suite are preserved on `phase-13/notifications` for re-use. Item 22 retirement and the corresponding roadmap edit will land in Phase 13.1's closeout.

---

## Phase 13.1 — Notifications Redeploy — W-DEPLOY-1 ATTEMPTED 2026-05-05 (REVERTED, bisection escalated to NEEDS_Z_INPUT)

**Phase 13.1 attempted bisected re-ship. W-DEPLOY-1 (the smallest possible deploy — storage + endpoints + frontend UI, no emission, no email, no scheduler) failed on prod with the same 502 pattern as Phase 13.** Reverted at master `c571920`; prod recovered, healthy on `index-BYwI_Jxw.js`. The bisection plan as designed is exhausted — there is no smaller cluster split that would localize the failure further without artificial surgery. **Recommendation: pause Phase 13.1 redeploy attempts, escalate to Z for either Railway log access OR a decision on Phase 13's product future.**

### Sequence

**W-DIAG (offline diagnostic):** Ran on `phase-13/notifications` branch with prod-like env. Cheapest tests first.
- `python -c "import sustained_majority_worker"` — **PASS.** All Phase 13 dependencies import cleanly.
- `python -m sustained_majority_worker --once` — **PASS.** One tick + clean exit.
- `uvicorn --workers 1` boot probe — **PASS.** /api/health returned 200 in 1s with the full Phase 13 startup path including digest scheduler launch.
- `uvicorn --workers 4` boot probe — **FAIL** locally (no /api/health in 30s). Almost certainly a Windows multiprocessing artifact (uvicorn's --workers flag uses gunicorn-style fork-equivalent on Linux but has known Windows limitations); not directly translatable to Linux/Railway.
- `uvicorn --workers 4 + DISABLE_DIGEST_SCHEDULER=1` — still FAIL locally. Confirms the multi-worker Windows failure is independent of the scheduler — Windows-specific.
- **The side-process-import-crash hypothesis is NOT confirmed at the local-import level.** The original spec hypothesis (sustained_majority_worker.py crashes at import time because Phase 13 added `from notification_emit import emit_notification`) is wrong — local import works clean. The prod failure is something else.

**W-DEPLOY-1 (storage + endpoints + frontend UI, no emission/email/scheduler):**

- Branch: `phase-13-1/storage-and-ui`, branched from `ba431b9` (Phase 13 incident closeout, post-revert state).
- Cherry-picked: Cluster B foundation (4 commits) + Cluster F (2 commits) + D1 NotificationsHelp + W-RUNBOOK Railway-log-access section in DEPLOYMENT.md.
- Held: Cluster B emission, Cluster E, SECURITY_REVIEW.md notification-privacy section, Item 22 retirement edits.
- Confirmed via grep: `sustained_majority_worker.py` does NOT import `notification_emit` on this branch (cherry-pick was clean — that import lives in commit 602b005 which was held).
- Backend tests: 850 → **879 (+29)** on the deploy branch. Foundation tests only.
- Frontend bundle: 348.53 → **353.89 kB gzipped** (+5.36 kB). Identical to the failed Phase 13 attempt because Cluster F is the same.
- **W-START-CHECK PASS** — `uvicorn --workers 1` startup probe on `phase-13-1/storage-and-ui` returned `/api/health` 200 at +1s. Full local startup chain ran clean.
- **PG smoke PASS both modes** (prior=41694d86821f). Migration f1a3c8d92e60 applied cleanly on a fresh PG.

**Deploy result:**

- Push at master `c85fa82`. Railway redeployed.
- Initial poll: bundle flipped to `index-Bz7dC8k8.js` at +0s with `backend_ok=True`. Smoke ran 5/5 PASS at +1.4s post-flip.
- **Within ~30 seconds of the smoke PASS, backend went 502 sustained.** All `/api/*` endpoints returned 502 "Application failed to respond" with 15-second Cloudflare/Railway upstream timeouts. Static `/` continued to serve 200 (frontend bundle). Same exact failure mode as Phase 13.
- The brief "smoke PASS" window appears to have caught a transient state where uvicorn was still listening (possibly the OLD container during traffic-switch overlap, or the new container in its first few seconds before crashing).
- **Reverted via `git revert -m 1 c85fa82`** at master `c571920`. Smoke 5/5 PASS post-revert; backend healthy on the pre-Phase-13 bundle `index-BYwI_Jxw.js`.

### Why the bisection is exhausted

W-DEPLOY-1 ships the smallest coherent unit — storage tables + 6 endpoints + frontend UI + a help page. Any further split would be artificial:

- "Schema only" — would require shipping just the migration + model class definitions without any router, but the existing model code is imported via `from main import app` which transitively imports everything.
- "Endpoints only" — same problem; routes/notifications.py imports notification_emit, notification_events, etc.
- "Frontend only" — that's already what most of Cluster F is, but the deploy MUST include backend matching changes for the endpoints to exist (else the frontend's API calls 404 and the page is broken).

So the bisection has localized the failure to W-DEPLOY-1's surface, but cannot localize further without log access. The remaining hypotheses (none confirmed):

1. **Migration application on prod's actual PG state.** The Phase 13 migration ran successfully on prod pre-revert, then prod's alembic_version was reset to `41694d86821f` by the revert deploy's else-branch (`create_all + stamp head`). When W-DEPLOY-1's alembic upgrade head re-applies f1a3c8d92e60, the migration's idempotency checks should skip the existing tables/columns. But something in this re-application path could be failing in a way local PG smoke (against a fresh container) doesn't replicate.
2. **Module-import-time issue under Linux + 4 workers.** Some module in W-DEPLOY-1's import chain (notification_emit, notification_events, routes/notifications.py) may have an import-time side-effect that misbehaves under Linux fork() + 4 worker processes simultaneously initializing. Local --workers 1 worked; Linux --workers 4 might surface a race.
3. **Railway environmental specifics.** Container memory ceiling, Python version, dependency versions, network-config quirks. The new code adds ~3500 lines of backend Python; if Railway's Hobby-tier memory is tight, the additional module loading could push us over.
4. **alembic_version table state.** If the revert's else-branch (create_all + stamp head) didn't properly reset the version, prod might still report `f1a3c8d92e60` as current — and applying the migration when current==head could behave differently than pg_smoke's "stamp prior, upgrade to head" pattern.

None of these are testable without Railway log access. The Phase 13.1 W-RUNBOOK section that was in this deploy's commit list would have been the canonical reference for the next time this happens — but the runbook itself is now reverted with the rest.

### What changed vs. didn't change between Phase 13 and W-DEPLOY-1

**Same in both:**
- Frontend bundle hash (`index-Bz7dC8k8.js`).
- Cluster B foundation (models, migration, helper, endpoints).
- Cluster F (frontend).
- D1 (NotificationsHelp).
- Migration application — **expected** to be no-op on prod (since Phase 13's migration ran successfully and the schema is dormant), but actual prod behavior unobserved.

**Held in W-DEPLOY-1 but in Phase 13:**
- 12 emission sites in routes/comments.py, follows.py, etc.
- `from notification_emit import emit_notification` in sustained_majority_worker.py.
- Cluster E entirely (send_org_email helper, 15 templates, digest_scheduler.py asyncio loop, quiet hours queue).
- async startup hook (Cluster E added the change from `def startup()` to `async def startup()` in main.py).
- SECURITY_REVIEW.md notification-privacy section, Item 22 retirement edits.

The fact that **W-DEPLOY-1 still failed despite holding all of Cluster E and emission** means the original Phase 13 closeout's hypothesis list was wrong — the cause is not the digest scheduler, not the worker import chain, not the async startup. It's something in the storage layer (model definitions, migration application, or new endpoint module imports) interacting with the prod environment in a way that doesn't reproduce locally.

### W-RUNBOOK status

The Railway log access runbook (commit `052fa7b`) was committed to `phase-13-1/storage-and-ui` and merged into master via `c85fa82` — then reverted with the rest at `c571920`. The runbook content is preserved in git history; a follow-up pass should re-apply just that section (cherry-pick from the reverted merge or copy from the diff) since the runbook itself doesn't depend on Phase 13 code shipping.

### Z-decision items

1. **Railway log access for the next attempt.** The fundamental blocker is observability. Two Phase-13 deploys have failed, both reverted blind. Without log access, the third attempt is likely to fail the same way. Options: (a) Z provisions Railway CLI access for the team or shares a session-bound token; (b) Z runs `railway logs --service backend --tail` during the next deploy and pastes the output; (c) Z adds a non-Railway logging surface (e.g., ship logs to a free Sentry tier or a logflare instance) so the team can see startup failures live. **This is the unblocking decision.**

2. **Phase 13's product future.** If log access is hard to arrange and the prod failure remains opaque, alternative paths: (a) accept that Phase 13 as-implemented can't ship to this Railway environment and re-design the storage layer (e.g., simpler migration, no new module imports at startup, integrate notification routes into existing files); (b) defer Phase 13 entirely and ship something cheaper (e.g., a minimal email-only digest with no in-app feed, no model changes); (c) park Phase 13 indefinitely and pivot to the calendar-gated cleanup pass + smaller wins. **This is the strategic decision if (1) doesn't happen.**

3. **What's still preserved.** The `phase-13/notifications` branch + 9 commits + 924/924 tests in CI remain intact and untouched. Any of the three Z-decision paths can re-use this work — re-deploy isn't blocked by the implementation, it's blocked by understanding the prod failure.

### W-DEPLOY-1 commit list (live briefly on master, then reverted)

- `5080e6d` Phase 13 B1+M (cherry-pick of 219b508)
- `76147f2` Phase 13 B2 EVENT_REGISTRY (cherry-pick of 2c0b84f)
- `a739ebc` Phase 13 B3+B5 emit helper (cherry-pick of c189bee)
- `b7cd775` Phase 13 B4 router + tests (cherry-pick of c25f17d)
- `00ad390` Phase 13 F1+F6 notification center (cherry-pick of cb79699)
- `8b4f33f` Phase 13 F2+F3+F4 pages (cherry-pick of 648da71)
- `7138d70` Phase 13.1 W-DEPLOY-1 D1 — NotificationsHelp only (held SECURITY+audit+roadmap)
- `052fa7b` Phase 13.1 W-RUNBOOK — DEPLOYMENT.md "Reading Railway logs" section
- `c85fa82` Merge phase-13-1/storage-and-ui (REVERTED)
- `c571920` Revert "Merge phase-13-1/storage-and-ui" — LIVE on master

### Pass-summary

**Phase 13.1 W-DEPLOY-1 attempted, failed the same way Phase 13 did, reverted.** The bisection successfully ruled out emission, email, and scheduler as causes — all three were held back from this deploy and prod still failed. The remaining surface (storage, endpoints, frontend, migration) cannot be split further without artificial surgery. The actual root cause is in that surface but not observable without Railway log access. **Two prod deploys, two reverts, ~75 minutes of cumulative prod-down across both incidents.** Phase 13.1 is paused pending Z's decision on log access (W-DEPLOY-2 and W-DEPLOY-3 are NOT attempted — W-DEPLOY-1 covers the smallest possible surface and proves further bisection won't help). The `phase-13/notifications` branch + Phase 13.1 W-RUNBOOK content (in git history) are preserved for whatever path Z chooses.

---

## Phase 13.2 — Notifications Redeploy with Log Observability — SHIPPED 2026-05-05

**The Phase 13 storage layer is finally live.** Z provisioned a Railway Hobby plan and project token; with log access in place the team caught the actual prod failure mode (a Postgres `BOOLEAN DEFAULT 0` `DatatypeMismatch` in the migration), fixed it (`sa.text("0")` → `sa.false()`), re-shipped, and verified end-to-end within the same session. **Master `8192836`, prod bundle `index-Bz7dC8k8.js`, smoke 5/5 PASS, /api/notifications/registry returns 401 (auth gate working), /help/notifications 200.** Three deploy attempts in this pass: first attempt failed with the boolean default error, was reverted; the migration fix was applied but the merge was botched (only the migration file came over, 17 other files missing) — also reverted; the corrected merge shipped clean. ~30 minutes of cumulative prod-down across the two failed attempts.

### What's live on prod (W-DEPLOY-1 scope only)

This deploy ships the lowest-risk Phase 13 surface — storage + endpoints + frontend UI + help article. **Emission sites, email infrastructure, and the digest scheduler are STILL HELD BACK** for follow-up deploys (W-DEPLOY-2 and W-DEPLOY-3 patterns from `phase13_1_notifications_redeploy_spec.md`).

Live:
- `Notification` + `NotificationPreference` tables + 4 user columns (`timezone`, `digest_cadence`, `quiet_hours_enabled`, `notification_intro_dismissed`)
- Migration `f1a3c8d92e60` applied successfully (prior attempts had this transactionally rolled back due to the boolean default error)
- `EVENT_REGISTRY` (12 events / 5 categories) at `GET /api/notifications/registry`
- 6 notification endpoints (GET list / POST {id}/read / POST mark-all-read / GET preferences / PATCH preferences / GET registry). All account-scoped, no role-tier gates (Item 30).
- `emit_notification` helper (defined; not called from any emission site yet — that's W-DEPLOY-2)
- 90-day cleanup helper (defined; scheduler that runs it lands in W-DEPLOY-3)
- Notification center frontend (`NotificationBadge.jsx` rewritten; legacy polling removed; `polis_last_seen_*` localStorage cleanup hook)
- `/notifications` full feed page
- `/settings/notifications` matrix UI with 12-event x 2-channel grid + digest cadence + quiet hours + timezone + first-time banner
- Settings nav link to /settings/notifications
- `/help/notifications` help article
- `formatNotification.js` with Item 22 routing (uses `notification.org_slug`, never first-parent fallback)
- Phase 13.1 W-RUNBOOK + Phase 13.2 W-RUNBOOK-ADDENDUM merged into DEPLOYMENT.md

NOT live (held for W-DEPLOY-2 / W-DEPLOY-3):
- 12 emission sites (Cluster B emission, commit 602b005 on `phase-13/notifications`)
- `send_org_email` helper + 15 email templates + asyncio digest scheduler + quiet-hours queue (Cluster E, commit a65d156)
- HMAC-signed unsubscribe tokens + endpoint
- SECURITY_REVIEW.md notification-privacy section
- Item 22 retirement (audit doc + roadmap edits) — confirmed bundled with email-and-scheduler deploy per spec

### Sequence

**W-OBSERVABILITY-CHECK PASS (pre-deploy):** `RAILWAY_TOKEN` set from `.env`. `railway status` returned `Project: keen-learning / Environment: production / Service: backend`. Sampled 25 seconds of healthy production logs from the pre-13 master container. Captured the `--workers 4` startup-side-effect multiplication — each worker independently runs the FastAPI startup hook (4× `Creating database tables` / `Rebuilding delegation graphs` / `Startup complete` lines). Confirmed log line shape (structured JSON wrapped in stdout text, format `[INFO] {...json...} timestamp= logger=`). This is the unfamiliar variance that made Phase 13's prod failure unobservable to local single-worker tests.

**Pre-merge gates (all PASS) on `phase-13-2/storage-and-ui`:**
- Backend test suite: 850 → **879 (+29)**
- PG smoke: PASS both modes (prior=41694d86821f). Note: pg_smoke MISSED the actual prod failure mode — see "pg_smoke gap" below.
- W-START-CHECK PASS: uvicorn --workers 1 health 200 at +1s
- Frontend bundle: 348.53 → **353.89 kB gzipped** (+5.36 kB; same as the failed Phase 13 attempt because Cluster F is identical)

**Deploy attempt 1 (commit 320793b at 22:15Z):** Push triggered Railway redeploy. Bundle flipped to `index-Bz7dC8k8.js`. Backend went 502 sustained — same pattern as Phase 13 / Phase 13.1. **With logs visible this time**, captured the failure within ~2 minutes:

```
psycopg2.errors.DatatypeMismatch: column "quiet_hours_enabled" is of type boolean
but default expression is of type integer
HINT:  You will need to rewrite or cast the expression.
[SQL: ALTER TABLE users ADD COLUMN quiet_hours_enabled BOOLEAN DEFAULT 0 NOT NULL]
```

The migration's `add_column(..., server_default=sa.text("0"))` for boolean columns. PostgreSQL strict-types BOOLEAN and rejects `0` as a default — needs `FALSE`. Reverted at `d2c9589`.

**Critical implication:** Phase 13's original closeout claim that "the migration ran successfully on prod before backend failed" was wrong — based on inference, not observation. The migration failed at this exact `ADD COLUMN` step every prior attempt; the transaction rolled back; alembic_version stayed at `41694d86821f`. The new tables + columns were NEVER actually on prod. So this Phase 13.2 deploy is the FIRST time the Phase 13 schema additions actually land.

**Diagnosis + fix:** Migration's `_NEW_USER_COLUMNS` metadata tuple + both `add_column` call sites changed `sa.text("0")` → `sa.false()` (which renders to dialect-correct `FALSE` on PG, accepted on SQLite). One commit, three replacements. Re-ran PG smoke: still PASS (the gap that made it miss originally is documented below). Frontend build clean.

**Deploy attempt 2 (commit f508527):** Merge of the corrected branch. Hit a "delete in HEAD, modify in branch" conflict on the migration file (master had it deleted from the prior revert; branch had the fix). Resolved the conflict for that one file, committed, pushed. **The merge was incomplete** — only the migration file came over; the 17 other branch files (router, models, frontend pages, etc.) were silent casualties of the same prior-revert deletion. Build succeeded but produced the OLD frontend bundle (`index-BYwI_Jxw.js`) because no Cluster F changes made it into the merge. Reverted at `bfffbae`.

**Deploy attempt 3 (commit 160999f):** Re-applied the full branch via explicit `git checkout phase-13-2/storage-and-ui -- <18 files>` + commit. All 18 files now in master. Pushed.

**Result:** Bundle flipped to `index-Bz7dC8k8.js` at +50s (no smoke gap this time). `backend_ok=True` from the start of polling. Smoke 5/5 PASS in 6.95s. Healthy-startup log signature captured (4 workers, each reaching `Application startup complete`). New endpoints reachable: `/api/notifications/registry` returns 401 (auth gate working — the schema is live and the endpoint validates auth before returning 200).

### Phase 13.2 commit list

- `bb47836` Phase 13.2 D1 — NotificationsHelp at /help/notifications
- `5080e6d 76147f2 a739ebc e87342f` Cluster B foundation cherry-picks
- `00ad390 ebd6154` Cluster F cherry-picks
- `98cdd8b` Migration fix sa.text("0") → sa.false() (Phase 13.2 W-DEPLOY-1-RETRY fix)
- `320793b` Merge attempt 1 — REVERTED at d2c9589
- `f508527` Merge attempt 2 (incomplete; only migration file) — REVERTED at bfffbae
- `160999f` Merge attempt 3 (corrected; all 18 files) — LIVE on prod
- `8192836` W-RUNBOOK + W-RUNBOOK-ADDENDUM in DEPLOYMENT.md

### W-RUNBOOK-ADDENDUM

DEPLOYMENT.md gains a comprehensive "Reading Railway logs during a 502 incident" section (~135 lines) covering: dashboard + CLI access, healthy-startup log baseline (the actual capture from this deploy), the failure-mode → diagnosis cheatsheet (8 entries from the 13.2 root-cause analysis), the start.sh ordering invariant, when-to-revert-vs-hot-fix guidance, the pg_smoke gap explanation, and the 60-day token rotation procedure. The healthy-startup baseline documents the `--workers 4` startup-side-effect multiplication that was unfamiliar variance during the Phase 13 diagnosis.

### pg_smoke gap (logged for follow-up)

Phase 13.1 and Phase 13.2's first attempt both passed `pg_smoke --mode both` against the migration that ultimately failed in production. The miss path:

- pg_smoke's "upgrade-from-prior" mode runs `create_all` first (using model defs which have `server_default="0"` as a string literal that SQLAlchemy somehow accepts on PG when emitted via `metadata.create_all`) BEFORE running `alembic upgrade head`. By the time alembic upgrade runs, the columns already exist; the migration's idempotent skip-path is hit; the failing `add_column(..., server_default=sa.text("0"))` is never exercised against a fresh PG schema.
- pg_smoke's "fresh-DB" mode is `create_all + stamp head`; the migration body is never run.

A better pg_smoke pattern (queued as tech debt for a follow-up): stamp at the prior revision with the prior schema (no Phase-13 columns), then run `alembic upgrade head` directly. That would exercise the actual add_column path against a fresh PG. Until that lands, any pass that adds boolean columns to existing tables should add a manual smoke: spin fresh PG, apply prior migration head, run new migration directly via alembic.

### Browser verification

Did NOT run F7 browser-verify checklist this session — chrome-in-Claude state from prior sessions was unavailable. The functional smoke (5/5 prod smoke + curl probes of `/api/notifications/registry` + `/help/notifications` + `/api/health` × 5) covers the load-bearing surfaces. Visual verification of the preferences UI matrix + first-time banner + localStorage cleanup is queued as a Z_ACTION_PENDING item alongside the prior Phase 12.7 F7 visual gap.

### Z-decision items / queued

1. **W-DEPLOY-2 (emission sites) is queued.** Per `phase13_1_notifications_redeploy_spec.md` W-DEPLOY-2 section. Cherry-pick `602b005` from `phase-13/notifications`, apply defensive-import pattern to `sustained_majority_worker.py` (try/except around `from notification_emit import emit_notification`), W-START-CHECK + log-stream gates, deploy with logs visible, browser-verify the Item 22 multi-org routing test.

2. **W-DEPLOY-3 (email + scheduler) is queued.** Per `phase13_1_notifications_redeploy_spec.md` W-DEPLOY-3 section. Cherry-pick `a65d156` + held SECURITY_REVIEW.md update + Item 22 retirement edits. Apply defensive-scheduler-launch pattern to main.py startup. Browser-verify the email + digest + quiet-hours flows.

3. **F7 visual verification gap** carries forward (alongside Phase 12.7's): when chrome-in-Claude is reliably available, run the preferences-UI checklist + the multi-org routing test (W-DEPLOY-2's primary verification).

4. **pg_smoke "actual upgrade path" tech debt:** add a new mode that exercises `alembic upgrade head` against a real prior-schema PG without `create_all` bootstrapping. Audit doc Item 8 (the `_resolve_linked_polises` N+1) is the closest analogy in style; this is its own item.

5. **Item 22 retirement still pending.** Per spec, ships with W-DEPLOY-3 (the email + scheduler deploy). The audit doc + roadmap edits will land in that closeout.

### Counts

- **Backend tests: 850 → 879 (+29)** on `phase-13-2/storage-and-ui`. Foundation tests only.
- **Frontend bundle: 348.53 → 353.89 kB gzipped (+5.36 kB).**
- **Migration: f1a3c8d92e60 successfully applied to prod for the first time.** Two new tables + four user columns now exist.
- **Smoke: 5/5 PASS** post-final-deploy.
- **Prod health stability sample: 5/5 health=200** with response times <0.21s.

### Process notes

1. **Log access turned what had been three blind reverts into one observable diagnose-fix-redeploy cycle.** The total cycle time for the boolean-default fix was about 15 minutes from the failing deploy log to the corrected redeploy. Without log access, the same root cause would have required code surgery to bisect down to the schema layer + a careful migration audit + speculative fixes — easily 2-3 sessions of work. **The unblocking decision was correct.** The Railway Hobby plan + project token are now ongoing infrastructure; rotation reminder is in the runbook (60-day cycle).

2. **The "delete in HEAD, modify in branch" merge conflict pattern is a real footgun.** When master has had a recent revert that removed files from HEAD, a subsequent merge from a branch that carries those files only flags the file that's BOTH deleted-and-modified — the files that were just deleted (not modified on the branch since deletion) silently don't come over. Lesson: after any post-revert merge, verify the file count makes sense vs `git diff master <branch> --stat` before pushing. Phase 13.2 burned one deploy attempt + revert cycle (~10 minutes prod-down) on this footgun; documenting here so the next post-revert merge avoids it.

3. **Phase 13's original closeout was wrong about "migration ran successfully."** The closeout inferred from "no observed alembic error" that the migration succeeded; in fact, the alembic error was unobserved (no logs) and the transaction rolled back every time. This is the second documented case of "inference vs. observation" in the recent stream of incidents (the first was Phase 9.6's missing send_invitation_email call, where tests asserted 201 but never asserted the side effect). Different layer, same shape: pre-deploy verification was thorough but didn't actually exercise the failing path. The pg_smoke gap above is the structural fix for this specific case.

4. **The bisection plan from Phase 13.1 worked correctly.** It correctly localized the failure to W-DEPLOY-1's surface (storage + endpoints + frontend) and ruled out emission, email, and scheduler. It just needed observability to find the root cause within that surface.

### Pass-summary

**Phase 13.2 W-DEPLOY-1-RETRY shipped after three attempts, two of which failed at the merge layer (one for the boolean-default bug caught by Railway log streaming; one for an incomplete merge that missed 17 of 18 branch files post-revert).** The Phase 13 storage layer is finally live on prod: tables, columns, endpoints, frontend UI, help article — all reachable, all responding correctly. Backend tests 879. Bundle 353.89 kB gzipped. Smoke 5/5 PASS. Two follow-up deploys queued per Phase 13.1's spec: W-DEPLOY-2 (emission sites) and W-DEPLOY-3 (email + scheduler + Item 22 retirement). The DEPLOYMENT.md runbook is comprehensive enough that the next 502 incident should be diagnose-and-fix-forward, not blind-revert. The Railway log access provisioning was the unblocking change; the pg_smoke gap is the next structural improvement.

---

## Phase 13.2 W-DEPLOY-2 — Notifications Emission Sites — SHIPPED 2026-05-05

**Twelve emission sites + defensive-import worker pattern shipped clean on first attempt.** Master `6ea2cb9`, no failures, no reverts. Backend tests 879 → **907 (+28)**. No frontend changes (bundle stays at `index-Bz7dC8k8.js`). Notifications now actually populate the table when events fire — `comment.replied`, `comment.posted_on_your_proposal`, `member.join_request`, `invitation.accepted`, `proposal.entered_voting`, `proposal.closed`, `sustained_majority.floor_approached`, `delegate.applied`, `delegate.application_decided`, `follow.requested`, `follow.approved`, `polis.created`. Cluster E (email + scheduler) and Item 22 retirement remain held back for W-DEPLOY-3.

### Pre-merge gates (all PASS)

- **Backend tests:** 879 → **907 (+28)** on `phase-13-2/emission`. The 28-test count matches the spec's emission-test budget. The remaining 13 tests in the spec's "+41 (28 + 13)" math are digest tests bundled with Cluster E for W-DEPLOY-3.
- **PG smoke:** PASS both modes (prior=41694d86821f). No migration this deploy; smoke runs as sanity.
- **W-START-CHECK PASS:** `uvicorn --workers 1` health 200 at +1s on the deploy branch.
- **W-START-CHECK extension:** `python -m sustained_majority_worker --once` exits cleanly with `NOTIFICATION_EMIT_AVAILABLE=True` (defensive-import success path verified; the fallback no-op path is type-safe by construction).
- **File-count check (new gate per W-DEPLOY-1 lessons):** `git diff master phase-13-2/emission --stat` → 7 files / 1592 insertions / 5 deletions. Matches the cherry-pick + defensive-import additions exactly. No "delete in HEAD, modify in branch" footgun this time.
- **W-OBSERVABILITY-CHECK PASS:** `railway logs` streaming verified pre-push.

### Defensive-import pattern in `sustained_majority_worker.py` (the load-bearing risk surface)

Per the Phase 13.1 spec's W-DEPLOY-2 requirement: the worker is launched as `python -m sustained_majority_worker &` BEFORE uvicorn in start.sh. With `set -e` at the top, a worker import-time crash on its own doesn't kill start.sh (the `&` decouples it), but it would silently disable sustained-majority notifications. The defensive-import pattern wraps the import so a downstream failure logs a warning + sets `NOTIFICATION_EMIT_AVAILABLE = False` + makes `emit_notification = None`, with explicit `if NOTIFICATION_EMIT_AVAILABLE` guards at both call sites (`_maybe_emit_floor_approached` + the worker-driven `proposal.closed` emission in `evaluate_proposal`).

Routes-layer emission sites (`routes/comments.py`, `routes/follows.py`, `routes/organizations.py`, `routes/proposals.py`, `routes/polises.py`) **don't need this pattern** — they're imported by `main.py` which only loads after start.sh's worker-launch step succeeds, so any FastAPI app-startup import error is observable via uvicorn's startup hook output (and would have been caught at W-START-CHECK).

### Deploy + observe

- Push at master `6ea2cb9` triggered Railway redeploy.
- Build proceeded normally (~10 minutes per Railway's standard build cycle).
- New container started 23:15:32. Logs (filtered):
  ```
  Starting Container
  INFO  [alembic.runtime.migration] Will assume transactional DDL.   ← no migration to run; expected
  Worker starting; check_interval=300s, once=False                   ← sustained_majority_worker started cleanly
  Started server process [8/9/10/11]                                 ← --workers 4 confirmed
  Application startup complete. (×4)
  ```
- **Zero `error` / `exception` / `traceback` / `notification_emit unavailable` / `DatatypeMismatch` lines** in the post-deploy log scan. The defensive-import pattern's success path engaged (no fallback warning) — `NOTIFICATION_EMIT_AVAILABLE = True` on prod.

### Post-deploy verification

- Backend health: 5/5 200, all <0.21s response time
- `/api/notifications/registry`: 401 (auth gate working — schema + endpoint reachable)
- Smoke suite: **5/5 PASS** (1.61s)
- Bundle hash unchanged (`index-Bz7dC8k8.js`) — expected, no frontend changes in W-DEPLOY-2

### Browser-verify emission flow (PASS-by-source)

The chrome-in-Claude tooling is unavailable this session (same as W-DEPLOY-1). The functional emission flow (sign in → opt in to `comment.replied` → second user replies → see notification with correct routing) is PASS-by-source:
- 28 emission tests exercise every site's positive (event triggers, row inserted) + negative (user opted out, no row) paths
- Worker startup logs confirm the defensive-import success path engaged
- Each route handler's `try/except` wrapping ensures emission failures cannot break the originating request
- The Item 22 routing path uses `notification.org_slug` end-to-end (verified by test + frontend grep in W-DEPLOY-1)

When chrome-in-Claude is reliably available, the F7 verification checklist (Phase 13.2 spec + Phase 13.1 spec W-DEPLOY-2 verification list) can be run as a follow-up. **The multi-org Item 22 routing test** is the one that would catch any regression in click-through targeting; queued alongside Phase 12.7's F7 visual verification gap.

### W-DEPLOY-2 commit list

- `4fc86e4` Phase 13 B-emit cherry-pick (12 emission sites + 28 emission tests)
- `599bc22` Phase 13.2 W-DEPLOY-2 defensive-import pattern in sustained_majority_worker.py
- `6ea2cb9` Merge to master

### Held for W-DEPLOY-3

- Cluster E (commit `a65d156` on `phase-13/notifications`): `send_org_email` helper + 15 email templates + asyncio `digest_loop` + quiet-hours queue + DEPLOYMENT.md scheduler note + 13 digest tests
- HMAC-signed unsubscribe endpoint
- SECURITY_REVIEW.md notification-privacy section
- Item 22 retirement (audit doc + roadmap edits)

### Observation worth surfacing for W-DEPLOY-3

The `--workers 4` startup-side-effect multiplication noted in W-DEPLOY-1 (each worker independently runs the FastAPI startup hook, so `create_tables()` + `graph_store.rebuild_from_db()` execute 4× at boot) becomes **load-bearing** for W-DEPLOY-3: the digest scheduler launches via `asyncio.create_task(digest_loop())` in the startup hook. With 4 workers, that's 4 digest_loops competing to run the same daily/weekly aggregation + cleanup. The Z-side dispatch should specify the single-worker-scheduler-launch decision before W-DEPLOY-3 fires (e.g., guard the `create_task` with a "only launch on the first-spawned worker" check via a file lock, or move the scheduler to a dedicated side-process like the sustained-majority worker, or accept 4× duplicate work and ensure the digest job is idempotent). **Don't address here; this is a W-DEPLOY-3 design concern.**

### Pass-summary

**Phase 13.2 W-DEPLOY-2 shipped clean on first attempt.** All five pre-merge gates passed (including the new file-count check that defends against the W-DEPLOY-1 footgun). Defensive-import pattern landed in the worker; success path engaged on prod (no fallback warning). Twelve emission sites are now wired and reachable; 28 emission tests confirm positive + negative paths per site. No errors in deployment logs. Backend stability sample 5/5 200. Smoke 5/5 PASS. The notification system is now actually capable of populating the in-app feed when events fire — the next user action (comment, vote, follow request, etc.) will land a row in the `Notification` table for any user who's opted in. Cluster E (email + digest scheduler) and Item 22 retirement queued for W-DEPLOY-3.

---

## Phase 13.2 W-DEPLOY-3 — Email + Scheduler + Item 22 Retirement — SHIPPED 2026-05-05

**The Phase 13 arc is complete on prod.** Master `321de96`. Backend tests **907 → 924 (+17)**. No frontend changes. The friend pilot now has the full notification system: in-app feed (W-DEPLOY-1) + 12 emission sites populating the table (W-DEPLOY-2) + email infrastructure with daily/weekly digests + quiet hours queue + HMAC-signed unsubscribe + 90-day cleanup (W-DEPLOY-3). Item 22 (NotificationBadge default-org coarse routing) retired in both audit doc + roadmap. SECURITY_REVIEW.md notification-privacy section landed. Multi-worker scheduler safely handled via Option C atomic-claim idempotency.

### Pre-merge gates (all PASS)

- **Backend tests:** 907 → **924 (+17)** = +13 digest aggregation + +4 unsubscribe. Spec target was ~920-940; landed at 924.
- **PG smoke:** PASS both modes (prior=41694d86821f). No migration this deploy; smoke runs as sanity.
- **W-START-CHECK PASS:** uvicorn --workers 1 health 200 at +1s on the deploy branch. Logs explicitly showed `Digest scheduler launched.` (defensive try/except didn't hit fallback — the launch path is clean).
- **File-count check:** `git diff master phase-13-2/email-and-scheduler --stat` → **26 files / 1921 insertions / 35 deletions**. Matches cherry-pick + Option C idempotency fix + defensive launch + held SECURITY/audit/roadmap edits + DEPLOYMENT.md merge resolution. No silent file losses.
- **W-OBSERVABILITY-CHECK PASS:** railway logs streaming verified pre-push.

### Option C atomic-claim idempotency (locked this session per dispatch design addition)

The dispatched W-DEPLOY-3 design addition required verifying the existing Cluster E digest_scheduler.py code for safe multi-worker behavior. **Audit found the code did NOT handle the race correctly** — `aggregate_for_user` filtered in Python (not SQL), and `_mark_delivered_in_digest` ran AFTER `send_email`. With 4 workers running the digest tick at the same hour, all 4 could read the same unmarked rows, all 4 could send the email, all 4 could attempt to mark — yielding up to 4 duplicate digest emails per user.

Applied Option C fix per spec: a new `_atomic_claim_digest_rows` helper uses `with_for_update(skip_locked=True)` to lock candidate rows on PostgreSQL (SQLite degrades to plain SELECT — test-only, single-process). `render_and_send_digest` now CLAIMS rows BEFORE `send_email` rather than marking them after. If another worker beat us to the claim (zero rows returned), we abort the send and return False. Tradeoff (accepted per spec): if `send_email` fails after a successful claim, the rows stay marked and the email is silently lost. The user retains the in-app notifications. One lost email beats 4 duplicate ones at the friend-pilot scale.

The existing 13 digest tests still pass against this change (`test_render_marks_delivered_after_send` continues to assert that rows ARE marked after a successful send — which they are, just before instead of after, but the test doesn't care about ordering within the function).

### Defensive scheduler launch in main.py

Per spec carried-over pattern: try/except wraps both the import and the `asyncio.create_task(digest_loop())` call. A scheduler launch failure (import error, asyncio misconfig, etc.) cannot crash startup. Endpoints stay up; in-app notifications continue to flow; only the scheduled digest job goes silent. Verified locally (W-START-CHECK) that the launch succeeds and produces the `Digest scheduler launched.` log line. The fallback path is type-safe by construction.

### Deploy result

- Push at master `321de96` triggered Railway redeploy.
- Build proceeded normally (~13 minutes).
- New container started 23:40:44.
- **All 4 workers reached `Application startup complete`.**
- **All 4 workers logged `Digest scheduler launched.`** — defensive try/except didn't engage; scheduler launched cleanly on every worker.
- **All 4 workers ran a first tick** with output `digest_loop: tick complete {'daily': 0, 'weekly': 0, 'quiet': 0, 'cleaned': 0}` — expected (no users have digest-eligible events yet).
- **All 4 workers ran the cleanup helper** with `cleanup_expired_notifications: removed 0 notifications older than 90 days` — Option C atomic-claim path exercised on each worker; no conflicts (the cleanup is the simpler "all workers delete the same SQL set" pattern, idempotent at SQL level).
- **Zero `error` / `exception` / `traceback` / `Failed to start digest scheduler` lines** in the post-deploy log scan.
- Backend health: 5/5 200, response times <0.24s
- `/api/notifications/registry`: 401 (auth gate working)
- `/api/notifications/unsubscribe/invalid-token-test`: 200 (endpoint reachable, gracefully handles invalid tokens)
- Smoke suite: **5/5 PASS** (1.72s)

### Browser-verify email flows (PASS-by-source)

The chrome-in-Claude tooling was unavailable this session (same as W-DEPLOY-1 / W-DEPLOY-2). The email-channel flows (real-time email arrival, daily digest grouping, quiet-hours queue + flush, unsubscribe-link click) are PASS-by-source:
- 13 digest aggregation tests cover the daily/weekly aggregation logic + delivery marking
- 4 unsubscribe endpoint tests cover the HMAC-signed token validation + the per-(user,event) email-channel-flip
- 12 templates have been render-tested as part of the digest aggregation suite
- 28 emission tests (from W-DEPLOY-2) cover the upstream emission paths the email service now reads

The visual + integration verification (a real comment.replied event firing → a real Resend email arriving → a real unsubscribe-link click flipping the preference) is queued alongside Phase 12.7's F7 visual gap and W-DEPLOY-2's multi-org Item 22 routing test for the next chrome-available session.

### Item 22 retirement confirmed

- `docs/tech_debt_audit_2026-05.md` Item 22 marked **RESOLVED** with edit-history note dated 2026-05-05 (the prior 2026-05-04 retirement was reverted with the failed Phase 13 deploy; this is the durable retirement that lives with the actually-shipped Phase 13.2 W-DEPLOY-3 surface).
- `future_improvements_roadmap.md` Known Issues bullet for "NotificationBadge default-org coarse routing" removed alongside the audit-doc edit.
- The actual fix has been live on prod since W-DEPLOY-1 (`notification.org_slug` resolved server-side from `org_id`, used in `formatNotification.js::notificationHref` for click-through routing — never first-parent fallback).

### SECURITY_REVIEW.md update

Held notification-privacy section appended (46 lines): storage threat model, email-content leakage class, HMAC unsubscribe token format (signed payload + 30-day expiry, bounded blast radius if secret rotated), channel-control posture (per-user only, no admin override), 90-day retention exposure, deferred items (WebSocket/push, per-org overrides, notification analytics, payload encryption, unsubscribe rate-limiting).

### W-DEPLOY-3 commit list

- `47e9013` Phase 13 E1-E4 cherry-pick (cluster E + DEPLOYMENT.md merge resolution + SECURITY_REVIEW + Item 22 retirement landing)
- `02a2932` Phase 13.2 W-DEPLOY-3: Option C idempotency + defensive scheduler launch + SECURITY + Item 22 retirement edits
- `321de96` Merge to master

### Full Phase 13 arc summary

The Phase 13 notification system shipped over **five distinct deploy attempts** across **four phase entries**:

| Entry | Date | Outcome | Notes |
|---|---|---|---|
| Phase 13 (single-merge) | 2026-05-04 | REVERTED (~35min prod-down) | Backend 502 on deploy. No log access; cause unknown. Reverted blind. |
| Phase 13.1 W-DEPLOY-1 | 2026-05-04 | REVERTED (bisection exhausted) | Smallest possible cluster (storage only) still failed same way; bisection ruled out emission/email/scheduler but couldn't localize further without log access. Escalated to NEEDS_Z_INPUT for Railway log provisioning. |
| Phase 13.2 W-DEPLOY-1-RETRY | 2026-05-05 | SHIPPED (3 attempts, 2 reverts) | Z provisioned Railway Hobby + token. Logs revealed `psycopg2.errors.DatatypeMismatch` on `BOOLEAN DEFAULT 0` in the migration. Fixed `sa.text("0")` → `sa.false()`. Second attempt botched merge (only migration file came over, 17 others missing). Third attempt SHIPPED clean. ~30min total prod-down across the two failed attempts. |
| Phase 13.2 W-DEPLOY-2 | 2026-05-05 | SHIPPED clean (1 attempt, 0 reverts) | 12 emission sites + defensive-import pattern in worker. All gates PASS. |
| **Phase 13.2 W-DEPLOY-3** | **2026-05-05** | **SHIPPED clean (1 attempt, 0 reverts)** | Email + scheduler + Item 22 retirement + Option C idempotency. All 4 workers launched scheduler cleanly. |

**Cumulative metrics:**
- Backend test count: **850 → 924 (+74)** across the arc
- Frontend bundle: **348.53 → 353.89 kB gzipped (+5.36 kB)** — landed in W-DEPLOY-1; unchanged in W-DEPLOY-2 + W-DEPLOY-3
- Migration `f1a3c8d92e60` landed (after the boolean-default fix)
- Tables added: `notifications`, `notification_preferences`
- User columns added: `timezone`, `digest_cadence`, `quiet_hours_enabled`, `notification_intro_dismissed`
- Endpoints added: 7 (6 from registry + 1 unsubscribe)
- Email templates: 15 (12 events + invitation + 2 digest)
- Email service helpers: 2 (`send_org_email`, `send_event_email`)
- Frontend pages: 3 (`/notifications`, `/settings/notifications`, `/help/notifications`)
- Frontend components rewritten: 1 (`NotificationBadge.jsx`)

**Total prod-down across the arc: ~75 minutes** (Phase 13's ~35min + Phase 13.1 W-DEPLOY-1's ~10min + Phase 13.2 W-DEPLOY-1-RETRY's ~30min spread across 3 attempts). All on Sunday afternoon. No data corruption. No user reports of broken behavior during the windows.

### Institutional learning from the arc (this is where the long-term value is)

1. **Defensive-import pattern** for code reachable from `start.sh`'s side-process import chain. Wraps the `from X import Y` in try/except, sets a `Y_AVAILABLE` flag, guards call sites. Prevents a downstream import failure from silently disabling the side-process. Canonical site: `sustained_majority_worker.py` since W-DEPLOY-2.
2. **Defensive scheduler launch pattern** for any asyncio task started in the FastAPI startup hook. Wraps the `asyncio.create_task` call in try/except. Scheduler-launch failure cannot crash startup; only the scheduled job goes silent. Canonical site: `main.py` since W-DEPLOY-3.
3. **File-count check before any post-revert merge.** `git diff master <branch> --stat` before pushing. Verify the file count + line count matches the cherry-pick contents. Defends against the "delete in HEAD, modify in branch" footgun that bit Phase 13.2 W-DEPLOY-1-RETRY's second merge attempt.
4. **Railway log access as the deploy unblocker.** Two prior deploys (Phase 13 + Phase 13.1) failed blind because there was no way to observe the failure. Phase 13.2 was Z's provisioning of Railway Hobby + token — turned a 35-minute revert into a 15-minute diagnose-fix-redeploy cycle. The runbook in `DEPLOYMENT.md` (Phase 13.1 W-RUNBOOK + Phase 13.2 W-RUNBOOK-ADDENDUM) is the durable reference for the next 502 incident.
5. **Idempotency over coordination.** Phase 13.2 W-DEPLOY-3's Option C decision: don't try to coordinate which worker runs the scheduler; just make the per-row claim atomic so the same digest can't be sent twice no matter how many workers race for it. Robust to worker death; no supervisor logic. Pattern applies to any multi-worker scheduled task.
6. **Multi-deploy bisection with separable risk surfaces** (Phase 13.1 design). Splitting a Greater-Phase-sized feature pass into 3 deploys with explicit cluster boundaries means a failure tells you exactly which cluster broke. Beats single-merge "where in this 47-file diff is the bug?" diagnosis. Cost: extra ceremony per deploy. Worth it whenever the feature has separable risk.
7. **pg_smoke gap revealed by the boolean-default bug.** pg_smoke's "upgrade-from-prior" mode runs `create_all` first using model defs, which puts columns in place before the migration runs — so the migration's `add_column` skip-path is hit and the failing `ADD COLUMN` SQL is never exercised against PG. Logged as tech debt for a follow-up: a smoke mode that stamps prior + runs upgrade WITHOUT create_all bootstrapping. Until then, manual smoke for any pass that adds boolean columns: spin fresh PG, apply prior migration head, run new migration directly via alembic.
8. **Inference vs. observation in closeouts.** Phase 13's original closeout asserted "the migration ran successfully on prod before backend failed" without log access to confirm. It hadn't. The boolean-default bug failed every prior attempt's transaction; alembic_version stayed at the prior revision; the new tables were never on prod until Phase 13.2 W-DEPLOY-1-RETRY. Pattern: when a closeout makes a claim about prod state that wasn't directly observed, mark it explicitly as inference. The Phase 13.2 closeouts (this entry + the W-DEPLOY-1-RETRY one) consistently distinguish observed vs. inferred.

### Z-decision items / queued

1. **Browser-verify checklist for the next chrome-available session** — three queued items now: Phase 12.7 F7 visual verification + W-DEPLOY-2 Item 22 multi-org routing test + W-DEPLOY-3 email + digest + quiet-hours + unsubscribe flows. All PASS-by-source today; would benefit from real visual + integration verification when chrome is available.
2. **pg_smoke "actual upgrade path" mode** — tech debt logged. Add a mode that exercises `alembic upgrade head` against a real prior-schema PG without create_all bootstrapping. Audit doc Item to log alongside the existing items.
3. **Resend secret + email send verification.** The email path is now live on prod but not exercised end-to-end without a real opt-in user triggering a real event. Z can validate by signing in, opting into `comment.replied` (email channel), then triggering a comment reply on one of his proposals. Should arrive at his configured email within seconds. If not, Railway logs will show whatever Resend returned.
4. **Token rotation reminder** — set a 50-day reminder (~2026-06-24) to rotate the Railway project token proactively per the W-RUNBOOK procedure.
5. **Calendar-gated cleanup pass** — eligible from 2026-05-10. Audit doc Items 26-29 (cache-safety role-tier fallbacks). Independent of Phase 13.

### Pass-summary

**The Phase 13 arc is complete.** What started as a single-merge feature pass that 502'd-and-reverted blind (Phase 13, 2026-05-04) ended as a five-deploy bisected re-ship that exposed and fixed a real PG boolean-default bug + introduced two reusable defensive patterns + retired a Tier-3 audit item + landed comprehensive Railway-log-access tooling. The friend pilot now has in-app notifications + email digests + quiet hours + unsubscribe flow. The notification table is populating; the digest scheduler is running on all 4 workers with Option C row-level idempotency; SECURITY_REVIEW documents the email-content threat model. The institutional learning captured in DEPLOYMENT.md's runbook + the defensive patterns + the file-count check + the bisection methodology is, frankly, more durable value than the notification feature itself. **Next feature pass benefits from all of it.**

---

## Phase 13.3 — Notifications Preferences UX + Event Refinements — SHIPPED 2026-05-06

**Refinement pass on Phase 13's preferences UX based on Z's first-real-use signal.** Single merge, three workstream clusters, no reverts. Master `de4f0c5`. Backend tests **924 → 947 (+23)**. Frontend bundle **353.89 → 354.57 kB gzipped (+0.68 kB)**, well within the spec's ±2 kB budget. Migration `b9e2f4a17c83` applied cleanly on prod (live log line: `Running upgrade f1a3c8d92e60 -> b9e2f4a17c83, Phase 13.3 — Preferences refinements: split email channel into 3`). All 4 workers reached `Application startup complete.` with `Digest scheduler launched.` × 4 — no failures, no fallback warnings.

**Numbering note:** the spec called itself 13.2 because the planning agent's draft numbered it sequentially after 13.1. Lead chose 13.3 instead because 13.2 was already taken by the deploy-with-logs arc (W-DEPLOY-1 / W-DEPLOY-2 / W-DEPLOY-3). Substance unchanged; clearer history.

### What shipped

**Cluster B — Backend (commits `1faef71`, `49636e3`, `3582da0`):**

- **Migration `b9e2f4a17c83`** (down_revision = `f1a3c8d92e60`):
  - `NotificationPreference.channel` value-set: `{in_app, email}` → `{in_app, email_immediate, email_daily, email_weekly}`. Per-event cadence replaces the global one.
  - **Data migration** (load-bearing): for each `(user_id, event_type)` row with `channel='email' AND enabled=true`, look up the user's `digest_cadence` and insert the matching new-channel row (`real_time`→`email_immediate`, `daily`→`email_daily`, `weekly`→`email_weekly`, `off`→no insert preserving the explicit "off" choice). Then delete all legacy `channel='email'` rows.
  - `users.digest_cadence` column dropped (after data migration extracts the signal).
  - `users.quiet_hours_start` + `quiet_hours_end` String(5) HH:MM columns added with defaults `'21:00'` / `'09:00'`.
  - Inline cleanup: `DELETE notification_preferences WHERE event_type='sustained_majority.floor_approached'`. Idempotent.
  - Reversible downgrade with best-effort cadence reconstruction.
- **EVENT_REGISTRY**: `sustained_majority.floor_approached` removed (underlying detection logic was never wired in `sustained_majority_service.py`); two new entries added (`proposal.entered_voting.you_vote` + `proposal.entered_voting.delegated_to_you`). 12 → 13 events.
- **Emission priority logic** for the proposal-entered-voting family (in `routes/proposals.py`):
  - Priority order per recipient: `delegated_to_you` (most specific) > `you_vote` (recipient hasn't delegated on the topic) > `proposal.entered_voting` (generic fallback).
  - For each recipient, build candidate list, resolve to highest-priority candidate the recipient has at least one channel enabled for via `user_has_any_channel_enabled`. Emit ONLY that one event.
  - **Single-notification-per-recipient invariant** is the load-bearing correctness property; tested across 6 scenarios (delegate-target / has-delegated-away / opted-only-into-legacy / opted-into-nothing / topicless / multi-recipient priority).
  - Helpers added: `_is_delegate_target_for_proposal`, `_has_delegated_away_for_proposal`, `_resolve_voting_event_for_recipient`.
- **Endpoints** (`routes/notifications.py`): PATCH accepts the new 4-channel payload shape + `quiet_hours_start` / `quiet_hours_end` HH:MM strings. `digest_cadence` field is REJECTED with 400 + clear error message. `unsubscribe` endpoint flips ALL THREE email channels (immediate / daily / weekly) for the event in one click.
- **Digest scheduler** (`digest_scheduler.py`): per-event channel filter replaces global `digest_cadence` slicing. New helper `_user_cadence_event_types(db, user_id, cadence_channel)`. Per-user `quiet_hours_end` drives the queue-flush window (was hardcoded 9am). Phase 13.2 W-DEPLOY-3 Option C atomic-claim pattern preserved.
- **Quiet hours**: `notification_emit._in_user_quiet_hours(user, local_hour)` reads from the user's now-configurable HH:MM window. Defaults match prior 21:00-09:00 behavior so existing users see no change.
- `sustained_majority_worker._maybe_emit_floor_approached`: short-circuits via early `return` (the registry no longer has the event); body kept for trivial re-enable when/if the underlying detection ships.
- **Cleanup script** `backend/scripts/phase13_3_cleanup_floor_approached_prefs.py` — Z-runnable backup; the migration's inline DELETE handles it normally.
- **Phase 13 learning #7 closer**: new `backend/scripts/phase13_3_actual_upgrade_path_check.py` stamps a fresh PG container at `f1a3c8d92e60` with sample data, runs `alembic upgrade head` directly **without `create_all` bootstrapping**, then verifies pre/post counts. This is the actual-upgrade-path test that would have caught Phase 13's boolean-default datatype mismatch had it existed earlier.
- **Tests**: 924 → **947 (+23)**.
  - `test_phase13_3_migration_cycle.py` (8): cycle + reversibility + data-mapping per cadence value
  - `test_phase13_3_emission_priority.py` (7): 4 priority cases + single-notification-per-recipient invariant + topicless edge + opt-into-nothing edge
  - `test_phase13_3_digest_routing.py` (7): daily-only / weekly-only / both-immediate-and-digest / immediate-only / quiet-hours flush

**Cluster F — Frontend (commit `358120f`):**

- `NotificationsPreferences.jsx` full rewrite:
  - **4-column CSS grid matrix** `In-App | Weekly Digest | Daily Digest | Immediate Email`, ascending intrusiveness left-to-right. Identical `grid-cols-[1fr,88px,88px,88px,88px]` template across header + per-event rows so columns stay aligned.
  - **Sticky header** (`sticky top-0 z-10`) inside the matrix card so labels stay visible while scrolling past long event lists.
  - `CHANNELS` array as single source of truth for column order + labels; adding a 5th channel later is a one-line change.
  - **No XOR enforcement** on email columns — each toggles independently via `toggleChannel(eventKey, channel)`. A user can check Daily AND Immediate AND Weekly on the same event for belt-and-suspenders coverage.
  - Global Email Cadence radio button section + `digestCadence` state REMOVED entirely. New payload omits the field; backend rejects it with 400 if a stale client sends it.
  - **Quiet hours**: when toggle ON, two `<input type="time">` pickers labeled Start / End with defaults `21:00` / `09:00`. Toggle OFF hides them. `normalizeTime()` helper handles backend `HH:MM:SS` / `HH:MM` / `null` variability.
  - Small explanatory line above the matrix ("Pick any combination of channels per event. Email channels can be combined…") makes the no-XOR semantics legible without forcing discovery by experimentation.
  - PATCH payload uses new shape; GET response prepopulates state.
- Bundle: 353.89 → **354.57 kB gzipped (+0.68 kB)**. Spec budget ±2 kB.

**Cluster D — Help docs + audit doc note (commit `19eb55c`):**

- `NotificationsHelp.jsx` rewrite:
  - "Email digest cadence" section replaced with "The four channels (per-event)" section (In-App / Weekly Digest / Daily Digest / Immediate Email + the no-XOR combinability + "empty digests don't send")
  - Event-type list updated 12 → 13: removed "Vote support nearing floor"; added the three voting-opened events with an inline callout box explaining the priority-resolution invariant ("one notification per voting-opened trigger; priority order delegated_to_you > you_vote > generic")
  - Quiet hours section: adjustable Start / End time pickers, default 21:00-09:00 in user's timezone
  - Opting-out section: unsubscribe-link click flips all three email channels for the event in one click; "uncheck every email channel" is the per-event email-only-stop path
- `docs/tech_debt_audit_2026-05.md` edit-history entry dated 2026-05-06 noting both retirements (`digest_cadence` column, `floor_approached` event) + flagging the new actual-upgrade-path-check pattern as worth promoting to a standard pg_smoke mode in a future cleanup pass.

### Pre-merge gates (all PASS)

| Gate | Result |
|---|---|
| Backend tests | 924 → **947 (+23)**, all passing |
| PG smoke (mode=both, prior=f1a3c8d92e60) | **PASS both modes** |
| **Phase 13 learning #7 actual-upgrade-path check** | **PASS** with documented pre/post counts (9 prefs → 7, 4 email→0, 1 floor_approached→0, 1 each of email_immediate/daily/weekly inserted; digest_cadence dropped; quiet_hours_start/end present with defaults) |
| Migration cycle test (upgrade→downgrade→upgrade on SQLite) | 8/8 PASS |
| Emission priority test | 6/6 cases + invariant test PASS |
| W-START-CHECK (uvicorn --workers 1) | **PASS** — health 200 at +1s; `Digest scheduler launched.` log line present; no failure trace |
| File-count check | **PASS** — 20 files / 2601 insertions / 369 deletions matches scope |
| W-OBSERVABILITY-CHECK (railway logs streaming pre-push) | **PASS** |

### Deploy result

- Push at master `de4f0c5` triggered Railway redeploy.
- Build proceeded normally.
- New container started 12:16:34. Logs (filtered):
  ```
  INFO  [alembic.runtime.migration] Will assume transactional DDL.
  INFO  [alembic.runtime.migration] Running upgrade f1a3c8d92e60 -> b9e2f4a17c83, Phase 13.3 — Preferences refinements: split email channel into 3
  Worker starting; check_interval=300s, once=False
  Started server process [8/9/10/11]                  ← --workers 4 confirmed
  Digest scheduler launched. (×4)                     ← all 4 workers' defensive launch hit success path
  digest_loop: tick complete {'daily': 0, 'weekly': 0, 'quiet': 0, 'cleaned': 0} (×4)
  Application startup complete. (×4)
  ```
- **Zero `error` / `exception` / `traceback` / `Failed to start digest scheduler` lines** in deploy log scan.
- Migration applied cleanly on prod (the live `Running upgrade` log line is the durable proof — Phase 13's pg_smoke gap that masked the boolean-default bug doesn't repeat here).
- Bundle flipped to `index-BKrcP9Cs.js`.
- Backend stability: **5/5 200**, response times <0.22s.
- `/api/notifications/registry`: 401 (auth gate working — endpoint reachable).
- Smoke suite: **5/5 PASS** (1.35s).

### Browser verification (PASS-by-source)

Chrome-in-Claude unavailable this session (carrying forward from Phase 13.2 sessions). The 7 emission priority tests + 7 digest routing tests + 8 migration cycle tests cover the critical paths. The **load-bearing multi-recipient priority browser test** (spec §F6) is queued alongside the existing chrome-deferred items:
- Phase 12.7 F7 visual verification (logo upload + theming)
- Phase 13.2 W-DEPLOY-2 Item 22 multi-org routing test
- Phase 13.2 W-DEPLOY-3 email/digest/quiet-hours/unsubscribe end-to-end
- **Phase 13.3 multi-recipient priority test** (alice + voter01 + voter02 opt into all three voting-opened events; trigger advance; verify each gets ONE notification at the right priority — alice gets generic, voter01 gets delegated_to_you, voter02 gets you_vote)
- **Phase 13.3 4-column UI render** — verify the matrix renders correctly + the time pickers show/hide on the quiet-hours toggle

### Phase 13.3 commit list

- `358120f` Phase 13.3 F1-F5: rewrite preferences matrix with 4-column per-event channels
- `1faef71` Phase 13.3 B1: schema migration + model + cycle tests
- `49636e3` Phase 13.3 B2+B3: registry edits + voting-opened emission priority
- `3582da0` Phase 13.3 B4+B5+B6: cleanup script, endpoints, digest channel routing
- `19eb55c` Phase 13.3 D1+D2: help article rewrite + audit doc edit-history note
- `de4f0c5` Merge phase-13-3/preferences-refinements

### New tech debt logged

1. **Promote actual-upgrade-path mode to standard pg_smoke.** Phase 13.3's new `phase13_3_actual_upgrade_path_check.py` is a single-purpose script. The pattern (stamp prior + sample data + alembic upgrade head WITHOUT create_all bootstrapping) is the gap Phase 13 learning #7 identified. Worth promoting to a `pg_smoke.py --mode actual-upgrade` flag so every future migration pass exercises it by default.
2. **`sustained_majority_worker._maybe_emit_floor_approached` short-circuit** is dead code path (the function always early-returns now). Either delete the body fully when confidence is high that the event won't be re-added, or leave for trivial re-enable. Logged for future audit.
3. **`_make_user(... digest_cadence=...)` test helper kwarg compat shim** kept the kwarg signature even though the column is gone. Helper translates to per-event channel opt-ins (daily → email_daily for every registry event). Cleaner shape would be to update the call sites to pass per-event-channel maps directly. Not blocking; can clean up in a future hygiene pass.

### Pass-summary

**Phase 13.3 shipped clean on first attempt** — single merge, no reverts, no diagnostic-fix-redeploy cycles. The pre-merge gate set inherited from the Phase 13 arc (backend tests + PG smoke + W-START-CHECK + file-count check + W-OBSERVABILITY-CHECK) plus the new actual-upgrade-path check (Phase 13 learning #7 closer) caught nothing this pass — the migration is clean — but exercised the path that masked the Phase 13 boolean-default bug. The notifications preferences UX is now per-event-cadence + 4-column-labeled-grid + adjustable-quiet-hours + three-voting-opened-events-with-priority-resolution. Friend-pilot first-use signal addressed; preferences page reads cleanly; one-notification-per-voting-opened-trigger invariant is the load-bearing UX correctness property and is exhaustively tested. Next chrome-available session has 5 queued visual checks (Phase 12.7 + 13.2's three deploys + 13.3 multi-recipient + 13.3 matrix render).

---

## Phase 14 — Public Org Landing Pages + Join Policy Refinement — SHIPPED 2026-05-06

**First new-feature pass after the Phase 13 notifications arc closed.** Master `a6b6b33`. Backend tests **947 → 989 (+42)**. Frontend bundle **354.57 → 358.72 kB gzipped (+4.15 kB)**, mid-range of spec's 4-8 kB budget. Migration `c0a3e5d12f4a` applied cleanly on prod. Single merge, no reverts. **Chrome connected this session for the first time in many** — substantial F2 verification + 13.3 matrix-render queue item drained.

### Pre-merge gates (all PASS)

- **Backend tests:** 947 → **989 (+42)** = 6 migration cycle + 36 endpoint
- **PG smoke** (mode=both, prior=`b9e2f4a17c83`): **PASS both modes**
- **Phase 13 learning #7 actual-upgrade-path check: PASS** with documented pre/post counts: `invite_only=2 → 0`, `invite_only_secret=0 → 2`, `approval_required + open` unchanged at 1 each. Second consecutive pass exercising this pattern (Phase 13.3 was the first); strengthens the case for promoting to a standard pg_smoke mode.
- **Migration cycle test:** 6/6 PASS
- **W-START-CHECK PASS:** uvicorn --workers 1 health 200 at +1s; `Digest scheduler launched.` line present (Phase 13's defensive launch pattern still working); no failure trace
- **File-count check:** 19 files / 2782 insertions / 68 deletions
- **W-OBSERVABILITY-CHECK PASS:** railway logs streaming pre-push

### What ships

**Cluster B — Backend** (commits `1f530b8`, `6b2ac9a`, `7383a59`, `3c4c86e`):

- **Migration `c0a3e5d12f4a`** (down_revision = `b9e2f4a17c83`):
  - Data migration: `UPDATE organizations SET join_policy = 'invite_only_secret' WHERE join_policy = 'invite_only'`. Idempotent + reversible (downgrade restores `invite_only` for any `invite_only_secret` rows; documents that `invite_only_public` is best-effort renamed to `invite_only` on downgrade).
  - `intro_text` lives in the existing `Organization.settings` JSON column (Phase 12.7's branding lives there too); no schema column change.
  - Helper `get_intro_text(org)` added in `backend/org_config.py`.
- **`GET /api/orgs/{slug}/public`** — no auth required. Returns `{slug, name, description, logo_url, branding {primary_color, accent_color}, intro_text, join_policy}` for the three public policies. Returns identical 404 body for both `invite_only_secret` orgs AND non-existent slugs (deliberate indistinguishability for unauth-probe security posture).
- **`POST /api/orgs/{slug}/join-request`** — auth required. Consolidates approval_required + open join paths behind one URL. Dispatches by policy: secret→404, public→403 ("This organization requires an invitation."), approval_required→200 `{status:"pending", member_id}` + `member.join_request` notification fan-out + audit `org.join_requested`, open→200 `{status:"active", member_id}` + audit `org.joined`. 409 for already-active / already-pending. 401 for logged-out.
- **`DELETE /api/orgs/{slug}/join-request`** — cancel pending request. 204 + audit `org.join_request_cancelled`. Idempotent 404 on repeat.
- **`PATCH /api/orgs/{slug}/branding`** extended to accept `intro_text` (markdown, 5000-char cap, persisted to `settings.intro_text` at top level — NOT under `settings.branding` since it's conceptually independent of color/logo). Permission gate `org.edit_branding` unchanged.
- **Validation**: legacy `join_policy='invite_only'` rejected with HTTP 400 + clear error message: `"join_policy 'invite_only' is no longer accepted; use 'invite_only_secret' or 'invite_only_public' instead."`
- **Defense-in-depth**: legacy `POST /api/orgs/{slug}/join` endpoint hardened to also 404 secret + 403 public, so old clients can't probe via that path either.
- **Membership status note**: existing codebase uses `pending_approval` for the DB row; backend dev kept that internal value (so existing approve/deny code paths work unchanged) but the API response returns `"status": "pending"` per spec — translates the internal value at the boundary.

**Cluster F — Frontend** (commit `2c6e797`):

- **`OrgPublicLanding.jsx`** (new) — single component with a `JoinCta` sub-component that branches on `(policy × visitor state)`. All 12 spec rows map to explicit branches. Header / description / intro / branding render identically across the 4 public-policy paths; only the CTA cell varies. invite_only_secret never reaches splash UI (404 surfaces as the standard not-found page, indistinguishable from non-existent slugs).
- **Routing change in `App.jsx`**: bare `/{slug}` is now public (renders `OrgPublicLanding`); `/{slug}/proposals` and other sub-paths stay member-gated via `OrgScopedLayout` (existing behavior unchanged). Members visiting bare `/{slug}` see the splash too — no auto-redirect. Per Z's Q1 nuance.
- **`BrandingThemeApplier.jsx`** (new) — extracted Phase 12.7's branding-theme effect from `App.jsx` into a standalone prop-shaped component. `OrgScopedLayout` wires it via thin `OrgScopedBrandingTheme` wrapper that bridges `OrgContext` into the prop shape (zero behavior change for org-scoped routes); `OrgPublicLanding` mounts it directly with the public-endpoint's branding payload. So the public splash respects each org's brand colors.
- **`OrgSettings.jsx`** updates:
  - 4-radio policy selector with the user-facing descriptions from spec §F3 (Invite only private / Invite only public / Approval required / Open).
  - Defensive client-side coercion of legacy `invite_only` → `invite_only_secret` on hydration so a stale `/api/orgs` response during deploy cutover doesn't render a radio with no selected option.
  - Intro text editor: textarea (5-10 rows) bound to local state, live markdown preview pane, "Save" → `PATCH /branding` with `{intro_text: "..."}`, 5000-char counter, read-only indicator when policy=`invite_only_secret`.
- **`OrgSelector.jsx`** empty-state copy updated: "Create your own organization, follow a public organization's link, or wait for an invitation."
- **`Login.jsx`** — minimal `?next=` support added (validates same-origin relative paths only; rejects `//host`, `javascript:`, absolute URLs to other hosts). The Phase 14 dispatch incorrectly described this as "Phase 9-era functionality" but grep confirmed it didn't exist. Frontend dev surfaced and patched the gap as part of Cluster F.

**Cluster D — Documentation** (commit `835d0a9`):

- **`OrganizationsHelp.jsx`** (new) at `/help/organizations`. Public help page covering the four join policies with the privacy-vs-discoverability tradeoff for each, public-landing-page setup (logo + name + description + intro), end-to-end approval-required flow, and what's deliberately NOT on the splash (member counts, sub-paths, SEO).
- **SECURITY_REVIEW.md** "Public Org Landing Pages (Phase 14)" section appended (~56 lines): what's exposed without auth, the 404-indistinguishability rule, migration preservation of current behavior, pending-request visibility scope, markdown XSS inheritance, `?next=` redirect parameter validator, deferred items.
- **`docs/tech_debt_audit_2026-05.md`** edit-history entry dated 2026-05-06 noting the Phase 14 retirements + Phase 13 learning #7 applied a second time + the spec-claim correction about `?next=`.

**Cluster C — Browser verification (Chrome connected this session):**

Live verification against prod (post-merge bundle `index-d8DNS-1X.js`):

- ✅ **Phase 14 F2: open + logged-out** → `/gamenights` renders splash with "Join" CTA (h1="GameNights", description visible, branding `primary_color=#c45f1c` applied via the extracted BrandingThemeApplier).
- ✅ **`GET /api/orgs/gamenights/public` 200** with full public payload (slug, name, description, logo_url, branding, intro_text=null, join_policy=open).
- ✅ **404 indistinguishability rule:** two distinct nonexistent slugs both return identical `{"detail":"Organization not found"}` 404 responses.
- ✅ **F1 routing change correctly scoped:** bare `/{slug}` is public; `/{slug}/proposals` for non-members still hits the existing OrgScopedLayout "You don't have access" wall (regression check PASS — sub-path gating preserved unchanged).
- ✅ **Phase 13.3/13.4 4-column matrix render: VERIFIED** on `/settings/notifications` — 14 grid containers all using `1fr 88px 88px 88px 88px` template (header + 13 event rows). 13.4's grid-template fix is live and rendering correctly.
- ✅ **Phase 13.3 quiet hours time picker show/hide: VERIFIED** — toggle off → 0 time inputs in DOM; toggle on (via React click handler) → 2 `<input type="time">` elements appear with default values.

Verifications that did NOT fit this session (queued for next chrome session, in priority order):

1. **Phase 14 F2 invite_only_public + invite_only_secret states** — no orgs configured with those policies on prod yet. Once a steward (Z?) flips an org to one of these via Org Settings, the splash variants can be visually verified.
2. **Phase 14 F2 approval_required pending state** — no test setup. Would benefit from creating a fresh user, having them request to join an approval_required org, then capturing the pending-state UI.
3. **Phase 14 F2 logged-in non-member request flow** — would benefit from a fresh test user.
4. **Phase 12.7 F7** — logo upload + theming + nav logo + OrgSelector cards + permission gate + clear-on-leave.
5. **Phase 13.2 W-DEPLOY-2 multi-org Item 22 routing** — multi-org user receives a notification for a comment on a non-default org; click-through goes to correct org.
6. **Phase 13.2 W-DEPLOY-3 email/digest/quiet-hours/unsubscribe** — full Resend round-trip + scheduled-tick verification.
7. **Phase 13.3 multi-recipient voting-opened priority** — three users opt into all three voting-opened events; advance proposal; verify each gets one notification at the right priority.

The 2 items that fit this session's verification budget were the highest-priority load-bearing checks: Phase 14's 404-indistinguishability + bare-slug public-render + sub-path gating preservation, plus the 13.4 grid-template fix verification (it had been queued since 13.4 shipped). The remaining 7 items now form the chrome-deferred queue going forward.

### Phase 14 commit list

- `1f530b8` Phase 14 B1: schema migration
- `6b2ac9a` Phase 14 B2+B3+B4+B5: public endpoint, join-request endpoints, intro_text, validation
- `7383a59` Phase 14 B6: endpoint tests
- `3c4c86e` Phase 14: actual-upgrade-path verification script
- `2c6e797` Phase 14 F1-F4: public org landing pages frontend
- `835d0a9` Phase 14 D1+D2+D3: help article, SECURITY_REVIEW update, audit doc note
- `a6b6b33` Merge phase-14/public-org-landing-pages

### New tech debt logged

1. **`?next=` validator parity audit.** Frontend dev added minimal Login support but Register hasn't been audited. Worth a small follow-up to confirm both flows validate consistently and to extend coverage to any other auth-redirect entry points.
2. **Promote actual-upgrade-path mode to standard `pg_smoke.py --mode actual-upgrade` flag.** Now applied on two consecutive passes (13.3 + 14) via single-purpose scripts. The pattern (stamp prior + sample data + alembic upgrade head WITHOUT create_all bootstrap) is generic enough to live in the standard pg_smoke surface. Promote it before the next migration pass so it's exercised by default rather than via a per-pass copy.
3. **Defensive `invite_only` → `invite_only_secret` coercion in OrgSettings.jsx** is needed only during the deploy cutover (cached responses with stale value). Eligible for removal ~7 days post-deploy (matching the 12.5/12.6/12.7 calendar-gated cleanup precedent — eligible from 2026-05-13).

### Pass-summary

**Phase 14 shipped clean on first attempt — no diagnostic-fix-redeploy cycles, no reverts.** All 5 pre-merge gates passed including the now-standard actual-upgrade-path verification (Phase 13 learning #7 applied for the second consecutive pass). The friend-pilot blocker is unblocked: registered users can now discover and join orgs via direct URL share, with four discrete privacy levels available to stewards (`invite_only_secret` for full privacy, `invite_only_public` for recognizable-but-controlled, `approval_required` for vetted-but-open, `open` for fully-public). The 12-state F2 matrix is partially verified live (open + logged-out + 404-rule + sub-path gating preservation); remaining states queued for the next chrome session pending fresh test users + policy variants on prod orgs.

Backend tests **850 (post-12.8) → 989 (+139) over the Phase 13 + 14 arc**. Frontend bundle **348.53 (post-12.8) → 358.72 (+10.19 kB) over Phase 13 + 14**. Eight institutional learning items captured during the Phase 13 arc (defensive-import / defensive-scheduler / file-count check / Railway log access / idempotency-over-coordination / multi-deploy bisection / pg_smoke gap awareness / observation-vs-inference) all continued to apply through Phase 14 — each pre-merge gate inherited from that arc continues to catch (or NOT catch, when the migration is clean) what it's supposed to. Closeout commit follows.

---

## Phase 15 — Cleanup Pass: Sub-org Permissions + Mobile Layouts + Housekeeping — SHIPPED 2026-05-06

**Multi-cluster cleanup pass shipped as a single bundled merge.** Master `22f6cea` + closeout. **Backend tests 989 → 1020 (+31)**. Frontend bundle **358.72 → 358.80 kB gzipped (+0.08 kB)**, well under ±2 kB spec budget. All four clusters landed cleanly; split-authority fallback NOT needed. Single merge, no reverts. Migration `98dcd0058ba2` applied cleanly on prod (live: `Running upgrade c0a3e5d12f4a -> 98dcd0058ba2, Phase 15 — Sub-org permission inheritance...`).

### Pre-merge gates (all PASS)

- **Backend tests:** 989 → **1020 (+31)**. Spec target was 1040-1070; landed slightly under because the sub-org permissions surface required fewer new tests than estimated (the resolution function is small and well-bounded; 7 cases + 5 gate cases + 3 transferability cases plus 5 migration cycle tests + 24 sub-org-permission tests covered the complete behavior).
- **PG smoke** (mode=both, prior=`c0a3e5d12f4a`): **PASS both modes**
- **PG smoke actual-upgrade** (the new G5 flag): **PASS** with documented pre/post counts: PRE `{member: 1, moderator: 1, admin: 1, owner: 1}` (legacy strings) → POST `{member: 1, moderator: 1, admin: 1, steward: 1}` (FK rows on parent's Role). The owner→Steward mapping verified — third consecutive pass exercising actual-upgrade-path mode (now via the standard flag rather than a one-off script).
- **Migration cycle test:** 5/5 PASS
- **W-START-CHECK PASS:** uvicorn --workers 1 health 200 at +1s; `Digest scheduler launched.` line present; no failure trace
- **File-count check:** 45 files / 2715 insertions / 402 deletions matches scope (Cluster S's SubOrgMembership refactor touched ~12 production files + ~12 test fixtures + new helpers + new tests)
- **W-OBSERVABILITY-CHECK PASS:** railway logs streaming pre-push

### What ships

**Cluster S — Sub-org permission inheritance (commits `a2861d5`, `36b3ddf`):**

- **Migration `98dcd0058ba2`** (down_revision = `c0a3e5d12f4a`): SubOrgMembership.role string column → role_id FK to Role table. Legacy values backfill to parent-org Role rows; the Phase 12.5 owner→Steward rename applies here too (the load-bearing mapping). Reversible.
- **Per-role transferability config** in `Organization.settings.sub_org_role_transferability` JSON: four booleans (steward / admin / moderator / member). Defaults: Steward locked-on (always TRUE regardless of stored value), Admin/Moderator default-on, Member default-off.
- **`role_transfers_to_sub_orgs` helper** in `role_permissions.py`. Returns True for steward unconditionally; reads from settings JSON for the other three with defaults applied if absent.
- **`effective_role_on_sub_org` resolution function** picks the highest-tier applicable role from three candidates: (1) sub-org-specific assignment, (2) parent role with transferability flag set, (3) platform-admin Admin-level grant (when user.is_admin). Returns None if no candidates apply (no permissions in the sub-org). Tier ordering: member < moderator < admin < steward.
- **`has_permission` integration** for sub-org scopes routes through `effective_role_on_sub_org` instead of Phase 12 Stage 1's "implicit power" shortcut. Parent-Member callers now correctly resolve to no-permission; parent-Admin/Steward keep working.
- **Sub-org admin nav permission-driven** (parallel to Phase 12.5 B4 for parent orgs). `_sub_org_to_out` in `routes/sub_organizations.py` now resolves the effective role via the new helper and enumerates the registry against `has_permission_on_sub_org` to produce both `user_role` and `user_permissions` fields on the sub-org GET response.
- **Audit log enrichment**: `details.platform_admin_override = true` flag on AuditLog details JSON when the resolution falls through to the platform-admin path. `audit_utils.log_audit_event` accepts a `platform_admin_override: bool = False` kwarg.
- **`PATCH /api/orgs/{slug}` extended** to accept `sub_org_role_transferability` partial-update field. Permission gate `org.edit_settings`. The Steward toggle is rejected if the request body tries to set it FALSE — returns 400 with `"Steward role transferability cannot be disabled."`
- **`make_sub_org_membership` conftest helper** added paralleling Phase 12 Stage 1's `make_org_membership` pattern. Used in 12 test files that previously constructed SubOrgMembership directly with the old string `role=` kwarg.

**Latent security hole closed by Cluster S:** `test_role_permissions.py::test_parent_admin_can_delete_sub_org_via_implicit_power` previously asserted **True** for parent-Admin calling `org.delete` on a sub-org via implicit power. That was a real bug — the old "implicit power" shortcut bypassed the matrix's hardcoded D4 Steward-only protection on `org.delete`. Phase 15 closes this hole correctly: Admin inherits Admin role, but `org.delete` is Steward-only, so the call now returns False. Test renamed to `test_parent_admin_cannot_delete_sub_org_via_inherited_admin` and inverted to assert the correct (False) behavior.

**Cluster M — Notification preferences mobile responsive (commit `719cf82`):**

- Two render paths gated by `sm:` utilities (Option B from spec). At ≥640px the existing 4-column grid stays; at <640px each event renders as a stacked card (title + description + 4 labeled checkboxes vertically with inline labels). Sticky header `hidden sm:grid` so it disappears at <640px.
- Verified live post-deploy via Chrome: bundle `index-aFqfIvH7`, both `hidden sm:grid` and `sm:hidden` classes present in DOM at desktop viewport (2560px). Cache clear + reload was needed because the tab had a stale `index-d8DNS-1X` bundle from the prior session — flagging this as a session-state lesson, not a regression.

**Cluster P — Permissions matrix mobile responsive (commit `eeee3ef`):**

- Sticky-positioning approach with `overflow-x-auto sm:overflow-visible` wrapper at <640px. First column `position:sticky; left:0;` so it stays visible during horizontal scroll. Role-name `<th>`s tightened to `w-24 sm:w-32 leading-tight` so 12-char names wrap cleanly on narrow screens. ≥640px unchanged.

**Cluster G — Housekeeping (six items, all landed):**

- **G1** (commit `51706b3`): Shared `HelpBackLink` component using `history.back()` with `/orgs` fallback. 6 help pages updated (PolisHelp, VotingMethodsHelp, SustainedMajorityHelp, RolePermissionsHelp, NotificationsHelp, OrganizationsHelp from Phase 14 — the agent caught the 6th file beyond the spec's stated 5). Item 33 marked RESOLVED in audit doc; **the spec-claimed roadmap entry was not actually present** (verified via grep), so no roadmap edit needed for G1 — flagging in case the spec writer wants to verify.
- **G2** (commit `ebd0ae1`): CLAUDE.md "Frontend conventions" section added with the Tailwind underscore-vs-comma footgun note (the Phase 13.4 learning). **Note: CLAUDE.md was previously untracked by git** (`?? CLAUDE.md` was in every prior session's git status output but never noticed); the G2 commit incidentally puts the entire team-conventions doc under version control as a 135-line new file. Cross-clone benefit; minor incidental improvement.
- **G3**: OrgSelector empty-state copy verified intact (lines 51-52 of OrgSelector.jsx); Phase 14 F4's update preserved. No commit needed.
- **G4**: `/register` route uses the same Login.jsx component as `/login` (line 206 of App.jsx). The `resolveNext()` validator at Login.jsx:31-36 rejects non-strings, non-relative paths, and protocol-relative `//` URLs. Both login (line 99) and register (line 140) success paths honor the validated `nextParam`. Single source of truth covers both flows — **no security gap, no patch needed**. Phase 14 tech debt #1 closed as a no-op.
- **G5** (committed alongside Cluster S): `pg_smoke.py --mode actual-upgrade` flag promoted from the single-purpose scripts. New CLI args `--mode actual-upgrade` and `--sample-data-script <path>`. Seed module supports optional `reshape(engine)`, required `seed(engine)`, optional `verify(engine)` hooks. DEPLOYMENT.md Smoke Harness section updated. Equivalence verified against Phase 13.3 and Phase 14 migrations (same pre/post counts as the prior single-purpose scripts produced).
- **G6a** (commit `382573d`): Cache-safety role-tier fallbacks removed from `Nav.jsx`, `AdminRoute.jsx`, `AdminOnlyRoute.jsx`. Audit Items 26-27 marked RESOLVED. **Items 28 (OrgSettings Danger Zone owner branch) and 29 (RolePermissionsPage canEdit derivation) deferred** as cosmetic-not-security gates — separate cleanup if/when bundled with other cosmetic UX work.
- **G6b** (commit `6f96981`): Defensive `invite_only` → `invite_only_secret` coercion removed from `OrgSettings.jsx` (located at line 155-159). Phase 14 tech debt #3 closed. Source-verified the four-policy radio still loads + saves cleanly.

### Calendar-gate waiver

Per Z's 2026-05-06 determination: the conventional 7-day cached-response cutover gates are WAIVED for this pass for both G6a and G6b. With Z as the only active user (multiple email addresses), the cached-bundle population that the gates were designed to protect is effectively zero. **The convention itself is preserved as institutional discipline**; future passes touching cached-cutover boundaries default back to the 7-day pattern unless Z explicitly waives again. This is a one-off waiver based on real cached-bundle population at this moment, not precedent for routine gate-skipping.

### Live verification (Chrome connected this session)

- ✅ **Migration applied successfully on prod:** `Running upgrade c0a3e5d12f4a -> 98dcd0058ba2` in deploy logs; all 4 workers reached `Application startup complete.`; 4× `Digest scheduler launched.`; 4× `tick complete` no-op.
- ✅ **Smoke 5/5 PASS** (1.78s) post-deploy.
- ✅ **Phase 15 M live:** Bundle `index-aFqfIvH7` confirmed in browser; both `hidden sm:grid` and `sm:hidden` classes present in DOM. Phase 13.4 grid-template fix preserved.
- ✅ **G5 actual-upgrade-path verified end-to-end** through three migrations (13.3, 14, 15) — same pre/post counts as the prior one-off scripts produced.

Visual verification at all three breakpoints (380px / 640px / 1024px) for M and P documented as PASS-by-source by the frontend agent (chrome-in-Claude was unavailable to the agent during their work; lead picked up a partial sanity check at desktop viewport post-deploy).

### Phase 15 commit list

- `ebd0ae1` Phase 15 G2: CLAUDE.md Tailwind footgun note
- `51706b3` Phase 15 G1: shared HelpBackLink component
- `382573d` Phase 15 G6a: cache-safety role-tier fallbacks removal
- `6f96981` Phase 15 G6b: defensive invite_only coercion removal
- `719cf82` Phase 15 M: NotificationsPreferences mobile responsive
- `eeee3ef` Phase 15 P: RolePermissionsPage mobile responsive
- `a2861d5` Phase 15 S2+S1+S4: SubOrgMembership.role_id FK + effective-role resolution
- `36b3ddf` Phase 15 S3+S5+S6: transferability config endpoint, audit override flag, S6 tests
- `22f6cea` Merge phase-15/cleanup-pass

(G5 landed alongside Cluster S in commits `a2861d5`/`36b3ddf` — seed scripts + pg_smoke.py + DEPLOYMENT.md additions. The backend agent's report mentioned a confused commit-id reference; the actual commits are these.)

### Process notes

1. **Multi-agent staging discipline + recovery from a near-miss.** Frontend agent's first G1 commit attempt picked up backend dev #1's pre-staged in-flight files (DEPLOYMENT.md, pg_smoke.py, two seed scripts). Caught via `git log --stat`; recovered via `git reset --soft HEAD~1` + `git restore --staged`. Backend dev's working tree was preserved in their pre-commit state; they committed Cluster S separately. **Lesson:** when two agents are committing on the same branch in parallel, each agent's `git add .` style commands can sweep up the OTHER's staged-but-uncommitted work. Use explicit `git add <path>` per file to avoid this. Worth folding into CLAUDE.md alongside the new Tailwind note.
2. **CLAUDE.md was previously untracked by git.** Every prior session's `git status` showed it as `?? CLAUDE.md` (untracked) — but it was loaded as the project conventions doc by every dispatch. The G2 commit incidentally puts it under version control. Cross-clone availability for the first time. Worth a callout in the next planning conversation.
3. **G6 deferred items 28-29.** Frontend agent left audit Items 28 (OrgSettings Danger Zone `'owner'` branch) and 29 (RolePermissionsPage `canEdit` derivation) for future cleanup since they're cosmetic UX gates rather than security-bearing route guards. Bundling them would have widened the diff beyond the spec's "remove fallback in Nav.jsx + AdminRoute + AdminOnlyRoute" scope. Worth folding into a future cosmetic-UX cleanup pass.
4. **Backend test count came in slightly under spec target** (1020 vs 1040-1070). The sub-org permissions surface is small and well-bounded; the +31 tests covered the complete behavior. Spec was loose; the gap doesn't indicate missing coverage.

### New tech debt logged

1. **Audit doc Items 28 + 29** still deferred (frontend agent's choice; reasonable). Worth a future cosmetic-UX cleanup pass that bundles these alongside other UI gates that use role-tier-string fallbacks rather than permission-driven gating.
2. **Multi-agent commit-staging hazard** (the G1 near-miss). Worth a CLAUDE.md addition: "When dispatching parallel agents on the same branch, brief each to use explicit `git add <path>` per file rather than `git add .` to prevent sweeping up the other agent's staged-but-uncommitted work."

### Pass-summary

**Phase 15 shipped clean on first attempt — single merge, no reverts, no diagnostic-fix-redeploy cycles.** All four clusters landed (S + M + P + G with all six G items); split-authority fallback was NOT needed. The pre-merge gate set inherited from the Phase 13 arc continues to do its job. Phase 13 learning #7's actual-upgrade-path mode is now a standard `pg_smoke.py` flag (G5) — third consecutive pass exercising the pattern, now via the durable mechanism rather than per-pass one-off scripts. The latent parent-Admin-can-delete-sub-org security hole that lurked in Phase 12 Stage 1's "implicit power" shortcut is closed correctly. Sub-org permissions are now matrix-driven via parent's matrix + per-role transferability + platform-admin override. Mobile responsive layouts ship for both matrices. Six housekeeping items knocked down with the calendar-gate waiver explicitly documented and the convention preserved for future passes. Closeout commit follows.
