"""Shared pytest setup for the workflow-automation track.

Pytest is run from the ``workflow-automation/`` directory (or with
``--rootdir`` pointing there); this conftest adds the package root to
``sys.path`` so the ``planner_state`` package is importable without
needing an installation step.

We deliberately do NOT pull in any of the website backend's conftest
fixtures. This track is self-contained.
"""
from __future__ import annotations

import sys
from pathlib import Path

_PKG_ROOT = Path(__file__).resolve().parent.parent
if str(_PKG_ROOT) not in sys.path:
    sys.path.insert(0, str(_PKG_ROOT))
