# Phase 46a — Cosign Refinements + Serializer-Coverage Guard

**Type:** Standard implementation pass. Refines the Phase 46 cosign mechanism (delegation-weighted signatures + window-end threshold gate) and adds a CI guard for a recurring model-vs-response gap. **Likely no migration** (reuses existing columns + the `proposal_cosignatures` table; the threshold value's *meaning* changes but its storage may not — confirm in B2).
**Branch:** `phase-46a/cosign-refinements` → `git merge --no-ff` to master.
**Dispatch prompt (one line):** `Read and execute phase46a_cosign_refinements_spec.md`

> **Provenance.** Three refinements banked during the Phase 46 design + closeout, deliberately deferred so as not to interrupt 46 in flight (standing rule: refinements get their own followup pass, never a mid-pass amendment). Items 1–2 are corrections to cosign mechanics Z called after 46 was dispatched; item 3 closes a test-coverage blind spot that has now caused a prod hotfix in **two consecutive passes** (45a + 46).
>
> **Sequencing:** independently shippable now. The only ordering constraint in the arc is that this must merge **before Phase 47 Stage 3**, which consumes cosign as an election trigger and should consume the corrected (weighted, window-gated) version — not 46's immediate-advance headcount version. 47 Stages 1–2 do not depend on this and can run in parallel.

---

## Status

Spec-ready. All three items fully specified and locked with Z.

---

## Why this pass

Phase 46 shipped cosign-gated proposals with two simplifications that Z corrected after dispatch, plus the closeout surfaced a recurring serializer gap:

1. **Cosigning ignored delegation.** 46 counted signatures as a flat headcount (one member, one signature). But delegation is the platform's core mechanic — trust-weighted, topic-scoped participation. A cosign should carry the same weight the signer would carry if they voted on the proposal, so the most-trusted delegate on a topic can advance a relevant proposal on the strength of the trust real members have placed in them. (Z: "Delegation is the core mechanic of the platform... the most trusted member on healthcare being able to advance a proposal alone doesn't feel like a problem.")
2. **Threshold advanced immediately on being met.** 46 advanced `deliberation → voting` the instant the threshold was crossed. That collapses the nomination/gathering window — a petition that clears threshold on day one would open voting before candidates (for elections) or further signatories could participate. The threshold should be a **gate evaluated at the end of the deliberation window**, not an immediate trigger.
3. **`OrgOut` serializer gap — recurring.** Both 45a (`OWNER_ONLY_KEYS`) and 46 (`proposal_creation_mode`) shipped a new `Organization` field, passed all backend tests, then broke in prod browser QA because the field was missing from `OrgOut` (the response schema the FE reads). Same gap, same symptom, same fix, same discovery point — twice. Backend tests assert the ORM model + route logic (where the field is correct); nothing asserts the response *surfaces* it. This is a structural blind spot that will re-trigger every time we add an org-level field — and Phase 47 adds several.

---

## Item 1 — Delegation-weighted cosignatures (D1)

**Locked decision (Option 2, weight = resolved voting weight on the proposal):** a cosignature's weight equals the weight the cosigner would carry if they cast a vote on that specific proposal. A direct signer with no inbound delegation = weight 1. A delegate carries 1 + their **topic-relevant** delegated weight for that proposal (the same resolution the tally engine performs — topic-scoped, not a flat sum of all their delegators). The threshold is therefore measured in **weight**, in the same units a vote tally uses, which is the only definition consistent with the platform's topic-scoped delegation model.

- **B1.1 — Weight resolution reuses the existing engine.** Do NOT reimplement delegation resolution. The tally/delegation engine already computes per-proposal resolved weight (topic-relevant, chain-aware). A cosign's weight is that same computation for the signer against the proposal's topics. Confirm the existing engine exposes a "resolved weight for user U on proposal P" path the cosign code can call; if it only exposes full-tally resolution, extract the per-user weight in the least-invasive way (a thin helper over the existing pure resolution functions — not a parallel implementation).
- **B1.2 — Threshold becomes weight-based.** The org-configured threshold value now means "total cosign weight required," not "number of signers." The stored config field may not need to change type (a float/number already), but its **semantics** change — document this explicitly. Reconsider the default value in weight terms (46's headcount default of ~max(3, 10% of members) should be re-expressed; recommend keeping a comparable bar — e.g. weight equal to ~10% of total eligible voting weight, floored at a small constant — and state the concrete default in the config section).
- **B1.3 — Author's initial signature carries the author's resolved weight**, not a flat 1 (consistent: the author is a signer like any other, weighted by their standing on the proposal). The "author counts as the first signature" semantic from 46 (D3) holds; it's now "author counts as their resolved weight."
- **B1.4 — Live recomputation.** Cosign weight is resolved against the delegation graph as it stands when evaluated. If delegations change during the gathering window, the effective weight of existing cosigns can change. Evaluate at window-end (see Item 2) against the then-current graph. (Don't snapshot per-signature weight at signing time — that would freeze a delegate's weight against later delegation changes and diverge from how the eventual vote would resolve. Resolve live, same as the tally would.)
- **B1.5 — UI shifts from count to weight.** The 46 gathering panel ("K more signatures needed") becomes weight-expressed. Recommend showing both the human signal and the weight: e.g. "Signed by 4 members · 8.5 of 12 weight needed to advance" — exact copy is the FE dev's call, but the *advancement* bar is weight, and the UI must not imply it's a pure headcount when a single high-weight delegate can move it substantially.

**Edge to handle explicitly:** a single delegate whose resolved weight alone meets or exceeds the threshold can advance the proposal by signing (this is the intended behavior per Z, not a bug). The UI should make this legible (the member can see their own weight), but no special-case gating — it's the mechanic working as designed.

---

## Item 2 — Window-end threshold gate, not immediate advance (D2)

**Locked decision:** the deliberation window is the proposal's cadence; the threshold is a pass/fail check applied **at window-end**. The proposal stays in `deliberation` for its full configured window regardless of when the threshold is reached, accruing signatures (and, for elections later, candidates). At window-end: if cosign weight ≥ threshold → advance to `voting`; else → expire (`expired_unsigned`, the terminal state from 46).

- **B2.1 — Remove immediate-advance.** The 46 behavior where crossing the threshold synchronously calls the `deliberation → voting` advance is removed. Signing no longer advances the proposal; it only updates the accrued weight.
- **B2.2 — Window-end evaluation rides the existing worker.** The same scheduled worker that handles 46's expiry now performs the combined window-end check: at the deliberation window's close, evaluate `weight ≥ threshold` → advance-or-expire. This **unifies** 46's two separate exit conditions (immediate-advance-on-threshold + expire-on-timeout) into one window-end decision. **This touches `sustained_majority_worker.py` / the `start.sh`-launched worker — the `bash start.sh` prod-like-env verification is mandatory (see matrix).** (Phase 46 already proved the prod-mimic worker sequence; reuse it.)
- **B2.3 — Live, not latched.** Threshold status is evaluated at window-end against the then-current state. A proposal that crossed threshold mid-window but dropped back under (via signature withdrawals or delegation changes shifting weight) **fails at window-end and expires.** Do not latch on first crossing. (Rationale: the threshold is "did this have enough support *when its window closed*," consistent with evaluating live weight.)
- **B2.4 — Advancement path unchanged downstream.** When the window-end check advances the proposal, it calls the same existing advance logic (`_compute_voting_end_at_advance` + the `proposal.entered_voting` emit) so a cosign-advanced proposal is indistinguishable downstream from a manually-advanced one — same as 46.
- **B2.5 — Audit.** `proposal.cosign_threshold_met` now fires at window-end advancement (not at first crossing). Add `proposal.cosign_window_closed_unmet` (or reuse the `expired_unsigned` transition audit) so the "had a window, didn't make it" case is legible in the log.

**Net effect:** the timer is no longer just an expiry backstop — it's the actual gathering cadence, with the weight threshold as the pass/fail check at the end. This is what gives elections (47) a sane nomination window: candidates declare during the full deliberation window, and the vote only opens after it closes with sufficient support.

---

## Item 3 — `OrgOut` serializer-coverage regression guard (D3)

**Locked decision:** close the model-vs-response gap structurally so it stops being discovered in prod QA.

- **B3.1 — Serializer-coverage test.** Add a backend test that round-trips an `Organization` through `_org_to_out` (and any sibling org-response serializers the FE depends on) and asserts the response surfaces the known org-config fields the frontend reads: at minimum `governance_mode`, `proposal_creation_mode`, the cosign config fields, and the owner-only permission flags wired in 45a's hotfix. The test should be written so that adding a new org-config field and forgetting to surface it is caught here, in CI, in seconds — rather than in prod browser QA. (Implementer's discretion on the exact mechanism — an explicit allow-list of must-surface fields asserted against the serialized output is the simplest robust version. A fully-automatic "every model column must appear" check is likely too broad, since some columns are intentionally internal — prefer the explicit must-surface list, documented as "add your field here when it's FE-facing.")
- **B3.2 — Standing convention, noted into 47.** Add a one-line checklist item to the Phase 47 spec (and as a general convention in `CLAUDE.md`'s testing-strategy section if it fits): *any new `Organization` field the FE depends on ships with its `OrgOut` surfacing + an assertion in the serializer-coverage test, in the same pass.* Phase 47 adds several org-level config fields (election enablement, trigger config, slate defaults) and is the pass most likely to re-trigger this bug — closing it here saves multiple prod-QA hotfix cycles there.

**This item has no FE work and no migration** — it's a test + a documented convention. It's the cheapest high-value thing in the pass.

---

## What IS NOT in scope

- Any change to the three-tier creation mode (open / cosign_required / admin_only) — that's 46 and stays as-is.
- Per-proposal or per-category cosign overrides — still a later refinement.
- Anything election-specific — 47. Cosign stays election-agnostic; 47 consumes it.
- Weighted *voting* changes — the vote tally is unchanged; this pass only makes *cosign weight* use the same resolution the tally already uses.

---

## Verification matrix

| Check | Required | Notes |
|---|---|---|
| Backend pytest (full) | Yes | Baseline per the Phase 46 closeout (24 cosign/governance tests above prior). Report delta. |
| Cosign-disabled / open-mode regression | Yes | Orgs in `open` mode and any non-cosign proposal path behave exactly as post-46. |
| Weighted-threshold behavior (Item 1) | Yes | Direct signer = weight 1; delegate = 1 + topic-relevant delegated weight (assert against the tally engine's resolution for the same user+proposal — they must agree); single sufficient-weight delegate can advance; weight recomputes live against delegation changes. |
| Window-end gate (Item 2) | Yes | Proposal stays in deliberation full window even after threshold crossed; advances at window-end if met; expires if unmet; **drop-back-under-then-window-close → expires** (not latched). Assert side effects (status, voting_start/end on advance; `expired_unsigned` on expiry). |
| **`bash start.sh` prod-like env** | **Yes** | **Item 2 changes the worker's window-end logic. Reuse 46's prod-mimic sequence (create_tables → alembic stamp head → `python -m sustained_majority_worker --once`). Non-negotiable for worker-touching passes.** |
| Serializer-coverage test (Item 3) | Yes | The new test fails if a known FE-facing org-config field is dropped from `OrgOut`. Verify it would have caught the 45a + 46 regressions (add a deliberately-omitted field in a scratch run to confirm it fails, then restore). |
| Migration | Confirm | Likely none (reuses existing storage). If the threshold-semantics change forces a column change, make it reversible + cycle-tested + PG smoke. State the outcome explicitly in closeout. |
| Frontend build + bundle hash | Yes | Item 1's UI shift (count → weight). **Watch the PWA cache stickiness flagged in 46 QA** — if the weight UI looks stale after deploy, suspect the PWA cache before chasing a regression. |
| Browser verification (Chrome MCP, prod) | Yes | (1) A cosign proposal stays in its gathering window after threshold is crossed and only advances at window-end; (2) a delegate signing visibly moves the weight bar by more than 1; (3) the weight UI reads correctly (not as a headcount). |

---

## Suggested team structure

**Continuing dev team / the team that shipped 46.** This refines their own cosign work + their worker change, and reuses the delegation engine — full codebase context. Not fresh-eyes.

Default four roles: lead (delegate, closeout), backend dev (Items 1–2 + the Item 3 test), frontend dev (Item 1 UI shift, browser-verifies + watches the PWA cache), QA (prod browser verification + the `bash start.sh` worker check — explicit QA responsibility given the worker touch).

---

## Closeout reporting

Standard shape, plus:
- Confirm cosign weight resolution agrees with the tally engine's resolution for the same user+proposal (the two must not diverge).
- Confirm window-end gate: full-window hold, advance-if-met, expire-if-unmet, not-latched.
- **Report the `bash start.sh` prod-like-env result** for the worker's window-end logic.
- Confirm the serializer-coverage test exists and would have caught the 45a/46 regressions (state how this was verified).
- State the migration outcome (none, or reversible + PG smoke).
- Confirm the standing serializer convention was noted into the 47 spec / `CLAUDE.md`.
- Test count delta; browser verification results; any PWA-cache observations.

---

## Notes for the team

- **Cosign weight = the weight the signer would carry voting on this proposal.** Reuse the delegation/tally engine's existing per-user resolution; do not build a parallel weight calculation. The threshold is now in weight units, not headcount.
- **The threshold is a window-end gate, not a trigger.** Signing accrues weight; the worker decides advance-or-expire when the deliberation window closes. One combined decision, evaluated live (not latched at first crossing).
- **The worker touch demands the `bash start.sh` check.** A worker import/logic crash is a silent container-killer. 46 already wrapped the expiry in try/except and ran the prod-mimic sequence — hold that bar.
- **Item 3 is cheap and high-value.** A new `Organization` field has broken prod twice for the identical reason. The serializer-coverage test turns that from a prod-QA hotfix into a CI failure. Make sure it actually fails when a field is dropped (verify by deliberately dropping one in a scratch run).
- **Keep cosign election-agnostic.** 47 consumes it; this pass must not reference elections.
