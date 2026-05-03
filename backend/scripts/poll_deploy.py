"""Poll Railway after a master push until the new bundle is live + backend is up.

Phase 10.2 W-FIX-D: this script also runs the prod smoke suite
(tests/smoke/) once the bundle hash has flipped + backend returns 200,
so we catch boundary regressions inside the same window we'd otherwise
spend manually verifying. Smoke total runtime is ~2 seconds — well
under the budget for inline post-deploy verification.

Usage:
    backend/.venv/Scripts/python backend/scripts/poll_deploy.py
    backend/.venv/Scripts/python backend/scripts/poll_deploy.py --no-smoke
    backend/.venv/Scripts/python backend/scripts/poll_deploy.py --start-bundle=index-foo.js

The --start-bundle flag lets the caller pin the pre-deploy hash so we
don't false-positive on a no-op invocation. If omitted, the script
captures the current hash on first probe and waits for it to change.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request

DEFAULT_TARGET = "https://www.liquiddemocracy.us"
PROBE_INTERVAL_SECONDS = 20
DEFAULT_TIMEOUT_SECONDS = 720  # 12 min — covers slow Railway builds + warmup


def fetch_bundle_hash(target: str) -> str | None:
    try:
        html = urllib.request.urlopen(target + "/", timeout=10).read().decode()
    except Exception as exc:  # noqa: BLE001
        return f"err:{exc.__class__.__name__}"
    match = re.search(r"index-[A-Za-z0-9_-]+\.js", html)
    return match.group(0) if match else None


def fetch_health(target: str) -> bool:
    try:
        with urllib.request.urlopen(target + "/api/health", timeout=10) as response:
            return response.status == 200
    except Exception:  # noqa: BLE001
        return False


def run_smoke(target: str) -> int:
    """Run tests/smoke/ against the live target. Returns pytest exit code."""
    print(f"\n=== Running smoke suite against {target} ===", flush=True)
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "tests/smoke/",
            "-v",
            f"--target={target}",
        ],
        check=False,
    )
    return completed.returncode


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--target",
        default=DEFAULT_TARGET,
        help=f"Base URL to poll (default: {DEFAULT_TARGET})",
    )
    parser.add_argument(
        "--start-bundle",
        default=None,
        help="Pre-deploy bundle hash. If omitted, captured from first probe.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=DEFAULT_TIMEOUT_SECONDS,
        help=f"Max seconds to wait (default: {DEFAULT_TIMEOUT_SECONDS})",
    )
    parser.add_argument(
        "--no-smoke",
        action="store_true",
        help="Skip running tests/smoke/ after the deploy lands.",
    )
    args = parser.parse_args()

    target = args.target.rstrip("/")
    deadline = time.time() + args.timeout
    start_bundle = args.start_bundle
    start = time.time()

    while time.time() < deadline:
        bundle = fetch_bundle_hash(target)
        backend_ok = fetch_health(target)
        elapsed = int(time.time() - start)
        print(f"[{elapsed}s] bundle={bundle} backend_ok={backend_ok}", flush=True)

        # Capture start-bundle on first probe if caller didn't pin it.
        if start_bundle is None and bundle and not bundle.startswith("err"):
            start_bundle = bundle
            print(f"  pinned start_bundle={start_bundle}", flush=True)
            time.sleep(PROBE_INTERVAL_SECONDS)
            continue

        bundle_changed = bundle and bundle != start_bundle and not bundle.startswith("err")
        if bundle_changed and backend_ok:
            print(f"DONE — new bundle {bundle}", flush=True)
            if args.no_smoke:
                print("  --no-smoke set; skipping smoke suite.", flush=True)
                return 0
            smoke_rc = run_smoke(target)
            if smoke_rc != 0:
                print(f"\n*** SMOKE FAILED (exit code {smoke_rc}) ***", flush=True)
                return smoke_rc
            print("\nSmoke PASS.", flush=True)
            return 0

        time.sleep(PROBE_INTERVAL_SECONDS)

    print(f"TIMEOUT after {args.timeout}s — bundle did not flip or backend not up.", flush=True)
    return 1


if __name__ == "__main__":
    sys.exit(main())
