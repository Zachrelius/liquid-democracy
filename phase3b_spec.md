# Phase 3b: Delegation Permissions Frontend — Claude Code Build Spec

## Overview

Build the frontend UI for the delegation permission system implemented in Phase 3a. This adds the follow/delegate request flow, public delegate browsing, permission-aware vote visibility, user profiles, and updates to the delegate selection experience.

Read `PROGRESS.md` for current project state. The backend endpoints for all of these features already exist from Phase 3a.

---

## Part 1: Backend Addition — Deferred Delegation Intent

Before building the frontend, add one new backend feature that wasn't in Phase 3a: the ability to queue a delegation intent that auto-activates when a follow request is approved with delegation permission.

### New Model

```
delegation_intents
  id: UUID
  delegator_id: FK -> users
  delegate_id: FK -> users
  topic_id: FK -> topics (nullable for global)
  chain_behavior: enum [accept_sub, revert_direct, abstain]
  follow_request_id: FK -> follow_requests
  status: enum [pending, activated, expired, cancelled]
  expires_at: datetime (default: 30 days from creation)
  created_at: datetime
  activated_at: datetime (nullable)

  UNIQUE(delegator_id, delegate_id, topic_id)
    — one pending intent per delegate per topic
```

### Logic

**When a delegation intent is created** (user clicks "Request Delegate" for someone they don't follow):
1. Create a follow_request to the target user (if one doesn't already exist)
2. Create a delegation_intent linked to that follow_request, with status "pending" and expires_at set to 30 days from now
3. Return a response confirming the request was sent and that the delegation will activate automatically if approved

**When a follow request is approved with delegation_allowed:**
1. Create the follow_relationship (existing behavior)
2. Check for any pending, non-expired delegation_intents from the requester to the approver
3. For each one found: create the actual delegation and update the intent status to "activated"
4. Audit log entries for both the follow approval and any auto-activated delegations

**When a follow request is approved with view_only:**
1. Create the follow_relationship (existing behavior)
2. Do NOT activate delegation intents — the permission level isn't sufficient
3. The intents remain pending (the delegator could later request an upgrade)

**When a delegation intent expires** (past expires_at):
1. On any read of the intent, if expires_at < now and status is still "pending," update status to "expired"
2. No need for a background job — lazy expiration on read is fine for the demo
3. Expired intents are not activated even if the follow request is later approved

**When a delegation intent is cancelled** (user decides they don't want it anymore):
1. Update status to "cancelled"
2. If the associated follow_request is still pending, optionally cancel that too (or leave it — the user might still want to follow without delegating)

### New Endpoints

- `POST /api/delegations/request` — create a delegation intent + follow request in one action
  - Body: `{ delegate_id, topic_id (nullable), chain_behavior }`
  - If the user already has permission to delegate (public delegate or existing follow with delegation_allowed), skip the intent and create the delegation directly (same as existing PUT /api/delegations behavior)
  - If permission is needed, create the follow_request + delegation_intent
  - Returns: `{ status: "delegated" | "requested", message: "..." }`

- `GET /api/delegations/intents` — list current user's pending delegation intents
  - Returns intents with status, target user info, topic, expiration date

- `DELETE /api/delegations/intents/{id}` — cancel a pending intent

Audit log events: `delegation_intent.created`, `delegation_intent.activated`, `delegation_intent.expired`, `delegation_intent.cancelled`

### Tests

- Intent created with follow request when delegating to non-followed user
- Intent auto-activates when follow approved with delegation_allowed
- Intent does NOT activate when follow approved with view_only
- Expired intent does not activate even after follow approval
- Direct delegation still works for public delegates (bypasses intent system)
- Direct delegation still works for users with existing delegation_allowed follow
- Cancelling an intent works and is audit-logged
- Multiple intents for different topics to the same delegate all activate on approval

---

## Part 2: Updated Delegate Selection Modal

The existing delegate selection modal (on the My Delegations page) needs to be redesigned to handle the permission tiers.

### Search Results Display

When a user searches for a delegate, each result shows:

**For public delegates on the relevant topic:**
```
┌──────────────────────────────────────────────────┐
│ 👤 Dr. Chen                                      │
│ Public delegate · Healthcare, Economy             │
│ "Board-certified physician with 20 years..."      │
│ Trusted by 47 others on Healthcare                │
│                                    [Delegate →]   │
└──────────────────────────────────────────────────┘
```
- Green indicator or badge showing "Public Delegate"
- Bio text (truncated)
- Delegation count
- Single "Delegate" button — creates delegation immediately

**For users you follow with delegation_allowed:**
```
┌──────────────────────────────────────────────────┐
│ 👤 Carol Direct-Voter                             │
│ Following · Delegation allowed                    │
│                                    [Delegate →]   │
└──────────────────────────────────────────────────┘
```
- Shows follow status and permission level
- Single "Delegate" button — creates delegation immediately

**For users you follow with view_only:**
```
┌──────────────────────────────────────────────────┐
│ 👤 Eve Watcher                                    │
│ Following · View only                             │
│                          [Request Delegate ↗]     │
└──────────────────────────────────────────────────┘
```
- Shows follow status
- "Request Delegate" button — sends a request to upgrade permission + creates delegation intent
- Tooltip or small text: "They'll need to approve delegation permission"

**For users you don't follow:**
```
┌──────────────────────────────────────────────────┐
│ 👤 Frank Unknown                                  │
│ Not following                                     │
│                [Request Follow]  [Request Delegate ↗] │
└──────────────────────────────────────────────────┘
```
- Two buttons:
  - "Request Follow" — sends follow request only (user just wants to see their votes first)
  - "Request Delegate" — sends follow request + delegation intent (user wants to delegate once approved)
- Small text under Request Delegate: "They'll need to approve. Delegation activates automatically if approved within 30 days."

**For users with a pending request:**
```
┌──────────────────────────────────────────────────┐
│ 👤 Frank Unknown                                  │
│ ⏳ Follow request pending (sent 3 days ago)       │
│                              [Cancel Request]     │
└──────────────────────────────────────────────────┘
```
- Shows pending status with age
- Cancel button

### After Delegation is Set

When a delegation is successfully created (either directly or via auto-activation), the My Delegations table updates to show the new delegate. If created via intent, show a subtle indicator until activated: "Pending approval — will activate when [name] approves."

---

## Part 3: Follow Request Management UI

Add a section to handle incoming and outgoing follow requests. This could be:
- A dedicated page (`/follows`) accessible from the nav, OR
- A section within the My Delegations page, OR  
- Part of the notification dropdown

Recommendation: put it in the notification dropdown for the indicator/count, with a "View all" link to a simple dedicated section. For the demo, a section at the bottom of the My Delegations page is simplest.

### Incoming Requests Section

```
Incoming Requests (2 pending)

┌──────────────────────────────────────────────────┐
│ 👤 Test User wants to delegate to you             │
│ "Hi, I'd like to follow your votes on healthcare" │
│ Sent 2 hours ago                                  │
│                                                   │
│ [Deny]  [Accept Follow (view only)]  [Accept Delegate] │
└──────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────┐
│ 👤 New Voter wants to follow you                  │
│ Sent 1 day ago                                    │
│                                                   │
│ [Deny]  [Accept Follow (view only)]  [Accept Delegate] │
└──────────────────────────────────────────────────┘
```

Three response buttons matching the backend options:
- **Deny** — rejects the request
- **Accept Follow (view only)** — they can see your votes but not delegate to you
- **Accept Delegate** — they can see your votes and delegate to you. If they sent a delegation intent, it activates automatically.

After responding, the request disappears from the list with a brief confirmation message.

### Outgoing Requests Section

```
Your Pending Requests

┌──────────────────────────────────────────────────┐
│ → Frank Unknown                                   │
│ Requested delegate access · Sent 3 days ago       │
│ Delegation on Healthcare will auto-activate       │
│                                    [Cancel]       │
└──────────────────────────────────────────────────┘
```

Shows pending outgoing requests with their type (follow vs delegate), age, and any associated delegation intent. Cancel button withdraws the request.

---

## Part 4: User Profile Page (`/users/:id`)

A public-facing profile page that respects the permission model.

### Layout

**Header:**
- Display name (large)
- Username (smaller, gray)
- Relationship status: "Public Delegate" / "You follow this user" / "Follows you" / no relationship
- Action button: "Delegate" / "Request Follow" / "Request Delegate" (based on current relationship)

**Public Delegate Section** (if they have delegate_profiles):
- Each topic they're registered as public delegate for:
  - Topic badge
  - Bio text
  - Number of delegators
  - Their voting record on proposals tagged with this topic (visible to everyone)

**Voting Record** (permission-gated):
- If you have permission (follow relationship or their public delegate topics): show their votes on proposals, listed chronologically
  - Each entry: proposal title, their vote (Yes/No/Abstain), date
  - Topics shown as badges
- If you don't have permission: show a message "Follow [name] to see their voting record" with a Request Follow button
- For public delegate topics: always visible regardless of follow status
- For non-public topics where you have a follow: visible
- For non-public topics where you don't have a follow: show "Private" placeholder

### Viewing Your Own Profile

When viewing your own profile (`/users/me` or your own ID), show everything plus:
- Edit display name
- Manage delegate registrations (register/deactivate as public delegate per topic, edit bios)
- Default follow policy dropdown (require_approval / auto_approve_view / auto_approve_delegate)
- List of your followers with permission levels and ability to revoke

---

## Part 5: Navigation Updates

### Notification Badge

Add a notification indicator to the nav bar:
- Show a count badge (red circle with number) when there are:
  - Pending incoming follow requests
  - Proposals in voting phase where the user's vote is unresolved
  - Recently activated delegation intents (within last 24 hours, so the user notices)
- Clicking the badge opens a dropdown with brief descriptions:
  - "2 follow requests pending" → links to My Delegations requests section
  - "3 proposals need your vote" → links to proposals page filtered to voting
  - "Delegation to Carol activated" → links to My Delegations
- Dropdown has a "dismiss all" or items auto-dismiss when the relevant page is visited

### Updated Nav Items

```
[Logo/App Name]   Proposals   My Delegations   [🔔 3]   [👤 Alice ▾]
                                                          Profile
                                                          Logout
```

---

## Part 6: Demo Data Updates

Update the seed data to showcase the permission features:

- Create a user "frank" who is not followed by anyone — used to demonstrate the follow request flow
- Create a pending follow request from a demo user to Alice — so Alice sees incoming requests on login
- Create a delegation intent from a demo user that will auto-activate when Alice approves
- Add bios to public delegate profiles that feel realistic:
  - Dr. Chen (Healthcare): "Board-certified physician with 20 years of clinical experience. I believe healthcare policy should be evidence-based and patient-centered."
  - Dr. Chen (Economy): "I focus on healthcare economics — how we fund care, control costs, and ensure access."
  - Emma (Environment): "Environmental scientist specializing in climate policy. I review all environmental legislation through the lens of peer-reviewed science."

---

## Build Order

1. **Backend: delegation intent system** — new model, migration, endpoints, intent activation on follow approval, expiration logic, tests
2. **Delegate selection modal update** — permission-aware search results with appropriate buttons
3. **Follow request management** — incoming/outgoing requests section on My Delegations page
4. **User profile page** — permission-gated voting record, delegate profile display, self-editing
5. **Navigation updates** — notification badge and dropdown
6. **Demo data updates** — new seed scenarios
7. **Polish** — loading states on new components, error handling for permission-denied responses, mobile responsive for new pages

Run all existing tests (backend unit + any frontend tests) after each step. Run the browser testing playbook (at minimum Suite A and B as regression) after step 7.

---

## What NOT to Build in Phase 3b

- Delegation graph visualization (that's Phase 3c)
- Dashboard page (Phase 3d)
- Per-topic follow permissions (future)
- Delegation intent expiration settings UI (use 30-day default; configurable later)
- Follow request message editing after send
- Block/mute users feature
