# Phase 99a — Pilot Copy Clarity and Homepage Promotion

**Status:** APPROVED FOR IMPLEMENTATION from Z's August 23, 2026 live-page review and explicit authorization to promote the revised page from the homepage.

## Goal

Make three narrow copy corrections on the deployed `/pilot` page and promote the corrected page from the public homepage in the same deploy:

1. remove an ambiguous publicity obligation from `What we ask from your organization`;
2. describe Liquid Democracy as free during and after the pilot, without implying anticipated future charges; and
3. answer the administrator-ballot question with a plain `No` before giving the minimum honest caveats;
4. make `Pilot your organization` the homepage's primary conversion action while preserving demo, discovery, self-service organization creation, About, and sign-in paths; and
5. remove the preview-only `noindex,nofollow` directive so the promoted page is indexable.

This is a frontend-only copy-and-promotion pass. It does not add `/pilot` to the shared footer, About, Security, or authenticated navigation; change ballot permissions; remove the exceptional audited API; or start inquiry, video, CRM, analytics, outbound recruitment, or a sitemap/SEO project.

## Branch and delivery

- Branch: `phase-99a/pilot-copy-and-promotion`
- Merge: no-fast-forward to `master`.
- Push and verify the production frontend bundle and the direct `/pilot` URL.
- One-line dispatch: `Read and execute phase99a_pilot_copy_clarity_spec.md.`
- Expected recurring-cost delta: $0.

## Verification matrix

| Check | Required | Notes |
|---|---:|---|
| Focused frontend test | Yes | Assert the two replacement FAQ answers and absence of the removed publicity sentence/old pricing/API-heavy wording |
| Frontend suite | Yes | Existing Phase 99 preview tests and all configured frontend tests pass |
| Frontend build | Yes | Production build succeeds with no new warning |
| Source review | Yes | Pilot copy, homepage CTA/copy, Pilot metadata, route comment, and tests only; no provider, API, permission, or backend behavior changes |
| Browser QA | Yes | Production `/` → `/pilot` journey plus direct `/pilot`, desktop and ~380px mobile |
| Homepage hierarchy | Yes | Pilot is the visually primary hero action; demo is secondary; browse/create/About/sign-in remain discoverable without five equal-weight buttons |
| Indexability | Yes | Pilot no longer creates or sets a robots `noindex,nofollow` tag; title/description setup and cleanup remain correct |
| Promotion boundary | Yes | Homepage links to `/pilot`; shared footer, About, Security, and authenticated navigation do not gain links in this pass |
| Production sanity | Yes | New bundle live; `/`, `/pilot`, and monitor healthy |
| Backend suite | No | No backend source or behavior change |
| Migration / PG smoke | No | No schema change |

## Suggested team structure

This is a small pass: lead + one frontend implementer + QA. No backend developer is needed. The frontend implementer owns the pilot copy, homepage hierarchy, metadata, and tests; QA independently verifies the homepage-to-pilot journey, responsive layout, indexability, and bounded promotion.

## Implementation

### 1. Remove the ambiguous organization obligation

In `frontend/src/pages/Pilot.jsx`, remove this list item from `What we ask from your organization`:

> Keep names, logos, quotes, and results private unless separate permission is given for public use.

Do not replace it with another bullet. The sentence was intended to express a mutual publicity rule, but in this section it reads as an unclear demand on the pilot organization. Liquid Democracy's clearer commitment not to use an organization's name, logo, testimonial, metrics, or case study without permission remains in the offline Pilot Participation Understanding; it does not need duplication on the conversion page.

### 2. State the permanent-free intent directly

Keep the FAQ question:

> Does the pilot cost anything?

Replace the answer with exactly:

> No. Liquid Democracy is free to use during and after the pilot. There is no subscription fee. Pilot organizations also receive hands-on setup and early support at no charge.

Remove the old sentence about future charges, advance discussion, and express agreement. It undersells a platform intended to remain free by introducing a pricing possibility that is not part of the product direction.

This change does not promise permanently high-touch support. The separate page copy explaining that hands-on support tapers as an organization becomes self-sufficient remains unchanged.

### 3. Lead the ballot-visibility answer with `No`

Keep the FAQ question:

> Can administrators see how members voted?

Replace the answer with exactly:

> No. Organization administrators can see membership and aggregate results, but not individual members' ballots. Members can choose to make some voting activity visible through public-delegate or follower settings. Because Liquid Democracy is a hosted service, the platform operator can technically access stored data; the Privacy and Security & Trust pages explain that narrow trust boundary.

Do not mention the endpoint, audit-entry ID, reason query, or other API mechanics in this pilot FAQ. Those details are accurate but make the answer sound evasive and are already disclosed on the Privacy and Security & Trust pages.

## Load-bearing access facts — no code change

The simplified FAQ remains accurate:

- An organization administrator does not receive individual-ballot access merely by administering an organization.
- A platform administrator is a separate account-level role requiring `User.is_admin=True`.
- The ordinary platform-admin frontend has no ballot viewer.
- A technical platform administrator with a valid authenticated API token can manually call `GET /api/admin/audit/ballots/{audit_log_id}?reason=...` using developer/API tooling. They must know the audit-entry ID and provide a nonblank reason.
- That endpoint returns the selected unredacted audit entry, creates `admin.audit_ballot_viewed`, and exposes the event in the affected user's Data Access History.
- The reason is an accountability record, not a second-person approval gate.
- The platform operator can also access the underlying hosted database. Direct database access is part of the hosted-service trust boundary and does not automatically create the application-level audit event.

The exceptional API remains useful as an accountable investigation path and should not be removed in this frontend-only pass. It is preferable to an operator silently using direct database access when a legitimate integrity investigation requires inspection.

## Homepage promotion

### 4. Establish a clear hero hierarchy

Refactor the shared `ctaButtons` block in `frontend/src/pages/Landing.jsx` as needed. Do not simply add a fifth equal-weight button.

The hero action hierarchy is:

1. **Primary filled button:** `Pilot your organization` → `/pilot`.
2. **Main secondary outlined button:** `Explore a demo org` → `/demo`.
3. **Quieter tertiary links below the main pair:**
   - `Browse public organizations` → `/explore`;
   - `Create an organization` → the existing auth-aware `startOrgTo`, hidden for demo users exactly as today;
   - `About the project` → `/about`; and
   - the existing `Sign in` link for logged-out visitors.

Preserve keyboard accessibility, visible focus, full-width mobile actions, and the existing auth/demo behavior. The primary pilot CTA is visible logged out and logged in.

The bottom homepage action should be focused rather than replaying every tertiary path:

- primary `Pilot your organization` → `/pilot`; and
- secondary `Explore a demo org` → `/demo`.

### 5. Replace the stale homepage pilot explainer

Replace the current `What "pilot stage" means` section—including the stale hardcoded test count and `mailto:z@liquiddemocracy.us` link—with:

- Heading: `Ready to try it with a real organization?`
- First paragraph: `Liquid Democracy is ready for its first supported external pilots. The platform is free to use, and pilot organizations receive hands-on help choosing settings, rehearsing the member experience, and running their first decisions.`
- Second paragraph: `Learn what a strong pilot looks like, what support is included, and the privacy and security boundaries before deciding whether it fits your group.`
- Prominent button: `Explore the supported pilot` → `/pilot`.

Do not put the permanent interest form on the homepage. The pilot page's existing email action remains the conversion endpoint for now.

Also correct the homepage `Unions and locals` audience card so it does not advertise initial-pilot uses that `/pilot` explicitly excludes. Replace its body with:

> Member resolutions, policy priorities, committee recommendations, and issue discussions. Give members a voice between meetings while keeping any separately required legal procedures outside the pilot.

Remove the homepage's current promotion of contract ratification, officer elections, and strike authorization. This is a public-copy consistency correction, not a removal of underlying platform features.

### 6. Make the promoted page indexable

In `frontend/src/pages/Pilot.jsx`, remove creation, mutation, restoration, and cleanup of the `meta[name="robots"]` element. Do not replace it with another robots directive. Preserve the page-specific title and description behavior and their cleanup on unmount.

Update the Phase 99 preview comment in `frontend/src/App.jsx` so it no longer says the route is direct-URL-only, absent from all public navigation, or marked `noindex`.

This pass does not add a sitemap, global SEO framework, structured data, or canonical-link system. Homepage linkage plus removal of `noindex,nofollow` is the complete indexing change.

## Tests

Update `frontend/test/pilotPreview.test.js` or the current successor test to assert:

- the page contains `No. Liquid Democracy is free to use during and after the pilot.`;
- the page contains `There is no subscription fee.`;
- the page contains `No. Organization administrators can see membership and aggregate results, but not individual members' ballots.`;
- the page does not contain `No pilot organization will be charged later`;
- the page does not contain `Keep names, logos, quotes, and results private`;
- the pilot FAQ does not contain `reason-recorded API`, `audit entry`, or endpoint mechanics;
- `Landing.jsx` contains a prominent `Pilot your organization` link to `/pilot` and a direct pilot-section link;
- `Landing.jsx` preserves `/demo`, `/explore`, auth-aware organization creation, `/about`, and sign-in paths;
- `Landing.jsx` no longer contains the old `z@liquiddemocracy.us` mailto, stale test count, or the three high-stakes union examples;
- `Pilot.jsx` no longer contains `noindex,nofollow` or manages a robots meta element;
- the page-specific title/description and cleanup assertions remain green;
- `PublicLayout.jsx`, `About.jsx`, `Security.jsx`, and authenticated `Nav.jsx` remain free of `/pilot` links in this bounded promotion pass; and
- existing mailto, demo-link, no-video, and no-form assertions remain green.

Use stable copy assertions rather than DOM snapshots. Replace the obsolete Phase 99 preview-isolation and noindex assertions with the new homepage-promotion, indexability, and bounded-promotion contract; do not merely delete them.

## Production QA

After the no-fast-forward merge and deploy:

1. Confirm the new frontend bundle is live.
2. Open `/` at desktop and approximately 380px mobile widths. Confirm `Pilot your organization` is the clear primary hero action, the demo is secondary, and browse/create/About/sign-in remain understandable and usable.
3. Follow the homepage primary action to `/pilot`; verify client-side and fresh-load routing.
4. Confirm the revised homepage pilot section and its `/pilot` button, the focused bottom CTA, and the corrected union card.
5. Confirm the organization-contribution list reads naturally after removing the last bullet.
6. Confirm the cost answer says the platform is free during and after the pilot and contains no future-pricing implication.
7. Confirm the administrator answer visibly begins `No.` and remains readable as one compact paragraph.
8. Confirm Privacy and Security & Trust still contain the detailed exceptional-access disclosure.
9. Confirm `/pilot` no longer emits `noindex,nofollow`; inspect the rendered document head after client-side navigation and a fresh `/pilot` load.
10. Confirm the shared footer, About, Security, and authenticated navigation do not gain `/pilot` links.
11. Confirm the production monitor remains healthy.

Routine copy changes may be browser-verified by the QA teammate without new screenshots if the closeout records the exact rendered sentences and viewport checks.

## Closeout contract

Report:

- all three pilot-page copy changes and all homepage-promotion work as DONE, or identify any deviation;
- focused/all frontend test results and build result;
- no backend change, backend suite not required;
- no migration, PG smoke not required;
- production bundle hash and homepage-to-pilot/direct-URL browser results;
- no-robots-directive proof and bounded-promotion regression result;
- files changed and commit/merge SHAs; and
- confirmation that inquiry form, video, CRM, analytics, sitemap/SEO expansion, additional navigation promotion, outbound recruitment, and changes to elevated ballot access remain **NOT STARTED**.
