# Phase 49b — Cedar Hollow Governance Showcase — Closeout

**Spec:** `phase49b_demo_showcase_spec.md`
**Branch:** `phase-49b/demo-governance-showcase` → merged `--no-ff` to master
**Date:** 2026-06-02

---

## Overall

**SHIPPED.** Pure demo-content pass using shipped Phase 46/47/48 machinery. No platform logic changes, no migration, no FE changes — the cosign UI + title rendering + election affordances are already built; 49b just makes Cedar Hollow visibly use them.

---

## Per-cluster status

| Cluster | Status | Notes |
|---|---|---|
| B1 — Three Phase 47 titles + assignments | DONE | `TitleSeed` dataclass added to `demo_content/schema.py`; `OrgBible.titles` field plus seed-pipeline materialization. President (bound steward, holder hoa_janet), Secretary (bound admin, holder hoa_brenda), Treasurer (bound admin, holder hoa_linda). Janet's bible `platform_role` bumped from `'admin'` to `'steward'` so the daily reset preserves the binding. Brenda + Linda are bumped from moderator to admin via the bound-role logic in the seed loop. Floor preserved (exactly one steward). System titles (Steward, Admin) are seeded via `seed_system_titles_for_org` from inside the seed pipeline now, so every demo org gets the Phase 47 label layer on first reset cycle. |
| B2 — Elections enabled + Treasurer electable | DONE | `OrgBible.elections_enabled = True` writes `settings.elections.enabled=True` with trigger_sources `['admin_direct', 'member_cosign']` (the natural pair given B3). Treasurer.fill_method = `'elected'`; President stays `'assigned'` per the spec's "leave President stable so the top-of-org doesn't churn each reset" recommendation. No seeded election proposal — leaving the "Open Election" affordance available so a demo visitor can drive the flow themselves. |
| B3 — Cosign petition mid-gathering | DONE | `CosignPetitionSeed` dataclass; `OrgBible.cosign_petition`. Bible declares a petition titled "Petition: Add bike rack at the pool entrance" authored by Tomás Ortega (a member without `proposal.create` — the natural petitioner). 3 of 5 signatures collected (author + Diane + Ron) so the gathering UI shows "2 more needed." `OrgBible.allow_cosign_petition = True` writes `settings.allow_cosign_petition=True` to the org (post-49a model). |
| B4 — Daily reset reproduces showcase | DONE | `demo_reset_job._wipe_demo_orgs` extended with: (a) explicit `ProposalCosignature` delete before the bulk Proposal delete (FK safety on Postgres); (b) `OrgTitleAssignment` + `OrgTitle` (where `is_system=False`) delete per demo org. System titles (Steward, Admin) survive the wipe because they're seeded by `seed_system_titles_for_org` on org creation and don't need to be re-seeded each cycle. Re-seed reproduces all three custom titles + their assignments + the petition + its signatures. |
| B5 — Tests | DONE | `test_phase_49b_demo_showcase.py` (10 tests, 10/10 PASS) — title bindings + holder assignments + role bumps for Brenda/Linda + floor preservation + Treasurer-elected + President-assigned + elections.enabled + petition signature count + allow_cosign_petition toggle + wipe-clears-custom-titles-and-petition + reseed-reproduces-showcase. |

---

## Verification matrix

| Check | Required | Result |
|---|---|---|
| Backend pytest (Phase 49b + adjacent) | Yes | **116/116 PASS** — Phase 49b (10), Phase 49a (20), Phase 49 (14), Phase 48 stages (36), Phase 47 (16), Phase 46 + 46a (20). |
| Demo seed produces showcase | Yes | **PASS** — all three titles materialize with correct bindings + holders; elections.enabled True; petition in deliberation with 3 signatures. |
| Titles render after names | Yes | **PASS-by-source** — Phase 47's existing `held_titles` surface on `OrgMemberOut` already covers this; verified during Phase 49 QA that the rendering works. Browser QA after deploy will spot-check. |
| No duplicate office representation | Yes | **PASS** — the `Member.role` text field on the bible (e.g. `role='President'`) is purely a display label / persona description; the actual title rendering uses `OrgMemberOut.held_titles` from the assignments. Existing `personas` surface is unchanged. |
| Daily reset reproduces showcase (B4) | Yes | **PASS** — `TestB4ResetCycleReproducesShowcase::test_reseed_after_wipe_restores_showcase` runs the wipe + re-seed and asserts all three titles back with correct bindings + petition back with 3 signatures. |
| Floor not violated | Yes | **PASS** — `TestB1TitlesSeededWithBindings::test_floor_preserved_exactly_one_steward` confirms exactly 1 steward post-seed. President's steward binding aligns with the existing Cedar Hollow steward (Janet). |
| No migration | Yes | **No Alembic revision.** Pure demo-content + seed-pipeline + wipe-path changes. |
| Frontend | N/A | **No FE change.** The title rendering, election UI, and cosign-gathering UI all exist from prior phases. |
| Browser verification (Chrome MCP, demo) | Yes | **TBD** — recommend dispatching the QA sub-agent to walk demo-cedar-hollow as Janet (steward): confirm titles render after names in the member list + vote graph; confirm Treasurer shows the "Open Election" button; confirm the petition is visible in the proposals list with its 3/5 signatures + the gathering UI. |

---

## Branch + commit state

- Branch: `phase-49b/demo-governance-showcase`
- Commit on branch: `0ef6c51`
- Merge commit on master: `ff8a4f4` (no-ff)
- Pushed to origin/master: confirmed
- Railway deploy: `e29aabc0` SUCCESS at 2026-06-02 08:29:10 ET
- Bundle hash on prod: unchanged (no FE change) — last bundle was `index-Bp9L34tG.js` from Phase 49a
- First post-deploy digest tick: `2026-06-02T12:29:39Z`, scheduler healthy
- **Note**: the showcase content goes live on the **next demo reset** (daily at midnight Pacific via `digest_scheduler`'s reset hook), OR via a manual trigger of `POST /api/admin/demo/reset`. Until then, prod still has the old Cedar Hollow state.

---

## Tech debt / followups

- **Janet's role drift**: the bible's `platform_role` had been `'admin'` despite prod showing `'steward'` since some point in the past. The 49b bible change to `'steward'` aligns the two going forward. Any pre-49b state divergence is resolved by the next reset.
- **Multi-bible adoption**: only Cedar Hollow has titles + petition in its bible. Union Local 4021 and the Activist Coalition could get the same treatment if it shows well in QA. Future content polish.
- **Daily-reset trigger visibility**: the showcase only materializes on the next reset cycle. A manual `POST /api/admin/demo/reset` (or the `scripts/trigger_demo_reset.py` helper) can be called by Z post-deploy to land it immediately if desired.
