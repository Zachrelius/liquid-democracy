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

### 2.2 AI Delegation Agents

**Problem:** Users who want to participate on every issue but lack time to read every proposal could benefit from AI assistance.

**Solution:** Two complementary approaches (as discussed in design sessions):

*On-device advisor (lighter touch):* A companion feature (not a separate system) that reads proposals, compares against the user's stated values/priorities, and generates voting recommendations with explanations. The user reviews and one-tap approves or overrides. From the system's perspective, every vote is a direct vote by a human — the AI never touches the platform.

*In-system AI delegate (heavier, regulated):* AI agents registered as a special user type (`user_type: ai_agent`, already in the data model) that can receive delegations and cast votes. Subject to the same or stricter transparency requirements as human public delegates. Requires confirmation model (silence ≠ consent for AI votes), public rationale for every vote, no AI-to-AI delegation chains, and operator-configurable caps on AI voting share.

**Data model support already exists:** `user_type` field, `ai_agents` and `ai_vote_drafts` table designs (in the architecture spec), delegation engine works unchanged for AI delegates.

**Estimate:** On-device advisor: 1-2 weeks. In-system AI delegate: 2-4 weeks including admin controls and monitoring.

### 2.3 Delegate Report Cards and Alignment Scoring

**Problem:** Voters have limited tools to evaluate whether their delegate is voting in ways that align with their values.

**Solution:** Generate automatic "report cards" for delegates showing: voting record, how often they voted with/against the majority of their delegators, topic-by-topic alignment scores, and a comparison view ("your delegate voted X, you would have voted Y based on your stated preferences on similar past proposals").

**Estimate:** 1-2 weeks including the alignment scoring algorithm and frontend display.

### 2.4 Accessibility Audit (WCAG 2.1 AA)

**Problem:** The platform hasn't had a dedicated accessibility review. For civic infrastructure, accessibility isn't optional — it's a requirement for inclusive democratic participation.

**Solution:** Systematic WCAG 2.1 AA audit covering: keyboard navigation, screen reader compatibility, color contrast, focus management, ARIA labels, form accessibility, and the delegation graph (which may need an alternative text-based representation for screen reader users).

**Estimate:** 1-2 weeks for audit and fixes.

### 2.5 Multi-Language Support / Internationalization

**Problem:** The platform is English-only, limiting adoption by non-English-speaking communities and international organizations.

**Solution:** Implement i18n using React's i18n framework. Extract all user-facing strings into translation files. Start with Spanish as the first additional language given US demographics.

**Estimate:** 1 week for infrastructure + 1-2 days per language for translation.

### 2.6 Advanced Analytics and Reporting

**Problem:** The current analytics dashboard shows basic participation metrics. Org admins and researchers need deeper insights.

**Solution:** Add analytics covering: delegation network health (concentration metrics, are a few delegates holding too much power?), participation trends over time, voter engagement lifecycle (new → occasional → active → lapsed), deliberation quality metrics (Polis consensus scores correlated with vote margins), and exportable reports for organizational governance reviews.

**Estimate:** 1-2 weeks.

### 2.7 Notification System (Email and In-App)

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
