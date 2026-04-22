# Phase 5 — Permission-Alignment and Dialog Replacement Spec

**Type:** Cleanup pass. No new features.
**Dependencies:** Phase 4 Cleanup complete (current `master`).
**Goal:** Close three clustered frontend/backend permission-alignment gaps, and replace all blocking JavaScript dialogs with in-DOM components so browser tests stop stalling on them.

---

## Context

Phase 4 Cleanup left nine technical debt items in `PROGRESS.md`. Three of them stem from the same pattern — the frontend doesn't reflect the backend's permission reality — and a fourth (from external QA guidance) is that Claude-in-Chrome cannot interact with native `alert()` / `confirm()` / `prompt()` dialogs, so any test path that hits them stalls. This pass addresses all four together because:

1. They're small and independent of upcoming feature work.
2. The dialog issue will become a bigger problem as Phase 6+ adds multi-option voting, Polis, and comments — each of which will need its own browser-test coverage.
3. Fixing the permission-alignment issues piecemeal risks the pattern calcifying. Doing them together forces the discipline "frontend permission state mirrors backend permission state" to be visible across the codebase.

This spec is deliberately narrow. No URL routing, no notification work, no broader accessibility audit, no role-permissions refactor. All of those are later phases.

---

## Fix 1 — Admin Route Guard Distinguishes Admin-Only vs Moderator-Accessible Routes

### The bug

`frontend/src/AdminRoute.jsx` uses `isModeratorOrAdmin` as its single authorization check. This means moderators can access every admin route via direct URL, including routes whose pages should be admin-only (`/admin/settings`, `/admin/delegates`, `/admin/analytics`). The nav bar correctly hides these links from moderators, but the route guard doesn't enforce the same distinction.

Backend is fine — `/api/orgs/{slug}` PATCH requires `require_org_admin`, and delegate-application approval/denial requires admin. Any moderator trying to actually save settings gets a 403. But the page still loads, the moderator sees the form, and only discovers their lack of power on submit. This is confusing UX and a spec deviation.

### Scope

Introduce a distinction between admin-accessible and moderator-accessible routes at the frontend.

**Option A (preferred):** Add a second guard component — e.g., `AdminOnlyRoute` — that checks `isAdmin` (not `isModeratorOrAdmin`). Wrap the admin-only routes in it. Keep `AdminRoute` for routes moderators can legitimately use.

**Option B:** Modify `AdminRoute` to accept a `requireAdmin` prop (default `false`). Routes set `requireAdmin={true}` when the page is admin-only.

Use Option A unless there's a reason the dev team finds it worse in practice — it's more greppable and makes the intent visible at the route definition site.

### Classification of existing admin routes

Based on the backend permission decorators in `backend/routes/organizations.py`:

| Route | Page | Access level |
|-------|------|--------------|
| `/admin/settings` | OrgSettings | admin only (backend: `require_org_admin`) |
| `/admin/members` | Members | moderator-accessible (backend: mixed — see Fix 3 below) |
| `/admin/proposals` | ProposalManagement | moderator-accessible (backend: `require_org_moderator_or_admin` for create/advance) |
| `/admin/topics` | Topics | moderator-accessible (backend: moderator can edit, admin required to create/delete) |
| `/admin/delegates` | DelegateApplications | admin only (backend: `require_org_admin`) |
| `/admin/analytics` | Analytics | admin only (backend: `require_org_admin`) |

Update `frontend/src/App.jsx` so `/admin/settings`, `/admin/delegates`, and `/admin/analytics` use the admin-only guard. The other three stay on the moderator-accessible guard.

### Acceptance criteria

- Moderator navigating directly to `/admin/settings` is redirected to `/proposals` (or a 403-style "not authorized" page, dev team's choice — redirect is fine).
- Moderator can still access `/admin/members`, `/admin/proposals`, `/admin/topics` via direct URL.
- Admin can access all six admin routes.
- At least one browser test per access level is added to Suite I (see test plan at the end of this spec).

---

## Fix 2 — Admin Members Page Renders Correctly for Moderators

### The bug

When a moderator opens `/admin/members`, the page shows "No members found" even though the org has plenty of members. The member list is empty.

### Root cause

`frontend/src/pages/admin/Members.jsx` — specifically the `load()` callback — fetches both members and invitations in parallel via `Promise.all`:

```javascript
const [mems, invs] = await Promise.all([
  api.get(`/api/orgs/${slug}/members`),
  api.get(`/api/orgs/${slug}/invitations`),
]);
```

The members endpoint (`GET /api/orgs/{slug}/members`) requires only membership — moderators can access it. But the invitations endpoint (`GET /api/orgs/{slug}/invitations`) is guarded by `require_org_admin`, so it returns 403 for moderators. `Promise.all` rejects on any rejection, the `catch { /* ignore */ }` swallows the error, and neither `setMembers` nor `setInvitations` ever runs. The page stays in its initial empty state.

This is not a backend query filter issue as hypothesized in `PROGRESS.md` — it's a frontend fetch-coupling issue.

### Scope

Decouple the two fetches so one failing doesn't sink the other, and gate the invitations fetch on `isAdmin`:

```javascript
const load = useCallback(async () => {
  if (!slug) return;
  try {
    const mems = await api.get(`/api/orgs/${slug}/members`);
    const active = mems.filter(m => m.status !== 'pending_approval');
    const pending = mems.filter(m => m.status === 'pending_approval');
    setMembers(active);
    setPendingRequests(pending);
  } catch (e) {
    // surface error in UI instead of silently swallowing
  }
  if (isAdmin) {
    try {
      const invs = await api.get(`/api/orgs/${slug}/invitations`);
      setInvitations(invs);
    } catch (e) {
      // ignore — invitations are a side panel
    }
  }
  setLoading(false);
}, [slug, isAdmin]);
```

The exact structure is at the dev team's discretion, but the behavior must be: moderator sees members and pending join requests; admin sees all three sections.

While you're in this file, also audit that the three `isAdmin &&` gates already in the render tree still hold after decoupling (invite section, invitations list). They already use `isAdmin` correctly — just confirm.

### Acceptance criteria

- Moderator viewing `/admin/members` sees the full active-member list and can suspend/reactivate members (already supported by the backend — `require_org_moderator_or_admin` on suspend, `require_org_admin` on reactivate; moderators see Suspend, not Reactivate, and the bug H11 was in the admin view).
- Moderator viewing `/admin/members` does NOT see the "Invite Members" section, the Invitations table, or the pending-invitations section. These stay admin-only.
- Moderator can see and approve/deny pending join requests (endpoint is `require_org_moderator_or_admin`, already correct on the backend).
- Admin behavior is unchanged.
- Error state: if the members endpoint fails, show the ErrorMessage component instead of silently rendering empty.

### Note on reactivate for moderators

The backend has `require_org_admin` on `/api/orgs/{slug}/members/{user_id}/reactivate`. This is intentional — reactivating a suspended member is higher-trust than suspending. The frontend already only shows "Reactivate" when the member is suspended, and we don't need to change that. Just confirm the button doesn't render for moderators; if it does, also hide the Reactivate button for non-admins. (It might already be hidden — worth checking.)

---

## Fix 3 — Unverified Users See Disabled Vote and Delegate Controls

### The bug

Unverified users — those who haven't yet clicked their email verification link — see the full voting UI and delegation UI as if they could use it. Clicking "Vote Now" or "Yes" triggers the backend's verification check and returns an error, which is then displayed inline. This works (per H7 and H8), but the UX is bad: the user clicks through three screens before discovering they can't act, and the error message appears in a different place each time depending on which flow they took.

### Scope

Hide or disable vote and delegate action controls for unverified users, with a clear explanation of why.

**Where to apply:**

1. **Proposal detail page (`frontend/src/pages/ProposalDetail.jsx`):** The "Vote Now" / "Cast Vote" / "Yes" / "No" / "Abstain" controls should be disabled (greyed out) for unverified users, with a tooltip or inline note: "Verify your email to vote." The existing yellow banner at the top of every page (the `EmailVerificationBanner` component) already reminds the user to verify — the inline disabled state connects the banner to the specific action.

2. **Delegations page (`frontend/src/pages/Delegations.jsx`):** The "Set Delegate" / "Change Delegate" / "Remove" buttons should be disabled for unverified users. Same tooltip/note.

3. **Delegate modal (`frontend/src/components/DelegateModal.jsx`):** If the modal opens for an unverified user (e.g., they had multiple tabs open), the action buttons inside it — "Delegate", "Request Delegate", "Request Follow" — should be disabled with the same explanation.

**How to detect verification status:** `AuthContext` already holds the current user. The user object has an `email_verified` boolean. If it doesn't, add it to the context. Consume that flag in the three files above.

**Explicit non-goal:** Do not remove or alter the backend enforcement. The backend must continue to reject unverified actions (403) — this is a defense-in-depth measure. The frontend change is UX only.

### Acceptance criteria

- Unverified user on a voting proposal sees greyed-out vote buttons with a "Verify your email to vote" tooltip or small note. Clicking them does nothing (or shows the tooltip).
- Unverified user on the Delegations page sees greyed-out Set/Change/Remove buttons with similar treatment.
- Unverified user opening the delegate modal sees greyed-out action buttons.
- Verified user sees all controls enabled and functional. No regression in voting or delegation flows.
- Backend enforcement is not touched.

---

## Fix 4 — Replace Blocking JavaScript Dialogs with In-DOM Components

### The bug

The codebase uses `alert()`, `confirm()`, and (less likely) `prompt()` throughout the frontend for error messages, success toasts, and destructive-action confirmations. These are native browser dialogs that:

- Block the browser's event loop until the user dismisses them.
- Cannot be interacted with by Claude-in-Chrome — any test run that hits one stalls until a human manually dismisses it. This has already forced QA to skip steps during Suite H (e.g., H2 topic deactivation was partially tested because `window.confirm()` blocked CDP automation).
- Look bad. They don't match the platform's design language and users rightly distrust them.

Known examples (from a partial read of `Members.jsx`):

```javascript
alert(e.message);                                                    // error toasts
if (window.confirm(`Remove ${member.display_name}...`)) { ... }      // destructive confirms
```

There are more throughout the codebase. The dev team must do a comprehensive audit (grep for `alert(`, `window.alert`, `window.confirm`, `window.prompt`, `confirm(` in `frontend/src/`) and replace every instance.

### Scope

**New components:**

1. **`Toast` / `ToastProvider` (in `frontend/src/components/Toast.jsx` or similar):**
   - In-DOM notifications that appear in a fixed position (top-right is standard) and auto-dismiss after a few seconds.
   - Three variants: success (green), error (red), info (blue). Optional: warning (yellow).
   - Exposed via a `useToast()` hook or a simple `toast.success(msg)` / `toast.error(msg)` API.
   - Mounted once at the app root (in `App.jsx` under the `AuthProvider`) so it's available everywhere.
   - Pick a minimal implementation. If you use a library (e.g., `react-hot-toast`, `sonner`), that's fine — pick something small, well-maintained, Tailwind-compatible, and already has an MIT/ISC-type license.

2. **`ConfirmDialog` / `useConfirm` (in `frontend/src/components/ConfirmDialog.jsx` or similar):**
   - In-DOM modal with title, message, destructive/non-destructive styling, and Cancel/Confirm buttons.
   - Exposed via a `useConfirm()` hook returning a promise — `const ok = await confirm({ title, message, destructive: true })` — that resolves true/false based on user action.
   - Focus-trap-aware (Esc cancels, Tab cycles through buttons, Enter on Confirm).
   - Mounted once at the app root like Toast.

**Replacement pattern:**

- Every `alert(msg)` → `toast.error(msg)` for errors, `toast.success(msg)` for successes.
- Every `alert(e.message)` in a catch block → `toast.error(e.message)`.
- Every `if (window.confirm(msg))` → `if (await confirm({ title: '...', message: msg, destructive: true }))`. Note this requires the surrounding function to be async.
- Every `prompt(msg)` — probably none, but if any exist, replace with a small inline form or modal.

**Audit the full codebase.** Expected locations include (but are not limited to):

- `pages/admin/Members.jsx`, `pages/admin/Topics.jsx`, `pages/admin/ProposalManagement.jsx`, `pages/admin/OrgSettings.jsx`, `pages/admin/DelegateApplications.jsx`
- `pages/Delegations.jsx`, `pages/ProposalDetail.jsx`, `pages/Settings.jsx`
- `components/DelegateModal.jsx`, `components/FollowRequests.jsx`
- Anywhere else `grep` finds a match.

### Acceptance criteria

- `grep -rn "alert(" frontend/src` returns no hits in application code (test files and node_modules don't count).
- `grep -rn "window.confirm" frontend/src` returns no hits.
- `grep -rn "window.alert" frontend/src` returns no hits.
- `grep -rn "prompt(" frontend/src` returns no hits in application code (CSS `prompt:` etc. don't count — use context).
- Toast component renders visually consistent with the platform's design (Tailwind, rounded corners, matching color palette).
- ConfirmDialog supports Esc-cancel and Enter-confirm.
- All previously-alert/confirm'd flows work: creating a topic shows a success toast, removing a member shows a destructive confirm then a success toast on success or error toast on failure, etc.
- QA can run browser tests end-to-end through destructive actions without CDP stalling on native dialogs.

---

## Testing

### Backend tests

Fix 2 is a frontend fix — no new backend tests required. Fixes 1, 3, and 4 are frontend-only.

However, if the dev team adds any backend changes (e.g., exposing `email_verified` on a `/me` endpoint that doesn't already expose it), add tests accordingly.

### Browser tests — new Suite I in `browser_testing_playbook.md`

Add the following suite to `browser_testing_playbook.md`. Execute with Claude-in-Chrome and commit the results. These tests replace no existing tests — Suite H and all earlier suites remain.

**I1: Admin-only route blocks moderator via direct URL.**
Login as a moderator (e.g., Carol). Navigate directly to `/admin/settings`. Confirm the page redirects to `/proposals` (or a 403 page). Repeat for `/admin/delegates` and `/admin/analytics`.

**I2: Moderator-accessible route loads for moderator via direct URL.**
Login as moderator. Navigate directly to `/admin/members`, `/admin/proposals`, `/admin/topics`. Confirm each loads successfully.

**I3: Admin route guard still works for admin.**
Login as admin. Confirm all six admin routes load successfully.

**I4: Members page renders correctly for moderator.**
Login as moderator. Navigate to `/admin/members`. Confirm:
- Member list is populated (not "No members found")
- Pending join requests section renders if any exist
- "Invite Members" section is not visible
- Invitations table is not visible
- Suspend button appears for active members

**I5: Unverified user sees disabled vote controls.**
Register a new user (which creates them unverified). Navigate to a proposal in "Voting" status. Confirm the vote buttons are greyed out with an explanation tooltip/note. Attempt to click them and confirm no action occurs.

**I6: Unverified user sees disabled delegate controls.**
Still as the unverified user from I5. Navigate to `/delegations`. Confirm Set/Change/Remove buttons are greyed out with explanation. Open the delegate modal if possible and confirm its action buttons are also greyed out.

**I7: Verified user retains full control.**
Verify the user from I5 (click the verification link, or use the debug-mode console output to get the token). Return to the proposal and Delegations page and confirm all controls are enabled and functional.

**I8: Toast replaces alert for success/error.**
Trigger a successful action (e.g., create a topic as admin). Confirm a success toast appears in-DOM (not a native browser alert). Trigger an error (e.g., create a topic with a duplicate name). Confirm an error toast appears in-DOM.

**I9: ConfirmDialog replaces window.confirm for destructive actions.**
Attempt a destructive action (e.g., remove a member, delete a topic). Confirm an in-DOM modal appears with Cancel and Confirm buttons. Cancel it — nothing happens. Retry and confirm — action proceeds. No native browser dialog appears at any point.

**I10: Regression.**
Re-run Suite H tests H1–H13. All must still pass.

### Commit the test results

Save the completed Suite I results into `browser_testing_playbook.md` following the same format as Suite H. The passdown from the previous planning agent flagged that Suites E–G were executed ad-hoc but never committed — don't repeat that.

---

## Definition of Done

- All four fixes are implemented.
- Backend tests still pass (no regressions): `cd backend && python -m pytest tests/ -v` reports all 96+ tests passing.
- Browser Suite I tests all pass and are committed to `browser_testing_playbook.md`.
- `PROGRESS.md` is updated with a new Phase 5 section describing what was done.
- Three technical debt items from Phase 4 Cleanup are moved from "open" to "resolved" in `PROGRESS.md`: moderator admin route too permissive, members page empty for moderators, unverified user UX.
- Add a note to the technical debt section: blocking JavaScript dialogs are gone, but further UX improvements to the Toast/Confirm components (positioning, animations, keyboard shortcuts beyond Esc/Enter) can happen later and aren't tracked.

---

## Out of Scope

The following are explicitly deferred to later phases:

- Path-based org URLs (Phase 11)
- Configurable role permissions / proper permission-keyed system (Phase 12)
- Notification system beyond toasts (deferred past this sequence)
- WCAG 2.1 AA accessibility audit (deferred past this sequence) — though the Toast/Confirm components should be keyboard-accessible as a baseline
- Rate limiting on non-auth endpoints
- CI/CD pipeline
- PostgreSQL dual-DB testing
- Edit Draft inline edit form (technical debt but not in this pass)

Keep the scope tight. If the dev team finds related issues during execution, log them as new technical debt items in `PROGRESS.md` rather than expanding this spec.
