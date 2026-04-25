# Liquid Democracy Platform — Future Improvements Roadmap

## Overview

This document is the canonical sequencing plan for all post-Phase-4 development. The platform is feature-complete enough to be pilot-ready, but the strategic goal is to reach **pilot-ideal** before recruiting any real organization. Once a pilot org is on the platform, breaking changes become expensive and fast iteration slows. Better to close the remaining gaps now, using internal testing for validation, than to rush to recruit and then be constrained by real users during the most important build-out period.

**Sequencing principle:** de-risk infrastructure changes before building features that depend on them, do cheap cleanup before stacking new complexity on top, and prefer passes that can be thoroughly internally tested with seed data over passes whose main value is only measurable with real users.

This roadmap reflects the sequence agreed on 2026-04-21, with subsequent insertions: Phase 7B (network graph) on 2026-04-22, Phase 6.5 (EA Demo Landing) on 2026-04-24, and Phase 7C (Sankey, split from 7B) on 2026-04-25. Earlier versions of this document are preserved in `Archive/`.

---

## Sequence

The passes are listed in the order they should be built. Each has a short rationale for its position. Detailed scope lives in the pass sections below.

1. **Phase 5 — Permission-Alignment Mini-Pass.** ✅ Complete. Cleanup of three clustered frontend/backend permission-alignment issues plus modal dialog replacement of blocking `alert()`/`confirm()` calls.
2. **Phase 6 — Multi-Option Voting Pass A: Approval Voting.** ✅ Complete. Full scaffolding for multi-option proposals (ballot storage, delegation engine branching, proposal-type-aware frontend, org config) shipped with approval voting. 136 backend tests passing (35 new). Suite J browser tests defined (15 tests). Toast success audit done. PostgreSQL smoke test pass — 2 deployment bugs fixed (Dockerfile CRLF normalization, start.sh bootstrap ordering).
3. **Phase 6.5 — EA Demo Landing and Public Deployment.** ✅ Complete. New public landing surface (`/`, `/about`, `/demo`), persona quick-login, demo-org auto-join on email-verify, Resend HTTP API for transactional email (Gmail SMTP blocked from Railway). Live at `https://www.liquiddemocracy.us` with HTTPS via Let's Encrypt.
4. **Phase 7 — Multi-Option Voting Pass B: RCV and STV.** ✅ Complete (2026-04-25). Ranked ballots on the Phase 6 scaffolding. Drag-to-rank UI (`@hello-pangea/dnd`), `pyrankvote==2.0.6` integration, multi-winner STV with fractional transfer display, round-by-round elimination breakdown, tied-final-round admin resolution. 191 backend tests passing (+46). Suite K 18/18. PostgreSQL smoke test pass. Live on prod with verified delegation inheritance. Network visualization redesign deferred to Phase 7B as planned.
5. **Phase 7B — Vote Network Visualization for Multi-Option.** Next up. Replaces the binary-only `VoteFlowGraph` with a method-aware visualization. Binary preserved as-is; approval and ranked-choice get a new option-attractor force layout where each option pins as a node and voters settle at force equilibrium based on their ballots. Includes the small fix for the proposal-list "0 of N votes cast" counter that's inaccurate for ranked_choice. Phase 7C (Sankey) is split off so this pass stays focused on the network graph design problem.
6. **Phase 7C — Round-by-Round Elimination Sankey for RCV/STV.** Standard Sankey-style visualization showing how votes transfer between options across elimination rounds. Standalone visualization that lives alongside the network graph on RCV/STV proposal detail pages. Split from 7B because it's a different visualization with its own design considerations and shares no code with the network graph.
7. **Phase 8 — Sustained-Majority Voting Windows.** The "stable result" semantics for multi-option need multi-option to exist, and it's governance-critical to have in place before any org runs binding decisions. Also validates our snapshot/tally infrastructure.
8. **Phase 9 — Polis Integration (Embedded).** Biggest single feature gap. Does meaningful work only with real deliberation content, so it benefits from the platform being otherwise feature-complete before we start.
9. **Phase 10 — Engagement Layer.** Proposal comments, profile pictures, PWA configuration. Small, loosely-related, low-risk. Good multi-agent dispatch material.
10. **Phase 11 — URL Routing Refactor.** Path-based org URLs (`/{org-slug}/proposals` etc.) as originally spec'd. Done after feature passes so we route a mature feature set once instead of reshuffling URLs repeatedly.
11. **Phase 12 — Configurable Role Permissions (Stage 1).** Replaces the hardcoded moderator-permissions scaffolding from Phase 4 Cleanup with a proper data-model-driven permission system. Save for near the end because the hardcoded version is functional and this is really about extensibility.

**Items deferred past this sequence:** alternative delegation strategies (2.1), AI delegation agents (2.3), delegate report cards (2.4), accessibility audit (2.5), i18n (2.6), advanced analytics (2.7), notification system (2.8), and all Tier 3 items. These remain valuable and are documented below, but they are not in the path to pilot-ideal.

**Note on time estimates:** Previous versions of this roadmap included week-long estimates per item. Those reflected human-team heuristics and have been removed — the multi-agent Claude Code team has been delivering passes in hours. Any estimate provided during planning should be calibrated to the team's actual pace, not the roadmap.

---

## Phase 5 — Permission-Alignment Mini-Pass

### Rationale

Three technical debt items from Phase 4 all stem from the same pattern: the frontend doesn't reflect the backend's permission reality. Fixing them together is cheaper than piecemeal, and doing it before the next feature pass means we start with a cleaner baseline. Bundled with this: replace blocking JavaScript dialogs (`alert()`, `confirm()`) with in-DOM modal/toast components. This is better UX and removes a real QA blocker — Claude-in-Chrome cannot interact with native dialogs, so any test path that hits an `alert()` or `confirm()` stalls.

### Scope

**Frontend permission alignment:**
- Admin route guard distinguishes admin-only pages from moderator-accessible pages (currently `AdminRoute` uses `isModeratorOrAdmin`, permitting moderators to access `/admin/settings` via direct URL even though it's hidden from nav)
- Admin Members page shows the correct member list when viewed by a moderator (currently shows 0 members — likely a backend query filter issue)
- Unverified users see disabled or hidden vote/delegate buttons rather than fully-accessible UI that errors on click

**Dialog replacement:**
- Replace all `alert()` calls with toast notifications (new component if one doesn't exist)
- Replace all `confirm()` calls with in-DOM modal dialogs (new component or reuse existing modal patterns)
- Audit the codebase for any remaining `window.alert` / `window.confirm` / `prompt` usage and convert

**Scope is intentionally narrow.** No new features, no refactoring outside these specific items, no URL routing work. Full spec in `phase5_spec.md`.

### Non-goals

- URL routing refactor (deferred to Phase 11)
- Notification system (deferred)
- Broader accessibility audit (deferred)

---

## Phase 6 — Multi-Option Voting Pass A: Approval Voting ✅ Complete

### Rationale

Ship the full multi-option voting scaffolding — ballot storage, delegation engine branching, proposal-type-aware frontend, org config — with approval voting as the only multi-option method initially supported. Approval has trivial tabulation (count approvals per option), which means if something breaks during internal testing, we know the bug is in the scaffolding, not the counting algorithm. Debugging a broken RCV implementation where you can't tell whether the bug is in ballot storage, delegation resolution, or tabulation is painful; de-risk by building scaffolding against the simplest case first.

### Scope

**Data model:**
- `Proposal.voting_method` enum (`binary`, `approval`, `ranked_choice`) — all three enum values defined now even though only binary and approval ship this pass. This avoids a migration for the enum in Phase 7.
- `Proposal.num_winners` integer (default 1) — relevant for RCV/STV later, no effect on binary or approval for now
- `ProposalOption` table: `(id, proposal_id, label, description, display_order)`. Binary proposals don't use it; approval proposals do.
- `Vote.ballot` JSON field for richer payloads: `{"approvals": [option_ids]}` for approval. `vote_value` stays for binary back-compat.
- `VoteSnapshot` extended to store ballot data for multi-option proposals
- `Organization.settings` gets `allowed_voting_methods` array, default `["binary", "approval"]` for new orgs

**Delegation engine:**
- Branch resolution on `proposal.voting_method`
- For approval: delegator inherits delegate's full approval set
- Chain behavior (`accept_sub` / `revert_direct` / `abstain`) only kicks in when delegate submitted no ballot at all; a partial approval set inherits as-is
- Strict-precedence delegation strategy only — other strategies (`majority_of_delegates`, `weighted_majority`) are binary-only for now and UI should reflect this

**Backend:**
- Proposal creation endpoint accepts `voting_method`, `num_winners`, and `options[]`
- Approval tabulation endpoint / logic (count approvals per option, identify winner(s))
- Results endpoint returns method-appropriate payload

**Frontend:**
- Proposal creation form: voting method selector, options editor (add/remove/reorder with labels and descriptions), conditional fields
- Proposal detail page: ballot UI dispatches on voting method — approval is a checkbox list of options
- Results display: bar chart of approvals per option with winner highlighted
- Delegate profile pages display multi-option votes compactly (e.g., "approved 2 of 4 options")
- Org admin settings: enable/disable voting methods per org

**Documentation:**
- Plain-language help page explaining approval voting ("when should I use this vs. binary?"). The page is extensible to RCV/STV in the next pass.

### Non-goals

- RCV, IRV, STV (Phase 7)
- Plurality, STAR, score, Condorcet methods (not planned)
- Multi-winner approval (Phase 7's STV covers the proportional multi-winner case)
- Amendments during the voting window (unrelated feature)
- Sustained-majority interaction (handled in Phase 8)

---

## Phase 6.5 — EA Demo Landing and Public Deployment ✅ Complete

### Rationale

Z is attending EA events in roughly the next week and wants something concrete to show. The platform is feature-complete enough to demo (binary and approval voting both work, multi-tenant orgs, public delegates, follow/permission system, delegation graphs for binary at least). The gap is that there's no public-facing entry surface — visitors arriving at `liquiddemocracy.us` would currently hit a login wall with no context about what they're looking at.

This pass is a tactical insertion ahead of Phase 7. It doesn't change the platform's voting/delegation behavior. It adds a marketing-style landing surface, makes one-click demo persona login work in production, wires real SMTP, and ships the platform to a real URL via Railway.

The longer roadmap is unchanged. Phase 7 (RCV/STV) resumes after this pass.

### Scope

**Public landing surface (frontend):**
- `/` landing page with hero, three CTA buttons (Try Demo / About / Sign In), brief feature pitches, footer
- `/about` project explanation, case for liquid democracy, GitHub link
- `/demo` persona picker (one-click login as alice/dr_chen/carol/dave/frank/admin) plus a register-your-own option
- Routing change: unknown URLs redirect to `/` instead of `/login`

**Backend:**
- New `is_public_demo` setting separate from `debug` — gates demo-specific behaviors in production
- New `POST /api/auth/demo-login` endpoint for password-free persona login (gated by `is_public_demo`)
- Auto-add new registrants to the demo org when `is_public_demo=true`
- `GET /api/auth/demo-users` exposed when `is_public_demo=true` (currently debug-only)

**Email transport (replaced Gmail SMTP after Railway block discovered):**
- Resend HTTP API integration via abstracted email service interface
- `email_service.py` refactored to support multiple transports (Resend for prod, console for dev)
- Documented Gmail App Password setup as fallback in DEPLOYMENT.md

**Railway deployment:**
- First-time setup: Railway account, GitHub integration, managed PostgreSQL, env var configuration
- DNS: `liquiddemocracy.us` pointed at Railway, HTTPS via Let's Encrypt
- Initial seed via `docker exec`
- End-to-end smoke test on the deployed instance (register, real email verification, vote, delegate)

**Documentation:**
- `DEPLOYMENT.md` updated with Railway + Resend guide, demo data management, deploy gotchas catalog (CRLF, apex domain, free-tier constraints)
- `PROGRESS.md` Phase 6.5 section with live URL

Full spec in `phase6_5_spec.md`.

### Non-goals

- Phase 7 (RCV/STV) — resumed after this pass
- Phase 11 URL routing refactor — demo uses current flat URLs
- Periodic demo data auto-reset (manual reset only for now, documented)
- Content moderation (Z monitors manually for the EA timeframe)
- Analytics, visitor tracking, multi-environment setup
- Demo-specific UI polish beyond the landing pages

---

## Phase 7 — Multi-Option Voting Pass B: RCV and STV ✅ Complete

### Rationale

Ranked ballots on top of validated scaffolding. Edge cases (tie-breaking during elimination, batch elimination, Meek vs. Scottish STV, partial rankings) live in the tabulation layer, isolated from the storage and delegation layers we've already validated.

### Scope

**Data model:**
- `Vote.ballot` payload extended to support `{"ranking": [option_ids]}` for RCV/STV
- No new tables — the `ProposalOption` table from Phase 6 is reused

**Backend:**
- `pyrankvote==2.0.6` integration for IRV and STV tabulation (library was flagged stale per the spec's 18-month threshold; team made deliberate choice given that algorithms are settled math, wrapped in service function for future swappability)
- Tabulation produces per-round breakdown for visualization (who was eliminated each round, vote transfers)
- Results endpoint extended to return round-by-round data

**Delegation engine:**
- Delegator inherits delegate's full ranking
- Partial ballots inherit as-is (a delegate ranking 2 of 4 is a deliberate choice)
- Same strict-precedence-only restriction as approval

**Frontend:**
- Drag-to-rank ballot UI for RCV/STV (`@hello-pangea/dnd`, reused DnD pattern from topic precedence)
- Round-by-round elimination text/table display via `RCVResultsPanel.jsx`. The richer Sankey-style visual ships in Phase 7C.
- STV multi-winner display (proportional results with winners per seat, fractional transfer display)
- Proposal creation form: `num_winners` field when RCV/STV is selected
- Org admin settings: enable RCV, STV independently

**Documentation:**
- Help page extended with RCV and STV explanations plus "when to use which method" guidance

### Non-goals

- Network visualization redesign for multi-option proposals (Phase 7B)
- Round-by-round elimination Sankey visualization (Phase 7C)
- Alternative delegation strategies with multi-option (Kemeny-Young rank aggregation, proportional approval) — deferred research areas
- Condorcet methods

---

## Phase 7B — Vote Network Visualization for Multi-Option

### Rationale

The current `VoteFlowGraph` is hardcoded for binary voting: green/red half-plane zones, "yes/no" labels, abstain bottom zone. For approval and ranked-choice proposals it renders nonsensically. This isn't a Phase 6 or Phase 7 regression — the underlying voting and tabulation work correctly. It's a visualization gap that needs dedicated design attention rather than being bundled with feature work.

### Direction (locked in 2026-04-22, refined 2026-04-25)

**Network graph: option-attractor force layout.** Each proposal option becomes a fixed/pinned node. Voters are subject to multiple simultaneous forces — attraction toward the options they approved (or ranked, for RCV), plus the standard voter-voter repulsion that keeps nodes from stacking. The simulation runs and each voter settles at force equilibrium, which is one position per voter. Voters with similar approval/ranking patterns naturally cluster together; voters with unusual or conflicting patterns end up centrally located.

This is a force-directed graph with extra attractor nodes — D3's existing force simulation handles the physics natively. Implementation is mostly force tuning, not algorithmic novelty.

**Linear ranking decay for RCV.** First preference pulls hardest (1.0), with weighted decay through lower preferences (0.66, 0.33, then a floor of 0.1 for rank 4+). Linear chosen over exponential because it keeps lower preferences visually meaningful.

**Mitigation controls for high option counts:**
- Toggle individual option attractors on/off
- Hover-to-isolate (voters strongly pulled toward hovered option highlighted, others dim)
- Hide voters who approved/ranked zero options
- Force parameters tuned empirically based on option count

**Binary voting stays as-is.** The current green/red clustering remains the binary visualization. New component dispatches on `proposal.voting_method` and routes to existing rendering for binary, new option-attractor rendering for approval and RCV.

### Scope

**Network graph:**
- Component refactor: `VoteFlowGraph` becomes a method-aware dispatcher; `BinaryVoteFlowGraph` extracts existing code unchanged; `OptionAttractorVoteFlowGraph` is new for approval and RCV
- Backend extension to `GET /api/proposals/{id}/vote-graph`: adds `options` array, `voting_method` field, and per-voter `ballot` field
- Method-appropriate `clusters` summary (yes/no/abstain for binary; option approval counts for approval; winner + round count for RCV)
- Method-appropriate detail panel when clicking voter nodes

**Bundled cleanup:**
- Fix proposal-list "0 of N votes cast" counter that's inaccurate for ranked_choice (vote count aggregator must count Vote rows regardless of which column is populated)

Full spec in `phase7B_spec.md`.

### Non-goals

- Round-by-round elimination Sankey (Phase 7C)
- Per-option overlap regions, tabbed-per-option, or other layout alternatives explored during planning but rejected
- Animation of vote transfers
- Migrating binary to the new architecture (binary visualization stays unchanged)

---

## Phase 7C — Round-by-Round Elimination Sankey for RCV/STV

### Rationale

Sankey-style flow visualization is the standard for showing how votes transfer between options across elimination rounds. It's a different visualization with different design considerations than the network graph — splitting it from 7B keeps each pass focused. The Sankey shares no code with the network graph; both can live alongside each other on the proposal detail page.

### Scope

**Sankey component:**
- New component for elimination flow visualization, rendered below the network graph on RCV/STV proposal detail pages
- Each elimination round is a column; voter blocks flow from option to option as eliminations transfer votes
- Round labels with eliminated option, transfer counts visible per round
- Reuses per-round tabulation data already returned by Phase 7's results endpoint — no backend changes expected

**Help page update:**
- Add explanation of how to read the Sankey

### Non-goals

- Animation of vote transfers between rounds (could be polish; not required for v1)
- Per-round network graph snapshots ("what did the graph look like at round 2")
- Sankey for binary or approval voting (these don't have rounds)

---

## Phase 8 — Sustained-Majority Voting Windows

### Rationale

The "stable result" semantics for multi-option sustained-majority need multi-option voting to exist. The feature is governance-critical — any org making binding decisions needs durable consensus protection — and doing it now means test proposals aren't running under snapshot-only semantics that we'd later have to migrate. Also serves as a forcing function to validate our `VoteSnapshot` infrastructure.

### Scope

**Data model:**
- `Organization.settings`: `sustained_majority_default` (bool), `sustained_majority_threshold` (default 0.5), `sustained_majority_floor` (default 0.45), `sustained_majority_failure_mode` (enum: `fail` / `extend` / `escalate`)
- `Proposal.sustained_majority_enabled` nullable override (null = use org default)
- `Proposal.status` lifecycle extends with `unresolved` status
- `VoteSnapshot` taken frequently enough to catch drops below the floor

**Backend:**
- Background job evaluates snapshots against threshold during active voting windows
- Drops below floor trigger failure mode:
  - `fail` — proposal moves to `failed` status
  - `extend` — voting window extended once (e.g., 48 hours); second drop still fails
  - `escalate` — proposal moves to `unresolved`, flagged for admin review
- Multi-option "stable result" semantics: the computed winner shouldn't change in the final N% of the window

**Frontend:**
- Proposal detail page: sustained-majority indicator showing current support level and distance to floor
- Historical chart of support over the window
- Admin settings UI for org-level configuration
- Proposal creation form: per-proposal override toggle (if allowed by org)
- Notifications when delegated votes cause approach to the floor

### Non-goals

- Real-time evaluation (per-minute background job is sufficient)
- Sustained-majority metrics in deliberation phase

---

## Phase 9 — Polis Integration (Embedded)

### Rationale

Biggest single feature gap — the platform can tally but can't deliberate. Done now, with the platform otherwise feature-complete, deliberation gets real content to test against: proposals with options (Phase 6-7), sustained-majority windows (Phase 8), the full permission/role model.

### Scope

**Option A (embedded) only.** Self-hosted deployment of Polis is deferred — it's a deployment concern, not a product concern, and pol.is is free for nonprofits and government.

- Proposal in `deliberation` phase automatically provisions or manually links a Polis conversation
- Polis iframe embedded in the proposal detail page's deliberation section
- `data-xid` parameter wires Polis identity to platform user ID
- `data-ucw` / `data-ucv` toggled based on proposal phase
- When deliberation closes and proposal moves to voting, Polis summary (consensus statements, opinion groups) displayed alongside the vote UI
- Polis data exported via `/api/v3/dataExport` and archived

### Non-goals

- Self-hosted Polis (deferred)
- Auto-generating statements from proposal content (potentially interesting but out of scope)
- Polis alternatives (Loomio, Decidim) — research items for later

---

## Phase 10 — Engagement Layer

### Rationale

Small, loosely-related polish items. Good multi-agent dispatch material — each component is independent and low-risk. Internal testing naturally drives prioritization within this phase if we hit gaps during earlier passes.

### Scope

**Proposal comments:** Threaded discussion on proposal detail pages. Markdown support. One level of reply threading. No real-time updates.

**Profile pictures:** `avatar_url` field on users, upload endpoint with image validation and resizing (128x128 and 48x48). Default generated avatar (initials-based) when none uploaded. Displayed in delegation graph nodes, delegate selection modal, proposal author, follow requests, notification dropdown, nav bar.

**PWA configuration:** `manifest.json`, minimal service worker caching the app shell, offline fallback page. Vite PWA plugin integration.

### Non-goals

- WebSocket real-time comments (comments refresh on page load)
- S3-compatible object storage for avatars (local filesystem sufficient for pilot-stage)
- Native push notifications (PWA adds home-screen install, nothing more)

---

## Phase 11 — URL Routing Refactor

### Rationale

Original architecture called for path-based org URLs (`/{org-slug}/proposals`). Current frontend uses flat URLs with org context in React state/localStorage. This is a cosmetic/UX deviation from spec that shipped in Phase 4c. Fixing it after feature passes means we route a mature feature set once, rather than churning URLs as features are added.

### Scope

- React Router configuration updated to path-based org routes
- All admin pages, proposal pages, delegation pages, user profiles re-routed
- Legacy flat URLs redirect to new path-based equivalents for a grace period
- `OrgContext` refactored to derive current org from URL rather than localStorage
- Deep links (email invitation links, notification links) updated to use new URLs

### Non-goals

- Subdomain-based multi-tenancy (path-based is sufficient and was the original choice)

---

## Phase 12 — Configurable Role Permissions (Stage 1)

### Rationale

Replaces the hardcoded `require_org_moderator_or_admin` scaffolding from Phase 4 Cleanup with a proper data-model-driven permission system. Done near the end because the hardcoded version works — this is really about extensibility for future role needs, not fixing a bug.

### Scope (Stage 1 only)

- `role_permissions` table: `(role_id, org_id, permission_key, enabled)`
- Permission keys defined as enum: `proposal.create`, `proposal.delete`, `proposal.advance`, `member.approve_join`, `member.suspend`, `member.remove`, `topic.create`, `topic.delete`, `topic.edit`, `org.edit_settings`, `delegate_application.approve`, plus whatever the final action set is
- Default permission sets seeded for `owner` / `admin` / `moderator` / `member` presets
- Backend: `has_permission(user, org, permission_key)` helper replaces all role-string comparisons throughout the codebase
- Migration: existing orgs get default permission sets applied to their existing roles

### Non-goals (deferred)

- Stage 2: admin UI for editing the permission matrix
- Stage 3: multi-admin approval workflows for destructive actions
- Custom roles beyond the four presets

---

## Deferred Features (Post-Sequence)

These remain valuable but are not in the path to pilot-ideal. They'll be revisited after Phase 12 based on what pilots actually need.

### Periodic Demo Data Auto-Reset

Phase 6.5 ships with manual demo data reset only. Once the demo gets real visitor traffic, an automated nightly or weekly reset will likely be wanted to keep the demo experience consistent. Implementation: scheduled job that wipes and re-seeds the demo org's data while leaving the schema and demo personas intact. Don't build until there's evidence it's needed.

### Additive Idempotent Seed Mechanism

Phase 7's RCV proposals didn't auto-apply on prod because `seed_if_empty.py` only runs on empty databases (correct behavior — we don't want to wipe visitor data). Future passes that add demo content currently require a manual re-seed to make the new content visible. Long-term fix: each phase's seed function checks whether its specific proposals exist (by stable identifier) and adds them if not. Adds the new content additively without wiping existing visitor data. Worth doing before Phase 9 (Polis demos benefit) but not blocking.

### Alternative Delegation Strategies (formerly 2.1)

Additional resolution strategies on top of strict-precedence: tag-weighted priority, majority of delegates, weighted majority. The delegation engine is already structured to support these via the `delegation_strategy` parameter. Restricted to binary voting; multi-option with these strategies is open research (Kemeny-Young, proportional approval).

### AI Delegation Agents (formerly 2.3)

Two complementary approaches: on-device advisor (AI recommends, user approves, every vote is direct) and in-system AI delegate (`user_type: ai_agent`, subject to strict transparency requirements — confirmation model, public rationale, no AI-to-AI chains). Data model already supports this.

### Delegate Report Cards and Alignment Scoring (formerly 2.4)

Automatic "report cards" for delegates: voting record, alignment with delegator majority, topic-by-topic alignment scores, and comparison views showing where a delegator would have voted differently.

### Org-Configurable Tie Resolution Methods

Phase 6 ships with admin-resolves-tie as the only mechanism. Long-term direction: orgs declare their tie-resolution method at org setup ("declared up front so it's much less controversial than in the moment"). Candidate methods: deterministic arbitrary (alphabetical, earliest-created, seed-based), broader-approval-base (tied option co-approved with more additional options wins), early-voting preference, multi-winner acceptance for proposals that allow it, status-quo-wins. Worth revisiting once we have real pilot data on how often ties happen and how orgs feel about resolution.

### Accessibility Audit — WCAG 2.1 AA (formerly 2.5)

Systematic accessibility review covering keyboard navigation, screen reader compatibility, color contrast, focus management, ARIA labels, form accessibility, and text-based alternatives for the delegation graph.

### Multi-Language Support (formerly 2.6)

i18n via React's framework. Extract user-facing strings into translation files. Spanish as first additional language.

### Advanced Analytics and Reporting (formerly 2.7)

Delegation network health metrics, participation trends, voter engagement lifecycle, deliberation-quality-correlated-with-vote-margins, exportable governance reports.

### Notification System — Email and In-App (formerly 2.8)

Configurable digests (daily/weekly) plus expanded in-app notification center. Per-category user preferences.

---

## Tier 3: Long-Term or Scale-Dependent

These become relevant at larger scale or for specific deployment contexts. Not planned for the path to pilot-ideal.

### 3.1 Native Mobile Apps

React Native or fully native apps. Only justified at scale where the PWA isn't sufficient.

### 3.2 Citizens' Council Management Module

Random selection with demographic stratification, term management, meeting scheduling, expert testimony coordination, legislative drafting workflow feeding into liquid democracy votes.

### 3.3 Federation / Inter-Org Collaboration

Proposals and deliberations spanning multiple organizations with their own delegation structures voting on a shared proposal.

### 3.4 Formal Penetration Testing

Professional security firm audit. Required for municipal government adoption.

### 3.5 End-to-End Verifiable Voting Integration

ElectionGuard or similar E2E-V technology for the highest-stakes votes in the graduated security model.

### 3.6 Data Portability and Interoperability

Export/import standards for moving organizational data between platform instances or integrating with other civic tech tools (Decidim, CONSUL, Loomio).

### 3.7 Quadratic Voting / Conviction Voting

Alternative voting mechanisms offered as additional proposal types alongside standard liquid democracy votes.

### 3.8 Blockchain Audit Trail (Optional)

Periodically hash the audit log and publish the hash to a public blockchain as a timestamped integrity proof. Not for voting itself.

### 3.9 Self-Hosted Polis Deployment

Add Polis's Docker components to the platform's docker-compose configuration for orgs that want full data sovereignty over their deliberations.

---

## Integration Ecosystem

### Confirmed Integration Candidates

| Platform | Purpose | Integration Type | Planned Phase |
|----------|---------|-----------------|---------------|
| **Polis** | Structured deliberation | Embed (iframe + XID); self-hosted deferred | Phase 9 |
| **GitHub** | Open-source contribution, issue tracking | OAuth login, repo links | Post-sequence |
| **Slack/Discord** | Notifications, community discussion | Webhooks, bot | With notification system |
| **ElectionGuard** | E2E verifiable voting for high-stakes | SDK integration | Tier 3 |

### Potential Integration Candidates (Needs Research)

| Platform | Purpose | Notes |
|----------|---------|-------|
| **Loomio** | Small-group deliberation | Could complement Polis for committee-level discussion |
| **Decidim** | Participatory processes | Large platform with established municipal adoption |
| **All Our Ideas** | Pairwise idea prioritization | Could be used for agenda-setting |
| **ID.me / Login.gov** | Identity verification | For government-adjacent deployments |

---

## Contributing

If you're interested in implementing any item on this roadmap:

1. Open a GitHub issue referencing the phase number or feature name
2. Discuss the approach in the issue before writing code
3. Submit a PR with tests
4. Update this document when an item is completed or moved to active development
