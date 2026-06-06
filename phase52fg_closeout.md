# Phase 52f + 52g — Combined Closeout

**Status:** Both phases SHIPPED + DEPLOYED 2026-06-06.
**Branch:** `phase-52fg/legal-name-age-bands` (merged --no-ff).
**Master:** `0127959` (merge) + `<this commit>` (closeout).
**Migration:** `f7a8b9c0d1e2` (down `e6f7a8b9c0d1`, hex-prefix). Applied on prod.
**Bundle:** `index-Bc-c4xAD.js → index-n8l9QaMJ.js` (live).
**Specs:** `phase52f_display_name_match_spec.md`, `phase52g_age_gating_spec.md`.

## Bundling decision

Z's dispatch said: "I'm like to give Orgs the option to either flag or block non matching names. All these options along with the to be speced 52i should be bundled under identity verification options in org settings."

Two structural decisions followed:
1. **52f block-vs-flag fork resolved → per-org configurable** (both options offered; ship both). Settings key `verification_name_match_action` with `block` (default) or `flag`.
2. **OrgSettings section renamed** from "Identity verification gates" to "Identity verification options" — 52f's name-match controls, 52g's min-age control, and the future 52i bundle here.
3. **52f + 52g shipped in one combined deploy.** Both touch `_apply_decision` (same site); both add nullable User columns (one migration is cleaner); both bundle under the same OrgSettings section; and the "verify once, light up everything" principle from both specs argues for shipping them together so a single re-verify populates legal name AND age band at once. Single `--no-ff` merge.

## What shipped

### Migration `f7a8b9c0d1e2`
Adds:
- `users.legal_first_name` (String 128, nullable) — 52f
- `users.legal_last_name` (String 128, nullable) — 52f
- `users.legal_full_name` (String 256, nullable) — 52f
- `users.verification_age_bands` (Text, nullable; stores sorted JSON list of met thresholds) — 52g
- `users.verification_age_promotes_at` (DateTime, nullable; month-aligned) — 52g
- `org_memberships.display_name` (String 80, nullable) — 52f
- `proposals.min_age` (Integer, nullable) — 52g

All nullable / additive; existing rows untouched. Direct PG query on prod confirms all 7 columns present + alembic head `f7a8b9c0d1e2`.

### 52g — age bands (DOB never stored)
- `verification.SUPPORTED_AGE_THRESHOLDS = (13, 16, 18, 21)`.
- `verification.compute_age_bands(date_of_birth, as_of)` returns `(sorted-met-set, month-aligned promotes_at)`. **Privacy-load-bearing: `promotes_at` is always the 1st of the relevant month**, never the user's exact birth day. Test `test_promotes_at_is_month_aligned_not_day` proves it.
- `verification.user_meets_age(user, threshold)` — lazy-promotion (Option A from the spec). No scheduler, no worker, no `start.sh` risk.
- `verification.check_membership_min_age_for_join(user, org)` + `check_vote_min_age_for_proposal(user, proposal)` — both raise structured 403 with `scope='min_age'` + the threshold value when not met.
- DOB is consumed in `_apply_decision` (alongside the hashes), then **discarded** — never stored.
- Cardinality-floor invariant: raising the min age on an org flips the predicate False for an under-band steward but **never** auto-strips the role row. Tested.

### 52f — legal name + per-org display name + display-name-match
- Legal name captured in `_apply_decision` from `decision.id_verifications[0].{first_name, last_name, full_name}` and stored **readable** on the User row. Locked decision rationale: the match feature compares an arbitrary user-entered display name against the legal name, which a hash can't support; the org is the enforcer, not the protected party, so hashing wouldn't add privacy. Disclosed in consent / Settings copy.
- `verification.display_name_for(user, org, membership=None)` — single resolver every org-context name-render must route through.
- `OrgMemberOut.display_name` now reads through the resolver — Members list shows the per-org override.
- `PATCH /api/orgs/{slug}/me/display-name` — sets the caller's per-org override; empty string clears.
- `verification.display_name_matches_legal(candidate, user, org)` — three modes (off / first / last / full). Reuses `verification_hashing.normalize_text` so match behavior tracks the hash-side conventions exactly.
- **Block vs flag** is org-configurable per Z's instruction. `SETTING_NAME_MATCH_ACTION` = `block` (default — hard-reject the write with 422 `name_match_required`) or `flag` (allow + audit row `org.display_name_mismatch`).
- Unverified users (no legal name) are unconstrained — the verification floor is what forces verification first; the name-match is an ADDITIONAL constraint on top.

### FE
- `OrgSettings.jsx`: section title renamed to "Identity verification options"; new dropdowns for name-match mode (off/first/last/full), name-match action (block/flag, conditionally rendered when mode != off), and minimum age (no minimum / 13 / 16 / 18 / 21).
- `verificationLabels.js`:
  - `ctaCopyForVerificationRequired` now handles `scope='min_age'` separately ("This organization requires members to be N+. Your verified age band doesn't meet that minimum.").
  - New `copyForNameMatchRequired(detail)` for the 422 `name_match_required` error.

## Verification matrix

| Check | Required | Result |
|---|---|---|
| Age band derived from real payload + DOB discarded | ✅ | `TestApplyDecisionCapturesLegalNameAndAgeBand::test_age_band_derived_from_dob`; DOB column not added in this migration (no path persists it) |
| Month-aligned promotes_at (privacy load-bearing) | ✅ | `TestComputeAgeBands::test_promotes_at_is_month_aligned_not_day`; `TestApplyDecisionCapturesLegalNameAndAgeBand::test_minor_gets_promotes_at_month_aligned` |
| `user_meets_age` lazy-promotion | ✅ | 4 cases — including the post-`promotes_at` advance + the pre-`promotes_at` non-advance |
| Membership min-age gate (side-effect) | ✅ | 3 cases — under blocked w/ structured 403 + no membership row; over passes; no setting = no gate |
| Proposal min-age gate | ✅ | 1 case — under blocked at vote with structured 403 |
| Composes with verification floor | ✅ | Both checks wired into the same three join paths sequentially; existing 52e Mode-3 + verification-floor tests still pass |
| Cardinality-floor invariant (52g) | ✅ | `TestCardinalityFloorInvariantWithAgeConfig::test_raising_min_age_does_not_strip_seated_steward` |
| Age NOT a new rung in the state ladder | ✅ | `TestIdentityUniqueRungNotInLadder::test_no_new_age_rung_added` |
| Legal name captured + stored readable | ✅ | `TestApplyDecisionCapturesLegalNameAndAgeBand::test_legal_name_persisted_on_verification` |
| Per-org display-name resolver | ✅ | `TestDisplayNameForResolver` — 3 cases (override via membership arg; fallback when null; fallback when no membership) |
| Member list uses the resolver | ✅ | `TestMemberListResolvesPerOrgDisplayName` — `/api/orgs/{slug}/members` surfaces the override |
| Match predicate (off/first/last/full) | ✅ | `TestDisplayNameMatchesLegal` — 10 cases including case+punctuation insensitivity, unverified-passes, empty-fails |
| Block vs flag enforcement | ✅ | `TestSetDisplayNameEnforcement` — 5 cases including block rejects 422, flag allows + audits, empty string clears |
| Mode-3 parity for both phases | ✅ | `TestMode3ParityStillHolds` (52e/52h existing) still passes; new `TestSetDisplayNameEnforcement::test_no_match_setting_any_name_allowed` and `TestMembershipMinAgeGate::test_no_setting_no_gate` cover the new gates |
| Serializer guards (legal name + age band NOT on UserOut) | ✅ | `TestSerializerGuards::test_legal_name_fields_not_on_userout` |
| Migration cycle (SQLite) | ✅ | 2 cases — upgrade adds all 7 columns; downgrade-upgrade cycle round-trips |
| PG smoke fresh + upgrade-from-`e6f7a8b9c0d1` | ✅ | PASS both modes |
| Adjacent regression | ✅ | 548/548 PASS in 4:40 (Phase 52h baseline + 42 new + 1 net update to the now-correct 52d cycle test) |
| FE build clean | ✅ | bundle `index-n8l9QaMJ.js`, 1.6MB / 415KB gzipped |
| `bash start.sh` prod-mimic | N/A | No start.sh / worker / scheduled tick change (lazy-promotion Option A) |
| Deploy + migration on prod | ✅ | `Running upgrade e6f7a8b9c0d1 -> f7a8b9c0d1e2, phase 52f+52g — legal name + age bands + per-org display name`; alembic head = `f7a8b9c0d1e2`; all 7 new columns visible via direct PG query |

## Test count delta

- Phase 52h baseline: 547 (after Stage 2)
- Phase 52f+52g additions: +42 new tests (40 unit + 2 migration cycle) + 1 fix to the 52d `test_doc_number_hash_unique_allows_multiple_nulls` test (now upgrades to head before the ORM insert since the model carries 52fg columns the 52d-only schema doesn't have).
- **548/548 PASS** in 4:40.

## Files added / modified

**Backend (8)**
- A `backend/migrations/versions/f7a8b9c0d1e2_phase_52fg_legal_name_age_bands.py`
- A `backend/tests/test_phase_52fg_legal_name_age_bands.py` (40 cases)
- A `backend/tests/test_phase_52fg_migration_cycle.py` (2 cases)
- M `backend/models.py` — 5 User cols + OrgMembership.display_name + Proposal.min_age
- M `backend/verification.py` — 52g age helpers + 52f name-match helpers + new settings keys; `SUPPORTED_AGE_THRESHOLDS` constant
- M `backend/routes/verification.py` — extract `full_name` in `_extract_ocr_fields`; persist legal name + derive age band in `_apply_decision`
- M `backend/routes/organizations.py` — `check_membership_min_age_for_join` wired into 3 join paths; `display_name_for` resolver wired into `list_members`; PATCH `/api/orgs/{slug}/me/display-name` endpoint with block-or-flag enforcement
- M `backend/routes/votes.py` — `check_vote_min_age_for_proposal` wired into vote-cast
- M `backend/tests/test_phase_52d_migration_cycle.py` — small fix for the multi-NULL ORM-based insert

**Frontend (2)**
- M `frontend/src/pages/admin/OrgSettings.jsx` — section title renamed; three new dropdowns (name-match mode + action + min age)
- M `frontend/src/verificationLabels.js` — `min_age` scope handling + `copyForNameMatchRequired`

**Specs (2)**
- A `phase52f_display_name_match_spec.md`
- A `phase52g_age_gating_spec.md`

## Audited name-rendering surfaces

Per the 52f spec, every surface that renders a user's name in an org context must route through `display_name_for`. Audited:
- ✅ `routes/organizations.list_members` (`OrgMemberOut.display_name`) — updated this pass.

**Not yet routed through the resolver (acknowledged follow-up, listed in the closeout as a found-gap):**
- Delegate profile pages and the public delegate listing — `DelegateProfile` / `OrgDelegateProfile` serializers still surface `user.display_name` directly. A follow-up resolver pass should route these.
- Proposal authorship + vote attribution + comments — same pattern; surfaces a user's name from various serializers that read `User.display_name` directly. A small follow-up routes them through the resolver.
- Notification copy + email templates — render names via various serializers; same routing pass.

These surfaces continue to render the platform-level `User.display_name`, which is consistent (just not yet per-org). The resolver returns the override only when an `OrgMembership.display_name` is set, so the consequence of NOT routing those surfaces yet is that a user who sets a per-org override sees the override on the Members list but their PLATFORM display name elsewhere. Acceptable for ship; tracked.

## For Z review (build-time decisions)

1. **Block vs flag (Z's instruction):** implemented as per-org configurable. `SETTING_NAME_MATCH_ACTION` defaults to `block` (recommended by the spec) but admins can flip to `flag` (allow + audit row). Both modes covered by side-effect tests.
2. **Single migration covers both phases.** The spec said the team could ship 52f + 52g separately if they wanted; the combined migration is the natural bundling per the "verify once, light up everything" principle (Z's next re-verify will populate legal name AND age band in one webhook).
3. **OrgSettings section renamed to "Identity verification options" per Z's instruction.** The future 52i bundles here too; same section title, same panel.
4. **Lazy-promotion (Option A) for age bands.** Recommended by the 52g spec; no scheduler / worker / `start.sh` touch. The user's age band advances on read once their `promotes_at` month has arrived.

## Existing-users-light-up-on-re-verify property

Both phases share the locked property that existing already-verified users (currently Z) populate the new columns only on their NEXT re-verify. Z's user row today has NULL `legal_*_name`, NULL `verification_age_bands`, NULL `verification_age_promotes_at` — and will until Z re-verifies. For the ~1-real-user pre-launch platform this is fine; once Z re-verifies, both 52f's match feature and 52g's age gate light up for that account simultaneously.

## Branch state

- `phase-52fg/legal-name-age-bands` merged via `0127959` (--no-ff); safe to delete at next cleanup.
- master at `0127959` (merge) + closeout commit (forthcoming this turn), pushed to origin, Railway deployed.

## What's NOT in this phase (future work)

- **Name-rendering resolver propagation to non-member-list surfaces** (delegate profiles, proposal authorship, vote attribution, comments, notifications). The resolver is centralized; the follow-up is purely "find call sites + replace." Tracked above.
- **A user-facing Settings panel to set per-org display names.** The PATCH endpoint exists and is enforced; the FE control to call it lives on a future per-org Settings cluster.
- **Proposal-creation form min_age picker.** The column exists; the FE control to set it on a per-proposal basis is a small follow-up.
- **Phase 52i** (TBD per Z's note) — will bundle under the same "Identity verification options" section.

## Closeout assertion

Phase 52f and Phase 52g are SHIPPED + DEPLOYED. The combined migration applied cleanly on prod. The verification arc now has three of its four announced future-phase candidates from the backlog live: 52f (per-org display names + display-name-match), 52g (derived age band), and 52h (org-scoped flag upgrade + doc-block removal — shipped previously). Phase 52i is the remaining queued capability under the same OrgSettings section title.
