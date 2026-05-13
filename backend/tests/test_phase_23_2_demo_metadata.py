"""Phase 23.2 — demo metadata expansion + reset autonomy tests.

This pass starts with the B0 (token-gated reset trigger) tests. B1-B5
cluster tests will be added in later commits as those workstreams ship.

B0 covers ``POST /api/demo/trigger-reset`` — the bearer-token path that
lets the Code team trigger a demo reset without admin credentials. The
endpoint reuses ``run_demo_reset_if_due(db, force=True)`` so the auth
layer is the only thing under test here; the reset pipeline itself is
already covered in test_phase_23_demo_reset.py.

Tests in this file:
  - TestB0TokenAuthMissingHeader — 401 when no Authorization header.
  - TestB0TokenAuthInvalidToken — 401 when token doesn't match.
  - TestB0TokenAuthValidTokenTriggersReset — 200 + DemoResetResult shape
    when token matches; mocks the reset call to avoid full-pipeline cost.
  - TestB0NoTokenConfigured — 503 when the env var is unset on this
    environment (defensive path; the endpoint should refuse to operate
    rather than fall through to an unauthenticated reset).
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest import mock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from database import Base, get_db
from demo_reset_job import DemoResetResult
from main import app


# ---------------------------------------------------------------------------
# Fixtures (mirror the pattern in test_phase_23_demo_reset.py)
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


def _fake_reset_result() -> DemoResetResult:
    """Construct a DemoResetResult that mimics a successful reset; used to
    short-circuit the real pipeline in the success-path token test."""
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    return DemoResetResult(
        success=True,
        started_at=now,
        completed_at=now,
        orgs_reset=[
            "demo-cedar-hollow",
            "demo-local-4021",
            "demo-westgate-coalition",
        ],
        rows_wiped=42,
        rows_seeded=99,
        error=None,
        skipped=False,
        reason=None,
    )


# ---------------------------------------------------------------------------
# B0 — token-auth on POST /api/demo/trigger-reset
# ---------------------------------------------------------------------------


class TestB0TokenAuthMissingHeader:
    """No Authorization header at all returns 401, regardless of token
    configuration on the environment."""

    def test_missing_header_returns_401(self, client, monkeypatch):
        monkeypatch.setenv("DEMO_RESET_TRIGGER_TOKEN", "test-token-xyz")
        resp = client.post("/api/demo/trigger-reset")
        assert resp.status_code == 401
        body = resp.json()
        assert "authorization" in body["detail"].lower()

    def test_malformed_header_returns_401(self, client, monkeypatch):
        """Header present but doesn't start with 'Bearer ' — still 401."""
        monkeypatch.setenv("DEMO_RESET_TRIGGER_TOKEN", "test-token-xyz")
        resp = client.post(
            "/api/demo/trigger-reset",
            headers={"Authorization": "Basic abc"},
        )
        assert resp.status_code == 401


class TestB0TokenAuthInvalidToken:
    """Authorization header present and Bearer-shaped, but token mismatches
    the configured value — 401 with a generic 'invalid token' message that
    does NOT echo the provided value."""

    def test_wrong_token_returns_401(self, client, monkeypatch):
        monkeypatch.setenv("DEMO_RESET_TRIGGER_TOKEN", "correct-token-abc")
        wrong = "wrong-token-supplied"
        resp = client.post(
            "/api/demo/trigger-reset",
            headers={"Authorization": f"Bearer {wrong}"},
        )
        assert resp.status_code == 401
        body = resp.json()
        assert "invalid token" in body["detail"].lower()
        # Never echo the provided value back in the response — would help
        # an attacker confirm partial matches via timing+content side channel.
        assert wrong not in body["detail"]


class TestB0TokenAuthValidTokenTriggersReset:
    """Correct token + Bearer header — 200 with the DemoResetResult JSON
    shape. The actual reset is mocked so this test focuses on the auth
    plumbing + response serialization, not the reset pipeline itself."""

    def test_valid_token_triggers_reset_and_returns_audit_shape(
        self, client, monkeypatch
    ):
        monkeypatch.setenv("DEMO_RESET_TRIGGER_TOKEN", "valid-token-123")

        fake = _fake_reset_result()
        with mock.patch(
            "demo_reset_job.run_demo_reset_if_due", return_value=fake
        ) as mocked:
            resp = client.post(
                "/api/demo/trigger-reset",
                headers={"Authorization": "Bearer valid-token-123"},
            )

        assert resp.status_code == 200, resp.text
        body = resp.json()
        # Response shape matches the admin endpoint at /api/admin/demo/reset.
        assert body["success"] is True
        assert body["orgs_reset"] == [
            "demo-cedar-hollow",
            "demo-local-4021",
            "demo-westgate-coalition",
        ]
        assert body["rows_wiped"] == 42
        assert body["rows_seeded"] == 99
        assert body["error"] is None
        assert body["skipped"] is False
        assert body["reason"] is None
        # started_at / completed_at are ISO strings (not raw datetimes).
        datetime.fromisoformat(body["started_at"])
        datetime.fromisoformat(body["completed_at"])

        # The endpoint MUST call run_demo_reset_if_due with force=True and
        # NO actor_id (token auth has no human user).
        mocked.assert_called_once()
        call_kwargs = mocked.call_args.kwargs
        assert call_kwargs.get("force") is True
        # actor_id is either explicitly None or absent (default None).
        assert call_kwargs.get("actor_id") is None


class TestB0NoTokenConfigured:
    """Environment without DEMO_RESET_TRIGGER_TOKEN — endpoint refuses to
    operate (503), never falls through to an unauthenticated reset."""

    def test_unset_token_returns_503(self, client, monkeypatch):
        monkeypatch.delenv("DEMO_RESET_TRIGGER_TOKEN", raising=False)
        resp = client.post(
            "/api/demo/trigger-reset",
            headers={"Authorization": "Bearer anything"},
        )
        assert resp.status_code == 503
        body = resp.json()
        assert "not configured" in body["detail"].lower()
