# Phase 44 — Multi-Admin Approval Workflow

**Status:** Ready to build. First pass of the elected-leadership arc — an N-of-M ratification queue for destructive admin actions. Standalone-valuable now; the data model it lands is the foundation the later elected-stewards/admins layer builds on. Merged dispatch + spec doc (Phase 19+ convention).

**Branch:** `phase-44/multi-admin-approval` → `--no-ff` merge to master at close.

---

## Dispatch framing

### Goal

Today, destructive org admin actions execute immediately on a single admin's call: removing a member, deleting a topic, changing the permission matrix, deleting the org. For orgs with shared-governance norms (multiple admins, a board, a steward team) that single-actor model is both a safety risk and a poor fit. This pass introduces an **opt-in, per-org, N-of-M ratification queue**: when enabled, a configured set of destructive actions don't execute immediately — they enter a `PendingAdminAction` queue, fan out a notification to the org's other eligible approvers, collect approvals/declines, and execute only when the approval threshold is met (or expire after a window). Off by default platform-wide; every org behaves exactly as today until a steward opts in.

This is a real product feature on its own (safer multi-admin orgs) **and** the concrete prerequisite for the flagship "elected leadership via the platform's own voting" work — the `PendingAdminAction` model + ratification mechanics give that future layer a place to land. This pass does NOT build the elected layer; that needs its own design conversation (term lengths, recall, bootstrap, failure modes) once this foundation exists.

### Branch + merge

- Branch: `phase-44/multi-admin-approval`.
- All work commits to that branch; `git merge --no-ff` to master at close; push to origin; Railway auto-deploys.

### Verification matrix

| Check | Required | Notes |
|---|---|---|
| Backend pytest (full) | Yes | New model + endpoints + permission gate + execution + expiry. Target a substantial new-test block. **Assert side effects, not just API contracts** (CLAUDE.md): a ratified action must actually execute (member actually removed, topic actually deleted); a pending action must NOT execute until threshold; an expired action must NOT execute. Test the notification fan-out fired (mock-inspect) and audit entries written at submit / approve / decline / execute / expire. |
| Migration reversible + cycle test | Yes | New `PendingAdminAction` table + `PendingActionApproval` table (see clusters). Implement `down()`. Add `test_phase_44_migration_cycle` (upgrade→downgrade→upgrade on SQLite). |
| PG smoke (`pg_smoke.py --mode both --prior-revision 4b0bf8f1761f`) | Yes | Migration added. **Prior revision confirmed `4b0bf8f1761f`** (Phase 39 identity hardening) — planning agent verified it's the single clean head (31 migrations, one head, no branches) as of this spec. The new migration's `down_revision = "4b0bf8f1761f"`. Re-confirm at build time only if other migrations merged since. |
| Frontend build | Yes | New pending-actions surface + opt-in settings + inline ratification UI. |
| Browser verification (Chrome MCP, prod) | Yes | Full ratification lifecycle on prod after deploy (scenarios below). |
| Bundle hash changed + backend non-502 post-deploy | Yes | Confirm in closeout. |

### QA scenarios (run on prod after deploy)

1. **Opt-in toggle:** as steward, enable multi-admin approval in Org Settings → setting persists → with it OFF, a destructive action still executes immediately (regression check that default behavior is untouched).
2. **Pending creation + fan-out:** with it ON (threshold 2-of-N), admin A initiates "remove member" → action does NOT execute → a `PendingAdminAction` appears in the pending list → other eligible approvers get a notification.
3. **Threshold execution:** admin B approves → with threshold met, the action executes (member actually removed) → initiator notified of execution → audit log shows submit + approvals + execute.
4. **Decline path:** a different pending action → admin B declines with a reason → action does NOT execute → initiator notified with the decline reason → status reflects declined.
5. **Expiry:** a pending action left unratified past its window → expires → does NOT execute → status reflects expired (verify via the configured window; QA may need a short test window or DB inspection).
6. **Self-approval rule:** the initiator's own submission counts (or doesn't) toward threshold per the locked decision below — verify the live behavior matches D4.
7. **Permission gate:** a non-approver (regular member) cannot see the pending-actions queue or ratify.
8. **Change preview + discovery (D11):** initiate a permission-matrix edit under approval → an approver sees, without asking anyone, (a) a notification, (b) a count badge in the admin area, (c) an in-context banner on the permissions page, and (d) in the ratify view, a **per-role before→after diff of only the changed permissions** (verify it shows the actual deltas, not the full matrix, using human labels). Then have a *different* admin change the matrix directly (with approval temporarily off, or via a second pending action) so the baseline drifts, and confirm the pending action shows the drift warning and/or resolves `failed` on execution per D7.

### Suggested team structure

Default four-role. **Lead** (delegate mode, closeout) + **backend dev** (model, migration, endpoints, execution engine, tests — the bulk) + **frontend dev** (opt-in toggle, pending-actions list, inline ratify UI, initiate-flow changes) + **QA** (prod lifecycle verification). The backend is the heavy half here; if pass-sizing allows, a second backend dev can split the execution-engine + expiry-worker cluster from the model + endpoints cluster.

### Sequence

1. **B1 + B2** first: migration (new tables) + models.
2. **B3** (the action registry + execution engine) + **B4** (submit/approve/decline endpoints) after models land.
3. **B5** (expiry handling) + **B6** (notification + audit wiring) in parallel with B4.
4. **F1 + F2 + F3** (opt-in setting, pending-actions list, inline ratify + initiate-flow interception) after the endpoints stabilize.
5. **B7** test file throughout; gate runs; QA prod lifecycle; merge.

### Load-bearing decisions (full list in Locked decisions below)

- **Opt-in, off by default, per-org via `Organization.settings` JSON** — mirrors the established feature-flag pattern (`public_delegates.enabled`, `write_ins.allowed_mode`). Zero behavior change for any org that doesn't opt in.
- **Wrap a defined, finite set of destructive actions** — not an open-ended "any admin action." v1 set: remove member, delete topic, change/assign permission matrix, delete organization. Each is a registered action type with a typed payload and a single execution function.
- **`PendingAdminAction` carries action_type + JSON payload + initiator + status + threshold + expiry**; approvals live in a child `PendingActionApproval` table (one row per approver decision) so the approve/decline audit trail is first-class, not a JSON blob.
- **"Eligible approver" = a user who holds the permission the wrapped action requires, in that org** — reuse `role_permissions.has_permission`; don't invent a parallel approver concept. The ratification quorum is drawn from exactly the people who could have done the action alone before.
- **Execution re-checks permission + payload validity at execution time**, not just at submit time — state can change while an action sits pending (the member may have already left; the initiator may have lost the permission).
- **Threshold is configurable per action type**, defaulting such that the *current* single-admin behavior is the floor — see D3.

### Operational watch-outs

- **The execution engine is the load-bearing core.** Each wrapped action needs its existing handler logic refactored so it can be invoked two ways: directly (when approval is off) and from the ratification executor (when threshold is met). Factor the actual mutation into a callable the endpoint and the executor both use — do NOT duplicate the deletion/removal logic. This refactor is the riskiest part; keep the direct path behaviorally identical to today.
- **Re-validation at execution time is mandatory.** A pending "remove member" that executes a week later must re-check: does the initiator still hold `member.remove`? Does the target still exist / is still a member? If re-validation fails, the action resolves as `failed` (not executed), with an audit entry and an initiator notification — never silently half-execute.
- **`org.delete` is currently Steward-only (hardcoded `require_org_owner`), not permission-gated.** Wrapping it in ratification needs care: the "eligible approver" set for org-delete is the steward(s)/owner, not the general admin permission holders. Handle org-delete's approver set explicitly rather than routing it through the generic permission-holder query.
- **Don't let ratification deadlock an org.** If the eligible-approver set is smaller than the threshold (e.g. threshold 2-of-N but only 1 admin exists), the action must fall back to immediate execution (or be blocked from entering the queue) rather than becoming un-ratifiable. Decide and implement this guard explicitly — see D6.
- **Expiry needs a worker tick, not just a lazy check.** A pending action should expire on schedule even if no one views the queue. Ride the existing `digest_scheduler.run_one_tick` periodic-task pattern (same place demo-reset, halfway-deadline, snapshot workers live) rather than a new scheduler. Lazy "expire on read" as a belt-and-suspenders is fine, but the worker is the source of truth.
- **Notification event types are new** — add them to `notification_events.py` registry: pending-action-submitted (to approvers), pending-action-decided (to initiator on approve-threshold/decline), pending-action-executed, pending-action-expired/failed. Wire via `notification_emit.emit_notification` wrapped in try/except per existing convention.
- **Audit at every transition** via `audit_utils.log_audit_event`: submitted, each approval/decline, executed, declined, expired, failed.
- **Frontend: the initiate flow changes shape when approval is on.** A destructive button that today fires the action + confirm modal must, when the org has approval enabled and the action is wrapped, instead submit a pending action and show "submitted for approval" rather than "done." `useHasPermission` still gates who can *initiate*; a separate check gates who sees the *ratification queue* (same permission set, different surface).

### Closeout reporting

Per CLAUDE.md closeout shape: per-cluster status, backend test count delta, PG smoke result with the confirmed prior revision, browser verification of each QA scenario, files added/modified, branch + commit SHAs, prod deploy status (URL + bundle hash + sanity), any new tech debt, and explicit confirmation that **with the feature off, all wrapped actions behave exactly as before** (the regression guarantee).

---

## Spec body

### Status block

Destructive admin actions (remove member, delete topic, edit permission matrix, delete org) are single-admin immediate calls today, gated by `role_permissions.has_permission` (or hardcoded Steward-only for org-delete). There is no ratification, no pending queue, no multi-party approval. This pass adds an opt-in N-of-M ratification layer over a defined set of those actions, leaving default behavior untouched and laying the `PendingAdminAction` foundation the future elected-leadership layer requires.

### Locked decisions

- **D1 — Opt-in, per-org, off by default.** Stored under `Organization.settings` as `multi_admin_approval` (an object: `{ "enabled": false, "thresholds": { "<action_type>": N, ... }, "window_hours": <int> }`). Read at the decision point with the established settings-read pattern. No org changes behavior until a steward enables it.
- **D2 — Wrapped action set (v1, finite).** `member.remove`, `topic.delete`, `role_permissions.edit` (permission-matrix change), `org.delete`. These four only. Other destructive actions (proposal.delete, sub_org.delete, etc.) are explicitly out of v1 scope and can be added later by registering them in the action registry — the architecture is extensible, the v1 *set* is small on purpose.
- **D3 — Threshold model + default.** Per-action-type threshold N (total approvals required to execute), configurable in the opt-in settings. Default when an org enables the feature without customizing: **2** for `org.delete` and `role_permissions.edit` (the highest-stakes), **2** for `member.remove` and `topic.delete` as well, but see D6 fallback. Rationale: the whole point is ≥2-party ratification; an org that wants 1-of-N for a given action is effectively not ratifying it, which is the default-off state. Orgs can raise thresholds; lowering to 1 is allowed but surfaced as "this action will not require ratification."
- **D4 — Self-approval: the initiator's submission counts as their own approval.** Submitting is an implicit approval; a 2-of-N action therefore needs ONE other approver. This matches intuition (you obviously approve of the action you initiated) and keeps the common board case (steward proposes, one other ratifies) to a single extra click. The initiator may not approve a second time. (If a future org wants "initiator does not count," that's a configurable refinement, not v1.)
- **D5 — Eligible approver set = holders of the wrapped action's required permission in that org**, resolved via `role_permissions.has_permission`. Exception: `org.delete`'s approver set is the steward/owner set (it's owner-gated, not permission-gated) — handle explicitly. The queue and ratify UI are visible only to this set.
- **D6 — Deadlock guard.** If, at submit time, the eligible-approver set size is LESS than the configured threshold, the action does not enter the queue as un-ratifiable. Instead: if the initiator is the only eligible approver, the action executes immediately (there is no one else to ratify — ratification is vacuous), with an audit entry noting "executed without ratification: insufficient approvers." This prevents a single-admin org from locking itself out of its own destructive actions while still defaulting to ratification whenever a quorum is actually possible.
- **D7 — Execution re-validates.** At threshold-met execution, re-check (a) the initiator still holds the required permission, (b) the target still exists and is in a valid state for the action. On failure, resolve status `failed`, write audit, notify initiator; never partially execute.
- **D8 — Expiry.** Default window 72 hours (`window_hours: 72`), configurable. Expiry is enforced by a periodic task in `digest_scheduler.run_one_tick`; lazy expire-on-read is a secondary guard. Expired actions resolve status `expired`, do not execute, and notify the initiator.
- **D9 — Status enum.** `PendingAdminAction.status`: `pending` → one of `executed` | `declined` | `expired` | `failed`. A decline by any single eligible approver resolves the whole action as `declined` (one veto blocks — appropriate for destructive actions; an org wanting "majority can override a decline" is a future refinement). Document this veto semantics in the UI.
- **D10 — Foundation framing.** The `PendingAdminAction` + `PendingActionApproval` tables and the submit→ratify→execute engine are designed to be reusable by the future elected-leadership layer (where "elect a steward" becomes another action type with its own approver set = the electorate). Keep the action registry and approver-set resolution generic enough that a future action type can plug in, but do NOT build any election logic in this pass.
- **D11 — Approvers must see WHAT they're ratifying, not just that something is pending. Two requirements:**
  - **(a) Discovery — three layers so a pending action can't be missed.** (1) Push at submit: the in-app notification fan-out to every eligible approver (B6) + optional email/digest per existing prefs. (2) A persistent **count badge** on the Admin entry / pending-actions link, visible whenever an approver is in the admin area. (3) **In-context banners** on the surface where the action originates — the Members page shows "N member removal(s) awaiting your approval," the permissions page shows pending matrix changes, etc. — linking to the ratify view. The standalone pending-actions queue (F2) is the canonical full list; the badge + banners are the can't-miss-it surfacing.
  - **(b) Change preview — each action type renders a human-readable preview of the actual change, not just its type.** `member.remove` → "Remove **{name}** ({membership context})" + initiator's reason. `topic.delete` → "Delete topic **{name}**" + impact count (e.g. proposals tagged with it). `org.delete` → prominent destructive warning. **`role_permissions.edit` → a per-role DIFF showing only changed permission cells as before→after** (e.g. "Moderator: + topic.delete, − member.remove"), using the human labels from `permission_registry` — NOT a dump of the full 26-key matrix. **Data-model consequence:** the `role_permissions.edit` payload must capture a **baseline snapshot of the matrix at submit time** alongside the proposed new state, so the preview can render before→after AND detect drift ("permissions changed since this was proposed — re-review"). This baseline ties directly to D7: if the live matrix no longer matches the captured baseline at execution time, the action resolves `failed` rather than applying a stale diff.

### Clusters

**Cluster B — Backend**

- **B1 — Migration.** `down_revision = "4b0bf8f1761f"` (confirmed current head). New `pending_admin_actions` table (`id`, `org_id` FK, `action_type` str, `payload` JSON, `initiator_id` FK, `status` str default `pending`, `threshold` int, `expires_at` datetime, `created_at`, `resolved_at` nullable, `resolution_detail` JSON nullable) + `pending_action_approvals` table (`id`, `pending_action_id` FK, `approver_id` FK, `decision` str [`approve`|`decline`], `reason` text nullable, `created_at`). Reversible `down()`.
- **B2 — Models** in `models.py` mirroring the `DelegateProfile` org-scoped + status + JSON conventions. Relationship from action → approvals. **Payload shape per action type matters (D11b):** `member.remove` payload = target user id + reason; `topic.delete` = topic id; `org.delete` = org id (confirmation); `role_permissions.edit` = **both** the proposed new grants **and** a baseline snapshot of the current grants captured at submit time (needed for the before→after diff preview and for D7 drift detection).
- **B3 — Action registry + execution engine.** A registry mapping each wrapped `action_type` to: the required-permission key (for approver-set resolution), an approver-set resolver, a payload validator, a single execution callable, **and a preview builder** (D11b) that returns the structured human-readable change description the frontend renders. **Refactor each wrapped action's existing mutation logic into a shared callable** invoked by both the direct endpoint (approval off) and the executor (approval on). This is the core; keep the direct path identical to today's behavior. The `role_permissions.edit` preview builder diffs proposed-vs-current and flags baseline drift; reuse `permission_registry` for human labels so the vocabulary matches the existing permissions-page UI.
- **B4 — Endpoints.** `POST /{org_slug}/admin/pending-actions` (submit — but in practice the existing destructive endpoints route here when approval is on; see F3), `GET /{org_slug}/admin/pending-actions` (list, approver-gated — each item includes its rendered change-preview from the B3 preview builder, plus a per-action-type count so the frontend can drive badges/banners without a second call), `GET /{org_slug}/admin/pending-actions/{id}` (single, full preview incl. the permission diff + any drift flag), `POST /{org_slug}/admin/pending-actions/{id}/approve`, `POST /{org_slug}/admin/pending-actions/{id}/decline` (with reason). Approve triggers threshold check → execute when met.
- **B5 — Expiry worker.** Periodic task in `digest_scheduler.run_one_tick` that resolves expired pending actions. Cheap short-circuit when none are due.
- **B6 — Notification + audit wiring.** New event types in `notification_events.py`; emit on submit (→approvers), decided (→initiator), executed, declined, expired, failed. Audit every transition.
- **B7 — Tests** (`test_phase_44_*.py`): side-effect assertions per the verification matrix, the migration cycle test, the deadlock-guard (D6), re-validation-failure (D7), expiry (D8), veto-decline (D9), and the **feature-off regression** (wrapped actions behave exactly as today).

**Cluster F — Frontend**

- **F1 — Opt-in setting** in `OrgSettings.jsx`: enable toggle + per-action threshold inputs + window-hours, gated on `org.edit_settings`. Mirror the existing settings-block pattern.
- **F2 — Pending-actions surface + change preview (D11b):** a list (under Admin) of this org's pending actions, each showing the **rendered change preview** (not just the action type), initiator, current approvals/threshold, expiry countdown, and approve/decline controls inline. For `role_permissions.edit`, render the **per-role before→after diff** of only the changed cells, with the drift warning if the baseline no longer matches. A single-action detail view shows the full preview. Visible only to the eligible-approver set.
- **F2b — Discovery surfacing (D11a):** a **count badge** on the Admin nav entry / pending-actions link (driven by the count the list endpoint returns), and **in-context banners** on the originating admin surfaces — Members page, Topics page, RolePermissions page, OrgSettings — reading e.g. "N change(s) awaiting your approval" and linking to the ratify view. Banners + badge only show for the eligible-approver set.
- **F3 — Initiate-flow interception.** When approval is on and the action is wrapped, the existing destructive buttons (Members remove, Topics delete, RolePermissions save, OrgSettings delete-org) submit a pending action and show "submitted for approval — N approvals needed" instead of executing + "done." When approval is off, behavior is unchanged. **For the permissions page specifically:** "Save" while approval is on captures the proposed matrix + baseline snapshot and submits a pending action rather than writing the matrix directly.

### What this pass IS

An opt-in, per-org, N-of-M ratification queue over four destructive admin actions (remove member, delete topic, edit permissions, delete org), with configurable thresholds + expiry, notification fan-out, full audit trail, deadlock + re-validation guards, and a generic action-registry foundation reusable by the future elected-leadership layer.

### What this pass is NOT

- **The elected-leadership layer.** No elections, terms, recall, or bootstrap logic. That's a separate arc gated on its own design conversation. This pass only lays the ratification foundation.
- **Ratification for non-destructive actions.** Only the four D2 actions. No approval queues for proposal creation, voting, routine edits.
- **Cross-org approval** or approvals spanning sub-org boundaries beyond how the wrapped action already scopes.
- **Configurable veto/override semantics beyond D9** (one decline blocks; majority-override is a future refinement).
- **"Initiator doesn't count" mode** (D4 self-approval is fixed for v1).
- **Time-locks on already-ratified actions** (execute immediately on threshold; no cooling-off).

### Operational notes

- Default-off means the entire feature is invisible until a steward opts in — the regression surface is small but the regression *guarantee* (feature off ⇒ identical to today) must be explicitly tested and stated in the closeout.
- The execution-engine refactor (B3) is where behavioral regressions could sneak in; keep the direct path a thin wrapper over the same shared callable the executor uses.
- The `org.delete` approver-set special-case (D5) is the most likely place for a bug — call it out in code review.

### Followups

- Roadmap: mark Multi-Admin Approval as shipped; promote "Elected Admins/Stewards via the Voting System" from research bucket toward active queue, noting its foundation now exists and it needs the dedicated design conversation (term lengths, recall, bootstrap, failure modes, eligibility) before specing.
- Refresh the roadmap's stale active queue (Templates + Onboarding both effectively closed/dropped; this arc is the new top).
- If real orgs adopt this, watch for requests that drive the deferred refinements: majority-override of declines, initiator-doesn't-count mode, additional wrapped action types, time-locks.
