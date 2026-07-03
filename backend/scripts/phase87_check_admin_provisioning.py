"""Phase 87 Cluster 3 — READ-ONLY prod pre-check for admin provisioning.

Reports, without mutating anything:
  * The ZacharyAdmin account (email z@liquiddemocracy.us): existence,
    is_admin, is_active, email_verified.
  * The seeded bootstrap 'admin' account: is_admin, is_active, and every
    active OrgMembership (org slug, is_demo, role system_key) so we can tell
    whether disabling it would strand a real org's governance.

Run with prod env injected:  railway run python backend/scripts/phase87_check_admin_provisioning.py
"""
import os

from sqlalchemy import create_engine, text


def main() -> None:
    # Prefer the public proxy URL (reachable from outside Railway's network);
    # fall back to DATABASE_URL (internal host, only works inside Railway).
    url = os.environ.get("DATABASE_PUBLIC_URL") or os.environ.get("DATABASE_URL")
    if not url:
        raise SystemExit("No DATABASE_PUBLIC_URL / DATABASE_URL (run under `railway run`).")
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    eng = create_engine(url)
    with eng.connect() as c:
        print("=== ZacharyAdmin (z@liquiddemocracy.us) ===")
        rows = c.execute(text(
            "SELECT id, username, is_admin, is_active, email_verified "
            "FROM users WHERE lower(email) = 'z@liquiddemocracy.us'"
        )).fetchall()
        if not rows:
            print("  NOT FOUND")
        for r in rows:
            print(f"  id={r[0]} username={r[1]} is_admin={r[2]} is_active={r[3]} email_verified={r[4]}")

        print("\n=== seeded bootstrap 'admin' account(s) ===")
        admins = c.execute(text(
            "SELECT id, username, email, is_admin, is_active "
            "FROM users WHERE username = 'admin'"
        )).fetchall()
        if not admins:
            print("  NOT FOUND")
        for a in admins:
            print(f"  id={a[0]} username={a[1]} email={a[2]} is_admin={a[3]} is_active={a[4]}")
            mems = c.execute(text(
                "SELECT o.slug, o.is_demo, r.system_key "
                "FROM org_memberships m "
                "JOIN organizations o ON o.id = m.org_id "
                "LEFT JOIN roles r ON r.id = m.role_id "
                "WHERE m.user_id = :uid AND m.status = 'active'"
            ), {"uid": a[0]}).fetchall()
            if not mems:
                print("    (no active org memberships)")
            for mrow in mems:
                print(f"    org={mrow[0]} is_demo={mrow[1]} role={mrow[2]}")

        print("\n=== all platform admins (is_admin=TRUE) ===")
        for r in c.execute(text(
            "SELECT username, email, is_active FROM users WHERE is_admin = TRUE"
        )).fetchall():
            print(f"  username={r[0]} email={r[1]} is_active={r[2]}")


if __name__ == "__main__":
    main()
