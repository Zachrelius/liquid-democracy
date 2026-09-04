"""Catch literal Didit secret assignments in tracked source, without printing values.

This focused guard is not a general secret scanner or a Git history scan. It
recognizes env/config assignments, JSON properties and Markdown table rows for
the two named Didit secrets. Computed, encoded, split or differently named
credentials require another scanner/review. Run from any repository directory.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import re
import subprocess
import sys


_ASSIGNMENT = re.compile(
    r"\bDIDIT_(?:API_KEY|WEBHOOK_SECRET)\b[\"'`]?\s*(?:=|:|\|)\s*"
    r"[\"'`]?([A-Za-z0-9_./+=:-]{12,})(?=[\s\"'`,;}|]|$)",
    re.IGNORECASE,
)
_PLACEHOLDERS = {
    "your-api-key-here", "your-webhook-secret-here", "your_didit_api_key",
    "your_didit_webhook_secret", "replace-with-api-key", "replace-with-secret",
    "redacted-pending-rotation", "set-in-environment",
}


def finding_lines(content: str) -> list[int]:
    """Return distinct 1-based lines, never credential contents."""
    return sorted({
        content.count("\n", 0, match.start()) + 1
        for match in _ASSIGNMENT.finditer(content)
        if match.group(1).lower() not in _PLACEHOLDERS
    })


def scan_paths(root: Path, paths: list[str]) -> int:
    found = False
    for relative in paths:
        path = root / relative
        if path.is_symlink() or not path.is_file():
            continue
        try:
            raw = path.read_bytes()
        except OSError:
            print(f"{relative}: unreadable tracked file", file=sys.stderr)
            return 2
        if b"\0" in raw:
            continue  # Binary assets are outside this text-assignment guard.
        for line in finding_lines(raw.decode("utf-8", errors="replace")):
            print(f"{relative}:{line}: literal Didit secret assignment (value withheld)")
            found = True
    if found:
        return 1
    print("Didit assignment check passed (tracked text only; not a general secret scan).")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, help="Repository directory (default: Git root)")
    args = parser.parse_args()
    try:
        root = args.root or Path(subprocess.check_output(
            ["git", "rev-parse", "--show-toplevel"], text=True, stderr=subprocess.PIPE,
        ).strip())
        tracked = subprocess.check_output(
            ["git", "-C", str(root), "ls-files", "-z"], stderr=subprocess.PIPE,
        ).decode("utf-8").split("\0")
    except (OSError, subprocess.CalledProcessError, UnicodeError):
        print("Unable to enumerate tracked files; Didit check did not run.", file=sys.stderr)
        return 2
    return scan_paths(root, [name for name in tracked if name])


if __name__ == "__main__":
    sys.exit(main())
