from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker, Session
from typing import Generator

from settings import settings

engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False} if "sqlite" in settings.database_url else {},
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
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
