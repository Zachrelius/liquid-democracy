from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker, Session
from typing import Generator

from settings import settings

# Phase 35 D17 — explicit SQLAlchemy pool config (was implicit SA default
# pool_size=5 + max_overflow=10 = 15 connections per worker process).
# At Cedar Hollow's single-instance friend-pilot scale, 15 connections per
# worker is wasteful overprovisioning. Each idle connection holds a small
# server-side allocation in PG + a client-side socket + ~5-10MB of
# SA per-connection state. Reducing to pool_size=2 + max_overflow=3 gives
# 5 connections per worker (more than sufficient for the single-worker
# default in start.sh) and frees memory for application work.
#
# SQLite-on-test path: use SA's default (the connect_args check below).
_engine_kwargs: dict = {
    "connect_args": {"check_same_thread": False} if "sqlite" in settings.database_url else {},
}
if "sqlite" not in settings.database_url:
    _engine_kwargs["pool_size"] = int(__import__("os").environ.get("DB_POOL_SIZE", "2"))
    _engine_kwargs["max_overflow"] = int(__import__("os").environ.get("DB_MAX_OVERFLOW", "3"))
    _engine_kwargs["pool_timeout"] = settings.db_pool_timeout_seconds
    _engine_kwargs["pool_recycle"] = 1800  # 30 min — drop idle connections to free memory
    _engine_kwargs["pool_pre_ping"] = True  # tolerate Railway's idle connection drops

engine = create_engine(settings.database_url, **_engine_kwargs)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def pool_snapshot() -> dict:
    """Return coarse QueuePool counters without connection identities."""
    pool = engine.pool
    required = ("size", "checkedout", "overflow")
    if not all(callable(getattr(pool, name, None)) for name in required):
        return {
            "supported": False, "size": None, "max_overflow": None,
            "capacity": None, "checked_out": None, "current_overflow": None,
            "utilization_percent": None,
            "pool_timeout_seconds": settings.db_pool_timeout_seconds,
        }
    size = int(pool.size())
    checked_out = int(pool.checkedout())
    current_overflow = max(0, int(pool.overflow()))
    max_overflow = int(_engine_kwargs.get("max_overflow", 0))
    capacity = max(1, size + max_overflow)
    return {
        "supported": True,
        "size": size,
        "max_overflow": max_overflow,
        "capacity": capacity,
        "checked_out": checked_out,
        "current_overflow": current_overflow,
        "utilization_percent": round(100 * checked_out / capacity, 2),
        "pool_timeout_seconds": settings.db_pool_timeout_seconds,
    }


class Base(DeclarativeBase):
    pass


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        # Explicit rollback makes the transaction boundary auditable and
        # guarantees pool-timeout/error paths never return an open transaction
        # to the pool. Session.close() also rolls back, but keeping it explicit
        # protects this load-bearing cleanup contract from future Session
        # configuration changes.
        if db.in_transaction():
            db.rollback()
        db.close()


def create_tables() -> None:
    import models  # noqa: F401 — registers ORM classes with Base metadata
    Base.metadata.create_all(bind=engine)
    _seed_platform_defaults()


def _seed_platform_defaults() -> None:
    """Phase 9.5 — ensure `platform_settings` has the org-creation-mode row.

    Fresh-deploy path runs create_tables() + `alembic stamp head`, which
    means the 373e1f066cc1 migration's INSERT is never executed. We mirror
    its seed here so the invariant "platform_settings.org_creation_mode
    exists and equals 'open'" holds regardless of how the schema arrived.
    Idempotent — safe to call repeatedly.
    """
    import models
    db = SessionLocal()
    try:
        existing = db.get(models.PlatformSetting, "org_creation_mode")
        if existing is None:
            db.add(models.PlatformSetting(
                key="org_creation_mode", value="open",
            ))
            db.commit()
    finally:
        db.close()
