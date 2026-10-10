"""Phase 112 — JWT token hardening regressions.

Covers:
  - Email unsubscribe tokens (same key, same ``sub``) can never authenticate
    a session: REST (/api/auth/me), WebSocket ``check_access``, or the
    rate-limit user key.
  - Access tokens carry ``typ: access``; untyped (pre-Phase-112), ``alg=none``,
    wrong-key, and expired tokens are rejected.
  - Unsubscribe links keep working, including links minted before this pass
    (``purpose`` claim only, no ``typ``).
  - ``python-jose`` is fully removed from source + requirements.
"""
from __future__ import annotations

import pathlib
from datetime import datetime, timedelta, timezone

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import auth as auth_utils
import models
import rate_limit_utils
import websocket as live
from database import Base, get_db
from email_service import decode_unsubscribe_token, generate_unsubscribe_token
from main import app
from settings import settings
from tests.test_phase_107_connection_security import socket_db  # noqa: F401 — fixture


_DUMMY_HASH = "$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/lewrwKJuRxm5pJmJi"
BACKEND = pathlib.Path(__file__).resolve().parents[1]


@pytest.fixture(scope="function")
def test_db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)


@pytest.fixture(scope="function")
def client(test_db: Session):
    def _get_db():
        yield test_db

    app.dependency_overrides[get_db] = _get_db
    yield TestClient(app)
    app.dependency_overrides.clear()


def _make_user(db: Session, username: str) -> models.User:
    user = models.User(
        username=username,
        display_name=username,
        email=f"{username}@example.test",
        password_hash=_DUMMY_HASH,
        email_verified=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _sign(payload: dict, key: str | None = None) -> str:
    return jwt.encode(payload, key or settings.secret_key, algorithm="HS256")


def _future(minutes: int = 15) -> datetime:
    return datetime.now(timezone.utc) + timedelta(minutes=minutes)


def _me(client: TestClient, token: str):
    return client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})


# ---------------------------------------------------------------------------
# REST authentication
# ---------------------------------------------------------------------------

def test_access_token_carries_access_type_and_authenticates(client, test_db):
    user = _make_user(test_db, "typed")
    token = auth_utils.create_access_token(user.id)
    payload = jwt.decode(token, settings.secret_key, algorithms=["HS256"])
    assert payload["typ"] == "access"
    assert payload["sub"] == user.id

    resp = _me(client, token)
    assert resp.status_code == 200
    assert resp.json()["id"] == user.id


def test_unsubscribe_token_cannot_authenticate(client, test_db):
    user = _make_user(test_db, "unsub_victim")
    token = generate_unsubscribe_token(user.id, "comment.replied")
    # Precondition for the regression: same subject, valid signature.
    assert jwt.decode(token, settings.secret_key, algorithms=["HS256"])["sub"] == user.id

    resp = _me(client, token)
    assert resp.status_code == 401


def test_legacy_unsubscribe_token_shape_cannot_authenticate(client, test_db):
    """Links already in inboxes (pre-Phase-112: ``purpose`` only, no ``typ``)."""
    user = _make_user(test_db, "legacy_unsub_victim")
    token = _sign({
        "sub": user.id, "event_type": "comment.replied",
        "purpose": "unsubscribe", "exp": _future(60 * 24 * 30),
    })
    assert _me(client, token).status_code == 401


def test_untyped_access_token_rejected(client, test_db):
    """Pre-Phase-112 access tokens lack ``typ``; the FE refreshes on 401."""
    user = _make_user(test_db, "untyped")
    token = _sign({"sub": user.id, "exp": _future()})
    assert _me(client, token).status_code == 401


@pytest.mark.parametrize("bad", ["wrong_key", "alg_none", "expired", "no_exp", "no_sub"])
def test_malformed_access_tokens_rejected(client, test_db, bad):
    user = _make_user(test_db, f"bad_{bad}")
    base = {"sub": user.id, "exp": _future(), "typ": "access"}
    if bad == "wrong_key":
        token = _sign(base, key="x" * 64)
    elif bad == "alg_none":
        token = jwt.encode(base, None, algorithm="none")
    elif bad == "expired":
        token = _sign({**base, "exp": datetime.now(timezone.utc) - timedelta(minutes=1)})
    elif bad == "no_exp":
        token = _sign({"sub": user.id, "typ": "access"})
    else:
        token = _sign({"exp": _future(), "typ": "access"})
    assert _me(client, token).status_code == 401


# ---------------------------------------------------------------------------
# WebSocket authentication
# ---------------------------------------------------------------------------

def test_websocket_rejects_unsubscribe_token(socket_db):  # noqa: F811
    _engine, factory, (_org_id, user_id, proposal_id) = socket_db
    unsub = generate_unsubscribe_token(user_id, "comment.replied")
    assert live.check_access(factory, proposal_id, unsub) == (4401, 0)

    code, expires = live.check_access(factory, proposal_id, auth_utils.create_access_token(user_id))
    assert code == 0 and expires > 0


# ---------------------------------------------------------------------------
# Rate-limit keying + request logging
# ---------------------------------------------------------------------------

class _FakeReq:
    def __init__(self, headers):
        self.headers = headers
        self.client = type("C", (), {"host": "1.2.3.4"})()


def test_rate_limit_key_ignores_unsubscribe_token():
    unsub = generate_unsubscribe_token("victim-id", "comment.replied")
    key = rate_limit_utils.user_or_remote_address(
        _FakeReq({"authorization": f"Bearer {unsub}"}))
    assert key == "1.2.3.4"

    access = auth_utils.create_access_token("victim-id")
    key = rate_limit_utils.user_or_remote_address(
        _FakeReq({"authorization": f"Bearer {access}"}))
    assert key == "user:victim-id"


def test_log_decode_rejects_unsubscribe_but_tolerates_expired_access():
    unsub = generate_unsubscribe_token("victim-id", "comment.replied")
    with pytest.raises(jwt.PyJWTError):
        auth_utils.decode_access_token(unsub, verify_exp=False)

    expired = auth_utils.create_access_token("u1", expires_delta=timedelta(minutes=-5))
    assert auth_utils.decode_access_token(expired, verify_exp=False)["sub"] == "u1"
    with pytest.raises(jwt.ExpiredSignatureError):
        auth_utils.decode_access_token(expired)


# ---------------------------------------------------------------------------
# Unsubscribe still works (side effect asserted)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("legacy", [False, True])
def test_unsubscribe_link_still_flips_preferences(client, test_db, legacy):
    user = _make_user(test_db, f"still_works_{legacy}")
    test_db.add(models.NotificationPreference(
        user_id=user.id, event_type="comment.replied",
        channel="email_immediate", enabled=True,
    ))
    test_db.commit()

    if legacy:
        token = _sign({
            "sub": user.id, "event_type": "comment.replied",
            "purpose": "unsubscribe", "exp": _future(60),
        })
    else:
        token = generate_unsubscribe_token(user.id, "comment.replied")

    resp = client.get(f"/api/notifications/unsubscribe/{token}")
    assert resp.status_code == 200
    assert resp.json()["success"] is True

    test_db.expire_all()
    pref = test_db.query(models.NotificationPreference).filter_by(
        user_id=user.id, event_type="comment.replied", channel="email_immediate",
    ).one()
    assert pref.enabled is False


def test_access_token_is_not_an_unsubscribe_token():
    assert decode_unsubscribe_token(auth_utils.create_access_token("u1")) is None


# ---------------------------------------------------------------------------
# Dependency removal
# ---------------------------------------------------------------------------

def test_python_jose_fully_removed():
    reqs = (BACKEND / "requirements.txt").read_text(encoding="utf-8").lower()
    assert "python-jose" not in reqs
    assert "pyjwt==" in reqs

    offenders = []
    for path in BACKEND.rglob("*.py"):
        rel = path.relative_to(BACKEND).parts
        if rel[0].startswith(".") or rel[0] in {"migrations", "node_modules"}:
            continue
        if path.resolve() == pathlib.Path(__file__).resolve():
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        if "from jose" in text or "import jose" in text:
            offenders.append(str(path.relative_to(BACKEND)))
    assert offenders == []


# ---------------------------------------------------------------------------
# Request logs never carry the unsubscribe token
# ---------------------------------------------------------------------------

def test_request_log_redacts_unsubscribe_token(client, test_db, caplog):
    import logging
    from main import _loggable_path

    user = _make_user(test_db, "log_redact")
    token = generate_unsubscribe_token(user.id, "comment.replied")
    with caplog.at_level(logging.INFO, logger="request"):
        resp = client.get(f"/api/notifications/unsubscribe/{token}")
    assert resp.status_code == 200
    request_lines = [r.getMessage() for r in caplog.records if r.name == "request"]
    assert any("/api/notifications/unsubscribe/:token" in line for line in request_lines)
    assert all(token not in line for line in request_lines)

    # UUID path params stay readable for debugging.
    uuid_path = f"/api/proposals/{user.id}"
    assert _loggable_path(uuid_path) == uuid_path


def test_uvicorn_access_log_redacts_token_path():
    """Uvicorn logs the raw path through its own handler; the filter installed
    by main.py must redact it (found on prod during Phase 112 deploy QA)."""
    import logging
    import main  # noqa: F401 — installs the filter

    token = generate_unsubscribe_token("u1", "comment.replied")
    record = logging.LogRecord(
        "uvicorn.access", logging.INFO, __file__, 0,
        '%s - "%s %s HTTP/%s" %d',
        ("1.2.3.4:0", "GET", f"/api/notifications/unsubscribe/{token}", "1.1", 200),
        None,
    )
    for f in logging.getLogger("uvicorn.access").filters:
        f.filter(record)
    rendered = record.getMessage()
    assert token not in rendered
    assert "/api/notifications/unsubscribe/:token" in rendered
