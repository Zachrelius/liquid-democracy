# Phase 85 — Steward Moderation Toolkit, Part 1: Attributed Comment Removal + Rejoin Ban

**Source:** Phase 83 findings B-1 and B-8 (see `phase83_readiness_findings_2026-07-02.md` — read it first). Remediation Group 1, first slice.

**Type:** Build pass. One migration. Single deploy. Does NOT touch `start.sh`, the worker, or any deploy-time codepath.

**Design decisions (locked by Z — do not relitigate):**
1. Moderator comment removal is a DISTINCT, ATTRIBUTED, NOTIFIED action — not a reuse of silent author self-delete. Transparency of moderation is a product value: removal must be visible as moderation.
2. `member.remove` gains a rejoin-ban option so removal has teeth in open-join orgs.

---

## Cluster 1 — Enforce `comment.moderate` (fix B-1)

**Model:** Add nullable `removed_by_id` FK (→ users) to `comments`. Semantics: `deleted_at` set + `removed_by_id` NULL = author self-delete (existing behavior, unchanged); `deleted_at` set + `removed_by_id` set = moderator removal.

**Route:** Extend `DELETE /api/comments/{comment_id}` in `routes/comments.py`:
- If caller is the author → existing self-delete path, byte-for-byte unchanged (`removed_by_id` stays NULL).
- Else, check `role_permissions.has_permission(db, caller, org_id, "comment.moderate")` where org_id is resolved from the comment's proposal (mind sub-org-scoped proposals: use the sub-org resolution path, `has_permission_on_sub_org`, consistent with how comment READ eligibility resolves in this module).
- Moderator path: set `deleted_at`, blank `body` (same as self-delete), set `removed_by_id = caller`.
- Audit event `comment.moderated` with details `{comment_id, proposal_id, author_id}` — body content NOT logged (consistent with existing comment audit events).
- Notification: new event type in `notification_events.py` (Comments category), e.g. `comment_moderated`, emitted to the comment's author: "A moderator removed your comment on <proposal title>." Registry-only addition; no schema change needed for events.
- Idempotency: already-deleted comment → 204 without re-audit (match existing behavior). A moderator "removing" an already-self-deleted comment is a no-op 204; do not overwrite a NULL `removed_by_id` on an already-deleted row.
- No moderator EDIT capability. Removal only.

**Frontend:** In the comment thread, a moderator-removed comment renders as "[removed by a moderator]" (distinct from "[deleted]" for self-deletes). Holders of `comment.moderate` see a remove control on others' comments, with a confirm dialog. The acting moderator's identity is in the audit log, not rendered publicly on the comment.

**Serializer:** Whatever field the FE needs to distinguish the two states (e.g. boolean `moderator_removed`) must be added to `CommentOut` — extend the serializer-coverage must-surface test accordingly (known model-vs-response gap pattern).

**Registry hygiene:** Update `permission_registry.py` description for `comment.moderate` if it references unimplemented behavior.

## Cluster 2 — Rejoin ban on removal (fix B-8)

**Model:** New table `org_bans`: `id`, `org_id` FK, `user_id` FK, `banned_by_id` FK, `reason` (nullable text, admin-facing only), `created_at`, `revoked_at` (nullable), `revoked_by_id` (nullable FK). Unique partial constraint: at most one ACTIVE (revoked_at IS NULL) ban per (org_id, user_id). Bans are org-scoped only — no platform-level bans in this pass.

**Removal flow:** The `member.remove` endpoint accepts an optional `ban: bool` (default false). When true, removal also writes an `org_bans` row in the same transaction. Frontend removal confirm dialog gains a "Ban from rejoining" checkbox (default unchecked) with one line of explanatory copy noting that in an open-join org, removal without a ban allows immediate rejoining. No em dashes in copy.

**Enforcement — the load-bearing invariant:** An active ban blocks EVERY join path for that (org, user):
- Open join → 403 "You have been removed from this organization and cannot rejoin."
- Approval-mode join request → same 403 at request creation (do not accept into the queue).
- Invitation acceptance → blocked at token consumption with the same error; an admin who genuinely wants the user back must revoke the ban first (Members page), then invite. Do NOT auto-revoke on invite.
- Enumerate ALL join/membership-creation entry points in `routes/organizations.py` and `routes/invitations.py` (including any re-activation of a lapsed membership row) and gate each. Sub-org joins are implicitly covered because parent membership is prerequisite — verify and assert this rather than assuming it.
- Demo orgs: demo login/join paths are out of scope and must be unaffected.

**Admin surface:** Members admin page gains a "Banned" section listing active bans (user, banned by, date, reason) with an Unban action. Unban sets `revoked_at`/`revoked_by_id` (never deletes the row — history is audit surface). Permission gate: same `member.remove` permission governs ban/unban (banning is an extension of removal; no new permission key this pass).

**Audit:** `member.banned` and `member.ban_revoked` events with actor + target.

**Governance floor check:** While in this code, VERIFY that the `member.remove` path calls `governance.count_active_governors()` and refuses to remove the last governor (parallel to the Phase 50 leave-org 409). If the guard is missing, that is in scope to add here with a side-effect test — it is the same invariant class this pass already touches.

## Verification matrix
- Side-effect assertions, not status codes: moderator removal asserts the resulting comment row (`deleted_at` set, `body` blanked, `removed_by_id` = moderator) and the audit + notification rows; ban tests assert the `org_bans` row and that a subsequent join attempt of EACH path fails AND creates no membership row.
- Self-delete regression: author delete still produces `removed_by_id` NULL and renders "[deleted]".
- Member without `comment.moderate` → 403 on others' comments (matrix-driven: test with the permission toggled off for moderator role too).
- Migration: hex-prefix revision ID, reversible, upgrade/downgrade cycle-tested, PG smoke both modes, on a verified prod alembic baseline (confirm `alembic current` matches actual prod schema before stacking).
- No backfill needed (new table + new nullable column; nothing seeded at org creation) — state this explicitly in the closeout rather than leaving it implicit.
- Browser verification: moderator remove flow, "[removed by a moderator]" rendering, ban checkbox in removal dialog, Banned list + unban, and a banned account bouncing off an open join.
- Existing tests green; report test-count delta in closeout.

## Out of scope (later Group 1/2 slices)
- Report/flag mechanism (B-4), UGC redaction beyond comments (B-5), rate limiting (B-7), platform-admin org/logo takedown (B-9/B-10), any new permission keys.
