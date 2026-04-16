# Phase 3: Visualization, Delegation Permissions, and Polish — Claude Code Build Spec

## Overview

Phase 3 adds three major features to the liquid democracy platform: a delegation permission system that controls who can delegate to whom and who can see whose votes, an interactive delegation graph visualization, and overall polish including the remaining UI pages, improved demo experience, and mobile refinements.

Read `PROGRESS.md` for current project state before starting.

---

## Part A: Delegation Permission Model

This is the most architecturally significant addition in Phase 3. It introduces tiered visibility and consent for delegation relationships.

### Core Concept

Votes are **private by default**. A user's voting record is visible only to:
- The user themselves
- The system (for delegation resolution)
- Users the voter has explicitly authorized (via follow approval)
- The public (only if the voter has registered as a public delegate, and only for topics they've registered for)

### New Data Models

#### Delegate Profiles

Users can register as public delegates for specific topics. This makes their votes on those topics publicly visible and allows anyone to delegate to them without prior permission.

```
delegate_profiles
  id: UUID
  user_id: FK -> users
  topic_id: FK -> topics
  bio: text (statement of qualifications/positions for this topic area)
  is_active: boolean (default true — can deactivate without deleting)
  created_at: datetime
  
  UNIQUE(user_id, topic_id)
```

When a user has a `delegate_profile` for a topic:
- Their votes on proposals tagged with that topic are publicly visible
- Anyone can delegate to them on that topic without requesting permission
- They appear in public delegate search/browse for that topic
- Their profile page shows their voting record for that topic

#### Follow Relationships

For private (non-public-delegate) delegation, a mutual consent flow is required.

```
follow_requests
  id: UUID
  requester_id: FK -> users (person who wants to follow/delegate)
  target_id: FK -> users (person being asked)
  status: enum [pending, approved, denied]
  permission_level: enum [view_only, delegation_allowed]
    — set by the TARGET when approving (not by the requester)
  message: text (nullable — optional note from requester: "Hey, it's Alice from book club")
  requested_at: datetime
  responded_at: datetime (nullable)
  
  UNIQUE(requester_id, target_id)
```

```
follow_relationships
  id: UUID
  follower_id: FK -> users
  followed_id: FK -> users
  permission_level: enum [view_only, delegation_allowed]
  created_at: datetime
  
  UNIQUE(follower_id, followed_id)
```

A `follow_relationship` is created when a `follow_request` is approved. The `follow_request` record is kept for audit purposes.

#### Default Follow Policy

Add to users model:
```
default_follow_policy: enum [require_approval, auto_approve_view, auto_approve_delegate]
  (default: require_approval)
```

- `require_approval`: all follow requests require manual approval
- `auto_approve_view`: automatically approve follow requests at view_only level
- `auto_approve_delegate`: automatically approve follow requests at delegation_allowed level

### Permission Logic

#### Who can delegate to whom:

1. **Public delegate on matching topic**: Anyone can delegate. No permission needed. Check: target user has an active `delegate_profile` for the delegation's topic.

2. **Approved follow relationship with delegation_allowed**: The follower can delegate. Check: `follow_relationships` exists with `permission_level = delegation_allowed`.

3. **All other cases**: Delegation is rejected with an error message explaining that a follow relationship with delegation permission is required.

#### Who can see whose votes:

1. **Your own votes**: Always visible to you.
2. **Public delegate votes**: Visible to everyone, but only on topics where they have a `delegate_profile`.
3. **Followed user votes**: Visible to approved followers (both `view_only` and `delegation_allowed`), on all topics. (Future refinement could add per-topic follow permissions, but keep it simple for now.)
4. **Delegation chain metadata**: If your vote was cast via a delegation chain (A → B → C), you can see the chain (who your delegate was, and who they delegated to) but you cannot see C's full voting record unless you separately have a follow relationship with C.
5. **All other cases**: Votes are not visible. API returns a "private" indicator rather than the vote value.

#### Revoking access:

- A followed user can revoke a follow relationship at any time.
- Revoking a follow relationship automatically revokes any delegation from the follower to the followed user.
- The system sends a notification (or at minimum, the follower sees their delegation marked as "revoked — delegate withdrew permission").
- Audit log entries are created for all follow/revoke actions.

### New API Endpoints

#### Delegate Profiles
- `GET /api/delegates/public` — browse public delegates, filterable by topic. Returns: user info, topics they're registered for, delegation count per topic, bio.
- `GET /api/delegates/public/{topic_id}` — public delegates for a specific topic, sorted by delegation count.
- `POST /api/delegates/register` — register as a public delegate for a topic. Body: `{ topic_id, bio }`.
- `DELETE /api/delegates/register/{topic_id}` — deactivate public delegate status for a topic. Existing delegations remain but no new ones can be created.

#### Follow System
- `POST /api/follows/request` — send a follow request. Body: `{ target_id, message (optional) }`.
- `GET /api/follows/requests/incoming` — view pending follow requests (for the current user to approve/deny).
- `GET /api/follows/requests/outgoing` — view follow requests the current user has sent.
- `PUT /api/follows/requests/{id}/respond` — approve or deny a request. Body: `{ status: "approved"|"denied", permission_level: "view_only"|"delegation_allowed" }`. If approved, creates the `follow_relationship`.
- `GET /api/follows/following` — list users the current user follows (with permission levels).
- `GET /api/follows/followers` — list users who follow the current user (with permission levels).
- `PUT /api/follows/{relationship_id}/permission` — upgrade or downgrade a follow relationship's permission level.
- `DELETE /api/follows/{relationship_id}` — revoke a follow relationship (either party can do this). Auto-revokes any delegation.

#### User Search (Updated)
- `GET /api/users/search?q=...` — search for users by name/username. Returns basic info (display name, username) but NOT voting records. This is used for the follow request flow.
- `GET /api/users/{id}/profile` — public profile. Shows: display name, public delegate registrations with bios, delegation counts on public topics, and voting record ONLY for public delegate topics. Private information is excluded.
- `GET /api/users/{id}/votes` — voting record. Returns votes only if the requesting user has permission (self, follower, or public delegate topics). Returns "private" for votes the requester can't see.

### Updating Existing Delegation Endpoints

The existing `PUT /api/delegations` endpoint must now check permissions before creating a delegation:

```python
# Pseudocode for delegation permission check
def can_delegate_to(delegator_id, delegate_id, topic_id):
    # Check 1: Is the delegate a public delegate for this topic?
    if has_public_delegate_profile(delegate_id, topic_id):
        return True
    
    # Check 2: Does a follow relationship with delegation_allowed exist?
    relationship = get_follow_relationship(delegator_id, delegate_id)
    if relationship and relationship.permission_level == "delegation_allowed":
        return True
    
    return False  # Delegation not permitted
```

Return a clear error if delegation is not permitted:
```json
{
  "detail": "Cannot delegate to this user. They are not a public delegate for this topic and you do not have a follow relationship with delegation permission. Send a follow request first."
}
```

### Audit Logging

Add audit events for:
- `follow.requested` — details: `{ target_id, message }`
- `follow.approved` — details: `{ requester_id, permission_level }`
- `follow.denied` — details: `{ requester_id }`
- `follow.revoked` — details: `{ other_party_id, revoked_by, delegations_revoked: [...] }`
- `delegate_profile.created` — details: `{ topic_id }`
- `delegate_profile.deactivated` — details: `{ topic_id }`

---

## Part B: Delegation Graph Visualization

Add an interactive network graph to the My Delegations page showing how votes flow through the delegation network. This is the "wow" feature that makes liquid democracy intuitive.

### Implementation

Use **D3.js force-directed graph** (available via CDN). If D3 is too complex for the timeline, **vis.js Network** is a simpler alternative with good defaults.

### What the Graph Shows

**Nodes:**
- The current user at the center (visually distinct — larger, highlighted border)
- Users the current user delegates TO (outgoing — shown to the right or above)
- Users who delegate TO the current user (incoming — shown to the left or below)
- One level of indirect connections (who your delegates delegate to, who your delegators delegate from) shown smaller/faded

**Edges:**
- Directed arrows showing delegation direction (delegator → delegate)
- Edge color or label indicates topic (matching topic badge colors)
- Edge thickness proportional to number of votes flowing through (a delegate with 50 delegators has thicker incoming edges)

**Node information on hover/click:**
- Display name
- Number of delegations held (incoming) per topic
- For public delegates: their bio
- For followed users: link to their voting record

**Interactivity:**
- Nodes are draggable (force layout repositions)
- Click a node to see details in a side panel
- Click an edge to see topic and delegation details
- Zoom and pan for larger networks

### Graph Data Endpoint

`GET /api/delegations/graph` — returns the graph centered on the current user:

```json
{
  "nodes": [
    {"id": "uuid", "label": "Alice", "type": "self"},
    {"id": "uuid", "label": "Dr. Chen", "type": "delegate", "is_public": true},
    {"id": "uuid", "label": "Dave", "type": "delegator"},
    ...
  ],
  "edges": [
    {"from": "alice_uuid", "to": "chen_uuid", "topic": "healthcare", "topic_color": "#e74c3c"},
    {"from": "dave_uuid", "to": "alice_uuid", "topic": null, "topic_label": "global"},
    ...
  ]
}
```

### Placement

Add the graph as a collapsible section on the My Delegations page, below the topic precedence section. Default to collapsed on mobile (performance), expanded on desktop. Include a "Show Delegation Network" toggle button.

---

## Part C: Additional Pages

### Dashboard (`/` or `/dashboard`)

The landing page after login. Shows at a glance:

**Your Attention Needed** (top section):
- Proposals in voting phase where your vote is unresolved (no direct vote, no applicable delegation)
- Pending follow requests awaiting your approval
- Delegation chain alerts (your delegate hasn't voted yet on an active proposal)

**Active Proposals** (middle section):
- Cards for proposals currently in voting phase, sorted by closing soon
- Compact version of the proposal card from the proposals list page

**Your Delegation Summary** (sidebar or bottom section):
- "You delegate on X topics to Y people"
- "Z people delegate to you"
- Quick link to My Delegations page

### User Profile (`/users/:id`)

Shows public information about a user:

**Public delegate section** (if they have any delegate profiles):
- Topics they're registered as public delegate for
- Bio for each topic
- Voting record on those topics (list of proposals with their votes)
- Number of delegators per topic

**For users you follow:**
- Their voting record on all topics (with votes you can't see marked as "private")
- Button to delegate to them (if permission_level allows)

**For users you don't follow:**
- Basic info only (display name, public delegate topics if any)
- "Send Follow Request" button

**Your own profile:**
- Everything above plus editing controls for display name, bio, delegate registrations
- Link to manage follow relationships

### Notifications (Lightweight)

Don't build a full notification system. Instead, add a simple notification indicator to the navigation bar:

- A badge on the nav showing the count of: pending follow requests + proposals where your vote is unresolved
- Clicking it shows a dropdown with brief descriptions and links to the relevant pages

---

## Part D: Demo Experience Polish

### Update the Demo Data Loader

Expand the seed data to showcase the new delegation permission system:

- Register dr_chen as a public delegate for Healthcare and Economy (with bios)
- Register env_emma as a public delegate for Environment
- Set up follow relationships between several users (some view_only, some delegation_allowed)
- Leave some delegation attempts that would require follow permission, so the demo can show the permission flow
- Create a pending follow request for Alice to demonstrate the approval flow

### Demo Login Enhancement

On the login page, if demo data is loaded, show a user selector:

```
Demo Mode — Quick Login:
[Alice Voter] [Dr. Chen] [Bob the Economist] [Carol] [Dave] [Emma]
```

Clicking a name logs in as that user immediately (with the demo password). This lets someone quickly switch between users to see the system from different perspectives — Alice sees her delegations, Dr. Chen sees people delegating to them, Dave sees a delegation chain.

---

## Part E: Polish and Quality

### Loading States
Every page and component that fetches data should show a skeleton/loading state while fetching. Don't show empty pages that flash before content appears.

### Error States
- Network errors: "Unable to connect to server. Check your connection."
- 401/403: Redirect to login or show "You don't have permission."
- 404: "This proposal/user was not found."
- 422 (validation): Show field-specific error messages from the API response.
- 500: "Something went wrong. Please try again."

### Empty States
- No proposals: "No proposals yet. Create one to get started."
- No delegations: "You haven't set up any delegations yet. Browse public delegates or follow friends to get started."
- No follow requests: "No pending requests."

### Mobile Responsive Refinements
- Test all pages at 375px width (iPhone SE)
- Delegation graph: hide by default on mobile, show a "View Graph" button
- Navigation: hamburger menu on mobile
- Vote panel: full-width buttons on mobile
- Tables: convert to card layout on mobile

### Navigation
Add a consistent top navigation bar:
- Logo/app name (links to dashboard)
- Proposals
- My Delegations
- Notification badge
- User menu (dropdown): Profile, Settings (future), Logout

---

## Build Order

### Phase 3a: Delegation Permissions (Backend)
1. Add new models (delegate_profiles, follow_requests, follow_relationships, default_follow_policy on users)
2. Alembic migration
3. Implement permission checking in delegation creation
4. New API endpoints for delegate profiles, follows, user search/profile
5. Update vote visibility endpoints to respect permissions
6. Audit logging for all new actions
7. Tests: permission checks, follow flows, visibility rules, revocation cascading
8. Update seed data with permission scenarios

### Phase 3b: Delegation Permissions (Frontend)
1. Update delegate selection modal to show public delegates and followed users
2. Follow request flow UI (send request, approve/deny, manage relationships)
3. Public delegate registration UI (on user profile settings)
4. User profile page with permission-aware voting record
5. Updated search to show user type and follow status

### Phase 3c: Visualization
1. Add graph data endpoint
2. Implement D3 or vis.js delegation graph component
3. Integrate into My Delegations page
4. Test with demo data (20+ nodes)

### Phase 3d: Additional Pages and Polish
1. Dashboard page
2. Notification indicator
3. Loading/error/empty states across all pages
4. Demo login enhancement (quick-switch user selector)
5. Mobile responsive pass on all pages
6. Navigation bar updates

### After each sub-phase, run all backend tests to confirm nothing is broken.

---

## What NOT to Build in Phase 3

Save these for future phases:
- WebSocket live updates (polling remains fine)
- Time simulation controls
- Sustained majority time-series chart
- Comments/discussion on proposals
- AI delegation agent support
- Per-topic follow permissions (all-or-nothing for now)
- Delegate "report card" or alignment scoring
- Advanced delegation strategies (majority, weighted — just strict_precedence for now)
