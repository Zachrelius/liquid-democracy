"""Trigger a demo-org reset on prod via the B0.1 endpoint.

Usage:
    python scripts/trigger_demo_reset.py [--env-file .env] [--url https://liquiddemocracy.us]

Reads ``DEMO_RESET_TRIGGER_TOKEN`` from .env (or shell environment) and
POSTs to ``/api/demo/trigger-reset``. Prints the response status and body
— including the ``DemoResetResult`` audit-shape JSON so the caller can see
which orgs were reset, row counts wiped/seeded, and any error/skip reason.

Exit codes:
    0 — 200 OK from the endpoint.
    1 — token missing from environment (no request made).
    2 — non-2xx response (request made, server returned an error or 401/503).

Spec: phase23_2_demo_metadata_dispatch_2026-05-13.md §B0.2.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--env-file",
        default=".env",
        help="Path to .env file (default: .env in cwd).",
    )
    parser.add_argument(
        "--url",
        default="https://liquiddemocracy.us",
        help="Base URL of the deployment (default: https://liquiddemocracy.us).",
    )
    args = parser.parse_args()

    env_path = Path(args.env_file)
    if env_path.exists():
        load_dotenv(env_path)

    token = os.environ.get("DEMO_RESET_TRIGGER_TOKEN")
    if not token:
        print(
            "ERROR: DEMO_RESET_TRIGGER_TOKEN not set in environment or .env",
            file=sys.stderr,
        )
        sys.exit(1)

    endpoint = f"{args.url.rstrip('/')}/api/demo/trigger-reset"
    print(f"POST {endpoint}")
    resp = requests.post(
        endpoint,
        headers={"Authorization": f"Bearer {token}"},
        timeout=120,  # reset can take ~30s + Railway warmup margin
    )
    print(f"Status: {resp.status_code}")
    content_type = resp.headers.get("content-type", "")
    if content_type.startswith("application/json"):
        import json
        print(json.dumps(resp.json(), indent=2, sort_keys=True))
    else:
        print(resp.text)

    sys.exit(0 if resp.ok else 2)


if __name__ == "__main__":
    main()
