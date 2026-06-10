# Phase 63 — Security Review + Hardening Closeout (2026-06-10)

Full-codebase security review (five parallel review passes: authn/authz, injection/input
handling, business-logic integrity, frontend, config/infra) followed by same-day fixes.
Branch: `phase-63/security-hardening`.

## Findings and dispositions

### CRITICAL — seeded platform-admin with committed password live on prod (FIXED + prod-mitigated)
`seed_data.py` seeded `admin` with `DEMO_PASSWORD = "demo1234"` and `is_admin=True`; verified
live on prod (login 200, `/api/admin/audit` reachable — including the ballot-unredaction
endpoint). **Prod action taken 2026-06-10:** password rotated via the app's change-password
flow (revokes refresh tokens); old password verified rejected. Audit log reviewed: every
historical `admin` login traces to Z's own IP (matching `ZacharyPetertam` activity) or to the
review itself — no evidence of foreign access. **Code fix:** `_admin_seed_password()` — the
admin seed now reads `SEED_ADMIN_PASSWORD` env or generates a random unusable password;
`DEMO_PASSWORD` is only ever used for non-admin demo personas. Seed is skip-if-exists, so the
rotated prod password persists across deploys.

### HIGH — vote-graph ballot-secrecy leak, two layers (FIXED)
`GET /api/proposals/{id}/vote-graph`:
1. No viewer-eligibility gate (siblings `get_proposal`/`get_results`/`get_trajectory` all 404
   non-eligible viewers) — any authenticated user could pull per-voter ballots for any org's
   proposal. Now gated identically to `get_results`.
2. Identity-redacted nodes carried the voter's real `user_id` alongside their exact ballot —
   joinable against `GET /api/orgs/{slug}/members` (user_id → display_name + email) to
   de-anonymize every member's vote. Redacted nodes now get per-request salted opaque ids
   (`anon_<hash>`), consistent across nodes+edges within one response, unlinkable across
   requests. Identity-visible nodes (self, public delegates, followed, delegators-to-viewer)
   keep real ids so profile links keep working.

### HIGH — cross-org IDOR in election candidacy routes (FIXED)
`routes/elections.py` candidacy GET/POST/DELETE validated membership in the *URL slug's* org
but never checked `proposal.org_id` — a member of any org could declare candidacy in another
org's leadership election, list its roster, or withdraw. `_proposal_or_404` now takes the
caller's `org_id` and 404s on mismatch (mirrors `duplicate_flags.resolve_flag`).

### HIGH — HTML injection into notification emails (FIXED)
`_prepare_org_email` interpolated user-controlled strings (display names, proposal titles,
org names, denial comments) into HTML templates unescaped — phishing-grade HTML injection
from the platform's own sending domain. All substitution values are now `html.escape`d;
`PRIMARY_COLOR` is exempt but strictly hex-validated (both in `_resolve_org_primary_color`
and `send_invitation_email`).

### HIGH — `/api/auth/register` unlimited (FIXED)
No rate limit + sends a verification email to an attacker-supplied address → spam relay /
email bombing via the Resend account + unbounded junk accounts. Now `@limiter.limit("10/hour")`.
(The distinct "Username already taken" / "Email already in use" messages are kept for UX —
the rate limit caps their use as an enumeration oracle.) The six `zz_revtest_*@nope.invalid`
accounts created while verifying this on prod were deleted from the prod DB the same day
(audit rows preserved with `actor_id` nulled).

### MEDIUM — votes accepted past `voting_end` (FIXED)
Deadline was enforced only by the sustained-majority worker tick (default 300s), so votes and
vote-changes landed up to ~5 min after the official close. `_require_voting_open` now rejects
when `now >= voting_end` (same naive-UTC clock the worker uses). Pre-voting carve-out intact.

### MEDIUM — no security headers on the SPA (FIXED, CSP deferred)
`frontend/nginx.conf` served zero security headers (backend middleware already set them on API
responses). Added X-Frame-Options DENY, X-Content-Type-Options nosniff, Referrer-Policy,
HSTS — at server level AND repeated in the static-assets location (nginx `add_header`
inheritance is suppressed by any location-level `add_header`). Config validated with
`nginx -t` in the nginx:alpine container. **CSP deferred** — it's the load-bearing
compensating control for sessionStorage tokens but needs testing against the pol.is embed +
inline styles; follow-up item.

### MEDIUM — FastAPI docs exposed on the public backend Railway domain (FIXED)
`backend-production-*.up.railway.app/docs` served Swagger UI (bypasses the nginx proxy).
`docs_url`/`redoc_url`/`openapi_url` now None when `settings.debug` is False.

### LOW (all fixed)
- Refresh-token reuse (replay of a revoked token) now revokes the user's whole active token
  family + writes an `auth.refresh_token_reuse_detected` audit event, then returns the same
  401 as any invalid token. NOTE: a duplicated browser tab (sessionStorage copied) that
  refreshes with the stale token will now log out all of that user's sessions — correct
  security behavior, mild UX tradeoff.
- Concurrent first-vote double-POST: `IntegrityError` on the unique constraint is now caught
  and resolved to the update path instead of surfacing a 500. (No integrity bug existed —
  the DB constraint always held.)
- `/api/demo/trigger-reset`: `@limiter.limit("6/hour")` (token compare was already
  timing-safe).
- `resolveNext`: rejects `/\` backslash protocol-relative variants alongside `//`.

### Reviewed and found SOLID (no action)
SQL injection (ORM-only, no interpolated SQL); file uploads (type allow-list, SVG rejected,
Pillow re-encode, server-generated filenames, decompression-bomb caps); SSRF (no
user-supplied URL fetches); mass assignment (profile update assigns only two whitelisted
fields); XSS (escape-first markdown renderer, all 16 `dangerouslySetInnerHTML` sites route
through it, nh3 server-side as second layer); CSRF (pure bearer-token, no cookies); secrets
(none committed — `.env` gitignored, sweep clean); JWT (HS256 pinned, placeholder-secret boot
guard); password reset/verification token flows; login brute-force defense; permission
matrix + platform-admin boundary; Didit webhook HMAC (fails closed, constant-time, replay
window); demo-reset `is_demo=True` wipe boundary; delegation cycle/weight integrity;
double-vote DB constraints; cosign idempotency; Docker non-root; CORS allow-list.

## Deferred / follow-ups (Z decisions or future passes)
1. **CSP header** — design + test against pol.is embed, Tailwind inline styles, PWA. The
   single highest-value remaining hardening given sessionStorage tokens.
2. **Demo filler-user wipe** matches `email LIKE '%@demo.example'` globally rather than the
   `is_demo` org boundary (guarded by KEEP_USERNAMES + real-org-membership skip; low risk).
3. **Tie-resolution seed** uses mutable `voting_end` (admin-grindable in principle; flagged
   in module docstring) — consider seeding on first-cast-vote timestamp.
4. **Registration enumeration messages** kept for UX — revisit if abuse appears.
5. **Org settings PATCH** merges unknown keys into the settings blob (admin-gated; consider
   an allow-list as defense-in-depth).
6. **Root-level scratch files with live tokens** (`janet.json`, `janet2.json`, `jtok.txt`)
   are untracked but should be deleted from the working tree.
7. Cross-org topic-name enumeration on unscoped `GET /api/topics` (documented-intentional;
   revisit if topic names become sensitive).

## Tests
- New: `backend/tests/test_phase_63_security_hardening.py` — 17 tests covering all six
  behavior changes (eligibility gate, opaque ids incl. cross-request unlinkability, candidacy
  org binding, email escaping + color validation, voting_end enforcement, refresh-reuse
  family revocation, rate-limit decorator presence).
- Updated: 6 existing vote-graph tests that located anonymous voters by real user_id (the
  leak itself); each now uses the `anon_` id and additionally asserts the real id is absent.
- Full backend suite run pre-merge; see closeout message for counts.
- No migration in this pass → PG smoke not required.

## Prod actions taken outside the deploy
1. `admin` password rotated (new credential handed to Z out-of-band; not in this repo).
2. Six `zz_revtest_*` junk accounts deleted from prod DB.
3. Audit log reviewed for historical compromise — none found.
