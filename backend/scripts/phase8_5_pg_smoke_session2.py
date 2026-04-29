"""Phase 8.5 Session 2 PostgreSQL smoke harness.

Exercises the sub-org routes against a real PostgreSQL instance, verifies the
schema migration is compatible, and spot-tests the `get_org_config`-migrated
voting-method allowlist (sub-org override path).

Required env: `LD_PG_SMOKE_URL` pointing at a PG db where alembic is at head.

Usage from backend/:
  LD_PG_SMOKE_URL=postgresql://smoke:smoke@localhost:55432/ld_smoke_session2 \
    .venv/Scripts/python.exe scripts/phase8_5_pg_smoke_session2.py

Exit code 0 == PASS, non-zero == FAIL.
"""
from __future__ import annotations

import os
import sys
import traceback

# Ensure backend/ is importable when run from repo root.
_BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from fastapi.testclient import TestClient


def _reset_tables(engine):
    """Truncate all non-alembic tables to start each smoke run clean."""
    with engine.connect() as conn:
        tables = [r[0] for r in conn.execute(text(
            "SELECT tablename FROM pg_tables WHERE schemaname = 'public' "
            "AND tablename != 'alembic_version'"
        )).all()]
        if tables:
            conn.execute(text(
                "TRUNCATE TABLE " + ", ".join(f'"{t}"' for t in tables) +
                " RESTART IDENTITY CASCADE"
            ))
            conn.commit()


def main() -> int:
    pg_url = os.environ.get("LD_PG_SMOKE_URL")
    if not pg_url:
        print("ERROR: LD_PG_SMOKE_URL not set", file=sys.stderr)
        return 1

    engine = create_engine(pg_url)
    _reset_tables(engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False)

    # Override the FastAPI app's get_db dependency to use PG.
    from database import get_db
    from main import app
    import auth as auth_utils
    import models

    session = SessionLocal()

    def override_get_db():
        try:
            yield session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)

    try:
        _DUMMY_HASH = "$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/lewrwKJuRxm5pJmJi"

        # ----- Bootstrap: parent org with admin, sub-org with topic -----
        admin = models.User(
            username="pg_admin", display_name="PG Admin",
            password_hash=_DUMMY_HASH, email="pg_admin@test.example",
            email_verified=True,
        )
        session.add(admin)
        session.flush()

        parent = models.Organization(
            name="PG Parent", slug="pg-parent", description="",
            join_policy="open",
            settings={"allowed_voting_methods": ["binary", "approval"]},
        )
        session.add(parent)
        session.flush()

        session.add(models.OrgMembership(
            user_id=admin.id, org_id=parent.id, role="admin", status="active",
        ))
        session.commit()

        token = auth_utils.create_access_token(admin.id)
        h = {"Authorization": f"Bearer {token}"}

        # 1. Sub-org create
        resp = client.post(
            f"/api/orgs/{parent.slug}/sub-orgs",
            json={
                "name": "Eng",
                "slug": "pg-eng",
                "description": "",
                "settings": {
                    "allowed_voting_methods": [
                        "binary", "approval", "ranked_choice",
                    ],
                },
            },
            headers=h,
        )
        assert resp.status_code == 201, ("sub-org create", resp.status_code, resp.text)
        sub = resp.json()
        sub_id = sub["id"]

        # 2. Topic scoped to the sub-org
        topic = models.Topic(
            name="PG Topic", description="", color="#abc",
            org_id=parent.id, sub_org_id=sub_id,
        )
        session.add(topic)
        session.commit()

        # 3. Sub-org RCV proposal succeeds (sub-org's allowlist via get_org_config)
        resp = client.post(
            f"/api/orgs/{parent.slug}/proposals",
            json={
                "title": "PG RCV Sub Prop",
                "body": "",
                "topics": [topic.id],
                "voting_method": "ranked_choice",
                "sub_org_id": sub_id,
                "options": [
                    {"label": "A"}, {"label": "B"}, {"label": "C"},
                ],
            },
            headers=h,
        )
        assert resp.status_code == 201, ("sub RCV", resp.status_code, resp.text)

        # 4. Parent-org RCV proposal still fails (parent allowlist)
        resp = client.post(
            f"/api/orgs/{parent.slug}/proposals",
            json={
                "title": "PG RCV Parent Prop",
                "body": "",
                "topics": [],
                "voting_method": "ranked_choice",
                "options": [
                    {"label": "A"}, {"label": "B"},
                ],
            },
            headers=h,
        )
        assert resp.status_code == 403, ("parent RCV reject", resp.status_code, resp.text)

        # 5. Parent-scoped binary proposal still works
        resp = client.post(
            f"/api/orgs/{parent.slug}/proposals",
            json={
                "title": "PG Binary Parent Prop",
                "body": "",
                "topics": [],
                "voting_method": "binary",
            },
            headers=h,
        )
        assert resp.status_code == 201, ("parent binary", resp.status_code, resp.text)

        # 6. Sub-org list visibility
        resp = client.get(f"/api/orgs/{parent.slug}/sub-orgs", headers=h)
        assert resp.status_code == 200
        assert any(s["slug"] == "pg-eng" for s in resp.json())

        # 7. Audit events present
        events = session.query(models.AuditLog).filter(
            models.AuditLog.action == "sub_org.created",
        ).all()
        assert len(events) >= 1, "sub_org.created audit event missing"

        print("PG SMOKE PASS")
        return 0

    except AssertionError as e:
        print("PG SMOKE FAIL:")
        traceback.print_exc()
        return 2
    except Exception:
        print("PG SMOKE FAIL (unexpected error):")
        traceback.print_exc()
        return 3
    finally:
        session.close()
        app.dependency_overrides.clear()
        engine.dispose()


if __name__ == "__main__":
    sys.exit(main())
