"""Stub responder — drains the IPC inbox and writes echo replies.

Stand-in for the future WA4 daemon's chat-input consumer. The
dashboard writes a message via ``IPCLayout.write_spec(<id>, body)``;
this process polls the inbox for ``.ready`` markers, reads the
spec body, claims the spec, and writes a closeout ack to the
outbox so the dashboard sees a reply land.

Run alongside the dashboard server for WA3 B4 round-trip
verification::

    python -m dashboard.stub_responder --ipc-root /path/to/ipc

It's intentionally dumb: no LLM call, no smart reply. Just proves
the IPC contract round-trip works end-to-end before WA4 builds
the real consumer.

Loops every 1.0s by default; ``--once`` exits after one drain
(useful for tests).
"""
from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Sibling planner_state package
_WA_DIR = Path(__file__).resolve().parents[1]
if str(_WA_DIR) not in sys.path:
    sys.path.insert(0, str(_WA_DIR))

from planner_state import IPCLayout  # noqa: E402


POLL_INTERVAL_S = 1.0


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _build_reply(spec_id: str, spec_body: str) -> str:
    return (
        "# Stub-responder ack\n\n"
        f"Spec id: `{spec_id}`\n"
        f"Acked at: {_now()}\n\n"
        "This is the WA3 stub responder standing in for the future WA4 "
        "daemon. The dashboard's chat round-trip is verified by the "
        "presence of this closeout in the outbox.\n\n"
        "---\n\n"
        "## Original message\n\n"
        f"{spec_body}\n"
    )


def drain_once(ipc: IPCLayout) -> int:
    """Drain inbox once. Returns the number of specs handled."""
    n = 0
    for spec_id in ipc.list_ready_specs():
        try:
            body = ipc.read_spec(spec_id)
        except OSError:
            ipc.claim_spec(spec_id)  # remove marker so we don't loop
            continue
        ipc.write_closeout(spec_id, _build_reply(spec_id, body))
        ipc.claim_spec(spec_id)
        n += 1
    return n


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--ipc-root", type=str, required=True)
    parser.add_argument("--once", action="store_true",
                        help="Drain inbox once and exit (test mode).")
    parser.add_argument("--interval-s", type=float, default=POLL_INTERVAL_S)
    parser.add_argument("--quiet", action="store_true",
                        help="Suppress per-drain log lines.")
    args = parser.parse_args()

    ipc = IPCLayout(Path(args.ipc_root))
    ipc.ensure()
    if not args.quiet:
        print(f"[stub_responder] watching {args.ipc_root}/inbox/", flush=True)

    if args.once:
        n = drain_once(ipc)
        if not args.quiet:
            print(f"[stub_responder] drained {n} spec(s); exiting", flush=True)
        return 0

    while True:
        n = drain_once(ipc)
        if n and not args.quiet:
            print(f"[stub_responder] acked {n} spec(s)", flush=True)
        time.sleep(args.interval_s)


if __name__ == "__main__":
    sys.exit(main())
