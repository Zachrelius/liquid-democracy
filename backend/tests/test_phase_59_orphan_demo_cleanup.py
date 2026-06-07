"""Phase 59 Cluster E — orphan demo-org cleanup script smoke test.

Asserts:
  * Script's deletion logic removes a slug='demo' Organization row.
  * Idempotent: re-running after deletion is a no-op (exit 0).
  * Refuses to delete a row that LOOKS like a managed 3-bible demo
    (has personas / governance_type / known bible slug).

The script runs against `DATABASE_URL` (prod path uses
`DATABASE_PUBLIC_URL` per the operational note in CLAUDE.md). This
test runs it against an in-memory sqlite via the test_db fixture so
the deletion logic is exercised without touching real data.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile

import pytest
import sqlalchemy as sa
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import models
from database import Base


@pytest.fixture(scope="function")
def temp_db_url():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db_url = f"sqlite:///{path}"
    engine = create_engine(db_url)
    Base.metadata.create_all(engine)
    engine.dispose()
    try:
        yield db_url
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def _run_script(db_url: str, *args: str) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["DATABASE_URL"] = db_url
    backend_dir = os.path.abspath(
        os.path.join(os.path.dirname(__file__), ".."),
    )
    return subprocess.run(
        [
            sys.executable,
            os.path.join(backend_dir, "scripts",
                         "phase59_remove_orphaned_demo_org.py"),
            *args,
        ],
        cwd=backend_dir, env=env,
        capture_output=True, text=True,
    )


def _seed_orphan(db_url: str) -> None:
    engine = create_engine(db_url)
    SessionLocal = sessionmaker(bind=engine)
    s = SessionLocal()
    try:
        org = models.Organization(
            name="Demo Organization", slug="demo",
            description="legacy demo org",
            join_policy="open", settings={},
        )
        s.add(org)
        s.commit()
    finally:
        s.close()
        engine.dispose()


def _orphan_present(db_url: str) -> bool:
    engine = create_engine(db_url)
    SessionLocal = sessionmaker(bind=engine)
    s = SessionLocal()
    try:
        return s.query(models.Organization).filter_by(
            slug="demo",
        ).first() is not None
    finally:
        s.close()
        engine.dispose()


def test_script_noop_when_no_orphan(temp_db_url):
    """Idempotent: empty DB → no-op, exit 0."""
    r = _run_script(temp_db_url)
    assert r.returncode == 0, r.stderr
    assert "Nothing to do" in r.stdout or "no-op" in r.stdout.lower()


def test_script_dry_run_does_not_delete(temp_db_url):
    """Without --confirm, the script reports counts but doesn't delete."""
    _seed_orphan(temp_db_url)
    assert _orphan_present(temp_db_url)

    r = _run_script(temp_db_url)
    assert r.returncode == 0, r.stderr
    assert "DRY RUN" in r.stdout or "dry-run" in r.stdout.lower()
    # Orphan still present after dry run.
    assert _orphan_present(temp_db_url), "dry run shouldn't delete"


def test_script_confirm_deletes_orphan(temp_db_url):
    _seed_orphan(temp_db_url)
    assert _orphan_present(temp_db_url)

    r = _run_script(temp_db_url, "--confirm")
    assert r.returncode == 0, (
        f"STDOUT:\n{r.stdout}\nSTDERR:\n{r.stderr}"
    )
    assert "DONE" in r.stdout
    # Orphan gone.
    assert not _orphan_present(temp_db_url)


def test_script_idempotent_after_delete(temp_db_url):
    """Re-running after delete is a no-op."""
    _seed_orphan(temp_db_url)
    _run_script(temp_db_url, "--confirm")
    assert not _orphan_present(temp_db_url)

    r = _run_script(temp_db_url, "--confirm")
    assert r.returncode == 0, r.stderr
    assert "Nothing to do" in r.stdout or "no-op" in r.stdout.lower()


def test_script_refuses_managed_bible_org(temp_db_url):
    """Defensive: if the row looks like a managed 3-bible demo (has
    personas or a bible-style slug), the script aborts rather than
    deleting."""
    engine = create_engine(temp_db_url)
    SessionLocal = sessionmaker(bind=engine)
    s = SessionLocal()
    try:
        # Insert a row at slug='demo' but with personas set — looks
        # like a managed bible (defensive trigger).
        org = models.Organization(
            name="Demo Org", slug="demo",
            description="",
            join_policy="open", settings={},
            personas=[{"username": "x"}],  # the defensive flag
        )
        s.add(org)
        s.commit()
    finally:
        s.close()
        engine.dispose()

    r = _run_script(temp_db_url, "--confirm")
    assert r.returncode == 2, (
        f"STDOUT:\n{r.stdout}\nSTDERR:\n{r.stderr}"
    )
    assert "ABORT" in r.stdout
    # Row NOT deleted.
    assert _orphan_present(temp_db_url)
