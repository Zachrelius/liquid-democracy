# Phase 52j — Verification UI Coherence + Org-Level Residency Model

**Status:** Spec + dispatch. Written 2026-06-06. One combined pass addressing eight observed issues from real-UI review, grouped into coherent clusters. Grounded against the shipped `verification.py`, `verification_hashing.py`, `verification_provider.py`, and `OrgSettings.jsx` (all read in full this session).

Reading order: this doc; `id_verification_arc_backlog.md`; the shipped `backend/verification.py` (gate predicates + the 52i locality helpers this RESTRUCTURES); `backend/verification_hashing.py` (`compute_locality_hash` — reused unchanged); `backend/routes/organizations.py` (the three join paths + the member-list resolver wiring); `frontend/src/pages/admin/OrgSettings.jsx` (the "Identity verification options" section); `frontend/src/verificationLabels.js` (CTA copy).

## Why this phase

Real-UI review surfaced eight issues. Two are **latent bugs that misfire today** (a dead dropdown option, a name-match that rejects common real names); several are **copy bugs**; one is a **structural model fix** (residency should be defined once at the org level, as a set, not re-specified per gate); plus the f/g closeout's **acknowledged resolver-propagation gap**. All are "make the shipped verification feature coherent + correct," so they ship together.

**Z decisions locked this session:** one combined pass; first-token name matching; the dropdown relabel keeps the backend ladder intact (no `rank()` renumber, no migration for the dead rung — deferred to a separate deliberate cleanup); residency becomes an org-level **set** of allowed (state, optional city) localities that any gate references.

---

## Cluster J1 — Org-level residency model (the structural fix)

**The problem.** Today residency geography is membership-scoped single values: `SETTING_MEMBERSHIP_JURISDICTION` (one state) + `SETTING_MEMBERSHIP_LOCALITY` (one city), read by `_gate_city_for_org` and enforced ONLY by `check_membership_locality_for_join`. Role gates and proposal gates can't reference geography at all, and an admin defining "this is a Somerville/Cambridge org" has nowhere to say it once. Geography is an org-wide fact, not a per-gate one.

**The fix.** Promote residency to an org-level definition: a **set** of allowed `(state, city?)` localities, defined once, that any gate references by a boolean "require residency."

### Data model (org `settings` JSON — no migration; it's JSON)
- **New:** `verification_residency_scope` — a list of allowed locality entries. Each entry: `{"state": "MA", "city": "Somerville"}` (city optional → `{"state": "MA"}` means "anyone in MA"). Example:
  ```json
  "verification_residency_scope": [
    {"state": "MA", "city": "Somerville"},
    {"state": "MA", "city": "Cambridge"},
    {"state": "NH"}
  ]
  ```
  A user satisfies the scope if they match **any** entry (OR semantics): for a city-bearing entry, the user's `verification_locality_hash` must equal `compute_locality_hash(entry.city, entry.state)`; for a state-only entry, the user's `verification_jurisdiction` must equal `entry.state`. **Independent levels preserved** (52i locked decision): a state-only entry is satisfied by state match; a city entry requires the city hash. No subsumption between a city entry and a state entry — each entry is matched on its own terms.
- **Migration of the OLD single-value settings:** the shipped `verification_membership_jurisdiction` + `verification_membership_locality` keys. Since this touches NO real orgs (confirmed — only Z's demo-stage orgs exist, and none have a city gate configured), the clean approach: **a one-time settings-shape normalizer** that, for any org carrying the old keys, folds them into a single `verification_residency_scope` entry (`[{"state": <old jurisdiction>, "city": <old locality or omitted>}]`), then the gate logic reads ONLY the new key. Run it as a tiny data-migration over orgs whose settings contain the old keys. (If the team confirms zero orgs carry them, the normalizer is a no-op but ships anyway for correctness + the parity test.) The old keys are then deprecated (leave in place, stop reading — same posture as other deprecated fields).

### New predicate (replaces the single-value locality logic)
`user_satisfies_residency_scope(user, org) -> bool` in `verification.py`:
- Reads `verification_residency_scope`. **Empty / absent → True** (no residency gate; additive-layer parity — this is the load-bearing "ungated orgs unchanged" guarantee).
- For each entry (OR): state-only entry → `user.verification_jurisdiction == entry.state`; city entry → `compute_locality_hash(entry.city, entry.state) == user.verification_locality_hash` (reuses the shipped hash fn UNCHANGED — the state is in the hash, so cross-state disambiguation still holds). Any entry matching → True.
- A user with neither a jurisdiction nor a locality hash → False against any non-empty scope (safe direction).
- **Replaces** `_gate_city_for_org` + `user_meets_locality`. Keep those as thin shims delegating to the new predicate ONLY if other code imports them; otherwise remove and update call sites. Confirm importers by reading the routes before deleting.

### Gates reference residency by a boolean (J1 + J3 together)
Each gate scope gets a "require residency" flag that references the org-level scope, rather than carrying its own geography:
- **Membership:** `verification_membership_require_residency` (bool). When true, `check_membership_*_for_join` also calls `user_satisfies_residency_scope`. (This replaces today's "city gate hangs off the membership floor" wiring.)
- **Role:** `verification_role_require_residency` (per-role bool map, mirroring `verification_role_floors`). When a role requires residency, the role-grant check also requires `user_satisfies_residency_scope`.
- **Proposal:** see J3 — a proposal can require residency referencing the same org scope.
- **The org-level scope is the single source of WHERE; each gate only toggles WHETHER.** This is the structural heart of the fix.

### Cardinality-floor invariant (unchanged, must hold)
A residency requirement on a role gates the GRANT; an org changing its residency scope must NOT auto-strip a seated role below the governor floor. Same construction as every other gate — the check precedes the role-id write, blocks the mutation, never demotes the incumbent. Test it for the residency dimension specifically.

---

## Cluster J2 — Dropdown simplification (the dead-option bug)

**The problem.** The membership + role floor dropdowns offer five options including "Identity verified — unique person" (`identity_unique`), which 52h made **dead** — the mapper never assigns it, so selecting it gates on rank ≥ 2 which behaves incoherently (a user at `address_on_id` rank 3 satisfies it, a user at `identity` rank 1 doesn't — it silently means "address-or-better" while labeled "unique person"). And "address on ID" vs "residency confirmed" present two near-identical options where only the former is real (the stronger proof-of-address tier isn't built).

**The fix (Z-locked: relabel only, backend ladder intact).** Collapse the dropdowns to three meaningful options reframed around *what you're checking*, not an abstract strength ladder:
- **"No verification required"** → unset (unchanged).
- **"Identity verified"** → `identity`.
- **"Verified resident"** → `address_on_id`, **and** auto-enables the gate's "require residency" boolean (J1) so the org's residency scope applies. (This is the natural fusion: "verified resident" means identity + address + matches our residency scope.)

Implementation:
- **FE only for the relabel** (`OrgSettings.jsx`): both the membership floor dropdown and the three role dropdowns drop the `identity_unique` and `residency_verified` `<option>`s, and relabel `address_on_id` to "Verified resident." Selecting "Verified resident" reveals the residency-scope editor (J1) rather than a per-gate jurisdiction text field.
- **Backend ladder UNCHANGED** (Z decision): `identity_unique` + `residency_verified` stay defined in `ORDER` / `VALID_STATES` so any stale stored value still resolves sanely. `rank()` is NOT renumbered. Removing the dead rung from `ORDER` is deferred to a separate deliberate cleanup pass (already noted in the backlog) because it renumbers every rank comparison.
- **No migration for the dropdown values themselves** — an org that somehow stored `identity_unique` keeps resolving (it just can't re-select it). J1's residency-settings normalizer is the only data-shape migration in this phase.
- This resolves observation #1 (residency control "missing"): it wasn't missing, it was buried under opaque labels; "Verified resident" + the org-level scope editor makes it discoverable.

---

## Cluster J3 — Org-level proposal verification policy

**The problem.** Proposal verification is purely per-proposal author-set (`check_vote_floor_for_proposal` reads `Proposal.verification_floor`); an org has no way to set a policy. Observed #2.

**The fix.** An org setting controlling proposal verification: `verification_proposal_policy` ∈ `always` / `never` / `author` (default `author` = today's behavior).
- `author` — the proposal author sets the floor at creation (today's behavior; unchanged).
- `always` — every proposal in the org carries the org's chosen floor regardless of author. Needs an org-level "what floor" value: `verification_proposal_floor` (+ the residency boolean per J1) — the floor applied to all proposals when policy is `always`.
- `never` — proposals can't carry a verification floor; the author's floor control is hidden/disabled and any stored proposal floor is ignored at enforcement.
- Enforcement: `check_vote_floor_for_proposal` resolves the EFFECTIVE floor = (policy `always` → org floor; policy `never` → none; policy `author` → the proposal's own floor). Centralize this resolution in one helper `effective_proposal_floor(proposal, org)` so the vote path + the proposal-creation FE agree.
- **Composes with residency + age:** an `always`-policy org requiring "verified resident" applies identity floor + residency-scope to every proposal vote.
- FE: an org setting (the three-way policy + the org floor picker shown when `always`); the proposal-creation form's floor picker is shown only when policy is `author`.

---

## Cluster J4 — Name-match fix + "either" mode

**The problem (confirmed bug).** `display_name_matches_legal` in `first` mode does `tokens[0] == _normalize_name_for_match(legal_first)`. Didit packs middle names into `first_name` ("Zachary Michael"), so `legal_first` normalizes to `"zachary michael"` and a display name of "Zachary" (token `"zachary"`) FAILS. With the default `block` action, this rejects a huge fraction of real users. Observed #5.

**The fix (Z-locked: first-token matching).**
- **`first` mode:** the display name's first token matches the legal first name's FIRST token. So `"zachary michael".split()[0] == "zachary"` matches a "Zachary" display name. (Also matches "Zachary Smith" display → first token "zachary".)
- **`last` mode:** symmetric — display name's last token matches the legal last name's LAST token.
- **`full` mode:** keep as-is (entire normalized display == entire normalized legal full) BUT reconsider: a user whose legal full is "Zachary Michael Smith" and display is "Zachary Smith" would fail full mode. Recommend: `full` mode requires the display's first token to match legal first's first token AND display's last token to match legal last's last token (first+last match, middle-name-tolerant), rather than exact full-string equality. This makes `full` mean "real first and last name" without forcing middle names into the display. **Confirm with Z** — if they want strict full-string match, keep exact; the recommended relaxed version is friendlier and consistent with the first-token philosophy. (Defaulting to the relaxed first+last interpretation.)

**The "either" option (Z-requested #4).**
- Add `NAME_MATCH_EITHER = "either"` to `_VALID_NAME_MATCH_MODES`.
- Semantics: passes if the `first`-mode check OR the `last`-mode check passes (display first-token matches legal first-token, OR display last-token matches legal last-token). The looser "you're using at least one part of your real name" option.
- FE: add "Either first or last name must match ID" to the mode dropdown.

---

## Cluster J5 — Copy fixes

All confirmed against the live `OrgSettings.jsx`.

- **#6 — stale sentence.** In the section intro paragraph, delete: "Identity-verification options for members will become available in a future update." (Leftover from Phase 52 Stage 1 before the member flow shipped; now false.)
- **#7 — backwards delegate toggle.** "Require verified members to be promoted to public delegate" → reword to "**Require verification to become a public delegate.**" The help text is fine; only the label inverts the meaning.
- **#8 — confusing age copy.** Rewrite the min-age help text to EXPLAIN rather than assert. Current text asserts "never the raw date of birth" + "auto-promote" which reads as contradictory. Replacement (tune wording with the content agent): "We record which age brackets a verified member has passed (for example, 16+ and 18+) and the month they'll reach the next one — not their date of birth. Members below the minimum can't join, and a member who later reaches the minimum gains access automatically without re-verifying." This is honest about the mechanism (`compute_age_bands` stores met-thresholds + a month-aligned `promotes_at`) so it doesn't read as a technicality dodge.

---

## Cluster J6 — Per-org display-name resolver propagation (the f/g found-gap)

**The problem.** The f/g closeout flagged it: `display_name_for` was only wired into the member list (`OrgMemberOut`). Delegate pages, proposal authorship, vote attribution, comments, and notification copy still render `User.display_name` directly. So a user who sets a per-org display name sees it on the member list but their platform name everywhere else — inconsistent.

**The fix.** Route the remaining org-context name surfaces through `display_name_for(user, org, membership=...)`. Audit + update:
- Delegate profile pages + the public delegate listing (`DelegateProfile` / `OrgDelegateProfile` serializers).
- Proposal authorship.
- Vote attribution.
- Comments.
- Notification copy + email templates that render a member's name in an org context.
- **Performance:** `display_name_for` walks `user.org_memberships` when no membership is passed; for list surfaces, pass the membership (or pre-fetch) to avoid N+1. The resolver already supports a `membership=` arg for this. Note any surface where the org context isn't readily available (a platform-level notification with no org scope correctly falls back to `User.display_name` — that's fine).
- Closeout lists every surface audited + which now route through the resolver.

---

## Verification matrix

| Check | Required | Notes |
|---|---|---|
| **J1** residency scope set, OR-match | ✅ | A user matching ANY entry satisfies; matching none fails; empty scope → True (parity). State-only entry matches on jurisdiction; city entry matches on locality hash. Both-level independence preserved. |
| **J1** old single-value settings normalized | ✅ | An org carrying the old `verification_membership_jurisdiction`/`_locality` keys folds into one `verification_residency_scope` entry; gate reads only the new key. No-op + parity test if zero orgs carry them. |
| **J1** residency boolean per gate | ✅ | Membership + per-role "require residency" reference the org scope; toggling on enforces it, off doesn't. |
| **J1** cardinality-floor on residency role gate | ✅ | Changing the org residency scope never auto-strips a seated role below the governor floor. |
| **J2** dropdowns show 3 options | ✅ | `identity_unique` + `residency_verified` options gone from membership + role dropdowns; "Verified resident" reveals the scope editor. Backend ORDER unchanged (assert `identity_unique` still in VALID_STATES, rank not renumbered). |
| **J2** stale stored value still resolves | ✅ | A settings value of `identity_unique` still resolves via the intact ladder (no crash, sane gate). |
| **J3** proposal policy always/never/author | ✅ | `effective_proposal_floor` resolves correctly for each policy; `always` applies org floor to a proposal with no author floor; `never` ignores a stored proposal floor; `author` uses the proposal's floor. Side-effect on a vote attempt. |
| **J3** composes with residency + age | ✅ | An `always`+verified-resident org gates every proposal vote on identity + residency. |
| **J4** first-token name match | ✅ | legal_first "Zachary Michael" + display "Zachary" → MATCH (the bug fix). Symmetric for last. The exact regression case from observation #5. |
| **J4** "either" mode | ✅ | Passes when first OR last token matches; fails when neither. |
| **J4** full mode (relaxed first+last) | ✅ | "Zachary Michael Smith" legal + "Zachary Smith" display → match (if Z confirms relaxed); document the chosen semantics. |
| **J5** copy | ✅ | Stale sentence removed; delegate toggle reworded; age copy explains the mechanism. No backend state codes in copy (Phase 49a rule). |
| **J6** resolver propagation | ✅ | Delegate pages, proposal authorship, vote attribution, comments, notifications route through `display_name_for`; closeout lists audited surfaces; no N+1 (membership passed/pre-fetched). |
| Additive-layer parity (whole phase) | ✅ | An org with no verification settings is byte-for-byte unchanged. The Mode-3 parity test still passes. |
| Migration (J1 settings normalizer) cycle + PG smoke | ✅ | The only data migration; settings-shape only. Confirm `alembic heads` single head (`a8b9c0d1e2f3` after 52i) — though a settings normalizer may be a data-migration script rather than a schema migration; either way confirm head + reversibility. |
| Adjacent regression | ✅ | Full suite green (596 baseline + new). |
| FE build clean | ✅ | New bundle hash recorded. |

## Sequence
J2 (dropdown relabel — pure FE, low risk, do first to de-risk) → J5 (copy — pure FE) → J4 (name-match fix + either — backend predicate + FE option) → J3 (proposal policy — backend resolver + settings + FE) → J1 (residency model — the structural cluster: settings normalizer + new predicate + per-gate booleans + FE scope editor) → J6 (resolver propagation — the find-call-sites cleanup). Deploy as ONE `--no-ff` merge (Z chose one combined pass). If the team finds J1 trips the Greater-Phase threshold on its own (it's the meatiest cluster — new predicate + migration + multi-gate wiring + a non-trivial FE scope editor), they may stage J1 separately behind the rest; flag at sizing.

## Invariants
- **Independent levels preserved** (52i): state and city match on their own terms; no subsumption.
- **Geography defined once** (org scope); gates reference WHETHER, not WHERE.
- **Derived, never stored:** residency satisfaction is computed on read; no stored "is_resident" boolean.
- **Cardinality floor:** no gate change auto-strips a seated role below the governor floor.
- **Additive-layer:** unconfigured orgs unchanged.
- **Backend ladder intact** (Z decision): no `rank()` renumber this pass; dead-rung removal deferred.
- **Reuse `compute_locality_hash` unchanged** — the hash machinery doesn't change; only settings shape + which gates read it.

## Closeout must report
J1 residency-scope OR-match + the old-settings normalizer result (how many orgs, if any, carried the old keys) + cardinality-floor on a residency role gate; J2 dropdown relabel + confirmation the backend ladder is untouched + a stale-value-still-resolves test; J3 the three-way policy side-effects; J4 the middle-name regression case (the observation-#5 fix) + either mode + the chosen full-mode semantics; J5 copy diffs; J6 the full list of name-rendering surfaces audited + routed; additive-layer parity; migration + PG smoke on a confirmed single head; adjacent green; new bundle hash.

## Z-action items
- **None to run.** All FE/backend; no Didit console, no re-verify required. (Z's existing verification already carries a `verification_locality_hash` from the 52i grounding re-verify, so the residency model can be exercised against Z's real row.)
- **One open semantic** for Z (has a default, flag in closeout): J4 `full` mode — relaxed first+last-token match (recommended, middle-name-tolerant) vs. strict full-string equality. Defaulting to relaxed.
