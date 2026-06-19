# Phase 76d — Full-Granularity Residency Scope (state/province + city, every country)

**Status:** Spec + dispatch. Written 2026-06-19. Follow-up to **Phase 76c** (country-level residency, SHIPPED 2026-06-19), which added `users.verification_country` capture + country-level scope entries. This pass extends residency matching from "US state/city + any-country country-level" to **full state/province + city granularity for every country**.

> Numbering note: "76a/76b/76c/76d" are an ad-hoc QoL sub-series Z and the planning agent ran directly on 2026-06-19; they are unrelated to `phase76_budget_method_toggles_dispatch_2026-06-17.md` (a separate, unbuilt budget pass that also took the 76 number). Don't conflate them.

**Reading order:** this doc; `phase52j_*_spec.md` (the org-level residency model this builds on); the shipped `backend/verification.py` (`_residency_scope_entries`, `user_satisfies_residency_scope`, `_residency_payload`); `backend/verification_provider.py` (`_extract_jurisdiction`, `_extract_country`, `map_decision_to_state`); `backend/verification_hashing.py` (`compute_locality_hash`); `backend/routes/verification.py` (`_apply_decision`); `frontend/src/pages/admin/OrgSettings.jsx` (residency-scope editor) + `frontend/src/utils/countries.js` (76c).

---

## Why this phase

76c shipped country-level matching as the safe subset. Z wants full granularity everywhere: an org should be able to gate on, e.g., "Ontario, Canada" or "Jalisco, Mexico" or "Bavaria, Germany — city of Munich", not just "Canada". The data model already half-generalized (entries carry `country`), but region matching is still US-only and city hashing assumes a US state.

**The load-bearing risk (read before estimating):** reliable region matching requires reconciling the **ID provider's free-form region string** (`parsed_address.region`, e.g. "Ontario", "Bavaria", "Jalisco") with the **admin's selected region**, for ~250 countries. The US path works today only because `normalize_jurisdiction` is a hand-built US-state name→2-letter table. There is no equivalent for other countries. If the provider's region name doesn't map to the same canonical code the admin picked, a member **silently fails a gate they should pass** — the exact failure mode the verification arc has been careful to avoid. This pass is mostly about making that mapping correct and *tested*, not about the data model.

---

## Locked decisions (from the 2026-06-19 planning exchange)

- Full granularity everywhere (Z chose this over country-only-for-non-US).
- Country picker is a dropdown storing ISO 3166-1 alpha-2 (shipped in 76c).
- Existing US-state members were backfilled to `verification_country='US'` (76c migration `b1c2d3e4f5a6`).

## Open decisions for this pass (resolve before/while building — surface to Z if blocking)

1. **Canonical region representation.** Recommend ISO 3166-2 subdivision codes (e.g. `CA-ON`, `DE-BY`, `US-MA`). Both the admin dropdown and the user's captured region normalize to this. Alternative (rejected): store raw region strings and string-match — fragile across providers and locales.
2. **`verification_jurisdiction` generalization.** Today it's a US 2-letter state. Options: (a) add a new `verification_region` (ISO 3166-2, country-scoped) and keep `verification_jurisdiction` as the US back-compat alias populated from it; (b) repurpose `verification_jurisdiction` to hold ISO 3166-2 and migrate US values `MA`→`US-MA`. Recommend (a) — less blast radius on the many `verification_jurisdiction` readers (proposals floor, admin, demo seed).
3. **`verification_state` ladder.** `ADDRESS_ON_ID` ("Verified resident") is US-region-centric today (76c deliberately left it alone, so a Canadian member is `IDENTITY` even with a parsed address). Decide whether to generalize `ADDRESS_ON_ID` to "residential address parsed (any country)". Recommend yes — otherwise non-US orgs can't use the "Verified resident" floor, only the residency-scope add-on. This is a semantic broadening of an existing gate; call it out to Z.
4. **City hashing input.** `compute_locality_hash(city, state)` today hashes `(city, US-state)`. For full granularity it must become `(city, region, country)` (Munich, Bavaria, DE ≠ Munich elsewhere). **Existing US city-gate hashes can't be re-derived** (raw city never stored), so either: (a) version the hash — keep v1 `(city, state)` comparison for US entries created pre-76d AND write v2 `(city, region, country)` going forward; or (b) accept that existing US city gates require members to re-verify. Recommend (a) with a `locality_hash_version` discriminator. This is the gnarliest migration detail.

---

## What IS in scope

- **Provider region extraction → ISO 3166-2.** Generalize `_extract_jurisdiction` (or add `_extract_region`) to map `parsed_address.region` + `parsed_address.country` to an ISO 3166-2 code for any country. Build on a subdivision dataset (`pycountry` carries ISO 3166-1 + 3166-2; add as a dep, or vendor a curated JSON). The reverse lookup (provider region *name* → code) needs:
  - exact + case-insensitive match on the subdivision `name`,
  - an alias table for high-traffic countries (provider abbreviations, local-language names, common variants),
  - a recorded "unmatched region" telemetry/log path so misses are visible (not silent).
- **Data model.** Per open-decision #2: `verification_region` (ISO 3166-2, nullable) on `users`, populated in `_apply_decision`; migration backfills `US-<state>` from existing `verification_jurisdiction`. Per #4: `locality_hash_version`.
- **Scope entry shape.** `{country, region?, city?}`. `_residency_scope_entries` normalizes region to ISO 3166-2; the predicate matches country → region → city in increasing specificity (an entry is satisfied when all its specified levels match). City still requires a region (the hash needs it).
- **Predicate + payload.** `user_satisfies_residency_scope` handles region matching (`user.verification_region == entry.region`) and the versioned city hash. `_residency_payload` carries `{country, region, city}`; FE CTA copy names the place (region display name via ISO 3166-2).
- **FE.** Cascading pickers in OrgSettings: country → region (ISO 3166-2 subdivisions for the chosen country) → optional city. Reuse `countries.js`; add a regions util keyed by country code. Remove the "non-US is country-level only — coming soon" note from 76c.
- **Tests.** Per-country region-normalization fixtures from **real provider payloads** (see watch-out), the versioned-hash US back-compat case, the ladder generalization (if #3 = yes), migration cycle + backfill, predicate matrix (country/region/city OR + specificity), serializer non-exposure of the new columns.

## What IS NOT in scope

- Sub-city granularity (postal code, neighborhood).
- Changing the OR-across-entries semantics or the cardinality-floor invariant (unchanged).
- Re-hashing existing US city gates from raw data (impossible — see #4).

---

## Verification matrix

| Check | Required | Notes |
|---|---|---|
| Backend unit tests (extraction, predicate, normalization, versioned hash) | Yes | Include per-country region fixtures; the alias table needs its own table-driven test. |
| Region name→code miss is logged, never silent | Yes | A miss must be observable (telemetry/audit), and must fail the gate in the safe direction. |
| Migration cycle (upgrade→downgrade→upgrade, SQLite) | Yes | New `verification_region` (+ `locality_hash_version`) columns. |
| Migration backfill (`verification_jurisdiction` `MA`→`US-MA`, country=US already done in 76c) | Yes | Assert DEMO sentinel excluded; null stays null. |
| PG smoke `--mode both --prior-revision b1c2d3e4f5a6` | Yes | Migration-bearing pass. |
| US back-compat: an existing US state/city gate still matches a pre-76d-verified US member | Yes | The versioned-hash decision (#4) is validated here. |
| 46a serializer coverage: new `users` columns NOT serialized to non-admin clients | Yes | Mirror `verification_country` (not surfaced). |
| FE build + cascading picker manual/Chrome QA | Yes | Real non-US ID needed for end-to-end; otherwise admin-config + predicate-unit coverage. |
| Full backend suite green | Yes | |

## Operational watch-outs

- **We likely lack real non-US Didit payloads.** The US extraction was built against a captured 2026-06-05 manifest. Region-name variance is the whole risk; without real non-US samples the alias table is guesswork. **Action:** capture (or have Z run) at least one non-US verification per target country during QA, and treat the alias table as living. Until a country has a tested mapping, consider gating its region option behind a "verified-supported" list rather than offering all ISO 3166-2 subdivisions with unproven matching.
- **Silent-failure direction.** Every unmatched region must miss the gate (not over-claim) AND emit a log line. Add a dedicated test that an unknown region name yields `verification_region = None` + a logged miss.
- **`verification_jurisdiction` has many readers** (proposal floor resolver, admin manual-verify, demo seed `='DEMO'`). If repurposing rather than aliasing (#2), audit every reader. Recommend aliasing to avoid this.
- **Hash versioning** (#4) is the single most error-prone change — get the US back-compat test green before anything else.

## Suggested team structure

Default four-role (lead + backend + frontend + QA). Backend owns the extraction/normalization + migration + hash versioning (the risk concentration); frontend owns cascading pickers. QA must include the non-US payload capture loop with Z.

## Closeout reporting

Per CLAUDE.md, plus: the per-country alias table's coverage list (which countries have *tested* region matching vs. offered-but-unverified), and the hash-versioning back-compat result.
