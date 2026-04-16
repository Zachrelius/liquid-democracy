# Liquid Democracy Project — Knowledge Transfer Brief

## Purpose of This Document

This document captures the accumulated design decisions, reasoning, research, and strategic context developed over the course of designing and building a liquid democracy platform. It is intended to onboard new Claude instances who may assist with any aspect of the project — technical development, democratic theory, advocacy strategy, community building, or content creation.

Use this document as the starting brief when spawning a new instance. Point it to the relevant sections based on the task. For technical implementation details, also reference `PROGRESS.md` and the spec documents in the project directory.

---

## Part 1: Project Overview and Vision

### What this project is

An open-source liquid democracy platform that allows citizens or organization members to vote directly on proposals or delegate their voting power to trusted representatives on specific topics, with the ability to revoke and redirect those delegations at any time. Built as a web application (Python/FastAPI backend, React frontend, PostgreSQL database).

### The person behind it

The project creator (referred to as Z) is a US-based non-technical user who came to this idea through a novel plotline about a hopeful AI future. The concept evolved from fiction into genuine interest in real-world democratic reform. Z values being pushed back on with expert consensus rather than sycophantic agreement, appreciates blue-sky thinking grounded in real-world constraints, and prefers iterative exploration of tradeoffs to arrive at coherent system designs. Z is not a developer — they use Claude Code for implementation and Claude chat for planning and design.

### The core argument

Democracy needs to evolve to remain meaningful in the AI era. The current US system is captured by monied interests, offers voters a binary choice every few years, and is structurally unresponsive to constituent preferences. Liquid democracy — where citizens can vote directly on issues they care about and delegate to trusted experts on everything else, with instant revocability — offers a specific, buildable alternative. The message framing is: "Make government accountable to you, not the billionaires and corporations."

### What has been built (as of Phase 4 completion)

A pilot-ready platform with:
- Liquid democracy voting with topic-specific delegation and precedence ordering
- Non-transitive delegations with opt-in chain behavior (accept sub-delegation, revert to direct, or abstain)
- Tag-based proposal categorization with relevance weighting
- Sustained-majority voting windows (proposals must maintain support throughout a week-long window, not just pass at a single moment)
- Public delegate system with admin-controlled application/approval
- Follow/permission system for private delegation (mutual consent required)
- Delegation intent system (request to delegate, auto-activates when follow is approved, expires after 30 days)
- Interactive delegation graph visualizations (proposal vote flow and personal network)
- Multi-tenant organization support with admin portal
- Email verification, invitation system, password reset
- Audit logging of every state-changing action
- Docker deployment with PostgreSQL
- OWASP-reviewed security
- Privacy policy and terms of service

---

## Part 2: Key Design Decisions and Their Reasoning

These are the decisions that took significant discussion to arrive at. New instances should understand not just what was decided but why.

### The secret ballot tradeoff

**Decision:** The system explicitly trades traditional ballot secrecy for liquid delegation mechanics. Votes are private by default (visible only to followers and on public delegate topics) but the system structurally *can* know how your vote was cast because it must track delegation relationships.

**Reasoning:** Liquid democracy requires persistent identity-linked delegation records — the system must know you delegated healthcare to Dr. Chen to cast your vote when she votes. This makes technical ballot secrecy (nobody *can* know your vote) impossible. The system instead offers institutional privacy (the independent voting infrastructure agency and permission model protect your data through access controls and legal accountability). The argument is that continuous, revocable representation is a net gain in democratic power even with weaker ballot secrecy — the current system's secret ballot protects the moment of voting but provides zero accountability for what representatives do afterward.

### Non-transitive delegations with opt-in chains

**Decision:** Delegations are non-transitive by default. If your delegate doesn't vote, your vote isn't automatically passed to their delegate. Instead, you set a chain behavior preference: accept the sub-delegation (opt-in transitivity), revert to direct voting (you're notified to vote yourself), or abstain.

**Reasoning:** The German Pirate Party's experiment with LiquidFeedback used fully transitive delegations, which caused severe power concentration — a few delegates accumulated thousands of votes through cascading chains that delegators never explicitly authorized. Non-transitive delegation with opt-in chains preserves the voter's control while still allowing the convenience of chain delegation when the voter explicitly wants it. The notification-and-default system means voters can set their preference once and only be bothered when their delegate can't vote.

### Topic tags with precedence ordering (not taxonomy)

**Decision:** Proposals are tagged with multiple topics (each with a relevance weight). Voters rank their topics by precedence. When a multi-topic proposal needs delegation resolution, the voter's highest-precedence topic's delegate wins.

**Reasoning:** A rigid taxonomy (each proposal belongs to exactly one category) gives too much power to whoever categorizes proposals. Tags with voter-controlled precedence puts the voter in charge of how multi-topic conflicts are resolved. The relevance weighting on tags (how central each topic is to a given proposal) was added to support future delegation strategies like weighted-majority where topic centrality could influence vote resolution.

### Graduated security tiers

**Decision:** Three tiers of voting security matched to decision stakes: Tier 1 (digital/app) for routine legislation, Tier 2 (mail-in or supervised kiosk) for major legislation, Tier 3 (in-person paper with E2E verification) for constitutional questions and executive elections.

**Reasoning:** Expert consensus is that binding internet voting is not currently secure for high-stakes elections (the National Academies, Bruce Schneier, Ronald Rivest, and the broader security research community agree). Rather than dismissing this consensus or waiting for it to change, the system designs around it — using digital voting where the risk-reward calculation is favorable (distributed low-value-per-vote decisions) and physical voting where stakes require maximum security. This is an honest acknowledgment of limitations, not a compromise.

### Delegate security escalation

**Decision:** Security requirements scale with delegated power. Individual voters use the standard app. Delegates holding 100+ votes need government-secured devices. Delegates holding 10,000+ votes must use secured facilities.

**Reasoning:** A delegate holding 500,000 votes is an incredibly high-value target compared to an individual citizen casting one vote. Security investment should be proportional to actual risk.

### Sustained-majority voting windows

**Decision:** Proposals don't pass at a single moment. They must maintain >50% support throughout a week-long voting window and never drop below 45%.

**Reasoning:** This creates a built-in correction mechanism. If a delegate casts a controversial vote on Monday, delegators have until Sunday to revoke and shift the outcome. It structurally favors durable consensus over narrow, fragile victories and prevents the "snap vote" manipulation that pure direct democracy is vulnerable to.

### Public delegates vs. private delegation

**Decision:** Two tiers of delegates: public delegates who register with a bio and have their votes publicly visible (anyone can delegate to them), and private delegates who require mutual consent via a follow/approval system.

**Reasoning:** Public delegates are essentially running for representation continuously — they put positions out there and build a track record. This creates accountability without elections. Private delegation enables friend-to-friend trust relationships without exposing everyone's votes. The follow/permission system prevents surveillance (you can't unilaterally delegate to someone just to monitor their votes).

### AI delegation as a future module, not a core feature

**Decision:** The data model supports AI delegation (user_type field, delegation intent system) but AI voting agents are not part of the current implementation. When built, they'll operate under stricter rules: confirmation model (silence ≠ consent), mandatory public rationale, no AI-to-AI chains.

**Reasoning:** AI delegation is simultaneously the most powerful feature (your values applied consistently across hundreds of decisions) and the scariest to most people. Leading with it would kill adoption. The system is designed so AI agents plug into existing delegation mechanics without special treatment — an AI delegate is just a delegate with extra transparency requirements. There's an open design question about whether AI voting aids should be system-level delegates or on-device advisors (helping users decide how to vote directly). Both models are valid and may coexist.

### Multi-tenancy via org-scoped URLs

**Decision:** Each organization gets a path-based URL (`liquiddemocracy.us/boston-ea/proposals`). Data is partitioned by org_id. Users can belong to multiple orgs.

**Reasoning:** Subdomains would be cleaner technically but path-based routing was simpler to implement for the pilot. Self-hosting from the GitHub repo is also supported for orgs that want full data control.

---

## Part 3: Democratic Reform Research Context

### The broader reform agenda

The liquid democracy platform exists within a larger democratic reform strategy. The key pillars discussed:

**Court reform** is the keystone that enables everything else. The preferred approach: 18-year term limits for Supreme Court justices with staggered appointments (each president gets 2 per term), potentially applied retroactively from each justice's appointment date. This is arguably achievable by statute (rotating justices to lower courts, not removing them from the judiciary). Combined with a modest expansion (to 13, matching circuit courts). The framing "modernize the judiciary" polls far better than "pack the court."

**Campaign finance reform** downstream of court reform. Even before overturning Citizens United, federal small-donor matching (8:1 for donations under $175) would transform campaign incentives. The DISCLOSE Act (dark money transparency) has passed the House multiple times.

**Citizens' councils** (randomly selected deliberative bodies) can be created by Congress through regular statute with BRAC-style authority — Congress must vote yes or no on council-drafted legislation, no amendments. Ireland's citizens' assemblies are the proof of concept (87% of assembly members voted to liberalize abortion; the subsequent referendum passed with 66.4%).

**National Popular Vote Interstate Compact** currently has commitments from states representing ~209 of needed 270 electoral votes. Federal endorsement and conditional funding could help.

**Democracy Innovation Fund** — federal grants for cities and states experimenting with participatory budgeting, citizens' assemblies, liquid democracy, and alternative voting methods. Small money ($100-500M annually), frameable as "laboratories of democracy."

### Key organizations in the reform ecosystem

- **RepresentUs** — largest nonpartisan anti-corruption org, 168+ reform victories, model based on local wins building to federal
- **FairVote** — RCV advocacy, 50+ jurisdictions, 17M Americans served
- **Protect Democracy** — anti-authoritarianism litigation, $10M MacArthur grant
- **Brennan Center** — voting rights research and litigation, Democracy Futures Project
- **Project 2029 (Orlowitz version at project2029.me)** — grassroots, 800+ members, 27 issue areas, open to participation
- **Democracy 2025** — 700+ organization coalition for legal defense
- **Unite America** — election reform funding, $70M budget
- **Assemble America** — citizens' assembly advocacy, "Summer of Assemblies" 2026

### Real-world precedents for liquid democracy concepts

- **Switzerland**: 175 years of direct democracy, ~4 votes per year on ~15 questions, 600+ referendums
- **Taiwan (vTaiwan)**: Polis-based digital deliberation, resolved Uber regulatory impasse, 80% of issues led to government action
- **Ireland**: Citizens' assemblies produced marriage equality and abortion referendums
- **Estonia**: i-Voting with 51% online participation by 2023, X-Road digital infrastructure
- **German Pirate Party (LiquidFeedback)**: Only real-world liquid democracy test at scale; collapsed due to transitive delegation power concentration, privacy-transparency tension, and participation decay. ~40% of failure was structural, ~60% was context-specific
- **Porto Alegre participatory budgeting**: Water/sewer connections rose from 75% to 98%, model spread to 11,500+ processes globally

---

## Part 4: Technical Architecture Summary

### Stack
- Backend: Python 3.11+, FastAPI, SQLAlchemy, PostgreSQL, NetworkX (delegation graphs)
- Frontend: React 18+, Vite, Tailwind CSS, D3.js (visualizations), Recharts (charts)
- Infrastructure: Docker, Docker Compose, nginx, Alembic (migrations)
- Auth: JWT with refresh tokens, email verification, admin invitation system

### Core algorithm: delegation resolution

The delegation engine is a pure function (no database access) that takes user data, proposal topics, precedences, delegations, and direct votes, and returns the resolved vote for any user. Key steps:

1. Check for direct vote (always overrides delegation)
2. Find relevant delegation by matching proposal topics to user's topic precedences
3. Follow delegation to the delegate's direct vote (non-transitive by default)
4. If delegate didn't vote, apply chain behavior (accept_sub, revert_direct, abstain)
5. Cycle detection via NetworkX (per-topic graphs)

### Data model key entities

Users (with user_type, delegation_strategy, email, default_follow_policy) → Organizations (multi-tenant) → Topics (org-scoped, with colors) → Proposals (org-scoped, multi-topic with relevance weights, status lifecycle) → Delegations (user-to-user, topic-specific, with chain_behavior) → Votes (direct or delegated, with delegation chain metadata) → Audit Log (append-only, every state change)

Supporting: delegate_profiles (public delegate registrations), follow_requests/follow_relationships (permission system), delegation_intents (deferred delegation pending follow approval), invitations (admin invite flow), topic_precedences (per-user priority ordering)

### Security model

- Institutional privacy (access controls, legal accountability) rather than technical ballot secrecy
- Graduated security tiers matching verification to stakes
- OWASP Top 10 reviewed
- Audit logging of every action in same transaction
- Rate limiting on auth endpoints
- Markdown sanitization (nh3)
- Security headers, strict CORS
- Secrets via environment variables, never hardcoded

---

## Part 5: Development Workflow

### Agent roles that work well

- **Planning agent (Claude chat)**: Holds project vision, researches tradeoffs, pushes back on ideas, produces detailed specs. Brings visual/UX issues here when they need design direction.
- **Dev agent (Claude Code)**: Implements specs, writes tests, fixes bugs. Gets focused task descriptions with clear acceptance criteria. Should read PROGRESS.md at session start and update it at session end.
- **QA agent (Claude Code with Chrome)**: Executes browser test playbooks, reports findings. Does not modify application code. Separate instance from Dev to maintain tester independence.
- **Workflow consultant (separate Claude chat)**: Helps with tool setup, multi-agent coordination, meta-questions about process. Keeps the planning agent focused on the project.

### Key workflow patterns

- Detailed specs before any coding — the planning agent produces the spec, Dev executes
- PROGRESS.md bridges context between Claude Code sessions
- Browser testing playbook (Suites A-G) is a living document that grows with each phase
- Automated unit tests cover logic; browser tests cover integration; human review covers UX/feel
- Small bugs go directly to Dev; design questions go to the planning agent first
- Multi-agent Claude Code (manager + Dev + QA) worked well for Phase 4 — autonomous overnight completion

### Documents in the project

| Document | Purpose |
|----------|---------|
| `PROGRESS.md` | Current state, updated after every session |
| `liquid_democracy_claude_code_brief.md` | Original Phase 1-3 spec with architecture notes |
| `phase2_frontend_spec.md` | Phase 2 frontend spec |
| `phase3_spec.md` | Phase 3 full spec |
| `phase3b_spec.md` | Phase 3b delegation permissions frontend |
| `phase3c_spec.md` | Phase 3c visualization |
| `phase3_cleanup.md` | Phase 3 missing features |
| `phase4_spec.md` | Phase 4 pilot-ready spec |
| `phase4_coordination.md` | Multi-agent coordination for Phase 4 |
| `browser_testing_playbook.md` | All browser test suites |
| `future_improvements_roadmap.md` | Consolidated future enhancements |
| `website_multi_agent_brief.md` | Public website project brief |
| `DEPLOYMENT.md` | Production deployment guide |
| `SECURITY_REVIEW.md` | OWASP audit results |

---

## Part 6: Strategic Context and Next Steps

### The transition strategy

The platform alone isn't enough — it needs a path into actual use. The discussed strategy:

1. **Prove at city level**: Target reform-friendly cities (Boulder, Austin, Portland, Cambridge) for first binding adoption via participatory budgeting or citizen-initiated ordinances.
2. **The liquid democracy caucus**: Candidates run within existing party primaries pledging to vote according to the platform's results. Even a small bloc in a tightly divided legislature holds tiebreaking power.
3. **Institutional adoption**: With proven implementations, advocate for federal citizens' councils, democracy innovation funding, and proportional representation (Fair Representation Act — statutory change, not amendment).
4. **Constitutional formalization**: Following the historical pattern of the 17th and 19th Amendments — states adopt first, federal amendment formalizes what already exists.

### The immediate next step

Find a first pilot organization. The platform is pilot-ready. The ideal first pilot is a civic organization with 50-500 members that already makes group decisions (budget allocation, policy positions, endorsements) and is frustrated with their current decision-making process. Candidates: local party chapters, EA groups, neighborhood associations, professional associations, reform advocacy groups.

### The messaging

For reform advocates: "Liquid democracy makes every vote count on every issue — not just once every four years."
For frustrated citizens: "What if you could fire your representative on any issue, any time, and pick someone you actually trust?"
For potential pilot orgs: "Your members get a voice on every decision. Experts get trusted. Everyone stays informed. Try it risk-free."

### What Z cares most about

Z's deepest motivation is ensuring humans retain meaningful influence in a post-AGI world. Democracy is the mechanism for that. The platform is a tool, the reform agenda is the strategy, and the novel idea that started it all is the vision. Any instance helping with this project should keep that thread in mind — this isn't a startup or a product play, it's an attempt to build infrastructure for human agency in an era where that's increasingly at risk.

---

## Part 7: Style and Communication Preferences

When working with Z:
- Push back with expert consensus and real evidence, don't sycophantically agree
- Explore tradeoffs iteratively — Z prefers to discuss options before committing
- Be direct about what's hard, what's unsolved, and what the honest limitations are
- Z values blue-sky thinking grounded in real-world constraints
- Z is not technical but has strong design instincts — translate technical concepts into plain language
- Z appreciates when important decisions are flagged for their attention rather than made silently
- Keep the focus practical — Z pivoted from a 25-year master plan to a concrete legislative agenda because "no plan survives contact with the enemy"
