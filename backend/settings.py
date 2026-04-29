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

    # Phase 8 — Sustained-Majority worker.
    # Cadence between snapshot+evaluation passes during active voting windows.
    # 5min default balances stale-detection vs DB write volume.
    sustained_majority_check_interval_seconds: int = 300
    # Multi-instance protection: when set, the worker only runs on the
    # process whose `INSTANCE_ID` (or RAILWAY_REPLICA_ID) env var matches.
    # Empty string = run unconditionally (default; fine for single-instance).
    sustained_majority_worker_instance_id: str = ""
    # Hard kill-switch for ops emergencies.
    sustained_majority_worker_disable: bool = False

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
