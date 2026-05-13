#!/bin/bash
set -e

# Phase 26 B1 — container entrypoint runs as root, fixes Railway-volume
# ownership, then drops privileges to appuser via gosu before exec-ing
# the real start.sh.
#
# Why this is needed:
#   * Railway mounts the volume at /data/uploads owned by root.
#   * The Dockerfile creates appuser and the FastAPI process runs as
#     appuser for security (no root in long-running code paths).
#   * Without this fix, the app cannot mkdir under /data/uploads at
#     startup — PermissionError, 502'd service. Phase 25.1 added a
#     writability fallback that degraded uploads to ephemeral storage;
#     this entrypoint addresses the root cause so uploads persist
#     across redeploys.
#
# chown is idempotent — a no-op when ownership already matches. The
# `2>/dev/null || true` swallows errors if /data/uploads isn't present
# (local dev without the volume) or if chown is denied for some unusual
# Railway configuration; the writability fallback in routes/avatars.py
# still catches that case.

if [ -d "/data/uploads" ]; then
    chown -R appuser:appuser /data/uploads 2>/dev/null || true
fi

# Drop privileges and exec the real start script. exec replaces the
# current process so signals (SIGTERM from Railway redeploy) propagate
# to start.sh without an intermediate bash shell intercepting them.
exec gosu appuser bash /app/start.sh
