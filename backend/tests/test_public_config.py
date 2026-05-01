"""Tests for /api/public-config (frontend-readable feature flags).

Phase 9 Session 3: drives the manual-fallback UX. Frontend reads at
app boot to decide whether Polis create/archive surfaces should
remind the operator to complete steps on pol.is.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from main import app
from settings import settings as app_settings


@pytest.fixture
def client():
    yield TestClient(app)


class TestPublicConfig:
    def test_returns_polis_token_configured_false_when_unset(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(app_settings, "polis_auth_token", "")
        resp = client.get("/api/public-config")
        assert resp.status_code == 200
        assert resp.json() == {"polis_token_configured": False}

    def test_returns_polis_token_configured_true_when_set(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(app_settings, "polis_auth_token", "fake-jwt-token")
        resp = client.get("/api/public-config")
        assert resp.status_code == 200
        assert resp.json() == {"polis_token_configured": True}

    def test_no_auth_required(self, client: TestClient) -> None:
        # Verify by hitting without any auth header — this is a public endpoint.
        resp = client.get("/api/public-config")
        assert resp.status_code == 200
