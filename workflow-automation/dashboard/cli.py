"""CLI entry: ``python -m dashboard.cli serve --port ... --state-dir ... --ipc-root ...``

Runs the FastAPI server via uvicorn, bound to 127.0.0.1 only.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import uvicorn

from dashboard import HOST, PORT


def _serve_cmd(args: argparse.Namespace) -> int:
    # Import lazily so --help doesn't pull in fastapi etc.
    from dashboard.server import init_app

    state_dir = Path(args.state_dir).expanduser().resolve()
    ipc_root = Path(args.ipc_root).expanduser().resolve()
    state_dir.mkdir(parents=True, exist_ok=True)
    ipc_root.mkdir(parents=True, exist_ok=True)

    app = init_app(state_dir, ipc_root)
    print(f"[dashboard] serving on http://{args.host}:{args.port}/")
    print(f"[dashboard] state_dir={state_dir}")
    print(f"[dashboard] ipc_root={ipc_root}")
    print("[dashboard] hook handler endpoint: POST /api/hook")
    print(f"[dashboard] hook command: python {Path(__file__).parent / 'hook_handler.py'}")
    print(f"[dashboard] (set env WA3_DASHBOARD_URL=http://{args.host}:{args.port} if non-default)")
    uvicorn.run(app, host=args.host, port=args.port, log_level=args.log_level)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="dashboard.cli", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("serve", help="Run the dashboard server.")
    s.add_argument("--host", default=HOST)
    s.add_argument("--port", type=int, default=PORT)
    s.add_argument("--state-dir", required=True,
                   help="WA1 planner state directory (where planner_state.json lives).")
    s.add_argument("--ipc-root", required=True,
                   help="IPC root with inbox/outbox/signals/workdir (per WA1 contract v1).")
    s.add_argument("--log-level", default="info")
    s.set_defaults(func=_serve_cmd)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
