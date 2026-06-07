"""Phase 58 Cluster C migration cycle test.

Asserts:
  * upgrade drops `verification_nullifier` + `doc_number_hash` + their
    lookup indexes (the partial-unique `ix_users_doc_number_hash_unique`
    was already dropped in `e6f7a8b9c0d1`).
  * downgrade re-adds the columns + the lookup indexes.
  * cycle round-trip (up→down→up) clean.
  * grep-style guard: no product code references the dropped columns.

The fixture-side parallel to Cluster T's Topic.description sweep: this
test pins the new state in CI so a future re-introduction of either
column would surface immediately.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import sqlalchemy as sa


_BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_PHASE_58_REVISION = "c0d1e2f3a4b5"
_PRIOR_REVISION = "b9c0d1e2f3a4"  # Phase 57 access axes

NULLIFIER_LOOKUP_INDEX = "ix_users_verification_nullifier"
NULLIFIER_UNIQUE_INDEX = "ix_users_verification_nullifier_unique"
DOC_NUMBER_LOOKUP_INDEX = "ix_users_doc_number_hash"


def _run_alembic(db_url: str, *args: str) -> None:
    env = dict(os.environ)
    env["DATABASE_URL"] = db_url
    res = subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=_BACKEND_DIR, env=env,
        capture_output=True, text=True,
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


def _columns(db_url: str, table: str) -> set[str]:
    engine = sa.create_engine(db_url)
    try:
        return {c["name"] for c in sa.inspect(engine).get_columns(table)}
    finally:
        engine.dispose()


def _indexes(db_url: str, table: str) -> set[str]:
    engine = sa.create_engine(db_url)
    try:
        return {ix["name"] for ix in sa.inspect(engine).get_indexes(table)}
    finally:
        engine.dispose()


def _build_pre_58(db_url: str) -> None:
    _create_all_subprocess(db_url)
    _run_alembic(db_url, "stamp", "head")
    _run_alembic(db_url, "downgrade", _PRIOR_REVISION)


# ===========================================================================
# Column / index drops
# ===========================================================================


def test_phase_58_upgrade_drops_columns_and_indexes():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db_url = f"sqlite:///{path}"
    try:
        _build_pre_58(db_url)
        pre = _columns(db_url, "users")
        # Both columns exist pre-Phase-58 (added in Phase 51 + Phase 52d
        # respectively; the downgrade chain through Phase 58 down re-adds
        # them, then we sit at PRIOR_REVISION which restores them via the
        # Phase 51 / 52d upgrades they originally came from).
        assert "verification_nullifier" in pre
        assert "doc_number_hash" in pre

        _run_alembic(db_url, "upgrade", "head")
        post = _columns(db_url, "users")
        assert "verification_nullifier" not in post, (
            "Phase 58 upgrade must drop users.verification_nullifier"
        )
        assert "doc_number_hash" not in post, (
            "Phase 58 upgrade must drop users.doc_number_hash"
        )

        post_idx = _indexes(db_url, "users")
        assert NULLIFIER_LOOKUP_INDEX not in post_idx
        assert NULLIFIER_UNIQUE_INDEX not in post_idx
        assert DOC_NUMBER_LOOKUP_INDEX not in post_idx
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def test_phase_58_downgrade_upgrade_cycle():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db_url = f"sqlite:///{path}"
    try:
        _build_pre_58(db_url)
        _run_alembic(db_url, "upgrade", "head")
        post = _columns(db_url, "users")
        assert "verification_nullifier" not in post
        assert "doc_number_hash" not in post

        _run_alembic(db_url, "downgrade", _PRIOR_REVISION)
        post_down = _columns(db_url, "users")
        assert "verification_nullifier" in post_down, (
            "Phase 58 downgrade must re-add users.verification_nullifier"
        )
        assert "doc_number_hash" in post_down, (
            "Phase 58 downgrade must re-add users.doc_number_hash"
        )

        post_down_idx = _indexes(db_url, "users")
        assert NULLIFIER_LOOKUP_INDEX in post_down_idx
        assert DOC_NUMBER_LOOKUP_INDEX in post_down_idx
        # The partial-unique is NOT re-created on downgrade — it was
        # dropped pre-Phase-58 in `e6f7a8b9c0d1` and is intentionally
        # not restored here. Documented in the migration body.

        # Re-upgrade returns to the dropped state.
        _run_alembic(db_url, "upgrade", "head")
        post2 = _columns(db_url, "users")
        assert "verification_nullifier" not in post2
        assert "doc_number_hash" not in post2
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


# ===========================================================================
# Grep-guard: no product code references the dropped columns
# ===========================================================================


def test_no_product_code_references_dropped_columns():
    """Cluster C2 grep-style guard. Scans backend product source for
    ATTRIBUTE-LEVEL reads/writes of the two dropped column names —
    `.verification_nullifier` / `.doc_number_hash`, or assignments to
    bare names. Dict keys, comments, docstrings, and migration history
    are intentionally allowed (they don't re-introduce the bug).

    Excludes migrations + tests + cache dirs. A future re-introduction
    of a real attribute access in product code surfaces here.
    """
    backend_root = Path(_BACKEND_DIR)
    # Match `.verification_nullifier` or `.doc_number_hash` (attribute
    # access on any object) OR a bare assignment `verification_nullifier
    # =` / `doc_number_hash =` at statement scope. The dot prefix
    # excludes dict-key strings ("doc_number_hash") and bare-token
    # mentions in comments / docstrings.
    bad_pattern = re.compile(
        r"\.(?:verification_nullifier|doc_number_hash)\b"
        r"|^\s*(?:verification_nullifier|doc_number_hash)\s*[:=]",
    )
    excluded_dir_segments = {"migrations", "tests", "__pycache__", ".venv"}

    offenders: list[tuple[str, int, str]] = []
    for py in backend_root.rglob("*.py"):
        rel = py.relative_to(backend_root)
        if any(part in excluded_dir_segments for part in rel.parts):
            continue
        try:
            text = py.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            # Strip comment-only lines; in-line trailing comments are
            # preserved (an attribute access on a code line still
            # counts even if the line has a trailing comment).
            stripped = line.lstrip()
            if stripped.startswith("#"):
                continue
            if bad_pattern.search(line):
                offenders.append((str(rel), lineno, line.strip()))
    assert not offenders, (
        "Phase 58 Cluster C grep guard: product code makes attribute "
        "access on the dropped column(s):\n"
        + "\n".join(f"  {p}:{ln} {src}" for p, ln, src in offenders)
    )
