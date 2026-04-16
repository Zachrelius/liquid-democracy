# Liquid Democracy Platform — Claude Code Starting Brief

## Project Overview

Build a **liquid democracy prototype** — a web application where users can vote directly on proposals or delegate their voting power to other users on specific topics. Delegations are revocable at any time and topic-specific. This is a functional demo/proof-of-concept, not a production election system.

The target audience is democracy reform advocates who want to demonstrate liquid democracy concepts interactively. The app should feel polished enough to show at a meetup or embed in a blog post, but the priority is correct delegation logic over production hardening.

---

## Tech Stack

- **Backend**: Python 3.11+ with FastAPI
- **Database**: SQLite via SQLAlchemy (easy local dev; can swap to PostgreSQL later)
- **Delegation graph**: NetworkX for graph operations, cycle detection, and chain traversal
- **Frontend**: React (single-page app) with Tailwind CSS
- **Auth**: Simple username/password for the demo (no OAuth complexity)
- **Realtime**: WebSocket via FastAPI for live vote tally updates during voting windows

---

## Data Model

### Users
```
users
  id: UUID (primary key)
  username: string (unique)
  display_name: string
  password_hash: string
  user_type: enum [human, ai_agent] (default: human)
    — for future AI delegation support; all demo users are human
  created_at: datetime
```

### Topics
A flat tag system. Proposals can have multiple topics.
```
topics
  id: UUID
  name: string (unique, e.g. "healthcare", "economy", "environment")
  description: string
  color: string (hex, for UI display)
```

### Proposals
A proposal is a piece of legislation or policy question that users vote on.
```
proposals
  id: UUID
  title: string
  body: text (markdown)
  author_id: FK -> users
  status: enum [draft, deliberation, voting, passed, failed, withdrawn]
  deliberation_start: datetime (nullable)
  voting_start: datetime (nullable)
  voting_end: datetime (nullable)
  pass_threshold: float (default 0.50, i.e. simple majority)
  quorum_threshold: float (default 0.40, fraction of eligible votes)
  created_at: datetime
  updated_at: datetime
```

### Proposal Topics (many-to-many)
```
proposal_topics
  proposal_id: FK -> proposals
  topic_id: FK -> topics
```

### Delegations
A user delegates their vote on a specific topic (or globally) to another user.
```
delegations
  id: UUID
  delegator_id: FK -> users (the person giving away their vote)
  delegate_id: FK -> users (the person receiving the vote)
  topic_id: FK -> topics (nullable — null means global/default delegation)
  chain_behavior: enum [accept_sub, revert_direct, abstain]
    — what happens if the delegate doesn't vote or sub-delegates
  created_at: datetime
  updated_at: datetime

  UNIQUE(delegator_id, topic_id)
    — one delegation per topic per user (null topic = one global delegation)
```

### Topic Precedence
When a proposal has multiple topics and a user has different delegates for each, this determines which delegate's vote is used.
```
topic_precedences
  id: UUID
  user_id: FK -> users
  topic_id: FK -> topics
  priority: integer (lower = higher priority)

  UNIQUE(user_id, topic_id)
```

### Votes
Records actual votes on proposals. Can be direct or delegated (via the resolution algorithm).
```
votes
  id: UUID
  proposal_id: FK -> proposals
  user_id: FK -> users (the person whose vote this represents)
  vote_value: enum [yes, no, abstain]
  is_direct: boolean (true if user voted themselves, false if cast by delegate)
  delegate_chain: JSON (nullable — array of user IDs showing the delegation path)
  cast_by_id: FK -> users (the delegate who actually cast this vote, or self)
  cast_at: datetime
  updated_at: datetime

  UNIQUE(proposal_id, user_id)
    — one vote per user per proposal (can be updated during voting window)
```

---

## Core Algorithm: Delegation Resolution

This is the most important piece of logic. When a proposal goes to vote, the system must determine how each user's vote is cast.

### Resolution steps for a single user on a single proposal:

```python
def resolve_vote(user_id, proposal_id):
    """
    Returns the effective vote for this user on this proposal.
    Returns None if the user's vote cannot be resolved (no vote, no delegate chain).
    """
    # 1. Did the user vote directly? If so, use that vote.
    direct_vote = get_direct_vote(user_id, proposal_id)
    if direct_vote:
        return direct_vote

    # 2. Find the relevant delegation.
    #    Get the proposal's topics, ordered by this user's topic precedence.
    #    Find the first topic for which the user has a delegation.
    #    If no topic-specific delegation, fall back to global delegation.
    delegate_id = find_delegate(user_id, proposal_id)
    if delegate_id is None:
        return None  # No delegation, no direct vote — vote not cast

    # 3. NON-TRANSITIVE by default: check if the delegate voted directly.
    delegate_vote = get_direct_vote(delegate_id, proposal_id)
    if delegate_vote:
        return VoteResult(
            vote_value=delegate_vote.value,
            is_direct=False,
            delegate_chain=[delegate_id],
            cast_by_id=delegate_id
        )

    # 4. Delegate didn't vote. Apply chain_behavior:
    delegation = get_delegation(user_id, delegate_id, proposal_id)

    if delegation.chain_behavior == 'accept_sub':
        # Check if the delegate has their own delegation for this topic
        sub_delegate_id = find_delegate(delegate_id, proposal_id)
        if sub_delegate_id and sub_delegate_id != user_id:  # cycle check
            sub_vote = get_direct_vote(sub_delegate_id, proposal_id)
            if sub_vote:
                return VoteResult(
                    vote_value=sub_vote.value,
                    is_direct=False,
                    delegate_chain=[delegate_id, sub_delegate_id],
                    cast_by_id=sub_delegate_id
                )
        # Sub-delegate chain failed too — fall through to no vote
        return None

    elif delegation.chain_behavior == 'revert_direct':
        # Notify user they need to vote directly (in real system, send notification)
        return None  # Vote pending user action

    elif delegation.chain_behavior == 'abstain':
        return None  # Explicitly not cast
```

### Finding the delegate for a proposal:

```python
def find_delegate(user_id, proposal_id):
    """
    Determine which delegate should vote for this user on this proposal.
    Uses topic tags + user's precedence ordering.
    """
    proposal_topics = get_proposal_topics(proposal_id)  # list of topic_ids
    user_precedences = get_user_topic_precedences(user_id)  # ordered by priority

    # Sort proposal topics by user's precedence (lowest priority number first)
    sorted_topics = sorted(
        proposal_topics,
        key=lambda t: user_precedences.get(t, 9999)
    )

    # Find first topic with an active delegation
    for topic_id in sorted_topics:
        delegation = get_delegation_for_topic(user_id, topic_id)
        if delegation:
            return delegation.delegate_id

    # Fall back to global delegation
    global_delegation = get_delegation_for_topic(user_id, topic_id=None)
    if global_delegation:
        return global_delegation.delegate_id

    return None
```

### Cycle detection:

Use NetworkX to maintain a delegation graph. Before creating any delegation, check that adding the edge would not create a cycle:

```python
import networkx as nx

def would_create_cycle(graph, delegator_id, delegate_id):
    """Check if adding this delegation would create a cycle."""
    # Temporarily add the edge and check
    graph.add_edge(delegator_id, delegate_id)
    has_cycle = not nx.is_directed_acyclic_graph(graph)
    graph.remove_edge(delegator_id, delegate_id)
    return has_cycle
```

Note: maintain separate graphs per topic for topic-specific cycle detection.

---

## API Endpoints

### Auth
- `POST /api/auth/register` — create account
- `POST /api/auth/login` — get JWT token
- `GET /api/auth/me` — current user info

### Topics
- `GET /api/topics` — list all topics
- `POST /api/topics` — create topic (admin)

### Proposals
- `GET /api/proposals` — list proposals (filterable by status, topic)
- `POST /api/proposals` — create proposal
- `GET /api/proposals/{id}` — get proposal with current vote tallies
- `PATCH /api/proposals/{id}` — update proposal (author only, draft status only)
- `POST /api/proposals/{id}/advance` — move to next status (admin/author)

### Delegations
- `GET /api/delegations` — list my delegations
- `PUT /api/delegations` — set/update a delegation (upsert by topic)
  - Body: `{ delegate_id, topic_id (nullable), chain_behavior }`
- `DELETE /api/delegations/{topic_id}` — revoke delegation for topic
- `GET /api/delegations/graph` — get delegation graph data for visualization
  - Returns nodes and edges for the current user's delegation neighborhood

### Votes
- `POST /api/proposals/{id}/vote` — cast direct vote
  - Body: `{ vote_value: "yes"|"no"|"abstain" }`
- `DELETE /api/proposals/{id}/vote` — retract direct vote (reverts to delegation)
- `GET /api/proposals/{id}/results` — get current tallies
  - Returns: `{ yes, no, abstain, not_cast, total_eligible, quorum_met, threshold_met, time_series: [...] }`
- `GET /api/proposals/{id}/my-vote` — how my vote is currently being cast
  - Returns: `{ vote_value, is_direct, delegate_chain, cast_by }`

### Delegation Visualization
- `GET /api/users/{id}/delegation-tree` — get the delegation tree for a user
  - Returns a tree structure showing who delegates to this user and who they delegate to

---

## Frontend Pages

### 1. Dashboard (`/`)
- Active proposals in voting phase with live tallies
- Upcoming proposals in deliberation
- Quick summary: "You have X active delegations. Y proposals need your attention."
- Notification badges for delegation chain events

### 2. Proposals List (`/proposals`)
- Filterable by status (deliberation, voting, passed, failed) and topic
- Each card shows: title, topics (colored badges), current vote tally bar, time remaining
- Sort by: newest, closing soon, most participation

### 3. Proposal Detail (`/proposals/:id`)
- Full proposal text (rendered markdown)
- Topic tags
- **Vote panel** (if in voting phase):
  - Three buttons: Yes / No / Abstain
  - "Your vote is currently: [YES via Dr. Chen (healthcare delegation)]" or "You haven't voted and have no delegation covering this proposal"
  - If voting via delegation, option to override with direct vote
  - If voted directly, option to retract (revert to delegation)
- **Live results** (updates via WebSocket during voting window):
  - Animated bar chart: yes/no/abstain with percentages
  - Quorum indicator
  - Time remaining countdown
  - Historical chart showing how totals evolved over the voting window
- **Deliberation panel** (if in deliberation phase):
  - Threaded discussion/comments

### 4. My Delegations (`/delegations`)
- **The most important UI page.** This is where the liquid democracy concept becomes tangible.
- **Table/card view**: One row per topic showing:
  - Topic name (colored badge)
  - Current delegate (avatar + name) or "None"
  - Chain behavior setting (dropdown: Accept sub-delegation / Revert to direct / Abstain)
  - Delegate's recent voting record on this topic (last 5 votes, thumbs up/down)
  - Quick actions: Change delegate, Remove delegation
- **Global/default delegation** row at top
- **Topic precedence ordering**: Drag-and-drop list to reorder topics by priority
- **Delegation graph visualization**: Interactive network graph (using D3.js force layout or vis.js) showing:
  - You at the center
  - Your delegates as connected nodes (outgoing edges)
  - People who delegate TO you (incoming edges)
  - Edge labels showing topic
  - Node size proportional to total delegated voting weight
  - Click a node to see their profile/voting record

### 5. User Profile (`/users/:id`)
- Public voting record (proposals they voted on directly, how they voted)
- Topics they accept delegations for
- Number of people delegating to them (per topic)
- Bio/statement (optional)

### 6. Admin Panel (`/admin`)
- Create/manage topics
- Advance proposal statuses
- Create demo scenarios (seed data button)
- View system-wide delegation graph

---

## Demo Scenarios (Seed Data)

Create a "Load Demo" button that populates the system with realistic test data to showcase the delegation mechanics:

### Scenario: "Healthcare Reform Act"
- 20 users with different delegation patterns
- Proposal tagged "healthcare" + "economy"
- Several users delegate healthcare to "Dr. Chen" and economy to "EconExpert"
- Some users have conflicting topic delegations (testing precedence)
- Dr. Chen votes Yes, EconExpert votes No
- Users with healthcare > economy precedence → Yes via Dr. Chen
- Users with economy > healthcare precedence → No via EconExpert
- A few users vote directly, overriding their delegations
- Show how changing one delegate's vote cascades through the network

### Scenario: "Environmental Budget Allocation"
- Tests the chain_behavior settings
- Delegate A hasn't voted and has sub-delegated to Delegate B
- Users with accept_sub → vote follows chain to B
- Users with revert_direct → flagged as needing attention
- Users with abstain → vote not cast

---

## Key Technical Decisions

1. **Vote resolution is computed on read, not stored permanently.** When tallying a proposal, iterate all users and resolve each one's vote in real-time. This ensures delegation changes during a voting window are immediately reflected. Cache results with a short TTL (5-10 seconds) for performance.

2. **The delegation graph is maintained in NetworkX in memory**, rebuilt from the database on startup and updated incrementally as delegations change. This makes cycle detection and chain traversal fast.

3. **WebSocket updates** push new tallies to all connected clients whenever a vote is cast or a delegation changes during an active voting window. Use FastAPI's WebSocket support.

4. **Time simulation**: For demo purposes, include a "fast forward time" control that lets the presenter advance the voting window clock to show how sustained-majority requirements work.

5. **Sustained majority tracking**: During the voting window, sample the vote tally every simulated hour and store snapshots. The results endpoint returns the time series. A proposal passes only if it meets the threshold at close AND never dropped below 45% during the window.

---

## Project Structure

```
liquid-democracy/
├── backend/
│   ├── main.py              # FastAPI app, CORS, startup
│   ├── models.py            # SQLAlchemy models
│   ├── schemas.py           # Pydantic request/response schemas
│   ├── database.py          # DB connection, session management
│   ├── auth.py              # JWT auth utilities
│   ├── delegation_engine.py # Core delegation resolution + NetworkX graph
│   ├── routes/
│   │   ├── auth.py
│   │   ├── topics.py
│   │   ├── proposals.py
│   │   ├── delegations.py
│   │   ├── votes.py
│   │   └── admin.py
│   ├── seed_data.py         # Demo scenario generator
│   ├── websocket.py         # WebSocket manager for live updates
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── App.jsx
│   │   ├── pages/
│   │   │   ├── Dashboard.jsx
│   │   │   ├── ProposalList.jsx
│   │   │   ├── ProposalDetail.jsx
│   │   │   ├── MyDelegations.jsx
│   │   │   ├── UserProfile.jsx
│   │   │   └── AdminPanel.jsx
│   │   ├── components/
│   │   │   ├── VotePanel.jsx
│   │   │   ├── LiveResults.jsx
│   │   │   ├── DelegationGraph.jsx
│   │   │   ├── TopicBadge.jsx
│   │   │   ├── DelegationRow.jsx
│   │   │   └── ProposalCard.jsx
│   │   ├── hooks/
│   │   │   ├── useWebSocket.js
│   │   │   └── useAuth.js
│   │   └── api.js            # API client
│   ├── package.json
│   └── tailwind.config.js
└── README.md
```

---

## Build Order (Suggested Phases)

### Phase 1: Core Backend
1. Set up FastAPI project with SQLAlchemy + SQLite
2. Implement models and database migrations
3. Build auth endpoints (register, login, JWT)
4. Implement topics and proposals CRUD
5. Build the delegation engine (delegation_engine.py) — this is the hard part
6. Implement vote casting and delegation resolution
7. Write tests for delegation resolution edge cases:
   - Direct vote overrides delegation
   - Topic precedence ordering
   - Chain behavior (accept_sub, revert_direct, abstain)
   - Cycle prevention
   - Global vs topic-specific delegation fallback
   - Delegation change during voting window updates tallies

### Phase 2: Core Frontend
1. Set up React app with Tailwind
2. Build auth flow (login/register)
3. Proposal list and detail pages
4. Vote panel with delegation status display
5. My Delegations page with topic precedence drag-and-drop

### Phase 3: Visualization & Polish
1. Delegation graph visualization (D3 force-directed or vis.js)
2. Live results with WebSocket updates
3. Sustained majority time-series chart
4. Seed data / demo scenarios
5. Time simulation controls
6. Mobile responsive design

---

## Design Notes

The UI should feel serious and trustworthy — this represents democratic infrastructure, not a social media app. Think: clean data visualization, muted color palette with strong accent colors for vote indicators (green/yes, red/no, gray/abstain), clear information hierarchy, and generous whitespace. The delegation graph visualization is the "wow" moment — make it interactive and visually compelling, showing how votes flow through the network in real time.

Avoid: gamification aesthetics, playful/casual tone, dark patterns, anything that feels like it's trying to manipulate engagement. This should feel like a tool for civic empowerment.

---

## Architecture Notes: Production-Readiness Foundations

This is a demo, but it's designed to evolve into a platform that civic organizations and potentially municipalities could use. The following foundations should be built into the demo now because they're trivial to implement early and painful to retrofit later. They also demonstrate to anyone evaluating the project that security and integrity were considered from the start.

### 1. Audit Log (Implement Now)

Create an append-only audit log table that records every state-changing action in the system. This is the single most important production-readiness feature.

```
audit_log
  id: UUID (primary key)
  timestamp: datetime (server-generated, not client-supplied)
  actor_id: FK -> users (who performed the action)
  action: string (enum-like, e.g. "vote.cast", "vote.retracted", "delegation.created",
          "delegation.revoked", "delegation.updated", "proposal.created",
          "proposal.status_changed", "user.registered", "user.login")
  target_type: string (e.g. "proposal", "delegation", "vote", "user")
  target_id: UUID (the ID of the affected entity)
  details: JSON (action-specific data — see below)
  ip_address: string (nullable, for future abuse detection)
```

**What to store in the details JSON for each action type:**

- `vote.cast`: `{ proposal_id, vote_value, is_direct, previous_value (if changing), delegate_chain }`
- `vote.retracted`: `{ proposal_id, previous_value }`
- `delegation.created`: `{ delegate_id, topic_id, chain_behavior }`
- `delegation.updated`: `{ delegate_id, topic_id, chain_behavior, previous_delegate_id, previous_chain_behavior }`
- `delegation.revoked`: `{ previous_delegate_id, topic_id }`
- `proposal.status_changed`: `{ proposal_id, old_status, new_status }`
- `proposal.created`: `{ proposal_id, title, topic_ids }`

**Critical implementation rules:**

- The audit log is **append-only**. No UPDATE or DELETE operations, ever. No API endpoint to modify or remove entries. This is a write-once ledger.
- Audit writes should happen in the **same database transaction** as the action they record. If the vote insert succeeds but the audit write fails, the whole transaction rolls back. This guarantees the log is complete.
- Add an API endpoint `GET /api/audit` (admin-only) that returns paginated audit entries with filtering by action type, actor, target, and date range. This becomes the foundation for transparency reporting.
- In the frontend admin panel, add a simple audit log viewer that shows recent actions in a scrollable table.

### 2. Request/Response Logging Middleware (Implement Now)

Add FastAPI middleware that logs every API request with:
- Timestamp
- HTTP method and path
- Authenticated user ID (if any)
- Response status code
- Response time in milliseconds

Use Python's standard `logging` module writing to a structured format (JSON lines). Don't log request/response bodies (they may contain sensitive data) — the audit log handles action-specific details.

This is ~20 lines of middleware code and provides invaluable debugging information for both development and future incident response.

### 3. Input Validation and Sanitization (Implement Now)

Pydantic (which FastAPI uses natively) handles most of this, but be explicit about:

- **String length limits** on all text fields. Username: 3-50 chars. Display name: 1-100 chars. Proposal title: 1-500 chars. Proposal body: 1-50000 chars. Topic name: 1-100 chars.
- **Enum validation** for all enum fields (vote_value, status, chain_behavior). Reject anything not in the allowed set.
- **UUID validation** for all ID fields. Don't accept arbitrary strings.
- **Markdown sanitization** for proposal bodies. Strip or escape any HTML tags to prevent XSS. Use a library like `bleach` or `nh3` to sanitize rendered markdown output.
- **Rate limiting** on auth endpoints. At minimum, add a simple in-memory rate limiter (5 login attempts per minute per IP) to prevent brute-force attacks. Use `slowapi` or a simple custom middleware.

### 4. Separation of Concerns in the Delegation Engine (Implement Now)

The delegation resolution logic in `delegation_engine.py` should be a pure, stateless module that:

- Takes inputs (user_id, proposal_id, and query functions/data)
- Returns outputs (resolved vote, delegation chain, metadata)
- Has **no direct database access**. Instead, it receives data through passed-in functions or pre-fetched data objects.

This separation matters for three reasons: it makes the algorithm independently testable without database fixtures, it makes it possible to swap the data layer later (e.g., moving to PostgreSQL or adding caching) without touching the core logic, and it makes the algorithm auditable — someone reviewing the system for a civic deployment can read the delegation engine in isolation and verify its correctness without understanding the web framework or database layer.

```python
# Good: delegation engine is a pure function
def resolve_vote(
    user_id: str,
    proposal_topics: list[str],
    user_precedences: dict[str, int],
    delegations: dict[str, Delegation],
    direct_votes: dict[str, VoteValue],
) -> VoteResult | None:
    ...

# Bad: delegation engine queries the database directly
def resolve_vote(user_id: str, proposal_id: str, db: Session):
    vote = db.query(Vote).filter(...).first()  # Don't do this inside the engine
    ...
```

### 5. Configuration Management (Implement Now)

Use environment variables (via `python-dotenv` and Pydantic's `BaseSettings`) for all configuration:

```python
class Settings(BaseSettings):
    database_url: str = "sqlite:///./liquid_democracy.db"
    secret_key: str  # No default — must be set
    jwt_expiration_minutes: int = 60
    cors_origins: list[str] = ["http://localhost:5173"]
    debug: bool = False
    log_level: str = "INFO"

    class Config:
        env_file = ".env"
```

Never hardcode secrets, database URLs, or environment-specific values. This is a 10-minute setup that prevents the most common class of deployment security issues.

### 6. Database Migration Support (Implement Now)

Set up **Alembic** for database migrations from the start, even though you're using SQLite:

```bash
pip install alembic
alembic init migrations
```

Configure it to auto-generate migrations from SQLAlchemy model changes. Every schema change should be a versioned migration, not a "drop and recreate the database" operation.

This costs 15 minutes to set up and means that when the project moves to PostgreSQL with real user data, schema changes can be applied without data loss. It also provides a history of every schema change, which is part of the audit story for civic deployments.

### 7. Test Coverage Targets (Implement Now)

Write tests for the delegation engine that cover every edge case. These tests are the project's most valuable long-term asset — they define what "correct" means and protect against regressions as the codebase evolves. Target cases:

**Delegation resolution:**
- Direct vote always overrides delegation
- Topic precedence ordering determines which delegate is used for multi-topic proposals
- Global delegation is used as fallback when no topic-specific delegation exists
- `accept_sub` follows one level of sub-delegation
- `revert_direct` returns None when delegate hasn't voted
- `abstain` returns None when delegate hasn't voted
- Delegation to a user who hasn't voted and has no sub-delegation returns None
- Changing a delegation during a voting window immediately changes resolved vote
- Retracting a direct vote reverts to delegation result

**Cycle prevention:**
- Direct cycle (A→B, B→A) is rejected
- Indirect cycle detection (A→B, B→C, C→A) is rejected
- Cycle check is per-topic (A→B on healthcare, B→A on economy is allowed)
- Global delegation cycle detection works correctly

**Sustained majority:**
- Proposal passes when threshold met at close and never dropped below floor
- Proposal fails when threshold met at close but dropped below floor during window
- Proposal fails when threshold not met at close even if it was met earlier
- Quorum calculation correctly counts delegated votes

**Edge cases:**
- User with no delegations and no direct vote has no resolved vote
- Proposal with no topic tags uses only global delegations
- User with delegations for all of a proposal's topics but different delegates uses highest-precedence topic
- Deleting a delegate's account or deactivating it properly handles orphaned delegations

### 8. CORS and Security Headers (Implement Now)

Configure FastAPI's CORS middleware strictly:

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,  # Explicit list, never ["*"] in production
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
)
```

Add security headers middleware:
- `X-Content-Type-Options: nosniff`
- `X-Frame-Options: DENY`
- `X-XSS-Protection: 1; mode=block`
- `Referrer-Policy: strict-origin-when-cross-origin`

These are a few lines of middleware that cost nothing and prevent entire categories of attacks.

---

## Roadmap: Demo → Pilot → Civic Deployment

This section is for reference — it maps what additional work is needed at each stage beyond the demo. It does not need to be built now but informs architectural decisions.

### Pilot Stage (civic organization internal use)

What changes from the demo:
- **Auth**: Email verification + admin approval for membership. Consider integration with OAuth providers (Google, GitHub) for convenience.
- **Database**: Migrate to PostgreSQL. Set up automated daily backups.
- **Deployment**: Docker containerization. Deploy to a reliable cloud host (Railway, Fly.io, or AWS). HTTPS via Let's Encrypt.
- **Privacy**: Privacy policy and terms of service. GDPR-compliant data export/deletion if serving EU users.
- **Monitoring**: Error tracking (Sentry), uptime monitoring, basic performance dashboards.

What carries forward unchanged from the demo:
- Data model and delegation engine
- API design and business logic
- Frontend application
- Audit logging infrastructure
- Test suite

### Municipal Proof-of-Concept Stage

What changes from the pilot:
- **Identity verification**: Integration with government ID or voter registration systems. In-person registration option with kiosk support. This is a major sub-project.
- **Security audit**: Formal penetration testing and code review by an independent security firm.
- **Accessibility**: Full WCAG 2.1 AA compliance. Screen reader testing. Multilingual support.
- **Legal review**: Analysis of legal authority for the municipality to use the platform, liability framework, open records compliance.
- **Availability**: Multi-region deployment, database replication, 99.9% uptime SLA.
- **Institutional structure**: Nonprofit organization or government contract to house the project. Advisory board with technical, legal, and civic representation.

What carries forward unchanged from the pilot:
- Core data model (may have minor extensions)
- Delegation resolution algorithm
- API structure (with added endpoints for admin/reporting)
- Audit log (with extended retention and reporting)
- Test suite (expanded)

### AI Delegation Agents (Optional Module — Municipal Stage or Later)

AI delegation allows users to delegate their votes to an AI agent configured with their personal values and priorities, rather than (or in addition to) human delegates. The AI reads proposed legislation, compares it against the user's stated priorities, and either votes on their behalf or sends them a summary with recommendations. This is framed as a regulated add-on, not a core system feature — it extends the delegation model rather than replacing it.

**Why it matters:** AI delegation makes the principal-agent alignment problem explicit and programmable. Instead of hoping a human delegate shares your values, you specify them directly. An AI agent with a well-defined constitution may actually represent a voter's preferences more faithfully than a human delegate who has their own interests and blind spots.

**Current architecture decisions that support future AI delegation:**

- Add a `user_type` field to the users table now: `user_type: enum [human, ai_agent] (default: human)`. This is a one-line addition that avoids a schema migration later. AI agents are registered as a special type of user — they can receive delegations, cast votes, and appear in the delegation graph just like human delegates.
- The delegation resolution algorithm already works unchanged — it follows the graph and finds a vote regardless of whether the voter is human or AI.
- The audit log's JSON `details` field can accommodate AI-specific metadata (model used, prompt/constitution hash, confidence level, reasoning summary) without schema changes.
- The pure-function delegation engine design means AI agent logic lives in a separate module that feeds votes into the same resolution pipeline.

**Design guardrails for AI delegation:**

- **Confirmation model (default: opt-in per vote cycle).** AI agents pre-register votes during the deliberation period. The human receives a digest notification: "Your AI assistant plans to vote YES on Healthcare Reform (reason: aligns with your priority for universal coverage), NO on Defense Budget Increase (reason: conflicts with your spending reduction priority). Tap any vote to override." Unlike human delegations where silence means consent, AI delegations should default to requiring explicit confirmation — at least initially. Users can opt into auto-approval after building trust with their agent's judgment.
- **Transparency requirements.** AI agents are subject to the same (or stricter) disclosure requirements as high-delegation-count human delegates. Their voting rationale must be publicly inspectable: anyone can see that an AI agent voted a particular way because its constitution prioritizes certain values. The prompt/constitution that defines the agent's values is viewable by the delegating user and optionally public.
- **No AI-to-AI chains.** An AI agent cannot delegate to another AI agent. Delegation chains must terminate at either a direct AI vote or a human vote. This prevents fully autonomous delegation cascades with no human in the loop.
- **Regulatory framework.** AI agents may be subject to additional rules set by the system operator: maximum percentage of total votes that can be AI-cast, mandatory human confirmation for proposals above a significance threshold, periodic re-confirmation of the agent's constitution by the user, and public reporting of aggregate AI vs. human voting patterns.

**Implementation sketch (not for current development):**

```
ai_agents (extends users with user_type='ai_agent')
  user_id: FK -> users
  owner_id: FK -> users (the human who created and controls this agent)
  model_provider: string (e.g. "anthropic", "openai", "local")
  constitution: text (the values/priorities prompt)
  constitution_hash: string (for audit trail — detect if constitution changed)
  confirmation_mode: enum [require_all, require_uncertain, auto_approve]
  uncertainty_threshold: float (0-1, at what confidence level to escalate to human)
  created_at: datetime
  updated_at: datetime

ai_vote_drafts (pre-registered votes awaiting human confirmation)
  id: UUID
  agent_id: FK -> users
  proposal_id: FK -> proposals
  recommended_value: enum [yes, no, abstain]
  confidence: float (0-1)
  reasoning: text (human-readable explanation)
  status: enum [pending_review, confirmed, overridden, expired]
  confirmed_at: datetime (nullable)
  confirmed_by: FK -> users (nullable — the human owner)
```

**What this means for the demo:** No AI delegation code needs to be written now. The only current action item is adding the `user_type` field to the users model. Everything else is a future module that plugs into the existing delegation architecture.
