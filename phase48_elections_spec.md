# Phase 48 — Binding Elections (Greater Phase)

**Type:** Greater Phase. Ships in **three staged deploys** (48 → 48a → 48b), each independently shippable and verifiable, with bisection built in per the Phase 13 lesson. Each stage gets its own branch, merge, closeout, and deploy.
**Dispatch:** stage by stage. Stage-1 dispatch prompt: `Read and execute phase48_elections_spec.md and implement Stage 1 only.`

> **Provenance & sequence.** This is model **B** of the governance end-state (locked with Z): an org can fill governance seats by **binding election through the platform's own voting engine**. It sits on top of Phase 45a (reassignable seats), 45b (the `single_steward` / `admin_council` mode field + the `governance.py` floor/recovery logic), 46/46a (cosign-gated proposals, reused as one election trigger), and **Phase 47 (titles)** — an election fills a **title** (and its optionally-bound platform role), reusing 47's titles concept + assignment machinery. Arc tail after this: **Phase 49 — scheduled / fixed-term elections** (the auto-on-term option). There is **no separate recall pass** — an off-cycle election IS the recall mechanism (challenge-and-replace in one act).
>
> **A `Title` is the election target (Phase 47 concept):** an election fills a title; if that title binds a platform role (e.g. "President" binds `steward`), winning grants the bound role via 47's assignment path. "Elect a steward" is just "elect the holder of the built-in steward title." This unifies all election targets — built-in seats and custom offices — behind one mechanism.
>
> Read `elected_leadership_arc_passdown_2026-05-31.md` for the full arc context before implementing. Depends on 45a/45b/46/46a/47 being shipped.

---

## Status

Spec-ready. All conceptual decisions locked (D1–D12 below). The only thing deliberately deferred to a later refinements pass: auto-nominate-incumbent-with-opt-out (D8 note).

---

## The core idea, and why it's small

An election is **a proposal whose outcome assigns a governance title** (and its optionally-bound platform role), rather than recording a decision. The platform already has: a voting engine with binary/approval/`ranked_choice` methods, `num_winners` + STV multi-winner tallying, quorum/threshold config, the proposal lifecycle (`draft → deliberation → voting → passed/failed`), the cosign-gated deliberation-exit (46/46a), and now the **titles concept + assignment machinery (47)**. The genuinely *new* machinery is narrow:

1. A way to mark a proposal as an **election** targeting a specific **title** (Phase 47 concept; the title carries its own cardinality and optional bound role).
2. **Candidacy** — self-nomination during the gathering/nomination window, producing the ballot.
3. A **close→assign-title hook**: when an election's vote closes, write the winner(s) into the title (and its bound role) via the Phase 47 assignment path — which itself uses the 45a/45b role machinery for any bound role.

Everything else is configuration of existing systems. The close→assign-title hook is the load-bearing, riskiest piece (it mutates governance state at tally time) — so it ships **first and most isolated**, in Stage 1, on the simplest path (single-holder steward-title election), where it can be verified end-to-end before the richer cases pile on.

---

## Locked decisions

**D1 — An election is a proposal subtype.** Reuses the proposal lifecycle, voting engine, eligibility model, and (46) cosign machinery. It carries election-specific fields (target seat(s), governance-mode context, candidate set) but is NOT a parallel object. All members vote, same eligibility as any proposal; inherits the verified-member-tier gate automatically when the ID-verification pass lands.

**D2 — Winning auto-grants the role; binding, no ratification.** When the election's voting closes and a winner is determined, the role assignment happens automatically as a side effect of close. This is the entire point — the non-binding "run a proposal, an admin manually assigns roles" path already exists via plain proposals and is NOT rebuilt here.

**D3 — Org-configurable: elect steward and/or admin seats.** An org chooses whether elections are enabled and for which seats. Works in both governance modes (`single_steward`, `admin_council`). Disabled by default — appointment (45a/45b) remains the default seat-filling mechanism until an org turns elections on.

**D4 — Triggering is configurable; cosign is one option, not a requirement.** An election can be triggered by: (a) **member cosign-petition** (reuses Phase 46 — the "call for an election" is a cosign-gated proposal whose advancement opens the election vote; this is the default for ordinary members), (b) **admin/steward direct** (leadership opens an election for a seat without a petition), or (c) **scheduled** (Phase 49, not built here). Do NOT hardcode cosign as required. An org configures which trigger sources are allowed.

**D5 — Candidacy is self-nomination only, during the nomination window.** Members declare "I'm running" during the gathering/nomination window (which, for cosign-triggered elections, overlaps the signature-gathering window; for admin-triggered, is an explicit nomination phase before voting opens). The ballot is whoever self-nominated by the time voting opens. **No draft-nominating others** — consent matters because the grant is binding and immediately assigns real power. (Future refinement, not here: nominate-someone-who-must-accept.)

**D6 — One candidate → auto-wins. Zero candidates → no vote, status quo holds.** An uncontested election installs the lone candidate (they stood, nobody contested). An election that reaches voting-open with zero candidates does not run — it expires (like an unsigned cosign petition), and the incumbent / current council stays. There is no "confirm the unopposed candidate yes/no" vote — because the seat is never empty (the 45a/45b floor guarantees an incumbent or council), a failed confirmation would just reinstate a non-running incumbent, which is a worse and more confusing outcome than letting the person who stood win.

**D7 — A seat only changes hands when a consenting alternative is fielded.** Consequence of D5+D6: to unseat an incumbent you must field a challenger; there is no purely-negative "remove the incumbent" referendum. This makes elections a *constructive* challenge mechanism (here's who instead, not just get rid of them) and means an incumbent never faces a vote unless a challenger appears.

**D8 — The incumbent must self-nominate to defend their seat.** No automatic ballot presence. If a challenger stands and the incumbent doesn't declare in the nomination window, the challenger runs unopposed and wins (incumbent forfeits by not defending). Consistent with "you should have run if you wanted it." Frivolous-challenge protection comes from the cosign-petition threshold (a member-triggered election needs the petition to open at all). **Deferred to the refinements pass:** an org option to auto-nominate the incumbent with a self-withdraw option.

**D9 — Multi-seat (council) elections reuse the existing multi-winner engine.** Electing N admin seats = a `ranked_choice` proposal with `num_winners = N`; the existing STV tally produces N winners. CONFIRMED present in the schema (`voting_method`, `num_winners`, `RCVTally`, `method: irv|stv`). No new voting infrastructure.

**D10 — Slate behavior is org- AND proposal-configurable.** For multi-seat elections, whether the election **refreshes the whole slate** (all elected seats up at once, winners replace the current holders) or **fills specific vacancies / adds seats** is declared by the election proposal itself (with an org-level default). Reuses `num_winners` to express seat count.

**D11 — Term model: "elected until a new election is called."** No fixed terms in this pass; an elected holder keeps the seat until a subsequent election changes it. (Fixed terms + auto-re-election = Phase 49.) This avoids any scheduler dependency and any leaderless gap — the incumbent holds until a replacement actually wins.

**D12 — Council-mode destructive-action gating folds in here.** (The deferred item from 45b.) In `admin_council` mode, the destructive/high-consequence actions — `org.delete` and the council→`single_steward` revert — **require multi-admin sign-off (Phase 44)**. Council mode requires Phase 44 multi-admin approval to be enabled for this destructive tier (the two opt-ins are coupled for destructive actions only; everyday council operation stays single-admin). This belongs in 47 because the **elected revert** (D-note below) is the same concern: electing a steward while in `admin_council` mode IS the revert to `single_steward`, so the gating and the elected-revert are one design surface.

> **Elected revert:** electing a steward while an org is in `admin_council` mode = the governance-mode revert to `single_steward` (the winner takes the steward seat, the mode flips). This is the "democratic" revert path that 45b's D3 anticipated, alongside 45b's baseline (an admin unilaterally reclaims) and the multi-admin-sign-off path (D12). All three coexist as org-configurable options.

---

## Stage breakdown

Each stage is an independently shippable deploy. Build + verify + deploy + closeout one before starting the next.

### Stage 1 (Phase 48) — Existing-org parity hardening + single-title election + the close→assign-title hook

The riskiest, most isolated piece first. Proves the binding-election mechanism end-to-end on the simplest path — AND lands the cross-cutting parity hardening up front so the rest of 48's new org-level config inherits the guard.

**B0 — Existing-org parity hardening (cross-cutting, lands first).** Folded into 48 per Z. Closes the recurring class of bug that needed reactive hotfixes in **three consecutive passes** (45a + 46 = response-schema gaps; 47 = a permission-grant gap): a new platform addition is wired into the org-creation / role-seed path, works for newly-created orgs, and silently breaks for **existing** orgs because nothing backfilled them. The serializer-coverage test (46a) catches the *schema* variant; this adds the *grant/seed* variant and a general parity assertion.
  - **B0.1 — Existing-vs-new-org parity test helper.** A reusable test that materializes an org "as if created before feature X" (no backfill) and an org "created now," runs migrations, and asserts the two reach parity on: role_permissions grant rows (the 47 hotfix class), seeded system titles (47), org-default settings/config rows, and the FE-facing response fields (extends the 46a `_MUST_SURFACE_FIELDS` contract). Designed so that adding a new seeded/granted thing and forgetting to backfill existing orgs FAILS here, in CI, not in prod QA.
  - **B0.2 — Prior-additions audit.** Same shape as the standing Phase 4c multi-tenancy retrofit audit: sweep for additions from *earlier* passes that may be silently missing on existing orgs but haven't surfaced because nobody's hit them yet. We've patched the three we tripped over; check for un-tripped ones (permission keys, default settings, seed rows added since multi-tenancy). Report findings; fix the cheap/safe ones in this stage, flag anything bigger as its own item rather than scope-creeping Stage 1.
  - **B0.3 — Apply the discipline to 48's own additions.** Every new org-level field/grant/seed this phase introduces (election-enablement config in Stage 1, trigger config in Stage 3, slate defaults in Stage 2) ships with its backfill migration for existing orgs AND its parity assertion in the B0.1 helper — in the same stage it's introduced. 48 is the first pass to practice the discipline on itself.

**Election work (Stage 1 core):**
- **Election proposal subtype targeting a Title (47 concept).** A proposal flagged as an election whose target is a **title** — for Stage 1, the built-in **steward system title** (47 seeds steward/admin as system titles). The election carries: target title, governance-mode context, candidate set. Reuses the proposal lifecycle/voting/eligibility — not a parallel object (D1).
- **Candidacy:** self-nomination endpoints (declare / withdraw) during the nomination window; ballot assembled from self-nominees (D5).
- **Triggering for Stage 1: admin/steward-direct only** (open an election for the title). Cosign-triggering lands in Stage 3 — Stage 1 just needs *a* way to open an election to exercise the hook.
- **The close→assign-title hook (the load-bearing piece):** on voting close, determine the winner (single-winner tally) and assign the target title via **47's `org_titles.py` assignment path** — for the steward system title, that path already routes the bound-role change through the 45a/45b machinery (`_apply_bound_role_for_assign` does the atomic steward swap: outgoing steward → admin, winner → steward) and is already guarded by `_check_revoke_floor` / the `governance.py` floor. **Reuse it; do not reimplement role assignment in the election close-hook.** Emit `election.resolved` + the existing title/role audit events. NOTE: 47 *rejects* steward-binding assignment in `admin_council` mode — Stage 1 is `single_steward` only, so this is fine; the council-mode elected-revert that needs that path is Stage 3 (and must reconcile with 47's council-mode rejection — flag for Stage 3 design).
- **D6 on the simple path:** one candidate auto-wins; zero candidates → election expires, incumbent stays.
- **Stage-1 UI:** open-election control (admin), self-nominate/withdraw, ballot + election framing on the proposal, result shows the installed title-holder (reuse 47's `held_titles` display so the winner's new title renders after their name automatically).

### Stage 2 (Phase 48a) — Multi-seat council elections + admin-seat elections + slate config

- Admin-seat elections (single and multi-seat) in both governance modes.
- Multi-seat via `ranked_choice` + `num_winners` + STV (D9).
- Slate behavior config (whole-refresh vs fill-vacancy, D10), org default + per-proposal declaration.
- The close→assign-title hook generalizes to write N winners into N holders of a multi-holder title (47 cardinality), via `org_titles.py`, respecting the mode-aware floor from `governance.py` (≥1 steward / ≥1 admin).

### Stage 3 (Phase 48b) — Trigger configuration + cosign-triggering + elected revert + council-mode destructive gating

- Trigger-source org config (D4): enable/disable member-cosign-petition, admin-direct.
- Cosign-triggered elections (reuse Phase 46): the call-for-election is a cosign-gated proposal; candidacy happens during its signature-gathering window; threshold-met opens the election vote.
- The **elected revert** (electing a steward in `admin_council` mode flips the org back to `single_steward`).
- **Council-mode destructive-action gating (D12)** — `org.delete` + the revert require Phase 44 sign-off in council mode.

---

## What IS NOT in scope (deferred)

- **Scheduled / fixed-term elections + auto-re-election** — Phase 49 (D11).
- **Auto-nominate-incumbent-with-opt-out** — refinements pass (D8 note).
- **Draft-nominating other people** — possibly a later refinement, with mandatory accept-to-run (D5).
- **Weighted / delegated candidacy or signatures** — out of scope.
- **Any new voting method** — D9 reuses what exists.

---

## Verification matrix (applies per-stage; stage-specific notes inline)

| Check | Required | Notes |
|---|---|---|
| Backend pytest (full) | Yes (every stage) | Baseline per the most recent prior closeout (46's, then 47's, then 47a's). Report delta each stage. |
| Elections-disabled regression | Yes (every stage) | **Load-bearing.** An org with elections off behaves exactly as 45b/46 left it. Appointment remains default. The opt-in is truly opt-in. |
| Existing-org parity (B0, Stage 1) | Yes (Stage 1) | The parity helper FAILS when a seeded/granted/FE-facing addition isn't backfilled to existing orgs. Verify by deliberately omitting a backfill in a scratch run (as 46a did for the serializer test). |
| Prior-additions audit reported (B0.2) | Yes (Stage 1) | Findings listed in the Stage 1 closeout; cheap fixes applied, bigger ones flagged. |
| 48's own additions backfilled (B0.3) | Yes (each stage adding org-level config) | Every new election org-config field/grant ships its existing-org backfill + a parity assertion in the same stage. |
| close→assign-title side effects | Yes (Stage 1, then each stage that touches it) | Assert the ACTUAL title assignment + role rows after close (via the 47 `org_titles.py` path): winner holds the title, bound role granted, outgoing holder demoted per 45a, floor satisfied, mode correct. Not just status codes. This is the load-bearing assertion of the whole phase. |
| At-least-one-governor floor preserved | Yes | After every election-resolution path, the `governance.py` floor holds (≥1 steward / ≥1 admin per mode). Reuse 45b's floor tests as a regression base. |
| D6 paths | Yes | One candidate auto-wins; zero candidates → expires, incumbent stays; contested → tally winner installed. |
| D8 path | Yes | Incumbent who doesn't self-nominate forfeits to an unopposed challenger. |
| Migration reversible + cycle test | Per stage that adds schema | Per CLAUDE.md. |
| PG smoke `--mode both --prior-revision <id>` | Per stage that adds a migration | Chain head at each stage's branch-cut. |
| Phase 44 path (Stage 3 / D12) | Yes (Stage 3) | Council-mode `org.delete` + revert defer to ratification; verify the gating couples correctly to the mode. |
| Multi-winner tally (Stage 2) | Yes (Stage 2) | N winners → N seats; STV path correct; floor respected. |
| Cosign-trigger (Stage 3) | Yes (Stage 3) | Reuses Phase 46; candidacy during the signature window; threshold opens the election vote. |
| Frontend build + bundle hash | Yes (every stage) | |
| Browser verification (Chrome MCP, prod) | Yes (every stage) | Stage 1: admin opens a steward election, members self-nominate, vote closes, winner is installed as steward and prior steward is now admin. Stage 2: a council multi-seat election installs N admins. Stage 3: a cosign petition opens an election; an elected steward in council mode reverts the org to single_steward. |
| Worker / `start.sh` check | If a stage touches the worker | Cosign-trigger (Stage 3) reuses 46's worker-expiry for the petition window — if Stage 3 touches `sustained_majority_worker.py`, the `bash start.sh` prod-like-env check is mandatory. |

---

## Suggested team structure

**Continuing dev team / the team that shipped 45a–46.** This is deep integration with the proposal lifecycle, the voting/tally engine, `governance.py`, the 45a transfer machinery, the Phase 44 approval registry, and 46's cosign — maximal codebase context required. Not a fresh-eyes pass.

Per stage: lead (delegate, writes the stage closeout + decides if the next stage is ready), backend dev (the subtype + candidacy + the close→assign-title hook — the load-bearing work), frontend dev (per-stage UI, browser-verifies own work), QA (prod browser verification of the full elect→install flow + the floor/regression checks).

---

## Closeout reporting (per stage)

Standard shape, plus per stage:
- Confirm elections-disabled regression (untouched orgs unchanged).
- Confirm the close→assign-title hook reuses 47's `org_titles.py` path and its side effects are asserted (actual title + role rows, floor satisfied, mode correct) — this is the headline of the phase.
- Confirm B0: the parity helper exists and fails when a backfill is omitted; report the B0.2 prior-additions audit findings.
- Confirm the floor holds after every resolution path.
- Stage 3: confirm the D12 gating couples to council mode correctly; confirm the elected revert flips the mode; report whether the worker was touched (and the `bash start.sh` result if so).
- Migration / PG smoke status.
- Test count delta.
- Browser verification results for the stage's elect→install flow.
- Readiness call: is the next stage clear to start, or did anything surface that changes its shape?

---

## Notes for the team

- **The close→assign-title hook is the whole ballgame.** It mutates governance state (who holds a title, and any bound role) at tally close. It reuses **47's `org_titles.py` assignment path** (which itself routes bound-role changes through the 45a/45b machinery and the `governance.py` floor) — do NOT reimplement role assignment. It ships first (Stage 1), most isolated, on the single steward-title path, so a failure localizes. Assert its side effects exhaustively — actual title + role rows after close, not status codes.
- **Elections are proposals — reuse, don't fork.** The lifecycle, voting engine, tally, eligibility, and cosign machinery all exist. The new surface is: the election marker + target seat(s), candidacy, and the close hook. Resist building a parallel voting system.
- **Binding auto-grant means consent and buy-in are load-bearing.** Self-nomination only (D5). One candidate wins, zero candidates = status quo (D6). Incumbent must defend (D8). These aren't arbitrary — they're what keep a binding role-grant from installing someone who never agreed to serve or seizing a seat with no org support.
- **The floor is sacred.** Every resolution path preserves ≥1 steward / ≥1 admin per mode. The 45b `governance.py` helpers are the single source of truth — read them, don't reimplement.
- **Stage gating is real.** Each stage deploys and is verified before the next starts. The Phase 13 precedent (a too-big single deploy) is why this is staged with the riskiest piece isolated first.
