# Phase 3 Cleanup — Missing Features and Navigation Gaps

## Overview

Several features specced in Phases 3b and 3c were either partially implemented or missing frontend navigation links. This document covers all gaps that need to be resolved before moving to Phase 4.

Read `PROGRESS.md` for current state. Address all items in this document, then run the full backend test suite and update `PROGRESS.md`.

---

## 1. User Profile Navigation — Names Should Be Clickable Everywhere

**Problem:** There's no consistent way to navigate to a user's profile page. User names appear in many places throughout the app but aren't linked.

**Fix:** Make user names/avatars clickable links to `/users/{user_id}` in ALL of the following locations:

- **Proposal detail — vote panel:** "Your vote: Yes via **Dr. Chen**" — Dr. Chen's name should link to their profile
- **Proposal detail — vote flow graph:** Clicking a node already shows a detail panel — add a "View Profile" link in that panel. Also, double-clicking a node could navigate directly to the profile.
- **My Delegations — delegation table:** The delegate name in each row (e.g., "Dr. Chen" in the Healthcare row) should link to their profile
- **My Delegations — personal delegation graph:** Same as proposal graph — detail panel should include "View Profile" link
- **Delegate selection modal — search results:** User names in search results should be clickable to view their profile before deciding to delegate (opens in new tab or has a "View Profile" icon button alongside the Delegate/Request buttons)
- **Follow requests — incoming and outgoing:** The requester/target name should link to their profile
- **Notification dropdown:** Any user names mentioned should link to their profiles
- **Audit log (admin):** Actor names should link to profiles

**Implementation:** Create a reusable `<UserLink>` component that renders a user's display name as a styled link to their profile. Use this component everywhere a user name appears. The component should accept a `user` object (or at minimum `user_id` and `display_name`) and render:
```jsx
<Link to={`/users/${user.id}`} className="text-blue-600 hover:underline font-medium">
  {user.display_name}
</Link>
```

---

## 2. User Settings / Self-Editing Page

**Problem:** Users have no way to manage their own settings — creating/editing bios, registering as public delegates, or changing their follow/delegation approval preferences.

**Fix:** Create a user settings page at `/settings` (accessible from the user dropdown menu in the nav bar, separate from the public profile page at `/users/{id}`).

### Settings Page Layout

**Section: Profile Information**
```
Display Name: [editable field]
Email: [shown, not editable here — separate change email flow if needed later]
                                              [Save Changes]
```

**Section: Follow & Delegation Preferences**
```
When someone sends you a follow request:
  ○ Require my approval for all requests (default)
  ○ Auto-approve follow requests (view only)
  ○ Auto-approve follow and delegate requests

[Save Preferences]
```

Changing this updates the `default_follow_policy` field on the user model. Include a brief explanation under each option:
- "Require approval": "You'll review each request individually"
- "Auto-approve view": "Anyone can follow and see your votes, but delegation still requires your approval"  
- "Auto-approve delegate": "Anyone can follow you and delegate their votes to you automatically"

**Section: Public Delegate Registration**

Show a card for each topic in the system:

```
┌──────────────────────────────────────────────────────────┐
│ 🔴 Healthcare                                            │
│ Status: Not registered                                    │
│                                        [Become a Delegate]│
└──────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────┐
│ 🔵 Economy                                               │
│ Status: Active Public Delegate                            │
│ Bio: "I focus on fiscal policy and government spending    │
│ efficiency..."                                            │
│                                     [Edit Bio] [Step Down]│
└──────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────┐
│ 🟢 Environment                                           │
│ Status: Pending Admin Approval                            │
│ Bio: "Environmental scientist with 10 years..."          │
│ Submitted: 2 days ago                                     │
│                                       [Cancel Application]│
└──────────────────────────────────────────────────────────┘
```

**"Become a Delegate" flow:**
1. Click "Become a Delegate" on a topic card
2. Modal or inline form appears:
   - Bio textarea: "Tell others why they should trust you on this topic" (required, 50-1000 chars)
   - "Your votes on [topic] proposals will become publicly visible"
   - Submit button: "Apply" (if admin approval required) or "Register" (if open)
3. On submit: calls `POST /api/delegates/register` with topic_id and bio
4. Card updates to show "Pending Admin Approval" or "Active" depending on org policy

**"Edit Bio" flow:**
1. Click "Edit Bio" on an active delegate card
2. Bio textarea becomes editable
3. Save button updates the bio via API

**"Step Down" flow:**
1. Click "Step Down"
2. Confirmation dialog: "This will remove you as a public delegate for [topic]. People who delegated to you on this topic will need to choose a new delegate. Are you sure?"
3. On confirm: calls `DELETE /api/delegates/register/{topic_id}`
4. Card updates to "Not registered"

**Section: Account**
```
[Change Password]
[Export My Data]
[Delete My Account]
```

Change Password: current password + new password + confirm new password form.
Export My Data: downloads a JSON file with all the user's data (profile, votes, delegations, audit log entries). This supports the privacy policy's data portability promise.
Delete My Account: confirmation dialog with password verification, then deletes account and all associated data. Delegations TO this user are revoked (delegators are notified).

### Nav Updates

Add "Settings" to the user dropdown menu in the nav bar:
```
[👤 Alice ▾]
  My Profile      → /users/{my_id}  (public view of your profile)
  Settings        → /settings       (private settings/editing page)
  Logout
```

---

## 3. Public Profile Page — Verify Completeness

The user profile page at `/users/{id}` should already exist from Phase 3b. Verify it includes all of the following. If anything is missing, add it:

**For any user (public view):**
- Display name and username
- Relationship status indicator: "Public Delegate" badge, "You follow this user," "Follows you," or no relationship
- Action button based on relationship:
  - Public delegate for relevant topic: "Delegate" button
  - Following with delegation_allowed: "Delegate" button
  - Following with view_only: "Request Delegate" button
  - Not following: "Request Follow" and "Request Delegate" buttons
  - Pending request: "Request Pending" with cancel option

**Public delegate section (if they have delegate profiles):**
- Each topic they're registered for, with bio text
- Number of delegators on each topic
- Their voting record on proposals tagged with those topics (always visible — that's the point of being a public delegate)

**Voting record (permission-gated):**
- For topics where they're a public delegate: visible to everyone
- For other topics: visible only to approved followers
- For users without permission: "Follow [name] to see their full voting record" with action button
- Each vote entry shows: proposal title (linked to proposal), vote value (Yes/No/Abstain), date, topics

**Viewing your own profile:**
- Shows the same public view so you can see what others see
- Prominent link: "Edit your profile and settings →" linking to `/settings`

---

## 4. Additional Items to Verify

Check each of these and fix if missing:

**Delegate selection modal — profile preview:**
When searching for a delegate, each search result should have a small icon/link to view that user's full profile before deciding to delegate. This lets voters review someone's voting record and bio before trusting them with their vote. Could be a small "ℹ️" or "View Profile" link on each search result card that opens the profile in a new tab.

**Follow request messages:**
Verify that when users send follow requests, they can include an optional message, and that the message is displayed to the recipient in the incoming requests UI. If this was implemented but the demo seed data has generic or confusing messages, update the seed data messages to be realistic:
- For follow-only requests: "I'd like to follow your voting record. I've seen your work on local healthcare policy."
- For delegation requests: "I'd like you to represent me on environmental issues. Your background in climate science aligns with my priorities."

**Delegation revocation notification:**
When a delegation is revoked (either because the user removed it, the delegate stepped down as public delegate, or a follow relationship was revoked), the affected user should see something indicating the change. At minimum, their My Delegations page should show the topic as "No delegate" where there was previously one. A notification badge item ("Your healthcare delegation was revoked because Dr. Chen stepped down as a public delegate") would be ideal but is not required for this cleanup — just make sure the state change is reflected in the UI.

---

## Build Order

1. Create the `<UserLink>` component and deploy it across all locations listed in item 1
2. Build the Settings page (item 2) — profile editing, follow preferences, public delegate management, account actions
3. Verify and fix the public profile page (item 3)
4. Verify and fix additional items (item 4)
5. Run full backend test suite
6. Update `PROGRESS.md`

---

## Testing

After completing all items, the QA agent should verify:

- Click a user name on the proposal detail page → navigates to their profile
- Click a user name in the delegation table → navigates to their profile
- Click a node in the vote flow graph, then "View Profile" → navigates to their profile
- Navigate to /settings → settings page loads with current values
- Change follow policy → saves successfully, verify via API that the value changed
- Register as public delegate → form appears, submit creates application
- Edit public delegate bio → saves successfully
- Step down as public delegate → confirmation, then status changes
- View own profile → shows public view with "Edit settings" link
- View another user's profile → shows appropriate content based on relationship
