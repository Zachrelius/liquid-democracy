"""Phase 52j — settings normalizer migration cycle test.

The J1 migration folds old single-value residency settings into the
new ``verification_residency_scope`` list. Covers:

  * Upgrade adds new keys + sets require_residency=True for an org
    carrying both old keys (jurisdiction + locality).
  * Upgrade is a no-op for an org with no old keys (additive-layer
    parity).
  * Downgrade removes the new keys it added.
  * Round-trip (downgrade then upgrade) is idempotent.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile

import sqlalchemy as sa


_BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_REV = "d1e2f3a4b5c6"
_PRIOR = "c0d1e2f3a4b5"  # Phase 58


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


def _build_pre(db_url: str) -> None:
    """Build schema + stamp + downgrade to the migration prior."""
    _create_all_subprocess(db_url)
    _run_alembic(db_url, "stamp", "head")
    _run_alembic(db_url, "downgrade", _PRIOR)


def _seed_org(db_url: str, *, slug: str, settings: dict) -> None:
    """Insert a minimal Organization row carrying the given settings."""
    engine = sa.create_engine(db_url)
    try:
        with engine.begin() as conn:
            # Match the columns on the Organization table. SQLite's
            # SQLAlchemy JSON column stores as TEXT; the migration
            # tolerates both shapes.
            conn.execute(sa.text(
                "INSERT INTO organizations (id, name, slug, description, settings, "
                "join_policy, discoverability, activity_visibility, "
                "governance_mode, is_demo, created_at, updated_at) "
                "VALUES (:id, :name, :slug, '', :settings, "
                "'open', 'discoverable', 'public', "
                "'single_steward', 0, "
                "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            ), {
                "id": f"org-{slug}",
                "name": slug.title(),
                "slug": slug,
                "settings": json.dumps(settings),
            })
    finally:
        engine.dispose()


def _read_settings(db_url: str, slug: str) -> dict:
    engine = sa.create_engine(db_url)
    try:
        with engine.begin() as conn:
            row = conn.execute(
                sa.text("SELECT settings FROM organizations WHERE slug=:s"),
                {"s": slug},
            ).first()
            assert row is not None
            raw = row[0]
            if isinstance(raw, str):
                return json.loads(raw)
            return raw
    finally:
        engine.dispose()


def test_upgrade_folds_old_keys_into_new_scope():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db_url = f"sqlite:///{path}"
    try:
        _build_pre(db_url)
        _seed_org(db_url, slug="folded-both", settings={
            "verification_membership_jurisdiction": "MA",
            "verification_membership_locality": "Somerville",
        })
        _seed_org(db_url, slug="folded-state-only", settings={
            "verification_membership_jurisdiction": "NH",
        })
        _seed_org(db_url, slug="no-old-keys", settings={})

        _run_alembic(db_url, "upgrade", _REV)

        s_both = _read_settings(db_url, "folded-both")
        assert s_both["verification_residency_scope"] == [
            {"state": "MA", "city": "Somerville"},
        ]
        assert s_both["verification_membership_require_residency"] is True

        s_state = _read_settings(db_url, "folded-state-only")
        assert s_state["verification_residency_scope"] == [{"state": "NH"}]
        assert s_state["verification_membership_require_residency"] is True

        s_none = _read_settings(db_url, "no-old-keys")
        assert "verification_residency_scope" not in s_none
        assert "verification_membership_require_residency" not in s_none
    finally:
        try: os.unlink(path)
        except OSError: pass


def test_downgrade_removes_new_keys():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db_url = f"sqlite:///{path}"
    try:
        _build_pre(db_url)
        _seed_org(db_url, slug="o", settings={
            "verification_membership_jurisdiction": "MA",
        })
        _run_alembic(db_url, "upgrade", _REV)
        assert "verification_residency_scope" in _read_settings(db_url, "o")
        _run_alembic(db_url, "downgrade", _PRIOR)
        s = _read_settings(db_url, "o")
        assert "verification_residency_scope" not in s
        assert "verification_membership_require_residency" not in s
        # Old keys preserved on downgrade.
        assert s.get("verification_membership_jurisdiction") == "MA"
    finally:
        try: os.unlink(path)
        except OSError: pass


def test_upgrade_is_idempotent():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db_url = f"sqlite:///{path}"
    try:
        _build_pre(db_url)
        _seed_org(db_url, slug="o", settings={
            "verification_membership_jurisdiction": "MA",
        })
        _run_alembic(db_url, "upgrade", _REV)
        first = _read_settings(db_url, "o")
        # Downgrade then upgrade — the second upgrade should produce
        # the same shape (not double-fold).
        _run_alembic(db_url, "downgrade", _PRIOR)
        _run_alembic(db_url, "upgrade", _REV)
        second = _read_settings(db_url, "o")
        assert second.get("verification_residency_scope") == first.get(
            "verification_residency_scope",
        )
        assert second.get("verification_membership_require_residency") is True
    finally:
        try: os.unlink(path)
        except OSError: pass
