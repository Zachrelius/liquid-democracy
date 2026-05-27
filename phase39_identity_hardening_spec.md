# Phase 39 — Identity Hardening

**Status:** Spec, dispatched [pending]. Written 2026-05-27 post-Phase-38 close.

This document combines dispatch framing (top) with the full spec body (below). Reading order at session start: this doc first.

---

## Dispatch framing

### Goal

Close four identity / account-lifecycle gaps from the 2026-05-27 external review (`external_review_2026-05-27.md`). The unifying shape: the platform's User table currently has no soft-revocation path (every token issued is valid until natural expiry — no "ban this user" lever short of `DELETE FROM users`); the refresh token path doesn't re-check user state at all; the forgot-password endpoint has a measurable timing side-channel; and the ORM model declarations have drifted out of sync with the migration state on `org_id NOT NULL` constraints across four Phase 18b tables. All four fixes ship together because they share the same migration (the new `User.is_active` column) and they all touch the auth/identity surface that Phase 37/38 just hardened.

The four items:

- **B1** (review §3.3): `User.is_active` column add + check in `_get_user_from_token` and `refresh_token`. Today's platform has no way to revoke a compromised account without `DELETE FROM users`, which the FK constraints prevent. Adding `is_active` gives ops a soft-revocation lever and gives the refresh-token path a state-check it currently lacks.
- **B2** (review §3.4): move the `send_password_reset_email(...)` call inside `forgot-password` into `BackgroundTasks` so the response returns before the SMTP/Resend call completes. Today the "user exists" branch performs the email send inline (~100-500ms+) and the "user doesn't exist" branch returns immediately — a measurable timing side-channel an attacker can use to enumerate registered emails. The `register` endpoint already uses the BackgroundTasks pattern (`routes/auth.py:347`); the fix is making `forgot-password` match.
- **B3** (review §3.5): align ORM model `nullable=False` declarations with the post-Phase-18b migration state on `Delegation.org_id`, `FollowRelationship.org_id`, `DelegationIntent.org_id`, `FollowRequest.org_id`. Today the models still declare `Mapped[Optional[str]]` with `nullable=True`, but the migrated DB has these as NOT NULL. The drift surfaces only on the fresh-DB branch of `start.sh` (where `create_all` builds from model declarations before `alembic stamp head` runs) — that branch ends up with structurally different schemas than the upgraded-DB branch. Pure declaration sync; no migration.
- **B4** (review §2.3 deferred piece): optional soft-lockout columns on User. Phase 38 D13 deferred this from Phase 38 to land alongside `is_active` in one migration. Add `User.failed_login_count: int default 0` and `User.locked_until: DateTime nullable`. Wire the login route to increment on 401, reset on 200, set `locked_until = now + 15min` after 10 consecutive failures, and reject login when `locked_until > now`. The rate limiter Phase 38 B3 added is per-IP; this is per-username. The two together make brute-force economics meaningfully worse.

### Branch + merge

Branch: `phase-39/identity-hardening`. Merge with `--no-ff` to master per CLAUDE.md.

### Verification matrix

| Check | Required | Notes |
|---|---|---|
| Backend pytest (full, excl. 3 demo-reset suites) | ✅ | Target ~+15-20 tests across four clusters. Post-Phase-38 baseline is 1442 PASS / 27 pre-existing FAILED (commit `e101d8b`). Target ~1457-1462 PASS, 27 pre-existing FAILED unchanged. |
| Backend pytest: targeted auth/identity suites | ✅ | `pytest -k "auth or refresh or forgot_password or login or user_state or migration_cycle"`. |
| Demo-reset suite | ✅ | Run separately. The new User columns must not break the demo seed (named personas + filler members all get default `is_active=True, failed_login_count=0, locked_until=NULL`). |
| Migration cycle test | ✅ | New migration in this pass. Must support `upgrade → downgrade → upgrade` cleanly on SQLite per CLAUDE.md migration convention. Pattern: `test_phase_39_migration_cycle`. |
| **PG smoke** `--mode both --prior-revision <Phase 30.1 B5 or last-migration-id>` | ✅ | This pass adds a migration. PG smoke is required per CLAUDE.md. Pre-flight: identify the prior revision by reading `backend/migrations/versions/` for the most recent revision id at master HEAD. |
| Frontend build | ❌ Not expected | Backend-only pass. Bundle should remain `index-Dp3YmSzh.js`. If FE touched (B4 may surface a "your account is temporarily locked" UI question — see B4 D8), bundle hash changes. |
| Backend deploy success verification | ✅ | Per CLAUDE.md backend-deploy hygiene. 13th consecutive clean auto-deploy expected. |
| Demo reset post-deploy | ✅ | Confirm reset completes and demo personas can still log in (defensive against the new column defaults). |
| API verify trio | ✅ | (a) Authenticated request as a user with `is_active=False` → 401 on protected endpoint (B1). (b) `POST /api/auth/forgot-password` for a known email vs. an unknown email — both return 200 within <50ms (B2 — timing measurement at p50 over 10 trials each). (c) 10 bad-credential POSTs to `/api/auth/login` from one IP for one username → 11th attempt returns 401 with `locked_until` in response detail (B4). |
| Browser verification (QA via Chrome MCP) | ✅ | Normal login + browse flow holds; "account locked" UX (if FE touched) renders correctly; password reset flow doesn't visibly hang at the email-send step. |
| File-count check | ✅ | `git diff master <branch> --stat`. |

### Suggested team structure

**Continuing dev team** per the refined heuristic surfaced after Phase 38: identity hardening is an "add what's missing" pass (add columns, check at well-defined sites, add background task) rather than a "find what we missed" pass. Codebase context + CLAUDE.md migration hygiene > independent eyes for this character of work. The Phase 38 team has the most recent context on the auth surface and would be marginally better if they're re-dispatchable as a single team-identity; otherwise the continuing dev team (Phase 36/37) is the right default.

Standard four-role structure per CLAUDE.md default:

- **Lead** in delegate mode. Coordinates B1-B4 sequencing, runs the migration cycle test + PG smoke, writes the closeout.
- **Backend dev.** Owns B1 (User.is_active + guards), B2 (forgot-password BackgroundTask), B3 (ORM nullable=False alignment), B4 (soft-lockout columns + login-route wiring), the migration, and all backend tests. Touches `backend/models.py`, `backend/auth_utils.py`, `backend/routes/auth.py`, `backend/migrations/versions/<new>.py`, and `backend/tests/test_phase_39_identity_hardening.py`.
- **Frontend dev (conditional).** Engaged only if B4 surfaces a "your account is temporarily locked" UI affordance — see B4 D8. Otherwise FE doesn't need to touch.
- **QA teammate.** Browser-verifies the password reset flow + normal login on prod after demo reset + the locked-account UX (if FE touched).

### Sequence

1. **B3** first (ORM nullable=False alignment). Zero-risk declaration sync — no behavior change. Gets the team comfortable with the file shape before touching the migration.
2. **B2** (forgot-password BackgroundTask). One-line move; no schema impact. Self-contained.
3. **B1 + B4 migration** (the new User columns: `is_active`, `failed_login_count`, `locked_until`). Single Alembic revision adds all three.
4. **B1 model + guards** (`is_active` checks in `_get_user_from_token` and `refresh_token`).
5. **B4 login-route wiring** (failed_login_count increment/reset + locked_until set/check).
6. **T1** tests across all four clusters.
7. Migration cycle test + PG smoke `--mode both`.
8. Targeted suite + full pytest sweep.
9. Commit + merge + push.
10. Backend deploy verification + demo reset + API verify trio.
11. QA browser verification.
12. Closeout report.

### Load-bearing decisions surfaced (full list in §"Locked decisions" below)

- **One migration, three columns.** `User.is_active`, `User.failed_login_count`, `User.locked_until` ship together in one Alembic revision. Backfill: all existing rows get `is_active=True, failed_login_count=0, locked_until=NULL`. Reversible per CLAUDE.md convention.
- **`is_active` is checked in BOTH `_get_user_from_token` AND `refresh_token`.** Closes the §3.3 gap that today's refresh path doesn't recheck user state.
- **`is_active=False` returns 401 (not 403) on protected endpoints.** Mirrors the existing "Could not validate credentials" posture; doesn't reveal whether the failure is "your account was revoked" vs. "your token is invalid." Account-state messaging is a future product-decision, not a security one.
- **Soft lockout is per-username, not per-IP.** 10 consecutive failures on one username from any IP triggers the lockout. Combined with Phase 38 B3's 10/minute per-IP rate limit, the joint policy is "10/min/IP AND 10-bad-attempts-per-username-per-15min." Both layers must fail an attacker for them to succeed.
- **Lockout window: 15 minutes.** Reviewer's suggested default. Configurable as a constant; not config-store-driven in this pass (changing it requires a deploy, which is appropriate at v1 scale).
- **Successful login resets `failed_login_count` to 0 and clears `locked_until`.** No carrying of "you've been failing for the past hour" state across a legitimate login.
- **Forgot-password BackgroundTask returns identical response in both branches.** The body shape doesn't change; only the timing characteristic.
- **B3 is pure declaration sync; no migration.** The DB schema is already NOT NULL post-Phase-18b. The fix is ORM-side declaration only.

### Operational watch-outs

- **Soft lockout is a real DoS surface.** An attacker who knows a target username can intentionally fail 10 times to lock the legitimate user out for 15 minutes. This is the explicit tradeoff with username-keyed lockouts. Mitigations: the lockout is short (15 min), the legitimate user can request a password reset to regain access immediately (the reset flow doesn't consult `locked_until`), and ops can manually clear `locked_until` if needed. If real abuse shows up at pilot scale, the next refinement is exponential backoff per-username instead of a fixed window. Don't pre-optimize.
- **The new columns affect demo seed.** Defaults are `is_active=True, failed_login_count=0, locked_until=NULL`; the seed pipeline does not explicitly set these, so the defaults are load-bearing. Confirm via the Phase 23 demo-reset suite.
- **`refresh_token` is the silent path where state-recheck is most consequential.** Frontend auto-refreshes on 401 against the access token. If a malicious actor's `is_active` is flipped to False, today's behavior is: their next access-token refresh succeeds because `refresh_token` doesn't check user state, and they retain access for another access-token lifetime (15min per Phase 4b). Post-B1: the refresh fails 401, frontend redirects to login, and the malicious actor must obtain credentials again. This is the core security improvement of the pass.
- **B3 is a free win, but worth verifying with a clean fresh-DB deploy locally.** Run `bash start.sh` against an empty DB locally and assert the `org_id` columns come up NOT NULL. The reviewer's concern was that the fresh-DB and upgraded-DB schemas could diverge silently; the verification is asserting they don't.
- **B2 is a one-line move — but the test must verify the timing.** A trivial test that "both responses return 200" won't catch a future regression that re-inlines the email send. The test asserts the response returns within a tight timeout (say, 50ms) for both branches, regardless of whether the user exists.
- **Lockout response shape needs to carry `locked_until` so the FE can render a useful message.** When the route rejects with 401 due to lockout, include `locked_until` in the error detail (ISO timestamp) so a future FE can render "Your account is locked until X" instead of the generic "Invalid username or password." Backwards-compat: existing 401 callers that don't read `locked_until` are unaffected.
- **The Phase 38 e101d8b proxy-headers fix is load-bearing for B4.** Without it, the rate limiter was per-edge-IP; with it, slowapi correctly keys per-client. The same `request.client.host` that drove the audit-log fix in Phase 38 is what `locked_until` will use to log the source of repeated failures. Make sure `start.sh` still has `--proxy-headers --forwarded-allow-ips '*'` in the uvicorn invocation — should be present post-Phase-38 e101d8b commit; defensive check before merging.

### Closeout reports back

- Backend test count delta (1442 → ?).
- Frontend bundle delta (only if FE touched for B4 UX — likely unchanged).
- Targeted suite results + full pytest sweep.
- Migration cycle test result.
- PG smoke `--mode both --prior-revision <id>` result.
- Demo-reset suite results.
- File-count.
- Backend deploy verification.
- API verify trio results (B1 + B2 timing measurement + B4 lockout).
- Browser verification status.
- Branch state + commit list.
- Production deploy status (Railway URL, prod sanity).
- Any new tech debt found.
- **Confirmation that all 4 clusters hold against their locked decisions; surface any deviations.**
- Pass-summary in PROGRESS.md style.

---

## Status block

The 2026-05-27 external review surfaced four identity-layer findings that share enough infrastructure to ship as one pass. Phase 37 closed the immediate priv-esc and three one-line bugs. Phase 38 closed five visibility/authorization gaps. Phase 39 closes the identity-lifecycle layer: how the platform represents "this user is active/banned/locked," how that state propagates through the auth-token lifecycle, and how the platform defends against credential stuffing at the username level (Phase 38 added the IP-level defense; Phase 39 adds the username-level defense to complete the policy).

Today's platform has no soft-revocation path for User accounts. The auth_utils `_get_user_from_token` and `refresh_token` paths re-fetch the User row but only check existence, not state — there's no `is_active` flag to consult. The only way to revoke a user today is `DELETE FROM users`, which FK constraints prevent in any non-trivial deployment. This means a compromised account can only be remediated by (a) password rotation by the legitimate user, or (b) rotating `SECRET_KEY` platform-wide (the Phase 37 hotfix did this once; doing it on every individual compromise is operationally untenable). Adding `is_active` closes this gap.

The forgot-password endpoint correctly returns identical response shapes in both branches (user-exists and user-doesn't-exist), but performs the SMTP/Resend email send inline in the user-exists branch (`routes/auth.py:618`). The send takes 100-500ms+; the no-user branch returns essentially immediately (line 596). Response-time measurement enumerates registered emails despite the matching response shape. The `register` endpoint already uses `BackgroundTasks` for the verification-email send (`auth.py:347`), so the fix is making `forgot-password` match — one-line move.

The ORM models for the Phase 18b retrofit tables (`Delegation`, `FollowRelationship`, `DelegationIntent`, `FollowRequest`) declare `org_id` as `nullable=True` (`Mapped[Optional[str]]`). The migration `e9419ee5906f` flipped these to NOT NULL on the DB side. `bash start.sh`'s fresh-DB branch runs `Base.metadata.create_all` before `alembic stamp head`, so a fresh deploy ends up with `org_id` nullable while an upgraded deploy ends up with it NOT NULL. The two schemas are silently different. Sync the ORM declarations to close this drift.

The soft-lockout columns (`failed_login_count`, `locked_until`) are the Phase 38 D13 deferral. Phase 38 added the per-IP rate limit (10/minute via slowapi); Phase 39 adds the per-username lockout (10 consecutive failures → 15-minute window). The two policies compound: an attacker needs to defeat both, which forces them into a slow-and-broad attack shape (many usernames, low per-IP rate) rather than the cheap-and-focused shape (one username, fast).

## Locked decisions

### B1 — `User.is_active` column + state checks (review §3.3)

- **D1 — `User.is_active: Mapped[bool] NOT NULL default True`.** Backfilled to True for all existing rows on upgrade. The column declaration includes `server_default="true"` so the migration's backfill is implicit at the SQL layer.
- **D2 — State check in `_get_user_from_token`.** Wherever the existing code calls `db.query(User).filter(User.id == user_id).first()` to resolve a token, add `.filter(User.is_active == True)`. Returns None for inactive users, which falls through to the existing 401 "Could not validate credentials" path. No new error code; reuse the existing posture.
- **D3 — State check in `refresh_token`.** Same shape — the existing user lookup gets `is_active == True` added to its filter chain. Inactive users get the same 401 they'd get from an invalid token.
- **D4 — No new endpoint to flip `is_active`.** Out of scope; an admin endpoint to revoke users belongs in a future ops-tooling pass. The DB-side `UPDATE users SET is_active = false WHERE id = ?` is the v1 mechanism, and CLAUDE.md's "Z runs prod queries via Railway PG console" pattern covers it.
- **D5 — `is_active=False` does not log the user out immediately.** Existing tokens stay valid through their natural expiry (15min for access tokens). The recheck happens on the next request via `_get_user_from_token`. This is the standard JWT tradeoff — we don't maintain a revocation list. For instant logout, the lever is `SECRET_KEY` rotation (Phase 37 demonstrated this).

### B2 — Forgot-password timing side-channel (review §3.4)

- **D6 — Move `send_password_reset_email(...)` into `BackgroundTasks`.** Signature change at `routes/auth.py:584`: add `background_tasks: BackgroundTasks` parameter to the route handler. Replace the inline `await send_password_reset_email(...)` with `background_tasks.add_task(send_password_reset_email, ...)`. Response returns before the email send.
- **D7 — `db.commit()` must happen before the response.** The reset token row is created in the existing branch — ensure the commit is BEFORE the response so the background task (which may run in a separate session) doesn't race with the commit. Pattern already established in `register` (`routes/auth.py:347`).

### B3 — ORM nullable=False alignment (review §3.5)

- **D8 — Sync the four tables: `Delegation`, `FollowRelationship`, `DelegationIntent`, `FollowRequest`.** In `backend/models.py`, find the `org_id` column declarations on each of these four ORM classes. Change `Mapped[Optional[str]] = mapped_column(ForeignKey(...), nullable=True)` to `Mapped[str] = mapped_column(ForeignKey(...), nullable=False, index=True)`. The migration is already in place (`e9419ee5906f`); this is declaration-only.
- **D9 — No migration in B3 itself.** The DB schema is already correct. This is ORM-side sync.
- **D10 — Verify via fresh-DB local deploy.** Spin up an empty SQLite database, run `start.sh` (or equivalent in a test fixture), assert the resulting schema has `org_id` NOT NULL on all four tables. A defensive integration test in `test_phase_39_identity_hardening.py` can use `inspect(db.bind).get_columns(table)` and check the `nullable` field.

### B4 — Soft-lockout columns + login-route wiring (review §2.3 deferred piece)

- **D11 — Add `User.failed_login_count: int NOT NULL default 0` and `User.locked_until: DateTime nullable`.** Both columns in the same migration as `is_active`. Backfill: `failed_login_count=0`, `locked_until=NULL` for all existing rows.
- **D12 — Login-route logic:**
  - On 200 (successful authenticate): set `failed_login_count=0`, `locked_until=NULL`.
  - On 401 (bad password): increment `failed_login_count`. If `failed_login_count >= 10`, set `locked_until = now + 15 minutes`.
  - Before authenticate: if `user.locked_until is not None AND user.locked_until > now`, return 401 with `detail={"reason": "account_locked", "locked_until": user.locked_until.isoformat()}`. Increment `failed_login_count` even for locked-account attempts (so a 30-minute attack window doesn't reset at the 15-minute lockout-expiry boundary).
- **D13 — Lockout window constant: `LOCKOUT_WINDOW_SECONDS = 900` (15 minutes).** In `routes/auth.py` near the other auth constants. Configurable via constant change; not surfaced to admin UI in this pass.
- **D14 — Lockout threshold constant: `LOCKOUT_THRESHOLD = 10`.** Same module. Tuneable.
- **D15 — Successful login resets state.** Per D12; this is the "you came back legitimately so we forget your past failures" path.
- **D16 — Lockout doesn't apply to nonexistent usernames.** If the User lookup returns None, the existing 401 path fires; no row to update, no lockout state to set. This prevents an attacker from creating phantom "locked" entries for usernames that don't exist. The Phase 38 B3 audit event still fires per its existing logic.
- **D17 — Password reset clears lockout.** The `reset_password` endpoint should set `failed_login_count=0, locked_until=NULL` on success. The legitimate user's path back to their account is unimpeded by the lockout.
- **D18 — Lockout 401 carries `locked_until` in response detail.** Per the operational watch-out — the FE can render "Your account is locked until X" when this field is present. Backwards-compat: existing FE that ignores the field still renders the generic "Invalid username or password" from the existing 401 shape.

## What this pass IS

- B1: `User.is_active` column add + state checks in `_get_user_from_token` and `refresh_token`.
- B2: `forgot-password` email send moved to `BackgroundTasks`.
- B3: ORM `nullable=False` sync on four Phase 18b tables.
- B4: `User.failed_login_count` + `User.locked_until` columns add + login-route wiring + reset-password lockout-clear.
- New migration: one Alembic revision adding the three User columns (one in B1, two in B4).
- New tests in `backend/tests/test_phase_39_identity_hardening.py`.
- Migration cycle test + PG smoke per CLAUDE.md.

## What this pass is NOT

- **Not an admin "revoke user" endpoint.** v1 mechanism is direct DB update via Railway PG console. Endpoint design belongs in a future ops-tooling pass.
- **Not a token revocation list.** JWT semantics preserved; `is_active=False` is checked on token decode, not via a persisted revocation set.
- **Not an exponential-backoff lockout.** Fixed 15-minute window per D13. Exponential backoff is a future refinement if abuse surfaces.
- **Not an account-recovery UX overhaul.** The existing password-reset flow is the recovery path; this pass just makes it clear lockout state on success per D17.
- **Not a session-management table.** Phase 38 demonstrated that `SECRET_KEY` rotation is the platform-wide revocation lever; per-user session listing/revocation belongs in a future pass.
- **Not a 2FA / MFA pass.** Out of scope.
- **Not a Pillow decompression-bomb fix** (review §3.8). Phase 40.
- **Not a demo-reset DB-level lock** (review §3.2). Phase 40.
- **Not a `WORKERS=1` startup assert** (review §3.1). Phase 40.
- **Not a scheduler health endpoint** (review §3.10). Phase 40.

## Cluster B — Backend

### B1 — `User.is_active` + state checks

**Migration:** new Alembic revision (let the lead generate the ID via `alembic revision -m "phase 39 identity hardening"`). Operations:

```python
def upgrade() -> None:
    op.add_column("users", sa.Column(
        "is_active", sa.Boolean(), nullable=False, server_default=sa.text("true"),
    ))
    # B4 columns ride along — see B4 below.
    op.add_column("users", sa.Column(
        "failed_login_count", sa.Integer(), nullable=False, server_default=sa.text("0"),
    ))
    op.add_column("users", sa.Column(
        "locked_until", sa.DateTime(timezone=False), nullable=True,
    ))

def downgrade() -> None:
    op.drop_column("users", "locked_until")
    op.drop_column("users", "failed_login_count")
    op.drop_column("users", "is_active")
```

`server_default` ensures the column is backfilled at the SQL layer; ORM-side `default=True` mirrors it. The down() drops cleanly per CLAUDE.md reversibility convention.

**Migration cycle test:** subprocess test pattern per CLAUDE.md — runs `upgrade → downgrade → upgrade` on SQLite. Add to `backend/tests/test_phase_39_identity_hardening.py::test_phase_39_migration_cycle`.

**Model declaration in `backend/models.py`:**

```python
is_active: Mapped[bool] = mapped_column(
    Boolean(), nullable=False, default=True, server_default=text("true"),
)
failed_login_count: Mapped[int] = mapped_column(
    Integer(), nullable=False, default=0, server_default=text("0"),
)
locked_until: Mapped[Optional[datetime]] = mapped_column(
    DateTime(timezone=False), nullable=True,
)
```

Place these alongside the existing User columns in `models.py`.

**State check in `_get_user_from_token`:** locate the function in `backend/auth_utils.py`. The existing pattern is:

```python
user = db.query(models.User).filter(models.User.id == user_id).first()
if user is None:
    raise credentials_exception
```

Update to:

```python
user = db.query(models.User).filter(
    models.User.id == user_id,
    models.User.is_active == True,  # Phase 39 B1 D2
).first()
if user is None:
    raise credentials_exception
```

Note `== True` not `is True` — SQLAlchemy filter expression vs. Python `is` operator.

**State check in `refresh_token`** (`routes/auth.py:419-446`): the existing code reads `rt.user_id` from the refresh-token row but doesn't re-fetch the User. Add:

```python
user = db.query(models.User).filter(
    models.User.id == rt.user_id,
    models.User.is_active == True,  # Phase 39 B1 D3
).first()
if user is None:
    raise HTTPException(status_code=401, detail="Could not validate credentials")
```

Before the existing `auth_utils.create_access_token(rt.user_id)` call.

### B2 — Forgot-password BackgroundTask

**File:** `backend/routes/auth.py` line 584.

Add `background_tasks: BackgroundTasks` to the route handler signature (FastAPI import already present at the top of the file from `register`'s usage). Replace the inline send:

```python
# Before:
await send_password_reset_email(user.email, token, settings.base_url)

# After:
background_tasks.add_task(
    send_password_reset_email, user.email, token, settings.base_url,
)
```

Ensure `db.commit()` happens BEFORE the response (the reset-token row needs to exist when the background task runs). Existing register pattern in `auth.py:347` is the reference shape.

**Test pattern:** `test_b2_forgot_password_timing_identical`. Issue 10 requests against a known-good email and 10 against an unknown email; assert p50 response time is within 20ms of each other (both branches should be sub-50ms post-fix). This is the regression net.

### B3 — ORM nullable=False alignment

**File:** `backend/models.py`. Find the `org_id` declarations on each of:

- `Delegation` (around line 681-687 per the review)
- `FollowRelationship` (around line 1023-1025)
- `DelegationIntent` (find the class; should be near Delegation)
- `FollowRequest` (find the class; should be near FollowRelationship)

For each, change:

```python
# Before:
org_id: Mapped[Optional[str]] = mapped_column(
    String, ForeignKey("organizations.id"), nullable=True, index=True,
)

# After:
org_id: Mapped[str] = mapped_column(
    String, ForeignKey("organizations.id"), nullable=False, index=True,
)
```

The DB schema is already NOT NULL post-`e9419ee5906f`; this is declaration sync only.

**Integration test:** assert `inspect(db.bind).get_columns(...)` shows `nullable=False` for the four tables' `org_id` columns. The test can use the existing test-DB fixture which goes through `create_all`.

### B4 — Soft-lockout login wiring

**File:** `backend/routes/auth.py`.

**Constants near the top of the file:**

```python
LOCKOUT_THRESHOLD = 10  # Phase 39 B4 D14
LOCKOUT_WINDOW_SECONDS = 15 * 60  # Phase 39 B4 D13
```

**Login route logic** (around line 364):

```python
@router.post("/login", response_model=schemas.TokenResponse)
@limiter.limit("10/minute")
def login(
    request: Request,
    form_data: OAuth2PasswordRequestForm = Depends(),
    invitation_token: Optional[str] = Form(default=None),
    db: Session = Depends(get_db),
):
    user = db.query(models.User).filter(
        models.User.username == form_data.username,
    ).first()

    # Phase 39 B4 D12 — lockout check (before authenticate).
    now = datetime.utcnow()
    if user is not None and user.locked_until is not None and user.locked_until > now:
        # Even locked-account attempts increment the counter (D12 — prevents
        # an attacker from gaming the 15-minute window by waiting it out
        # and continuing the attack from where they left off).
        user.failed_login_count += 1
        # Phase 38 B3 — failed-login audit event still fires.
        log_audit_event(
            db, action="user.login_failed",
            target_type="user", target_id=user.id, actor_id=None,
            details={
                "username": form_data.username,
                "reason": "account_locked",
                "locked_until": user.locked_until.isoformat(),
                "user_exists": True,
            },
            ip_address=request.client.host if request.client else None,
        )
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "reason": "account_locked",
                "locked_until": user.locked_until.isoformat(),
            },
        )

    if not user or not auth_utils.verify_password(form_data.password, user.password_hash):
        # Phase 38 B3 audit event.
        log_audit_event(
            db, action="user.login_failed",
            target_type="user",
            target_id=user.id if user else None,
            actor_id=None,
            details={
                "username": form_data.username,
                "user_exists": user is not None,
            },
            ip_address=request.client.host if request.client else None,
        )
        # Phase 39 B4 D12 — increment counter + set lockout if threshold hit.
        if user is not None:
            user.failed_login_count += 1
            if user.failed_login_count >= LOCKOUT_THRESHOLD:
                user.locked_until = now + timedelta(seconds=LOCKOUT_WINDOW_SECONDS)
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
        )

    # Successful auth — Phase 39 B4 D15 — reset state.
    user.failed_login_count = 0
    user.locked_until = None

    # ... existing audit + invitation consumption + token issuance ...
```

The structure: lockout-check → password-check → on-fail-update-counter / on-success-reset-counter.

**Password-reset clear** (B4 D17): in the `reset_password` endpoint (find via grep in `auth.py`), after the password is updated:

```python
user.failed_login_count = 0
user.locked_until = None
```

## Cluster T — Tests

**New file:** `backend/tests/test_phase_39_identity_hardening.py`. Required coverage (15-18 tests):

**B1 tests (4):**
- `test_b1_inactive_user_token_returns_401` — set `is_active=False` on a User with a valid access token; GET a protected endpoint with that token; expect 401.
- `test_b1_refresh_token_rejects_inactive_user` — set `is_active=False`; POST `/api/auth/refresh` with the user's refresh token; expect 401.
- `test_b1_active_user_unaffected` — sanity: normal user with `is_active=True` continues working.
- `test_b1_is_active_default_true_for_existing_users` — assert post-migration backfill: all existing rows have `is_active=True`.

**B2 tests (2):**
- `test_b2_forgot_password_known_email_returns_quickly` — POST forgot-password for a known email; assert response time < 50ms (use `time.perf_counter()`).
- `test_b2_forgot_password_unknown_email_returns_quickly` — same, for an unknown email; assert response time < 50ms. The pair locks in the timing-side-channel closure.

**B3 tests (1-2):**
- `test_b3_org_id_columns_not_nullable_on_fresh_create_all` — call `Base.metadata.create_all(engine)` against an empty SQLite, then `inspect(engine).get_columns("delegations")` and assert the `org_id` column's `nullable` is False. Same shape for the other three tables, parametrized.

**B4 tests (5-7):**
- `test_b4_lockout_triggers_after_10_failures` — POST `/api/auth/login` 10 times with bad password for one username; assert the 10th increments `failed_login_count` to 10 AND sets `locked_until` ~15min from now.
- `test_b4_lockout_persists_for_15_minutes` — after lockout, immediate retry returns 401 with `detail={"reason": "account_locked", ...}`.
- `test_b4_lockout_does_not_apply_to_nonexistent_username` — bad logins for `"username_that_doesnt_exist"` don't create a row, don't trigger lockout (the lockout-relevant state is per-user, not per-username-string).
- `test_b4_successful_login_resets_counter` — fail 5 times, then succeed; assert `failed_login_count=0` and `locked_until=None` post-success.
- `test_b4_lockout_counter_increments_during_lockout_window` — fail to 10 (lockout fires), then try once more during the window; assert counter increments to 11.
- `test_b4_password_reset_clears_lockout` — fail to 10 (lockout fires), complete password reset; assert `failed_login_count=0, locked_until=None`.

**Migration tests (1):**
- `test_phase_39_migration_cycle` — subprocess test running `alembic upgrade → downgrade → upgrade` on a fresh SQLite. Standard pattern from prior phases.

## Operational sequencing

Standard CLAUDE.md flow. Notable points:

- **PG smoke required.** Identify the prior revision (most recent migration ID at master HEAD) via `ls backend/migrations/versions/ | tail`. Run `python backend/scripts/pg_smoke.py --mode both --prior-revision <id>` per CLAUDE.md migration convention. Both `--mode upgrade` and `--mode fresh` must pass.
- **No SECRET_KEY rotation this pass.** Phase 37 was a one-time hotfix; ordinary code changes don't need it.
- **Demo reset post-deploy required.** The new User columns must not break demo persona logins.
- **Bundle hash should NOT change.** Backend-only pass. If FE touched for B4 D18 UX (rendering `locked_until` to the user), bundle changes — flag in closeout.

## Followups (out of scope this pass)

Per the external-review remediation roadmap:

- **Phase 40 — Ops + multi-instance prep:** demo-reset DB-level lock (§3.2), Pillow decompression-bomb defense (§3.8), scheduler health endpoint (§3.10), `WORKERS=1` startup assert (§3.1), §4 minor items batched. The Phase 37 audit-log IP forensics item is already closed via Phase 38's `e101d8b` proxy-headers fix — Phase 40's queue is one item lighter than originally planned.
- **Admin "revoke user" endpoint.** v1 mechanism is direct DB update; build an admin UI for it once user volume warrants.
- **Exponential-backoff lockout.** Fixed 15-min window for v1; refine if abuse surfaces.
- **Locked-account UX in the frontend.** B4 D18 includes `locked_until` in the response detail; a future FE pass can render it as a user-facing message. Not load-bearing for the security improvement.
- **`demo_users` endpoint sources from `Organization.personas`** — Phase 38 closeout's Tier-3 tech debt. Batch into a future cleanup pass.
- **`_eligible_viewers_for_proposal` promotion out of `routes/comments.py`** — Phase 38 closeout's structural-cleanup item. Batch into a future cleanup pass.
- **WebSocket FE wiring** — Phase 38 surfaced that `/ws/proposals/{id}` is plumbed but unconsumed. Either wire the FE for live tally updates or delete the dead plumbing. Decide consciously rather than letting it sit.
- **Cross-sub-org delegation chain audit** — external review §6 uncertain item. Worth a dedicated read-pass once Phase 40 lands.
