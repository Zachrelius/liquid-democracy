# Dependency security exceptions

The automated Python dependency audit (`pip-audit -r requirements.txt` in CI)
runs with **no** ignored advisories. Any new finding fails backend CI before
tests run.

## Current exceptions

None.

## Retired exceptions

- `PYSEC-2026-1325` (`ecdsa` signing timing side channel) — retired in
  Phase 112. `ecdsa` was only a transitive dependency of `python-jose`, which
  was replaced by PyJWT after `python-jose` received a no-fix advisory
  (GHSA-3qf3-8w2g-rqmx / CVE-2026-85394). See
  `phase112_jwt_token_hardening_spec.md`.

## Review process

Adding an exception requires an entry here naming the advisory, why the
affected code path is unreachable, and the condition for removing it, plus a
visible `--ignore-vuln <ID>` on the CI command line. Review this file whenever
token algorithms or authentication cryptography change.
