# Phase 45a — Steward Recovery + Voluntary Handoff

**Type:** Standard implementation pass. Backend behavior change + new endpoint + one FE fix. **No migration** (no schema changes — all guards key off existing columns).
**Branch:** `phase-45a/steward-recovery-handoff` → `git merge --no-ff` to master.
**Dispatch prompt (one line):** `Read and execute phase45a_steward_recovery_handoff_spec.md`

> **Provenance:** Implements the A0+A1 recommendations from `phase45_ownerless_recon_findings_2026-05-31.md`, folded into one pass. The recon split them A0/A1 out of caution; they share the same two files and the same conceptual surface (the steward removal/transfer guards), so shipping them together is the more coherent unit. The opt-in *ownerless* mode (recon's A2 — zero-stewards-allowed, recovery state machine, elected-board scaffolding) is **deferred to Phase 45b** and is explicitly out of scope here.

---

## Status

Spec-ready. No open questions blocking implementation. Two conceptual decisions were made by the planning agent (locked below as D1 and D2); the rest is mechanical.

---

## Why this pass

Phase 45's recon found a **live latent production bug**, independent of the broader elected-leadership arc:

A solo steward whose account is soft-revoked (`User.is_active = False`, shipped Phase 39 B1) becomes simultaneously **unreachable** (`backend/auth.py` `_get_user_from_token` filters `is_active == True`, so they can't log in) and **irremovable** (`backend/routes/organizations.py::remove_member` blocks removing any steward unconditionally, regardless of `is_active`). Compounding it, the `org.transfer_stewardship` permission key is declared in `OWNER_ONLY_KEYS` but **no endpoint implements it** — there is no API path to hand off stewardship at all. Net effect: such an org is permanently ungovernable via the API; only direct production-DB mutation recovers it.

The planning agent independently verified all three legs of this against source (the removal guard, the auth filter, the absent transfer route). The recon's severity assessment holds.

This pass closes that lockout AND delivers voluntary stewardship handoff — a real, standalone user need (today a founder cannot step down at all). Both are recovery/continuity primitives; they belong together.

**The steward stays the default and the guaranteed single top-officer of every org. This pass does not introduce ownerless operation.** It makes the *specific person* holding stewardship replaceable and recoverable, while preserving the invariant that exactly one steward always exists. The zero-stewards-by-design case is Phase 45b.

---

## Locked decisions

**D1 — On voluntary handoff, the outgoing steward becomes Admin (not Member, not configurable).**
A founder handing off day-to-day leadership almost always stays involved; Admin keeps them fully operational without the permanent founder-artifact privilege. A clean exit (drop to Member, or leave the org entirely) is a *separate* future action — there is no "leave org" flow today (see Forward Dependencies). Transfer is an atomic role-swap: outgoing steward → admin, target → steward. It is never a demotion-leaving-a-vacuum.

**D2 — Inactive-steward removal is single-admin by default, but force-routes through Phase 44 multi-admin approval when the org has that enabled.**
Removing the org's top officer is exactly the high-stakes action Phase 44 exists for — so when an org has opted into multi-admin approval and `member.remove` is wrapped, removing an inactive steward goes through the ratification queue like any other wrapped removal. For orgs that have NOT opted in, a single admin can remove a *provably inactive* steward (the steward's account is revoked; they cannot object), because the alternative is the permanent lockout this pass exists to fix. We do not impose multi-admin approval on orgs that never asked for it.

**D3 — At-least-one-steward is enforced as a hard invariant on the default path.**
Wiring up transfer + inactive-steward-removal creates a new way to reach zero stewards (GAP-4 in the recon). On the default path that must be impossible. Enforcement:
- Transfer is atomic (swap, never leaves zero) — structurally can't drop the count.
- Inactive-steward *removal* is only permitted when it is a recovery action; after removal the org has zero stewards transiently, so the removal flow must **require the acting admin to simultaneously claim stewardship OR name a successor** (see B2). An admin cannot remove the sole steward and leave the org steward-less.
- The existing `change_member_role` guard ("Cannot change Steward role") and removal guard ("Cannot remove the Steward") remain for *active* stewards — unchanged.

**D4 — Active stewards remain fully protected; only the *inactive*-steward path is newly permitted.**
The relaxation is narrow: the removal guard gains an `is_active` check. An active steward is exactly as protected as today. This keeps the blast radius minimal and the regression surface tiny.

---

## What IS in scope

- **B1 — Relax the steward-removal guard for inactive stewards.** In `remove_member` (`routes/organizations.py`) and its mirror in `pending_actions/registry.py::execute_member_remove` (+ its validate path), the `system_key == "steward"` block gains an `is_active` check: an active steward stays un-removable; an inactive steward (`User.is_active == False`) may be removed as a recovery action. Audit event `steward.removed_while_inactive` on that path so the asymmetry is visible in the log.
- **B2 — Successor requirement on inactive-steward removal (D3 enforcement).** Removing the sole steward cannot leave the org steward-less. The removal of an inactive steward must atomically promote a named successor (or the acting admin) to steward in the same transaction. Surface this as a required parameter on the recovery path. (If the org somehow has more than one steward — not possible on the default path today, but defensive — removing one inactive steward while another remains does not trigger the successor requirement.)
- **B3 — Implement `org.transfer_stewardship`.** New endpoint `POST /api/orgs/{slug}/transfer-stewardship` with body `{target_user_id}`. Atomic swap per D1: current steward → admin, target → steward. Permission-gated on the existing `org.transfer_stewardship` owner-only key (steward-initiated). Target must be an active member of the org. Audit event `org.stewardship_transferred`.
- **B4 — Phase 44 integration for the recovery-removal path (D2).** When the org has multi-admin approval enabled and `member.remove` is wrapped, inactive-steward removal routes through the existing `PendingAdminAction` flow rather than executing directly. The successor designation (B2) must be carried through the pending-action payload so the ratified execution still satisfies D3. Confirm the Phase 44 action registry can carry the extra payload field; extend the `member.remove` action definition if needed.
- **B5 — Tests.** Cover: active steward still un-removable (regression); inactive steward removable by single admin on a non-opted-in org; inactive-steward removal blocked if no successor named (D3); successor promoted atomically; transfer endpoint happy path (swap is atomic, both roles correct after); transfer rejects non-member / non-active target; transfer rejects when caller is not steward; at-least-one-steward invariant holds after every path; Phase 44 path defers correctly when enabled and carries the successor field through ratification; audit events emitted on each path. **Assert side effects** (actual role rows after the swap, actual membership deletion + successor promotion), not just status codes — per CLAUDE.md testing strategy.
- **F1 — FE delete-org un-hardcoding (GAP-5).** `frontend/src/pages/admin/OrgSettings.jsx:199` swaps `const isSteward = currentOrg?.user_role === 'steward'` for the permission-driven `useHasPermission('org.delete')`, matching the Phase 12.5/12.6 convention used everywhere else on the page. One-line-ish.
- **F2 — Transfer-stewardship UI.** A minimal admin-surface control for the steward to initiate handoff: pick an active member, confirm, call B3. Lives in the org settings / members admin area wherever it fits the existing IA. Steward-only visibility (gated on `org.transfer_stewardship` via the resolved permission set). Keep it simple — this is a low-frequency action; a member-picker + confirm dialog is sufficient.

---

## What IS NOT in scope (deferred to Phase 45b or later)

- **Opt-in ownerless mode** — `org.allow_ownerless` setting, zero-stewards-as-a-valid-state, the recovery/"needs re-bootstrapping" state machine. **Phase 45b.** Phase 45a must not contradict it: the at-least-one-steward invariant here is *default-path* behavior, and 45b will gate the zero-steward case behind the opt-in. Do not hardcode "exactly one steward" in a way that 45b can't relax via setting.
- **Elected-leadership / board / recall** — Pass B/C of the broader arc. Not here.
- **Admin-initiated transfer as a routine path** — B3 is steward-initiated. The recovery path (B1+B2) is how an admin takes over when the steward is *inactive*. A general "admin initiates transfer of an *active* steward" path is an ownerless/elected-mode concern (45b+) and is deliberately omitted.
- **Multi-admin override of the at-least-one-steward invariant** — not applicable on the default path.
- **"Leave org" and "delete my account" flows** — don't exist today (confirmed: no self-removal or self-delete endpoint). Out of scope here. See Forward Dependencies.

---

## Forward dependencies (notes, not work for this pass)

- **Leave-org flow (future):** when built, must guard against a sole steward self-stranding the org — a steward attempting to leave must transfer first (reuse B3) or be blocked. Z flagged the missing leave-org path in `5-31_Notes.txt`.
- **Account-deletion flow (future):** same guard — deleting the account of a sole steward must not silently strand the org. Today no self-delete exists, so this is not a live vector; it becomes one the moment self-delete is built.
- **Phase 45b (ownerless opt-in):** will relax the at-least-one-steward invariant behind a per-org setting. Keep B1/B2/B3 logic readable enough that the cardinality floor can become setting-driven without a rewrite.

---

## Verification matrix

| Check | Required | Notes |
|---|---|---|
| Backend pytest (full) | Yes | Baseline 1564 PASS / 28 FAIL (per Phase 44 closeout). New tests add to PASS; the 28 known failures stay constant. Report the delta. |
| New behavior tests (B5) | Yes | All scenarios in B5 green. Side-effect assertions, not just status codes. |
| No migration | Yes | Confirm in closeout that no Alembic revision was added (guards key off existing `User.is_active` + role rows). If implementation discovers a schema need, STOP and flag — that would change the pass shape. |
| Active-steward regression | Yes | Explicit test: active steward still cannot be removed, suspended, or role-changed. The relaxation must be inactive-only. |
| At-least-one-steward invariant | Yes | Explicit test after every mutating path: org always has ≥1 steward on the default path. |
| Phase 44 path (D2/B4) | Yes | Browser-or-test verification that inactive-steward removal defers to ratification when the org has multi-admin approval on, and that the successor field survives the round-trip. |
| Frontend build | Yes | New bundle hash. |
| Browser verification (Chrome MCP, prod) per CLAUDE.md | Yes | Load-bearing user-facing changes: (1) steward initiates transfer via F2 UI → roles swap correctly; (2) the delete-org Danger Zone still renders for the steward post-F1 change. The inactive-steward *recovery* removal is hard to exercise in a browser (requires a soft-revoked account) — verify that path by test + source review and note it as such. |
| PG smoke | No | No migration. State "no migration, smoke not required" in the closeout. |
| Bundle hash changed + backend non-502 post-deploy | Yes | Standard deploy verification. |

---

## Suggested team structure

**Continuing dev team, not fresh-eyes.** Per the team-choice heuristic: this is "add what's missing" + "refactor existing guard" implementation work where codebase context wins, and the team will have to live with the change. The recon (Phase 45) was the fresh-eyes audit; 45a is the build. If the Phase 44 team is the one available, they're a good fit too — they own the `PendingAdminAction` registry that B4 integrates with, which de-risks the D2 path.

Default four-role structure: lead (delegate mode, writes closeout), backend dev (B1-B4 + B5 tests), frontend dev (F1-F2, browser-verifies own UI), QA (prod browser verification of the transfer flow + Danger Zone render).

---

## Closeout reporting

Standard shape (per CLAUDE.md), plus specifically:
- Confirm the at-least-one-steward invariant is enforced and tested on every mutating path.
- Confirm active stewards remain fully protected (regression test result).
- Confirm "no migration" explicitly.
- Report whether the Phase 44 `member.remove` action definition needed extending to carry the successor field (B4), and how.
- Test count delta.
- Browser verification results for the transfer flow + the post-F1 Danger Zone render; note the recovery-removal path as test/source-verified rather than browser-verified, with rationale.
- Any new tech debt surfaced (especially anything that will affect Phase 45b's ownerless opt-in).

---

## Notes for the team

- The narrow relaxation is the whole safety story: **only `is_active == False` stewards become removable.** Do not broaden it. An active steward must be exactly as protected after this pass as before.
- The at-least-one-steward invariant is the load-bearing guard. Every path that could change the steward count must preserve it on the default path. Transfer preserves it structurally (atomic swap); recovery-removal preserves it via the successor requirement (B2). Test both.
- Keep the cardinality floor logic readable and centralized — Phase 45b will make it setting-driven (`org.allow_ownerless`) and you don't want it smeared across three call sites.
- The `org.transfer_stewardship` permission key already exists in `OWNER_ONLY_KEYS` and is already tested at the permission-resolution layer — you're implementing the route that consumes a gate that's been sitting there unused since Phase 12.