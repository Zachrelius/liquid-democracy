# Phase 45 — Ownerless-Readiness Recon Findings (2026-05-31)

**Pass type:** Read-only investigation (Pass A audit). No code changes.
**Spec:** `phase45_ownerless_recon_spec.md`
**Branch:** `phase-45/ownerless-recon`
**Baseline at branch-cut:** master @ `06fb6fe`, backend tests 1564 PASS / 28 FAIL.

The arc framing under which every finding below is bucketed:
**target = "make steward-dependence removable + add a recovery safety net"** — NOT "rip the steward out." Stewards stay; steward-*dependence* is what we audit.

---

## 1. Executive summary

**Headline counts:**
- **GAP:** 4 (backend) + 1 (frontend role-string fragility, advisory) — call it **5 sites total**, of which **2 are critical lockout vectors**.
- **CONVENIENCE:** 4 backend + ~6 frontend role-check call sites (all admin-tier symmetric or correctly protective).
- **OPT-IN-SURFACE:** 3 design questions.

**The single most dangerous GAP — and a live latent bug a real org can hit today:**
A solo steward whose account is soft-revoked (`User.is_active = False`, added Phase 39 B1) becomes structurally unreachable AND irremovable. `_get_user_from_token` (`backend/auth.py:56-58`) rejects inactive users, so the steward cannot log in to transfer power. The removal guard (`backend/routes/organizations.py:791-792`) blocks any admin from removing them ("Cannot remove the Steward") regardless of `is_active`. The `org.transfer_stewardship` permission key is declared but **no endpoint implements it** — there is no API surface for stewardship handoff at all today. Net effect: the org is permanently ungovernable via the API; only direct DB mutation by Z can recover it. This isn't a future-Pass-A problem; it's a real production latent bug.

**Is Pass A one pass or several?**
**Split. Recommend three deploys.** Detailed reasoning in §7, summary:
- **Pass A0 (hotfix, 1 commit):** Relax the steward-removal guard to allow removal when `User.is_active == False`. Independently shippable in a session. Closes the live latent lockout. **Recommend doing this *before* the rest of Pass A so we're not knowingly carrying a recovery deadlock for the weeks the broader design takes.**
- **Pass A1 (standard pass, ~4-6 clusters):** Implement the missing `org.transfer_stewardship` endpoint and a steward-cardinality-aware removal/transfer guard. Adds the "voluntary handoff" path that today doesn't exist at all.
- **Pass A2 (Greater-Phase-sized, may further split):** The opt-in ownerless mode, recovery state machine ("needs re-bootstrapping"), elected-board design surface. This is where the new schema + opt-in feature flag + recovery UI live.

**Steward-cardinality model in one line:** No cardinality is enforced anywhere — orgs are created with exactly one steward, the system protects that steward from removal/demotion, and there is no API path to add a second steward or replace the first. *De facto* the model is "exactly one steward, immutable" — and that *de-facto* exact-one constraint is what makes the soft-revoke case a permanent lockout.

---

## 2. Steward-cardinality model

**Enforced cardinality: none. *De-facto* cardinality: exactly one, immutable post-creation.**

- **Creation** (`backend/routes/organizations.py::create_organization` ~L394-400): founder is assigned `role_id = roles_by_key["steward"]`. Always exactly one steward at create time.
- **Demotion** (`backend/routes/organizations.py::change_member_role` L701-729): steward role-change is blocked by an explicit guard ("Cannot change Steward role"). The current steward cannot be demoted to a lower role at all.
- **Removal** (`backend/routes/organizations.py::remove_member` L790-792, mirrored in `backend/pending_actions/registry.py::execute_member_remove` L271-273): "Cannot remove the Steward" — unconditional on `system_key`, with no escape for inactive/soft-revoked users.
- **Transfer**: the `org.transfer_stewardship` permission key is **declared** in `OWNER_ONLY_KEYS` and referenced in three module docstrings, but **no route handler exists**. Grep across `backend/routes/` finds zero implementations. The tests (`backend/tests/test_role_permissions.py:365-389`) only assert the permission gate, not a routing surface.
- **No schema constraint** enforces "at least one steward" or prevents "two stewards." The system relies entirely on access control (the role-change + removal guards), not on database invariants.

This combination — **created with one, protected from demotion, protected from removal, no transfer surface** — is what turns a soft-revoke into a permanent lockout. The cardinality is "exactly one steward" by *de-facto* invariant, with no recovery path if that one steward becomes unreachable.

**Implication for Pass A design:** the cardinality decision is the load-bearing one. Three options surface from the recon:
- (a) Stay at exactly-one-steward; add transfer + inactive-steward-removal. Simplest. Doesn't unlock ownerless mode.
- (b) Allow zero-to-many stewards; add transfer; treat "no steward" as a valid opt-in state. Unlocks ownerless. Largest design surface (every guard needs review).
- (c) Allow exactly-one-steward in default mode, zero-stewards-allowed only behind an opt-in `org.allow_ownerless` setting. Splits the risk: default-path orgs are unchanged; only opt-in orgs see the new surface. Recommended starting point for the §7 split.

---

## 3. GAP register

### GAP-1 — `org.transfer_stewardship` is declared but has no endpoint (CRITICAL — recovery deadlock)

- **Location:** `backend/role_permissions.py:60` (`OWNER_ONLY_KEYS = {"org.delete", "org.transfer_stewardship"}`); referenced in `backend/org_middleware.py:212` + `backend/permission_registry.py:23` + `backend/role_permissions.py:19, 210, 455`; tested for permission resolution in `backend/tests/test_role_permissions.py:365-389`. **No route handler implements it.** Confirmed by direct grep — no `@router.post(".../transfer-stewardship")` or equivalent.
- **What breaks:** stewards cannot hand off the role even voluntarily. The permission gate exists, but there is nothing it gates.
- **Trigger scenario:** any org founder who eventually wants to step down. Today this is structurally impossible via the API.
- **Severity:** **locks org governance handoff entirely**. Combined with GAP-2, makes lockout permanent.
- **Fix sketch:** `POST /api/orgs/{slug}/transfer-stewardship` with `{target_user_id}`. Atomic: current steward → admin (or whatever the prior role was), target → steward. Wrapping in Phase 44 `PendingAdminAction` for multi-admin approval is a forward note — initial implementation can be steward-only initiation. Need a decision (Pass A1 spec) on whether admins can also initiate (recovery path; necessary for opt-in mode).

### GAP-2 — Removal guard blocks even soft-revoked stewards (CRITICAL — live latent bug)

- **Location:** `backend/routes/organizations.py:790-792` and mirrored at `backend/pending_actions/registry.py:271-273`. Guard fires on `membership_role_system_key(m) == "steward"` unconditionally — does NOT check `User.is_active`.
- **What breaks:** if a steward's account is soft-revoked (Phase 39 B1 — `User.is_active = False`), they are simultaneously (a) unreachable via login (`backend/auth.py:56-58` filters `is_active == True`) and (b) un-removable by any admin. No transfer endpoint exists (GAP-1). Combined effect: permanent org lockout.
- **Trigger scenario:** any real org with a solo steward whose account is revoked for any reason — ToS violation, security incident, account compromise, user requests deletion. Phase 39 B1 was shipped to *enable* this kind of revocation; the steward-removal guard predates it (Phase 12) and was never updated.
- **Severity:** **locks org permanently via API**. Recovery requires direct DB mutation by Z. **This is a live production latent bug, not a future-Pass-A concern.**
- **Fix sketch:**
  ```python
  if membership_role_system_key(m) == "steward":
      user = db.get(models.User, m.user_id)
      if user and user.is_active:
          raise HTTPException(status_code=400, detail="Cannot remove the Steward")
      # else: steward account is inactive → allow removal so an admin can recover the org.
  ```
  Apply to both `routes/organizations.py:remove_member` and `pending_actions/registry.py::execute_member_remove`. Emit an audit event on the inactive-steward path (`steward.removed_while_inactive`) so the asymmetry is visible. **Recommend hotfix BEFORE the rest of Pass A.**

### GAP-3 — Sub-orgs strand when parent steward goes dark (STRANDS SUB-ORGS, secondary to GAP-1/2)

- **Location:** Parent-org governance dependency chain: `backend/role_permissions.py::effective_role_on_sub_org` (L347-438), `backend/role_permissions.py::role_transfers_to_sub_orgs` (L287-329).
- **What breaks (nuanced):** Sub-orgs themselves continue to *function* day-to-day even if the parent's sole steward goes dark — admin-tier transfers ON by default (and steward-tier transfers ON unconditionally per L320), so a parent-org admin can still operate on sub-orgs. **BUT** the parent org itself is locked (GAP-1 + GAP-2), so any governance mutation that flows through the parent (sub-org deletion, restructuring, transferability changes) is frozen. Sub-org users are along for the ride.
- **Trigger scenario:** any org with sub-orgs whose parent hits the GAP-2 lockout.
- **Severity:** **partial strand** — reads work, day-to-day writes work, governance restructuring is frozen.
- **Fix sketch:** mostly inherits from GAP-1/2 fixes (recovering the parent unblocks the sub-orgs). The deeper "sub-org carve-off when parent unrecoverable" question is Pass A2 design surface — not needed today if GAP-1/2 are addressed.

### GAP-4 — Cardinality drift becomes possible once transfer is added (DESIGN GAP, latent on GAP-1 fix)

- **Location:** `backend/routes/organizations.py:701-729` (`change_member_role` — protects existing steward) + the not-yet-existent transfer endpoint (GAP-1).
- **What breaks:** today the de-facto exact-one-steward invariant holds *because* there is no path to demote. If GAP-1's fix lets stewards transfer + the existing role-change guard is relaxed to permit post-transfer demotion, a sequence could leave zero stewards: User A transfers to B → B is removed → org has zero stewards. Whether that's a *bug* depends on whether the opt-in ownerless mode is enabled.
- **Severity:** **GAP (needs design call)** — not a bug today, becomes one when transfer is wired up.
- **Fix sketch:** the transfer endpoint should check cardinality based on org setting. Default-path orgs: enforce "at least one steward must remain" (transfer is atomic role-swap, not demotion-leaving-vacuum). Opt-in ownerless orgs: allow zero stewards but enforce "at least one active admin" as the floor.

### GAP-5 — Frontend `isSteward` hardcoded role-string check on delete (ADVISORY, FE)

- **Location:** `frontend/src/pages/admin/OrgSettings.jsx:199` — `const isSteward = currentOrg?.user_role === 'steward';`. Gates the Danger Zone (delete-org) UI. Contrast: every other admin control on the page uses `useHasPermission(...)` (Phase 12.5 / 12.6 refactor convention).
- **What breaks:** not a *runtime* break today — the backend `org.delete` permission gate is still authoritative — but the FE's role-string check will silently misbehave in any future scenario where `org.delete` is delegable to admins (e.g., the opt-in ownerless mode where there may be no steward at all). The Danger Zone simply won't render even when the user has the permission.
- **Severity:** **CONVENIENCE-leaning-GAP** — backend stays correct, but the UI assumes a steward exists to operate it.
- **Fix sketch:** swap to `useHasPermission('org.delete')`. One-line. Worth bundling with Pass A1 since the surrounding work touches the same area.

---

## 4. CONVENIENCE register

Sites where steward is privileged but not load-bearing for "the org keeps functioning":

- **`_ADMIN_TIER_SYSTEM_KEYS = ("admin", "steward")` in `backend/permissions.py` and `backend/eligibility.py:23`** — admin and steward are interchangeable for admin-tier checks. **This is the main reason GAP-2's fix is sufficient for most of Z's "any current admin keeps things running" sketch.** Verified no contradicting steward-only gate.
- **`change_member_role` blocks demoting an existing steward** (`backend/routes/organizations.py:721`) — correct by design; the two-step flow (must transfer or remove, not demote) prevents accidents.
- **`pending_actions/registry.py` member-removal validate + execute paths** check `system_key == "steward"` symmetrically — safe pattern.
- **Platform-admin (`User.is_admin`) is never consulted for org-internal permission checks** (`backend/role_permissions.py:415-419` is the only fallback site, sub-org only). The platform-admin tier is a *completely separate* tier from org-steward — they can't collide.
- **FE OrgContext.jsx `isAdmin = (steward || admin || owner)`** (legacy `owner` is back-compat string from Phase 12 Stage 1 cutover) — admin-tier symmetric, no steward bias.
- **FE Nav.jsx admin-dropdown gating is permission-driven** (Phase 12.5 F1 / 12.6 G2 refactor), not role-tier. Phase 45 ready.
- **FE Members.jsx protects steward rows from being expanded/edited in the UI** — correct mirror of backend invariant; consistent with the cardinality model.
- **FE OrgSelector.jsx normalizes `'owner' → 'steward'` for display** — back-compat detail.

---

## 5. OPT-IN-SURFACE register

Design questions Pass A2 (or later) must answer; not bugs today:

- **OPT-IN-1 — Cardinality policy under opt-in ownerless mode.** Default-path orgs stay at exactly-one-steward. What does an "ownerless" org enforce? "Zero stewards OK, but at-least-one active admin"? "Zero stewards + at-least-one ratified board member"? Recommend the floor be "at-least-one user holding the admin-tier permissions" so the chain in §6 holds.
- **OPT-IN-2 — Who initiates `org.transfer_stewardship` when no steward exists?** Steward-only initiation works in default mode. In opt-in ownerless mode (or as a recovery path even in default mode), admins must be able to initiate. The simplest split: keep steward-only as the privileged path; add an admin-tier path that requires Phase 44 multi-admin approval. The `PendingAdminAction` registry already exists and was built for exactly this shape of "needs more than one admin to confirm" action.
- **OPT-IN-3 — Sub-org governance when parent is in opt-in ownerless mode.** Current code: `role_transfers_to_sub_orgs` locks steward transferability ON unconditionally (`backend/role_permissions.py:320`). If a parent has no steward by design, the lock-ON is moot. Verify the resolver behavior is sane in that case (fallback path is platform-admin at L416-419, which is safe). Likely no code change; needs a test.

---

## 6. The recovery/succession chain — pressure-tested against the codebase

Z's cowork-session sketch:
> elected board holds the authority → if board empty/expired, any current admin → if no admins at all, an explicit audited "org needs re-bootstrapping" state rather than silent lockout.

**How the existing code maps to that chain:**

| Sketch tier | Code today | Status |
|---|---|---|
| Elected board holds authority | Not modeled. No election system, no term tracking. | Pass A2+ design surface. |
| Any current admin can keep things running | `_ADMIN_TIER_SYSTEM_KEYS = ("admin", "steward")` — admin and steward are interchangeable at every gate I checked. 27/27 permissions default-granted to both. | **Already true.** This is the biggest win the existing code gives us. |
| If no admins at all, audited "needs re-bootstrapping" | No flag, no state, no audit event. | Pass A2 design surface — possibly an `org.governance_state` column with values `default | needs_rebootstrap | ownerless_active`. |

**Where the chain breaks today, before any of the above design is wired up:**

1. **The chain ruptures at "steward becomes unreachable but is still in the role."** This is GAP-1 + GAP-2. The "any admin keeps things running" tier is *almost* there at the permission layer, but the lockout-on-removal guard prevents admins from even cleaning up the steward row to fully take over. GAP-2's one-line fix closes this — it's the highest-leverage change in the entire arc.
2. **The chain has no detection.** Even if no admins remain in an org, the system has no way to know — there's no nightly check, no audit event, no alert. Z would only find out if a user reports it.

**Minimum viable safety net (Pass A0 + A1, no opt-in yet):**
- Fix GAP-2 (one-line removal guard relaxation) → an admin can remove an unreachable steward.
- Fix GAP-1 (add transfer endpoint) → an active steward can hand off voluntarily; an admin can take over after removing an unreachable steward.
- Optional but valuable: emit a WARN audit event when `User.is_active` is set False on a user holding a steward role anywhere, so monitoring can flag at-risk orgs.

That minimum viable safety net is **shippable independently of the elected-leadership arc** and closes the live latent bug. The full elected-board design (Pass A2+) layers on top.

---

## 7. Pass A sizing + split recommendation

Applying the project's pass-sizing heuristic (`>5 clusters + >50 new tests + novel infra + a migration ⇒ Greater-Phase-sized, must split`):

**Pass A as a single pass** would need to include: relax removal guard (1 cluster), transfer-stewardship endpoint + permission wrapper + tests (1-2 clusters), cardinality enforcement under opt-in (1 cluster), opt-in feature flag column + migration (1 cluster), recovery/re-bootstrapping state (1-2 clusters), audit event emission for steward soft-revoke (1 cluster), FE delete-org un-hardcoding + transfer UI + opt-in toggle (2-3 clusters), elected-board scaffolding (deferred but pressures design). That's **6-9 clusters, novel state machine, at least one migration, easily 50+ tests**. Triggers the split rule.

**Recommended split:**

| Pass | Scope | Size | Independence |
|---|---|---|---|
| **A0 (hotfix)** | GAP-2 only: relax removal guard for inactive stewards. 1 backend file + 1 mirror in pending_actions + ~3 tests + audit event. | 1 commit, ~30 min. | Independent of everything else. Recommended *immediately*. |
| **A1** | GAP-1: implement `org.transfer_stewardship` endpoint. GAP-4: add cardinality guard in transfer. GAP-5: FE delete-org un-hardcoding. Phase 44 `PendingAdminAction` wrapping for admin-initiated transfers (recovery path). | Standard pass, 4-6 clusters, ~30-40 tests. | Depends on A0 (logically, not technically). |
| **A2** | The opt-in ownerless mode itself: `org.allow_ownerless` setting, opt-in cardinality policy, recovery/re-bootstrapping state, monitoring. | Greater-Phase-sized; likely splits further into A2a (opt-in flag + cardinality), A2b (recovery state), A2c (FE opt-in UI). | Depends on A1. |
| **B/C (out of recon scope)** | Elections, recall, ratification. Reuses A1's `PendingAdminAction` integration as the approval substrate. | Per the spec, out of scope. |

**Why this shape rather than one pass:**
- A0 closes a *live production latent bug* and shouldn't wait on the design conversation for A2. The fix is mechanical and well-understood; the design risk is zero.
- A1 establishes the missing primitive (transfer) without committing to the opt-in design. Useful on its own — voluntary handoff is a real user need separate from ownerless mode.
- A2 is where the design uncertainty lives. Splitting it after A0+A1 means the broader arc can move at design speed without holding up the bug fix.

---

## 8. Phase 4c multi-tenancy debt check

**No new Phase 4c debt found.** All steward-assumption code I traced is properly org-scoped:
- Permission checks join through `OrgMembership.org_id`.
- Steward role is seeded *per-org* in `backend/role_seed.py::seed_default_roles_for_org(db, org_id)`.
- Removal/role-change guards operate on `(org_id, user_id)` tuples.
- No cross-org leakage detected in the steward path.

The Phase 4c retrofit (closed at Phase 18) covered the relationship tables; the role/permission/membership tables were always org-scoped from earlier passes. This recon found nothing that traces back to that pattern.

---

## Search log (auditable coverage)

Backend (Explore agent):
```
grep -rn 'steward' backend/ --include="*.py"                      # ~150 hits
grep -rn 'OWNER_ONLY\|STEWARD_LOCKED\|require_org_owner' backend/ # ~30 hits
grep -rn 'org.transfer_stewardship\|transfer_stewardship' backend/  # 10 hits (all refs; no impl)
grep -rn 'is_active\|_get_user_from_token' backend/auth.py        # confirmed L56-58 filter
grep -rn 'cannot.*remove.*steward\|steward.*cannot' backend/ -i   # ~15 guards
grep -rn 'count.*steward\|steward.*count' backend/ -i             # 0 (no cardinality enforcement)
```

Frontend (Explore agent):
```
grep -rn 'steward' frontend/src/                                  # 20 files
grep -rn 'isSteward\|isOwner' frontend/src/                       # 4 files
grep -rn 'system_key' frontend/src/                               # 2 files
grep -rn 'transferStewardship\|transfer.stewardship' frontend/src/  # 1 file (help text only)
grep -rn 'role\s*===\|role\s*==' frontend/src/                    # 7 files
grep -rn 'deleteOrg\|delete.*org\|orgDelete' frontend/src/        # 11 files
```

Direct verification (lead) of the two load-bearing claims:
```
Grep transfer_stewardship in backend/                              # confirmed: declared, no route
Read backend/routes/organizations.py:780-820                       # confirmed: removal guard unconditional on is_active
Read backend/auth.py:50-70                                         # confirmed: is_active filter on token resolution
```

---

## Notes / things bigger or smaller than expected

- **GAP-2 is the headline.** The spec called out `is_active` interaction as "the most likely place a real GAP hides." That intuition was correct — and the GAP is more severe than the spec framed it (it's a live latent bug, not a future-state risk).
- **Transfer endpoint missing entirely was a surprise.** The spec called out `OWNER_ONLY_KEYS` as the "prime suspect for a recovery deadlock" — the recon confirmed that, *and* found that the deadlock is even more total than the spec assumed: there is no transfer endpoint at all. The permission key is declared, three modules reference it in docstrings, tests check the permission gate — but no route implements it.
- **Admin-tier symmetry is real and saves us a lot.** `_ADMIN_TIER_SYSTEM_KEYS = ("admin", "steward")` holding at every gate I checked means most of "any admin keeps things running" is already true at the permission layer. The recovery work isn't "build admin parity"; it's "remove the lockout that prevents admins from exercising the parity they already have."
- **Frontend is lighter than expected.** Most FE gating is permission-driven post-Phase-12.5/12.6 refactors. The one hardcoded role-string check (OrgSettings Danger Zone) is the only meaningful FE surface for Pass A; sub-org Nav shortcut is acknowledged tech debt already.
- **There is no user-initiated "leave org" path** (Z noted in `5-31_Notes.txt` he was unsure if one exists — confirmed it doesn't). A user can have their membership removed by an admin/steward, but cannot self-remove. This narrows the steward-vanishing vectors to: (a) account soft-revoke, (b) account deletion (not investigated separately — likely cascades, worth a future check), (c) membership removal by another admin (blocked by the GAP-2 guard if the target is steward).
