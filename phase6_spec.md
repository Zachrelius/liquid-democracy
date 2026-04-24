# Phase 6 — Multi-Option Voting Pass A: Approval Voting

**Type:** Feature pass. New capability.
**Dependencies:** Phase 5.5 complete (current `master`, 101 backend tests passing).
**Goal:** Ship the full multi-option voting scaffolding — data model, delegation engine branching, proposal-type-aware frontend, org config — with **approval voting** as the only multi-option method initially supported. Binary voting continues to work unchanged. RCV and STV are deliberately out of scope; they ship in Phase 7 on top of the scaffolding built here.

---

## Context and Rationale

The platform currently only supports binary (yes/no/abstain) votes. Civic orgs need more than that: electing officers from a slate, picking event dates, choosing names, selecting among several policy options. Multi-option voting closes that gap.

**Why approval first, not RCV:** Approval tabulation is trivial (count approvals per option). If something breaks during internal testing of this pass, we know the bug is in the scaffolding — ballot storage, delegation branching, proposal-type-aware frontend — not in a counting algorithm. Debugging a broken RCV implementation where you can't tell whether the bug is in ballot storage, delegation, or tabulation is painful. De-risk the scaffolding first. Phase 7 will add RCV and STV on top of a validated foundation.

**What "the scaffolding" means:** Every piece of infrastructure that will also be needed for RCV/STV must ship in this pass. That includes: the `voting_method` enum defined with all three values (binary, approval, ranked_choice) even though only two ship; the `ProposalOption` table; the `Vote.ballot` JSON column; the options editor in the proposal creation form (even though approval doesn't need reordering, RCV's drag-to-rank will reuse the same editor); method-aware ballot UI dispatching; method-aware results display; org-level `allowed_voting_methods` config.

**What is explicitly out of scope this pass:** RCV, IRV, STV, plurality, STAR, score, Condorcet, multi-winner approval, ballot amendments during the voting window, non-strict-precedence delegation strategies applied to multi-option proposals, sustained-majority interaction with multi-option (all of those belong to Phase 7, 8, or later).

---

## Design Decisions Made Before Dispatch

These are decisions the planning agent and Z resolved. They are not open for re-litigation by the dev team; if there's a strong reason a decision won't work in practice, flag it back to planning rather than changing it unilaterally.

### Decision 1: Zero-approvals submit requires an explicit confirmation

Approval voting has no explicit "abstain" button. A user who submits a ballot with zero options checked has technically abstained — but they might also have misclicked, or thought they'd selected something they hadn't. To prevent silent accidents while still allowing intentional abstention:

- When the user clicks submit on an approval ballot with zero approvals, fire a `ConfirmDialog` (the one built in Phase 5) with wording roughly like: **"You haven't approved any options. Submitting now counts as an abstention — you're saying you don't support any of them. This is different from not voting at all. Continue?"**
- Cancel returns them to the ballot unchanged.
- Confirm submits the ballot with `{"approvals": []}` — explicit empty array.
- Distinguish from "didn't vote at all" (no Vote record) and from "voted yes/no/abstain on binary" (uses existing `vote_value` column).

A delegator whose delegate submitted `{"approvals": []}` inherits the empty approval set. This is a deliberate stance by the delegate; chain behavior does not kick in.

### Decision 2: Ties surface to the org admin; no algorithmic auto-resolution at launch

When two or more options tie for the most approvals:
- The backend tabulation returns a list of winners, not a single winner. Length > 1 means tie.
- The frontend results display shows "Tied result — N options received M approvals each" with all tied options highlighted.
- A new admin action, **"Resolve tie,"** is available to org admins when a proposal is in `passed` status with a tied result. The admin picks one of the tied options as the selected winner, and the proposal records which option was selected and who resolved the tie. This is logged to the audit trail.
- A proposal with an unresolved tie remains in `passed` status with `tied=true` in the results payload. No auto-resolution.

This is a deliberate minimum-viable tie mechanism. Long-term, ties should be resolved by a method declared up-front at org setup (options being considered for future work: deterministic arbitrary tiebreaker, early-voting preference, broader-approval-base, multi-winner acceptance for proposals that allow it). The "declare the tie method at org setup" direction is captured as deferred work in the roadmap — not built in this pass.

Out of scope for this pass: admin re-voting the tied options as a follow-up mini-proposal, user-facing tie voting rounds, algorithmic tiebreakers beyond "admin picks."

### Decision 3: The `voting_method` enum is defined with all three values now

Define `voting_method` as `Enum("binary", "approval", "ranked_choice")` in Phase 6 even though only `binary` and `approval` are accepted by proposal creation. This avoids a follow-up migration in Phase 7 when RCV ships. Proposal creation should reject `ranked_choice` with a clear error message ("Ranked-choice voting is planned for a future release") until Phase 7 enables it.

### Decision 4: `Vote.ballot` is new JSON column; `vote_value` stays for binary

Binary votes continue to use the existing `vote_value` enum column. Approval votes store `{"approvals": [option_id, option_id, ...]}` in a new `ballot` JSON column. This avoids data migration of existing binary votes and keeps the two paths clearly separated in code. A vote record has either `vote_value` populated (binary) or `ballot` populated (multi-option), never both. Enforce this in the schema via validation, not DB constraint (SQLite can't easily express "exactly one of").

### Decision 5: Delegation for approval uses strict-precedence only; inherit full approval set

Delegators inherit their delegate's full approval set. The mental model is the same as binary: "my delegate's vote becomes my vote." Chain behavior (`accept_sub` / `revert_direct` / `abstain`) only kicks in when the delegate submitted no ballot at all. An empty-approvals ballot (`{"approvals": []}`) is a submitted ballot and inherits as-is.

Delegation strategies beyond strict-precedence (`majority_of_delegates`, `weighted_majority`) remain binary-only for now. If a user has a non-strict-precedence strategy configured and delegates on a multi-option proposal, the system falls back to strict-precedence for that proposal with a UI note explaining why. The explanation is user-facing: "This proposal uses approval voting, which currently supports only strict-precedence delegation. Your delegate was selected based on your highest-priority matching topic." Don't silently change their strategy.

---

## Scope

### Backend: Data Model

**New enum value on `Proposal.voting_method`:**

```python
voting_method: Mapped[str] = mapped_column(
    Enum("binary", "approval", "ranked_choice", name="voting_method"),
    nullable=False,
    default="binary",
)
```

Existing proposals get `voting_method="binary"` via migration backfill.

**New column `Proposal.num_winners`** (integer, default 1). Unused for binary and approval in this pass; reserved for RCV/STV in Phase 7. Include it now to avoid a second migration.

**New column `Proposal.tie_resolution`** (JSON, nullable). Populated only when a tie is resolved. Shape: `{"resolved_by": user_id, "resolved_at": timestamp, "selected_option_id": option_id}`. Null for proposals without ties or with unresolved ties.

**New table `ProposalOption`:**

```python
class ProposalOption(Base):
    __tablename__ = "proposal_options"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    proposal_id: Mapped[str] = mapped_column(
        String, ForeignKey("proposals.id"), nullable=False, index=True
    )
    label: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    display_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)

    proposal: Mapped["Proposal"] = relationship("Proposal", back_populates="options")
```

And on Proposal: `options: Mapped[list["ProposalOption"]] = relationship("ProposalOption", back_populates="proposal", cascade="all, delete-orphan", order_by="ProposalOption.display_order")`.

Binary proposals have zero `ProposalOption` rows. Approval proposals have 2-20 rows (see validation below).

**New column `Vote.ballot`** (JSON, nullable). Shape for approval: `{"approvals": [option_id, option_id, ...]}`. Null for binary votes. Validation rule (enforced in Pydantic schema + endpoint logic): exactly one of `vote_value` or `ballot` is populated.

**New column `Organization.settings.allowed_voting_methods`** (within existing JSON settings blob). Default for new orgs: `["binary", "approval"]`. Migration: existing orgs get this key added with default value.

**Migration:** Single Alembic migration adding all of the above. Tests run against SQLite (current state of tests); the PostgreSQL dual-DB gap remains open tech debt per Phase 5.5 retrospective.

### Backend: Validation

Proposal creation (`POST /api/orgs/{org_slug}/proposals`):

- `voting_method` defaults to `"binary"` if not provided.
- If `voting_method="binary"`: `options` must be absent or empty; `num_winners` ignored.
- If `voting_method="approval"`:
  - `options` must contain between 2 and 20 entries. (Below 2 makes no sense; above 20 is an arbitrary sanity cap that can be revisited.)
  - Each option must have a non-empty `label` (max 200 chars) and optional `description` (max 2000 chars).
  - Option labels within a single proposal must be unique (case-insensitive comparison).
  - `num_winners` must be 1 (reserved for RCV/STV).
- If `voting_method="ranked_choice"`: reject with 400, message "Ranked-choice voting is planned for a future release."
- Org's `allowed_voting_methods` must include the requested method, else reject with 403, message "This organization does not have approval voting enabled. An admin can enable it in org settings."

Proposal editing while in draft (`PATCH ...`):

- `voting_method` cannot be changed after creation. If an author wants a different method, they withdraw and create a new proposal. Enforce this in the endpoint.
- `options` can be added/removed/edited freely while proposal is in `draft` or `deliberation` status.
- Once proposal enters `voting` status: options are locked. Any attempt to edit options returns 409 with "Options cannot be modified after voting begins."

### Backend: Vote Casting

Vote casting (`POST /api/proposals/{proposal_id}/vote`):

- For binary proposals: unchanged from current behavior. Uses `vote_value`.
- For approval proposals: accept `{"approvals": [option_id, ...]}` in the request body. Validate:
  - Each option_id belongs to this proposal.
  - No duplicates in the array.
  - Empty array is allowed (see Decision 1; confirmation is a frontend concern, but the backend accepts empty).
- Store in `Vote.ballot`; `vote_value` stays null.
- Delegation chain metadata (`delegate_chain`, `is_direct`, `cast_by_id`) works identically to binary — this is method-agnostic.

### Backend: Delegation Engine Extension

The pure layer's `ProposalContext` currently holds `direct_votes: dict[user_id, vote_value_str]`. Extend to support ballots:

**Option A (preferred):** Rename to `direct_ballots: dict[user_id, Ballot]` where `Ballot` is a new dataclass with fields `vote_value: Optional[str]` (binary) and `approvals: Optional[list[str]]` (approval). Exactly one populated.

**Option B:** Keep `direct_votes` for binary, add parallel `direct_ballots` for multi-option.

Use Option A unless the dev team finds a concrete reason it's worse — it's cleaner and the binary/multi-option distinction is already carried via `proposal.voting_method`, so a uniform `Ballot` container avoids two parallel code paths.

**`resolve_vote_pure()` extension:** The function currently returns a `VoteResult` with `vote_value`. Change it to return a `BallotResult` (or similar) carrying either `vote_value` (binary) or `approvals` (multi-option). The delegation-following logic (direct vote check → topic precedence → chain behavior) is unchanged in shape — only the payload being propagated is different. An empty approval set inherits as-is; chain behavior fires only when no ballot exists for the delegate.

**`compute_tally_pure()` extension:** Currently returns a `ProposalTally` with `yes / no / abstain / not_cast` counts. For approval proposals, it should return an `ApprovalTally` (new dataclass) with:

```python
@dataclass
class ApprovalTally:
    option_approvals: dict[str, int]   # option_id -> approval count
    total_ballots_cast: int            # how many users submitted a ballot (including empty)
    total_abstain: int                 # how many submitted {"approvals": []}
    not_cast: int
    total_eligible: int
    winners: list[str]                 # option_ids with max approvals; len > 1 means tie
    tied: bool                          # convenience flag; winners has length > 1
```

Existing `ProposalTally` stays for binary. The service layer dispatches on `proposal.voting_method` and returns the appropriate tally type.

### Backend: Results Endpoint

`GET /api/proposals/{proposal_id}/results` returns method-appropriate payload:

- Binary: unchanged.
- Approval: returns the `ApprovalTally` fields plus option labels, and if a tie is resolved, the `tie_resolution` record.

### Backend: Tie Resolution Endpoint

New endpoint: `POST /api/orgs/{org_slug}/proposals/{proposal_id}/resolve-tie`

- Requires `require_org_admin`.
- Body: `{"selected_option_id": "..."}`.
- Validates proposal is `passed` and has a tied result (winners length > 1).
- Validates the selected option is one of the tied winners.
- Writes `Proposal.tie_resolution` JSON with `{resolved_by, resolved_at, selected_option_id}`.
- Logs audit event `proposal.tie_resolved`.
- Returns updated proposal/results.

### Backend: Org Admin Endpoint

Existing `PATCH /api/orgs/{org_slug}` already accepts settings updates. Just confirm `allowed_voting_methods` flows through correctly — no new endpoint needed.

### Frontend: Proposal Creation Form

`frontend/src/pages/admin/ProposalManagement.jsx`:

- Voting method selector (dropdown or radio group): Binary, Approval. (Ranked Choice visible but disabled with "Coming soon" tooltip.)
- If Binary: form behaves as today.
- If Approval: show an options editor below title/body/topics:
  - Each option has a label input (required), description textarea (optional), and a remove button.
  - "Add option" button below the list.
  - Minimum 2 options (submit disabled until met); maximum 20 (add button disabled at 20).
  - Duplicate label detection (case-insensitive) — shown as inline validation error.
  - Display order is the order shown in the form; reorder via up/down arrows or drag handles (keep it simple — don't over-engineer; Phase 7 will need drag for RCV ranking and can reuse).
- Voting method selector is disabled on edit after the proposal is created (can't change method mid-life).

Org admin settings page (`frontend/src/pages/admin/OrgSettings.jsx`):

- New section "Voting Methods" with checkboxes for Binary (always enabled, can't uncheck), Approval. Ranked Choice visible but disabled/coming-soon. Saving updates `org.settings.allowed_voting_methods`.

### Frontend: Ballot UI

`frontend/src/pages/ProposalDetail.jsx`:

- Dispatch on `proposal.voting_method`:
  - Binary: existing Yes/No/Abstain buttons.
  - Approval: render option list with checkboxes. Each option shows label, description, and checkbox. "Submit Ballot" button at bottom.
  - On submit:
    - If any approvals checked: submit directly.
    - If zero checked: fire `ConfirmDialog` per Decision 1. Submit on confirm.
  - After submission, show summary view: "You approved: [option A, option C]" or "You abstained (approved no options)" with a "Change ballot" button that returns to the editing view if proposal is still in voting.

### Frontend: Delegated Ballot Display

When the current user's vote is delegated on an approval proposal, the ProposalDetail vote panel shows:

- "Your vote: via [delegate name]"
- What the delegate approved: "[Delegate] approved [labels]" or "[Delegate] abstained (approved no options)"
- "Override — vote directly" button (unchanged from binary).
- Delegate-chain tooltip/expand works identically to binary.

If the delegate has not yet submitted a ballot, show "[Delegate] has not voted yet" with the same chain behavior logic as binary (revert-direct prompts the user to vote, abstain shows "You will abstain unless you vote directly," accept-sub shows the sub-delegate's ballot).

### Frontend: Results Display

`ProposalDetail.jsx` or a results subcomponent:

- Binary: existing bar chart.
- Approval: horizontal bar chart. One bar per option. Bar length = approval count. Winning option(s) highlighted. Below the chart: total ballots cast, total abstain (empty ballots), participation rate.
- Tied result: banner at top "Tied result — N options received M approvals each." Tied options share the winner highlight color. If current user is admin: "Resolve tie" button opens a modal where admin picks one of the tied options as selected winner. Submit triggers the resolve-tie endpoint.
- Resolved tie: banner shows "Tie resolved by [admin name] on [date]. Selected winner: [option label]."

### Frontend: Public Delegate Profiles

`frontend/src/pages/UserProfile.jsx` voting record:

- Binary proposals unchanged.
- Approval proposals: show compact summary per proposal. "[Proposal title] — approved 2 of 4 options" (non-expanded). Click to expand shows the labels. Empty ballots show "Abstained (approved no options)."

### Frontend: Documentation

New help page at `/help/voting-methods` (route in `App.jsx`, component in `pages/VotingMethodsHelp.jsx` or similar):

- Plain-language explanation of binary voting (one section, short).
- Plain-language explanation of approval voting (one section, longer): what it is, when to use it, the empty-ballot-is-abstention rule, how delegation works for approval.
- Placeholder section: "Ranked-choice voting (coming soon)" with a one-line description.
- Link to this page from the proposal creation form's voting method selector ("Which should I pick?").

Keep it short. This is internal-test-facing first; it'll get polish before pilot recruitment.

### Seed Data

Update `backend/seed_data.py`:

- Add at least one approval-voting proposal to the demo org. Suggested scenario: a "Pick the venue for the next meeting" proposal with 4-5 options, in `voting` status, with various demo users having voted (some empty, some single-option, some multi-option), and at least one delegator inheriting an approval ballot.
- Optionally: one approval proposal in `passed` status with a tied result so the tie-resolution UI has something to exercise without needing to simulate a full voting window.

---

## Testing

### Backend Unit Tests

**New file `tests/test_approval_voting.py`.** Cover the following scenarios as separate test functions, minimum:

**Data model / proposal creation:**
1. Create approval proposal with 3 options — succeeds, options persisted in order.
2. Create approval proposal with 0 options — rejected with 400.
3. Create approval proposal with 1 option — rejected with 400.
4. Create approval proposal with 21 options — rejected with 400.
5. Create approval proposal with duplicate labels (case-insensitive) — rejected with 400.
6. Create approval proposal with `num_winners=2` — rejected with 400 (reserved for STV).
7. Create proposal with `voting_method="ranked_choice"` — rejected with 400 with the "planned for future release" message.
8. Create approval proposal in an org without approval in `allowed_voting_methods` — rejected with 403.
9. Edit proposal options while in `draft` status — succeeds.
10. Edit proposal options while in `voting` status — rejected with 409.
11. Change `voting_method` after creation — rejected.

**Vote casting:**
12. Cast approval ballot with 2 of 4 options — vote record has `ballot={"approvals": [...]}` and `vote_value=null`.
13. Cast approval ballot with empty approvals (`[]`) — accepted, stored as `{"approvals": []}`.
14. Cast approval ballot with option_id not belonging to this proposal — rejected.
15. Cast approval ballot with duplicate option_ids — rejected.
16. Cast binary vote on an approval proposal (wrong payload type) — rejected.
17. Cast approval ballot on a binary proposal — rejected.
18. Retract approval vote — vote record deleted, delegation recomputes.

**Delegation for approval:**
19. Delegator's vote resolves to delegate's approval ballot (identical approvals inherited).
20. Delegator inherits delegate's empty-approvals ballot (abstain-equivalent).
21. Delegate has not voted, delegator's chain behavior is `revert_direct` — delegator's resolved vote is "not_cast."
22. Delegate has not voted, delegator's chain behavior is `accept_sub` and sub-delegate voted — delegator inherits sub-delegate's ballot.
23. Delegate has not voted, chain behavior is `abstain` — delegator's resolved ballot is empty-approvals (abstain-equivalent).
24. User with `delegation_strategy="majority_of_delegates"` delegates on an approval proposal — engine falls back to strict-precedence.

**Tabulation:**
25. Tally approval proposal with 3 options and 10 voters, mixed approval patterns — returns correct per-option counts and single winner.
26. Tally with tied winners — returns winners list of length 2+, `tied=True`.
27. Tally with all empty ballots — returns zero approvals per option, all ballots counted as abstain, winners empty.
28. Tally with zero ballots cast — returns zero approvals per option, winners empty, not_cast equals total_eligible.

**Tie resolution:**
29. Admin resolves a tied proposal — `tie_resolution` populated, audit event logged.
30. Non-admin attempts to resolve tie — rejected with 403.
31. Resolve tie with option_id that isn't among tied winners — rejected with 400.
32. Resolve tie on a non-tied proposal — rejected with 400.
33. Resolve tie on a proposal not in `passed` status — rejected with 400.
34. Resolve already-resolved tie — rejected with 400 (no re-resolution).

**Regression:**
35. All existing binary-voting tests continue to pass without modification.

**Coverage target:** ~30 new tests. Backend test count should go from 101 → approximately 130+.

### Browser Tests — New Suite J in `browser_testing_playbook.md`

Committed to `browser_testing_playbook.md` in the same format as Suite I. Execute with Claude-in-Chrome.

**J1: Create approval proposal (admin).** Login as admin. Navigate to Admin > Proposals. Create proposal with voting method "Approval", 4 options. Confirm proposal appears in list with approval badge.

**J2: Edit options in draft.** Open the draft from J1. Add a 5th option, rename one, save. Confirm changes persist.

**J3: Advance to voting.** Advance J1 proposal through deliberation to voting.

**J4: Cast approval ballot (multi-select).** Login as a member. Open the proposal. Check 2 of 5 options. Submit. Confirm the vote panel shows "You approved: [label A, label B]" and results bar chart updates.

**J5: Cast empty ballot triggers confirm dialog.** As another member, open the proposal. Don't check anything. Click Submit. Confirm the ConfirmDialog appears with the abstention explanation. Click Cancel — ballot still empty, nothing saved. Click Submit again, this time Confirm — ballot saved as abstain.

**J6: Delegated approval ballot inheritance.** As a user who delegates to a member who voted in J4, open the proposal. Confirm vote panel shows "Your vote: via [delegate]" and lists the delegate's approvals.

**J7: Override delegated approval ballot.** From J6, click "Override — vote directly". Cast a different approval pattern. Confirm override took effect.

**J8: Options locked after voting starts.** As admin, attempt to edit options on J1 (now in voting status). Confirm the edit is blocked with an error message.

**J9: Results display with approval counts.** As any user, view the results section of J1. Confirm horizontal bar chart displays per-option approval counts.

**J10: Create tied-result scenario via seed data.** If seed data includes a tied approval proposal (per the seed spec), navigate to it. Confirm the "Tied result" banner appears and shows the tied options highlighted.

**J11: Admin resolves tie.** As admin on the tied proposal, click "Resolve tie." Pick one of the tied options. Confirm the resolution banner replaces the tied banner and shows who resolved and which option was selected.

**J12: Non-admin sees no resolve-tie button.** As a regular member on the tied proposal, confirm "Resolve tie" is not visible.

**J13: Approval voting disabled in org settings.** As admin of a different org (or after disabling approval in the current org), attempt to create an approval proposal. Confirm the voting method selector doesn't offer approval, or if offered, rejects with the "not enabled" message.

**J14: Binary voting unchanged.** Create a binary proposal and cast a yes vote. Confirm flow is unchanged from Suite H regression baseline.

**J15: Regression.** Re-run Suite H tests H1–H13 and Suite I tests I1–I11. All must still pass.

### Explicit non-test items

Do not build tests for:
- RCV or STV paths — they ship in Phase 7.
- Sustained-majority interaction with approval — Phase 8.
- Multi-option behavior with `majority_of_delegates` or `weighted_majority` beyond the fallback test.
- Accessibility of the options editor (Phase-deferred, goes with the overall WCAG audit).

---

## Definition of Done

- All backend scope items implemented with a single Alembic migration.
- All frontend scope items implemented. Every approval-voting flow works end-to-end in the browser.
- Backend tests: at least ~30 new tests added. All tests pass. Target: 130+ passing.
- Suite J added to `browser_testing_playbook.md` and all 15 tests pass.
- Seed data updated to include at least one approval proposal in voting status, and (if feasible) one with a tied result in passed status.
- `PROGRESS.md` updated with a Phase 6 section covering: what was built, key design decisions referenced, backend test count, Suite J results.
- `future_improvements_roadmap.md` updated: Phase 6 marked complete in the sequencing section. Note added that Phase 7 will build RCV/STV on the scaffolding from this pass.
- **Toast success audit (carried from Phase 5 deferred item):** audit the frontend for success paths that close a form without firing `toast.success()`. Make toast behavior consistent across all form submissions. This is a small cleanup that belongs in this pass because Phase 6 introduces new success paths (approval ballot submission, tie resolution, option edits); it's cleaner to standardize now than to add more inconsistency and do a separate pass later.
- No regressions in existing binary voting, delegation, or admin workflows.

---

## Out of Scope

Deferred to Phase 7:
- Ranked-choice voting (IRV)
- Single Transferable Vote (STV)
- `num_winners > 1`
- Drag-to-rank ballot UI
- `pyrankvote` integration
- Round-by-round elimination visualization

Deferred to Phase 8:
- Sustained-majority interaction with approval voting (stable-result semantics)
- Any snapshot-based approval tally behavior

Deferred post-sequence:
- Non-strict-precedence delegation strategies applied to multi-option (research area: rank aggregation, proportional approval)
- Org-configurable tie resolution methods declared at org setup
- Algorithmic tiebreakers (broader-approval-base, early-voting preference, deterministic arbitrary)
- Ballot amendments during voting window
- Plurality, STAR, score, Condorcet methods
- Multi-winner approval voting (STV covers the proportional multi-winner case)

If the dev team discovers adjacent issues during execution, log them as new technical debt in `PROGRESS.md` rather than expanding this spec.

---

## Note on PostgreSQL Testing

The Phase 5.5 retrospective flagged that the PostgreSQL dual-DB testing gap caused a real production bug (verify-email 500 from naive-vs-aware datetime comparison). Phase 6 adds new datetime-adjacent code paths (proposal option timestamps, tie resolution timestamps) and new JSON column code paths (ballot storage, tie_resolution). These are exactly the kinds of code paths where SQLite and PostgreSQL disagree.

The team should **not** build the PostgreSQL test infrastructure in this pass — that's a separate item worth doing cleanly. But the team should **manually smoke-test** the new endpoints against a PostgreSQL instance (via the existing docker-compose setup) before calling Phase 6 done. A 15-minute manual sanity check covering: create approval proposal, cast approval ballot, tally, resolve tie. If any of those 500s, the bug is in scope for Phase 6 fix. If they all pass, note the verification in `PROGRESS.md` and move on. The planning agent will schedule the dedicated dual-DB CI pass soon.
