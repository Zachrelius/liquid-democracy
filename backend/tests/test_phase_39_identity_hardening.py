"""Phase 39 — Identity hardening regression tests.

Covers B1 (User.is_active + state checks in _get_user_from_token and
refresh_token), B2 (forgot-password BackgroundTasks timing), B3 (ORM
nullable=False sync on the four Phase 18b tables), B4 (User.failed_login_count
+ locked_until + login-route wiring + password-reset clear).

Spec: phase39_identity_hardening_spec.md §"Cluster T".
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import auth as auth_utils
import models
from database import Base, get_db
from main import app


_BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_PHASE_39_REVISION = "4b0bf8f1761f"
_PRIOR_REVISION = "b6d8e2f1a350"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="function")
def test_db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)


@pytest.fixture(scope="function")
def client(test_db):
    def override_get_db():
        try:
            yield test_db
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app)
    app.dependency_overrides.clear()


def _make_user(db, username: str, *, password: str = "test1234") -> models.User:
    u = models.User(
        username=username,
        display_name=username.title(),
        password_hash=auth_utils.hash_password(password),
        email=f"{username}@test.example",
        email_verified=True,
    )
    db.add(u)
    db.flush()
    return u


def _auth(user) -> dict:
    return {"Authorization": f"Bearer {auth_utils.create_access_token(user.id)}"}


def _login(client, username: str, password: str) -> object:
    return client.post(
        "/api/auth/login",
        data={"username": username, "password": password},
    )


def _reset_slowapi():
    """Phase 38 B3 + Phase 39 B4 interaction: the per-IP slowapi 10/minute
    on /login fires after 10 attempts, before the per-username lockout
    check can be exercised. The conftest autouse fixture resets between
    tests, but within a single test that exercises the 11th-attempt
    behavior we need an explicit mid-test reset.
    """
    from routes import auth as auth_routes
    from main import limiter as main_limiter
    auth_routes.limiter.reset()
    main_limiter.reset()


# ===========================================================================
# B1 — User.is_active + state guards
# ===========================================================================


def test_b1_inactive_user_token_returns_401(client, test_db):
    """An access token issued before is_active flipped to False must be
    rejected on the next protected-endpoint use. Closes the gap that
    pre-Phase-39 had no way to revoke a compromised account short of
    DELETE FROM users (which FK constraints block in any real deploy).
    """
    user = _make_user(test_db, "b1_inactive")
    test_db.commit()
    token_headers = _auth(user)

    # Active user — protected endpoint returns 200.
    resp = client.get("/api/auth/me", headers=token_headers)
    assert resp.status_code == 200, resp.text

    # Flip is_active to False.
    user.is_active = False
    test_db.commit()

    # Same token, same endpoint → 401.
    resp = client.get("/api/auth/me", headers=token_headers)
    assert resp.status_code == 401


def test_b1_refresh_token_rejects_inactive_user(client, test_db):
    """The refresh path now re-checks User.is_active before issuing fresh
    access tokens. Pre-Phase-39 a flipped-to-inactive user would keep
    silently refreshing for the lifetime of their refresh token (~30 days).
    """
    user = _make_user(test_db, "b1_refresh_inactive")
    test_db.commit()

    # Obtain a refresh token via the normal login flow.
    resp = _login(client, "b1_refresh_inactive", "test1234")
    assert resp.status_code == 200, resp.text
    refresh_token = resp.json()["refresh_token"]

    # Refresh works while active.
    resp = client.post("/api/auth/refresh", json={"refresh_token": refresh_token})
    assert resp.status_code == 200, resp.text
    new_refresh = resp.json()["refresh_token"]

    # Flip is_active to False; refresh now fails.
    user.is_active = False
    test_db.commit()

    resp = client.post("/api/auth/refresh", json={"refresh_token": new_refresh})
    assert resp.status_code == 401


def test_b1_active_user_unaffected(client, test_db):
    """Regression net: a normal active user continues working — the new
    state-check filter doesn't accidentally reject anyone with the column
    at its server_default True value."""
    user = _make_user(test_db, "b1_active_sanity")
    test_db.commit()

    resp = client.get("/api/auth/me", headers=_auth(user))
    assert resp.status_code == 200
    body = resp.json()
    assert body["username"] == "b1_active_sanity"


def test_b1_is_active_default_true_for_new_users(test_db):
    """New User() rows get is_active=True via the ORM default (no explicit
    set in seed paths). Mirrors the server_default that backfills existing
    rows on upgrade."""
    user = _make_user(test_db, "b1_default_true")
    test_db.commit()
    test_db.refresh(user)
    assert user.is_active is True


# ===========================================================================
# B2 — forgot-password timing side-channel closed
# ===========================================================================


def test_b2_forgot_password_uses_background_tasks_for_known_email(
    client, test_db, monkeypatch,
):
    """Known-email branch must enqueue ``send_password_reset_email`` via
    ``BackgroundTasks.add_task`` — NOT call it inline. Pre-Phase-39 the
    inline ``await`` made the known-email response 100-500ms slower than
    the unknown-email response, creating a timing side-channel for
    enumerating registered emails.

    The straight "measure response time with TestClient" test the spec
    sketched is unusable: TestClient blocks on background tasks before
    returning from ``.post()`` (well-documented FastAPI behavior), so a
    slow stub would slow the .post() too. Instead, mock
    ``BackgroundTasks.add_task`` and assert the email-send function was
    enqueued via it. Behavior-equivalent and TestClient-compatible.
    """
    from fastapi import BackgroundTasks
    from routes import auth as auth_route

    _make_user(test_db, "b2_known")
    test_db.commit()

    calls: list = []
    real_add_task = BackgroundTasks.add_task

    def _spy_add_task(self, func, *args, **kwargs):
        calls.append((func, args, kwargs))
        return real_add_task(self, func, *args, **kwargs)

    monkeypatch.setattr(BackgroundTasks, "add_task", _spy_add_task)

    resp = client.post(
        "/api/auth/forgot-password", json={"email": "b2_known@test.example"},
    )
    assert resp.status_code == 200, resp.text

    # The email-send was enqueued via BackgroundTasks, not awaited inline.
    matched = [
        c for c in calls
        if getattr(c[0], "__name__", "") == "send_password_reset_email"
    ]
    assert len(matched) == 1, (
        f"Expected send_password_reset_email enqueued via BackgroundTasks "
        f"exactly once; saw {len(matched)}. If this regresses, the email "
        f"send was re-inlined into the request path and the timing "
        f"side-channel is back."
    )


def test_b2_forgot_password_unknown_email_returns_200_without_email_send(
    client, test_db, monkeypatch,
):
    """Unknown-email branch returns 200 (same response shape as the known-
    email branch — Phase 36 anti-enumeration posture) without enqueuing
    any background task. Paired with the known-email test above, the two
    confirm the route's behavior split is structural, not timing-based:
    both branches return identical 200 responses; only the known branch
    queues the email send.
    """
    from fastapi import BackgroundTasks

    calls: list = []
    real_add_task = BackgroundTasks.add_task

    def _spy_add_task(self, func, *args, **kwargs):
        calls.append((func, args, kwargs))
        return real_add_task(self, func, *args, **kwargs)

    monkeypatch.setattr(BackgroundTasks, "add_task", _spy_add_task)

    resp = client.post(
        "/api/auth/forgot-password",
        json={"email": "no-such-user@test.example"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json() == {
        "message": (
            "If that email is registered, we've sent a password reset link."
        ),
    }

    # No background task was enqueued (no email send, no reset row to write).
    email_calls = [
        c for c in calls
        if getattr(c[0], "__name__", "") == "send_password_reset_email"
    ]
    assert email_calls == [], (
        "Unknown-email branch enqueued an email-send task — that's a "
        "behavior regression that leaks 'this email isn't registered' "
        "by absence of a task."
    )


# ===========================================================================
# B3 — ORM nullable=False sync on the four Phase 18b tables
# ===========================================================================


@pytest.mark.parametrize(
    "table",
    [
        "delegations",
        "follow_requests",
        "follow_relationships",
        "delegation_intents",
    ],
)
def test_b3_org_id_not_nullable_on_fresh_create_all(table):
    """Fresh Base.metadata.create_all() must produce org_id NOT NULL on all
    four Phase 18b retrofit tables. Pre-Phase-39 these were declared
    nullable=True in the ORM (a holdover from Phase 18a), so the fresh-DB
    branch of start.sh built a schema that drifted from the upgraded-DB
    branch (where the e9419ee5906f migration had already flipped the
    columns to NOT NULL).
    """
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    cols = {c["name"]: c["nullable"] for c in inspect(engine).get_columns(table)}
    assert "org_id" in cols, f"{table}.org_id column missing"
    assert cols["org_id"] is False, (
        f"{table}.org_id is nullable on fresh create_all(); the ORM model "
        f"declaration drifted from the migrated DB shape (NOT NULL post-"
        f"e9419ee5906f). Sync the Mapped[Optional[str]] declaration to "
        f"Mapped[str] with nullable=False."
    )


# ===========================================================================
# B4 — Soft-lockout
# ===========================================================================


def test_b4_lockout_triggers_after_10_failures(client, test_db):
    """The 10th consecutive bad-password attempt sets locked_until to
    ~15 minutes from now. Counter advances to 10 (D14 threshold)."""
    user = _make_user(test_db, "b4_lockout_trigger")
    test_db.commit()
    user_id = user.id

    for i in range(10):
        resp = _login(client, "b4_lockout_trigger", "wrong")
        assert resp.status_code == 401, f"attempt {i + 1}: {resp.text}"

    test_db.expire_all()
    fresh = test_db.get(models.User, user_id)
    assert fresh.failed_login_count == 10
    assert fresh.locked_until is not None
    # ~15 minutes from now (allow a few seconds of test wallclock slack).
    expected = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(minutes=15)
    delta = abs((fresh.locked_until - expected).total_seconds())
    assert delta < 5.0, f"locked_until={fresh.locked_until} expected~{expected}"


def test_b4_lockout_persists_for_15_minutes(client, test_db):
    """After lockout fires, immediate retry returns 401 with
    detail.reason='account_locked' + locked_until in the response detail.
    """
    user = _make_user(test_db, "b4_lockout_persists")
    test_db.commit()

    for _ in range(10):
        _login(client, "b4_lockout_persists", "wrong")
    _reset_slowapi()  # Phase 38 B3 cap exhausted; reset before 11th check.

    # 11th attempt — locked.
    resp = _login(client, "b4_lockout_persists", "wrong")
    assert resp.status_code == 401
    detail = resp.json()["detail"]
    assert isinstance(detail, dict), f"expected dict detail, got {detail!r}"
    assert detail["reason"] == "account_locked"
    assert "locked_until" in detail
    # Even the correct password is rejected while locked.
    resp = _login(client, "b4_lockout_persists", "test1234")
    assert resp.status_code == 401
    assert resp.json()["detail"]["reason"] == "account_locked"


def test_b4_lockout_does_not_apply_to_nonexistent_username(client, test_db):
    """Lockout state is per-User row. A nonexistent username can be
    probed arbitrarily without creating phantom locked entries — the
    existing 401 ('Invalid username or password') fires unchanged."""
    for i in range(15):
        if i == 10:
            _reset_slowapi()  # avoid the per-IP 10/min cap masking the test
        resp = _login(client, "no-such-user-b4", "wrong")
        assert resp.status_code == 401

    # No phantom row created.
    ghost = test_db.query(models.User).filter(
        models.User.username == "no-such-user-b4",
    ).first()
    assert ghost is None


def test_b4_successful_login_resets_counter(client, test_db):
    """Fail 5 times, then succeed. failed_login_count resets to 0 and
    locked_until stays None (never tripped). D15 — legitimate login wipes
    failure history."""
    user = _make_user(test_db, "b4_reset_on_success")
    test_db.commit()
    user_id = user.id

    for _ in range(5):
        _login(client, "b4_reset_on_success", "wrong")
    test_db.expire_all()
    assert test_db.get(models.User, user_id).failed_login_count == 5

    resp = _login(client, "b4_reset_on_success", "test1234")
    assert resp.status_code == 200, resp.text

    test_db.expire_all()
    fresh = test_db.get(models.User, user_id)
    assert fresh.failed_login_count == 0
    assert fresh.locked_until is None


def test_b4_lockout_counter_increments_during_lockout_window(client, test_db):
    """Attempts during the 15-min window still increment the counter so an
    attacker can't pause-and-resume across the boundary. After 10 → locked,
    11th attempt → 11 counter."""
    user = _make_user(test_db, "b4_increment_during_lock")
    test_db.commit()
    user_id = user.id

    for _ in range(10):
        _login(client, "b4_increment_during_lock", "wrong")
    test_db.expire_all()
    assert test_db.get(models.User, user_id).failed_login_count == 10

    # 11th attempt — locked + counter bumps to 11. Reset the per-IP cap
    # first so it isn't the layer that rejects the 11th attempt.
    _reset_slowapi()
    _login(client, "b4_increment_during_lock", "wrong")
    test_db.expire_all()
    assert test_db.get(models.User, user_id).failed_login_count == 11


def test_b4_password_reset_clears_lockout(client, test_db):
    """D17 — a successful password reset clears failed_login_count + locked_until.
    Legitimate user back-channel to their account isn't blocked by the
    per-username counter."""
    user = _make_user(test_db, "b4_reset_clears")
    test_db.commit()
    user_id = user.id

    # Lock the user out.
    for _ in range(10):
        _login(client, "b4_reset_clears", "wrong")
    test_db.expire_all()
    locked = test_db.get(models.User, user_id)
    assert locked.locked_until is not None

    # Generate a password-reset token directly (bypass the email flow).
    reset = models.PasswordReset(
        user_id=user_id,
        token="reset-tok-b4",
        expires_at=datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=1),
    )
    test_db.add(reset)
    test_db.commit()

    resp = client.post(
        "/api/auth/reset-password",
        json={"token": "reset-tok-b4", "new_password": "newpass1234"},
    )
    assert resp.status_code == 200, resp.text

    test_db.expire_all()
    fresh = test_db.get(models.User, user_id)
    assert fresh.failed_login_count == 0
    assert fresh.locked_until is None


# ===========================================================================
# Migration cycle test
# ===========================================================================


def _run_alembic(db_url: str, *args: str) -> None:
    env = dict(os.environ)
    env["DATABASE_URL"] = db_url
    res = subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=_BACKEND_DIR, env=env, capture_output=True, text=True,
    )
    assert res.returncode == 0, (
        f"alembic {' '.join(args)} failed:\nSTDOUT:\n{res.stdout}\n"
        f"STDERR:\n{res.stderr}"
    )


def _create_all_subprocess(db_url: str) -> None:
    code = (
        f"import os; os.environ['DATABASE_URL']={db_url!r}; "
        "from database import create_tables; create_tables()"
    )
    res = subprocess.run(
        [sys.executable, "-c", code],
        cwd=_BACKEND_DIR, capture_output=True, text=True,
    )
    assert res.returncode == 0, (
        f"create_tables failed:\nSTDOUT:\n{res.stdout}\nSTDERR:\n{res.stderr}"
    )


def _has_column(engine, table: str, column: str) -> bool:
    insp = sa.inspect(engine)
    if table not in set(insp.get_table_names()):
        return False
    return column in {c["name"] for c in insp.get_columns(table)}


def test_phase_39_migration_cycle():
    """upgrade → downgrade → upgrade leaves the three Phase 39 columns
    correctly present/absent at each step. Pure column-add migration, so
    the cycle is structural; no data transform to assert.
    """
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db_url = f"sqlite:///{path}"
    try:
        # Today's create_tables() builds the full schema including Phase 39
        # columns. Stamping at head establishes alembic at the post-Phase-39
        # revision; the downgrade below exercises the actual migration code.
        _create_all_subprocess(db_url)
        _run_alembic(db_url, "stamp", "head")

        engine = sa.create_engine(db_url)
        try:
            for col in ("is_active", "failed_login_count", "locked_until"):
                assert _has_column(engine, "users", col), (
                    f"Phase 39 column users.{col} missing post create_tables + "
                    "stamp head — model declarations may have drifted."
                )
        finally:
            engine.dispose()

        # Downgrade to prior — Phase 39 columns drop.
        _run_alembic(db_url, "downgrade", _PRIOR_REVISION)
        engine = sa.create_engine(db_url)
        try:
            for col in ("is_active", "failed_login_count", "locked_until"):
                assert not _has_column(engine, "users", col), (
                    f"Phase 39 column users.{col} should be absent after "
                    f"downgrade to {_PRIOR_REVISION}; the migration's "
                    "downgrade() may not be dropping it."
                )
        finally:
            engine.dispose()

        # Re-upgrade — columns return; idempotent.
        _run_alembic(db_url, "upgrade", "head")
        engine = sa.create_engine(db_url)
        try:
            for col in ("is_active", "failed_login_count", "locked_until"):
                assert _has_column(engine, "users", col)
        finally:
            engine.dispose()
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass
