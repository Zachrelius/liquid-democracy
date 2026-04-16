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
