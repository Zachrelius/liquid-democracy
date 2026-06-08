# Phase 62 — Full Draft Proposal Editing + Color Picker Re-fix + Org-Limit Bump (documented) + Demo-Org Cleanup Run

## Status

Spec drafted 2026-06-08 by the planning agent, grounded against the live repo: `ProposalManagement.jsx` (the full `CreateProposalForm` component + `OptionsEditor` + `TopicPickerList`), the org-scoped proposal create/PATCH/DELETE handlers (`routes/organizations.py` + `routes/proposals.py`), the org-creation-limit gate (`create_organization` in `routes/organizations.py`), and the Phase 59 closeout (color-picker + demo-org cleanup status). Not yet dispatched.

Four items, mostly independent. Cluster A (full draft editing) is the substantive core and follows directly from Z's walkthrough feedback that Phase 59's draft editing is "no longer totally broken but still incomplete."

## Why this exists

From Z's site walkthrough after Phase 59/60/61 shipped:
1. **Draft editing is incomplete.** Phase 59 made draft editing reachable and added type-change + delete + title/description editing, but a draft proposal can't be edited for the *full* field set available at creation: topics, ID-verification floor, thresholds, durations, deliberation-engagement, and stable-result settings. Z wants draft editing to expose the complete creation-time field set, ideally by reusing/cloning the creation screen, entered directly on clicking into a draft the user can edit (an edit button is acceptable too).
2. **Color picker still auto-closes** on any click — the Phase 59 conservative `onMouseDown preventDefault` fix did not resolve it.
3. **Org-creation limit** for Z's account (`@ZacharyPetertam`) needs bumping from 3 to 10 (the limit was left at 3 to test the gate; Z has hit it). Z wants the *procedure documented* so similar requests don't require investigation each time.
4. **Demo Organization cleanup** (Phase 59 Cluster E) shipped a script but it was never run against prod — the orphan org is still there.

## Grounding notes (verified against current code)

### Item 1 — draft editing (the reuse path is clean)
- `CreateProposalForm` in `frontend/src/pages/admin/ProposalManagement.jsx` is a single self-contained component holding the COMPLETE field set Z wants: voting method (binary/approval/ranked_choice), `OptionsEditor`, num_winners, `TopicPickerList` (with Phase 56 category grouping + guidance hint), per-proposal verification floor + jurisdiction, pass/quorum thresholds (permission-gated), deliberation/voting durations (permission-gated), stable-result-required toggle, and the Phase 32.2 deliberation-engagement toggles (write-ins, pre-voting, vote visibility, edit lockout). It takes props `{slug, orgSettings, topics, subOrgs, onCreated, onCancel}` and POSTs to `/api/orgs/{slug}/proposals`.
- The backend PATCH (`PATCH /api/proposals/{id}`, extended in Phase 59 A4) already accepts `voting_method` + `num_winners` changes (draft-only) plus title/body. Whether it accepts the FULL field set (topics, verification_floor, thresholds, durations, stable_result, the 6 engagement overrides) on PATCH is the **key confirm-at-build** — the create handler (`create_org_proposal`) writes all of them, but the PATCH handler must be checked/extended to accept the same set while status=draft.
- The proposal create handler does substantial server-side validation + normalization (verification floor against `VALID_STATES` + jurisdiction-presence; threshold/duration permission gates via `model_fields_set`; topic scope-compatibility; options reshape). **Draft PATCH must run the same validation** so an edited draft can't bypass what creation enforces. Reuse the existing `_validate_proposal_creation`, `_enforce_threshold_permission`, `_enforce_duration_permission`, `_validate_duration_floors`, and the verification-floor normalization block rather than reimplementing.
- `ProposalDetail.jsx` already has the Phase 59 `isDraft` gating + `DraftActionsPanel` (type-change + delete + the inline title/body editor). Phase 62 extends this into the full-form edit.

### Item 2 — color picker (Phase 59 fix insufficient)
- Phase 59 C1 added `onMouseDown={preventDefault}` on swatches, noting "no React popover exists; auto-close was OS-level focus loss" and flagging it for Z spot-check. Z confirms it still auto-closes on any click. So the root cause is NOT the swatch mousedown — it's whatever dismisses the picker container. **Team must inspect the actual `ColorPicker` component in `Topics.jsx` live** (the Phase 56 component) to find the real dismissal trigger (likely an `onBlur` on the container, a document click-outside listener that's misfiring on inside clicks, or the native `<input type=color>` stealing focus and collapsing a custom dropdown). This needs interactive debugging, not a source guess — the Phase 59 source-only fix is exactly why it didn't land.

### Item 3 — org-creation limit (fully grounded; procedure below)
- The limit is `User.org_creation_limit` (nullable INT). In `create_organization` (Gate 3): `effective_limit = current_user.org_creation_limit if not None else DEFAULT_PER_USER_ORG_LIMIT` (=3). The count is steward-role memberships (owned orgs). So bumping Z to 10 = set `User.org_creation_limit = 10` on Z's row.
- There is **no admin API endpoint** to set this today (it's a raw column). So the change is either a one-off DB update (code-team-run) or — better, per Z's "serviceable without investigation" ask — a small documented script + a written runbook. See Cluster C.

### Item 4 — demo-org cleanup (script exists, never run)
- `backend/scripts/phase59_remove_orphaned_demo_org.py` (dry-run default; `--confirm` deletes; idempotent; refuses on bible markers; writes `org.deleted` audit). Per the Phase 59 closeout it was routed to Z for go-ahead and not run. Z now says remove it this pass.

## Clusters

### Cluster A — Full draft proposal editing (the substantive core)

**A1 — Refactor `CreateProposalForm` into a create-or-edit form.**
Generalize the existing component (rename to `ProposalForm` or keep `CreateProposalForm` with an `editingProposal` prop — team's call) to support both modes:
- **Create mode (today's behavior):** unchanged — no `editingProposal`, POSTs to `/api/orgs/{slug}/proposals`, button reads "Create Proposal".
- **Edit mode (new):** accepts an `editingProposal` object, prefills ALL form state from it (title, body, voting_method, options, num_winners, selected topics + relevances, verification_floor + jurisdiction, thresholds, durations, stable_result_required, the 6 engagement overrides), PATCHes to the draft-edit endpoint, button reads "Save Changes". Cancel returns to the proposal view.
- Prefill is the careful part: map the proposal's persisted fields back onto the form's state shape. Options come back as `ProposalOption` rows → map to `{label, description}`. Selected topics come from the proposal's `ProposalTopic` rows → map to `{topic_id, relevance}`. Verification floor/jurisdiction, thresholds, durations, engagement overrides map directly. Where a proposal has NULL (inherit-from-org) for an override, prefill from the org default exactly as create mode does (so "inherit" stays "inherit" unless the user changes it).
- Keep the existing permission gates (threshold/duration inputs still gated on `proposal.set_thresholds` / `proposal.set_durations`).

**A2 — Backend: full-field draft PATCH.**
Confirm + extend the draft-edit PATCH (`PATCH /api/proposals/{id}` or the org-scoped equivalent — confirm which the FE should call) to accept the full creation field set WHILE status=draft only:
- title, body, voting_method (+ options reshape, already in Phase 59 A4), num_winners, topics (replace the `ProposalTopic` set), verification_floor + jurisdiction, pass/quorum thresholds, deliberation/voting durations, stable_result_required, and the 6 engagement overrides (allow_write_in_options, allow_write_ins_during_voting, max_write_ins, allow_pre_voting, show_votes_during_deliberation, edit_lockout_fraction).
- **Reuse the create-path validation** (the confirm-at-build): `_validate_proposal_creation`, the verification-floor normalization block (VALID_STATES + jurisdiction-presence + email_only→NULL), `_enforce_threshold_permission`, `_enforce_duration_permission`, `_validate_duration_floors`, and the topic scope-compatibility checks. A draft edit must not be a validation backdoor.
- **Status guard (load-bearing):** the full-field edit is `draft`-only. Editing title/body during deliberation stays as Phase 32.2 left it (with the revision-snapshot trail); this pass does NOT widen deliberation-phase editing. Assert: a full-field PATCH on a non-draft proposal is rejected (400/403) for the fields that are draft-only.
- Topics-replace semantics: editing replaces the proposal's topic set wholesale (delete existing `ProposalTopic` rows, insert the new set) — matching the form's full-replacement shape. Within a transaction.

**A3 — Entry point: click-into-draft enters edit (Z's lean).**
Per Z: clicking into a draft proposal the user has edit rights for should go straight to the full edit form (an edit button is an acceptable fallback). Implement in `ProposalDetail.jsx`:
- When the proposal is `draft` AND the viewer has `org.edit_proposal` (or is the author), render the full `ProposalForm` in edit mode as the primary view (or auto-open it), rather than the read view + a separate small editor.
- Keep a way back to the read view (cancel). The Phase 59 `DraftActionsPanel` (delete + the simpler controls) folds into or sits alongside the full form — team's call, but avoid two competing edit affordances. Prefer: the full form IS the draft view for editors; delete lives as a button on it.
- Non-editors viewing a draft (rare — drafts are mostly author/admin visible) keep the read view.

**A4 — Tests (Cluster A).**
- Edit-mode prefill: a draft with options + topics + a verification floor + custom thresholds/durations + engagement overrides round-trips into the form and back out via PATCH with all fields persisted (backend side-effect asserts on each field group).
- Full-field PATCH persists each field group on a draft (topics replaced, verification floor set/normalized, thresholds/durations within permission, engagement overrides, stable_result).
- **Draft-only guard:** full-field PATCH rejected on deliberation/voting/passed status (the load-bearing assert) — only the Phase 32.2 deliberation title/body edit remains allowed where it already was.
- Validation reuse: an invalid verification floor / jurisdiction-presence mismatch / over-floor threshold without permission is rejected on PATCH exactly as on create.
- Type-change during edit still discards options with confirm (Phase 59 A4 behavior preserved through the refactor).
- Permission gating: a user without `proposal.set_thresholds` editing a draft can't change thresholds (inputs hidden + backend ignores/rejects), same as create.

### Cluster B — Color picker real fix

**B1 — Interactively debug + fix the auto-close.**
Inspect the live `ColorPicker` in `Topics.jsx`. Find the actual dismissal trigger (onBlur / click-outside listener / native-input focus steal). Fix so the picker stays open while the user interacts with swatches AND can drag the native color slider, closing only on an explicit done/close or a genuine click-outside. Browser-verify the multi-tweak + drag flow (the Phase 59 PASS-by-source approach is what missed it — this one needs live verification).

### Cluster C — Org-creation-limit bump + documented runbook (Z-serviceable)

**C1 — Bump Z's limit to 10.**
Set `User.org_creation_limit = 10` for the user `@ZacharyPetertam` (resolve by username/email to the user row). This is a prod DB write → **code-team-run**, not Z-run, and not via the ad-hoc `.tmp_diag/bump_z_org_creation_limit.py` script (which hit permissions and is unreviewed). Use a small, reviewed, idempotent script `backend/scripts/set_org_creation_limit.py --user <username_or_email> --limit <N>` that:
- Resolves the user, prints current limit, sets the new limit, writes an audit row (`user.org_creation_limit_changed` with old/new + actor), dry-run by default + `--confirm` to apply (mirroring the Phase 59 cleanup-script safety pattern).
- Is reusable for any future limit change (not hardcoded to Z).

**C2 — Document the procedure (the durable ask).**
Add a short runbook entry — `docs/runbooks/adjust_org_creation_limit.md` — covering: where the limit lives (`User.org_creation_limit`, NULL→default 3 via `DEFAULT_PER_USER_ORG_LIMIT`), how the gate counts owned orgs (steward memberships), the exact command to run the C1 script (dry-run then `--confirm`), and that it's a code-team operation (prod DB write). This is what makes future requests serviceable without re-investigation.
- **Optional (flag for Z, do NOT build unless Z says so):** a proper platform-admin API endpoint + UI to set a user's org-creation limit would remove the need for a script entirely. That's a bigger surface (admin auth, audit, a settings screen). The runbook + script is the right-sized answer for now; the endpoint is a future enhancement if limit-adjustment becomes frequent. Note it in the runbook as a possible future improvement.

### Cluster D — Run the Phase 59 demo-org cleanup

**D1 — Execute the existing cleanup script against prod.**
Run `backend/scripts/phase59_remove_orphaned_demo_org.py` — dry-run first, confirm the target is the orphaned `slug=demo` org (not a bible org), then `--confirm`. Code-team-run (prod DB write). Verify post-run: the `slug=demo` org is gone, `/api/orgs/explore` + admin org lists no longer surface it, `/demo` route still works, and a demo reset (`run_demo_reset_if_due`) doesn't recreate it. This is the deferred Phase 59 Cluster E action, now authorized by Z.

## Operational notes

- **Branch:** `phase-62/draft-edit-complete-and-fixes`.
- **No migration.** Cluster A reuses existing columns; B is frontend; C/D are scripts. No `start.sh` / migration surface.
- **Cluster A is the priority + most substantive.** The backend full-field PATCH (A2) is the load-bearing piece — it must reuse create-path validation, not reimplement, and the draft-only status guard is the safety invariant (assert it).
- **Cluster C/D are code-team-run prod DB operations** — per the "don't ask Z to run scripts" rule, the team runs them. Z's role is the go-ahead (given for both: limit bump + demo-org removal).
- **Cluster B needs live debugging** — the Phase 59 source-only fix is precisely why it didn't work; don't repeat that. Browser-verify.
- **Confirm-at-build:** whether the draft-edit PATCH endpoint is `/api/proposals/{id}` or org-scoped, and exactly which fields it currently accepts post-Phase-59 (A2 extends it to the full set); the live ColorPicker dismissal trigger (B1); the `@ZacharyPetertam` user row resolution (C1).
- **Planning agent does NOT write PROGRESS.md.** Closeout writes the Phase 62 entry.

## What this pass is NOT

- Not widening deliberation-phase proposal editing — Cluster A's full-field edit is `draft`-only; deliberation editing stays as Phase 32.2 left it (title/body with revision snapshots).
- Not building the platform-admin org-limit API/UI (C2 flags it as a future option; the runbook + script is this pass's answer).
- Not touching the access model, verification gate, or the test suite.
- Not the just-for-fun org content (with a fresh agent).

## Suggested team structure

- Lead in delegate mode; continuing-dev team (rides on Phase 32.2/56/59 context).
- One dev on Cluster A (the meaty refactor + backend PATCH + tests) end-to-end.
- A second dev (or the same in series) on B (interactive color-picker debugging), C (limit script + runbook), D (run the cleanup) — all small.

## Closeout report back

- **A:** the form refactor (create-or-edit); the full-field draft PATCH with create-path validation reused (list which validators); the draft-only status guard asserted; click-into-draft entering edit mode; prefill round-trip verified for each field group; type-change-discard preserved.
- **B:** the ACTUAL root cause of the color-picker auto-close (not the Phase 59 guess); the fix; browser-verified multi-tweak + slider drag.
- **C:** Z's limit set to 10 (old→new, audit row written); the runbook doc added; the reusable script.
- **D:** the orphan `slug=demo` org removed (dry-run output + confirm); verified gone from explore/admin lists; `/demo` route intact; demo reset doesn't recreate it.
- Test count delta; browser verification; any new tech debt.

## Go.
