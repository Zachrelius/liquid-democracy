# Phase 45 — Ownerless-Readiness Recon (Pass A audit)

**Type:** Read-only investigation pass. Produces a findings document. **No code changes, no migration, no deploy.**
**Branch:** `phase-45/ownerless-recon` (findings doc only; merged `--no-ff` to master like any pass so the doc is checked in).
**Deliverable:** `phase45_ownerless_recon_findings_2026-05-31.md` at repo root.
**Dispatch prompt (one line):** `Read and execute phase45_ownerless_recon_spec.md`

---

## Goal

This is the recon for **Pass A** of the elected-leadership arc. Pass A's eventual job (a *later* pass — NOT this one) is to make the platform **able to operate without a guaranteed steward**, as an opt-in capability, without disturbing the steward-default path. This pass does not build that. This pass *finds out how big it is* by exhaustively cataloging where the single-steward assumption is wired into the codebase today.

The arc framing (locked with Z, 2026-05-31):

- **Having a steward stays the default and initial state for every newly-created org.** That is not changing. New orgs are created with one steward; that's the normal, expected configuration.
- What Pass A will change is making the steward **non-load-bearing**: the platform must be *able* to operate with governing authority distributed across a role/group, and must **never reach a silent-lockout state** if the steward disappears (leaves, deletes their account, loses access).
- **Ownerless operation and elected leadership are opt-in features** an org turns on. They must not disturb the steward-default path for orgs that never opt in.
- The founding steward is an **onboarding artifact** (whoever happened to create the org on this platform), not necessarily the org's real leader. Pass A removes the assumption that this person must exist forever; it does not remove the steward role.

So the reframe that should guide every classification in this recon: the target is **"make steward-dependence removable + add a recovery safety net,"** NOT "rip the steward out." Most steward behavior is fine. We are hunting specifically for the places where the *absence* of a steward would break the org or trap it.

---

## The central question this recon must answer

> **Where, today, does the code assume a steward will always exist — such that an org could not function, or could not recover, if the steward vanished?**

For every site found, classify it into exactly one of three buckets:

- **GAP (recovery/safety):** absence of a steward here causes a lockout, an unrecoverable state, or a broken core operation with no other actor able to perform it. These are the things Pass A must address. *Highest-value output of this recon.*
- **CONVENIENCE (default-path, leave alone):** steward is privileged here, but the org keeps functioning without one (some other role can do it, or it's non-essential). Pass A can leave these untouched. Record them so we know we considered them.
- **OPT-IN-SURFACE:** a site that won't be a problem for steward-default orgs but will need a defined behavior once the ownerless/elected opt-in exists (e.g., "who holds `org.transfer_stewardship` in an org that has no steward by design?"). These shape the Pass A *design*, not its bug-fix list.

A site mis-bucketed as CONVENIENCE when it's really a GAP is the failure mode that matters most here. When genuinely unsure, mark it **GAP (needs design call)** and explain the uncertainty — do not optimistically downgrade.

---

## Known starting surfaces (not exhaustive — the recon must go wider)

These are seeds, identified by the planning agent. The recon's value is in finding what *isn't* on this list.

**`backend/role_permissions.py` — the core of the assumption:**
- `OWNER_ONLY_KEYS = {"org.delete", "org.transfer_stewardship"}` — gated on `role.system_key == "steward"` and *nothing else*. No steward ⇒ no one can delete the org and **no one can transfer stewardship**. The transfer gate is the prime suspect for a recovery deadlock: if the only path to becoming steward is an existing steward transferring it, a steward-less org can never regain one. Trace this carefully.
- `STEWARD_LOCKED_PERMISSIONS = {"member.change_role", "org.edit_settings", "role_permissions.edit"}` — hardcoded TRUE for the steward role as self-lockout protection. The module's own docstring explains these exist as "the minimum protection against self-lockout." That protection is *built around the assumption that a steward exists*. With no steward, the protection evaporates — is there a residual lockout? Specifically: can a non-steward admin reach these, or does the org freeze?
- `has_permission` resolution steps 2 and 2b (`_user_role_system_key(...) == "steward"`), and the parallel logic in `has_permission_on_sub_org`.

**`backend/permissions.py`:**
- The `_*_ADMIN_TIER_SYSTEM_KEYS = ("admin", "steward")` sets and every consumer. Note these treat admin+steward as interchangeable for *admin-tier* checks — that's a point in favor of "admins can keep things running," but verify it holds everywhere and isn't contradicted by a steward-only gate elsewhere.

**`backend/org_middleware.py`:**
- `require_org_owner` (imported into `routes/organizations.py`) — every route guarded by it is a steward-only route. Enumerate them all and bucket each.
- `membership_role_system_key`, `require_org_admin`, `require_org_moderator_or_admin` for contrast.

**`backend/routes/organizations.py` and `backend/routes/role_permissions_routes.py`:**
- `create_organization` — how the founding steward is assigned at creation (confirms the default-path origin; not a gap, but documents the baseline).
- Every endpoint behind `require_org_owner` or that checks `org.delete` / `org.transfer_stewardship`.
- The member-role-change path: can the *last* steward be demoted/removed, and if so, what state does that leave? Is there a guard preventing removal of the last steward, and if so, does that guard itself become a lockout (can't demote the steward who left the org / went inactive)?

**`backend/role_seed.py`:**
- `PRESET_ROLES` — steward is seeded per-org. Confirm whether anything enforces *exactly one* steward, *at least one* steward, or neither. The cardinality model is load-bearing for Pass A design.

**Member lifecycle interactions (cross-cutting):**
- Phase 39 added `User.is_active` (soft-revocation) and soft-lockout columns. **What happens to an org whose sole steward's account goes inactive / soft-locked / is removed?** Trace `_get_user_from_token` and membership-status interactions. This is exactly the "steward vanishes" scenario and is the most likely place a real GAP hides.
- Is there a user-initiated "leave org" path? (Z noted in `5-31_Notes.txt` he's unsure one exists.) If a steward can leave, that's a vanish vector. If they can't, note that too.
- Account deletion / membership deletion: does anything cascade in a way that strands an org?

**Sub-orgs:**
- Sub-orgs inherit governance via the parent (`effective_role_on_sub_org`, transferability). A sub-org has no independent steward. Does a parent with no steward strand all its sub-orgs? Trace the parent→sub authority dependency for the no-parent-steward case.

**Frontend (lighter touch — backend is where the gaps live):**
- Where does the UI assume a steward exists? (e.g., settings pages that only render for steward, "transfer stewardship" UI, admin nav gating.) Catalog at the level of "which screens/controls are steward-gated," not line-by-line. The point is to know the FE surface Pass A will eventually touch, not to fix it now.

---

## What the findings document must contain

Structure `phase45_ownerless_recon_findings_2026-05-31.md` as:

1. **Executive summary (≤ 1 page).** How many GAP sites, how many CONVENIENCE, how many OPT-IN-SURFACE. The single most dangerous GAP. A first-cut answer to "is Pass A one pass or does it need to split?" with reasoning. Whether any GAP is severe enough to be worth fixing *independently* of the whole elected-leadership arc (a steward-less lockout is a latent bug even for ordinary orgs — if a real org's solo steward deletes their account today, what happens?).

2. **The steward-cardinality model, stated plainly.** Does the system enforce exactly-one / at-least-one / any-number of stewards per org? Where is that enforced or assumed? This single fact shapes the entire Pass A design.

3. **GAP register.** One entry per gap: location (file + symbol/function), what breaks when no steward exists, the trigger scenario (how an org reaches that state), severity (does it lock the org / strand sub-orgs / merely degrade), and a one-line sketch of the *kind* of fix (capability-instead-of-role, succession chain, recovery state) — sketch only, not a spec.

4. **CONVENIENCE register.** Terser. Site + why it's safe to leave.

5. **OPT-IN-SURFACE register.** Sites that need a *defined behavior* under the future opt-in but aren't bugs today. These become the Pass A design questions.

6. **The recovery/succession question, framed for a Z design conversation.** The cowork-session sketch was: elected board holds the authority → if board empty/expired, any current admin → if no admins at all, an explicit audited "org needs re-bootstrapping" state rather than silent lockout. The recon should pressure-test that chain against what it actually found: does the codebase's existing admin-tier model (admin+steward interchangeable in `_*_ADMIN_TIER_SYSTEM_KEYS`) already get us most of "any admin can keep things running"? Where does the chain break? What's the minimum viable safety net vs. the full elected model?

7. **Pass A sizing + split recommendation.** Given the GAP register: is Pass A one deploy or several? Apply the project's pass-sizing heuristic (>5 clusters + >50 new tests + novel infra + a migration ⇒ Greater-Phase-sized, must split). Recommend a concrete split if warranted.

8. **Phase 4c multi-tenancy debt check.** Per the standing project pattern, audit whether any steward-assumption gap traces to incomplete multi-tenancy retrofitting. Flag if so.

---

## Explicit non-goals for this pass

- **No code changes.** Not even "obvious" one-line fixes. If a genuine latent bug is found (e.g., a real lockout an ordinary org could hit today), it goes in the findings as a flagged GAP with a recommended-urgency note — the planning agent decides whether to spin a hotfix. The recon does not fix it inline.
- **No migration, no schema design.** Pass A's data model is a later deliverable. The recon may *note* "this will need a column / table" as part of a fix-sketch, but does not design it.
- **No elections, no recall, no ratification wiring.** Those are Pass B/C. Mentioning how Phase 44's `PendingAdminAction` registry might be reused by the recovery path is in-scope as a *forward note*; building anything is not.
- **No frontend changes.** FE is cataloged, not touched.

---

## Verification matrix

This is a read-only pass, so the matrix is about findings quality, not deploy safety.

| Check | Required | Notes |
|---|---|---|
| Findings doc produced at the named path | Yes | `phase45_ownerless_recon_findings_2026-05-31.md`, repo root. |
| Every known-starting-surface in this spec addressed | Yes | Each seed above appears in one of the registers (or is explicitly noted as "checked, no assumption found"). |
| Backend steward/owner assumption sweep is exhaustive | Yes | Grep-level rigor: `grep -rn 'steward\|OWNER_ONLY\|STEWARD_LOCKED\|require_org_owner\|system_key' backend/` (and equivalents) walked to completion, each hit bucketed. The findings doc lists the search terms used so coverage is auditable. |
| Each GAP has trigger scenario + severity + fix-sketch | Yes | A gap without a "how does an org reach this state" is incomplete. |
| Steward-cardinality model stated | Yes | §2 of the findings doc. |
| Pass A split recommendation with reasoning | Yes | §7. |
| No code / schema / config changed | Yes | `git diff` on merge shows only the findings doc added. Confirm in closeout. |
| Full test suite still green (sanity, since nothing changed) | Yes | Run once to confirm the branch is clean: expect the baseline 1564 PASS / 28 FAIL. Any deviation means something was touched that shouldn't have been. |

---

## Suggested team structure

**Fresh-eyes audit shape, not the standard build team.** This is a "find what we missed" pass — the team-choice heuristic says fresh-instance / the Phase 38 team has real value here (their auth/identity audit instinct caught the `--proxy-headers` gap live since Phase 6.5; this recon is the same shape of work). Recommend:

- **Lead** (delegate mode): coordinates the sweep, owns the findings doc, makes the bucketing calls, writes §1/§2/§6/§7.
- **One backend investigator**: the grep-level exhaustive sweep of `backend/`; populates the GAP/CONVENIENCE/OPT-IN registers with file+symbol precision; traces the "steward vanishes" lifecycle scenarios.
- **One frontend investigator** (lighter load): catalogs the steward-gated FE surface at screen/control granularity.

No QA role needed (nothing deploys). No migration role (no migration).

---

## Closeout reporting

Standard closeout shape, adapted for a recon pass:

- Confirm the findings doc landed and where.
- Headline counts (GAP / CONVENIENCE / OPT-IN-SURFACE) and the single most dangerous GAP.
- The Pass A split recommendation in one or two sentences.
- **Flag explicitly** if any GAP is a latent bug an ordinary steward-default org could hit today (planning agent will decide on an independent hotfix).
- Confirm `git diff` shows only the doc added; confirm test suite still at baseline.
- Branch + merge commit SHAs.
- Any surprises or surfaces that turned out bigger/smaller than the seeds suggested.

---

## Notes for the team

- The arc framing section above is load-bearing context, not throat-clearing. Re-read it before bucketing anything. The most common way to get this recon wrong is to drift toward "remove the steward" when the actual target is "make steward-dependence removable + add a safety net." Stewards stay; steward-*dependence* is what we're auditing.
- When in doubt on a bucket, choose GAP (and say why you're unsure). Optimistic downgrades are the dangerous error.
- This recon's quality is judged on the GAP register: precise locations, real trigger scenarios, honest severity. A long CONVENIENCE list with a thin GAP list is a weaker deliverable than the reverse.
