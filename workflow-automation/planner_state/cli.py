"""Command-line entry point (WA1 small CLI).

Three subcommands cover the things a human (or a Bash script) might
want to do directly with the state dir:

  python -m planner_state.cli bootstrap <state_dir>
      Print the bootstrap Markdown to stdout.

  python -m planner_state.cli passdown <state_dir>
      Print the passdown Markdown to stdout.

  python -m planner_state.cli cold-start <state_dir> [--out FILE]
      Run the WA1 B5 cold-start reconstruction validation: render the
      bootstrap, invoke `claude -p --dangerously-skip-permissions`
      against it (ANTHROPIC_API_KEY unset), and print the cold
      session's restatement to stdout. With ``--out``, also write a
      JSON record (transcript + harness metadata) for the closeout.

The CLI is intentionally tiny — the package's main API is the Python
imports. CLI is here for "I want to dump a passdown" + the validation.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from textwrap import dedent

from .bootstrap import render_bootstrap
from .checkpoint import StateStore
from .passdown import render_passdown


CLAUDE_TIMEOUT_S = 180


def _claude_env() -> dict[str, str]:
    """Subprocess env with ANTHROPIC_API_KEY explicitly removed.

    Mirrors ``backend/scripts/workflow_resume_spike.py::_claude_env``
    (Phase 42). A stray ANTHROPIC_API_KEY would silently switch the
    subprocess to API billing AND a different auth path than the
    wrapper will use, invalidating the WA1 B5 cold-start validation.
    """
    env = os.environ.copy()
    env.pop("ANTHROPIC_API_KEY", None)
    return env


COLD_START_INSTRUCTION = dedent(
    """\
    You are a FRESH planner session being bootstrapped. You have NEVER
    seen this project before this moment. Read the bootstrap document
    that follows and produce a SHORT (4-8 bullets) restatement of:

    1. What project this is.
    2. The current platform state (one bullet).
    3. What pass (if any) is currently in flight, and its status.
    4. What's pending and what's blocked.
    5. The 2-3 most consequential locked decisions.

    Do NOT propose actions. Do NOT modify any files. Do NOT touch the
    repository or its state. This is a read-only validation: your
    output is the test result. Be concise.

    ---

    """
)


def _emit(text: str) -> None:
    """Write ``text`` to stdout as UTF-8 regardless of the host's
    default console encoding. Needed on Windows where Python defaults
    stdout to cp1252, which fails on unicode characters in rendered
    bootstrap docs (e.g. en-dashes, arrows in the working-context digest).
    """
    try:
        sys.stdout.buffer.write(text.encode("utf-8"))
    except AttributeError:
        # Some test environments wrap stdout — fall back to plain write.
        sys.stdout.write(text)


def _bootstrap_cmd(args: argparse.Namespace) -> int:
    store = StateStore(args.state_dir)
    state = store.load()
    _emit(render_bootstrap(state, state_dir=args.state_dir))
    return 0


def _passdown_cmd(args: argparse.Namespace) -> int:
    store = StateStore(args.state_dir)
    state = store.load()
    _emit(render_passdown(state, max_decisions=args.max_decisions))
    return 0


def _cold_start_cmd(args: argparse.Namespace) -> int:
    store = StateStore(args.state_dir)
    state = store.load()
    bootstrap_md = render_bootstrap(state, state_dir=args.state_dir)
    prompt = COLD_START_INSTRUCTION + bootstrap_md

    started_at = time.time()
    cmd = [
        "claude", "-p", "--dangerously-skip-permissions",
        "--output-format", "json",
        "--", prompt,
    ]
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(Path(args.state_dir).resolve()),
            env=_claude_env(),
            capture_output=True,
            text=True,
            timeout=args.timeout_s,
        )
    except subprocess.TimeoutExpired:
        sys.stderr.write(
            f"cold-start validation timed out after {args.timeout_s}s\n"
        )
        return 2
    elapsed_s = round(time.time() - started_at, 2)

    try:
        payload = json.loads(proc.stdout) if proc.stdout else {}
    except json.JSONDecodeError:
        payload = {"_parse_error": True, "_stdout_head": proc.stdout[:500]}

    result_text = ""
    if isinstance(payload, dict):
        result_text = payload.get("result", "") or payload.get("text", "") or ""

    record = {
        "elapsed_s": elapsed_s,
        "exit_code": proc.returncode,
        "stderr_tail": proc.stderr[-500:] if proc.stderr else "",
        "payload": payload,
        "result_text": result_text,
    }

    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(record, indent=2), encoding="utf-8")

    _emit(result_text)
    if not result_text.endswith("\n"):
        _emit("\n")
    return 0 if proc.returncode == 0 else 1


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="planner_state.cli",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("bootstrap", help="Render bootstrap Markdown")
    b.add_argument("state_dir", type=str)
    b.set_defaults(func=_bootstrap_cmd)

    d = sub.add_parser("passdown", help="Render passdown Markdown")
    d.add_argument("state_dir", type=str)
    d.add_argument("--max-decisions", type=int, default=6)
    d.set_defaults(func=_passdown_cmd)

    c = sub.add_parser(
        "cold-start",
        help="Run claude -p cold-start reconstruction validation",
    )
    c.add_argument("state_dir", type=str)
    c.add_argument(
        "--out",
        type=str,
        default=None,
        help="Write the full transcript + metadata JSON to this path",
    )
    c.add_argument(
        "--timeout-s",
        type=int,
        default=CLAUDE_TIMEOUT_S,
        help=f"Subprocess timeout (default {CLAUDE_TIMEOUT_S}s)",
    )
    c.set_defaults(func=_cold_start_cmd)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
