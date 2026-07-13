# Dependency security exceptions

The automated Python dependency audit blocks all known advisories except the
upstream, no-fix finding below. This exception must be removed if the
application begins using the affected functionality or a fixed release becomes
available.

## `PYSEC-2026-1325` — `ecdsa` signing timing side channel

No fix is planned upstream. `ecdsa` is a transitive dependency of
`python-jose[cryptography]`; the advisory affects ECDSA signing and key
operations. Liquid Democracy signs and verifies only symmetric HS256 JWTs and
does not perform ECDSA signing, key generation, or ECDH. The affected operations
are therefore unreachable in the application.

## Review process

CI still reports the ignored ID in its command line so the exception remains
visible. Review this file and the ignore whenever token algorithms or
authentication cryptography changes.
