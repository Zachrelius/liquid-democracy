# Phase 2: Frontend MVP — Claude Code Build Spec

## Overview

Build a React frontend for the liquid democracy platform. This phase covers three screens plus a demo data loader — the minimum needed to demonstrate liquid democracy to someone who has never seen it before.

Read `PROGRESS.md` to understand the existing backend. The backend API is already built and tested (36/36 tests passing). This phase adds a frontend that consumes those APIs.

---

## Pre-Frontend: Two Small Schema Additions

Before building the frontend, add these two fields to future-proof the data model. Both should be Alembic migrations.

### 1. User delegation strategy preference

Add to the `users` model:
```
delegation_strategy: string (default: "strict_precedence")
```

This field is not exposed in the UI yet. It exists so that future delegation resolution strategies (majority-of-delegates, weighted-majority, etc.) can be added without a schema migration. The delegation engine should read this field but only implement `strict_precedence` for now — if the value is anything else, fall back to `strict_precedence` with a log warning.

### 2. Topic relevance weight on proposals

Change the `proposal_topics` join table from a simple many-to-many to include a relevance score:
```
proposal_topics
  proposal_id: FK -> proposals
  topic_id: FK -> topics
  relevance: float (default: 1.0, range 0.0 to 1.0)
```

This describes how central each topic is to a given proposal (1.0 = core topic, 0.3 = minor implications). The current delegation resolution ignores this field — strict precedence doesn't use topic weights. But the field should be settable when creating/editing proposals, and the API should return it when listing proposal topics.

Update the proposal creation endpoint to accept optional relevance values:
```json
{
  "title": "...",
  "body": "...",
  "topic_ids": [
    {"topic_id": "uuid-here", "relevance": 1.0},
    {"topic_id": "uuid-here", "relevance": 0.3}
  ]
}
```

For backward compatibility, also accept the old format (plain list of topic ID strings) and default relevance to 1.0.

Run all existing tests after these changes to confirm nothing breaks.

---

## Tech Stack

- **Framework**: React 18+ with Vite
- **Routing**: React Router v6
- **Styling**: Tailwind CSS
- **HTTP client**: fetch or axios (keep it simple)
- **State management**: React context + hooks (no Redux — the app isn't complex enough to need it)
- **Charts**: Recharts (already available in artifact environments, lightweight)

---

## Design Direction

The UI should feel like **civic infrastructure** — serious, trustworthy, and clear. Think government website meets modern data dashboard. Not playful, not gamified, not social-media-like.

**Color palette:**
- Primary: Deep navy (#1B3A5C) for headers and navigation
- Accent: Steel blue (#2E75B6) for interactive elements and links
- Vote colors: Muted green (#2D8A56) for Yes, muted red (#C0392B) for No, medium gray (#7F8C8D) for Abstain
- Backgrounds: White and very light gray (#F8F9FA)
- Text: Near-black (#2C3E50) for body, medium gray for secondary

**Typography:**
- Use system fonts for reliability: `-apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif`
- Clear hierarchy: large bold titles, medium weight section headers, regular body text
- Generous line height (1.6) for readability

**General principles:**
- Generous whitespace — don't crowd information
- Clear visual hierarchy — the most important information (your current vote, who's casting it) should be immediately obvious
- Status indicators should be color-coded and unambiguous
- Every delegation relationship should be explainable in plain English in the UI

---

## Screen 1: Login / Register (`/login`)

Simple full-page auth form. Two tabs or a toggle: Login and Register.

**Login tab:**
- Username field
- Password field
- Submit button
- Error display for wrong credentials or rate limiting

**Register tab:**
- Username field (3-50 chars)
- Display name field
- Password field (8+ chars)
- Submit button
- Error display with field-specific validation messages

**After login:** Store the JWT token in memory (React state/context, not localStorage — per the artifact environment constraints). Redirect to the Proposals page.

**Auth context:** Create an AuthContext provider that holds the current user and token, provides login/logout/register functions, and makes the authenticated API client available to all child components.

---

## Screen 2: Proposals (`/proposals` and `/proposals/:id`)

This is the main screen. It has two views: the list and the detail.

### Proposals List View (`/proposals`)

**Header area:**
- Page title: "Proposals"
- Filter bar: status filter (All, Deliberation, Voting, Passed, Failed) as segmented buttons or tabs. Topic filter as a multi-select dropdown with colored badges.
- Sort: "Closing Soon" (default for voting status), "Newest", "Most Participation"

**Proposal cards** (one per proposal, stacked vertically):
- Title (large, clickable — links to detail view)
- Topic badges (small colored pills showing each topic with name)
- Status badge (Deliberation = blue, Voting = amber, Passed = green, Failed = red)
- If in voting phase:
  - Compact vote tally bar (horizontal stacked bar: green/red/gray proportional to yes/no/abstain)
  - Percentage labels: "62% Yes · 28% No · 10% Abstain"
  - Time remaining: "3d 14h remaining" or "Closes today"
  - Your vote status (small text): "Your vote: Yes via Dr. Chen" or "You haven't voted"
- If in deliberation phase:
  - "Deliberation period · Opens for voting in 5 days"

### Proposal Detail View (`/proposals/:id`)

**Header:**
- Back link to proposals list
- Title (large)
- Topic badges with relevance indicators (if relevance < 1.0, show it: "healthcare (primary) · economy (minor)")
- Status badge
- Author name

**Proposal body:**
- Rendered markdown in a clean reading column (max-width ~700px)

**Vote Panel** (right sidebar on desktop, below body on mobile):

This panel is the core interaction. Its content depends on proposal status:

*If status is "voting":*

**Your Vote Status** (prominent, top of panel):
- If voting via delegation: A clear box saying something like:
  ```
  Your vote: YES
  Via Dr. Chen (healthcare delegation)
  Dr. Chen voted Yes on [date]
  ```
  With two action buttons: "Override — Vote Directly" and "Change Delegate"

- If voted directly: A clear box saying:
  ```
  Your vote: NO (direct)
  You voted No on [date]
  ```
  With a "Retract Vote (revert to delegation)" button

- If no vote resolved (no direct vote, no applicable delegation):
  ```
  Your vote: Not cast
  You have no delegation covering this proposal's topics.
  ```
  With a "Vote Now" prompt

**Vote Buttons** (shown when user clicks "Override" or "Vote Now", or if no vote exists):
- Three large buttons in a row: Yes (green), No (red), Abstain (gray)
- Clicking one immediately casts/changes the vote via API
- Confirmation feedback: brief success animation or checkmark

**Current Results** (below vote panel):
- Horizontal stacked bar chart (wider/taller than the card version)
- Numeric breakdown: "1,247 Yes (62%) · 561 No (28%) · 192 Abstain (10%)"
- Total participation: "2,000 of 3,500 eligible votes cast (57%)"
- Quorum indicator: "Quorum met ✓" or "Quorum not yet met (need 40%)"
- If sustained majority tracking is implemented: mini line chart showing threshold over the voting window

*If status is "deliberation":*
- Show "Voting opens [date]" with the vote panel grayed out
- Optionally show a comment/discussion area (can be a simple list of text comments for the demo)

*If status is "passed" or "failed":*
- Show final results (same format as voting, but static)
- Show "Passed on [date]" or "Failed on [date]"

---

## Screen 3: My Delegations (`/delegations`)

This is the page that makes liquid democracy click for people. It needs to clearly show: who is voting for you on what topics, and how you can change it.

**Page layout:**

**Section 1: Global Default Delegation**

A card at the top:
```
Default Delegate: [avatar] Bob the Economist
Used when no topic-specific delegation applies
Chain behavior: Accept sub-delegation ▾
[Change] [Remove]
```

Or if none set:
```
No default delegate set
Your vote won't be cast on topics without a specific delegation
[Set Default Delegate]
```

**Section 2: Topic Delegations**

A table or card list, one row per topic. Columns:

| Topic | Delegate | Chain Behavior | Actions |
|-------|----------|----------------|---------|
| 🔴 Healthcare | Dr. Chen | Accept sub-delegation ▾ | Change · Remove |
| 🔵 Economy | Bob the Economist | Revert to direct ▾ | Change · Remove |
| 🟢 Environment | — None — | — | Set Delegate |

For each row:
- Topic shown as colored badge
- Delegate shown as name (with small note of how many others delegate to this person on this topic, if available: "also trusted by 47 others")
- Chain behavior as a dropdown that saves immediately on change
- Change opens a user search/select modal
- Remove button with confirmation

**Section 3: Topic Precedence**

A reorderable list showing the voter's priority ranking of topics. This determines which delegate's vote is used when a proposal spans multiple topics.

```
Your topic priority (drag to reorder):
1. 🔴 Healthcare
2. 🟢 Environment  
3. 🔵 Economy
```

Include a brief explanation: "When a proposal covers multiple topics, your highest-priority topic's delegate determines your vote."

Implement drag-and-drop reordering. Each reorder immediately saves via API.

**Delegate Selection Modal:**

When clicking "Change" or "Set Delegate" on any row, a modal appears:
- Search field to find users by name/username
- Results show: display name, username, and (if available) how many delegations they hold on this topic
- Clicking a user selects them and closes the modal
- The delegation is created/updated via API immediately

---

## Demo Data Loader

Add a "Load Demo Scenario" button accessible from the login page or a `/demo` route. When clicked, it calls a backend endpoint that:

1. Creates demo users (if they don't already exist):
   - alice / Alice Voter (password: demo1234)
   - dr_chen / Dr. Chen (Healthcare Expert)
   - econ_bob / Bob the Economist
   - carol / Carol (Direct Voter)
   - dave / Dave the Delegator
   - env_emma / Emma (Environmental Advocate)
   - Plus 14 more users with assorted names to make the numbers feel realistic

2. Creates topics: Healthcare, Economy, Environment, Civil Rights, Defense, Education

3. Creates 5 proposals in various statuses:
   - "Universal Healthcare Coverage Act" — tagged Healthcare (relevance 1.0) + Economy (relevance 0.3), status: voting, mixed votes
   - "Carbon Tax Implementation" — tagged Environment (1.0) + Economy (0.7), status: voting, mostly yes
   - "Education Funding Reform" — tagged Education (1.0), status: deliberation
   - "Infrastructure Investment Act" — tagged Economy (1.0) + Environment (0.4), status: passed, final results visible
   - "Digital Privacy Rights Act" — tagged Civil Rights (1.0), status: voting, close vote

4. Sets up delegation patterns:
   - Alice delegates Healthcare → Dr. Chen, Economy → Bob, precedence: Healthcare > Economy
   - Dave delegates everything globally → Alice (testing chain)
   - 10+ other users with various delegation patterns creating a realistic-looking network
   - Several users have voted directly, overriding their delegations

5. Returns credentials for demo login:
   ```json
   {
     "message": "Demo loaded. Log in as any user with password 'demo1234'",
     "suggested_user": "alice",
     "users": ["alice", "dr_chen", "econ_bob", "carol", "dave", "env_emma", ...]
   }
   ```

**The demo experience:** Someone visits the app, clicks "Load Demo," logs in as Alice, immediately sees proposals with live votes, checks the Delegations page to see her delegation setup, goes to the Healthcare proposal and sees "Your vote: Yes via Dr. Chen," changes her healthcare delegation to someone who voted No, watches her vote flip. That's the "aha" moment.

---

## API Client Setup

Create an `api.js` module that:
- Stores the base URL (defaults to `http://localhost:8000`)
- Attaches the JWT token to every request as `Authorization: Bearer <token>`
- Handles 401 responses by redirecting to login
- Provides typed helper functions: `api.get(path)`, `api.post(path, body)`, `api.put(path, body)`, `api.delete(path)`
- Handles errors gracefully — network failures, validation errors (422), server errors (500) — and returns structured error objects the UI can display

---

## Responsive Design

The app should work on both desktop and mobile:
- Desktop: sidebar layout for proposal detail (body left, vote panel right)
- Mobile: stacked layout (body, then vote panel below)
- Delegations page: table on desktop, cards on mobile
- Breakpoint: 768px

---

## Build Order

1. **Project setup**: Vite + React + React Router + Tailwind. Proxy API requests to localhost:8000.
2. **Auth**: AuthContext, login/register page, protected route wrapper.
3. **API client**: api.js with token management and error handling.
4. **Proposals list**: Fetch and display proposals with status filters and topic badges.
5. **Proposal detail**: Full proposal view with vote panel and results display.
6. **My Delegations**: Delegation table, chain behavior dropdowns, delegate selection modal, precedence reordering.
7. **Demo data loader**: Backend seed endpoint + frontend button.
8. **Polish**: Loading states, error states, empty states, mobile responsive tweaks.

### After each step, verify:
- No console errors
- API calls work (check Network tab)
- Auth token is being sent on all requests
- Error states display correctly (try with server stopped, try invalid inputs)

---

## What NOT to Build in Phase 2

Save these for Phase 3:
- Delegation graph visualization (D3/vis.js network diagram)
- WebSocket live updates (polling is fine for the demo)
- Dashboard page
- User profile pages
- Admin panel (use the FastAPI /docs page for admin tasks)
- Time simulation controls
- Sustained majority time-series chart (just show current totals)
- Comments/discussion on proposals
