# Phase 99b — Homepage CTA Balance

**Status:** APPROVED FOR IMPLEMENTATION from Z's August 23, 2026 live homepage review.

## Goal

Rebalance the homepage after Phase 99a overemphasized the explanatory `/pilot` page relative to functional ways of experiencing the platform.

Make exactly two user-facing changes:

1. promote `Browse public organizations` from a quiet tertiary link to the same full-button row as Pilot and Demo, including the repeated bottom CTA; and
2. remove the duplicate `Explore the supported pilot` button from the explanatory section immediately above the bottom CTA.

The intended hierarchy is “pilot first among peers,” not “pilot everywhere.” The explanatory pilot section remains, `/pilot` remains indexable, and the homepage continues to link to it. No pilot-page copy, organization behavior, routes, backend behavior, provider configuration, or additional promotion surface changes in this pass.

## Branch and delivery

- Branch: `phase-99b/homepage-cta-balance`
- Merge: no-fast-forward to `master`.
- Push and production-verify the homepage and linked destinations.
- One-line dispatch: `Read and execute phase99b_homepage_cta_balance_spec.md.`
- Expected recurring-cost delta: $0.

## Verification matrix

| Check | Required | Notes |
|---|---:|---|
| Focused frontend tests | Yes | CTA membership, order, reuse, and duplicate-pilot-button removal |
| Frontend suite | Yes | All configured frontend tests pass; Phase 99/99a contracts remain green except intentionally superseded CTA assertions |
| Frontend build | Yes | Production build succeeds with no new warning |
| Source review | Yes | `Landing.jsx`, its focused tests, this spec/status documentation, and closeout only |
| Desktop browser QA | Yes | Logged-out homepage shows a three-button primary row and three-link secondary row; bottom CTA shows the same three full buttons |
| Mobile browser QA | Yes | Approximately 380px, actions remain full-width/stacked, ordered, readable, and free of horizontal overflow |
| Auth-state regression | Yes | Logged-in and demo-user create/sign-in visibility remains exactly as before |
| Production sanity | Yes | New bundle live; `/`, `/pilot`, `/demo`, `/explore`, and monitor healthy |
| Backend suite | No | No backend source or behavior change |
| Migration / PG smoke | No | No schema change |

## Suggested team structure

Small pass: lead + one frontend implementer + QA. No backend developer is needed. The frontend implementer owns the two layout edits and focused source-contract tests; QA verifies the actual rendered hierarchy on desktop and mobile.

## Implementation

### 1. Promote Browse to a full button

In `frontend/src/pages/Landing.jsx`, move the existing `/explore` action out of `tertiaryLinks` and into `ctaButtons` after the demo action.

The full-button group must be ordered:

1. `Pilot your organization` → `/pilot` — retain the filled brand-primary treatment;
2. `Explore a demo org` → `/demo` — retain the outlined secondary treatment; and
3. `Browse public organizations` → `/explore` — use the same full outlined-button treatment as Demo, not the former quiet text-link treatment.

Do not create a second standalone Browse button. Because `ctaButtons` is already rendered in both the hero and bottom CTA sections, adding Browse to that shared group should produce it in both places.

For a logged-out visitor, the homepage hero should now read visually as two groups of three:

- full buttons: Pilot, Demo, Browse;
- quieter links: Create an organization, About the project, Sign in.

Preserve existing conditional behavior:

- `Create an organization` continues to use the auth-aware `startOrgTo`;
- demo users do not see the impossible create action;
- logged-in users do not see Sign in; and
- no filler link is added merely to force every auth state into a three-item second row.

### 2. Remove the duplicate explainer CTA

In the `Supported pilot` homepage section headed `Ready to try it with a real organization?`, remove the standalone button:

> Explore the supported pilot

Remove its surrounding `Link` element completely. Do not replace it with another button or inline pilot link.

Keep both explanatory paragraphs unchanged. The shared bottom CTA follows immediately after this section and already contains `Pilot your organization`, so another action inside the explainer is redundant.

### 3. Preserve the rest of Phase 99a

Do not change:

- the revised permanent-free or administrator-ballot FAQ copy;
- `/pilot` indexability, title, or description;
- the supported-pilot explainer prose;
- the corrected `Unions and locals` card;
- the pilot email actions;
- shared footer, About, Security, or authenticated navigation links;
- organization creation routing or demo-user fencing; or
- inquiry form, video, CRM, analytics, sitemap/SEO, or outbound recruitment state.

## Tests

Update `frontend/test/pilotPreview.test.js` or its current successor without weakening unrelated Phase 99/99a assertions.

Add or revise stable assertions proving:

- the `ctaButtons` definition contains `/pilot`, then `/demo`, then `/explore` in that order;
- `Browse public organizations` uses a full outlined-button treatment rather than the tertiary text-link block;
- `tertiaryLinks` does not contain `/explore`;
- `ctaButtons` is rendered in exactly the hero and bottom CTA locations;
- the `Supported pilot` explainer section contains its two approved paragraphs but does not contain `Explore the supported pilot` or a direct `Link`/button;
- the homepage still contains auth-aware organization creation, About, and logged-out Sign in;
- Pilot remains filled-primary and Demo/Browse remain outlined peers; and
- all pilot-page copy, indexability, no-form/no-video, and bounded cross-site-promotion assertions remain green.

Do not use a broad DOM snapshot. A small source-slice helper is acceptable for distinguishing `ctaButtons`, `tertiaryLinks`, and the explainer section.

## Production QA

After merge and deploy:

1. Confirm the new production bundle is live.
2. Logged out on desktop, verify the first row contains full buttons for Pilot, Demo, and Browse in that order; the quieter second row contains Create, About, and Sign in.
3. Confirm Pilot is visually first/filled while Demo and Browse are full outlined peers.
4. Confirm each button reaches `/pilot`, `/demo`, or `/explore` respectively through client navigation and fresh load.
5. Confirm the bottom CTA repeats the same three full buttons.
6. Confirm the supported-pilot explainer keeps both paragraphs and has no button; visually, it should lead naturally into the bottom CTA rather than duplicate it.
7. At approximately 380px, verify the full buttons and quiet links stack cleanly, preserve order, have visible focus, and cause no horizontal scrolling.
8. Logged in, confirm create routes directly and Sign in is absent. If a demo session is available, confirm the create link remains absent.
9. Confirm `/pilot` remains indexable and its Phase 99a copy is unchanged.
10. Confirm the production monitor remains `ok`.

If the browser bridge remains unavailable, report visual QA as blocked rather than inferring it from responsive classes. Source tests and HTTP/bundle checks do not replace the requested layout review.

## Closeout contract

Report:

- Browse-button promotion and explainer-button removal as DONE or identify any deviation;
- focused/all frontend test results and build result;
- desktop/mobile/auth-state browser results or an explicit blocked status;
- no backend change, backend suite not required;
- no migration, PG smoke not required;
- production bundle hash, route checks, and monitor result;
- files changed and implementation/no-fast-forward merge SHAs; and
- confirmation that pilot-page copy, inquiry form, video, CRM, analytics, sitemap/SEO expansion, additional navigation promotion, outbound recruitment, and elevated-ballot access remain unchanged/not started.
