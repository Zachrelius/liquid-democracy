# Phase 52 Stage 1 — Closeout

**Status:** SHIPPED 2026-06-03
**Branch:** `phase-52/verification-enforcement` (merged --no-ff)
**Merge commit:** `a89f9b1`
**Feature commit:** `00cee05`
**Spec:** `phase52_verification_enforcement_and_didit_spec.md`

## Scope shipped

Stage 1 (enforcement + delegation fork against stubbed verification state) — only.
Stage 2 (52a: Didit integration) and Stage 3 (52b: free-pool metering) are
deferred to subsequent passes per the original spec.

## Per-workstream status

| Workstream | Status |
|------------|--------|
| C1 — `PROV_DIDIT` constant + DB audit | DONE (all 252 prod users on `provenance='none'`; no rename needed) |
| C2 — Migration `d9e4f2a78543` (proposal.verification_floor + jurisdiction) | DONE |
| C3 — Gate predicate + three enforcement points (membership / role / vote) | DONE |
| C4 — Delegation fork + transparency endpoint | DONE |
| C5 — FE enforcement surfaces (per-proposal picker, OrgSettings, structured-403 unwrap, transparency panel) | DONE |

## Verification matrix

| Check | Required | Result |
|-------|----------|--------|
| Phase 52 unit tests (`test_phase_52_verification_enforcement.py`) | Yes | 27/27 PASS |
| Phase 52 migration cycle test (`test_phase_52_migration_cycle.py`) | Yes | 2/2 PASS |
| Adjacent regression sweep (Phases 45–51 + delegation/voting/role/org_titles) | Yes | 385/385 PASS in 3:21 |
| PG smoke (fresh + upgrade-from-c8d3e1f56432) | Yes | PASS both modes |
| FE build clean | Yes | `index-4my4n4xI.js`, 1.5MB / 408KB gzipped |
| Railway deploy | Yes | Bundle flip in 41s, backend startup complete |
| Migration applied on prod | Yes | Log: `Running upgrade c8d3e1f56432 -> d9e4f2a78543, phase 52 stage 1 — proposal verification floor fields` |
| Prod sanity (`/api/orgs/demo-cedar-hollow/public` → 200; real-user `/admin/pending-actions/count` traffic 200) | Yes | PASS |

## Test count delta

Phase 51 (adjacent regression baseline): 267 tests
Phase 52 Stage 1 (adjacent regression with new files): 385 tests
Adds: +29 (27 enforcement + 2 migration cycle), rest from broader adjacent set
(added vote/delegation/role suites that weren't in the Phase 51 curated set).

The full-repo sweep was attempted but stalled in the buffered-output trap; the
curated adjacent set is the right scope per CLAUDE.md convention and matches
the Phase 51 pattern.

## Browser verification

Not exercised this pass — pure-source review of the FE surfaces with structured-403
unwrap wiring + the verification floor picker rendering. Recommend QA sweep against
prod (Cedar Hollow / Local 4021 demo orgs) before flipping any real floors, since
floors-as-NULL means today's prod is byte-for-byte unaffected and the behavioral
change only surfaces when an admin sets a floor in OrgSettings or in a proposal
create form.

## Files added / modified (21)

**Backend (12)**
- M `backend/verification.py` — three enforcement helpers, structured-403 builder,
  delegation-carries-weight setting helper, `PROV_DIDIT` constant
- M `backend/models.py` — Proposal.verification_floor + verification_jurisdiction
- M `backend/schemas.py` — ProposalCreate / ProposalOut field additions
- M `backend/routes/organizations.py` — membership floor + role-grant floor at four
  join/role-mutation sites; per-proposal floor validation + persistence in
  `create_org_proposal`
- M `backend/routes/org_titles.py` — role-grant floor in `_apply_bound_role_for_assign`
  BEFORE the steward atomic-swap demote
- M `backend/routes/votes.py` — per-vote floor BEFORE the eligibility check
- M `backend/routes/proposals.py` — Proposal response builder field surfacing;
  new `/api/proposals/{id}/verification-weight` transparency endpoint
- M `backend/delegation_engine.py` — `eligible_voter_ids_for_proposal` narrows by
  floor when the proposal is gated AND org setting is False
- M `backend/elections.py` — `_apply_election_winner` grants title row, then tries
  bound role with structured-403 → audit `election.winner_verification_required`
- A `backend/migrations/versions/d9e4f2a78543_phase_52_proposal_verification_floor.py`
- A `backend/tests/test_phase_52_verification_enforcement.py` (27 tests)
- A `backend/tests/test_phase_52_migration_cycle.py` (2 tests)

**Frontend (8)**
- A `frontend/src/verificationLabels.js` — shared state/provenance labels,
  structured-403 CTA copy helper, `extractVerificationRequiredDetail` extractor
- M `frontend/src/pages/Settings.jsx` — uses shared labels
- M `frontend/src/pages/admin/OrgSettings.jsx` — "Identity verification gates"
  section (three role floors + membership floor + jurisdiction + delegation toggle)
- M `frontend/src/pages/admin/ProposalManagement.jsx` — per-proposal floor dropdown
  + conditional jurisdiction input in `CreateProposalForm`
- M `frontend/src/pages/ProposalDetail.jsx` — header badge, vote-cast structured-403
  unwrap, transparency-weight panel
- M `frontend/src/pages/OrgPublicLanding.jsx` — join-flow structured-403 unwrap
- M `frontend/src/pages/InviteAccept.jsx` — invite-accept structured-403 unwrap
- M `frontend/src/pages/admin/Members.jsx` — role-change structured-403 unwrap

**Spec (1)**
- A `phase52_verification_enforcement_and_didit_spec.md`

## Deploy verification

- Railway deploy triggered by push of master `a89f9b1`
- Bundle hash flip observed 41s after push: `BXYiuSeI` → `4my4n4xI`
- Backend log: `Running upgrade c8d3e1f56432 -> d9e4f2a78543` + `Startup complete` +
  `Uvicorn running on http://0.0.0.0:8000`
- Smoke: `/api/orgs/demo-cedar-hollow/public` returning 200; real-user
  `/api/orgs/demo-cedar-hollow/admin/pending-actions/count` traffic returning 200
- PWA service worker may mask the new bundle for returning users until SW
  unregister + caches.delete + reload — known caveat, not Phase 52 specific.

## For Z review (load-bearing design choices)

1. **Cardinality-floor preservation by construction.** Role-grant verification
   check fires at the top of every role-mutation path, BEFORE any role-id write
   happens. Block aborts → existing role-holder keeps role → governance floor
   never violated. No "race" between demote-and-revert is possible because the
   check happens first.

2. **Election-winner fails verification.** Spec recommendation followed: title
   row granted (recognition kept) but role-bind held with structured audit
   `election.winner_verification_required`. Other HTTPException types re-raise
   so `finalize_election` records them in `failed_assignments`. This means if a
   winner doesn't meet the bound role's floor, they still show as the winner in
   election history but don't get the admin/moderator/steward role applied —
   org has to either run a new election or grant the role manually after the
   winner verifies.

3. **Delegation fork default.** "Unverified delegated weight carries on gated
   proposals" defaults to **No** (the new column defaults `False`). An admin
   has to flip the OrgSettings toggle to bring the legacy behavior back. The
   default-No matches the spec's safety stance: a verification floor that
   leaks weight through unverified delegators is a fake floor.

4. **`email_only` is treated as empty.** A floor of `""` or `"email_only"` is
   normalized to NULL on the column, so today's ungated proposals + ungated
   orgs remain ungated regardless of which sentinel is written.

5. **Persona = Didit mapping.** Existing `provenance='persona'` rows would
   still pass `user_satisfies_floor`, but prod has zero such rows (252/252 on
   `none`). When Didit goes live in Stage 52a, the constant lookup will trust
   `didit` provenance the same way it would have trusted `persona`. No rename
   migration needed.

## Deferred to Stage 52a (Didit)

- Nullifier `UniqueConstraint` (column landed in Phase 51 with index only; the
  uniqueness invariant + the `(provenance, identity_nullifier)` composite key
  enforcement comes with the actual Didit verifier).
- Honoring `demo_stub` provenance in production (`PROV_DEMO_STUB` is recognized
  but admin should not be able to write it outside the demo orgs — current state
  is the admin-backdoor accepts it; tighten in 52a).
- The "verify now" / "start verification" CTA in the FE structured-403 paths —
  currently the copy says "Verification options will become available in a
  future update" because there's no provider to route to yet.

## New tech debt

None introduced. The Phase 51-to-52 verification helper sprawl across
`verification.py` is intentional centralization, not debt.

## Operational follow-ups

- When an admin sets a floor on a proposal that's already in voting state,
  in-flight delegated weight from below-floor delegators is dropped on the
  next tally render via `eligible_voter_ids_for_proposal`. There is no audit
  on the delegators (which is fine — they didn't vote, they delegated). If
  this becomes noisy on prod, consider a "weight loss notification" event in
  a future pass.
- The transparency endpoint is per-proposal, not per-org. If users want a
  rollup ("how much delegated weight has been dropped on gated proposals this
  month?"), that's an org-scoped follow-up.

## Branch state

- `phase-52/verification-enforcement` merged to master via `a89f9b1` (--no-ff)
- master at `a89f9b1`, pushed to origin
- branch can be deleted locally and remotely at next cleanup pass
