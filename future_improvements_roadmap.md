# Liquid Democracy Platform — Future Improvements Roadmap

## Overview

This document consolidates all planned enhancements, optional modules, and integration ideas discussed during the design and development of the platform. Items are organized by priority tier based on their impact on the platform's value proposition and the effort required to implement.

This is a living document. Items should be moved to active development specs when they're ready to be built.

---

## Tier 1: High Impact, Near-Term

These improvements would significantly enhance the platform for pilot organizations and early adopters.

### 1.1 Polis Integration for Deliberation

**Problem:** The platform handles voting and delegation well but has no structured deliberation process. Proposals are voted on but there's no built-in way for the community to discuss, refine, and build consensus before a vote. This is the biggest missing piece — voting without deliberation is just polling.

**Solution:** Integrate with Polis (pol.is), the open-source AI-powered consensus-finding platform used by Taiwan's vTaiwan and many other civic processes.

**How Polis works:** Participants submit short statements and vote agree/disagree/pass on others' statements. Polis uses PCA and k-means clustering to identify opinion groups and surfaces "bridging statements" that find consensus across groups. It's designed for exactly the kind of large-scale deliberation that precedes a liquid democracy vote.

**Integration approach — two options:**

*Option A: Embedded Polis (recommended for first implementation)*

Polis provides an iframe embed that can be dropped into any web page. The integration would work like this:

1. When a proposal enters the "deliberation" phase, the system automatically creates a Polis conversation linked to that proposal (via the Polis API or admin creates one manually and pastes the conversation ID)
2. The Polis conversation is embedded in the proposal detail page's deliberation section via iframe
3. Users participate in the Polis deliberation directly within the platform — submitting statements, voting on others' statements, and seeing the opinion landscape evolve
4. Identity bridging via the XID system: pass the user's platform ID as the `data-xid` parameter in the Polis embed, so Polis participation is linked to the user's platform identity across sessions
5. When deliberation closes and the proposal moves to voting, the Polis results (consensus statements, opinion group breakdown) are displayed alongside the proposal as context for voters
6. Polis data export (via their `/api/v3/dataExport` endpoint) can be pulled into the platform for archival

*Option B: Self-hosted Polis (recommended for production)*

Polis is open source and can be self-hosted via Docker. For a production deployment, running your own Polis instance alongside the liquid democracy platform gives you full control over data, eliminates dependency on pol.is availability, and allows deeper integration. The Polis Docker setup (docker-compose with PostgreSQL, file-server, math worker, and client-participation components) could be added to the platform's existing Docker Compose configuration.

**Key technical details:**
- Polis embed uses a `<div>` with a script tag, configurable via `data-` attributes
- `data-xid` parameter links Polis participation to external user IDs — critical for connecting deliberation to voting
- `data-ucw` (user can write) and `data-ucv` (user can vote) can be toggled dynamically based on the proposal's phase
- Polis export API returns CSV/ZIP with summary stats, participant votes, comments, and group assignments
- Polis is free for nonprofits and government use on pol.is; self-hosting is always free

**Implementation estimate:** Embedded Polis (Option A) is probably 2-3 days of dev work. Self-hosted Polis (Option B) is a week including Docker configuration and testing.

**Deliberation-to-vote workflow:**
```
Proposal Created → Deliberation Phase (Polis active, statements & voting)
                 → Citizens' Council Review (if applicable)
                 → Voting Phase (Polis results shown as context, liquid democracy vote)
                 → Passed/Failed
```

### 1.2 Profile Pictures / Avatars

**Problem:** Users are represented by text names throughout the UI. Profile pictures make the platform feel more personal and make it easier to recognize delegates in the delegation graph.

**Solution:** Allow users to upload a profile picture. Store as resized images (128x128 and 48x48 thumbnails) in the server's static files directory or an object storage service (S3-compatible). Display in all locations where user names appear — delegation graph nodes, delegate selection modal, proposal author, follow requests, notification dropdown, nav bar user menu.

**Implementation:** Add an `avatar_url` field to the users model. Create an upload endpoint with image validation (file type, size limit ~2MB, resize on upload). Use a default generated avatar (initials-based, like GitHub's default) when no picture is uploaded.

**Estimate:** 1-2 days including frontend integration across all components.

### 1.3 Progressive Web App (PWA) Configuration

**Problem:** The web app works in mobile browsers but doesn't feel like an installed app — no home screen icon, browser chrome is visible, and there's no offline indicator.

**Solution:** Add PWA manifest and service worker configuration. This lets users "install" the app to their home screen where it launches without browser chrome, has an app icon, and shows a basic offline page when connectivity is lost.

**Implementation:** Create a `manifest.json` with app name, icons, theme color. Add a minimal service worker that caches the app shell and shows an offline fallback page. Configure Vite's PWA plugin for automatic service worker generation.

**Estimate:** Half a day.

### 1.4 WebSocket Real-Time Updates

**Problem:** Vote tallies and delegation changes currently require page refresh or polling to see updates. During an active voting window with many participants, this creates a stale-feeling experience.

**Solution:** Implement WebSocket connections (already specced in the original architecture) that push updated tallies to all connected clients whenever a vote is cast or delegation changes during an active voting window.

**Estimate:** 2-3 days including frontend subscription management and reconnection logic.

### 1.5 Proposal Comments and Discussion

**Problem:** Beyond Polis-style structured deliberation, users may want simple threaded discussion on proposals — asking questions, raising concerns, debating points.

**Solution:** Add a basic threaded comment system to the proposal detail page. Comments are visible to all org members. Markdown support for formatting. Reply threading (one level deep is sufficient). No real-time updates needed — refresh on page load is fine.

**Estimate:** 2-3 days.

### 1.6 Multi-Option Voting (Approval, RCV, STV)

**Problem:** The platform currently only supports binary votes (yes/no/abstain on a single proposal). Civic organizations have many decisions that naturally require more than two options — electing officers from a slate of candidates, picking an event date, choosing a name, selecting among several policy proposals. Forcing these into a sequence of binary votes is awkward and produces worse outcomes (vote splitting, spoiler effects, forcing artificial "this option vs that option" runoffs). If the platform supports these use cases natively, it handles the full range of an organization's voting needs — a significantly stronger adoption case than "use us for yes/no, something else for everything else."

**Solution:** Add multi-option proposals as a distinct proposal type alongside binary proposals. Proposal authors select a voting method at creation time. Launch with three methods, all integrated with the existing delegation engine and public delegate system:

- **Approval voting** (single-winner): Voters check all options they approve of. Option with the most approvals wins. Simple to explain, eliminates vote splitting, strategically robust. Good for: event dates, naming decisions, policy selection from a short list.
- **Ranked-choice / Instant Runoff (IRV)** (single-winner): Voters rank options. Lowest-ranked eliminated iteratively, votes redistribute, until one option has a majority. Good for: single-officer elections with 3+ candidates, multi-candidate policy decisions where majority preference matters.
- **Single Transferable Vote (STV)** (multi-winner): Same ballot as IRV but for electing multiple seats proportionally. A minority with 30% support gets roughly 30% of the seats. Good for: electing boards, steering committees, delegates to parent organizations.

**Voting method availability is org-configurable.** Org admins can enable/disable each method via org settings. Some orgs will want to standardize on one method; others will want the full range. Binary voting is always available.

**Use established libraries for tabulation.** RCV and STV have well-known edge cases (tie-breaking during elimination, batch elimination, Meek vs. Scottish STV variants) that have caused real-world controversies. Use `pyrankvote` or equivalent rather than implementing from scratch. Approval voting tabulation is trivial (count approvals per option) so no library needed there.

**Delegation integration:**

- Delegators inherit their delegate's full ballot — the complete ranking for RCV/STV, the complete approval set for approval voting. Same mental model as binary: "my delegate's vote becomes my vote."
- Chain behavior semantics remain the same: chain behavior (accept_sub / revert_direct / abstain) only kicks in when the delegate submitted no ballot at all. A partial ballot (e.g., only ranking one option in a four-option race) inherits as-is, because that's a deliberate choice by the delegate.
- Multi-option voting works only with the **strict-precedence delegation strategy** at launch. The more exotic strategies from roadmap item 2.1 (majority-of-delegates, weighted-majority) require aggregating different ballots across delegates, which is its own research area (Kemeny-Young rank aggregation, proportional approval methods). Those remain binary-only for now; revisit when strategy 2.1 is built.

**Public delegate integration:**

- Public delegates' ballots are public on multi-option proposals, same as binary. A ranked or approval ballot is richer data than yes/no — more informative for delegators evaluating who to follow.
- Delegate profile pages get updated UI to display multi-option votes compactly (e.g., "approved 2 of 4 options" with hover to expand; "ranked 3 of 4" for RCV).
- Consider (not required at launch) displaying a "completion rate" metric on delegate profiles — how often they submit full vs partial ballots. Public delegates voting on behalf of many people should probably rank all options, and a visible metric nudges toward that norm.

**Interaction with sustained-majority windows:** Sustained-majority windows (see section 1.7) make the most sense for binary votes — "the new law doesn't pass unless support is durable." For multi-option elections, the natural expectation is usually "we need to pick someone/something." Making sustained-majority opt-in per proposal (and off by default for multi-option) is the right call. When sustained-majority is on for a multi-option proposal, the semantics are "stable result" — the computed winner (by whichever method) shouldn't change in the final portion of the window. This avoids the awkward binary-style "must maintain >50%" logic that doesn't map cleanly to approval or RCV.

**Data model changes:**

- `Proposal` gets a `voting_method` enum (`binary`, `approval`, `ranked_choice`), a `num_winners` integer (default 1), and a `sustained_majority_enabled` boolean (default true for binary, false for multi-option).
- New `ProposalOption` table: `(id, proposal_id, label, description, display_order)`. Binary proposals don't need this; multi-option proposals do.
- `Vote` gets a `ballot` JSON field for richer payloads: `{"approvals": [option_ids]}` for approval, `{"ranking": [option_ids]}` for RCV. Existing `vote_value` column stays for binary to avoid migration pain.
- `VoteSnapshot` stores full ballot data for multi-option proposals (needed because RCV/STV tabulation isn't a simple sum — you have to re-run the elimination from the ballots).
- `Organization.settings` (JSON) gets `allowed_voting_methods` field for org-level configuration.

**Frontend work:**

- Proposal creation form: voting method selector, options editor (add/remove/reorder options with labels and descriptions), num_winners field (conditional on RCV being selected).
- Proposal detail page: ballot UI that changes based on voting method. Approval = checkbox list. RCV/STV = drag-to-rank interface (reuse the DnD pattern from topic precedence).
- Results display: bar chart of approvals for approval voting; round-by-round elimination display for IRV/STV (standard visualization — shows each round, who was eliminated, how votes transferred).
- Delegate profile updates to display multi-option votes.
- Plain-language documentation page explaining each method ("When should I use approval vs. RCV?"). Pilot orgs will need this.

**Explicit non-goals at launch:**

- Plurality voting (vote splitting defeats the purpose; reform advocates universally consider it inferior)
- STAR voting, score voting, Condorcet methods (leaves surface area open for future additions; adding more methods later is easy once the architecture supports pluggable methods)
- Multi-winner approval voting (STV covers the proportional multi-winner case)
- Amendments during the voting window (changing options mid-vote is a mess; treat as separate feature)

**Estimate:** 4-6 weeks of focused work. Roughly: 1 week backend data model + ballot storage + tabulation integration, 1-2 weeks delegation engine extension and public delegate integration, 1-2 weeks frontend (proposal creation, ballot UI, results display), 1 week documentation and org admin configuration UI.

### 1.7 Sustained-Majority Voting Windows

**Problem:** Proposals currently pass based on a single snapshot at the close of the voting window. This is vulnerable to late-stage manipulation — a delegate casting a controversial vote in the final hours with no time for delegators to react — and rewards narrow, fragile majorities over durable consensus. The original platform design called for sustained-majority windows as a built-in correction mechanism, but the feature hasn't been implemented yet.

**Solution:** Implement configurable sustained-majority voting windows for binary proposals. The default behavior: a proposal must maintain >50% support throughout the voting window and must never drop below 45%. If it does drop below 45% at any point, it fails. This creates structural pressure toward durable consensus and gives delegators time to correct a controversial delegate vote.

**The feature is per-proposal and per-org configurable:**

- Org admins set a default (on or off) in org settings.
- Proposal authors can override the default on a per-proposal basis (with admin permission, depending on org settings).
- Configurable parameters: majority threshold (default 50%), drop-below floor (default 45%), window length (default 7 days).

**Multi-option interaction:** As discussed in section 1.6, sustained-majority is off by default for multi-option proposals and uses "stable result" semantics when on (the computed winner shouldn't change in the final portion of the window). The "must maintain majority throughout" logic doesn't map cleanly to approval or RCV.

**Failure handling — a design question worth surfacing:** What happens when a proposal fails the sustained-majority test? Three reasonable options, with real tradeoffs:

1. **Proposal fails, status quo wins** (simplest, matches binary "no" default). Good for binding legislation where "do nothing" is a valid outcome.
2. **Voting window extends automatically** (e.g., 48 hours additional). Good for close-call situations where a few more delegator reactions might clarify things. Risks indefinite extension if manipulation continues.
3. **Result declared "unresolved," escalated to org admin or citizens' council.** Good for high-stakes decisions where neither passage nor failure is acceptable without deliberation. Requires org-level governance structure to handle escalations.

The feature should support all three, configurable per-org with a reasonable default (option 1). This is the kind of design depth that makes sustained-majority more than just a flag — it's a real governance feature with org-configurable philosophy.

**Data model changes:**

- `Organization.settings` gets `sustained_majority_default` (on/off), `sustained_majority_threshold` (default 0.5), `sustained_majority_floor` (default 0.45), `sustained_majority_failure_mode` (fail/extend/escalate).
- `Proposal` gets `sustained_majority_enabled` override field (nullable — null means use org default).
- `VoteSnapshot` table (already exists) becomes the basis for sustained-majority checking. Snapshots need to be taken frequently enough (every few minutes during active windows) to catch drops below the floor. A background job evaluates snapshots against the threshold and marks proposals as failed when they drop below the floor.
- `Proposal.status` lifecycle extends: `voting → passed/failed/unresolved` (adding unresolved).

**Frontend work:**

- Proposal detail page: sustained-majority indicator when active, showing current support level and how close to the floor. Historical chart of support over the window.
- Admin settings page: sustained-majority configuration UI.
- Proposal creation form: sustained-majority toggle (if org allows per-proposal override).
- Notification when a user's delegated vote causes the proposal to approach the floor (gives delegators a chance to revoke before it fails).

**Explicit non-goals:**

- Real-time sustained-majority checking during the window. A background job running every few minutes is sufficient; finer resolution adds complexity without value.
- Sustained-majority for deliberation-phase metrics. This feature is about voting-phase stability only.

**Estimate:** 1-2 weeks. The core logic is a background job plus snapshot analysis; most of the work is the configuration UI, failure-mode handling, and frontend display.

---

## Tier 2: Medium Impact, Medium-Term

These improvements become important as the platform grows beyond initial pilots.

### 2.1 Alternative Delegation Strategies

**Problem:** The current "strict precedence" strategy (highest-priority topic's delegate wins) is simple and explainable but may not match every voter's preferences.

**Solution:** Implement additional delegation resolution strategies, selectable per user via the `delegation_strategy` field (already in the data model):

- **Strict precedence** (current): highest-priority topic's delegate wins
- **Tag-weighted priority**: delegate selection weighted by both topic precedence AND the proposal's topic relevance scores
- **Majority of delegates**: all delegates with applicable tags vote; majority determines the user's vote. Ties broken by precedence.
- **Weighted majority**: same as majority but votes weighted by topic precedence and/or relevance

The delegation engine is already structured as a pure function with a strategy parameter — adding strategies means writing new resolution functions, not refactoring existing code.

**Estimate:** 3-5 days for all strategies including UI for selecting strategy in user settings.

### 2.2 Configurable Organization Role Permissions

**Problem:** The current org role model is too coarse for real civic organizations. Admins have unlimited powers (unilaterally remove members, delete topics, delete proposals, manage invitations, etc.). The `moderator` role exists in the data model but has no special powers — moderators are effectively indistinguishable from regular members. Real organizations distribute governance across multiple trust levels: people trusted to run day-to-day operations (create proposals, approve new members) but not to unilaterally delete org assets, people trusted with destructive actions, and sometimes destructive actions that require multi-admin approval for high-stakes decisions.

This matters for adoption: any civic organization of meaningful size will want at least one tier between "full admin" and "regular member." Without it, either every trusted person gets full admin powers (too risky) or the one admin becomes a bottleneck for routine tasks like approving new members.

**Solution — staged implementation:**

*Stage 1 (initial build — data model + sensible default moderator powers):*

Build the permission system as a proper permissions-per-role data model from day one, but ship with a small set of sensible built-in role presets rather than a configurability UI. Specifically:

- New `role_permissions` model: `(role_id, org_id, permission_key, enabled)`. Role presets: `owner`, `admin`, `moderator`, `member`, each with a default permission set applied when the org is created.
- Default moderator powers: create proposals, edit own proposals while in draft, advance proposals they created through the lifecycle, approve pending member join requests, suspend members (but not remove them), edit topics (but not delete them).
- Default admin powers: everything moderator can do, plus delete proposals/topics, remove members, manage invitations, edit org settings, approve delegate applications.
- Owner: everything admin can do, plus transfer ownership and delete the org itself.
- Backend enforcement via a permission check helper (`has_permission(user, org, permission_key)`) called by every action endpoint. This replaces the current role-string comparison pattern in `org_middleware.py`.

*Stage 2 (later — full configurability UI):*

Add admin UI to view and edit the permission matrix per role. Org admins can:
- Toggle individual permissions on/off per role
- Create custom roles beyond the four defaults
- Require multi-admin approval for specified destructive actions (e.g., "deleting a topic requires 2 of 3 admin approvals")
- Copy permission sets between roles as starting points

*Stage 3 (future — action approval workflows):*

For actions gated behind multi-admin approval, a pending-actions queue where admins review and approve/deny each other's high-stakes actions before they take effect. Separate roadmap item when this becomes important.

**Rationale for staging:** The data model is the hardest part to get right — once permissions are keyed on enum strings and checked per endpoint, adding new permissions or changing defaults is straightforward. The admin UI for editing the matrix is purely frontend work that can be deferred. Shipping Stage 1 unblocks the most critical gap (moderators who can do day-to-day work) without requiring the full configurability UI upfront. Orgs that need non-default behavior during Stage 1 can ask the platform admin to adjust via direct database edits — acceptable for pilot-stage deployments.

**Data model changes:**

- New `role_permissions` table as described above, seeded with defaults on org creation.
- Permission keys defined as an enum in the codebase: `proposal.create`, `proposal.delete`, `proposal.advance`, `member.approve_join`, `member.suspend`, `member.remove`, `topic.create`, `topic.delete`, `org.edit_settings`, `delegate_application.approve`, etc. Start with ~15-20 keys covering the actions that currently exist.
- Backend: replace role string checks (`if user.role in ("admin", "owner")`) with `has_permission(user, org, "permission.key")` calls throughout `routes/organizations.py` and related files.
- Migration: existing orgs get default permission sets applied to their existing roles.

**Estimate:** Stage 1: 1-2 weeks (data model + migration + permission check helper + replacing all role-string checks + default preset UX where moderator role does something useful). Stage 2: 1 week (matrix editor UI). Stage 3: 1-2 weeks (approval queue + pending action handling).

### 2.3 AI Delegation Agents

**Problem:** Users who want to participate on every issue but lack time to read every proposal could benefit from AI assistance.

**Solution:** Two complementary approaches (as discussed in design sessions):

*On-device advisor (lighter touch):* A companion feature (not a separate system) that reads proposals, compares against the user's stated values/priorities, and generates voting recommendations with explanations. The user reviews and one-tap approves or overrides. From the system's perspective, every vote is a direct vote by a human — the AI never touches the platform.

*In-system AI delegate (heavier, regulated):* AI agents registered as a special user type (`user_type: ai_agent`, already in the data model) that can receive delegations and cast votes. Subject to the same or stricter transparency requirements as human public delegates. Requires confirmation model (silence ≠ consent for AI votes), public rationale for every vote, no AI-to-AI delegation chains, and operator-configurable caps on AI voting share.

**Data model support already exists:** `user_type` field, `ai_agents` and `ai_vote_drafts` table designs (in the architecture spec), delegation engine works unchanged for AI delegates.

**Estimate:** On-device advisor: 1-2 weeks. In-system AI delegate: 2-4 weeks including admin controls and monitoring.

### 2.4 Delegate Report Cards and Alignment Scoring

**Problem:** Voters have limited tools to evaluate whether their delegate is voting in ways that align with their values.

**Solution:** Generate automatic "report cards" for delegates showing: voting record, how often they voted with/against the majority of their delegators, topic-by-topic alignment scores, and a comparison view ("your delegate voted X, you would have voted Y based on your stated preferences on similar past proposals").

**Estimate:** 1-2 weeks including the alignment scoring algorithm and frontend display.

### 2.5 Accessibility Audit (WCAG 2.1 AA)

**Problem:** The platform hasn't had a dedicated accessibility review. For civic infrastructure, accessibility isn't optional — it's a requirement for inclusive democratic participation.

**Solution:** Systematic WCAG 2.1 AA audit covering: keyboard navigation, screen reader compatibility, color contrast, focus management, ARIA labels, form accessibility, and the delegation graph (which may need an alternative text-based representation for screen reader users).

**Estimate:** 1-2 weeks for audit and fixes.

### 2.6 Multi-Language Support / Internationalization

**Problem:** The platform is English-only, limiting adoption by non-English-speaking communities and international organizations.

**Solution:** Implement i18n using React's i18n framework. Extract all user-facing strings into translation files. Start with Spanish as the first additional language given US demographics.

**Estimate:** 1 week for infrastructure + 1-2 days per language for translation.

### 2.7 Advanced Analytics and Reporting

**Problem:** The current analytics dashboard shows basic participation metrics. Org admins and researchers need deeper insights.

**Solution:** Add analytics covering: delegation network health (concentration metrics, are a few delegates holding too much power?), participation trends over time, voter engagement lifecycle (new → occasional → active → lapsed), deliberation quality metrics (Polis consensus scores correlated with vote margins), and exportable reports for organizational governance reviews.

**Estimate:** 1-2 weeks.

### 2.8 Notification System (Email and In-App)

**Problem:** Users currently need to check the platform to know when proposals need their attention, when follow requests arrive, or when their delegation changed.

**Solution:** Configurable notification system with email digest (daily or weekly summary of pending actions) and in-app notification center (expanding beyond the current badge/dropdown). Users control notification preferences per category.

**Estimate:** 1 week.

---

## Tier 3: Lower Priority, Longer-Term

These become relevant at larger scale or for specific deployment contexts.

### 3.1 Native Mobile Apps (iOS / Android)

Build native mobile apps using React Native (sharing component logic with the web app) or as fully native apps. Adds push notifications, biometric auth, and native performance. Only justified at scale where the PWA isn't sufficient.

### 3.2 Citizens' Council Management Module

Digital tools for managing randomly selected citizens' councils within the platform: random selection with demographic stratification, term management, meeting scheduling, expert testimony coordination, and the legislative drafting workflow that feeds into liquid democracy votes.

### 3.3 Federation / Inter-Org Collaboration

Allow proposals and deliberations to span multiple organizations — e.g., several neighborhood associations in a city collaborating on a citywide policy recommendation, each with their own delegation structures but voting on a shared proposal.

### 3.4 Formal Penetration Testing

Engage a professional security firm for formal penetration testing and security certification. Required for municipal government adoption.

### 3.5 End-to-End Verifiable Voting Integration

For the highest-stakes votes (Tier 3 in the graduated security model), integrate ElectionGuard or similar E2E-V technology to provide cryptographic verification that votes were counted correctly, while maintaining the graduated security approach.

### 3.6 Data Portability and Interoperability

Export/import standards for moving organizational data between liquid democracy platform instances, or integrating with other civic tech tools (Decidim, CONSUL, etc.).

### 3.7 Quadratic Voting / Conviction Voting Options

Alternative voting mechanisms beyond simple yes/no/abstain: quadratic voting (allocate "voice credits" across proposals, paying quadratically — 1 credit for 1 vote, 4 credits for 2 votes, etc.) and conviction voting (continuous voting where support builds over time). These could be offered as alternative proposal types alongside the standard liquid democracy vote.

### 3.8 Blockchain Audit Trail (Optional)

For organizations that want additional tamper-evidence beyond the database audit log, periodically hash the audit log state and publish the hash to a public blockchain. This doesn't use blockchain for voting (which the security research argues against) but uses it purely as a timestamped integrity proof for the audit trail.

---

## Integration Ecosystem

### Confirmed Integration Candidates

| Platform | Purpose | Integration Type | Priority |
|----------|---------|-----------------|----------|
| **Polis** | Structured deliberation | Embed (iframe + XID) or self-hosted | Tier 1 |
| **GitHub** | Open-source contribution, issue tracking | OAuth login, repo links | Tier 2 |
| **Slack/Discord** | Notifications, community discussion | Webhooks, bot | Tier 2 |
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

This roadmap is open for community input. If you're interested in implementing any of these features:

1. Open a GitHub issue referencing the roadmap item number
2. Discuss the approach in the issue before writing code
3. Submit a PR with tests
4. Update this document when an item is completed or moved to active development
