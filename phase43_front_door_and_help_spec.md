# Phase 43 — Front Door + Help Discoverability

**Status:** Ready to build, pending one planning-agent prerequisite (the help-content artifact — see Cluster C / Operational watch-outs). This is the merged dispatch + spec doc (Phase 19+ convention).

**Branch:** `phase-43/front-door-and-help` → `--no-ff` merge to master at close.

---

## Dispatch framing

### Goal

One-paragraph version: a fresh new-user walkthrough of prod (2026-05-30) surfaced three structural gaps that the platform's maturity otherwise hides. (1) **No front door for a prospective org leader** — the landing page's only CTAs are "Try the Demo / About the Project / Sign In"; nothing invites a visitor to *start their own organization*, and the only path to org creation is buried in an authenticated profile dropdown. (2) **Help is undiscoverable** — seven good help pages exist at `/help/<topic>` but there is no `/help` index and no Help link in any nav, profile menu, or footer; they are reachable only via scattered contextual links. (3) **The just-created-org steward has no orientation** — `CreateOrg` redirects straight into an empty proposals list facing a deep admin surface with zero guidance. This pass closes all three with a recruiting CTA, a `/help` hub plus Help nav links, three new audience-oriented "getting started" help pages (member / steward / delegate), and a lightweight post-creation empty-state pointer — plus a stale-demo-copy fix. It is deliberately mostly frontend + content; no migration.

### Branch + merge

- Branch: `phase-43/front-door-and-help`.
- All work commits to that branch.
- `git merge --no-ff` to master at session close; push to origin; Railway auto-deploys.

### Verification matrix

| Check | Required | Notes |
|---|---|---|
| Frontend build (`npm run build`) | Yes | Must pass clean before merge. Watch the Tailwind arbitrary-value underscore rule (CLAUDE.md) if any grid/transform classes are used in the help-hub cards. |
| Backend pytest (full suite) | Only if backend touched | Frontend-only pass *unless* registration intent-preservation (Cluster F) needs a server-side change. If backend untouched, still run once to confirm the 1476 PASS / 27 pre-existing FAIL baseline is unchanged and state that in the closeout. If touched, add tests asserting the redirect/intent side effect, not just a 200. |
| PG smoke (`pg_smoke.py`) | No | This pass adds **no migration**. State "no migration, smoke not required" in the closeout. |
| Browser verification (Chrome MCP, per CLAUDE.md) | Yes | All four user-facing surfaces are load-bearing. Full QA scenario list below. |
| Bundle hash changed post-deploy | Yes | Confirm new hash in closeout. |
| Backend non-502 on known endpoint | Yes | Confirm post-deploy (even though backend likely untouched, the deploy still cycles). |
| Prod sanity (QA) | Yes | Run the QA scenarios on prod after deploy. |
| Responsive / basic-a11y check on new pages | Yes | Help hub + landing CTA at mobile width; new help pages keyboard-reachable, back link works. |

### QA scenarios (run on prod after deploy)

1. **Landing CTA, logged out:** visit `/` logged out → the new "Start an organization" CTA is present → click it → routed into registration with create-org intent preserved → complete register + email verification → land on `/orgs/create` (NOT a generic dashboard). Intent survives the verification round-trip.
2. **Landing CTA, logged in:** visit `/` logged in → CTA present → click → land directly on `/orgs/create`.
3. **Help link, logged out:** Help link visible in `PublicNav` → click → `/help` hub renders.
4. **Help link, logged in:** Help link visible in `Header` (top-level or profile dropdown) → click → `/help` hub renders.
5. **Help hub completeness:** `/help` lists all topics (7 existing + 3 new) → every link resolves to the correct page → each page's back link returns to the hub or browser-back as designed.
6. **New help pages:** each of member / steward / delegate getting-started pages renders the planning-agent copy verbatim, with screenshots loading.
7. **Post-creation orientation:** create a fresh org → on first landing, a dismissible empty-state pointer appears linking to the steward getting-started help → dismiss persists for that org/user.
8. **Demo copy:** `/demo` no longer claims "three demo organizations" / "all three orgs"; copy matches the actually-displayed count.

### Suggested team structure

Smaller than the default four-role. **Lead** in delegate mode (coordinates, writes closeout) + **one frontend dev** + **QA**. No backend dev by default — add one only if QA scenario 1 reveals that registration intent-preservation needs a server-side change (see watch-outs). No migration, so no PG-smoke role.

### Sequence

1. Planning-agent prerequisite (DONE before dispatch): deliver `phase43_help_content.md` + screenshot assets (Cluster C input).
2. Frontend: Cluster H (help hub + nav links + route) and Cluster F (landing CTA + intent preservation) — independent, can proceed in parallel.
3. Frontend: Cluster C (wire the three new help pages from the content artifact; add post-creation empty-state pointer).
4. Frontend: Cluster X (demo copy fix).
5. QA: browser-verify all scenarios on prod after deploy.
6. Lead: closeout.

### Load-bearing decisions

- **New help content is authored by the planning agent and wired verbatim by the Code team.** The team does NOT generate help copy. This is a deliberate guard against unsupervised content drift (the demo-bibles lesson). Copy + screenshots arrive as `phase43_help_content.md`.
- **No wizard.** The orphaned `SetupWizard.jsx` is deleted, not revived. Post-creation guidance is a single dismissible empty-state pointer, nothing more.
- **The `/help` hub is a PUBLIC route** (alongside the existing `/help/*` routes in App.jsx's public block). Prospective pilot leaders aren't authenticated.
- **The landing CTA preserves create-org intent through registration** so the prospect isn't dumped on a generic dashboard after verifying email.
- **No pre-seeded topics or content on new orgs** (per Z). The new-steward help is guidance, not auto-configuration.

### Operational watch-outs

- **Intent-preservation is the one genuinely tricky piece.** Email verification sits between "click Start an organization" and "create org," so the intent must survive that round-trip. First check whether `/register` (and the login/verify flow) already supports a `next`/redirect param; if it does, reuse it (`/register?next=/orgs/create`). If it doesn't, add the minimal mechanism (query param honored post-verification, or persisted intent). This is the only place a backend touch might be needed — flag early.
- **Don't touch the seven existing help pages' content.** Cluster H only adds an index that links them; leave their bodies alone.
- **Help hub must be reachable logged-out.** Register it in the public route block (~App.jsx line 213), not behind the auth guard.
- **Screenshots** are captured against the Cedar Hollow demo org. Store under the frontend's static/public assets; keep file sizes reasonable; no real user data exists but capture demo-only regardless.
- **Tailwind underscore rule** for any arbitrary multi-value classes in the hub card grid.
- **Leave `SetupWizard.jsx` alone — it is NOT dead code.** It's the first-user / platform-bootstrap flow at `/setup`, reached from `Login.jsx` when `needs_setup` / `is_first_user` is true. An earlier read mistook it for orphaned; it isn't. Don't delete it and don't try to fold it into the new-steward flow. This pass's post-creation guidance is the dismissible pointer only.
- **`Login.jsx` already honors a `next` param** (its `nextParam` branch), so the landing CTA's intent-preservation reuses an existing mechanism rather than inventing one. The only open question is whether `next` survives the email-verification round-trip — verify that, and add minimal persistence only if it's dropped.

### Closeout reporting

Per the CLAUDE.md closeout shape. Include: per-cluster status, test count delta (or "backend untouched, baseline 1476/27 confirmed"), PG smoke ("no migration, not required"), browser verification result for each QA scenario above, files added/modified/deleted, branch + commit SHAs, prod deploy status (URL + new bundle hash + sanity result), any new tech debt found.

---

## Spec body

### Status block

- **What IS in scope:** a "Start an organization" recruiting CTA on the landing page with create-org intent preserved through registration; a public `/help` index hub; a Help link in both the logged-out surface (PublicLayout footer + landing) and the authenticated nav (`Nav.jsx`); three new audience-oriented getting-started help pages (member / steward / delegate) wired from planning-agent-authored copy + screenshots; a dismissible post-creation empty-state pointer steering new stewards to the steward help; a fix to the stale "three demo organizations" copy.
- **What is NOT in scope:** pre-seeded topics or content on new orgs; any setup wizard; org templates (deferred to a pilot-derived future pass); fixing or expanding the other two demo orgs; video tutorials, real i18n, or AI-generated help; any change to the `CreateOrg` form fields themselves; ID verification (on hold).

### Locked decisions

- Help content authored by planning agent, wired verbatim by Code.
- No wizard; orphaned `SetupWizard.jsx` deleted; post-creation guidance is a dismissible pointer only.
- `/help` hub is a public route.
- Landing CTA preserves create-org intent across registration + email verification.
- New orgs are not pre-seeded with topics/content.
- Templates remain a future pilot-derived pass; ID verification stays on hold.

### Clusters

**Cluster F (Front door).**
- `pages/Landing.jsx` (route `/`, rendered via `LandingOrRedirect` inside `PublicLayout`; existing CTAs "Try the Demo / About the Project / Sign In" at ~lines 22–41): add a primary "Start an organization" CTA. Two-state behavior: authenticated → `/orgs/create`; logged-out → `/register?next=/orgs/create`.
- Intent preservation: `Login.jsx` already honors a `next` param (its `nextParam` branch), so reuse that mechanism. Verify the `next` target survives the email-verification round-trip (register → verify-email → resume) so the user lands on `/orgs/create`, not a generic dashboard; add minimal persistence only if verify drops it. Add a test for the intent side effect if any flow code is touched.

**Cluster H (Help discoverability).**
- New `pages/HelpIndex.jsx` at public route `/help`. Lists all help topics — the 7 existing plus the 3 new — grouped sensibly (e.g. "Getting started" for the three new audience pages, "How it works" for the existing concept pages). Mirror the sibling help-page container pattern (`max-w-3xl mx-auto px-4 py-8`, white section cards); `lucide-react` icons available.
- Logged-out entry point: there is **no public top-nav bar** — public pages render under `PublicLayout`, which has only a footer (GitHub / Why / Security & Trust / Privacy / Terms). Add a "Help" link to that `PublicLayout` footer, plus a secondary "Help" / "How it works" link on `Landing.jsx` itself.
- Logged-in entry point: `components/Nav.jsx` — add a "Help" link (→ `/help`) to the desktop nav (after the `Delegates` link, ~line 404) and the mobile menu (~line 615).
- `App.jsx`: register the `/help` route in the public routes block alongside the existing `/help/*` routes (~lines 214–222).

**Cluster C (New-user content + pages).**
- Three new help pages mirroring the existing pattern, copy wired verbatim from `phase43_help_content.md`:
  - `/help/getting-started-member` — "I just got invited / joined an org."
  - `/help/getting-started-steward` — "I just created an org."
  - `/help/getting-started-delegate` — "I just got approved as a public delegate."
- Register the three routes in App.jsx's public help block. (Public is fine; the content is non-sensitive and useful pre-auth.)
- Post-creation orientation: `CreateOrg` currently redirects the new steward to the org's admin-settings page (`urlFor(org, 'admin-settings')`). Add a dismissible empty-state pointer there (and/or on the org's empty proposals view) linking to `/help/getting-started-steward`. Dismissal persists per org/user via existing state patterns (follow whatever the codebase uses; do not introduce browser localStorage). Lightweight; not a wizard, not a multi-step overlay.

**Cluster X (Minor copy fix).**
- `pages/Demo.jsx`: the org list is fetched dynamically from `/api/orgs/demo`, but the surrounding prose hardcodes the count — "across three demo organizations" (~line 103) and "across all three orgs" (~line 114). On the live site only one demo org currently renders, so those count words are stale. Make them derive from the fetched list length (count-aware phrasing) so the copy is correct whether 1 or 3 orgs are served. First confirm what `/api/orgs/demo` actually returns in prod — the displayed count (1) and the seed (3 orgs exist in the backend) don't currently agree; reconcile the copy to what's actually shown.

### Operational notes

- The four clusters are largely independent; F and H can run in parallel, C depends on the content artifact, X is trivial cleanup.
- Keep new public pages visually consistent with the existing About / Why / help pages.
- The post-creation pointer is the smallest possible intervention — resist scope-creeping it toward a tour or wizard.

### Followups

- Roadmap: mark the front-door CTA + help hub + new-user help as shipped. Note that org **templates remain deferred to a pilot-derived pass** — the first real template comes from walking the first pilot org leader through creation live and capturing that config, not from synthetic archetypes.
- If the steward help page proves insufficient in real use, consider promoting parts of it into contextual in-app tips later (deferred; only on evidence).
- ID verification arc stays on hold until after this ships (Z's call, 2026-05-29).
