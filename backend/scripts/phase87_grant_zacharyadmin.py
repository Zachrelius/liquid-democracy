"""Phase 87 Cluster 3 — grant is_admin to ZacharyAdmin (prod, one-time).

Surgical + safe:
  * Targets ONLY the account with email z@liquiddemocracy.us / username
    ZacharyAdmin, matched on BOTH before writing.
  * Prints the row before and after (OBSERVED).
  * Does NOT touch the seeded 'admin' bootstrap account (it is the sole
    steward of an org, so disabling it is deferred to Z per the dispatch).

Run:  railway run --service Postgres <venv-python> backend/scripts/phase87_grant_zacharyadmin.py
"""
import os

from sqlalchemy import create_engine, text


_EXPECTED_EMAIL = "z@liquiddemocracy.us"
_EXPECTED_USERNAME = "ZacharyAdmin"


def main() -> None:
    url = os.environ.get("DATABASE_PUBLIC_URL") or os.environ.get("DATABASE_URL")
    if not url:
        raise SystemExit("No DATABASE_PUBLIC_URL / DATABASE_URL.")
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    eng = create_engine(url)
    with eng.begin() as c:
        row = c.execute(text(
            "SELECT id, username, email, is_admin, is_active, email_verified "
            "FROM users WHERE lower(email) = :e"
        ), {"e": _EXPECTED_EMAIL}).fetchone()
        if row is None:
            raise SystemExit(f"No user with email {_EXPECTED_EMAIL}; aborting.")
        if row[1] != _EXPECTED_USERNAME:
            raise SystemExit(
                f"Username mismatch (got {row[1]!r}, expected {_EXPECTED_USERNAME!r}); aborting."
            )
        print("BEFORE:", dict(id=row[0], username=row[1], email=row[2],
                              is_admin=row[3], is_active=row[4], email_verified=row[5]))
        if row[3] is True:
            print("Already is_admin=True; no change.")
            return
        c.execute(text("UPDATE users SET is_admin = TRUE WHERE id = :id"), {"id": row[0]})
        after = c.execute(text(
            "SELECT id, username, email, is_admin, is_active, email_verified "
            "FROM users WHERE id = :id"
        ), {"id": row[0]}).fetchone()
        print("AFTER: ", dict(id=after[0], username=after[1], email=after[2],
                             is_admin=after[3], is_active=after[4], email_verified=after[5]))


if __name__ == "__main__":
    main()
