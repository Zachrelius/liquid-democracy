# Phase 45b — Opt-In Ownerless Governance (Flat Admin Council)

**Type:** Standard-to-meaty implementation pass. New per-org setting + mode-aware permission/cardinality logic + recovery state + FE controls. **Likely one migration** (a governance-mode field + possibly a recovery-state flag — confirm during impl; see B1).
**Branch:** `phase-45b/governance-modes` → `git merge --no-ff` to master.
**Dispatch prompt (one line):** `Read and execute phase45b_governance_modes_spec.md`

> **Provenance & sequence.** This is the foundation pass of the elected-leadership end-state. End state (locked with Z): **an org chooses its governance model — flat admin council (A) or elected leadership (B) — as opt-in configuration; both are first-class, neither is "the" answer.** Model B is structurally A-plus-elections: an org running elected leadership is, underneath, an org in distributed-authority mode whose seats happen to be filled by election. So A is not a lesser alternative to B — it is the substrate B runs on. This pass builds A. Elections (B) are **Phase 45c**; recall + refinements are **Phase 45d**.
>
> Depends on Phase 45a (steward recovery + voluntary handoff) having landed — 45a made the *person* holding a governance seat reassignable; 45b makes the *single-steward seat itself* optional. Do not start until 45a is merged.

---

## Status

Spec-ready. Conceptual decisions locked below (D1–D6). One decision (D4 — who holds steward-only powers when there is no steward) was made by the planning agent as it follows directly from the locked principles; flagged explicitly so Z can override.

---

## Why this pass

Today every org has exactly one steward, and after Phase 45a that steward is reassignable but still **mandatory** — the at-least-one-steward invariant is a hard floor. That's correct as a *default*, but the platform's philosophy is that orgs self-determine how they're governed. Some orgs don't want a single top officer; they want to run on a council of co-equal admins with no single point of failure (and, later via 45c, to *elect* that leadership).

The Phase 45 recon established that the permission layer is already most of the way there: `admin` and `steward` are interchangeable at nearly every gate (`_ADMIN_TIER_SYSTEM_KEYS = ("admin", "steward")`). So this pass is less "build a new power structure" and more "let an org formally operate without the single-steward seat, safely, with a recovery path if the council evaporates too."

**This is opt-in and off by default. Orgs that never touch the setting behave exactly as they do today** (single steward, all 45a guarantees intact). The blast radius is scoped to orgs that deliberately switch modes.

---

## The governance-mode model

Introduce a per-org **governance mode** with (initially) two values:

- **`single_steward`** (default — today's behavior): exactly one steward always exists; the 45a at-least-one-steward floor applies; `org.delete` + `org.transfer_stewardship` are steward-only.
- **`admin_council`** (opt-in, this pass): no steward seat required; governing authority is held collectively by the admin tier; the cardinality floor becomes **at-least-one-admin**; the steward-only powers vest in the admin tier (see D4).

A third conceptual state is **not a mode but a recovery condition** — `needs_rebootstrap` — see B4. It's the audited "the council evaporated" state that replaces silent lockout.

> **Forward-compat note for 45c:** electing leadership does not add a *third* mode. An org running elected stewards is in `single_steward` mode with the seat filled by election; an org running an elected council is in `admin_council` mode with seats filled by election. 45c layers a *seat-filling mechanism* onto these modes; it does not introduce a new mode. Keep the mode field and the election concern orthogonal.

---

## Locked decisions

**D1 — Mode switch is steward-initiated, steward's call alone, no approval gate.**
Switching governance models is consequential, but a steward can already unilaterally *delete the entire org* — renouncing/distributing their own power is strictly less dramatic than annihilating the org, so gating it harder would be incoherent. The steward flips the switch alone. (Actions *within* `admin_council` mode still route through Phase 44 multi-admin approval when the org has that enabled — but the act of switching modes is not itself gated.)

> **Calibration anchor for the whole arc:** any governance-restructuring action is bounded above by "can delete the org." Do not over-gate actions that are less severe than deletion.

**D2 — On switching to `admin_council`, the sitting steward demotes to admin.**
They join the council as a co-equal, not forced to leave. Consistent with the 45a handoff decision. The switch is an atomic role change (steward → admin) plus the mode flip, in one transaction. After the switch there is no steward and at least one admin (the former steward), satisfying the new floor.

**D3 — The mode switch is bidirectional (reversible).**
An org in `admin_council` mode can revert to `single_steward`: one of the admins claims the steward seat (admin → steward promotion), and the mode flips back. This is the same machinery as 45a's transfer-stewardship (an admin→steward role write). Without reversibility, "ownerless" is a one-way door and an org that tried it and disliked it would be stuck. Who can initiate the revert: any admin (they are the governing tier in council mode); route through Phase 44 if enabled. The revert must satisfy the `single_steward` floor on completion (exactly one steward exists afterward).

**D4 — In `admin_council` mode, the steward-only powers vest in the admin tier. (Planning-agent call — Z may override.)**
`org.delete` and `org.transfer_stewardship` are hardcoded steward-only today (`OWNER_ONLY_KEYS`). In `admin_council` mode there is no steward, so these must resolve to **any admin** (mirroring how a single steward can do them alone in default mode), with Phase 44 multi-admin approval as the opt-in extra protection an org can layer on. Rationale: admins are the governing tier in this mode; the "less dramatic than delete" principle; and the existing admin-tier symmetry. `org.transfer_stewardship` in council mode is effectively "an admin claims the steward seat" = the D3 revert. **If Z prefers these high-stakes powers to *require* Phase 44 approval in council mode rather than merely allow it, that's a one-line policy change — flag at review.**

**D5 — Self-lockout protection follows the mode.**
Today three permissions (`member.change_role`, `org.edit_settings`, `role_permissions.edit`) are hardcoded TRUE for the steward as anti-self-lockout protection (`STEWARD_LOCKED_PERMISSIONS`). In `admin_council` mode there is no steward to hold these, so the same protection must be guaranteed for the **admin tier** — otherwise council mode reintroduces exactly the self-lockout risk the recon flagged. The at-least-one-admin floor (D6) plus admin-held locked permissions together guarantee a council-mode org can always re-govern itself.

**D6 — The cardinality floor is mode-dependent, and is never zero.**
- `single_steward` mode: at-least-one-steward (the 45a invariant, unchanged).
- `admin_council` mode: at-least-one-admin. Every path that could remove/demote the last admin in council mode is blocked, exactly as the last steward is protected in default mode.
- Neither mode can reach zero governors through normal operation. The only path to a govern­or-less org is catastrophic (e.g., all admin accounts independently soft-revoked by the platform), which is what the recovery state (B4) exists to catch.

---

## What IS in scope

- **B1 — Governance-mode field + migration.** Add the per-org governance mode (`single_steward` | `admin_council`), defaulting to `single_steward` for every existing and new org so behavior is unchanged until opted in. Likely a column on `Organization` (or a structured key in `Organization.settings` if the team judges that cleaner and migration-free — but a first-class column is preferred for query-ability and because mode gates permission logic on the hot path). If a column: reversible migration + cycle test + PG smoke per CLAUDE.md. Confirm the choice in the closeout.
- **B2 — Mode switch endpoints (both directions).** `single_steward → admin_council` (D1/D2: steward-initiated, demotes self to admin, atomic). `admin_council → single_steward` (D3: admin-initiated, names the admin who claims the steward seat, atomic, Phase 44 if enabled). Audit events `org.governance_mode_changed` with from/to + the role reassignment recorded.
- **B3 — Mode-aware permission + cardinality logic.** Centralize the floor logic introduced in 45a so it becomes mode-driven (D6): the same helper answers "can this role-removal/demotion proceed?" by consulting the org's mode. D4 (owner-only keys vest in admin tier when council) and D5 (locked permissions follow the mode) implemented in `role_permissions.py` alongside the existing `OWNER_ONLY_KEYS` / `STEWARD_LOCKED_PERMISSIONS` handling — extend, don't fork. Keep it readable; 45c will read the same mode field.
- **B4 — Recovery / `needs_rebootstrap` state (replaces silent lockout).** Define what happens if a council-mode org loses its last admin (all admin accounts soft-revoked, etc.). Rather than a silent permanent lockout, the org enters an explicit, audited `needs_rebootstrap` condition. Minimum viable for this pass: (a) detect the zero-governor condition, (b) record it (audit event `org.needs_rebootstrap`), (c) define the recovery actor — platform-admin (`User.is_admin`) can re-seat a governor, which is a safe backstop that already exists as a separate tier and does not collide with org-internal roles. A nightly/scheduled check that flags at-risk orgs (a council down to its last admin, or a single-steward org whose sole steward is inactive) is **valuable but optional** for this pass — include if cheap, defer with a note if not. Do NOT build a full self-service re-bootstrap UI here; the platform-admin backstop + audit visibility is the floor. Richer re-bootstrap is a later refinement.
- **B5 — Tests.** Mode default is `single_steward` for new + migrated orgs (regression: untouched orgs behave exactly as 45a left them). Switch to council demotes steward to admin atomically. Council-mode at-least-one-admin floor holds against every removal/demotion path. Revert to single_steward produces exactly one steward. Owner-only keys resolve to any-admin in council mode (D4). Locked permissions held by admin tier in council mode (D5). Phase 44 path: mode-switch is NOT gated (D1) but in-mode high-stakes actions still defer when enabled. Recovery state: zero-governor condition is detected + audited, not a silent lockout; platform-admin can re-seat. **Assert side effects** (actual role rows, actual mode field, actual audit rows) — per CLAUDE.md.
- **F1 — Governance-mode UI.** An org-settings control for the steward to switch to council mode (with a clear, slightly-heavy confirmation explaining the consequence: "you will become an admin; the org will run on its admin council; no single steward"). And the reverse control for admins in council mode to revert (pick who becomes steward). Gate visibility on the appropriate permission/mode. Keep copy human and non-alarming but honest — this is a deliberate, reversible choice.
- **F2 — Mode-aware admin UI.** Anywhere the FE currently assumes a steward exists (the 45a F1 work un-hardcoded the delete-org check; sweep for siblings) must render correctly in council mode — e.g., a "transfer stewardship" control makes no sense when there's no steward; show the mode-appropriate control instead. Catalog and fix the steward-assuming FE surfaces flagged in the recon's GAP-5 / CONVENIENCE FE list that are now reachable in council mode.

---

## What IS NOT in scope (deferred)

- **Elections / auto-granting roles via a vote — Phase 45c.** This pass fills/changes seats by *appointment* (the steward switches mode, an admin claims the seat on revert). Filling seats by *election* is 45c. 45b must leave the mode field + role-assignment paths clean enough that 45c can write election winners into them without a rewrite.
- **Recall — Phase 45d.**
- **Fixed terms / scheduled re-elections.** See forward-notes; a 45c+ concern.
- **Full self-service re-bootstrap UI.** B4 ships the platform-admin backstop + audit visibility; richer flows are a later refinement.
- **A third governance mode.** Two modes only. Elected variants are seat-filling mechanisms over these two modes, not new modes.

---

## Forward dependencies & notes (NOT work for this pass)

**For Phase 45c (elections) — decisions already locked with Z, recorded here so 45c inherits them:**
- Elections are **org-configurable**: an org chooses whether to elect at all, and for which seats — **steward and/or admins**. Works in both governance modes.
- **Winning auto-grants the role** when the vote closes — binding, no ratification step. (The non-binding "run a proposal, admin assigns roles manually" path already exists today; do not rebuild it.)
- **Elections are proposals** — they run through the existing voting engine; all members vote, same eligibility model as any proposal. When the ID-verification pass lands its verified-member tier, elections inherit the option to gate behind verification automatically (because they *are* proposals) — not 45c scope, just inherited capability.
- **Term/trigger (3a):** default behavior is **"elected until a new election is called"** (the more liquid-democracy posture — a seat's holder can be challenged any time by calling an election). Fixed terms are an **optional, configurable-later** addition (more traditional-democracy feel). Default ships without a scheduler dependency and without a leaderless gap (incumbent holds until a replacement actually wins).
- **Slate behavior (3b):** for multi-seat (council) elections, whether an election **refreshes the whole slate** (all elected seats up at once) or **fills specific vacancies / adds members** is **org- AND proposal-configurable** — the election proposal itself declares which mode it runs in. Reuses the existing multi-winner voting (`num_winners` / ranked-choice).

**For future leave-org / delete-account flows (carried from 45a):** must guard against a sole governor self-stranding the org in *either* mode (sole steward in default mode; last admin in council mode). Reuse the mode-aware floor (B3).

---

## Verification matrix

| Check | Required | Notes |
|---|---|---|
| Backend pytest (full) | Yes | Baseline per the 45a closeout (45a adds tests above the 1564/28 Phase 44 baseline; use 45a's reported count as the new baseline). Report delta. |
| Default-mode regression | Yes | **Load-bearing.** Orgs that never switch mode behave byte-for-byte as 45a left them: single steward, all 45a floors + guards intact. The opt-in must be truly opt-in. |
| Migration reversible + cycle test | If a column is added | Per CLAUDE.md. If mode lives in `settings` JSON instead, state "no migration" and justify. |
| PG smoke | If migration added | `pg_smoke.py --mode both --prior-revision <id>` — prior revision is the latest in `backend/migrations/versions/` at branch-cut (note: 45a added none if it held to "no migration"; confirm the chain). |
| Council-mode at-least-one-admin floor | Yes | Explicit tests against every removal/demotion path. |
| Mode switch atomicity (both directions) | Yes | Steward→admin demotion + mode flip in one transaction; revert produces exactly one steward. |
| Owner-only keys + locked perms in council mode (D4/D5) | Yes | Tested. |
| Recovery state (B4) | Yes | Zero-governor condition detected + audited (not silent); platform-admin re-seat works. |
| Frontend build | Yes | New bundle hash. |
| Browser verification (Chrome MCP, prod) per CLAUDE.md | Yes | (1) Steward switches org to council mode → becomes admin, no-steward state renders correctly; (2) admin reverts → claims steward seat; (3) a default-mode org's admin screens are visually unchanged. |
| Bundle hash changed + backend non-502 post-deploy | Yes | Standard. |

---

## Suggested team structure

**Continuing dev team or the Phase 44 team.** This extends the same permission/role surface 45a touched and integrates with Phase 44's approval engine (D1's in-mode actions, D4's optional gating, D3's revert) — codebase context wins, and the Phase 44 team owns the `PendingAdminAction` machinery. This is a build/refactor pass, not a fresh-eyes audit.

Default four roles: lead (delegate, writes closeout), backend dev (B1–B4 + B5), frontend dev (F1–F2, browser-verifies own UI), QA (prod browser verification of both switch directions + default-mode-unchanged check).

---

## Closeout reporting

Standard shape, plus:
- Confirm default-mode regression: untouched orgs behave exactly as 45a left them.
- State whether governance mode is a column (migration) or a settings key (no migration), and why.
- Confirm the mode-dependent floor (D6) is centralized and tested on every path.
- Confirm D4/D5 behavior in council mode, and whether Z's optional "require Phase 44 for owner-only keys in council mode" toggle was implemented or left as allow-any-admin.
- Describe the B4 recovery state: what's detected, what's audited, who can re-seat, and whether the optional scheduled at-risk check was included or deferred.
- Test count delta; migration/PG-smoke status.
- Browser verification results for both switch directions.
- Any new tech debt — especially anything that will shape Phase 45c (the election layer reads this pass's mode field + role-assignment paths).

---

## Notes for the team

- **Opt-in is the entire safety story.** A default-mode org must be indistinguishable from its pre-45b self. Every mode-aware branch is `if mode == admin_council: ... else: <today's behavior>`.
- **Two modes, not three.** `needs_rebootstrap` is a recovery *condition*, not a governance mode. Elected variants (45c) are seat-filling mechanisms over the two modes, not new modes. Keep the mode field small and orthogonal to the election concern.
- **The floor is the load-bearing invariant.** Default mode: ≥1 steward. Council mode: ≥1 admin. Never zero governors via normal operation. Centralize it (45a started this; make it mode-driven, don't smear it across call sites — 45c will read it too).
- **Reuse, don't fork.** D4/D5 extend the existing `OWNER_ONLY_KEYS` / `STEWARD_LOCKED_PERMISSIONS` handling in `role_permissions.py`. The revert (D3) reuses 45a's admin→steward role-write. The in-mode high-stakes gating reuses Phase 44. This pass is mostly *making existing machinery mode-aware*, not building new machinery.
