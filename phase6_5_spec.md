# Phase 6.5 — EA Demo Landing and Public Deployment

**Type:** Hybrid pass — small frontend feature work plus first production deployment.
**Dependencies:** Phase 6 PostgreSQL smoke test complete (current `master`, 136 backend tests passing, Docker stack verified working).
**Goal:** Get a working demo of the platform live at `liquiddemocracy.us` in time for upcoming EA events. Visitors land on a marketing page, can try the demo as a pre-built persona or register their own demo account, can browse the project's about page, and the platform actually sends email for verification flows. This is the platform's first public deployment.

---

## Context and Strategic Framing

Z is attending EA events in roughly the next week and wants something concrete to show people. Until now, the platform has been internal-test-only with the live URLs being `localhost`. This pass takes it from internal-only to publicly accessible at `liquiddemocracy.us`, with a landing page that gives visitors three clear paths: try the demo, learn about the project, or sign in (for any future real-org users).

**Important framing for the dev team:** This is not a pivot to "ship now, polish later." It's a tactical move to have a usable showcase for a specific window. The longer roadmap (Phase 7 RCV/STV, Phase 7B visualization, Phase 8 sustained-majority, etc.) is unchanged and resumes after this pass. The demo is the platform as it currently exists — binary and approval voting work, RCV doesn't yet, and that's fine for the EA timeframe.

**Strategic decisions already locked in (don't re-litigate):**

- **Real codebase, real deploy.** Same code as eventual production, same database, with demo data seeded. The demo org becomes a permanent fixture under its own slug; real orgs added later are naturally separated by `org_id` (which the codebase already does correctly via `OrgContext` and middleware). No separate sandbox.
- **Persistent demo data with manual reset for now.** Visitor-created proposals/votes/delegations persist across sessions. Periodic auto-reset is deferred — for the EA timeframe, low traffic plus Z's monitoring is sufficient. Visitors are told this on the demo page so they understand why others' content might be visible.
- **Two demo entry paths.** Pre-built persona pick (one-click login as alice/dr_chen/carol/admin/etc.) for friction-free exploration, or "register your own demo account" for visitors who want to experience the full onboarding flow.
- **Hosting on Railway, SMTP via Gmail App Password.** Both are appropriate for the demo stage. Z has no DevOps experience, and these are the simplest credible options. Migration to a more robust setup is post-Phase-12 work if/when needed.
- **Phase 11 URL routing refactor stays deferred.** Demo deployment uses current flat URLs. The new marketing pages (`/`, `/about`, `/demo`) sit at the root; the existing app keeps its current internal routes. Path-based org URLs (`/{slug}/proposals`) happen later in Phase 11.

---

## Scope

### Part A: Frontend — Public Landing Surface

The current root path `/` redirects to `/proposals`, which then redirects unauthenticated visitors to `/login`. That flow is wrong for a public demo — visitors should land on a marketing page, not a login screen. Replace this with three new public routes that don't require authentication.

**`/` — Landing page (`pages/Landing.jsx`):**

- Hero section with the project name, a one-line tagline (e.g., "An open-source platform for liquid democracy — vote directly or delegate to people you trust, on every issue, any time."), and three clear CTAs as buttons:
  - **"Try the Demo"** → `/demo`
  - **"About the Project"** → `/about`
  - **"Sign In"** → `/login` (existing page; for any real users, currently mostly unused)
- Brief secondary section below the hero with 3-4 short pitches of what makes the project distinct: topic-based delegation, instant revocability, transparent delegate accountability, multiple voting methods. Each is a sentence or two — not a wall of text.
- Footer with links to GitHub repo (Z's repo URL), `/privacy`, `/terms`.
- Visual treatment: clean, professional, warm. This is the first impression at EA events. Matches the platform's existing Tailwind palette so the transition into the app feels coherent.

**`/about` — About page (`pages/About.jsx`):**

- The case for liquid democracy: what's wrong with current democratic systems, what liquid democracy is, why it matters now (post-AI agency framing if Z wants — see notes below).
- What this specific platform is and why Z is building it. Include a brief acknowledgment that it's open-source and pilot-stage.
- Link to the GitHub repo prominently. Visitors who like the project should be able to find the code easily.
- Length: two-to-four screens of scrolling. Substantive but not academic. Z is an EA-adjacent audience's communicator — calibrate accordingly.
- Z should provide the actual copy for this page, or the team should write a draft for Z to edit. Don't ship Lorem Ipsum.

**`/demo` — Demo entry point (`pages/Demo.jsx`):**

- Brief intro: "This is a working demo of the liquid democracy platform. You can vote, delegate, and explore as one of these pre-built users, or register your own account to experience the full onboarding flow."
- **Note about persistent data:** "This is a shared demo. Anything you create — proposals, delegations, votes — will be visible to other visitors. The demo data is reset periodically." (Even though "periodically" currently means "manually when Z decides," the visitor doesn't need that detail.)
- **Persona picker section:** Card grid of 5-6 demo personas, each with a one-line description and a "Sign in as [name]" button. Each click logs the visitor in immediately as that user and lands them on `/proposals`.
  - **alice** (Voter Admin) — "A typical voter who delegates to experts on healthcare and economy. Also an org admin so you can see the admin tools."
  - **dr_chen** (Public Delegate) — "A public delegate on healthcare and economy. See what it's like to be trusted with others' votes."
  - **carol** (Direct Voter) — "Votes directly on every proposal. No delegations."
  - **dave** (Chain Delegator) — "Delegates everything to alice via global delegation. Useful for seeing chain behavior."
  - **frank** (New Voter) — "A user with no delegations or follows yet. Start fresh."
  - **admin** (Owner) — "Full org owner permissions. Create proposals, manage members, see analytics."
- **Register-your-own section** below the persona picker: "Prefer to start fresh? [Register a demo account] and you'll experience the full onboarding flow including email verification."
- The link goes to `/register` (which is just `/login` with the register tab — verify the existing flow works for new accounts joining the demo org, see Backend section below).

**Routing changes in `App.jsx`:**

- `/`, `/about`, `/demo` are public routes — no `ProtectedRoute` wrapper.
- The `Layout` component (which wraps the app with `Nav` and `EmailVerificationBanner`) is not used on these public pages — they get their own minimal layout (probably just a footer, no nav, since visitors aren't authenticated yet).
- The fallback `*` route currently redirects to `/proposals` — change this to redirect to `/` instead, so unknown URLs hit the landing page rather than auth-walling visitors.
- Existing authenticated routes (`/proposals`, `/delegations`, `/admin/*`, etc.) stay exactly as they are.

**Persona quick-login mechanics:**

The Phase 4d demo quick-switch login already exists at `GET /api/auth/demo-users` but is debug-only (`if not settings.debug: raise 404`). For the demo deployment, this needs to work in production. Options:

- **Option A:** Add a new setting `enable_demo_login: bool` (default False). Set to True in the Railway environment. Endpoint and login flow check this setting instead of `settings.debug`.
- **Option B:** Add a more general `is_public_demo: bool` setting that gates demo-related behaviors (the demo-users endpoint, the demo persona-picker route exposure, possibly future demo-specific behaviors like rate limits or content moderation).

Use Option B. It's a cleaner separation: `debug` continues to mean "developer-mode features like seed endpoints and time simulation," while `is_public_demo` means "this deployment is a public demo." They might both be true in dev, only `is_public_demo` is true in the demo deployment, and neither is true for an eventual real production deployment.

Add the setting in `backend/settings.py`. Wire `GET /api/auth/demo-users` to check `is_public_demo` (or keep debug as a fallback for local dev). When `is_public_demo` is True, the persona-picker endpoint returns the same data it does in debug mode.

Persona quick-login itself can use the existing `POST /api/auth/login` endpoint with the demo user's known password (`demo1234`), or for cleaner UX, add a new endpoint `POST /api/auth/demo-login` that accepts `{username}` and issues tokens without requiring a password — gated by `is_public_demo`. The new-endpoint approach is slightly more work but keeps the demo password from appearing in the frontend code, which feels cleaner. Use the new-endpoint approach.

### Part B: Backend — Production Readiness for Demo

**New settings (`backend/settings.py`):**

- `is_public_demo: bool = False` — gates demo-specific behaviors (persona picker, demo-login endpoint).
- Confirm SMTP settings (`smtp_host`, `smtp_port`, `smtp_user`, `smtp_password`, `from_email`) work as intended when populated. The infrastructure already exists from Phase 4b.
- `base_url` — the public URL of the deployment (`https://liquiddemocracy.us`). Used in verification email links and password reset emails. Already exists; just needs to be set correctly in Railway env vars.

**New endpoint:** `POST /api/auth/demo-login`

- Body: `{username: str}`
- Gated by `is_public_demo`. Returns 404 if not enabled.
- Validates username is in the demo persona allowlist (alice, admin, dr_chen, carol, dave, frank — same list as `/demo-users`).
- Issues access + refresh tokens for that user, same as normal login.
- Logs an audit event `user.demo_login` with the username and request IP, so abuse can be tracked.

**Registration flow for demo visitors:**

When a visitor uses "Register your own demo account":
- They go through the normal `/register` → email verification flow.
- After email verification, they should automatically join the demo org as a member. Check current behavior — it's possible registration currently leaves users orgless and requires them to find/join the demo org via `/orgs`. If so, add a small piece of logic: when `is_public_demo` is True, automatically add new registrants to the demo org (slug `demo`) as members on registration. This keeps the visitor flow smooth.

**`/api/admin/seed` in production:**

The seed endpoint is gated by `if not settings.debug: return 403`. For the demo deployment, we need to seed the initial demo data once, then never again automatically. Two options:

- **Option A:** Manually run `docker exec` against the deployed container to invoke the seed function. Slightly cumbersome but explicit and safe.
- **Option B:** Add a one-time bootstrap mechanism that seeds on first deploy if the database is empty.

Use Option A. Initial seed is a one-time operation Z does after deploy; documenting the command in `DEPLOYMENT.md` is sufficient. Don't risk accidentally re-seeding (and wiping visitor data) in production.

**Demo data reset mechanism:**

For now, manual only. Add a documented procedure in `DEPLOYMENT.md`:

> **Resetting demo data:** SSH into the Railway instance (or use Railway's web console). Run `docker exec -it backend python -c "from database import engine, Base; Base.metadata.drop_all(engine); Base.metadata.create_all(engine)"` to wipe the database, then the seed command from above to repopulate. Total downtime is approximately 30 seconds.

This is intentionally rough — a periodic auto-reset is a future improvement, but for the EA timeframe, manual is fine. The DEPLOYMENT.md note also serves as the "show your work" trail for what's planned.

### Part C: SMTP Wiring

Real email sending is required for the demo because:
- Visitors who register a demo account need verification emails to arrive in their actual inbox.
- Password reset works for any visitor who registers.
- The system actually feels "real" rather than half-broken.

**Setup steps for Z to perform** (the dev team should not do this since it requires Z's Google account):

1. In Z's Gmail account → Account → Security → 2-Step Verification (must be on first).
2. App passwords → Generate one for "Liquid Democracy Demo" (or similar label). Save the 16-character password.
3. Provide these env vars to Railway:
   - `SMTP_HOST=smtp.gmail.com`
   - `SMTP_PORT=587`
   - `SMTP_USER=liquiddemocracy.qa@gmail.com` (or whichever Gmail account is sending)
   - `SMTP_PASSWORD=<the-app-password>`
   - `FROM_EMAIL=Liquid Democracy <liquiddemocracy.qa@gmail.com>` (so the From: header looks reasonable)

**The dev team's job:**

- Verify the existing `email_service.py` works with Gmail's SMTP when these env vars are set (Phase 4b implemented async TLS via `aiosmtplib`, which should work with Gmail's `smtp.gmail.com:587`).
- Update `DEPLOYMENT.md` with a "Setting up SMTP for demo" section documenting the steps above (so Z can follow the playbook and so future deployments have it).
- Test the actual delivery: deploy with SMTP configured, register a fresh demo user, confirm the verification email arrives in the inbox within 30 seconds, click the link, confirm verification works.

### Part D: Railway Deployment

This is new infrastructure work for the project. The team should treat it as a real deliverable, not a quick adjunct. Document everything in `DEPLOYMENT.md` so it's reproducible.

**Steps:**

1. **Create a Railway account and project.** Z will need to sign up at railway.com if not already. Free tier is sufficient for the demo (no traffic, low resource use).
2. **Connect the GitHub repo.** Railway can deploy directly from GitHub on push. Configure to deploy from `master` branch.
3. **Provision PostgreSQL.** Railway has a managed PostgreSQL add-on. Provision it and grab the `DATABASE_URL` connection string from Railway's env vars.
4. **Configure backend service.** Railway should auto-detect the `backend/Dockerfile`. Set the necessary env vars:
   - `DATABASE_URL` (auto-injected by Railway when PostgreSQL is linked)
   - `SECRET_KEY` (generate a strong random value)
   - `DEBUG=false`
   - `IS_PUBLIC_DEMO=true`
   - `BASE_URL=https://liquiddemocracy.us`
   - `CORS_ORIGINS=https://liquiddemocracy.us`
   - SMTP env vars (Z provides per Part C)
5. **Configure frontend service.** Two options:
   - **Option A:** Deploy frontend as a separate Railway service using `frontend/Dockerfile`. nginx serves static files and proxies `/api/` to the backend service. Slightly more complex but matches the existing Docker setup.
   - **Option B:** Build the frontend statically (`npm run build`) and serve via Railway's static-site hosting or a separate static-host service. Simpler but diverges from the existing Docker architecture.
   - Use Option A — it matches what Phase 4a built and keeps the deployment story consistent.
6. **DNS setup.** Z needs to point `liquiddemocracy.us` (which they already own) at Railway. Railway provides DNS instructions for custom domains; Z follows them in their domain registrar's DNS settings. HTTPS is automatic via Railway's Let's Encrypt integration.
7. **Initial seed.** Once the deployment is healthy, run the seed command via `docker exec` (or Railway's web console) to populate demo data. Verify by hitting `/proposals` as a logged-in alice and confirming the seeded proposals are there.
8. **Smoke test the deployed instance.** Run through the same Phase 6 PostgreSQL smoke test against the deployed URL: register a fresh user, verify email (clicking the real link in the real inbox), log in, cast votes, delegate, confirm everything works. This is the production version of what Phase 6 completion verified locally.

### Part E: Documentation

Update `DEPLOYMENT.md` with:

- **Railway deployment guide:** step-by-step from "create a Railway account" to "site is live." Include screenshots if practical, env var reference, troubleshooting common issues (CORS, DATABASE_URL format, SMTP connectivity).
- **SMTP setup:** Gmail App Password procedure as documented in Part C.
- **Demo data management:** how to seed initially, how to manually reset.
- **Custom domain setup:** how to point a domain at Railway, how HTTPS works.

Update `PROGRESS.md` with a Phase 6.5 section covering what was built, what was deployed, and the live URL once it's up.

---

## Acceptance Criteria

**Frontend:**
- `liquiddemocracy.us/` shows the landing page with hero and three CTA buttons.
- `liquiddemocracy.us/about` shows the about page with project content.
- `liquiddemocracy.us/demo` shows the persona picker and the register-your-own option.
- Clicking a persona logs the visitor in as that user and lands them on `/proposals`.
- Registering a new demo account walks the visitor through email verification (real email sent and received), then automatically joins the demo org.
- All existing app routes continue to work for authenticated users.
- Unknown URLs (e.g., `liquiddemocracy.us/asdf`) redirect to `/`, not `/login`.

**Backend:**
- `is_public_demo` setting added and gates the persona-picker endpoint and demo-login endpoint.
- New `POST /api/auth/demo-login` endpoint works for the persona allowlist; returns 404 outside of public-demo deployments.
- Demo registrants automatically join the demo org when `is_public_demo=true`.
- All Phase 6 backend tests still pass.

**Deployment:**
- Site is live at `https://liquiddemocracy.us` with HTTPS.
- PostgreSQL backend, demo data seeded.
- Real SMTP works: a fresh registration triggers a real verification email that arrives in a real inbox.
- A complete end-to-end flow on the deployed site (register → verify → join demo org → cast vote → delegate) works without errors.

**Documentation:**
- `DEPLOYMENT.md` has the full Railway + Gmail SMTP guide.
- `PROGRESS.md` has the Phase 6.5 section.
- The live URL is documented in `PROGRESS.md`.

**Testing:**
- A new browser test suite (Suite K — naming intentional, this slots in before the eventual Phase 7 Suite L since 7 was originally going to use K) validates the public landing surface: can hit `/`, `/about`, `/demo` without auth; persona quick-login works; register-your-own flow works end-to-end including real email verification on the deployed site.
- Existing suites continue to pass.

---

## Out of Scope

- **Phase 7 (RCV/STV).** Resumes after this pass. The demo ships with binary and approval voting only — that's fine.
- **Phase 11 (URL routing refactor).** Demo uses flat URLs. Path-based org URLs come later.
- **Periodic demo data auto-reset.** Manual reset only for now. Documented in DEPLOYMENT.md.
- **Rate limiting beyond what already exists on auth endpoints.** Demo traffic is expected to be low; if it spikes, Railway will throttle or scale automatically.
- **Content moderation.** Visitors can technically create offensive proposals or delegate names. Acceptable risk for the EA timeframe — Z will monitor and manually clean if needed. Real moderation is a post-pilot concern.
- **Analytics or visitor tracking.** Not needed for an EA-stage demo. Add later if useful.
- **Demo-specific UI polish beyond the new pages.** The internal app stays exactly as it is. Visitors who click into `/proposals` see the same UI as developers do. No "demo banner" or watermarking.
- **Multi-environment setup (staging vs production).** Single deployment for now. Staging environments come later if/when there's a reason.

---

## Operational Notes for the Dev Team

- **This pass involves Z performing some setup steps personally** (Gmail App Password generation, Railway account creation, DNS configuration). The team coordinates with Z on these — write clear instructions in DEPLOYMENT.md and confirm Z has completed each step before proceeding to the next.
- **Z is non-technical for DevOps work specifically.** Treat Railway-and-DNS the way you'd treat a junior engineer's first deployment: clear step-by-step with verification at each stage. Don't assume Z knows what a CNAME record is.
- **Don't ship Lorem Ipsum.** The about page needs real copy. Either write a draft for Z to edit (preferred) or pause and ask Z to provide it. Same for the landing page tagline and the persona descriptions.
- **The persistent-shared-demo decision means visitor content survives.** Make sure the dev team understands this — they should not, for example, build a "wipe my session on logout" feature thinking it's helpful. The demo's value is partly the accumulated activity from prior visitors.
- **Suggested team structure:** Lead in delegate mode. Frontend dev for the new pages and persona-picker UX. Backend dev for the new settings, demo-login endpoint, demo-org auto-join. DevOps work (Railway setup, SMTP wiring, DNS) probably benefits from a dedicated teammate or being absorbed by the lead since it's interactive with Z. QA tests the deployed instance end-to-end at the end.
- **The deployment is a real deliverable.** "We built the pages and they work locally" is not done. Done means the live URL serves the demo and a fresh user can register and verify successfully against the deployed instance.

Report completion with: live URL, screenshots or short description of what visitors see at each public page, confirmation that real email verification works on the live deploy, any setup gotchas worth noting in DEPLOYMENT.md, updated PROGRESS.md excerpt.
