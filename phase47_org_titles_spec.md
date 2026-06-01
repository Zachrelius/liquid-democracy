# Phase 47 — Org Titles / Offices (decoupled from platform roles)

**Type:** Standard-to-meaty implementation pass. New first-class org concept (titles) + the title↔role binding model + public display surfaces + direct assignment. **One migration** (titles table + assignment records + likely a built-in-title reconciliation).
**Branch:** `phase-47/org-titles` → `git merge --no-ff` to master.
**Dispatch prompt (one line):** `Read and execute phase47_org_titles_spec.md`

> **Provenance & sequence.** Titles are conceptually **upstream** of elections: an election fills a *title*, so the titles concept is built first and elections (now **Phase 48**) consume it. This renumbers the arc tail: **47 titles → 48 elections → 49 scheduled-terms.** The elected-leadership end-state (models A/B, the governance modes from 45b) is unchanged; titles generalize *what a seat is* so that "elect a steward" and "elect a President who also holds steward powers" are the same mechanism.
>
> Read `elected_leadership_arc_passdown_2026-05-31.md` for full arc context. Depends on 45a/45b (role reassignment + governance modes + `governance.py`) being shipped — they are.

---

## Status

Spec-ready. Conceptual decisions locked (D1–D8). The central one is D1 (the title↔role decoupling); get it right and the rest follows.

---

## The idea, and the concept it adds

The platform today has **permission roles** — steward, admin, moderator, member — which are permission bundles answering "what can this person *do*." It has no concept of an **office/title** answering "what is this person *called* / what position do they hold in this org." Real orgs have offices — President, Secretary, Treasurer, Council Member — that:

- don't map cleanly onto the four permission roles (a Treasurer and a Secretary might both be permission-"admins" but are distinct offices the org and its members care about),
- may carry **no** platform permissions at all (Council Member could be a pure label), or **may** carry permission-role powers (President → steward powers),
- exist independent of elections — many predate platform adoption and are just *assigned*.

This pass adds **titles** as a first-class, per-org concept, **decoupled from but optionally bound to** platform roles, with public display and direct assignment. Elections filling titles is **Phase 48** (this pass does not build election→title; it builds the titles concept + manual assignment that 48's hook will reuse).

---

## Locked decisions

**D1 — A title and a platform role are separable; a title optionally *binds* one role. This is the load-bearing model.**
A title carries: a name, an optional **bound platform role** (none / moderator / admin / steward), and assignment/cardinality config (below). The binding is the spine:
- **Title only** (bound role = none): an office with a public label and zero platform permissions. E.g. "Council Member," "Honorary Chair."
- **Title + bound role**: holding the title grants the bound role's permissions. E.g. "President" binds `steward`; "Treasurer" binds `admin`.
- **Role only**: the existing bare permission roles (today's behavior) — a member can hold `admin` with no ceremonial title. Titles are **additive**; nothing forces an org to use them.

Assigning/revoking a title with a bound role grants/removes that role via the **existing 45a/45b role-assignment machinery** — titles do not reimplement permission assignment, they sit on top of it.

**D2 — Titles are additive; the permission-role model and `governance.py` floor are unchanged.**
This is the primary risk-containment decision. The permission roles (steward/admin/moderator/member), the at-least-one-steward / at-least-one-admin floor, the governance modes, and all 45a/45b recovery guarantees stay **exactly as shipped**. Titles are a labeling + binding layer over roles. The floor logic stays keyed on **roles, not titles**. A title with bound role `steward` results in a steward role-holder, and the floor sees a steward exactly as before — it does not need to know a title is involved. **If the built-in reconciliation (D6) turns out to require changing floor logic, STOP and flag — do not power through.** The whole point of "additive" is that 47 cannot regress the steward-recovery / ownerless guarantees.

**D3 — Cardinality per title: single-holder or multi-holder.**
A title declares how many members can hold it: **single** (President, Treasurer — one holder) or **multi** (Council Member — N holders, optionally capped). This is the org's call per title. (Forward note: multi-holder titles are what 48's multi-seat elections fill via `num_winners`.)

**D4 — Fill method per title: assigned, elected, or both-allowed.**
Each title declares how it's filled: **assigned** (direct grant by a permitted actor — this pass), **elected** (filled by an election — Phase 48), or **both-allowed** (can be assigned now and put up for election later, or either). This pass implements **assignment**; the *elected* and *both* options are stored as config now (so the data model is complete) but the election path that consumes them is 48. A title marked elected-only simply has no manual-assign path enabled in this pass's UI (or assignment is restricted to a bootstrap/recovery actor — see D7).

**D5 — Direct assignment is permission-gated, org-configurable.**
Who can grant/revoke a title is governed by the permission matrix (default: admin/steward-tier, i.e. an existing `org.*` permission — wire to a new `title.assign` key or reuse an appropriate existing one; implementer's call, but it must be matrix-configurable so an org can delegate title-granting). Assignment of a bound-role title is itself a role change, so it respects the floor (D2) — e.g. you can't revoke the title that's the org's only steward-binding without the floor logic catching the role removal, same as today.

**D6 — Reconcile built-in seats (steward/admin) with the title concept — conservatively.**
For 48 to treat "elect a steward" and "elect a President" uniformly, the built-in seats need to be expressible as titles. **Conservative approach (required): represent steward/admin as built-in/system titles that bind their namesake role, WITHOUT changing how the role is stored or how the floor reads it.** The role remains the source of truth for permissions and the floor; the built-in title is a thin standard label over it. Do NOT migrate the permission model into the titles table. The test of "conservative enough": deleting the entire titles feature in your head leaves steward/admin working exactly as today. If reconciliation tempts you toward making roles *depend on* titles, that's the stop-and-flag line (D2).

**D7 — Bootstrap/recovery interaction.**
Title assignment must not create a new way to strand an org or bypass 45a/45b recovery. A title binding `steward` assigned/revoked goes through the same steward-transfer/floor machinery (you can't leave zero stewards). The platform-admin re-bootstrap backstop (45b B4) remains the ultimate recovery actor. Titles add labels; they don't add lockout vectors. Test this explicitly.

**D8 — Public display: title shows after the member's name where they appear publicly.**
A held title renders after the member's name across public + admin surfaces: member rosters, vote-flow graph node labels, delegate listings/profiles, proposal authorship, comments. Multi-title members (rare but allowed) show their titles per a simple, consistent rule (recommend: primary/most-privileged first, or org-defined display order — pick one and document). Display respects existing identity-visibility rules (a title doesn't deanonymize a node that's otherwise redacted in the vote graph — if the name is hidden, the title is hidden with it).

---

## What IS in scope

- **B1 — Titles data model + migration.** A `titles` table (per-org: name, bound_role nullable enum, cardinality single/multi + optional cap, fill_method assigned/elected/both, display config) and a title-assignment record (which member holds which title, granted-by, granted-at). Reversible migration + cycle test + PG smoke (per CLAUDE.md). Built-in steward/admin system titles seeded per D6 (conservatively — see B5).
- **B2 — Title CRUD (org-config).** Endpoints for an org to define/edit/remove its titles (name, bound role, cardinality, fill method, display). Permission-gated. Removing a title that has holders / binds a floor-critical role needs guarding (can't orphan the org's only steward-binding title; can't violate the floor).
- **B3 — Direct assignment / revocation.** `POST`/`DELETE` (or equivalent) to grant/revoke a title to/from a member, permission-gated per D5. Assigning a bound-role title performs the role grant via the 45a/45b machinery; revoking removes it, **respecting the floor** (D2/D7). Cardinality enforced (can't exceed a single-holder title; can't exceed a multi-title's cap). Audit events `title.assigned` / `title.revoked` / `title.created` / `title.updated` / `title.deleted`.
- **B4 — Public display surfacing.** Title(s) render after member names across the surfaces in D8. **This is where the `OrgOut` / serializer-coverage lesson from 46a applies directly** — titles must be surfaced in the member/profile/vote-graph response schemas the FE reads, and the 46a serializer-coverage test should be extended to assert title fields are present where the FE depends on them. (Per the 46a standing convention: new FE-facing fields ship with their serializer assertion in the same pass.)
- **B5 — Built-in title reconciliation (conservative, D6).** Seed steward/admin as system titles binding their roles, as a label layer. Verify (test) that the floor, recovery, governance modes, and all 45a/45b guarantees are byte-for-byte unchanged. This is the risk-bearing cluster — keep it thin.
- **B6 — Tests.** Title↔role binding (none / bound) grants/removes permissions correctly via the existing role machinery. Floor preserved: revoking the only steward-binding title is blocked exactly as removing the only steward is today (D2/D7). Cardinality enforced (single + multi-cap). Assignment permission-gated. Public display: title appears after name on the D8 surfaces; redacted vote-graph nodes don't leak a title. Built-in reconciliation regression: steward/admin behave exactly as pre-47 (D6). Serializer-coverage extended for title fields (B4). **Assert side effects** (actual role rows after a bound-title grant; actual floor behavior on revoke) — not just status codes.
- **F1 — Title management UI.** Org-settings surface to define titles (name, bound role, cardinality, fill method, display) and assign/revoke them to members. Permission-gated visibility.
- **F2 — Title display UI.** Render titles after member names across the D8 surfaces. Respect identity-visibility (redacted = no title shown).

---

## What IS NOT in scope (deferred)

- **Elections filling titles** — Phase 48. The election close-hook becomes "assign a title (and its bound role)"; that's built in 48, consuming this pass's titles + assignment. This pass stores the `fill_method = elected/both` config but does not build the election path.
- **Scheduled / term-based title turnover** — Phase 49.
- **Title hierarchies / reporting structures** (e.g. "Secretary reports to President") — out of scope; titles are flat labels with optional bound roles.
- **Per-title custom permission sets beyond the four roles** — a title binds one of the existing roles or none; it does not define bespoke permission bundles. (If an org wants finer control, that's the existing role-permission matrix, not titles.)
- **Migrating the permission model into titles** — explicitly forbidden (D6). Roles stay the source of truth.

---

## Verification matrix

| Check | Required | Notes |
|---|---|---|
| Backend pytest (full) | Yes | Baseline per the most recent prior closeout (46a's). Report delta. |
| Built-in reconciliation regression | Yes | **Load-bearing.** Steward/admin + the `governance.py` floor + recovery + governance modes behave byte-for-byte as pre-47. Reuse 45a/45b/46 floor + recovery tests as the regression base. |
| Title↔role binding | Yes | Bound-role title grant/revoke flows through the 45a/45b role machinery; title-only carries no permissions; role-only (no title) unaffected. Assert actual role rows. |
| Floor preserved through title ops | Yes | Revoking/deleting the only steward-binding title is blocked exactly as removing the only steward is today (D2/D7). |
| Cardinality | Yes | Single-holder enforced; multi-holder cap enforced. |
| Assignment permission gate (D5) | Yes | Only matrix-permitted actors can grant/revoke. |
| Public display + identity-visibility (D8) | Yes | Title renders after name on member rosters, vote-graph, delegate listings, authorship; a redacted vote-graph node shows no title. |
| Serializer-coverage extended (B4) | Yes | The 46a serializer-coverage test now also asserts title fields are surfaced where the FE reads them. (Closes the model-vs-response gap for titles before it can bite — the lesson from 45a/46.) |
| Migration reversible + cycle test | Yes | Per CLAUDE.md. |
| PG smoke `--mode both --prior-revision <id>` | Yes | Prior revision = the chain head at branch-cut (46a's migration if it added one, else 46's `e8b4d6f31a92`; confirm). |
| Frontend build + bundle hash | Yes | **Watch the PWA cache stickiness flagged in 46 QA** — if titles don't appear after deploy, suspect the cache before chasing a regression. |
| Browser verification (Chrome MCP, prod) | Yes | (1) Define a "President" title binding steward + a "Council Member" title binding nothing; (2) assign President to a member → they gain steward powers + the label shows after their name; (3) assign Council Member → label shows, no permission change; (4) try to revoke the only steward-binding title → blocked by the floor. |
| Worker / `start.sh` | If touched | This pass likely does NOT touch the worker (no scheduled title behavior — that's 49). If it doesn't, state "worker untouched" in closeout. If it does, the `bash start.sh` prod-like-env check is mandatory. |

---

## Pass sizing

Meaty but within a single staged pass — it's one coherent concept (titles) with a contained risk cluster (built-in reconciliation, B5). It has a migration and touches several display surfaces, but no novel infrastructure and well under the Greater-Phase threshold. Build bisection-friendly: land the data model + CRUD + built-in reconciliation (B1/B2/B5) and verify the floor is intact **first**, then assignment (B3), then display (B4/F2). The reconciliation (B5) is the riskiest isolated piece — if it tempts toward touching floor logic, it's the stop-and-flag line, and if it turns out bigger than expected it's the clean thing to split into a 47a.

---

## Suggested team structure

**Continuing dev team / the team that shipped 45a–46a.** This sits directly on the 45a/45b role-assignment + `governance.py` floor machinery and must not regress it — maximal context required. Not fresh-eyes.

Default four roles: lead (delegate, closeout, owns the conservative-reconciliation judgment), backend dev (B1–B3 + B5 + B6 — the binding model + reconciliation is the load-bearing work), frontend dev (F1–F2, browser-verifies, watches PWA cache), QA (prod browser verification of the define→assign→display flow + the floor-preservation check).

---

## Closeout reporting

Standard shape, plus:
- Confirm built-in reconciliation is conservative: steward/admin + floor + recovery + governance modes byte-for-byte unchanged (the headline safety property).
- Confirm bound-title grant/revoke flows through the existing 45a/45b role machinery (not a reimplementation).
- Confirm the floor blocks revoking/deleting the only steward-binding title.
- Confirm the serializer-coverage test was extended for title fields.
- Migration + PG smoke status; worker touched or not.
- Test count delta; browser verification results; any PWA-cache observations.
- Flag anything that will shape Phase 48 (the election close-hook consumes titles + the fill_method config).

---

## Notes for the team

- **The title↔role decoupling (D1) is the whole design.** A title optionally binds one platform role. Title-only = label, no permissions. Title+role = label that grants permissions via the existing machinery. Role-only = today's behavior. Get this model right and elections (48) become "fill a title (and its bound role)."
- **Titles are additive; the role model and floor are sacred (D2/D6).** Roles stay the source of truth for permissions and the `governance.py` floor. Built-in steward/admin become thin system-title labels over their roles — NOT a migration of the permission model into titles. The stop-and-flag line: if reconciliation requires the floor to read titles, halt.
- **Reuse the 45a/45b role-assignment machinery** for bound-title grants/revokes. Don't reimplement permission assignment.
- **The 46a serializer lesson applies here (B4).** Titles are FE-facing fields on member/profile/vote-graph responses — surface them AND extend the serializer-coverage test in the same pass, per the standing convention. This is the third pass in a row where new FE-facing data must not silently fail to serialize.
- **Identity-visibility wins over title display.** A redacted vote-graph node shows no title — the title must never deanonymize.
- **Keep election logic out.** Filling titles by election is 48. This pass stores the fill-method config but builds only direct assignment.
