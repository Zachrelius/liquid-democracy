"""Pytest setup for the dashboard tests.

The dashboard imports planner_state, which is at
``workflow-automation/planner_state``; add that package root to
sys.path so tests can be run from either the workflow-automation/
dir or the repo root.
"""
from __future__ import annotations

import sys
from pathlib import Path

_WA_DIR = Path(__file__).resolve().parents[2]  # workflow-automation/
if str(_WA_DIR) not in sys.path:
    sys.path.insert(0, str(_WA_DIR))
