"""Phase 103 database-overload response, liveness, and pool-monitor tests."""
from __future__ import annotations

import asyncio
import inspect
import time

import pytest
from fastapi import Depends
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError, TimeoutError as SQLAlchemyTimeoutError

import database
from database import get_db
from main import app
import main
import ops_monitoring
from settings import settings


def test_liveness_is_async_and_database_independent(monkeypatch):
    monkeypatch.setattr(main, "SessionLocal", lambda: (_ for _ in ()).throw(AssertionError("DB touched")))
    assert inspect.iscoroutinefunction(main.health)
    assert asyncio.run(main.health()) == {"status": "ok", "version": "0.1.0"}


@pytest.mark.asyncio
async def test_readiness_has_bounded_dedicated_timeout(monkeypatch):
    monkeypatch.setattr(settings, "db_pool_timeout_seconds", 0.05)
    monkeypatch.setattr(main, "_database_ready_check", lambda: time.sleep(1))
    started = time.perf_counter()
    response = await main.health_ready()
    elapsed = time.perf_counter() - started
    assert response.status_code == 503
    assert elapsed < 0.35
    assert b"disconnected" in response.body


def test_pool_monitor_thresholds_and_rolling_timeout(monkeypatch):
    now = ops_monitoring._utcnow()
    monkeypatch.setattr(database, "pool_snapshot", lambda: {
        "supported": True, "size": 2, "max_overflow": 3, "capacity": 5,
        "checked_out": 3, "current_overflow": 1, "utilization_percent": 60.0,
        "pool_timeout_seconds": 5.0,
    })
    warning = ops_monitoring._database_pool_component(now)
    assert warning["status"] == "warning"
    assert "before raising pool size" in warning["guidance"]
    ops_monitoring.record_pool_timeout(now=now)
    error = ops_monitoring._database_pool_component(now)
    assert error["status"] == "error"
    assert error["timeout_count_15m"] == 1
    assert "url" not in str(error).lower()


def test_feed_paths_are_sanitized_without_org_slug():
    assert ops_monitoring.sanitize_path("/api/proposal-feed") == "/api/proposal-feed"
    assert ops_monitoring.sanitize_path("/api/orgs/secret-council/proposal-feed") == "/api/orgs/:id/proposal-feed"
    assert ops_monitoring.sanitize_path("/api/orgs/secret-council/public/proposal-feed") == "/api/orgs/:id/public/proposal-feed"


def test_queuepool_timeout_is_json_503_and_dependency_cleanup_runs(monkeypatch):
    state = {"rolled_back": False, "closed": False}

    class BusySession:
        def in_transaction(self):
            return True
        def rollback(self):
            state["rolled_back"] = True
        def close(self):
            state["closed"] = True

    def busy_dependency():
        db = BusySession()
        try:
            yield db
        finally:
            if db.in_transaction():
                db.rollback()
            db.close()

    async def busy_route(_db=Depends(busy_dependency)):
        raise SQLAlchemyTimeoutError("QueuePool limit reached; secret sql must not leak")

    path = "/api/_phase103-test-pool-timeout"
    if not any(route.path == path for route in app.routes):
        app.add_api_route(path, busy_route, methods=["GET"])
    monkeypatch.setattr(database, "pool_snapshot", lambda: {
        "supported": True, "size": 2, "max_overflow": 3, "capacity": 5,
        "checked_out": 5, "current_overflow": 3, "utilization_percent": 100.0,
        "pool_timeout_seconds": 5.0,
    })
    response = TestClient(app, raise_server_exceptions=False).get(path)
    assert response.status_code == 503
    assert response.headers["Retry-After"] == "2"
    assert response.headers["Cache-Control"] == "no-store"
    body = response.json()
    assert body["code"] == "database_busy"
    assert body["request_id"] == response.headers["X-Request-ID"]
    assert "secret" not in response.text.lower() and "sql" not in response.text.lower()
    assert state == {"rolled_back": True, "closed": True}


def test_unrelated_sqlalchemy_error_is_not_reclassified_as_database_busy():
    async def broken_route():
        raise OperationalError("SELECT hidden", {}, Exception("boom"))

    path = "/api/_phase103-test-unrelated-error"
    if not any(route.path == path for route in app.routes):
        app.add_api_route(path, broken_route, methods=["GET"])
    response = TestClient(app, raise_server_exceptions=False).get(path)
    assert response.status_code == 500
    assert response.headers.get("Retry-After") is None
    assert "database_busy" not in response.text
