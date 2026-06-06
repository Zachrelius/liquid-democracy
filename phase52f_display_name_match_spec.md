# Phase 52f — Per-Org Display Names + Display-Name-Match

**Status:** Spec + dispatch. Written 2026-06-06.

Reading order: this doc; `id_verification_arc_backlog.md` (the display-name-match locked decision + keep-list); the shipped `backend/routes/verification.py` `_extract_ocr_fields` + `_apply_decision` (where the legal name gets captured + stored); `backend/models.py` `User` + `OrgMembership` (where legal name + per-org display name live); `backend/verification_hashing.py` (the name normalization already written — reuse it).

## Goal

Two linked capabilities:
1. **Per-org display names** — a user can present a different display name in each org they belong to (cosmetic per-org identity, NOT a separate verified identity — verification stays one platform-wide identity per Phase 51).
2. **Display-name-match** — an org can require that a verified member's display name matches their legal name (as read from their ID), configurable as first / last / full must-match. This lets an org enforce "real names" for its members.

## Locked values decisions (resolved with Z — settled)

- **Store the LEGAL NAME readable** (first / last / full) on the verified user, with a privacy disclosure. NOT hashed. (Z reasoning, conceded: the feature's purpose is letting an org enforce display-name-against-legal-name; hashing the legal name adds no privacy because the org is enforcing AGAINST it, not being protected from it, and the system must compare arbitrary user-entered display names to it — which a hash can't do for partial/first-only matching. So readable is correct here. This is the INVERSE of the city case, where the org configures the gate value and hashing works.)
- **No purge-fix dependency.** Storing the legal name is about what WE retain long-term on our side; it's independent of the Didit session purge (which is about Didit-side retention). Sequence freely. Positive reason: capture the full long-term field set now so a user verifies ONCE and never has to re-verify to light up a later feature.
- **Configurable match granularity:** an org can require first-name match, last-name match, OR full-name match (Z wants all three options — "allow only real first name" etc.). Each independently selectable.
- **One platform-wide identity (Phase 51, unchanged):** per-org display names are cosmetic. They do NOT create separate verified identities; verification + dedup remain one-identity-per-person.

## Design — data model

### Legal name storage (new readable PII — disclosed)
Add to `User` (additive, nullable):
- `legal_first_name` (String, nullable)
- `legal_last_name` (String, nullable)
- `legal_full_name` (String, nullable) — Didit returns `full_name` directly; store it rather than reconstructing, since name ordering/middle-name conventions vary.

Captured in `_apply_decision` from the real payload (`decision.id_verifications[0].{first_name, last_name, full_name}` — confirmed paths from the 52e grounding). These currently flow into the hashes and are discarded; this phase ALSO persists them readable. **Privacy disclosure:** the consent copy + the privacy copy must state the legal name is retained and why ("kept so an organization you join can verify your displayed name matches your ID, if that org requires it"). Coordinate exact wording with the content agent.

- **Keep-list update:** the backlog keep-list already anticipated "legal name first/last/full (display-name-match)" — this phase makes it real. No surprise to the locked retention posture.
- **demo_stub / backdoor:** no real payload → no legal name; demo path sealed as always.

### Per-org display name
Today `User.display_name` is a single platform-level field. Add per-org override:
- `OrgMembership.display_name` (String, nullable) — when set, the user's display name IN THAT ORG; when null, falls back to `User.display_name`. Confirm `OrgMembership` is the right home (it's the per-user-per-org row — the natural place). A resolver helper `display_name_for(user, org)` returns the override or the fallback, centralized so every surface (member list, delegate pages, vote attribution) reads the same value.
- **Surfaces that render a user's name in an org context** must route through the resolver. Audit: member list, delegate profiles/pages, proposal authorship, vote attribution, comments. This is the "find every call site" cluster — the resolver is cheap; missing a site means an inconsistent name. List the audited surfaces in the closeout.

## Design — the match check

- New settings keys on `Organization.settings` (mirror the verification-floor pattern):
  - `verification_require_name_match` — one of `off` (default) / `first` / `last` / `full`. (A single enum is cleaner than three booleans since the options are mutually exclusive in practice — confirm with Z if they want COMBINABLE first+last-but-not-full; if so, use a set/flags instead. Default assumption: single enum, `full` implies both parts match in full-name form.)
- A predicate `display_name_matches_legal(user, org) -> bool`:
  - Resolves the user's effective display name in the org (the resolver above).
  - Resolves the required match mode from settings.
  - Normalizes BOTH sides with the EXISTING `verification_hashing.normalize_text` (reuse — same lowercase/strip/accent rules the hashes use, so matching behaves consistently) and compares per the mode:
    - `first` — normalized display name contains / equals the normalized legal first name (decide contains-vs-equals; recommend the display name's first token equals the legal first name — handles "Bob Smith" display vs "Bob" legal first).
    - `last` — analogous on last name.
    - `full` — normalized display name equals normalized legal full name.
  - `off` → always True (no gate).
  - Returns True when the user has NO legal name on file? **Decision needed (see fork):** an unverified user has no legal name — does the match gate apply to them at all? Recommend: the name-match gate only applies to users the org requires to be verified (it's meaningless for unverified users — there's nothing to match against). So `display_name_matches_legal` returns True (passes) for a user with no legal name on file, and the VERIFICATION floor is what forces them to verify first. The name-match is an ADDITIONAL constraint on top of being verified, not a standalone gate. Confirm.

## Design — enforcement points

The match check fires at two moments (both must enforce, or the gate leaks):
1. **Setting/changing a display name** in an org that requires a match → the new display name is validated against the legal name; non-match is rejected (or flagged — see fork) at write time.
2. **Enabling the org setting** (or a user becoming verified in an org that already requires it) → existing members whose display names DON'T match need handling. Recommend: enabling the setting does NOT retroactively block existing members (additive-layer + don't-strip-on-config-change, consistent with the cardinality-floor philosophy); instead it applies going forward (on their next display-name change) + optionally surfaces a list of non-matching members to the admin. Confirm — the alternative (retroactively flag/block) is more aggressive.

**Block vs flag (fork):** when a display name doesn't match, is the write REJECTED (hard block — you can't set that name) or FLAGGED (set it, but the admin sees a non-match flag)? Hard-reject is simpler + clearer for "real names required" orgs. Flag is softer. Recommend hard-reject at display-name-write time for an org with the setting on (the user gets "this org requires your display name to match your ID; please use your real {first/last/full} name"), since that's the legible behavior for the feature's purpose. Confirm with Z.

## The two forks for Z (called out, not buried)
1. **Match-mode shape:** single enum (`off`/`first`/`last`/`full`) vs. combinable flags (first AND last separately). Recommend single enum unless Z wants first+last-without-full.
2. **Block vs flag on non-match:** hard-reject the display-name write vs. allow + flag to admin. Recommend hard-reject.
(Both have a recommendation; the team can build the recommended path and Z flips if desired — don't block dispatch on these, but surface them in the closeout.)

## Verification matrix

| Check | Required | Notes |
|---|---|---|
| Legal name captured + stored readable | ✅ | A real verification populates `legal_first_name`/`last`/`full`; assert on a real-shape payload fixture. |
| Legal name disclosed in consent/privacy copy | ✅ | The new retention is disclosed; copy reviewed. |
| Per-org display name resolver | ✅ | `display_name_for(user, org)` returns the override when set, fallback when null. Every audited surface routes through it. |
| All name-rendering surfaces use the resolver | ✅ | Member list, delegate pages, proposal authorship, vote attribution, comments. Closeout lists the audited set. |
| Match predicate — first/last/full | ✅ | Each mode matches correctly against normalized names (reusing `normalize_text`); `off` always passes; no-legal-name passes. |
| Enforcement on display-name change | ✅ | In a match-required org, a non-matching new display name is rejected (or flagged per the fork). Assert the write outcome. |
| Enabling the setting doesn't retroactively strip | ✅ | Turning the setting on doesn't block existing members mid-session; applies going forward. |
| Cardinality-floor safety | ✅ | A name-match config change never auto-strips a seated role / removes a member below the governor floor. |
| demo_stub sealed | ✅ | No real legal name on demo accounts. |
| Additive-layer parity | ✅ | Org with `verification_require_name_match=off` + no per-org display names → byte-for-byte today. |
| Serializer | ✅ | Legal name is NEVER serialized to other members/clients (it's enforcement data, visible to the org admin adjudication context only if at all — decide: does the admin SEE the legal name to adjudicate a mismatch? If yes, that's an admin-only PII surface — gate it like the duplicate-flag adjudication, org-admin-only, audited). Default: legal name not serialized anywhere user-facing; the match predicate returns a boolean. |
| Migration (legal name cols + OrgMembership.display_name + setting) cycle + PG smoke | ✅ | Additive nullable. Confirm single head (`e6f7a8b9c0d1` after 52h, or later if 52g lands first — coordinate). |
| Adjacent regression | ✅ | Full suite green. |

## Sequence
Migration (legal name cols + `OrgMembership.display_name`) → capture legal name in `_apply_decision` (alongside existing hash extraction) → per-org display-name resolver + route all name surfaces through it → match predicate (reuse `normalize_text`) → enforcement at display-name-write + setting-enable handling → FE (per-org display-name field; org settings match-mode control; the non-match rejection copy) → consent/privacy disclosure copy. Deploy.

## Z-action items
- **None to run.** No Didit console work. A future re-verify naturally populates the legal name; existing verified users (Z) get a legal name only on next re-verify (the DOB-style "already discarded" issue does NOT apply here for NEW verifications, but Z's EXISTING verification predates legal-name storage, so Z's legal name is currently absent until re-verify). Same property as 52g's age band + the locality phase: existing verified users light up the new field on next verification. For a ~1-real-user pre-launch platform, fine — note it.
- **Two design forks** (match-mode shape; block-vs-flag) have recommendations; Z can flip post-build. Not dispatch-blocking.

## Notes for the team
- **Reuse `verification_hashing.normalize_text`** for name normalization on both sides of the match — do NOT write a second normalizer (consistency + the existing one is already tuned: lowercase/NFKD/strip-marks/strip-punct/collapse-ws).
- **The "verify once, light up everything" principle:** 52f, 52g, and the locality phase all share the property that existing verified users only populate the new field on re-verify. If Z wants to minimize re-verification, these three could be specced/shipped close together so a single re-verify populates legal name + age band + locality hash at once. Worth considering the bundling at dispatch time (they're independent enough to ship separately, but a user benefits from one re-verify covering all three). Flag for Z's sequencing call.
