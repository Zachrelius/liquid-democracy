"""Phase 9 — `polis_service` HTTP wrapper tests.

We mock the `requests` module's HTTP entry points (`requests.post`,
`requests.get`) via `unittest.mock.patch` — same approach used in the
phase 8 worker tests for environmental boundaries. No live network calls.
"""
from unittest import mock

import pytest

import polis_service
from polis_service import (
    PolisAPIError,
    add_seed_statement,
    add_seed_statements,
    archive_conversation,
    create_conversation,
    fetch_export,
    get_participation_stats,
)


class _FakeResp:
    def __init__(self, status_code: int, json_body=None, text: str = ""):
        self.status_code = status_code
        self._json = json_body
        self.text = text if text else ("" if json_body is None else "{}")
        self.content = text.encode() if text else b""

    def json(self):
        if self._json is None:
            raise ValueError("no json")
        return self._json


@pytest.fixture(autouse=True)
def _set_token(monkeypatch):
    """Default token configured so admin calls don't short-circuit on auth."""
    monkeypatch.setattr(polis_service.settings, "polis_auth_token", "test-jwt")
    monkeypatch.setattr(polis_service.settings, "polis_api_base_url", "https://pol.is")


def test_create_conversation_success(monkeypatch):
    captured = {}

    def fake_post(url, json=None, headers=None, timeout=None):
        captured["url"] = url
        captured["json"] = json
        captured["headers"] = headers
        return _FakeResp(200, {"conversation_id": "abc12def34"}, '{"conversation_id":"abc12def34"}')

    monkeypatch.setattr(polis_service.httpx, "post", fake_post)
    out = create_conversation("My title", "My prompt", seed_statements=None)

    assert captured["url"] == "https://pol.is/api/v3/conversations"
    assert captured["json"]["topic"] == "My title"
    assert captured["json"]["description"] == "My prompt"
    assert captured["headers"]["Authorization"] == "Bearer test-jwt"

    assert out["conversation_id"] == "abc12def34"
    assert out["embed_url"] == "https://pol.is/abc12def34"
    assert out["seed_statement_results"] == []


def test_create_conversation_with_seed_statements(monkeypatch):
    calls = []

    def fake_post(url, json=None, headers=None, timeout=None):
        calls.append({"url": url, "json": json})
        if url.endswith("/api/v3/conversations"):
            return _FakeResp(200, {"conversation_id": "conv-xyz"}, "{}")
        # /api/v3/comments
        return _FakeResp(200, {"tid": 1}, "{}")

    monkeypatch.setattr(polis_service.httpx, "post", fake_post)
    out = create_conversation("T", "P", seed_statements=["s1", "s2", "s3"])
    assert out["conversation_id"] == "conv-xyz"
    assert len(out["seed_statement_results"]) == 3
    assert all(r["ok"] for r in out["seed_statement_results"])
    # 1 conversation create + 3 seed inserts
    assert len(calls) == 4
    seed_urls = [c["url"] for c in calls[1:]]
    assert all(u.endswith("/api/v3/comments") for u in seed_urls)


def test_create_conversation_partial_seed_failure(monkeypatch):
    """Conversation succeeds, one seed fails -> caller gets per-statement results."""
    state = {"calls": 0}

    def fake_post(url, json=None, headers=None, timeout=None):
        state["calls"] += 1
        if url.endswith("/api/v3/conversations"):
            return _FakeResp(200, {"conversation_id": "c1"}, "{}")
        # First seed ok, second seed fails
        if json and json.get("txt") == "bad-seed":
            return _FakeResp(400, {"error": "polis_err_bad_text"}, '{"error":"x"}')
        return _FakeResp(200, {"tid": 1}, "{}")

    monkeypatch.setattr(polis_service.httpx, "post", fake_post)
    out = create_conversation("T", "P", seed_statements=["good", "bad-seed", "good2"])
    assert out["conversation_id"] == "c1"
    results = {r["text"]: r["ok"] for r in out["seed_statement_results"]}
    assert results == {"good": True, "bad-seed": False, "good2": True}


def test_create_conversation_http_error_raises(monkeypatch):
    def fake_post(url, json=None, headers=None, timeout=None):
        return _FakeResp(401, {"error": "No authentication token found"}, '{"error":"x"}')

    monkeypatch.setattr(polis_service.httpx, "post", fake_post)
    with pytest.raises(PolisAPIError) as exc_info:
        create_conversation("T", "P")
    assert exc_info.value.status_code == 401


def test_create_conversation_no_id_in_response_raises(monkeypatch):
    def fake_post(url, json=None, headers=None, timeout=None):
        return _FakeResp(200, {"unrelated": "shape"}, "{}")

    monkeypatch.setattr(polis_service.httpx, "post", fake_post)
    with pytest.raises(PolisAPIError):
        create_conversation("T", "P")


def test_missing_token_raises_clearly(monkeypatch):
    monkeypatch.setattr(polis_service.settings, "polis_auth_token", "")
    # No HTTP call should happen — _require_token short-circuits.
    monkeypatch.setattr(
        polis_service.httpx, "post",
        lambda *a, **kw: pytest.fail("Should not have called HTTP"),
    )
    with pytest.raises(PolisAPIError) as exc_info:
        create_conversation("T", "P")
    assert "POLIS_AUTH_TOKEN not configured" in str(exc_info.value)
    assert exc_info.value.status_code is None


def test_add_seed_statement_success(monkeypatch):
    captured = {}

    def fake_post(url, json=None, headers=None, timeout=None):
        captured["url"] = url
        captured["json"] = json
        return _FakeResp(200, {"tid": 5}, "{}")

    monkeypatch.setattr(polis_service.httpx, "post", fake_post)
    add_seed_statement("conv-id", "Hello world")
    assert captured["url"] == "https://pol.is/api/v3/comments"
    assert captured["json"] == {
        "conversation_id": "conv-id",
        "txt": "Hello world",
        "is_seed": True,
    }


def test_add_seed_statements_bulk_collects_results(monkeypatch):
    state = {"i": 0}

    def fake_post(url, json=None, headers=None, timeout=None):
        state["i"] += 1
        if state["i"] == 2:
            return _FakeResp(500, {"error": "server"}, '{"error":"x"}')
        return _FakeResp(200, {"tid": state["i"]}, "{}")

    monkeypatch.setattr(polis_service.httpx, "post", fake_post)
    out = add_seed_statements("c1", ["a", "b", "c"])
    assert [r["ok"] for r in out] == [True, False, True]


def test_get_participation_stats_success(monkeypatch):
    body = {
        "voters": [1, 2, 3],
        "commenters": [10, 20],
        "votes": [5, 15, 25, 30],
    }

    def fake_get(url, params=None, timeout=None):
        assert url == "https://pol.is/api/v3/conversationStats"
        assert params == {"conversation_id": "c1"}
        return _FakeResp(200, body, "{}")

    monkeypatch.setattr(polis_service.httpx, "get", fake_get)
    stats = get_participation_stats("c1")
    assert stats["participant_count"] == 3
    assert stats["statement_count"] == 20
    assert stats["vote_count"] == 30
    assert stats["live_stats_unavailable"] is False


def test_get_participation_stats_network_error_returns_fallback(monkeypatch):
    def fake_get(url, params=None, timeout=None):
        raise polis_service.httpx.ConnectError("dns")

    monkeypatch.setattr(polis_service.httpx, "get", fake_get)
    stats = get_participation_stats("c1")
    assert stats["live_stats_unavailable"] is True
    assert stats["participant_count"] == 0


def test_get_participation_stats_http_error_returns_fallback(monkeypatch):
    def fake_get(url, params=None, timeout=None):
        return _FakeResp(404, {"error": "not found"}, '{"error":"x"}')

    monkeypatch.setattr(polis_service.httpx, "get", fake_get)
    stats = get_participation_stats("c1")
    assert stats["live_stats_unavailable"] is True


def test_get_participation_stats_works_without_auth_token(monkeypatch):
    """conversationStats is auth-optional — works in dev without token."""
    monkeypatch.setattr(polis_service.settings, "polis_auth_token", "")

    def fake_get(url, params=None, timeout=None):
        return _FakeResp(200, {"voters": [1]}, "{}")

    monkeypatch.setattr(polis_service.httpx, "get", fake_get)
    stats = get_participation_stats("c1")
    assert stats["live_stats_unavailable"] is False


def test_archive_conversation_success(monkeypatch):
    captured = {}

    def fake_post(url, json=None, headers=None, timeout=None):
        captured["url"] = url
        captured["json"] = json
        return _FakeResp(200, {}, "{}")

    monkeypatch.setattr(polis_service.httpx, "post", fake_post)
    archive_conversation("c1")
    assert captured["url"] == "https://pol.is/api/v3/conversation/close"
    assert captured["json"] == {"conversation_id": "c1"}


def test_archive_conversation_failure_raises(monkeypatch):
    def fake_post(url, json=None, headers=None, timeout=None):
        return _FakeResp(403, {"error": "polis_err_unauth"}, '{"error":"x"}')

    monkeypatch.setattr(polis_service.httpx, "post", fake_post)
    with pytest.raises(PolisAPIError) as exc_info:
        archive_conversation("c1")
    assert exc_info.value.status_code == 403


def test_fetch_export_success(monkeypatch):
    def fake_get(url, params=None, headers=None, timeout=None):
        assert url == "https://pol.is/api/v3/dataExport"
        assert params == {"conversation_id": "c1", "format": "csv"}
        assert headers["Authorization"] == "Bearer test-jwt"
        return _FakeResp(200, None, "id,vote,xid\n1,1,xyz\n")

    monkeypatch.setattr(polis_service.httpx, "get", fake_get)
    out = fetch_export("c1")
    assert b"xid" in out


def test_fetch_export_failure_raises(monkeypatch):
    def fake_get(url, params=None, headers=None, timeout=None):
        return _FakeResp(500, {"error": "server"}, '{"error":"x"}')

    monkeypatch.setattr(polis_service.httpx, "get", fake_get)
    with pytest.raises(PolisAPIError) as exc_info:
        fetch_export("c1")
    assert exc_info.value.status_code == 500
