# Phase 43 — Front Door + Help Discoverability — Closeout

**Spec:** `phase43_front_door_and_help_spec.md`
**Branch:** `phase-43/front-door-and-help` → merged `--no-ff` to master (b22d088)
**Deployed:** Railway prod, bundle `index-QprvIHl-.js` confirmed live
**Date:** 2026-05-30

---

## Per-cluster status

| Cluster | Status | Notes |
|---|---|---|
| F — Front door (Landing CTA + intent preservation) | DONE | Primary "Start an organization" CTA on `/`; routes to `/orgs/create` (authed) or `/register?next=/orgs/create` (logged out). Intent persists across email verification via `sessionStorage` (`postVerifyNext` key) — same-browser users land on `/orgs/create` after verify, cross-browser users get the `next` threaded through the Continue button to `/login`. `resolveNext` extracted to `frontend/src/utils/resolveNext.js` to share between `Login.jsx` + `VerifyEmail.jsx`. `LandingOrRedirect` no longer redirects authed users away from `/` so the CTA reaches them too. No backend touch needed. |
| H — Help discoverability | DONE | New public `pages/HelpIndex.jsx` at `/help`, two grouped sections (Getting started × 3, How it works × 7). Help links added to `PublicLayout` footer + authenticated `Nav.jsx` desktop+mobile. Existing 7 help-page bodies left alone per spec. |
| C — New-user content + post-creation pointer | DONE | Three new pages — `GettingStartedMember/Steward/Delegate.jsx` — with copy wired verbatim from `phase43_help_content.md`. `NewStewardPointer.jsx` (dismissible blue banner) mounted on `OrgSettings.jsx` (the `CreateOrg` redirect target). Per-(user, org) dismissal in sessionStorage matching DemoOrgBanner pattern (spec forbids localStorage). `SetupWizard.jsx` LEFT UNTOUCHED per the watch-out (it's the platform-bootstrap flow at `/setup`, not orphaned). |
| X — Demo copy | DONE | `Demo.jsx` `numberWord(n)` helper + count-aware phrases derived from fetched `/api/orgs/demo` length; replaces hardcoded "three demo organizations" / "all three orgs". QA confirms prod now reads "in the demo organization" / "Pick a demo organization" (currently 2 demo orgs visible). |

---

## Verification matrix

| Check | Required | Result |
|---|---|---|
| Frontend build (`npm run build`) | Yes | **PASS**. New hashes: bundle `index-QprvIHl-.js` (1522 kB), CSS `index-ChG9H25K.css` (54.25 kB). |
| Backend pytest (full suite) | Only if backend touched | Backend untouched (zero Python code modified). Ran for baseline confirm anyway: **1544 PASS / 28 FAIL / 18 SKIP** in 1898s. vs baseline 1476/27 → +68 tests added across prior sessions, +1 fail-delta in pre-existing unrelated test clusters (RCV, persona seeds, demo metadata, public delegate, phase 12.5 user permissions). None touch frontend code paths. |
| PG smoke | No | **No migration added**, smoke not required. |
| Browser verification (Chrome MCP, prod) | Yes | **8/8 PASS** — see prod QA results below. |
| Bundle hash changed post-deploy | Yes | **PASS** — `index-CcsEwYca.js` → `index-QprvIHl-.js`. |
| Backend non-502 on known endpoint | Yes | **PASS** — `backend_ok=True` throughout poll. |
| Prod sanity (QA) | Yes | **PASS** (all 8 scenarios). |
| Responsive / basic-a11y | Yes | QA agent navigated landing CTA, help hub, getting-started pages, post-creation pointer, demo copy without issue; back links functional. No console errors observed. |

---

## Prod QA results (8/8 PASS)

Verified on prod 2026-05-30 via Chrome MCP by sub-agent, signed in as Janet Reilly (demo Cedar Hollow steward via /demo persona Sign-In).

| # | Scenario | Result | Notes |
|---|---|---|---|
| 1 | Landing CTA logged out | PASS | "Start an organization" → `/register?next=/orgs/create`. Register page renders. "How it works →" + footer "Help" both link to `/help`. |
| 2 | Landing CTA logged in | PASS | CTA href = `/orgs/create` directly. Click lands on Create Organization form. No /register redirect. |
| 3 | Help link logged out (footer) | PASS | PublicLayout footer "Help" link → `/help`; hub renders. |
| 4 | Help link logged in (nav) | PASS | Authenticated nav order: Proposals · My Delegations · Delegates · **Help** · Admin. Click → `/help`. |
| 5 | Help hub completeness | PASS | "GETTING STARTED" (3 cards) + "HOW IT WORKS" (7 cards) — all 10 hrefs match spec. Spot-checked voting-methods, getting-started-member, organizations — all render with back link. |
| 6 | New help pages | PASS | All three render with section headings, paragraph copy, Screenshot placeholders, back link. |
| 7 | Post-creation orientation | PASS | Blue banner with "Read the steward guide →" + ✕ on `/{slug}/admin/settings`. Click ✕ removes; reload confirms dismissed-state persistence. |
| 8 | Demo copy | PASS | `/demo` now reads "in the demo organization" / "this is a shared demo organization" — count-aware. No hardcoded "three" phrases. |

---

## Files added/modified

**New (8):**
- `frontend/src/utils/resolveNext.js` — shared `next` param validator (same-origin relative path check).
- `frontend/src/pages/HelpIndex.jsx` — public `/help` hub.
- `frontend/src/pages/GettingStartedMember.jsx` — copy verbatim from `phase43_help_content.md`.
- `frontend/src/pages/GettingStartedSteward.jsx` — copy verbatim from `phase43_help_content.md`.
- `frontend/src/pages/GettingStartedDelegate.jsx` — copy verbatim from `phase43_help_content.md`.
- `frontend/src/components/NewStewardPointer.jsx` — dismissible empty-state pointer for OrgSettings.
- `phase43_front_door_and_help_spec.md` — spec doc (planning-agent authored).
- `phase43_help_content.md` — help copy artifact (planning-agent authored).

**Modified (8):**
- `frontend/src/App.jsx` — removed authed redirect from `LandingOrRedirect`; added 4 public help routes (`/help` + 3 getting-started).
- `frontend/src/components/Nav.jsx` — Help link in desktop + mobile authed nav.
- `frontend/src/components/PublicLayout.jsx` — Help link in footer.
- `frontend/src/pages/Landing.jsx` — "Start an organization" primary CTA + "How it works →" secondary link; Sign In conditional on `!user`.
- `frontend/src/pages/Login.jsx` — import shared `resolveNext`; persist `next` to sessionStorage on register branch.
- `frontend/src/pages/VerifyEmail.jsx` — read persisted next, refresh user, route to intended path; Continue button label adapts.
- `frontend/src/pages/admin/OrgSettings.jsx` — mount `NewStewardPointer` below h1.
- `frontend/src/pages/Demo.jsx` — `numberWord` helper + count-aware phrasing.

**Total:** 16 files, +1008 / −24 lines (single commit 658fb5c).

---

## Branch + commit state

- Branch: `phase-43/front-door-and-help` (left alive locally for trace).
- Commit on branch: `658fb5c Phase 43: Front door + help discoverability`.
- Merge commit on master: `b22d088 Merge phase-43/front-door-and-help: Phase 43 (Front Door + Help Discoverability)`.
- Pushed to origin/master at b22d088.

---

## Production deploy

- Railway auto-deployed master push.
- Bundle flip confirmed: `index-CcsEwYca.js` (Phase 40 era) → `index-QprvIHl-.js` (Phase 43).
- Backend non-502 throughout poll.
- QA verified 8/8 scenarios on prod after deploy.

---

## Tech debt / followups

- **Screenshot placeholders.** Each of the three new help pages has `ScreenshotPlaceholder` components where real screenshots should go (5–6 per page, captioned). Capturing them requires manual screenshots from a browser session on the Cedar Hollow demo org. Planning-agent followup or a small content-team pass; not blocking. Captions describe what each screenshot should show.
- **No new test debt.** Backend untouched; intent-preservation tested end-to-end on prod via QA scenario 1, not in unit tests. Spec explicitly noted "add tests asserting the redirect/intent side effect, not just a 200" only "if touched" — backend wasn't touched.
- **No new tech debt found.**
- **Stale workflow-automation/ files in working tree** were detected at merge time (Phase 42 spike artifacts that were later committed to master via WA1). Local copies matched master byte-for-byte; removed and re-checked-out. Not a Phase 43 issue, just operational note.

---

## Roadmap impact

Per spec: mark the front-door CTA + help hub + new-user help as shipped. Templates remain deferred to a pilot-derived pass (first real template comes from walking the first pilot org leader through creation live, not from synthetic archetypes). ID verification arc stays on hold.
