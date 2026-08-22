# Phase 99 — Pilot Page Preview and Public-Copy Truth Pass

**Status:** APPROVED FOR IMPLEMENTATION by Z on August 22, 2026. This pass deliberately publishes `/pilot` at its direct URL without promoting or linking it from the homepage, public navigation, footer, About page, or Security page. Z will review the built production page before a later activation pass changes that visibility.

## Goal

Ship a reviewable, production-quality pilot page and replace the materially outdated public Privacy, Terms, Security & Trust, and About claims.

The result is a safe preview release:

1. `/pilot` is public and usable by direct URL so Z can review the real responsive page;
2. ordinary visitors are not routed to it from the rest of the site;
3. search engines are told not to index or follow it during the preview;
4. the permanent inquiry pipeline, promoted navigation, and video integration wait for Z's page review and the separate recruitment-pipeline decision; and
5. the currently inaccurate self-hosted/demo-era public copy is corrected immediately.

## Branch and delivery

- Branch: `phase-99/pilot-page-preview`
- Merge: no-fast-forward to `master`.
- Push `master`, wait for Railway, verify the frontend bundle and backend deployment, and run production QA at the direct `/pilot` URL.
- One-line dispatch: `Read and execute phase99_pilot_conversion_and_public_trust_spec.md.`
- No new provider, subscription, recurring expense, production secret, analytics system, CRM, form vendor, or video-hosting configuration is authorized.

## What is in this pass

- A fixed public `/pilot` route and polished responsive page.
- `pilot` reserved against organization/sub-organization slug creation.
- Approved hosted-service Privacy and Terms copy.
- Approved targeted Security & Trust and About corrections.
- Shared `PublicLayout` around Privacy and Terms.
- Direct-email and demo actions on `/pilot`.
- Route, copy, accessibility, build, and reserved-slug tests.
- Direct-URL production browser QA.

## What is not in this pass

- No homepage hero, homepage pilot-section, public navigation, footer, About, or Security link to `/pilot`.
- No sitemap inclusion or search indexing of `/pilot`.
- No pilot-interest database table, API, internal admin queue, CSV export, acknowledgment email, or third-party form/CRM.
- No embedded video, video placeholder, YouTube iframe, YouTube privacy disclosure, CSP change, poster image, transcript, or video component.
- No organization recruitment, outreach, business-card change, or communication to prospective pilots.
- No new export, portability, self-hosting, account-deletion, SLA, certification, or legally binding election promise.
- No change to authentication, organization creation, voting, delegation, permissions, production data, or backup configuration.

The deferred activation work belongs in a later Phase 99a spec after Z reviews the page. That pass can remove `noindex`, add the approved prominent links, implement the selected inquiry destination, and add a click-to-load training video after a reviewed recording exists.

## Verification matrix

| Check | Required | Notes |
|---|---:|---|
| Fixed route test | Yes | `/pilot` loads logged out, logged in, and in a demo session; fixed route wins before any dynamic org-slug route |
| Reserved-slug tests | Yes | Both organization and sub-organization creation reject `pilot`; existing reserved-slug coverage stays green |
| Public-copy tests | Yes | Privacy, Terms, Security, and About contain the approved load-bearing claims and no superseded claims |
| Preview-isolation tests | Yes | No `/pilot` link in Landing, `PublicLayout`, About, Security, authenticated navigation, or footer; page emits `noindex,nofollow` |
| CTA tests | Yes | Direct-email CTA targets `support@liquiddemocracy.us`; demo CTA routes to `/demo`; no form submission path exists |
| Conditional-provider test | Yes | No YouTube/Google disclosure, iframe, external request, or CSP allowance ships in this pass |
| Frontend unit tests | Yes | Page sections, direct route, metadata cleanup, CTA targets, and preview isolation |
| Frontend build | Yes | Production build succeeds with no new warning |
| Focused backend tests | Yes | Reserved-slug suite |
| Full backend suite | Yes | Required because `backend/reserved_slugs.py` changes; no unexplained regression |
| Migration cycle / PG smoke | No | No database migration in this pass |
| Accessibility | Yes | Logical headings, keyboard focus, descriptive links, contrast, reduced-motion behavior, ~380px layout, and print readability |
| Browser QA | Yes | Production desktop and ~380px mobile direct-URL review, logged-out and logged-in, plus regression checks on `/`, `/privacy`, `/terms`, `/security`, and `/about` |
| Production delivery | Yes | Railway deployment matches merge, new frontend bundle is live, backend smoke passes, and production monitor remains healthy |

## Suggested team structure

- **Lead:** owns approved-copy fidelity, preview boundaries, integration, deployment, and closeout.
- **Frontend developer:** implements `/pilot`, public-copy pages, metadata, layout, and tests.
- **Backend developer:** adds the reserved slug and its tests, then supports the full backend gate.
- **QA teammate:** independently verifies the production direct-URL page, responsive/accessibility behavior, updated public copy, and absence of promotional links.

## Locked decisions

1. **Public contact:** `support@liquiddemocracy.us`.
2. **Offer:** the initial supported pilot is free and has no preset end date.
3. **Continuation:** continued use is welcome when the platform works for the organization.
4. **Support:** support is concentrated during setup and the first decisions, then becomes lighter as the organization becomes self-sufficient. Unlimited or permanently high-touch support is not promised.
5. **Future pricing:** no pilot organization is charged without advance discussion and express agreement.
6. **Adoption language:** “first supported external pilot(s)” is accurate. Example organizations and participation by friends/family are not represented as established organizational pilots.
7. **Initial fit:** roughly 20–200 known members, a committed steward, and meaningful but correctable decisions.
8. **Age:** do not imply the platform generally verifies age. State briefly that the hosted service is not directed to children under 13; optional age thresholds work only with identity verification.
9. **Export and self-hosting:** not included in the initial pilot. They may be considered as future features if requested, but must not be presented as existing or promised.
10. **Operator identification:** use the functional description “operated ... by the founder of Liquid Democracy” and the support email. Do not publish Z's home address or invent a company identity, governing-law clause, or arbitration clause.
11. **Preview visibility:** `/pilot` is intentionally unpromoted until Z reviews the built page.
12. **Video:** omit the entire video section until a reviewed video exists. Training/demonstration videos may later be hosted as Unlisted YouTube videos with click-to-load behavior.

## Implementation sequence

### Cluster B — Reserve the route

1. Add lowercase `pilot` to the canonical reserved-slug source in `backend/reserved_slugs.py`.
2. Preserve the existing case-normalization behavior.
3. Extend the existing parameterized tests so both top-level organization and sub-organization creation reject the slug.
4. Do not add a migration or touch existing organizations; any collision scan must be read-only.

### Cluster F — Correct the public trust copy

Use `docs/pilot_public_copy_review_2026-08.md` as the approved copy source. Product-fact corrections found during implementation may be made only when supported by code or current production evidence; report any material wording change in the closeout.

#### Privacy

- Replace the self-hosted template with the approved hosted-service policy.
- Include the actual data categories, visibility boundaries, provider roles, browser storage, security/backups, retention, request limitations, under-13 boundary, and `support@liquiddemocracy.us` contact.
- Accurately distinguish organization administrators, the ordinary platform-admin screen, the restricted reason-recorded API, and underlying operator database access.
- State plainly that the initial pilot does not include a complete export, portability package, or supported self-hosting migration package.
- **Omit every YouTube/Google provider or browser-storage disclosure in this pass.** Those paragraphs are conditional in the approved copy source and publish only with a playable video.
- Use the deployment date as `Last updated`.

#### Terms

- Replace the self-hosted template with the approved hosted-pilot terms.
- Retain the best-effort service boundary, appropriate-use exclusions, organization/member responsibilities, privacy/content terms, open-ended pilot continuation, future-pricing consent, current export/self-hosting limitations, disclaimer/liability savings language, changes, and contact.
- Do not add bracketed placeholders or invent operator identity/address, governing law, arbitration, indemnity, or jurisdiction-specific promises.
- Use the deployment date as `Last updated`.

#### Security & Trust

- Rename the demo-era deployment section to `About this hosted pilot service` and use the approved current monitoring, backup/restore, operator-access, and appropriate-use language.
- Update security-practice and provider paragraphs to the approved August 2026 facts.
- Clarify that the ordinary platform-admin screen has no ballot viewer; the exceptional unredacted audit-entry path is a restricted API requiring an entry ID and written reason, creates an audit event, and appears in the affected user's Data Access History.
- Retain the current non-pilot CTAs. Do not add a `/pilot` link.

#### About

- Change the adoption statement to `ready for its first supported external pilots`.
- Use the approved identity-verification wording, including that optional age thresholds depend on identity verification rather than general age enforcement.
- Add the approved monitoring and recovery summary.
- Update the `Get involved` prose to describe the intended pilot fit, but retain the demo, GitHub, and direct-email actions. Do not link to `/pilot`.

#### Shared layout

- Wrap Privacy and Terms in `PublicLayout`, matching About/Security public chrome.
- Preserve readable line length and current brand styling.
- Ensure no shared layout addition accidentally adds a Pilot link.

### Cluster P — Build the direct-URL `/pilot` preview

1. Add a dedicated `Pilot.jsx` page and register fixed route `/pilot` before dynamic organization routes.
2. Use `PublicLayout` but do not add `/pilot` to that layout's navigation/footer.
3. Set a descriptive document title and description while mounted. Add `robots` metadata of `noindex,nofollow` during this preview and restore prior head state on unmount.
4. Use the existing Liquid Democracy visual language: restrained brand colors, readable cards/sections, generous whitespace, real responsive behavior, and no generic stock imagery.
5. The written page must stand on its own without video.
6. Do not render a video heading, empty player, “coming soon” box, interest form, or fake form controls.
7. Make the page print cleanly enough to serve as the temporary one-page overview.

### Approved `/pilot` hierarchy and copy

Small line-length or accessibility edits are permitted without changing meaning.

#### Hero

- Eyebrow: `Supported organizational pilots`
- Headline: `Pilot Liquid Democracy with your organization`
- Body: `Give members a direct vote when they want one and the ability to delegate by topic when they do not. We are recruiting a small number of organizations for a supported, no-cost pilot of Liquid Democracy.`
- Primary CTA: `Request a pilot conversation` → a pre-addressed `mailto:support@liquiddemocracy.us` link with a concise pilot-interest subject; do not prefill sensitive body text.
- Secondary CTA: `Explore the live demo` → `/demo`.
- Trust line: `Best suited to known-member organizations making meaningful but correctable internal decisions. Not a certified public-election system.`

#### Member value

- Headline: `Representation without giving up your own voice`
- Explain direct voting, topic-by-topic delegation, immediate override/revocation, multiple voting methods, and accountable public delegates/private consent-gated relationships.

#### Initial fit

- Headline: `A good fit for the first supported pilot`
- Describe the strongest fit as roughly 20–200 known members, a committed steward, recurring decisions, and meaningful but reversible/correctable use.
- Include examples such as clubs, associations, cooperatives, volunteer networks, student/community groups, advocacy organizations, and committees.
- Clearly exclude governmental elections, legally mandated secret ballots, contentious officer elections, contract ratification, emergency decisions, and any process where an outage, error, or correction would create unacceptable harm.

#### What the pilot includes

- Headline: `Supported from setup to self-sufficiency`
- Show this sequence: discovery conversation; guided setup; steward rehearsal; one to three initial real but correctable decisions; check-ins and reflection.
- Explain that support is closest during setup and early decisions and becomes lighter as the organization becomes comfortable.
- Do not show a countdown, duration, end date, or timeline implying the organization should stop using the platform.

#### What the organization contributes

- Name a primary steward and backup contact.
- Recruit a genuine member cohort.
- Tell members the service is pilot-stage and explain how results will be used.
- Run at least one real, appropriate decision.
- Share candid feedback on comprehension, participation, workload, missing features, and trust.
- No public use of names, logos, quotes, or results without separate permission.

#### Privacy, security, and recovery

- Headline: `Honest boundaries, tested recovery`
- Explain institutional privacy versus paper-ballot secrecy in plain language.
- Say the ordinary organization-admin and platform-admin screens do not provide a routine ballot viewer. Describe the restricted reason-recorded API and underlying operator database access accurately but compactly.
- Summarize HTTPS, hashed passwords, short-lived/rotating credentials, permissions, audit logging, rate limits, monitoring, provider-native backups, encrypted offsite backups, and successful isolated restore rehearsals.
- State that identity verification is optional and that Didit processes documents when used; Liquid Democracy stores results/derived fields rather than raw ID images or document numbers.
- Link to Security & Trust, Privacy, and GitHub source.

#### FAQ

Include:

- `Does the pilot cost anything?` — free, no preset end, support tapers, continued use welcome, no future charge without express agreement.
- `How many members do we need?` — roughly 20–200 is the strongest range, but commitment and decision fit matter more.
- `Does everyone have to verify their identity?` — no; government-ID verification is optional and normally off unless needed.
- `Can administrators see how members voted?` — distinguish normal org-admin views, no ordinary platform-admin ballot screen, the restricted audited API, underlying operator access, and intentionally public/follower-visible activity.
- `Is this a legally binding election system?` — no; the organization determines authority and follows separate legal/procedural requirements.
- `Can we keep using the platform if the pilot works for us?` — yes; no preset end, lighter ongoing support, export/portability/self-hosting packages not included but possible future work.
- `What if we find a bug or need help?` — direct support contact and operational monitoring, but no uptime SLA or fixed response-time promise.

#### Closing action

- Headline: `Interested in trying it with your organization?`
- Explain that a finished plan is not required and ask only for enough context to understand the organization and possible use.
- Primary CTA: `Email about a pilot` → `support@liquiddemocracy.us`.
- Secondary CTA: `Explore the demo` → `/demo`.
- Add a short privacy reminder not to email member lists, ballots, identity documents, confidential disputes, or other sensitive personal information.

### Cluster T — Tests and source review

- Add focused tests for every new route, metadata behavior, CTA, and preview-isolation rule.
- Prefer stable semantic assertions over layout-class snapshots.
- Add regression assertions for the materially risky claims: no self-hosted template language, no claim that production is merely a demo, no claim of established real-organization adoption, no automated export/self-hosting promise, no YouTube disclosure before video, and no routine ballot-viewer claim.
- Run `git diff --check`, focused frontend tests, frontend production build, focused backend reserved-slug tests, and the full backend suite.
- No migration means no migration cycle or PostgreSQL smoke is required; state that explicitly in closeout.

### Cluster Q — Production verification

After merge, push, and deployment:

1. Confirm the Railway frontend and backend deployments match the pushed merge.
2. Confirm the new bundle is live and the backend smoke/readiness endpoint succeeds.
3. Open `/pilot` directly logged out, logged in, and in a demo session.
4. Verify desktop and approximately 380px mobile layouts, keyboard navigation, visible focus, links, reduced-motion behavior, and print preview.
5. Verify `noindex,nofollow` in the rendered document head.
6. Verify `/`, public navigation/footer, `/about`, and `/security` contain no `/pilot` link.
7. Verify Privacy, Terms, Security, and About display the approved updated copy and dates.
8. Verify no YouTube request, iframe, text disclosure, CSP addition, form submission, or new provider appears.
9. Verify the production monitor remains `ok` with zero unexplained issues.

## Visual-review handoff to Z

The closeout must give Z the direct production URL `https://www.liquiddemocracy.us/pilot` and call out that promotion remains **NOT STARTED**. Include screenshots or concise observations for desktop and mobile and identify any copy/layout choices the implementation team made beyond the spec.

Z's review should focus on:

- whether the page feels inviting rather than overly legalistic;
- whether the offer and ideal organization are immediately clear;
- whether the security/privacy section is appropriately candid without overwhelming the page;
- whether the free, open-ended pilot and tapering support model read correctly;
- whether the email and demo actions are sufficient before a permanent interest form exists; and
- what should change before Phase 99a promotes the page.

## Cost and risk controls

- Expected recurring-cost delta: $0.
- Do not enable analytics, CAPTCHA, a form/CRM vendor, YouTube, or a paid service.
- Do not change Railway variables, DNS, secrets, backup schedules, or provider configuration.
- Public direct-URL access is intentional, but discovery is minimized through the absence of internal links and `noindex,nofollow`.
- This is not a confidential preview; anyone who receives the URL can open and share it.

## Closeout contract

Report:

- per-cluster DONE / blocked / deferred;
- exact public-copy deviations, if any, with evidence;
- reserved-slug test delta and full backend count;
- frontend test count and production build result;
- no migration / PG smoke not required;
- desktop/mobile/keyboard/print production QA;
- direct URL, `noindex,nofollow` proof, and absence of promotional links;
- files changed and commit SHAs;
- no-ff merge, push, Railway deployment rows, frontend bundle hash, backend smoke, and production-monitor result;
- confirmation that inquiry intake, video, and promotion remain **NOT STARTED**; and
- the exact recommendations, if any, for Z's visual review before Phase 99a.
