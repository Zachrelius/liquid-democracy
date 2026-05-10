# Liquid Democracy Platform — Future Improvements Roadmap

## Overview

This is the forward-looking planning doc for what the platform builds next. It replaces the prior pilot-readiness sequencing plan, which served its purpose: the platform is now feature-complete enough that a real org can be onboarded as soon as one is recruited. The prior doc is preserved as `Archive/future_improvements_roadmap 2026-05-09.md`; for shipped-work history see `PROGRESS.md` (Phase 9+) and `docs/PROGRESS_archive_phase1-8.md` (earlier).

### Operating context

- **Real-pilot signal is on an unknown timeline.** Z is recruiting but doesn't control when an org lands. The friend pilot (board game group) already paid out its main value during org-creation and invite-flow validation; it isn't expected to generate significant new feedback going forward.
- **Build cadence is not gated on user feedback.** When a real pilot lands, their requests preempt this list. Until then, items in this doc proceed on their own merits.
- **The AI coding team executes faster than human recruiting timelines.** "Wait for signal" is rarely the right answer when an item has clear standalone value.
- **Estimates remain in passes, not weeks.** Sequencing is by priority, not duration.

### Organizing principle

Three buckets:

1. **Active queue** — items worth dispatching in roughly the order listed. Priority order is approximate; specific dispatch order can shuffle based on what's convenient to bundle.
2. **Backlog** — real items, lower priority than the active queue. Picked up between active-queue passes or when something nudges them up.
3. **Research / open questions** — items needing design thinking before they're spec-ready. Discussed before built.

Plus standing rhythms (audit refresh, doc hygiene), a known-issues / tech debt section, and Tier 3 (scale-dependent or deployment-context-specific). Phase numbers are assigned at spec time, not in this doc.

Each active-queue and backlog item carries a brief rationale and rough scope sketch. Items with external dependencies or natural triggers note them.

---

## Active Queue

### 1. Org-Configurable Tie Resolution

**Why now:** Z's stated dislike of the current default — admin decides ties after the fact — is concrete and well-grounded. Resolving ties post-hoc is exactly the kind of decision that's controversial in the moment and uncontroversial when declared up-front. This has been on the deferred list for a while; it deserves to ship.

**Scope sketch:**
- Org-level setting selecting tie-resolution method, declared at org setup (or in admin settings, with the strong default being "set this once and don't touch it").
- Method options to consider: deterministic-arbitrary (alphabetical / earliest-created / seeded), broader-approval-base (in approval voting, the tied option co-approved with more additional options wins), earliest-cast-decisive-vote, status-quo-wins (if one option represents "no change"), multi-winner promotion (proposal allows N winners and there are N+1 tied options). Final method list is a design decision in the spec.
- Backend: tabulation layer reads the configured method and applies it during result computation rather than producing an unresolved tie.
- Frontend: org admin settings UI to select the method; per-method copy explaining the tradeoffs; results display surfaces "tie resolved by [method]" rather than waiting for admin action.
- Migration: existing orgs default to a sensible method (likely deterministic-arbitrary with seed) rather than preserving the manual-resolution behavior. Existing unresolved-tie proposals get handled as a one-time backfill.
- Help page section explaining when each method is appropriate.

**Non-goals for first pass:** Per-proposal override of org default (can come later); tie resolution for multi-winner STV beyond what `pyrankvote` already produces (its built-in handling is the baseline).

---

### 2. Public Delegate Pages

**Why now:** Liquid democracy as a system *is* the delegate ecosystem. Right now the public delegate surface is thin — there's a delegate profile with a bio field and a list of votes, but no real space for a delegate to introduce themselves, explain their thinking, or build the kind of accountable public identity that makes someone want to delegate to them. This is high-leverage for the platform's identity and a real differentiator vs. systems where delegation is anonymous or transactional.

**Scope sketch:**
- Expanded public delegate page with: longer-form intro / "about me" content (likely markdown), per-vote rationale explanations (delegate can attach a short writeup to their votes explaining why they voted that way), topic-by-topic positioning statements ("on housing I generally favor X"), and a clean URL surface.
- Per-vote rationale is the most novel piece — delegates leave a comment-like artifact tied to their vote that's visible to anyone viewing their public profile or the proposal's vote breakdown.
- Likely interactions with the comments system (Phase 10) — possibly the rationale is a special comment type, or possibly it's its own table. Spec should evaluate both.
- Frontend: redesigned delegate profile page; rationale-attached UI in the vote-cast flow for public delegates; "see delegate's reasoning" links wherever public-delegate votes appear.
- Backend: delegate-content tables, rationale CRUD endpoints, delegate-search ranking signals (so delegates with fleshed-out profiles surface higher than placeholder ones).
- Help page on "being a public delegate" — what to write, how to think about accountability.

**Non-goals for first pass:** Delegate-to-delegate Q&A, follower comments on delegate profiles, formal endorsement systems. Those are research-bucket extensions if the basic surface lands well.

---

### 3. Sustained-Majority Fix

**Why now:** The feature shipped in Phase 8 is currently known-broken and disabled by default. That's tech debt, not a deferred feature. It's not load-bearing for any current use case, but leaving a broken feature visibly disabled in admin settings is the kind of thing a real pilot org will ask about, and "we shipped it but it doesn't work" is an awkward answer.

**Scope sketch:**
- Diagnostic pass first: what specifically is broken? The Phase 9.8 C1 fix addressed `support_ever_established` in the worker; the Phase 12.8 audit Item 5 flagged `build_status` had a parallel bug in the read path. Whether one or both of those is the load-bearing issue here, or whether there's a third issue, needs a real look at the code before scoping the fix.
- Fix whatever the diagnostic surfaces. Likely scope: align worker and read-path semantics, ensure floor-breach logic correctly gates on prior establishment, verify the snapshot cadence matches the threshold-evaluation cadence, confirm the failure-mode transitions (`fail` / `extend` / `escalate`) work as specified.
- Browser-verify the full lifecycle on prod with a test proposal that crosses and re-crosses the threshold.
- Re-enable as a non-default org setting, with help-page documentation. Don't flip the platform default until at least one real org has used it successfully.

**Non-goals:** Real-time evaluation; sustained-majority metrics in deliberation phase; cross-org sustained-majority analytics. These were all deferred from the original Phase 8 scope and remain deferred.

---

### 4. Demo Data Cleanup + Easy Manual Reset

**Why now:** The demo deployment at `liquiddemocracy.us` is the platform's sales surface. Right now the demo data is functional (post-Phase-7C.1 it shows the privacy boundary correctly, voter names are realistic, etc.) but it's not curated for telling a compelling story about what liquid democracy *does*. A real pilot recruitment conversation is going to lead to "let me show you" — and the demo should be tight enough that it sells without needing Z to narrate around its rough edges.

**Scope sketch:**
- Demo data audit: walk through the demo as a first-time visitor would, list what's confusing / weak / missing. Likely findings: proposal mix doesn't show off the full feature surface (binary + approval + RCV + STV all need representative live examples in different lifecycle states); delegation graph is thin or doesn't tell a story; comments section is empty or near-empty; sub-orgs may or may not be exercised; sustained-majority once fixed should have an example.
- Curated proposal/vote/delegation/comment seed that exercises each feature as a coherent narrative — e.g., a "city housing policy" proposal with thoughtful comments and a visible delegation chain, an approval-vote "venue selection" proposal showing the option-attractor visualization at its best, an RCV election showing the Sankey, etc.
- **Easy manual reset path:** a single command (Railway CLI or a simple script Z can run) that wipes and re-seeds the demo data without touching schema or user accounts created on the demo org since last reset. The Phase 7C.1 idempotent additive seed mechanism is the foundation; the reset variant is the destructive sibling.
- Document the reset path in DEPLOYMENT.md so it's not tribal knowledge.

**Non-goals:** Auto-reset on a schedule (Z explicitly doesn't want this); preserving user-created content across resets (the reset is destructive by design); A/B-tested demo content optimization (real pilot recruitment is the signal that would justify that work).

---

### 5. Automated Accessibility Pass

**Why now:** Standard automated accessibility checks (Lighthouse, axe-core) are cheap, signal-independent, and catch a real subset of WCAG issues. The deeper audit — keyboard navigation flows, screen-reader compatibility, etc. — needs real-user signal or specialized expertise, which we don't have. But the automated layer is pure free wins and worth taking before any pilot org with accessibility needs lands.

**Scope sketch:**
- Run Lighthouse and axe-core against the major page surfaces: landing pages, login/register, proposal list and detail (all four voting methods), vote graph and Sankey, delegation pages, admin settings, role permissions matrix, notification preferences.
- Fix what the tools flag at the high-confidence level: missing alt text, color-contrast violations, missing form labels, missing ARIA on custom components, focus-trap issues in modals, keyboard-inaccessible interactive elements.
- Skip what the tools flag as low-confidence or that requires real-user judgment (e.g., screen-reader narrative quality, complex keyboard navigation patterns in the drag-to-rank UI).
- Document what was checked and what wasn't, so a future deeper-audit pass knows where to start.

**Non-goals:** Full WCAG 2.1 AA compliance audit (defer until pilot signal or specialized expertise); D3 visualization accessibility (text-based alternatives are real work, defer); i18n (separate item, backlog).

---

### 6. Notifications Polish

**Why now:** The Phase 13/13.x notification system shipped end-to-end (in-app, email, digest cadences, quiet hours, per-event preferences across four channels). It works. What's deferred is rigorous exercise — the friend pilot didn't generate enough volume to surface edge cases, and several end-to-end flows are still in the chrome-deferred verification queue. Worth a focused pass that drains the verification queue, surfaces any gaps, and finishes anything that's been hanging.

**Scope sketch:**
- Drain the chrome-deferred queue items related to notifications (items 5–7 in the passdown's queue: multi-org Item 22 routing; email/digest/quiet-hours/unsubscribe end-to-end; multi-recipient voting-opened priority).
- Audit the notification surface for any "checkbox exists but the underlying detection isn't wired" issues like the `floor_approached` event that was caught and removed in Phase 13.3. The fix-pattern is well-established now; running through the registry to confirm every event actually fires when its trigger condition is met is cheap insurance.
- Tech debt items from the audit doc that are notifications-adjacent: email theming centralization (audit Item 27 in the doc, deferred until a second org-scoped email exists — sustained-majority's notifications might be the trigger).
- If there are any "I expected a notification and didn't get one" situations Z has hit during dogfooding, fix those.

**Non-goals:** Notification analytics; SMS or push channels beyond what's shipped; per-event quiet hours (passdown follow-up item, backlog).

---

### 7. Tech Debt Audit Refresh

**Why now:** The 2026-05 audit was a Phase 12.8 artifact. Items have accumulated through 13.x, 14, 15, and 16. The passdown explicitly flags this as a recurring rhythm — every ~10 phases warrants a refresh. We're roughly there. Audit refreshes also tend to surface low-cost cleanups that bundle nicely into a single pass.

**Scope sketch:**
- Walk PROGRESS.md from Phase 13 forward, codebase TODO/FIXME grep, and any new items surfaced during recent passes.
- Classify into the same TECH_DEBT / Z_ACTION_PENDING / MANUAL_VERIFICATION_GAP lanes, tier-assigned same as before.
- Bundle Tier-1 fixes into the same pass (the "audit-then-fix-in-same-merge" pattern from Phase 10.2 / 12.8 / 15).
- Update the existing `docs/tech_debt_audit_2026-05.md` rather than creating a new file (consistent with how it's been edited through several closeouts already).
- Roadmap Known Issues section gets reconciled against the updated audit.

**Trigger nudge:** If the deferred-items count crosses ~30, this jumps higher in priority. Right now it's around the level where a refresh starts paying off.

---

### 8. AI Delegation Agents — Polis Seed Statements

**Why now:** Smallest of the three AI-delegation surfaces, with a real tactical payoff: removing friction from the most labor-intensive part of running a Polis conversation (writing the seed statements). Z has emailed Polis about API access; if that lands, this item becomes immediately spec-able. If Polis declines and self-hosting is the only path, this item bumps Polis self-hosted (currently in research) into the active queue as a prerequisite.

**Scope sketch:**
- Configurable at org level and/or per-proposal: "auto-generate seed statements from proposal description and context." Off by default; opt-in.
- Backend: Anthropic API (or compatible) call generating ~5–10 candidate statements; admin-review step before they're sent to Polis; ability for admin to edit/reject candidates before publication.
- Polis API integration: depends on `data-api` access (waiting on Polis email reply) or self-hosted instance.
- Cost handling: this is an org-pays or platform-pays decision. For the embedded-Polis case where the platform is Anthropic-on-the-hook, set a per-org rate limit. Document clearly that this feature uses paid AI inference.
- Frontend: admin UI in proposal-create or polis-create flows to opt in, review generated statements, and publish.

**Hard dependency:** Polis API access (external). If `data-api` isn't available and self-hosting isn't pursued, this item parks until one or the other resolves.

**Non-goals for first pass:** Public AI delegates; private AI advisors; AI-driven moderation of human-submitted statements; AI-summarization of conversation outcomes (could be a later add-on).

---

## Backlog

Items below are real, but not actively prioritized. Picked up between active-queue passes when there's a natural fit, or pulled forward if a trigger condition (real pilot, dogfooding signal, dependency unlock) makes them more relevant.

### Live-Poll Mode UX

The fractional voting durations from Phase 16 enable sub-day voting windows (down to 0.05 days = 72 minutes). There's no dedicated UX for "live poll" framing — a meeting-context use case where votes happen synchronously over minutes, not days, with everyone watching the result update. Worth a pass once there's a use case driving it, but no current one. Real value if a pilot org runs in-meeting decisions.

### Org-Level Invite-Link Generation

A single URL anyone can use to auto-join an org (with whatever join-policy gate the org has set). Currently invitations are per-email. The passdown flags this as a follow-up. Useful for orgs with rapid onboarding (e.g., conference attendees joining a deliberation org), low-priority otherwise.

### Public Org Browser (`/explore`)

A discovery surface for public orgs. Useful once 2+ public orgs exist; speculative until then. Phase 14's public landing pages are the prerequisite; this builds on them.

### Onboarding / Empty-State UX

When a new user signs up and isn't yet in an org, what do they see? When a new org has zero proposals/members, what's the steward's experience? These first-impression surfaces have accumulated cruft as the platform's grown past their original assumptions. Worth a focused pass when there's signal (or before a recruited pilot org's first session, if one is imminent).

### End-User Documentation

Help pages are mostly written for stewards/admins. There's no "I just got invited, what do I do?" flow doc. Low-cost, real value once non-Z users start showing up.

### Delegate Report Cards / Alignment Scoring

Useful for large orgs with many public delegates and voting history; low-priority until that scale exists. Auto-generated metrics: voting record, alignment with delegator majority, topic-by-topic alignment scores, what-if comparison ("you would have voted differently 12% of the time"). Real product surface, defer until there's a real ecosystem to sort through.

### Alternative Delegation Strategies

Tag-weighted priority, majority of delegates, weighted majority. The delegation engine already supports the parameter; the UI doesn't. The currently-unused tag-percentage strategy is the closest to a near-term need. Low priority until an org asks.

### AI Delegation Agents — Public AI Delegates

Org- and/or user-configurable: AI-driven public delegates that read proposals, vote according to declared values, and explain their votes publicly. Real product surface; governance-adjacent (an AI delegate's accountability model differs meaningfully from a human's). Bigger than seed statements; smaller than private advisors. Picks up after seed statements lands and there's signal on whether the AI-delegation surface is something orgs actually want.

### AI Delegation Agents — Private AI Advisors

User-configurable: a personal AI prompted with the user's values, advising on votes and optionally auto-voting with summary or escalation-on-unclear. Largest of the three AI surfaces. UX is hairy — when does the AI auto-vote vs. escalate? How does the user audit the advisor's reasoning? The API key handling question is real here: at any scale, this needs to be user-BYO-key (the platform shouldn't be on the hook for usage bills tied to per-user advisors).

### Encrypted Ballot Storage

For deployments where the trust model needs to be stronger than "operators bound by audit logs and legal accountability." Real cryptographic work; user-side or escrowed key management; not a fit for current pilot scale. From the prior roadmap, kept here for completeness.

### Periodic Demo Data Auto-Reset

Z has explicitly said this isn't needed; the manual-reset path (active-queue item 4) is the preferred answer. Kept on the backlog for completeness — if demo traffic ever grows enough that manual reset becomes a chore, this becomes the answer.

### Formal Operator Agreements / Independent Oversight

The Security & Trust page's promise of "legal accountability for anyone operating the platform" is currently aspirational. Real institutional follow-through (operator terms, oversight body, accountability mechanisms) is governance work as much as technical, and gated on the platform reaching a scale where it actually matters. The Phase 7.5 work covered the technical access-restriction side; this is the institutional follow-through.

---

## Research / Open Questions

Items that need design thinking before they're spec-ready. Discussion-bucket, not dispatch-bucket.

### Group Governance Experiments — Platform Eating Its Own Cooking

This is the most distinctive item on the doc. The platform's value proposition is that organizations can govern themselves with liquid democracy; the platform itself is, currently, governed by a single-Steward hierarchy. Three sub-questions, all interconnected:

- **Multi-admin approval for some actions.** Destructive actions (deleting an org, removing a member, changing permission matrix) could require N-of-M admin agreement rather than a single admin's call. The data model from Phase 12 (configurable role permissions) is most of the prerequisite; what's missing is the workflow layer (a request that's pending until enough admins ratify it).
- **Operating without a Steward.** Currently every org has a Steward; what does it look like to have an org with only Admins, where authority is distributed? What breaks? What needs a designated final-decision-maker and what doesn't?
- **Electing Admins and Stewards via the voting system itself.** The flagship version. An org's leadership is itself the output of liquid-democracy votes. Term lengths? Recall mechanisms? What if the voting system has a bug and no one is elected? What's the bootstrap when the org is first created?

This is the kind of feature surface that genuinely differentiates the platform — a clear "look, the platform governs itself" demo story. It's also large enough that scoping it requires real design conversation. Worth its own discussion when Z is ready to design it; unlikely to be the next-up item but high-leverage when it ships.

### Polis Self-Hosted

Currently embedded-only; self-hosted was deferred as a deployment concern. **Conditional bump:** if Polis declines `data-api` access for the embedded version, self-hosting becomes the prerequisite for the active-queue item (AI seed statements) and bumps into the active queue. Tracking the Polis email reply.

If pursued: add Polis's Docker components to the platform's docker-compose configuration; deployment pattern documented; data sovereignty story documented for orgs that want it.

### AI Delegate API Key Handling

Cross-cuts all three AI delegation surfaces but is most acute for private advisors. The question: who pays for inference, and how is that billed/limited?

- **Platform-pays:** simple UX, but the platform is on the hook for usage at any scale, and abuse mitigation becomes a real engineering problem.
- **Org-pays:** org admin provides the API key, advisors within that org consume it. Reasonable for AI seed statements (org-driven). Awkward for private advisors (user-driven, org-billed).
- **User-BYO-key:** user provides their own API key. Cleanest separation but adds friction; many users won't have an API key.
- **Hybrid:** small free tier (platform-paid), then user-BYO for heavier use.

Worth its own design conversation before any AI delegation feature ships at scale, even though seed statements (active-queue) is small enough to land with a hardcoded answer.

### Org-Configurable Tie Resolution — Method Set

The active-queue tie-resolution item assumes the spec will pick a method set. The actual list of supported methods is itself a design question worth a conversation before specing. Candidates noted in the active-queue scope; final list TBD.

---

## Standing Rhythms

These aren't features; they're recurring activities that should happen on cadence.

- **Tech debt audit refresh** every ~10 phases. Currently item 7 in the active queue; recurs after.
- **Roadmap doc hygiene** at major arc transitions. The forward-looking doc should never get stale enough to be unrecognizable; archive + rewrite when it does. Prior versions live in `Archive/` with date suffixes.
- **Browser verification queue drainage** when Chrome is reliably available. Currently 8 items deep per the passdown; these accumulate every chrome-deferred pass. Worth a half-day every few passes to drain.
- **CLAUDE.md updates** when new operational lessons surface. Phase 15 G2 added the Tailwind footgun note; future passes should keep doing this proactively.
- **PROGRESS.md split** when the file crosses ~250 KB again. The Phase-1-through-8 split happened during Phase 11; the next natural cut would be around Phase 16 → 17 if it grows that way.

---

## Tier 3 — Long-Term or Scale-Dependent

Become relevant at larger scale or for specific deployment contexts. Not planned for the current build cadence.

### Native Mobile Apps

React Native or fully native. Only justified at scale where the PWA isn't sufficient.

### Citizens' Council Management Module

Random selection with demographic stratification, term management, meeting scheduling, expert testimony coordination, legislative drafting workflow feeding into liquid democracy votes. A module for a specific governance use case.

### Federation / Inter-Org Collaboration

Proposals and deliberations spanning multiple organizations with their own delegation structures, voting on a shared proposal.

### Formal Penetration Testing

Professional security firm audit. Required for municipal government adoption.

### End-to-End Verifiable Voting Integration

ElectionGuard or similar E2E-V technology for the highest-stakes votes in a graduated security model.

### Data Portability and Interoperability

Export/import standards for moving organizational data between platform instances or integrating with other civic tech tools (Decidim, CONSUL, Loomio).

### Quadratic Voting / Conviction Voting

Alternative voting mechanisms offered as additional proposal types.

### Blockchain Audit Trail (Optional)

Periodically hash the audit log and publish the hash to a public blockchain as a timestamped integrity proof. Not for voting itself.

### Subdomain-Based Multi-Tenancy

`gamenights.liquiddemocracy.us` style. Phase 11 explicitly kept this out of scope.

---

## Integration Ecosystem

### Confirmed Integration Candidates

| Platform | Purpose | Integration Type | Status |
|----------|---------|-----------------|--------|
| **Polis** | Structured deliberation | Embed (iframe + XID); self-hosted research | Embedded shipped Phase 9; self-hosted conditional |
| **GitHub** | Open-source contribution, issue tracking | OAuth login, repo links | Backlog |
| **Slack/Discord** | Notifications, community discussion | Webhooks, bot | With future notification expansion |
| **ElectionGuard** | E2E verifiable voting for high-stakes | SDK integration | Tier 3 |

### Potential Integration Candidates (Needs Research)

| Platform | Purpose | Notes |
|----------|---------|-------|
| **Loomio** | Small-group deliberation | Could complement Polis for committee-level discussion |
| **Decidim** | Participatory processes | Large platform with established municipal adoption |
| **All Our Ideas** | Pairwise idea prioritization | Could be used for agenda-setting |
| **ID.me / Login.gov** | Identity verification | For government-adjacent deployments |

---

## Known Issues / Tech Debt

For the canonical working list (resolved + deferred + Z-action items + manual-verification gaps), see `docs/tech_debt_audit_2026-05.md`. The audit doc is the source of truth; this section is a curated long-term-planning view.

The audit doc is due for a refresh (active-queue item 7) — entries have accumulated through 13.x / 14 / 15 / 16. Until the refresh ships, the doc's existing classifications are the reference.

Current high-level shape:
- ~25 deferred Tier-2 items, mostly small (1–2 hours each), waiting for natural bundling triggers.
- ~5 Tier-3 items needing real specing (alembic chain squash, flat-path deprecation, etc.).
- A handful of Z-action-pending items (Railway volume provisioning, prod diagnostic runs).
- Browser verification queue (8 items) blocked on Chrome connection availability.

---

## Contributing

If you're interested in implementing any item on this roadmap:

1. Open a GitHub issue referencing the item name.
2. Discuss the approach in the issue before writing code.
3. Submit a PR with tests.
4. Update this document when an item is completed or shifted.
