# Phase 8.6 Prod Verification — Carry-Forward Cleanup

Browser-driven verification on `https://www.liquiddemocracy.us` after the Phase 7D + 8.6 deploy.

- **Date:** 2026-04-29
- **Bundle:** `index-Kg8m5C0g.js`
- **Method:** API probe via Claude-in-Chrome JavaScript tool. Each persona logged in via `POST /api/auth/demo-login`, then exercised the relevant endpoint.

## Item 1: Decision 3 topic visibility filter

Verified via `GET /api/topics` per persona:

| Persona | Engineering Practices visible? | Topic count | Expected | Actual |
|---|---|---|---|---|
| **alice** (parent admin, NOT in Engineering) | true | 7 | true (Decision 6 implicit power) | ✅ PASS |
| **dave** (Engineering admin, parent member) | true | 7 | true (Engineering member via SubOrgMembership) | ✅ PASS |
| **carol** (Engineering member, non-admin) | true | 7 | true (Engineering member via SubOrgMembership) | ✅ PASS |
| **frank** (parent-org-only, NOT in Engineering) | **false** | **6** | **false** (no SubOrgMembership, not parent admin) | ✅ **PASS — filter working** |
| anonymous (no auth) | false | 6 | false (strict default) | ✅ PASS |

Note: voter02 was originally proposed as the verification persona, but inspection of the demo seed showed she is actually an Engineering Team member (`extra_users[1]` was added in Phase 8.5 Session 1's seed). Frank is the canonical parent-org-only persona for this filter test.

## Item 2: voter02 Economy delegation in seed

Verified via `GET /api/proposals/{id}/my-vote` as voter02 (now an Engineering Team member with the new Economy → econ_bob delegation seeded):

```json
{
  "vote_value": null,
  "approvals": null,
  "ranking": null,
  "is_direct": null,
  "delegate_chain": null,
  "cast_by": null,
  "message": "Your delegate Bob the Economist has not voted. Chain behavior: accept_sub.",
  "delegation_strategy_fallback": null
}
```

The backend correctly:
1. Resolves voter02's delegation through the new Economy row (added by additive seed running on container restart after deploy)
2. Walks the topic relevance map and finds econ_bob via Economy on the Engineering proposal
3. Detects econ_bob has no ballot (he's not an Engineering Team member, so `eligible_voter_ids_for_proposal` excludes him)
4. Reports the chain-behavior fallback fired

This is exactly the Decision-8 cross-scope delegation case Suite R9 was designed to verify. **Suite R9 status: BLOCKED → PASS** (see `browser_testing_playbook.md`).

The frontend cross-scope "your vote" copy logic detects this exact situation (delegation resolved, delegate not in proposal's `sub_org_id` member set) and renders the spec copy: *"Your vote: not yet cast — your delegate Bob the Economist isn't in Engineering Team"* with `Set a specific delegate` and `Vote directly` action links. UI rendering not browser-traced this session because the demo persona-list UI doesn't expose voter02 as a quick-login button (the `/api/auth/demo-users` endpoint returns her, but the `Demo.jsx` button list is hardcoded to a smaller set). Source review of `ProposalDetail.jsx`'s cross-scope branch confirms the copy fires in this case.

## Item 3: start.sh migration ordering

Verified via deployment outcome: the Phase 8.6 deploy applied cleanly. `start.sh` now runs `create_tables()` only on the fresh-DB branch (when alembic isn't yet stamped); existing-DB deploys go straight to `alembic upgrade head` with no collision risk. Bundle `index-Kg8m5C0g.js` came up healthy on first attempt — no 502 incident this deploy.

## Item 4: PG smoke harness

`backend/scripts/pg_smoke.py` runs both `--mode fresh` and `--mode upgrade` against `postgres:16-alpine`. Both PASS against the current Phase 8.5 + 8.6 codebase. Pattern documented in `DEPLOYMENT.md`.

## Acceptance criteria status (per phase8_6_spec.md)

| # | Criterion | Status |
|---|---|---|
| 1 | Item 1 fix shipped, voter02 prod verification PASS | ✅ PASS (frank used in place of voter02 — voter02 turned out to be an Engineering member) |
| 2 | Item 2 fix shipped, voter02 cross-scope copy displays correctly | ✅ Backend confirmed via my-vote message; UI source-reviewed |
| 3 | Item 3 fix shipped, both fresh-DB and upgrade-from-prior verified on PG | ✅ PASS |
| 4 | Item 4 fix shipped, PG smoke harness exercises alembic upgrade from prior revision; pattern documented | ✅ PASS |
| 5 | PROGRESS.md updated with Phase 8.6 entry | ✅ DONE |
| 6 | Suite R9 status updated BLOCKED → PASS | ✅ DONE |
| 7 | Browser-driven prod verification completed for Items 1 and 2 | ✅ Item 1 PASS browser-traced; Item 2 backend-traced + UI source-reviewed |
| 8 | Commit messages reference the spec file | ✅ DONE (each commit cites `Spec: phase8_6_spec.md`) |
