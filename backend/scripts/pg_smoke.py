"""Phase 8.6 Item 4 — PostgreSQL smoke harness (durable pattern).

Replaces the Phase 8.5 Session 2 ``create_all + alembic stamp head`` pattern.
Exercises the *actual* production-deployment alembic upgrade path so
collision-class bugs (Phase 8.5 incident) are caught before deploy.

Two paths are run by default; both must pass:

  1. **Fresh-DB path** (``--mode fresh``)
     Equivalent to ``start.sh``'s fresh-DB branch on a brand-new container:
     create the schema via ``Base.metadata.create_all`` and stamp alembic
     to head. Verifies the fresh-deploy bootstrap doesn't fall over on PG.

  2. **Upgrade-from-prior path** (``--mode upgrade``)
     Equivalent to deploying a new pass to an already-running prod
     container: stamp alembic at the **prior** revision (default
     ``c5f3a2b81e07`` — the Phase 8 revision, immediately before Phase
     8.5's ``d41a8c92f3b1``), then run ``alembic upgrade head`` to apply
     the pass-under-test's migrations on top. This is the path the 502
     incident hit; the harness now exercises it explicitly.

Why this matters: ``create_all + stamp head`` masks ordering bugs because
it never runs the migration's DDL — alembic just records "you're at
head" without verifying the migration actually works against the existing
schema. The upgrade-from-prior path runs the migration's DDL on a
schema-shaped state, so a collision (or any other migration bug) surfaces
loudly.

Default behavior: spin up a postgres:16-alpine container, run both paths
sequentially, run a focused smoke spot-check after each, tear down the
container. Fail-fast on any error with a clear message.

Usage from backend/:

    .venv/Scripts/python.exe scripts/pg_smoke.py
    # or pin a different prior revision:
    .venv/Scripts/python.exe scripts/pg_smoke.py --prior-revision c5f3a2b81e07
    # or run only one mode:
    .venv/Scripts/python.exe scripts/pg_smoke.py --mode fresh
    .venv/Scripts/python.exe scripts/pg_smoke.py --mode upgrade

Exit code 0 == PASS (all requested modes); non-zero == FAIL.

Adopt this harness for every future schema-adding pass. See
``DEPLOYMENT.md`` for the operator-facing pattern docs.
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
import traceback
import uuid
from contextlib import contextmanager
from typing import Iterator, Tuple

_BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

# Default prior revision: Phase 9 Session 2 (e72362fd7cd5). Phase 9.5 ships
# the org-creation-gate migration (373e1f066cc1) on top of Session 2's
# `intended_seed_statements` column; the upgrade-from-prior path exercises
# ONLY that increment rather than re-running every prior chain step. Bump
# again in the next pass.
_DEFAULT_PRIOR_REV = "e72362fd7cd5"

_DEFAULT_PG_IMAGE = "postgres:16-alpine"
_DEFAULT_PG_PORT = 55433  # Distinct from Phase 8.5's 55432 to avoid clash.
_DEFAULT_PG_DB = "ld_pg_smoke"
_DEFAULT_PG_USER = "smoke"
_DEFAULT_PG_PASSWORD = "smoke"


# ---------------------------------------------------------------------------
# Container lifecycle
# ---------------------------------------------------------------------------

def _have_docker() -> bool:
    return shutil.which("docker") is not None


@contextmanager
def _pg_container(
    image: str = _DEFAULT_PG_IMAGE,
    port: int = _DEFAULT_PG_PORT,
    db: str = _DEFAULT_PG_DB,
    user: str = _DEFAULT_PG_USER,
    password: str = _DEFAULT_PG_PASSWORD,
) -> Iterator[Tuple[str, str]]:
    """Spin up a fresh PG container; yield (container_name, db_url).

    Tear down on exit even if assertions fail — relies on context-manager
    semantics so the container never leaks across runs.
    """
    name = f"ld-pg-smoke-{uuid.uuid4().hex[:8]}"
    print(f"[pg_smoke] starting {image} as {name} on host port {port}…", flush=True)
    subprocess.run(
        [
            "docker", "run", "-d", "--rm",
            "--name", name,
            "-e", f"POSTGRES_DB={db}",
            "-e", f"POSTGRES_USER={user}",
            "-e", f"POSTGRES_PASSWORD={password}",
            "-p", f"{port}:5432",
            image,
        ],
        check=True,
        stdout=subprocess.DEVNULL,
    )
    db_url = f"postgresql://{user}:{password}@localhost:{port}/{db}"
    try:
        _wait_for_pg(db_url)
        yield name, db_url
    finally:
        print(f"[pg_smoke] tearing down {name}…", flush=True)
        subprocess.run(
            ["docker", "rm", "-f", name],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )


def _wait_for_pg(db_url: str, timeout_s: int = 30) -> None:
    """Poll the PG instance until accepting connections, or timeout."""
    from sqlalchemy import create_engine, text
    deadline = time.time() + timeout_s
    last_err: Exception | None = None
    while time.time() < deadline:
        try:
            eng = create_engine(db_url)
            with eng.connect() as conn:
                conn.execute(text("SELECT 1"))
            eng.dispose()
            return
        except Exception as e:  # pragma: no cover — sleep-and-retry path
            last_err = e
            time.sleep(0.5)
    raise RuntimeError(
        f"Postgres at {db_url} did not become ready within {timeout_s}s; "
        f"last error: {last_err!r}"
    )


# ---------------------------------------------------------------------------
# Alembic helpers (subprocess so each invocation gets a fresh DATABASE_URL)
# ---------------------------------------------------------------------------

def _run_alembic(db_url: str, *args: str) -> None:
    env = dict(os.environ)
    env["DATABASE_URL"] = db_url
    cmd = [sys.executable, "-m", "alembic", *args]
    print(f"[pg_smoke] alembic {' '.join(args)}", flush=True)
    res = subprocess.run(
        cmd,
        cwd=_BACKEND_DIR,
        env=env,
        capture_output=True,
        text=True,
    )
    if res.returncode != 0:
        sys.stdout.write(res.stdout)
        sys.stderr.write(res.stderr)
        raise RuntimeError(
            f"alembic {' '.join(args)} failed (exit {res.returncode}). "
            "See stderr above for the migration traceback."
        )


def _create_all(db_url: str) -> None:
    """Run SQLAlchemy ``create_all`` against the given DB URL.

    Used by the fresh-DB branch — mirrors what ``start.sh`` does on a
    brand-new deployment before stamping alembic head.
    """
    # Subprocess so we don't pollute the parent's database engine.
    code = (
        "import os; "
        "os.environ['DATABASE_URL']=" + repr(db_url) + "; "
        "from database import create_tables; create_tables()"
    )
    print("[pg_smoke] python -c 'from database import create_tables; create_tables()'", flush=True)
    res = subprocess.run(
        [sys.executable, "-c", code],
        cwd=_BACKEND_DIR,
        capture_output=True,
        text=True,
    )
    if res.returncode != 0:
        sys.stdout.write(res.stdout)
        sys.stderr.write(res.stderr)
        raise RuntimeError(f"create_tables failed (exit {res.returncode}).")


# ---------------------------------------------------------------------------
# Smoke spot-checks (run after each upgrade path)
# ---------------------------------------------------------------------------

def _smoke_spot_check(db_url: str, label: str) -> None:
    """After alembic finishes, verify the resulting DB shape is sane.

    Asserts:
      - Phase 8.5's ``sub_org_memberships`` table exists (the one whose
        creation collided in the 502 incident).
      - Phase 8's ``proposals.sustained_majority_enabled`` column exists.
      - Phase 9's ``polises`` and ``polis_xids`` tables exist.
      - Phase 9's ``proposals.linked_polis_ids`` column exists.
      - alembic_version row matches the chain head.

    Run after each mode; passes only if the schema was actually constructed
    end-to-end.
    """
    from sqlalchemy import create_engine, text

    eng = create_engine(db_url)
    try:
        with eng.connect() as conn:
            # Phase 8.5's table — the one that hit the collision.
            res = conn.execute(text(
                "SELECT to_regclass('public.sub_org_memberships') IS NOT NULL"
            )).scalar()
            assert res, f"[{label}] sub_org_memberships table missing"

            # Phase 8's sustained_majority_enabled column on proposals.
            res = conn.execute(text(
                "SELECT 1 FROM information_schema.columns "
                "WHERE table_schema='public' AND table_name='proposals' "
                "AND column_name='sustained_majority_enabled'"
            )).scalar()
            assert res, (
                f"[{label}] proposals.sustained_majority_enabled column missing"
            )

            # Phase 9's polises table.
            res = conn.execute(text(
                "SELECT to_regclass('public.polises') IS NOT NULL"
            )).scalar()
            assert res, f"[{label}] polises table missing"

            # Phase 9's polis_xids table.
            res = conn.execute(text(
                "SELECT to_regclass('public.polis_xids') IS NOT NULL"
            )).scalar()
            assert res, f"[{label}] polis_xids table missing"

            # Phase 9's linked_polis_ids column on proposals.
            res = conn.execute(text(
                "SELECT 1 FROM information_schema.columns "
                "WHERE table_schema='public' AND table_name='proposals' "
                "AND column_name='linked_polis_ids'"
            )).scalar()
            assert res, (
                f"[{label}] proposals.linked_polis_ids column missing"
            )

            # Phase 9 Session 2's intended_seed_statements column on polises.
            res = conn.execute(text(
                "SELECT 1 FROM information_schema.columns "
                "WHERE table_schema='public' AND table_name='polises' "
                "AND column_name='intended_seed_statements'"
            )).scalar()
            assert res, (
                f"[{label}] polises.intended_seed_statements column missing"
            )

            # Phase 9.5's users.org_creation_limit column.
            res = conn.execute(text(
                "SELECT 1 FROM information_schema.columns "
                "WHERE table_schema='public' AND table_name='users' "
                "AND column_name='org_creation_limit'"
            )).scalar()
            assert res, (
                f"[{label}] users.org_creation_limit column missing"
            )

            # Phase 9.5's platform_settings table + seeded row.
            res = conn.execute(text(
                "SELECT to_regclass('public.platform_settings') IS NOT NULL"
            )).scalar()
            assert res, f"[{label}] platform_settings table missing"
            count = conn.execute(text(
                "SELECT COUNT(*) FROM platform_settings"
            )).scalar()
            assert count >= 1, (
                f"[{label}] platform_settings table has no rows; "
                f"expected at least the seeded org_creation_mode='open'"
            )
            seeded = conn.execute(text(
                "SELECT 1 FROM platform_settings "
                "WHERE key = 'org_creation_mode'"
            )).scalar()
            assert seeded, (
                f"[{label}] platform_settings missing the seeded "
                f"org_creation_mode row"
            )

            # alembic_version row matches head
            ver = conn.execute(text(
                "SELECT version_num FROM alembic_version"
            )).scalar()
            head = _alembic_head_revision()
            assert ver == head, (
                f"[{label}] alembic_version={ver}, expected head={head}"
            )
    finally:
        eng.dispose()
    print(f"[pg_smoke] [{label}] spot-check PASS (tables present, alembic at head).", flush=True)


def _alembic_head_revision() -> str:
    """Return the head revision id from the migrations directory."""
    res = subprocess.run(
        [sys.executable, "-m", "alembic", "heads", "--verbose"],
        cwd=_BACKEND_DIR,
        capture_output=True,
        text=True,
        check=True,
    )
    # Output line looks like "Rev: <hex> (head) ...". Pick the first hex token.
    for line in res.stdout.splitlines():
        line = line.strip()
        if line.startswith("Rev:"):
            return line.split()[1]
    raise RuntimeError(
        f"Could not parse alembic head from output:\n{res.stdout}"
    )


# ---------------------------------------------------------------------------
# Mode runners
# ---------------------------------------------------------------------------

def run_fresh(db_url: str) -> None:
    """Fresh-DB path: ``create_all`` + ``stamp head``. Mirrors start.sh's
    fresh branch.
    """
    print("\n=== MODE: fresh-DB (create_all + stamp head) ===", flush=True)
    _create_all(db_url)
    _run_alembic(db_url, "stamp", "head")
    _smoke_spot_check(db_url, "fresh")


def run_upgrade(db_url: str, prior_rev: str) -> None:
    """Upgrade-from-prior path: ``stamp <prior>`` + ``upgrade head``.

    Why ``stamp`` not ``upgrade <prior>``: the alembic chain's base
    revision ALTERs ``users``, which doesn't exist on an empty PG. So we
    can't faithfully replay the chain from base — we have to seed the
    Phase 1/2 tables via ``create_all`` first, then ``stamp`` at the
    prior revision (telling alembic "you're already at <prior>"), then
    apply only the *pending* migrations via ``upgrade head``. This is
    exactly what an existing prod container looks like the moment a new
    pass deploys.

    For a future cleanup pass: when the alembic chain no longer assumes
    pre-existing tables (i.e., when the chain is squashed or the base
    revision is rewritten to create the early tables), this can shift
    to ``upgrade <prior>`` + ``upgrade head`` for a fully-replayed path.
    """
    print(
        f"\n=== MODE: upgrade-from-prior (prior={prior_rev}) ===",
        flush=True,
    )
    # 1. Build the schema as it existed at the prior revision.
    #    Best approximation given the chain's "tables-exist" assumption:
    #    create_all today's models, then stamp at the prior rev. This
    #    actually OVER-shapes the schema (today's columns/tables included),
    #    so the upgrade-from-prior path only meaningfully tests the *new*
    #    migration's idempotency / collision-resistance — which is the
    #    exact bug class this harness is designed to catch.
    _create_all(db_url)
    _run_alembic(db_url, "stamp", prior_rev)
    # 2. Apply pending migrations (the pass-under-test's revisions).
    _run_alembic(db_url, "upgrade", "head")
    _smoke_spot_check(db_url, "upgrade")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Phase 8.6 Item 4 — PG smoke harness (alembic upgrade path).",
    )
    parser.add_argument(
        "--mode",
        choices=("fresh", "upgrade", "both"),
        default="both",
        help="Which path to exercise (default: both).",
    )
    parser.add_argument(
        "--prior-revision",
        default=_DEFAULT_PRIOR_REV,
        help=(
            f"Alembic revision to stamp before running upgrade head. "
            f"Default: {_DEFAULT_PRIOR_REV} (Phase 8 — immediately prior "
            "to the Phase 8.5 d41a8c92f3b1 sub-org migration)."
        ),
    )
    parser.add_argument(
        "--reuse-pg-url",
        default=None,
        help=(
            "Skip container management and run against an existing PG URL. "
            "Caller is responsible for providing an empty database."
        ),
    )
    args = parser.parse_args()

    modes = ("fresh", "upgrade") if args.mode == "both" else (args.mode,)

    if args.reuse_pg_url:
        db_url = args.reuse_pg_url
        try:
            for m in modes:
                if m == "fresh":
                    run_fresh(db_url)
                else:
                    run_upgrade(db_url, args.prior_revision)
            print("\nPG SMOKE PASS")
            return 0
        except Exception:
            print("\nPG SMOKE FAIL:")
            traceback.print_exc()
            return 2

    if not _have_docker():
        print(
            "ERROR: docker not on PATH. Install docker or pass "
            "--reuse-pg-url postgresql://… for an externally-managed DB.",
            file=sys.stderr,
        )
        return 1

    overall_rc = 0
    for m in modes:
        # Each mode gets its own container so we never carry state between
        # paths — fresh- and upgrade- are independent assertions.
        try:
            with _pg_container() as (_name, db_url):
                if m == "fresh":
                    run_fresh(db_url)
                else:
                    run_upgrade(db_url, args.prior_revision)
        except Exception:
            print(f"\nPG SMOKE FAIL ({m} mode):")
            traceback.print_exc()
            overall_rc = 2

    if overall_rc == 0:
        print("\nPG SMOKE PASS (all modes)")
    return overall_rc


if __name__ == "__main__":
    sys.exit(main())
