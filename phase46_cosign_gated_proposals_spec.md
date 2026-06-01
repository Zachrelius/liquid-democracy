# Phase 46 — Cosign-Gated Proposals (Petition Threshold)

**Type:** Standard implementation pass. New per-org proposal-creation tier + a signature-threshold exit condition on the existing deliberation phase + worker-driven expiry. **One migration** (cosign config + a signatures table/count + a couple of proposal columns).
**Branch:** `phase-46/cosign-gated-proposals` → `git merge --no-ff` to master.
**Dispatch prompt (one line):** `Read and execute phase46_cosign_gated_proposals_spec.md`

> **Provenance & sequence.** This is general governance infrastructure, not an election feature. It was surfaced while designing elections (Phase 47): the "call for an election" needs a way for ordinary members to trigger something without it being either fully open (anyone forces a vote) or admin-only. Z's insight: that "demonstrated-support gate" is valuable for **any** proposal, not just elections — it's the missing middle tier of proposal creation. So it's built first, as its own primitive, and Phase 47 consumes it as *one* of several election-trigger options.
>
> Arc order: **46 cosign (this) → 47 elections → 48 scheduled-terms.** (Note: "recall" is NOT a separate pass — see the arc passdown. Because leadership is "elected until a new election is called," an off-cycle election IS the recall mechanism. Scheduled/fixed-term elections are the later-pass option.)

---

## Status

Spec-ready. Conceptual decisions locked below (D1–D5).

---

## The idea

Today an org's proposal-creation sits at one of two poles, governed by permissions: either members can create proposals that go to the whole org (open, potentially noisy), or only admins/mods can (controlled, but concentrates agenda-setting power). **Cosign is the missing middle:** any member can *initiate* a proposal, but it only advances to a full org-wide vote once it has gathered a configurable number of member signatures — demonstrated support that it's worth the org's attention.

This is a real democratic primitive (petitions, motions-needing-a-second, ballot-initiative thresholds). It's valuable on its own merits and ships independently of elections.

**Mechanically (Z's design):** don't build a new phase. **Reuse the existing `deliberation` phase, and swap its exit trigger from time-based to signature-based.** A cosign-gated proposal sits in `deliberation` accumulating signatures; when it crosses the threshold, it advances to `voting` (the same transition `/advance` performs today). Everything already hanging off deliberation — comments, write-in options, the engagement layer — works unchanged during the signature-gathering window.

---

## Locked decisions

**D1 — Cosign is a per-org proposal-creation *mode*, configurable, sitting between open and admin-only.** Org config gains a creation-gating setting with (at least) these tiers: `open` (today's member-can-create-and-it-goes-live behavior), `cosign_required` (members can create, but a new proposal enters a signature-gathering state and only advances at threshold), and `admin_only` (only `proposal.create`-holders can create). The exact wiring to the existing `proposal.create` permission is an implementation detail; the conceptual model is "three tiers, org picks one (and per-proposal or per-category overrides are a *later* refinement, not this pass)."

**D2 — Signature threshold exits deliberation; a timeout expires it.** A cosign-gated proposal advances `deliberation → voting` the moment its signature count reaches the org-configured threshold. If it does NOT reach threshold within a configurable window, it expires — closing in a terminal `failed`-like state (recommend a distinct status value, e.g. `expired_unsigned`, so it's visually and analytically distinguishable from a proposal that went to vote and failed). The threshold check is synchronous (fires on each new signature); the expiry check rides the **existing scheduled worker** (`sustained_majority_worker`) — see Notes for the deploy-risk caveat. Dead petitions don't linger forever.

**D3 — The author counts as the first signature.** Creating a cosign-gated proposal implicitly signs it. So a threshold of `3` means "author + 2 others." Document this explicitly in the API, the UI ("2 more signatures needed"), and the spec'd tests so the semantics are unambiguous. (Z: either semantic is fine as long as the docs are clear; author-counts-as-1 is the chosen one.)

**D4 — Any active member can cosign; one signature per member; signing is not voting.** Cosigning is a lightweight "I want this to reach the org" signal — not a yes/no vote and not tied to the eventual ballot. Any active org member may sign; each member at most once; a member may withdraw their signature while the proposal is still gathering (which decrements the count and can keep it below threshold). No deliberation/quorum/voting-method apparatus attaches to the signature phase — it is a counter-to-threshold, nothing more. The author cannot withdraw their implicit signature without withdrawing the proposal.

**D5 — Cosign is general infrastructure; do NOT couple it to elections.** This pass builds the primitive for ordinary proposals. Phase 47 will wire it as *one* election-trigger option, but cosign must not assume or reference elections. (Forward note for 47: an election will be triggerable by cosign-petition OR by an admin/steward directly OR — Phase 48 — by a schedule. Cosign is one plug, not a requirement.)

---

## What IS in scope

- **B1 — Org creation-gating config + migration.** The three-tier creation mode (D1) on the org (column or `settings` key — implementer's call, but mode gates a hot path so a first-class column is preferred; justify in closeout). Default = `open` so every existing org behaves exactly as today. Migration reversible + cycle-tested + PG smoke (per CLAUDE.md, since the worker/migration ordering is deploy-time).
- **B2 — Signature model + threshold config.** A signatures record (one row per member-per-proposal, supporting the one-per-member + withdraw semantics of D4) and the per-org threshold + expiry-window config. Threshold semantics: author counts as 1 (D3). Sensible defaults (recommend threshold = max(3, ~10% of active members) and a multi-day expiry window — tune to a concrete default in the spec's config section; org-overridable).
- **B3 — Cosign-aware proposal creation.** When an org is in `cosign_required` mode, a member-created proposal enters the signature-gathering state (reuse `deliberation` status with a cosign marker on the row, rather than inventing a parallel status — keeps the existing deliberation machinery intact) instead of going live. Admin/`proposal.create`-holders may still create directly (mode is a floor for ordinary members, not a ceiling on admins — confirm this matches the permission model). A proposal row needs to carry: is-cosign-gated, current signature count (or derive via count query), threshold snapshot (capture at creation so later config changes don't move the goalposts mid-petition), and expiry timestamp.
- **B4 — Sign / withdraw endpoints.** `POST /api/proposals/{id}/cosign` (add the caller's signature; idempotent — re-signing is a no-op, not an error) and `DELETE /api/proposals/{id}/cosign` (withdraw). On each signature, check threshold; if met, perform the `deliberation → voting` advance (reuse the existing advance logic + `_compute_voting_end_at_advance` + the `proposal.entered_voting` notification emit, so cosign-triggered advancement is indistinguishable downstream from a manual advance). Audit events `proposal.cosigned` / `proposal.cosign_withdrawn` / `proposal.cosign_threshold_met`.
- **B5 — Expiry via the existing worker.** Extend the scheduled worker to close cosign-gated proposals whose expiry window has elapsed without reaching threshold, into the terminal `expired_unsigned` state, with an audit event. **This touches `sustained_majority_worker.py` / the worker launched from `start.sh` — see the deploy-risk note; verification MUST include running `bash start.sh` with prod-like env, not just `uvicorn --reload`.**
- **B6 — Tests.** Default-mode regression (org in `open` mode behaves byte-for-byte as today — the opt-in must be truly opt-in). Cosign-required mode: created proposal enters gathering state, not live. Author counts as signature 1 (D3). Threshold met → auto-advance to voting (assert the side effect: status, voting_start/end set, `proposal.entered_voting` notification fired). One-signature-per-member; re-sign idempotent; withdraw decrements and can drop below threshold; author can't withdraw without withdrawing the proposal. Expiry: a sub-threshold proposal past its window → `expired_unsigned` via the worker (test the worker codepath). Threshold snapshot at creation is immune to later org-config changes. **Assert side effects, not just status codes.**
- **F1 — Cosign UI.** On a cosign-gated proposal: a signature counter ("N of M signatures — K more needed"), a Sign / Withdraw button (member's own state), and the gathering-state framing distinct from an open proposal. In org settings, the creation-mode selector (open / cosign-required / admin-only) + threshold + expiry-window config, gated on the appropriate org-settings permission.
- **F2 — Creation-flow awareness.** When a member creates a proposal in a `cosign_required` org, the create flow should make clear what's about to happen ("your proposal will gather signatures before going to a vote; it needs M signatures within N days"). No silent behavior change.

---

## What IS NOT in scope (deferred)

- **Elections / role-assignment** — Phase 47. Cosign must not reference elections.
- **Per-proposal or per-category cosign overrides** — a later refinement. This pass is org-level mode only.
- **Scheduled / term-based anything** — Phase 48.
- **Delegation of signatures, weighted signatures, etc.** — out of scope; a signature is one member, one count.

---

## Forward dependencies & notes

- **Phase 47 (elections)** will consume cosign as one election-trigger option. Keep the cosign sign/threshold/advance logic readable and not proposal-type-specific, so an "election" proposal type can reuse it. The election's "call for election" = a cosign-gated proposal whose advancement opens the election vote; candidacy happens during the gathering window. But again — 47 wires that; 46 must not assume it.
- **Worker deploy risk (load-bearing):** `start.sh` launches `sustained_majority_worker` before uvicorn under `set -e`; a worker import crash takes down the container (backend 502, frontend 200). B5 touches the worker, so the verification matrix REQUIRES a local `bash start.sh` run with prod-like env. Do not certify B5 on `uvicorn --reload` alone.

---

## Verification matrix

| Check | Required | Notes |
|---|---|---|
| Backend pytest (full) | Yes | Baseline per the Phase 45b closeout (32 governance tests above the prior baseline). Report delta. |
| Default-mode regression | Yes | **Load-bearing.** An org in `open` mode behaves exactly as pre-46. The opt-in is truly opt-in. |
| Migration reversible + cycle test | Yes | Per CLAUDE.md. |
| PG smoke `--mode both --prior-revision <id>` | Yes | Prior revision = `d5e9f8a23bc4` (Phase 45b's migration) unless a later one landed; confirm the chain head at branch-cut. |
| **`bash start.sh` with prod-like env** | **Yes** | **B5 touches the worker. Local dev bypasses the worker side-process launch; this check is non-negotiable for worker-touching passes.** |
| Threshold/advance side effects | Yes | Threshold-met advances to voting with voting_start/end set + `proposal.entered_voting` emitted. Assert the effects. |
| Signature semantics | Yes | Author=1; one-per-member; re-sign idempotent; withdraw decrements; threshold snapshot immune to config change. |
| Expiry path | Yes | Sub-threshold past window → `expired_unsigned` via the worker codepath (not just a unit of the function — exercise the worker). |
| Frontend build | Yes | New bundle hash. |
| Browser verification (Chrome MCP, prod) | Yes | (1) Member creates a proposal in a cosign-required org → enters gathering state with counter; (2) signing advances the counter and, at threshold, the proposal moves to voting; (3) an `open`-mode org's create flow is unchanged. |
| Bundle hash changed + backend non-502 post-deploy | Yes | Standard — and doubly important given the worker touch. |

---

## Pass sizing

Within single-pass size, but it has a migration + a worker touch + new endpoints + FE, so it's on the heavier side of "one pass." It does NOT trip the Greater-Phase threshold (it's one coherent cluster, well under 50 new tests, one migration, no novel infra — the worker and deliberation machinery already exist). Ship as one pass, but build bisection-friendly: land the model + config + creation-gating first, then the sign/advance endpoints, then the worker-expiry, so a deploy failure localizes. The worker-expiry (B5) is the riskiest isolated piece — if anything about it feels bigger than expected mid-build, it's the clean thing to split into a 46a followup rather than forcing it into one deploy.

---

## Suggested team structure

**Continuing dev team or the Phase 44/45 team.** This extends the proposal lifecycle + the org-config + the worker — all well-trodden surfaces. Codebase context wins; not a fresh-eyes pass.

Default four roles: lead (delegate, writes closeout), backend dev (B1–B5), frontend dev (F1–F2, browser-verifies own UI), QA (prod browser verification + the `bash start.sh` worker check — make this QA's explicit responsibility given the deploy risk).

---

## Closeout reporting

Standard shape, plus:
- Confirm default-mode (`open`) regression: untouched orgs behave exactly as pre-46.
- State whether creation-mode is a column or settings key, and why.
- Confirm the author-counts-as-1 semantic is documented in API + UI + tests.
- Confirm the threshold snapshot is captured at creation and immune to later config changes.
- **Explicitly report the `bash start.sh` prod-like-env result** for the worker-expiry path.
- Migration + PG smoke status (both modes).
- Test count delta.
- Browser verification results.
- Any new tech debt — especially anything that will shape Phase 47 (elections reads this pass's cosign/advance logic).

---

## Notes for the team

- **Reuse the deliberation phase; don't invent a parallel one.** A cosign-gated proposal is a `deliberation`-status proposal with a cosign marker and a signature-based (rather than time-based) exit. The existing `/advance` logic, `_compute_voting_end_at_advance`, and the `proposal.entered_voting` emit are the advancement path — cosign just calls them when the threshold trips, so downstream behavior is identical to a manual advance.
- **Opt-in is the safety story.** `open` mode = today's behavior, untouched. Every cosign branch is gated on the org's creation mode.
- **The worker touch is the deploy-risk surface.** `bash start.sh` with prod-like env is mandatory verification, not optional. A worker import crash is a silent container-killer (502 backend / 200 frontend).
- **Keep cosign election-agnostic.** It's general infrastructure. Phase 47 will reuse it; this pass must not depend on or reference elections.
- **A signature is not a vote.** No quorum, no voting method, no ballot linkage. It's a counter-to-threshold with one-per-member + withdraw. Resist the urge to model it as a sub-proposal.
