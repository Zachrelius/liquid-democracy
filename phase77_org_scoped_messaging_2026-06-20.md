# Phase 77 — Org-Scoped Direct Messaging

**Date:** 2026-06-20
**Status:** Spec ready for dispatch
**Staged:** Yes — Stage 1 (backend), Stage 2 (frontend)

---

## What this pass ships

Async 1:1 messaging within organizations, delivered through the existing notification system. Three messaging surfaces — delegate messaging, org inbox, and member-to-member DMs — share one conversation model but differ in who can initiate.

No WebSocket/real-time infrastructure. Messages are plain text. Conversations are 1:1 (no group threads beyond the org inbox's multi-admin-view pattern). This is a governance communication tool, not a chat app.

---

## What this pass is NOT

- **Not real-time chat.** No WebSocket, no typing indicators, no presence.
- **Not rich media.** Text-only messages. No attachments, images, or file sharing.
- **Not message editing/deletion.** Sent messages are immutable (append-only, like votes).
- **Not group messaging.** Conversations are 1:1. The org inbox is multi-reader but single-thread.
- **Not conversation search.** v1 has no full-text search over message content.
- **Not read receipts.** Unread tracking is local only — senders don't see if the recipient read their message.
- **Not a moderation system.** No message reporting, flagging, or admin message review in v1. Block-and-move-on is the abuse path.

---

## Design decisions

### D1 — Three messaging surfaces, one model
All three surfaces use the same `Conversation` + `Message` tables, differentiated by `conversation_type`:

| Surface | `conversation_type` | Who initiates | Gate |
|---|---|---|---|
| Delegate messaging | `delegate` | Any member | Delegate profile visible to sender (public, followers_only + approved follow, or public_accepting) |
| Org inbox | `org_inbox` | Any member | Always available; `org_inbox.view` gates the admin read/reply side |
| Member DM | `direct` | Any member | Org's `member_dm_policy` setting + per-user block check |

### D2 — Org-scoped, always
Every conversation belongs to exactly one org. There is no cross-org or platform-level messaging. This matches every other entity scope on the platform and keeps access control simple.

### D3 — Three-way member DM policy
`Organization.settings['member_dm_policy']`: `disabled` | `follow_only` | `open`

- **`follow_only`** (default): Members can DM other members they share a follow relationship with in either direction — if A follows B, both A and B can message each other. Messaging is a lighter trust level than delegation (which exposes vote history), so the existing follow consent gate is sufficient.
- **`open`**: Any member can DM any other member in the org. Per-user blocks are the abuse control.
- **`disabled`**: No member-to-member DMs. Delegate and org inbox messaging still work.

### D4 — Bidirectional follow rule
In `follow_only` mode, a `FollowRelationship` between two users in **either direction** is sufficient for either party to initiate a DM. The follow is a mutual trust signal — if you approved someone's follow request, you've accepted a communication relationship with them.

This applies to DM initiation. It does NOT apply to delegate messaging (which has its own visibility-based gate) or org inbox (which is always open).

### D5 — Conversations are always bidirectional once they exist
Once a conversation exists, both participants can send messages in it regardless of follow state, DM policy, or delegate visibility. A delegate who is messaged can always reply. A followed user who is messaged can always reply. The only thing that blocks messages in an existing conversation is a `MessageBlock`.

This is the critical rule: creation gates control who can START a conversation; participation is symmetric.

### D6 — Per-user DM opt-out
`User.settings['dm_disabled']` boolean (default `false`). When true, the user cannot receive new DM conversation initiations (conversation_type `direct`). Delegate messages and org inbox messages still arrive — those are role-scoped, not personal-preference-scoped. Existing conversations remain accessible and writable by both participants.

### D7 — Block mechanism
`MessageBlock` table: `(blocker_id, blocked_id, org_id)`. Org-scoped (blocking someone in one org doesn't affect another). Effects:
- Blocked user cannot create new conversations with blocker.
- Blocked user cannot send messages in existing conversations with blocker.
- Blocker's existing conversations with blocked user remain readable but accept no new messages from blocked user.
- Blocks are silent — the blocked user gets a generic "unable to send" error, not "you are blocked."

### D8 — Org inbox is multi-reader, single-thread
When a member sends an org inbox message, it creates a conversation with `recipient_id = NULL`. Any user with the `org_inbox.view` permission can see all org inbox conversations and reply. Replies carry the replying admin's identity — they come from a person, not "the org." An admin can close the conversation (sets `status = 'closed'`). A new message from the initiator reopens it.

### D9 — Context linking
Conversations can optionally link to a proposal via `context_proposal_id`. This supports the "why did you vote this way on X?" delegate-messaging use case — the conversation detail view shows the linked proposal as context. No other context types in v1.

### D10 — Notification delivery
Messages are delivered via the existing notification system. Two new event types, one new category. Signal level `standard` — defaults to in-app + email digest. Users who want instant email for DMs can configure it in notification preferences.

### D11 — Rate limiting
20 messages per hour per user per org. Uses the existing `rate_limit_utils` pattern. Prevents spam without interfering with normal conversation.

### D12 — Message immutability
Messages cannot be edited or deleted. This matches the platform's append-only philosophy (audit log, vote records). If a user sends something regrettable, the recipient can block them.

---

## Schema

### New tables

#### `conversations`

| Column | Type | Constraint | Notes |
|---|---|---|---|
| `id` | String (PK) | `default=_uuid` | |
| `org_id` | String (FK → organizations.id) | NOT NULL, indexed | Org scope |
| `conversation_type` | String | NOT NULL | `direct` \| `delegate` \| `org_inbox` |
| `initiator_id` | String (FK → users.id) | NOT NULL | User who started the conversation |
| `recipient_id` | String (FK → users.id) | NULLABLE | NULL for org_inbox conversations |
| `context_proposal_id` | String (FK → proposals.id) | NULLABLE | Optional linked proposal |
| `subject` | String(200) | NULLABLE | Optional subject line (set at creation) |
| `status` | String | NOT NULL, default `'active'` | `active` \| `closed` |
| `last_message_at` | DateTime | NULLABLE | Denormalized; updated on each new message. Sort key for conversation lists. |
| `created_at` | DateTime | NOT NULL, default `_now` | |

**Unique constraint:** `(org_id, conversation_type, initiator_id, recipient_id)` — prevents duplicate conversations. For org_inbox: `(org_id, 'org_inbox', initiator_id, NULL)` — one inbox thread per user per org.

**Important — direct conversation dedup:** For `conversation_type='direct'`, the pair `(A, B)` and `(B, A)` must resolve to the same conversation. The unique constraint alone doesn't handle this because `initiator_id` records who sent the first message. Dedup must be enforced at the application layer: on `POST /conversations`, query for an existing `direct` conversation matching `(org_id, 'direct', A, B) OR (org_id, 'direct', B, A)` before creating. See access control matrix for details.

**Indexes:**
- `(org_id, recipient_id, status)` — "conversations where I'm the recipient"
- `(org_id, initiator_id, status)` — "conversations I started"
- `(org_id, conversation_type)` — org inbox listing filtered by type

#### `messages`

| Column | Type | Constraint | Notes |
|---|---|---|---|
| `id` | String (PK) | `default=_uuid` | |
| `conversation_id` | String (FK → conversations.id) | NOT NULL, indexed | |
| `sender_id` | String (FK → users.id) | NOT NULL | |
| `body` | Text | NOT NULL | Sanitized via `nh3` (same pipeline as comments) |
| `is_system` | Boolean | NOT NULL, default `False` | For system messages ("conversation closed by admin") |
| `created_at` | DateTime | NOT NULL, default `_now` | |

**Index:** `(conversation_id, created_at)` — message ordering within a conversation.

#### `conversation_reads`

| Column | Type | Constraint | Notes |
|---|---|---|---|
| `user_id` | String (FK → users.id) | PK (composite) | |
| `conversation_id` | String (FK → conversations.id) | PK (composite) | |
| `last_read_at` | DateTime | NOT NULL | Updated when user views the conversation |

Unread count = messages in conversation where `created_at > last_read_at` and `sender_id != user_id`.

#### `message_blocks`

| Column | Type | Constraint | Notes |
|---|---|---|---|
| `id` | String (PK) | `default=_uuid` | |
| `blocker_id` | String (FK → users.id) | NOT NULL | |
| `blocked_id` | String (FK → users.id) | NOT NULL | |
| `org_id` | String (FK → organizations.id) | NOT NULL | |
| `created_at` | DateTime | NOT NULL, default `_now` | |

**Unique constraint:** `(blocker_id, blocked_id, org_id)` — one block record per pair per org.

### Org settings addition

Key: `member_dm_policy`
Values: `disabled` | `follow_only` | `open`
Default: `follow_only` (via `settings.get('member_dm_policy', 'follow_only')` — no backfill migration needed for existing orgs; they get `follow_only` behavior automatically)

### Permission addition

New key in `permission_registry.py`:

```python
# Add "Messages" to CATEGORIES list (after "Audit and analytics")

PermissionDefinition(
    "org_inbox.view",
    "View org inbox",
    "Allow viewing and responding to messages sent to the organization's shared inbox.",
    "Messages",
)
```

**Default grants:** `steward` and `admin` get it automatically (their `DEFAULT_GRANTS` entries are `set(ALL_PERMISSION_KEYS)`, which dynamically includes any new key). `moderator` and `member` do not get it by default.

**Backfill migration (REQUIRED — backfill rule):** Existing orgs' steward and admin roles do not have a `RolePermission` row for `org_inbox.view`. The migration must INSERT `RolePermission(role_id=<role.id>, permission_key='org_inbox.view', enabled=True)` for every existing role where `system_key IN ('steward', 'admin')` and no row for this key already exists. Ship an existing-vs-new-org parity assertion using the Phase 48 B0 parity-test helper pattern.

### Notification event additions

Add to `notification_events.py`:

```python
# Add "Messages" to CATEGORIES tuple

EventDefinition(
    key="message.received",
    label="New direct message",
    description="Someone sent you a direct message within an organization.",
    category="Messages",
    signal_level="standard",
),
EventDefinition(
    key="message.org_inbox",
    label="New message in org inbox",
    description="A member sent a message to the organization's shared inbox.",
    category="Messages",
    signal_level="standard",
),
```

### Response schemas

Add to `schemas.py`:

```python
class ConversationOut(BaseModel):
    id: str
    org_id: str
    conversation_type: str  # direct | delegate | org_inbox
    initiator_id: str
    recipient_id: Optional[str]
    subject: Optional[str]
    context_proposal_id: Optional[str]
    status: str  # active | closed
    last_message_at: Optional[datetime]
    created_at: datetime
    # Denormalized for list views:
    other_party_display_name: str  # resolved via verification.display_name_for
    other_party_id: Optional[str]  # NULL for org_inbox on the admin side
    unread_count: int
    last_message_preview: Optional[str]  # first 100 chars of last message body

class MessageOut(BaseModel):
    id: str
    conversation_id: str
    sender_id: str
    sender_display_name: str
    body: str
    is_system: bool
    created_at: datetime

class ConversationDetailOut(BaseModel):
    conversation: ConversationOut
    messages: list[MessageOut]
    context_proposal: Optional[dict]  # lightweight proposal summary if linked

class MessageBlockOut(BaseModel):
    id: str
    blocked_id: str
    blocked_display_name: str
    org_id: str
    created_at: datetime
```

---

## API routes

New file: `backend/routes/messages.py`

All routes require authentication + active org membership unless noted.

### Conversation management

| Method | Path | Permission | Notes |
|---|---|---|---|
| `GET` | `/api/orgs/{org_id}/conversations` | Member | List conversations where user is initiator OR recipient. Paginated, sorted by `last_message_at` desc. Includes unread count per conversation. For users with `org_inbox.view`, also includes org inbox conversations. |
| `POST` | `/api/orgs/{org_id}/conversations` | Member | Create a new conversation. Body: `{ recipient_id, conversation_type, subject?, context_proposal_id?, body }`. First message body is required — no empty conversations. See access control matrix below. |
| `GET` | `/api/orgs/{org_id}/conversations/{id}` | Participant | Get conversation + paginated messages (newest first, cursor-paginated). Updates `conversation_reads.last_read_at`. |
| `POST` | `/api/orgs/{org_id}/conversations/{id}/messages` | Participant | Send a message. Body: `{ body }`. Rate limited: 20/hr/user/org. See D5 — both participants can always send. |
| `POST` | `/api/orgs/{org_id}/conversations/{id}/read` | Participant | Mark conversation as read (upsert `conversation_reads.last_read_at` to now). |
| `POST` | `/api/orgs/{org_id}/conversations/{id}/close` | See below | Close a conversation. Org inbox: requires `org_inbox.view`. Direct/delegate: either participant. Inserts a system message "Conversation closed by {name}." |

"Participant" means: initiator, recipient, or (for org_inbox) any user with `org_inbox.view` in the org.

### Org inbox

| Method | Path | Permission | Notes |
|---|---|---|---|
| `GET` | `/api/orgs/{org_id}/org-inbox` | `org_inbox.view` | List all org inbox conversations. Filterable by status (`active` / `closed` / `all`). Paginated by `last_message_at` desc. |

### Blocks

| Method | Path | Permission | Notes |
|---|---|---|---|
| `GET` | `/api/orgs/{org_id}/message-blocks` | Member | List user's blocks in this org. |
| `POST` | `/api/orgs/{org_id}/message-blocks` | Member | Block a user. Body: `{ blocked_id }`. Cannot block yourself. |
| `DELETE` | `/api/orgs/{org_id}/message-blocks/{blocked_id}` | Member | Unblock a user. |

### Unread count

| Method | Path | Permission | Notes |
|---|---|---|---|
| `GET` | `/api/orgs/{org_id}/messages/unread-count` | Member | Returns `{ unread_count: int }` — total unread messages across all conversations in this org where user is a participant. Used by the nav badge. |

---

## Access control matrix — conversation creation

The `POST /conversations` endpoint enforces these rules. All checks happen server-side.

### `conversation_type = 'delegate'`
1. `recipient_id` is required and must be an active org member.
2. Recipient must have at least one `DelegateProfile` in this org with visibility the sender can see:
   - `public` or `public_accepting` → any org member can message.
   - `followers_only` → sender must have an approved `FollowRelationship` with recipient (sender follows recipient) in this org.
   - `private` → cannot be messaged via this surface.
3. Sender ≠ recipient.
4. No active `MessageBlock` from recipient → sender. Return 403 with `unable_to_send` (generic).
5. Recipient's `dm_disabled` setting is **not checked** for delegate messages — delegates have implicitly consented to being contacted via their public profile.
6. **Dedup:** If a delegate conversation already exists between this pair in this org (either direction of initiator/recipient), return the existing conversation. Do NOT create a duplicate.

### `conversation_type = 'org_inbox'`
1. `recipient_id` must be NULL (enforced server-side; ignored if sent by client).
2. Any org member can create. No block check, no DM policy check — members can always contact their org's leadership.
3. **Dedup:** If an org_inbox conversation already exists for this `(org_id, initiator_id)`, reopen it (set `status = 'active'` if closed) and return it rather than creating a duplicate.

### `conversation_type = 'direct'`
1. `recipient_id` is required and must be an active org member.
2. Sender ≠ recipient.
3. Org's `member_dm_policy` must not be `disabled`. Return 403 with error code `dm_policy_disabled`.
4. If `member_dm_policy = 'follow_only'`: there must be an approved `FollowRelationship` between sender and recipient **in either direction** within this org. That is: sender follows recipient OR recipient follows sender. Return 403 with `follow_required` if neither exists.
5. No active `MessageBlock` from recipient → sender. Return 403 with `unable_to_send` (generic — do not reveal block exists).
6. Recipient's `dm_disabled` must not be `true`. Return 403 with `recipient_unavailable` (generic).
7. **Dedup:** Query for existing `direct` conversation matching `(org_id, 'direct', A, B) OR (org_id, 'direct', B, A)`. If found, return the existing conversation. If found and closed, reopen.

### Sending a message in an existing conversation (`POST /{id}/messages`)
1. User must be a participant (initiator, recipient, or — for org inbox — holder of `org_inbox.view`).
2. No `MessageBlock` from the other participant → sender (for direct/delegate types). For org_inbox: no block check on admin replies; block check on initiator messages against individual admins is not enforced (the inbox is an org surface).
3. Rate limit: 20 messages/hr/user/org.
4. Body sanitized via `nh3` (same pipeline as comment bodies in `routes/comments.py`).
5. `conversation.last_message_at` updated to `_now()`.
6. If conversation `status = 'closed'`, set it back to `'active'` (reopen on new message).
7. Notification emitted to recipient(s) — see notification emission rules below.

---

## Notification emission

### `message.received`
- **Fires when:** A new message is sent in a `direct` or `delegate` conversation, OR an admin replies to an org_inbox conversation (fires to the initiator).
- **Audience:** The other participant (not the sender). For org_inbox admin replies: the initiator.
- **Payload:** `{ conversation_id, sender_display_name, preview (first 100 chars of body), conversation_type, context_proposal_id (nullable) }`
- **Emission point:** `POST /conversations/{id}/messages` handler, after commit.

### `message.org_inbox`
- **Fires when:** The initiating member sends a message in an `org_inbox` conversation (initial creation or follow-up messages from the initiator).
- **Audience:** All org members with `org_inbox.view` permission (excluding the sender).
- **Payload:** `{ conversation_id, sender_display_name, preview }`
- **Emission point:** `POST /conversations/{id}/messages` handler, after commit, when conversation_type is `org_inbox` AND sender is the initiator.

Admin replies to org inbox conversations do NOT fire `message.org_inbox` — the other admins don't need a notification for every reply. Only the initiator gets `message.received`.

---

## Email templates

Two new templates in `backend/email_templates/`:

### `message_received.html`
Subject: `New message from {sender_display_name} in {org_name}`
Body: Sender name, message preview (first 200 chars), link to conversation.
Follow existing email template patterns (org branding, unsubscribe link).

### `message_org_inbox.html`
Subject: `New org inbox message in {org_name} from {sender_display_name}`
Body: Sender name, message preview, link to org inbox.
Follow existing email template patterns.

---

## Frontend

### New pages

#### `MessagesPage` (`/orgs/{slug}/messages`)
- Nav entry in org navigation (icon: mail/message).
- Two tabs (or sections):
  - **My Messages:** conversations where user is initiator or recipient, sorted by `last_message_at` desc.
  - **Org Inbox** (visible only to users with `org_inbox.view`): all org inbox conversations.
- Each row: other party's display name (or "Org Inbox" label for inbox items on the member side), last message preview (truncated), relative timestamp, unread dot/badge.
- Empty state per tab.

#### `ConversationDetail` (`/orgs/{slug}/messages/{conversation_id}`)
- Header: other party's name (linked to their member profile or delegate page), conversation type badge (`Delegate` / `Direct` / `Org Inbox`), linked proposal card if `context_proposal_id` set.
- Message list: chronological scroll, sender-aligned (own messages right-aligned, theirs left-aligned). Load older messages via cursor pagination.
- Composer at bottom: text input + send button. Character limit display (5000 chars). Disabled states:
  - If blocked by recipient: "You can't send messages to this user."
  - If conversation closed: show "Send a message to reopen this conversation" placeholder (sending reopens automatically per D5/sending rules).
- Dropdown/menu actions:
  - "Block user" (not shown for org inbox conversations).
  - "Close conversation" (org inbox: admin only; direct/delegate: either party).

#### Org admin settings integration
The org inbox tab is integrated into `MessagesPage` rather than a separate admin page — avoids fragmenting the messaging surface. Admin-only visibility is controlled by the tab's presence/absence based on permission check.

### New components

#### `MessageButton`
Reusable button/link that appears on:
- **Delegate public pages** (`DelegatePublic.jsx`): "Message" button next to delegate info. Creates conversation with `conversation_type='delegate'`, pre-fills `recipient_id`. If viewing a specific proposal's delegate page, pre-fills `context_proposal_id`.
- **Org public landing / member-facing pages**: "Contact organization" button. Creates `conversation_type='org_inbox'`.
- **Member list** (when `member_dm_policy != 'disabled'`): "Message" action per member row. Creates `conversation_type='direct'`.
- **User profile / member detail** (when DM is available): "Message" button.

Button visibility logic:
- Delegate message button: shown when the delegate's profile is visible to the current user.
- Org inbox button: always shown to org members.
- DM button: shown when `member_dm_policy != 'disabled'` AND (if `follow_only`: a follow relationship exists in either direction). Hidden for self.

#### `MessageBadge`
Unread message count in the org nav. Options for integration:
- Extend the existing `NotificationBadge` to include message unread count as a separate indicator, OR
- Add a dedicated badge on the Messages nav item.

Code team's call — the important thing is that unread messages are visible without navigating to the messages page. Poll interval matches existing notification badge refresh.

### Settings additions

#### Org Settings (`OrgSettings`)
New section: **"Messaging"**
- **Member-to-member messaging:** radio/select with three options:
  - `follow_only` — "Members who follow each other" (default)
  - `open` — "Any member can message any member"
  - `disabled` — "Disabled (delegate and org inbox messaging still available)"
- Help text: "Controls whether members can send direct messages to other members. Delegate messaging and the org inbox are always available regardless of this setting."

#### User Settings (`Settings`)
New toggle in a "Messaging" section:
- **"Disable direct messages from other members"** — checkbox/toggle. Help text: "When enabled, other members cannot start new message conversations with you. You can still be contacted by delegates you follow and via the org inbox. Existing conversations are not affected."

#### User Settings > Notification Preferences
New "Messages" category section in the preferences matrix with the two new event types (`message.received`, `message.org_inbox`), following the existing matrix pattern.

#### User Settings > Blocked Users
New "Blocked Users" section (or subsection within an existing section):
- Per-org list of blocked users with display name and unblock button.
- Or: accessible from the Messages page via a "Manage blocks" link.
- Code team's call on placement.

---

## Staging plan

### Stage 1 (B0) — Backend

**Clusters:**

**B0-1: Models**
`Conversation`, `Message`, `ConversationRead`, `MessageBlock` in `models.py`. Follow existing model patterns (`_uuid` PKs, `_now` timestamps, `Mapped` type annotations).

**B0-2: Migration + backfill**
Alembic migration (hex-prefix revision ID) creating the four new tables + indexes + unique constraints. Permission backfill: INSERT `RolePermission(role_id, permission_key='org_inbox.view', enabled=True)` for every existing role with `system_key IN ('steward', 'admin')`. Must include existing-vs-new-org parity assertion.

**B0-3: Permission + notification registries**
- `permission_registry.py`: Add `"Messages"` to `CATEGORIES`, add `org_inbox.view` `PermissionDefinition`. Steward/admin DEFAULT_GRANTS auto-include via `ALL_PERMISSION_KEYS`.
- `notification_events.py`: Add `"Messages"` to `CATEGORIES`, add `message.received` and `message.org_inbox` `EventDefinition` entries (both `signal_level="standard"`).

**B0-4: Routes**
New file `backend/routes/messages.py` with all endpoints from the API routes section. Register router in `main.py`.

**B0-5: Schemas**
`ConversationOut`, `MessageOut`, `ConversationDetailOut`, `MessageBlockOut` in `schemas.py`.

**B0-6: Email templates**
`message_received.html` and `message_org_inbox.html` in `backend/email_templates/`.

**B0-7: Sanitization + rate limiting**
Message body sanitized via `nh3` (same path as comment bodies). Rate limit: 20/hr/user/org on send-message endpoint using `rate_limit_utils`.

**B0-8: Tests**
Full test suite:
- Conversation creation for each `conversation_type`:
  - `delegate`: test each delegate visibility level (public, public_accepting, followers_only with/without follow, private → rejected).
  - `org_inbox`: test creation, dedup/reopen, admin visibility via `org_inbox.view`.
  - `direct`: test each `member_dm_policy` mode:
    - `disabled` → 403.
    - `follow_only` → test with forward follow, reverse follow, no follow → 403.
    - `open` → test with no follow relationship (succeeds).
  - `direct` + `dm_disabled` on recipient → 403.
  - `direct` + block from recipient → 403 with generic error.
  - Dedup: creating conversation that exists returns existing (both pair orderings for `direct`).
- Message sending:
  - Both participants can reply in existing conversation (D5 — bidirectional).
  - Block prevents sending in existing conversation.
  - Rate limiting fires at 20/hr.
  - Body sanitization strips dangerous HTML.
  - `last_message_at` updated.
  - Sending to closed conversation reopens it.
- Org inbox:
  - Multiple admins with `org_inbox.view` can see same conversation.
  - Admin reply fires `message.received` to initiator, NOT `message.org_inbox`.
  - Initiator follow-up fires `message.org_inbox` to admins.
- Unread count:
  - Correct count after messages sent.
  - Marking read zeroes count.
  - Own messages don't count as unread.
- Block CRUD: create, duplicate → 409, unblock, re-block.
- Permission backfill parity: assert existing org steward/admin have `org_inbox.view` == fresh org steward/admin.
- Org-scope enforcement: cannot read/write conversations in orgs user doesn't belong to.
- Notification emission: `message.received` fires for DM/delegate messages; `message.org_inbox` fires for inbox messages from initiator.

**Stage 1 verification:**
- All tests pass.
- `bash start.sh` with prod-like env — migration applies cleanly on both fresh DB and existing DB with data.
- Permission backfill verified: query at least one existing org's steward/admin roles for `org_inbox.view` row.

### Stage 2 (B1) — Frontend

1. `MessagesPage` with My Messages + Org Inbox tabs.
2. `ConversationDetail` with message list, composer, actions.
3. `MessageButton` wired into `DelegatePublic`, org landing, member list.
4. `MessageBadge` in org nav.
5. Org Settings: "Messaging" section with `member_dm_policy` radio.
6. User Settings: "Disable direct messages" toggle.
7. User Settings > Notification Preferences: "Messages" category.
8. Blocked users management UI.

**Stage 2 verification:** Browser-test full flows:
- Create delegate conversation from delegate page → send and receive messages.
- Create org inbox message → admin sees it in Org Inbox tab → admin replies → initiator sees reply.
- Create direct DM in `follow_only` org with follow in each direction → verify both work.
- Verify `disabled` org shows no DM buttons on member list.
- Block a user → verify message send fails → unblock → verify send works.
- Toggle `dm_disabled` → verify new conversation initiation blocked.
- Verify unread badge appears and clears.

---

## Audit considerations

Message content is **not** logged to the `audit_log` table. Messages are a communication tool, not a governance action. This prevents audit bloat and avoids giving admins a backdoor to read members' private conversations. Block/unblock actions are similarly not audit-logged (personal preferences).

If moderation/reporting is added in a future pass, the moderation *action* would be audit-logged, not the message content itself.

---

## Migration notes

- **Hex-prefix revision ID** on the Alembic migration.
- **Permission backfill** is the load-bearing piece: INSERT `RolePermission` rows for `org_inbox.view` on every existing org's steward and admin roles. Pattern: `SELECT r.id FROM roles r JOIN organizations o ON r.org_id = o.id WHERE r.system_key IN ('steward', 'admin')`, then bulk-insert `(role_id, 'org_inbox.view', True)` where not exists.
- **No org settings backfill needed** — `member_dm_policy` defaults to `follow_only` via `settings.get('member_dm_policy', 'follow_only')`.
- **No user settings backfill needed** — `dm_disabled` defaults to `false` via `settings.get('dm_disabled', False)`.
- **start.sh not touched** — no new workers or side-processes. Standard migration-on-deploy path.

---

## Tech debt / future work (not in scope)

- **Message moderation / reporting:** Flag a conversation for admin review. Would add `message.moderate` permission.
- **Read receipts:** Optional per-user toggle showing "seen" indicators to senders.
- **Message search:** Full-text search over message bodies within an org.
- **Richer context linking:** Link to specific votes, comments, or topics — not just proposals.
- **Group conversations:** Multi-party threads beyond the org inbox pattern.
- **Message reactions:** Emoji reactions.
- **Auto-close stale conversations:** Close org inbox conversations after N days of inactivity.
- **Conversation export:** Allow users to download their message history.

---

## Dispatch

Stage 1: `Read and execute phase77_org_scoped_messaging_2026-06-20.md and implement Stage 1 (B0 — backend) only.`

Stage 2 (after Stage 1 verified): `Read and execute phase77_org_scoped_messaging_2026-06-20.md and implement Stage 2 (B1 — frontend) only.`
