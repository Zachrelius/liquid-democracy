"""
Centralised configuration via Pydantic BaseSettings.
All values can be overridden with environment variables or a .env file.
"""

from pydantic_settings import BaseSettings
from pydantic import field_validator
from typing import Optional


class Settings(BaseSettings):
    # Database — SQLite default for local dev; set DATABASE_URL for PostgreSQL in production
    database_url: str = "sqlite:///./liquid_democracy.db"

    # Auth
    secret_key: str = "change-me-in-production-use-a-long-random-string"
    jwt_expiration_minutes: int = 15  # Short-lived access tokens; use refresh tokens

    # CORS
    cors_origins: list[str] = ["http://localhost:5173", "http://localhost:3000"]

    # Debug / logging
    debug: bool = False
    log_level: str = "INFO"

    # Public demo deployment flag — enables persona picker + demo-org auto-join.
    # SEPARATE from `debug`: debug = dev-mode features (seed endpoint, time sim);
    # is_public_demo = this deployment is the public EA-demo environment.
    is_public_demo: bool = False

    # Email delivery — Resend (preferred for cloud deploys where SMTP is blocked)
    # takes priority over SMTP when resend_api_key is set.
    resend_api_key: str = ""

    # SMTP settings (all optional — if both resend_api_key and smtp_host are empty,
    # emails are logged to console)
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    from_email: str = ""

    # Base URL for links in emails
    base_url: str = "http://localhost:5173"

    # Phase 8 / Phase 20 — Stable Result Required worker (formerly
    # Sustained-Majority worker; renamed user-facing in Phase 20). The env-var
    # NAMES retain the legacy `SUSTAINED_MAJORITY_*` prefix for backwards-compat
    # with prod env files (per spec D15 + spec line 477). Phase 20 also adds
    # `STABLE_RESULT_*` aliases that resolve to the same fields — see the
    # `__init__` override below.
    #
    # Cadence between snapshot+evaluation passes during active voting windows.
    # 5min default balances stale-detection vs DB write volume.
    sustained_majority_check_interval_seconds: int = 300
    # Multi-instance protection: when set, the worker only runs on the
    # process whose `INSTANCE_ID` (or RAILWAY_REPLICA_ID) env var matches.
    # Empty string = run unconditionally (default; fine for single-instance).
    sustained_majority_worker_instance_id: str = ""
    # Hard kill-switch for ops emergencies.
    sustained_majority_worker_disable: bool = False

    # Phase 23 (D9) — demo daily-reset time-of-day, HH:MM 24h format in
    # Pacific timezone. Default midnight Pacific. The scheduler computes
    # the next due moment from this value + the
    # ``demo_reset_last_completed_at`` PlatformSetting. Operationally
    # tunable via the DEMO_RESET_TIME_PACIFIC env var without code change.
    demo_reset_time_pacific: str = "00:00"

    # Phase 9 — pol.is integration. The hosted pol.is API uses JWT-based auth
    # rather than an API key (see `phase9_polis_api_findings.md`); this is the
    # Bearer JWT obtained from a pol.is admin session that polis_service.py
    # sends in the `Authorization: Bearer <token>` header. Empty string =
    # programmatic API integration disabled (manual create-conversation-on-pol.is
    # fallback flow is the v1 prod default until CompDemocracy admin-token
    # access or self-hosting lands).
    polis_auth_token: str = ""
    # Base URL for the pol.is API. Override for self-hosted instances.
    polis_api_base_url: str = "https://pol.is"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


def _build_settings() -> Settings:
    """Build Settings, applying Phase 20 STABLE_RESULT_* env-var aliases.

    Per spec line 477: the env var ``SUSTAINED_MAJORITY_CHECK_INTERVAL_SECONDS``
    keeps its name (deployed in prod env files; renaming would require a
    coordinated env-var-edit-and-deploy). Phase 20 adds
    ``STABLE_RESULT_CHECK_INTERVAL_SECONDS`` and the worker-control aliases
    that resolve to the same fields. If both are set, the new (STABLE_RESULT_*)
    name wins so operators can flip cleanly post-rename.
    """
    import os as _os
    overrides: dict[str, object] = {}
    new_check = _os.environ.get("STABLE_RESULT_CHECK_INTERVAL_SECONDS")
    if new_check is not None and new_check.strip() != "":
        try:
            overrides["sustained_majority_check_interval_seconds"] = int(new_check)
        except ValueError:
            pass
    new_inst = _os.environ.get("STABLE_RESULT_WORKER_INSTANCE_ID")
    if new_inst is not None:
        overrides["sustained_majority_worker_instance_id"] = new_inst
    new_dis = _os.environ.get("STABLE_RESULT_WORKER_DISABLE")
    if new_dis is not None and new_dis.strip() != "":
        overrides["sustained_majority_worker_disable"] = new_dis.lower() in (
            "1", "true", "yes", "on",
        )
    return Settings(**overrides)


settings = _build_settings()
