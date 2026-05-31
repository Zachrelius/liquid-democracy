"""Phase 44 — Multi-admin approval workflow.

Public API:
  - ``settings``: per-org opt-in + threshold + window config.
  - ``registry``: action-type definitions (permission key + approver
    set + payload validation + execution + change preview).
  - ``engine``: submit / approve / decline / execute / expire orchestration.

Import shape kept flat — callers do ``from pending_actions import
settings, registry, engine``.
"""

from . import engine, registry, settings  # noqa: F401
