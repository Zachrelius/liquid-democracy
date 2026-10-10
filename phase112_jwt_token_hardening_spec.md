# Phase 112 — JWT token hardening (PyJWT migration + token-purpose separation)

## Goal

Close two related JWT findings in one small security pass:

1. **Unsubscribe links authenticate as the recipient (High).** `generate_unsubscribe_token` (`backend/email_service.py`) signs a 30-day JWT with the same `SECRET_KEY`, the same HS256 algorithm, and the same `sub` = user id as login access tokens. `_get_user_from_token` (`backend/auth.py`) checks signature, expiry and `sub` only — never token purpose — so any unsubscribe link from any notification email is a 30-day bearer credential for the recipient's account (REST and WebSocket). Password reset / logout-all revoke refresh tokens only, so the user cannot kill a leaked link. The token also sits in the URL path, which the request logger records.
2. **Backend CI blocked by `python-jose` advisory GHSA-3qf3-8w2g-rqmx / CVE-2026-85394 (no fixed release).** The exploit requires using a public key as the HMAC secret; we use a configured shared secret with the algorithm pinned to HS256, so it is not reachable here. But `pip-audit` fails before tests run, so backend CI currently tests nothing. Replacing `python-jose` with PyJWT also removes the transitive `ecdsa` dependency, making the documented `PYSEC-2026-1325` exception obsolete.

## Branch + merge

- Branch: `phase-112/jwt-token-hardening`, cut from `origin/master` (931d6b2).
- `git merge --no-ff` to master, push, verify Railway backend deploy per CLAUDE.md.

## Verification matrix

| Check | Required | Notes |
|---|---|---|
| New regression tests (`tests/test_phase112_jwt_token_hardening.py`) | Yes | Unsubscribe token → 401 on `/api/auth/me`; legacy untyped access token → 401; WebSocket `check_access` rejects unsubscribe token; rate-limit key ignores non-access tokens; unsubscribe flow still works with old + new token shapes; `alg=none` and wrong-key tokens rejected |
| Full backend suite | Yes | `python -m pytest -n auto` from `backend/` |
| `pip-audit -r requirements.txt` with **no** `--ignore-vuln` | Yes | Must report zero findings |
| No remaining `jose` imports | Yes | `grep -rn "jose" backend --include=*.py` empty |
| Alembic migration | No | None added; PG smoke not required |
| Browser QA | No | No UI change. Login → authenticated page load after deploy is checked via prod smoke (`/api/auth/me` 401 for unauthenticated, health 200) |
| Prod deploy verified | Yes | Railway deployment row for merge commit + backend smoke |

## Team structure

Single full-stack lead (small pass, < 3h). No frontend changes.

## Load-bearing decisions

1. **Library:** PyJWT 2.15.1 (`PyJWT==2.15.1`), HS256 only, `algorithms=[ALGORITHM]` always passed explicitly.
2. **Token-type claim:** access tokens now carry `"typ": "access"`. A single helper `auth.decode_access_token(token, *, verify_exp=True)` is the only way to decode an access token; it requires `exp` + `sub` and rejects any `typ` other than `"access"`. Every access-token decode site routes through it: `_get_user_from_token` (REST + WebSocket), `websocket.check_access`, `rate_limit_utils.user_or_remote_address`, and the request-logging middleware in `main.py`.
3. **No grace period for untyped access tokens.** Tokens minted before deploy lack `typ` and are rejected. Access tokens live 15 minutes and `frontend/src/api.js` transparently refreshes on 401, so the cost is one silent refresh per active session. A compatibility shim would re-open the hole (unsubscribe tokens are also untyped-for-access).
4. **Unsubscribe tokens** gain `"typ": "unsubscribe"` (alongside the existing `"purpose": "unsubscribe"`). The decoder keeps accepting the existing `purpose` claim so links already sitting in inboxes keep working as *unsubscribe* links for their remaining lifetime. Same signing key retained deliberately — switching keys would break every outstanding unsubscribe link, and type separation enforced at the single decode helper is sufficient.
5. **CI:** remove `--ignore-vuln PYSEC-2026-1325`; update `docs/dependency_security_exceptions.md` to record that no exceptions remain.

## Operational watch-outs

- Every logged-in user takes one transparent refresh right after deploy. A user whose refresh token is also expired/revoked lands on login — same as any normal expiry.
- PyJWT validates that `sub` is a string; all user ids are UUID strings.

## Closeout reporting

Per CLAUDE.md. Append the result to `PROGRESS.md`.

---

## Status

Deployed 2026-10-10 (merges `d45d501` + `4219e04`). See the Phase 112 closeout in PROGRESS.md. W2 (uvicorn access-log redaction) was added after prod QA found the raw token in uvicorn's own access log.

## What IS in scope

- `python-jose` → PyJWT in `auth.py`, `email_service.py`, `main.py`, `websocket.py`, `rate_limit_utils.py`, `tests/test_demo_mode.py`.
- `typ` claim + `decode_access_token` helper; all access-token decode sites use it.
- CI audit exception removal + exceptions doc update.
- Regression tests.

## What ISN'T in scope (followups)

- **F1 — Hash password-reset and email-verification tokens at rest.** Refresh tokens were hashed in Phase 91; `PasswordReset.token` and `EmailVerification.token` are still plaintext. Needs a migration. Low severity (DB read access required, 1h / 24h windows).
- **F2 — Invalidate outstanding reset tokens** when one is used or the password is changed.
- **F3 — Access-token revocation on logout/password change** (15-minute residual window). Accepted design trade-off; revisit only if access-token lifetime grows.
