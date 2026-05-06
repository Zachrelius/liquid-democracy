"""Phase 14 — actual upgrade path verification (Phase 13 learning #7).

Spins up a fresh PG container, builds today's schema via create_all,
stamps at b9e2f4a17c83 (Phase 13.3 head — the prior revision), seeds
sample Organization rows with each pre-rename value (invite_only,
approval_required, open), then runs ``alembic upgrade head`` directly.
Asserts:

  - 0 rows with join_policy='invite_only' post-upgrade.
  - The previously-invite_only org now has 'invite_only_secret'.
  - approval_required + open orgs unchanged.

This is the Phase 14 analog of phase13_3_actual_upgrade_path_check.py.
The check exists because pg_smoke's upgrade mode runs ``create_all +
stamp + upgrade`` against an empty DB which doesn't catch DATA-migration
bugs (only DDL bugs). For Phase 14 the only schema change is a value
rename, so this check is the only place where the rename's correctness
is demonstrated end-to-end on PG.
"""
from __future__ import annotations

import contextlib
import os
import shutil
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone

_BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)


_PRIOR_REV = "b9e2f4a17c83"
_PG_IMAGE = "postgres:16-alpine"
_PG_PORT = 55435  # Distinct from Phase 13.3's 55434.
_PG_DB = "ld_phase14_check"
_PG_USER = "smoke"
_PG_PASSWORD = "smoke"


def _run_alembic(db_url: str, *args: str) -> None:
    env = dict(os.environ)
    env["DATABASE_URL"] = db_url
    res = subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=_BACKEND_DIR, env=env, capture_output=True, text=True,
    )
    if res.returncode != 0:
        sys.stdout.write(res.stdout)
        sys.stderr.write(res.stderr)
        raise RuntimeError(f"alembic {' '.join(args)} failed")


@contextlib.contextmanager
def _pg_container():
    name = f"ld-14-check-{uuid.uuid4().hex[:8]}"
    print(f"[check] starting {_PG_IMAGE} as {name}")
    subprocess.run([
        "docker", "run", "-d", "--rm", "--name", name,
        "-e", f"POSTGRES_DB={_PG_DB}",
        "-e", f"POSTGRES_USER={_PG_USER}",
        "-e", f"POSTGRES_PASSWORD={_PG_PASSWORD}",
        "-p", f"{_PG_PORT}:5432", _PG_IMAGE,
    ], check=True, stdout=subprocess.DEVNULL)
    db_url = f"postgresql://{_PG_USER}:{_PG_PASSWORD}@localhost:{_PG_PORT}/{_PG_DB}"
    try:
        from sqlalchemy import create_engine, text
        deadline = time.time() + 30
        while time.time() < deadline:
            try:
                eng = create_engine(db_url)
                with eng.connect() as c:
                    c.execute(text("SELECT 1"))
                eng.dispose()
                break
            except Exception:
                time.sleep(0.5)
        yield db_url
    finally:
        print(f"[check] tearing down {name}")
        subprocess.run(["docker", "rm", "-f", name], check=False,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _create_all(db_url: str) -> None:
    code = (
        f"import os; os.environ['DATABASE_URL']={db_url!r}; "
        "from database import create_tables; create_tables()"
    )
    res = subprocess.run([sys.executable, "-c", code], cwd=_BACKEND_DIR,
                         capture_output=True, text=True)
    if res.returncode != 0:
        sys.stdout.write(res.stdout)
        sys.stderr.write(res.stderr)
        raise RuntimeError("create_tables failed")


def _insert_org(
    db_url: str, *, slug: str, join_policy: str,
) -> str:
    """Insert an Organization with the given join_policy. Returns id."""
    from sqlalchemy import create_engine, text
    eng = create_engine(db_url)
    org_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    try:
        with eng.begin() as conn:
            conn.execute(text(
                "INSERT INTO organizations "
                "(id, name, slug, description, join_policy, settings, "
                " parent_org_id, created_at, updated_at) "
                "VALUES (:id, :n, :s, '', :jp, '{}', NULL, :now, :now)"
            ), {
                "id": org_id, "n": slug.title(), "s": slug,
                "jp": join_policy, "now": now,
            })
    finally:
        eng.dispose()
    return org_id


def _join_policy(db_url: str, org_id: str) -> str:
    from sqlalchemy import create_engine, text
    eng = create_engine(db_url)
    try:
        with eng.connect() as conn:
            row = conn.execute(
                text("SELECT join_policy FROM organizations WHERE id = :i"),
                {"i": org_id},
            ).first()
            return row[0] if row else None
    finally:
        eng.dispose()


def _count_with_policy(db_url: str, value: str) -> int:
    from sqlalchemy import create_engine, text
    eng = create_engine(db_url)
    try:
        with eng.connect() as conn:
            return int(conn.execute(text(
                "SELECT COUNT(*) FROM organizations WHERE join_policy = :v"
            ), {"v": value}).scalar() or 0)
    finally:
        eng.dispose()


def main() -> int:
    if shutil.which("docker") is None:
        print("ERROR: docker not on PATH", file=sys.stderr)
        return 1

    with _pg_container() as db_url:
        # Phase 1: build today's schema (create_tables) and stamp at the
        # prior revision so alembic believes we're at 13.3's head. Phase
        # 14's only change is a value rename — no DDL reshape needed
        # since the join_policy column shape is unchanged across this
        # migration.
        _create_all(db_url)
        _run_alembic(db_url, "stamp", _PRIOR_REV)

        # Seed sample data covering the three pre-migration values.
        # Two invite_only rows so we can verify the count rename.
        legacy1 = _insert_org(db_url, slug="legacy-1", join_policy="invite_only")
        legacy2 = _insert_org(db_url, slug="legacy-2", join_policy="invite_only")
        ar = _insert_org(db_url, slug="ar-org", join_policy="approval_required")
        op_org = _insert_org(db_url, slug="open-org", join_policy="open")

        pre_legacy = _count_with_policy(db_url, "invite_only")
        pre_secret = _count_with_policy(db_url, "invite_only_secret")
        pre_ar = _count_with_policy(db_url, "approval_required")
        pre_open = _count_with_policy(db_url, "open")
        print(f"[check] PRE-upgrade: organizations rows by join_policy:")
        print(f"[check]   invite_only          = {pre_legacy}")
        print(f"[check]   invite_only_secret   = {pre_secret}")
        print(f"[check]   approval_required    = {pre_ar}")
        print(f"[check]   open                 = {pre_open}")
        assert pre_legacy == 2, f"expected 2 invite_only rows, got {pre_legacy}"
        assert pre_secret == 0
        assert pre_ar == 1
        assert pre_open == 1

        # Run the actual upgrade.
        _run_alembic(db_url, "upgrade", "head")

        post_legacy = _count_with_policy(db_url, "invite_only")
        post_secret = _count_with_policy(db_url, "invite_only_secret")
        post_ar = _count_with_policy(db_url, "approval_required")
        post_open = _count_with_policy(db_url, "open")
        print(f"[check] POST-upgrade: organizations rows by join_policy:")
        print(f"[check]   invite_only          = {post_legacy}")
        print(f"[check]   invite_only_secret   = {post_secret}")
        print(f"[check]   approval_required    = {post_ar}")
        print(f"[check]   open                 = {post_open}")

        # Data-migration assertions.
        assert post_legacy == 0, (
            f"expected 0 invite_only rows post-upgrade, got {post_legacy}"
        )
        assert post_secret == 2, (
            f"expected 2 invite_only_secret rows post-upgrade, got {post_secret}"
        )
        assert post_ar == 1, "approval_required count must be unchanged"
        assert post_open == 1, "open count must be unchanged"

        # Per-org assertions.
        assert _join_policy(db_url, legacy1) == "invite_only_secret"
        assert _join_policy(db_url, legacy2) == "invite_only_secret"
        assert _join_policy(db_url, ar) == "approval_required"
        assert _join_policy(db_url, op_org) == "open"

        print("\n[check] PHASE 14 ACTUAL-UPGRADE-PATH CHECK: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
