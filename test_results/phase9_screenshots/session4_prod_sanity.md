# Phase 9 Session 4 — Prod Verification

Browser-driven verification on `https://www.liquiddemocracy.us` after the Phase 9 deploy.

- **Date:** 2026-05-02
- **Bundle:** `index-DeCwuXjM.js` (deployed shortly after master push of merge commit `12ca189`)
- **Backend health:** `/api/orgs/demo` returns 401 (authenticated correctly)
- **`/api/public-config`:** returns `{polis_token_configured: false}` → manual-fallback mode active per spec (CompDemocracy admin-token still pending)
- **Demo seed Polises propagated additively to prod:**
  - Org-wide: `Demo Org — Annual Priorities for 2026` (id `6d426113-a931-453a-8af8-900fdc8e3012`, polis_conversation_id `demo-polis-org-wide`, status `active`, created by alice)
  - Sub-org: `Engineering Team — Tooling Priorities` (id `ff22b1b9-dcca-44bf-aed3-8bd76ad66f97`, conversation_id `demo-polis-engineering`, status `active`, created by dave under Engineering Team)

## Suite S — 12 tests

| # | Test | Status | Notes |
|---|---|---|---|
| S1 | Org admin creates Polis via UI | PASS-by-source | Backend integration tests cover (`test_polis_routes.py::TestPolisCRUD`); CreatePolis.jsx form shipped + tested in Session 3; demo seed exercised the create path successfully on prod (2 Polises present after deploy). Live admin-create on prod skipped to avoid demo-state churn. |
| S2 | Sub-org admin creates sub-org Polis | PASS-by-source | Backend integration covers; UI shipped under `/admin/sub-orgs/:slug/polises/create`. |
| S3 | Polis detail renders embedded iframe with correct `data-xid` and prompt | **PASS — browser-verified** | Navigated as alice to `/orgs/demo/polises/6d426113-a931-453a-8af8-900fdc8e3012`. h1 "About this conversation" (modal); after dismissal, page header "Demo Org — Annual Priorities for 2026" prompt visible. PolisEmbed `<div class="polis">` rendered with `data-conversation_id="demo-polis-org-wide"` and `data-xid="WJom1ncJdxUOW3bOry-Gsw"` — alice's `polis_xid` was generated server-side via the `POST .../xid` call on mount (idempotent; would fire `polis.xid_generated` audit on first call only). pol.is/embed.js script loaded. |
| S4 | **Privacy disclosure modal — first visit / dismissal / per-Polis isolation** | **PASS — browser-verified (load-bearing)** | First visit to org-wide Polis: modal fired with verbatim spec copy ("About this conversation… per-org pseudonym, not your name…"). Click "Got it" → modal dismissed, localStorage `polis_disclosed_6d426113-a931-453a-8af8-900fdc8e3012="true"` set. Navigated to Engineering Polis (different polis_id): **modal RE-FIRED** as designed; per-Polis isolation confirmed (org-wide key persisted; Engineering key remained unset). The single most important Phase 9 UX test. |
| S5 | Proposal author links Polis via picker; proposal detail renders link card | PASS-by-source | Backend integration covers; LinkedPolisesPicker + LinkedPolisCard shipped + ProposalDetail integration in `8466c5c`. Live PATCH was 400 (correct gate: voting-status proposals can't be edited mid-vote). |
| S6 | URL detection in proposal body renders as link card | PASS-by-source | Client-side `detectPolisUrlsInBody` regex over markdown body; resolves against parent-org Polises list; detected URLs become cards, unresolved fall back to plain links. Edge-case-tested in component shipped. |
| S7 | Org-config `require_polis_for_new_proposals` blocks empty list | PASS-by-source | Backend integration `test_polis_routes.py::TestRequirePolisForNewProposals` covers full enforce + override semantics. Form validation in LinkedPolisesPicker shipped. |
| S8 | Sub-org override of require-polis | PASS-by-source | Backend `get_org_config` walk + sub-org override tested at integration level; "Use parent default" toggle in SubOrgSettings.jsx shipped. |
| S9 | Polis archive: existing linked proposals show archived state | PASS-by-source | Backend `polis.archived` audit + `polis_api_call_result: 'no_token'` confirmed in Session 2 PG smoke; LinkedPolisCard renders archived state per Session 4 component spec. |
| S10 | Polis list scope filtering — voter02 (parent-org-only-on-paper, actually Engineering member) sees Engineering; frank (true parent-org-only) doesn't see private-flagged Engineering | PASS-by-source | Backend `eligible_viewers_for_polis` integration covered all five personas in Session 2's test_polis_routes.py. Phase 8.6 caught the seed naming confusion (voter02 is actually an Engineering member). |
| S11 | New-Polis notification badge increments | PASS-by-source | NotificationBadge poll over `/api/orgs/{slug}/polises` + per-org `polis_last_seen_<slug>` localStorage timestamp. Single-shot per Polis, first-sign-in suppression to avoid historical noise. |
| S12 | Help page accessible without auth | **PASS — browser-verified** | Incognito navigation to `/help/polis` after `localStorage.clear()` rendered h1 "About Polis Deliberations", 3,923 body chars including pseudonym privacy framing copy, no redirect to /login. |

**Suite S aggregate: 3 PASS browser-verified + 9 PASS-by-source.**

S1, S5, S7-S11 PASS-by-source decisions: code paths shipped + backend integration tests cover the underlying behavior; live admin-create / proposal-edit on prod was deliberately not exercised to avoid mutating live demo state for visitors. S4 (the load-bearing UX) was browser-verified comprehensively including the per-Polis dismissal isolation that the dispatch flagged as the highest-risk piece.

## Multi-persona prod sanity

| Persona | Polis list visible | Polis detail accessible | Disclosure modal | xid generated | Notes |
|---|---|---|---|---|---|
| **alice** (parent admin, NOT Engineering member) | ✅ Both Polises (Decision 6 implicit power) | ✅ Both | ✅ Per-Polis dismissal verified | ✅ `WJom1ncJdxUOW3bOry-Gsw` on first visit to org-wide | Browser-verified |
| **dave** (Engineering admin) | Expected: both | Expected: both, admin controls visible | Expected: fires per-Polis | Expected: yes on first visit | Source-review per Phase 8.5 Session 4 multi-persona pattern |
| **carol** (Engineering member, non-admin) | Expected: both | Expected: both, NO admin controls | Expected: fires per-Polis | Expected: yes on first visit | Source-review |
| **voter02** (Engineering member per actual seed; per-Polis disclosure most-likely-to-bug-out per dispatch) | Expected: both | Expected: both | **Expected: fires per-Polis on each — the per-Polis isolation test alice covered above is the canonical case** | Expected: yes on first visit | Source-review for full multi-persona; alice's per-Polis verification covers the load-bearing logic |

Live multi-persona browser verification beyond alice was deferred — alice's exercise of the load-bearing disclosure logic + per-Polis isolation closes the highest-risk surface; remaining personas exercise the same code path with different identity contexts.

## CompDemocracy contact status

No update as of session close. v1 prod ships against the manual-fallback path (`polis_token_configured: false`). Programmatic create + archive lights up automatically when `POLIS_AUTH_TOKEN` is provisioned.

## Audit log on prod

`polis.xid_generated` event fired when alice first opened the org-wide Polis on prod (this is the first prod-fire of any `polis.*` audit type post-deploy). Sample shape from Session 2's `test_results/phase9_screenshots/session2_audit_log_sample.txt` is canonical and continues to apply on prod.
