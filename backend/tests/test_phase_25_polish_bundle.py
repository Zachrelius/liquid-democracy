"""Phase 25 — polish bundle tests.

Covers backend clusters B1 (duration override consumption at advance time),
B2 (0-day deliberation skip at create time), B3 (env-driven uploads path),
and B4 (PATCH duration floor validation). B5 was a no-op verification
(Phase 23.2 already aligned STV tests); F1/F2/F3 are frontend-only.

Uses real ``models.Proposal`` rows on an in-memory SQLite database per
the Phase 17 fixture-shape lesson.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from unittest import mock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import StaticPool

import auth as auth_utils
import models
from database import Base, get_db
from main import app
from routes.proposals import _compute_voting_end_at_advance
from tests.conftest import make_org_membership


_DUMMY_HASH = "$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/lewrwKJuRxm5pJmJi"


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="function")
def db():
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


def _now_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _user(db: Session, username: str, *, is_admin: bool = False) -> models.User:
    u = models.User(
        username=username,
        display_name=username.title(),
        password_hash=_DUMMY_HASH,
        email=f"{username}@test.example",
        email_verified=True,
        is_admin=is_admin,
    )
    db.add(u)
    db.flush()
    return u


def _org(db: Session, slug: str, **settings) -> models.Organization:
    org = models.Organization(
        name=f"Org {slug}",
        slug=slug,
        description="",
        join_policy="open",
        settings={
            "default_deliberation_days": settings.get("default_deliberation_days", 7),
            "default_voting_days": settings.get("default_voting_days", 7),
            "stable_result_enabled_default": False,
            "stable_window_fraction": 0.25,
            "max_extension_fraction": 0.25,
        },
    )
    db.add(org)
    db.flush()
    return org


def _voting_proposal(
    db: Session,
    *,
    org: models.Organization,
    author: models.User,
    voting_method: str = "binary",
    deliberation_days: float | None = None,
    voting_days: float | None = None,
    status: str = "deliberation",
) -> models.Proposal:
    now = _now_naive()
    p = models.Proposal(
        title="P",
        body="",
        author_id=author.id,
        org_id=org.id,
        voting_method=voting_method,
        status=status,
        deliberation_days=deliberation_days,
        voting_days=voting_days,
        deliberation_start=now - timedelta(hours=2),
        pass_threshold=0.5,
        quorum_threshold=0.0,
    )
    db.add(p)
    db.flush()
    return p


# ===========================================================================
# B1 — Duration override consumption at advance time
# ===========================================================================

class TestAdvanceUsesVotingDaysOverride:
    """A proposal carrying voting_days=0.05 should produce a voting_end
    72 minutes after voting_start when advanced — NOT the org default."""

    def test_voting_end_derived_from_override(self, db):
        author = _user(db, "alice")
        org = _org(db, "ovr", default_voting_days=7)
        proposal = _voting_proposal(
            db, org=org, author=author, voting_days=0.05,
        )
        voting_start = _now_naive()
        result = _compute_voting_end_at_advance(
            voting_start=voting_start,
            body_voting_end=None,
            proposal=proposal,
            org=org,
        )
        delta_seconds = (result - voting_start).total_seconds()
        # 0.05 days = 72 minutes = 4320 seconds.
        assert 4319 <= delta_seconds <= 4321, (
            f"expected ~4320s window for voting_days=0.05; got {delta_seconds}s"
        )


class TestAdvanceFallsBackToOrgDefault:
    """Proposal with voting_days=None falls back to org.default_voting_days."""

    def test_voting_end_from_org_default(self, db):
        author = _user(db, "alice")
        org = _org(db, "deflt", default_voting_days=3)
        proposal = _voting_proposal(
            db, org=org, author=author, voting_days=None,
        )
        voting_start = _now_naive()
        result = _compute_voting_end_at_advance(
            voting_start=voting_start,
            body_voting_end=None,
            proposal=proposal,
            org=org,
        )
        delta_days = (result - voting_start).total_seconds() / 86400
        assert 2.99 <= delta_days <= 3.01, (
            f"expected 3-day window from org default; got {delta_days:.4f}"
        )


class TestAdvanceHonorsBodyVotingEnd:
    """When body.voting_end is supplied, it wins (with a deprecation log)."""

    def test_body_voting_end_takes_precedence(self, db, caplog):
        import logging
        author = _user(db, "alice")
        org = _org(db, "bod", default_voting_days=7)
        proposal = _voting_proposal(
            db, org=org, author=author, voting_days=0.05,
        )
        voting_start = _now_naive()
        custom_end = voting_start + timedelta(days=14)
        with caplog.at_level(logging.WARNING, logger="routes.proposals"):
            result = _compute_voting_end_at_advance(
                voting_start=voting_start,
                body_voting_end=custom_end,
                proposal=proposal,
                org=org,
            )
        assert result == custom_end
        assert any(
            "body.voting_end is deprecated" in rec.message
            for rec in caplog.records
        ), "expected a deprecation warning when body.voting_end was honored"


class TestAdvanceRejectsZeroVotingDays:
    """When the proposal AND the org both resolve to <=0 voting_days, the
    helper returns 400 (org configuration error)."""

    def test_400_on_zero_voting_days(self, db):
        from fastapi import HTTPException
        author = _user(db, "alice")
        # Org with default_voting_days=0 — degenerate case.
        org = _org(db, "zero", default_voting_days=0)
        proposal = _voting_proposal(
            db, org=org, author=author, voting_days=None,
        )
        with pytest.raises(HTTPException) as exc_info:
            _compute_voting_end_at_advance(
                voting_start=_now_naive(),
                body_voting_end=None,
                proposal=proposal,
                org=org,
            )
        assert exc_info.value.status_code == 400
        assert "voting_days" in exc_info.value.detail.lower()


# ===========================================================================
# B2 — 0-day deliberation skip at create time
# ===========================================================================

def _make_client(db: Session) -> TestClient:
    """TestClient with the get_db dependency overridden to the test session."""
    def _override_db():
        try:
            yield db
        finally:
            pass
    app.dependency_overrides[get_db] = _override_db
    return TestClient(app)


def _login_token(db: Session, user: models.User) -> str:
    return auth_utils.create_access_token(user.id)


class TestZeroDayDeliberationSkipsPhase:
    """A proposal created via POST /api/orgs/{slug}/proposals with
    deliberation_days=0 is created directly in 'voting' status."""

    def test_create_with_zero_delib_starts_in_voting(self, db):
        author = _user(db, "alice")
        org = _org(db, "skip", default_voting_days=7)
        make_org_membership(
            db, org_id=org.id, user_id=author.id,
            role="steward", status="active",
        )
        db.commit()
        client = _make_client(db)
        token = _login_token(db, author)
        try:
            resp = client.post(
                f"/api/orgs/{org.slug}/proposals",
                json={
                    "title": "Quick skip",
                    "body": "",
                    "voting_method": "binary",
                    "topics": [],
                    "deliberation_days": 0,
                    "voting_days": 0.05,
                },
                headers={"Authorization": f"Bearer {token}"},
            )
            assert resp.status_code == 201, resp.text
            body = resp.json()
            assert body["status"] == "voting"
            # voting_end was computed from voting_days=0.05.
            assert body["voting_end"] is not None
            assert body["voting_start"] is not None
            assert body["deliberation_start"] is not None
        finally:
            app.dependency_overrides.pop(get_db, None)


class TestZeroDayDeliberationAuditLogSingleEvent:
    """Skip path emits ONE proposal.status_changed audit event (draft ->
    voting), NOT two events at the same timestamp."""

    def test_single_status_changed_event(self, db):
        author = _user(db, "alice")
        org = _org(db, "auditone")
        make_org_membership(
            db, org_id=org.id, user_id=author.id,
            role="steward", status="active",
        )
        db.commit()
        client = _make_client(db)
        token = _login_token(db, author)
        try:
            resp = client.post(
                f"/api/orgs/{org.slug}/proposals",
                json={
                    "title": "Quick skip audit",
                    "body": "",
                    "voting_method": "binary",
                    "topics": [],
                    "deliberation_days": 0,
                    "voting_days": 0.05,
                },
                headers={"Authorization": f"Bearer {token}"},
            )
            assert resp.status_code == 201, resp.text
            proposal_id = resp.json()["id"]
        finally:
            app.dependency_overrides.pop(get_db, None)

        rows = (
            db.query(models.AuditLog)
            .filter(
                models.AuditLog.action == "proposal.status_changed",
                models.AuditLog.target_id == proposal_id,
            )
            .all()
        )
        assert len(rows) == 1, (
            f"expected exactly 1 status_changed event; got {len(rows)}"
        )
        details = rows[0].details or {}
        assert details.get("old_status") == "draft"
        assert details.get("new_status") == "voting"
        assert details.get("trigger") == "zero_day_deliberation_skip"


class TestNonZeroDeliberationGoesToDraft:
    """Existing behavior preserved: non-zero deliberation_days leaves the
    proposal in 'draft' status at creation."""

    def test_non_zero_delib_keeps_draft(self, db):
        author = _user(db, "alice")
        org = _org(db, "draft")
        make_org_membership(
            db, org_id=org.id, user_id=author.id,
            role="steward", status="active",
        )
        db.commit()
        client = _make_client(db)
        token = _login_token(db, author)
        try:
            resp = client.post(
                f"/api/orgs/{org.slug}/proposals",
                json={
                    "title": "Slow start",
                    "body": "",
                    "voting_method": "binary",
                    "topics": [],
                    "deliberation_days": 1,
                    "voting_days": 7,
                },
                headers={"Authorization": f"Bearer {token}"},
            )
            assert resp.status_code == 201, resp.text
            body = resp.json()
            assert body["status"] == "draft"
            assert body["voting_end"] is None
        finally:
            app.dependency_overrides.pop(get_db, None)


class TestOrgDefaultZeroDeliberation:
    """Org with default_deliberation_days=0 + proposer doesn't override =>
    proposal still skips deliberation."""

    def test_org_default_zero_skips(self, db):
        author = _user(db, "alice")
        org = _org(db, "orgskip", default_deliberation_days=0, default_voting_days=1)
        make_org_membership(
            db, org_id=org.id, user_id=author.id,
            role="steward", status="active",
        )
        db.commit()
        client = _make_client(db)
        token = _login_token(db, author)
        try:
            resp = client.post(
                f"/api/orgs/{org.slug}/proposals",
                json={
                    "title": "Org-default skip",
                    "body": "",
                    "voting_method": "binary",
                    "topics": [],
                    # No duration overrides — falls back to org defaults.
                },
                headers={"Authorization": f"Bearer {token}"},
            )
            assert resp.status_code == 201, resp.text
            body = resp.json()
            assert body["status"] == "voting"
        finally:
            app.dependency_overrides.pop(get_db, None)


# ===========================================================================
# B3 — Uploads env-driven path
# ===========================================================================

class TestUploadDirEnvVarRespected:
    """UPLOAD_DIR env var resolves to the given path at module import."""

    def test_upload_dir_env_var(self, tmp_path, monkeypatch):
        # Re-import the resolver with the env var set to confirm it picks
        # up UPLOAD_DIR over the default.
        monkeypatch.setenv("UPLOAD_DIR", str(tmp_path))
        import importlib
        import routes.avatars as avatars_module
        importlib.reload(avatars_module)
        try:
            assert avatars_module.UPLOADS_BASE_DIR == tmp_path
            assert avatars_module.AVATARS_BASE_DIR == tmp_path / "avatars"
            assert avatars_module.LOGOS_BASE_DIR == tmp_path / "logos"
        finally:
            # Restore module state for other tests.
            monkeypatch.delenv("UPLOAD_DIR", raising=False)
            importlib.reload(avatars_module)


class TestUploadDirDefaultsToDataUploads:
    """When no env var is set, UPLOADS_BASE_DIR defaults to /data/uploads."""

    def test_default_path(self, monkeypatch):
        monkeypatch.delenv("UPLOAD_DIR", raising=False)
        monkeypatch.delenv("UPLOADS_BASE_DIR", raising=False)
        import importlib
        from pathlib import Path
        import routes.avatars as avatars_module
        importlib.reload(avatars_module)
        try:
            assert avatars_module.UPLOADS_BASE_DIR == Path("/data/uploads")
        finally:
            # Reload one more time so subsequent tests see a clean state
            # (they may have UPLOADS_BASE_DIR set via earlier monkeypatching).
            importlib.reload(avatars_module)


class TestLegacyUploadsBaseDirEnvVarStillRespected:
    """Backward compat: UPLOADS_BASE_DIR (Phase 12.7 name) continues to work."""

    def test_legacy_env_var(self, tmp_path, monkeypatch):
        monkeypatch.delenv("UPLOAD_DIR", raising=False)
        monkeypatch.setenv("UPLOADS_BASE_DIR", str(tmp_path))
        import importlib
        import routes.avatars as avatars_module
        importlib.reload(avatars_module)
        try:
            assert avatars_module.UPLOADS_BASE_DIR == tmp_path
        finally:
            monkeypatch.delenv("UPLOADS_BASE_DIR", raising=False)
            importlib.reload(avatars_module)


# ===========================================================================
# B4 — PATCH duration floor validation
# ===========================================================================

class TestPATCHDurationFloorValidation:
    """PATCH /api/proposals/{id} rejects voting_days below the 0.05 floor."""

    def test_patch_below_floor_returns_400(self, db):
        author = _user(db, "alice")
        org = _org(db, "patchfloor")
        make_org_membership(
            db, org_id=org.id, user_id=author.id,
            role="steward", status="active",
        )
        proposal = _voting_proposal(
            db, org=org, author=author,
            deliberation_days=1, voting_days=7,
            status="draft",
        )
        db.commit()
        client = _make_client(db)
        token = _login_token(db, author)
        try:
            resp = client.patch(
                f"/api/proposals/{proposal.id}",
                json={"voting_days": 0.001},  # below 0.05 floor
                headers={"Authorization": f"Bearer {token}"},
            )
            assert resp.status_code == 400, resp.text
            assert "0.05" in resp.text or "72 minutes" in resp.text
        finally:
            app.dependency_overrides.pop(get_db, None)

    def test_patch_negative_deliberation_returns_400(self, db):
        author = _user(db, "alice")
        org = _org(db, "patchneg")
        make_org_membership(
            db, org_id=org.id, user_id=author.id,
            role="steward", status="active",
        )
        proposal = _voting_proposal(
            db, org=org, author=author,
            deliberation_days=1, voting_days=7,
            status="draft",
        )
        db.commit()
        client = _make_client(db)
        token = _login_token(db, author)
        try:
            resp = client.patch(
                f"/api/proposals/{proposal.id}",
                json={"deliberation_days": -1},
                headers={"Authorization": f"Bearer {token}"},
            )
            assert resp.status_code == 400, resp.text
            assert "negative" in resp.text.lower()
        finally:
            app.dependency_overrides.pop(get_db, None)
