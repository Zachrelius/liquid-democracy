"""polis_seed_generator.py — Phase 82 C1 AI-assisted pol.is seed-statement drafts.

Drafts a set of pol.is seed statements (single, clear, agree/disagree-able
opinions spanning the genuine spectrum of views) from a Polis's discussion
topic + description, an optional freeform steer, and an optional org
description. The output is an editable list the admin reviews, then downloads
as a pol.is-import CSV on the client — nothing is persisted (consistent with
Phase 81 dropping seed storage from the UI).

Mirrors ``smart_import.py`` exactly: ``is_configured()`` gates on
``ANTHROPIC_API_KEY``; ``_call_anthropic`` is the isolated, monkeypatchable
POST; ``generate_statements`` returns ``(statements, warning)`` and degrades to
``([], warning)`` on any failure — never raises, never 500s.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Optional

import httpx

log = logging.getLogger(__name__)

_ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
_DEFAULT_MODEL = "claude-sonnet-4-6"
_LLM_TIMEOUT_SECONDS = 60.0

# Defensive caps (route also enforces).
MAX_INPUT_CHARS = 2000          # per topic/description/steer field
MAX_STATEMENTS = 30             # hard cap on returned statements

_SYSTEM_PROMPT = """\
You draft seed statements for a pol.is conversation. pol.is is a tool where
participants vote agree / disagree / pass on each statement, and the votes are
clustered to reveal where a group's opinions converge and diverge. The quality
of that clustering depends entirely on the seed statements.

Write statements that follow these rules:
- Each statement is a SINGLE, clear, standalone assertion — one idea. Never
  compound ("X and Y"), never a list, never multi-sentence.
- Each is an OPINION a reasonable person could agree OR disagree with. Never a
  question. Never a neutral fact. Never a procedural note.
- The SET must span the genuine spectrum of views on the topic, INCLUDING
  minority, contrarian, and uncomfortable positions. Deliberately include
  positions the organization's own leadership might NOT hold — clustering is
  only useful when real disagreement is represented.
- Neutral, fair phrasing. Not loaded, not strawmanned. Someone who would vote
  "disagree" should still feel the statement is a fair version of a view a real
  person holds.
- Concise — roughly one sentence each.
- No duplicates or near-duplicates; each statement covers a distinct facet.
- Aim for 12-15 statements.

Respond with ONLY a JSON array of strings — no preamble, no markdown fences:
["statement one", "statement two", ...]
"""


def is_configured() -> bool:
    """True iff an Anthropic API key is available."""
    return bool(os.getenv("ANTHROPIC_API_KEY"))


def _model() -> str:
    return os.getenv("SMART_IMPORT_MODEL") or _DEFAULT_MODEL


def build_user_message(
    *, topic: str, description: str, steer: str, org_description: str,
) -> str:
    """Compose the focused generation prompt. Omits any empty section."""
    lines: list[str] = []
    if topic and topic.strip():
        lines.append(f"Discussion topic: {topic.strip()}")
    if description and description.strip():
        lines.append(f"Description: {description.strip()}")
    if steer and steer.strip():
        lines.append(f"Additional steer from the organizer: {steer.strip()}")
    if org_description and org_description.strip():
        lines.append(
            "This conversation is run by an organization that describes itself "
            f"as: {org_description.strip()}"
        )
    lines.append(
        "\nDraft pol.is seed statements for this conversation following the "
        "rules above."
    )
    return "\n".join(lines)


def _call_anthropic(*, system: str, user: str, api_key: str, model: str) -> str:
    """POST to the Anthropic Messages API; return concatenated text content.

    Isolated so tests can monkeypatch without a real network call. Raises on
    transport / HTTP error (the caller degrades gracefully)."""
    resp = httpx.post(
        _ANTHROPIC_URL,
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": model,
            "max_tokens": 2048,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        },
        timeout=_LLM_TIMEOUT_SECONDS,
    )
    resp.raise_for_status()
    data = resp.json()
    parts = []
    for block in data.get("content", []):
        if isinstance(block, dict) and block.get("type") == "text":
            parts.append(block.get("text", ""))
    return "".join(parts)


def parse_llm_array(text: str) -> Optional[list]:
    """Extract a JSON array from the model's text. Returns the list, or None
    when nothing parseable is found (caller emits the degradation warning)."""
    if not text:
        return None
    stripped = text.strip()
    candidates = [stripped]
    start = stripped.find("[")
    end = stripped.rfind("]")
    if start != -1 and end != -1 and end > start:
        candidates.append(stripped[start: end + 1])
    for cand in candidates:
        try:
            parsed = json.loads(cand)
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(parsed, list):
            return parsed
    return None


def _clean_statements(items: list) -> list[str]:
    """Trim, drop empties, de-dupe (exact, order-preserving), cap."""
    out: list[str] = []
    seen: set[str] = set()
    for raw in items:
        if not isinstance(raw, str):
            continue
        s = raw.strip()
        if not s or s in seen:
            continue
        seen.add(s)
        out.append(s)
        if len(out) >= MAX_STATEMENTS:
            break
    return out


def generate_statements(
    *, topic: str = "", description: str = "", steer: str = "",
    org_description: str = "",
) -> tuple[list[str], Optional[str]]:
    """Call the LLM and return (statements, warning).

    Degrades to ``([], warning)`` on empty input, transport failure, or
    unparseable output — never raises."""
    # Don't call the API on empty input.
    if not any(s and s.strip() for s in (topic, description, steer)):
        return [], (
            "Enter a discussion topic or description first so the generator "
            "has something to work from."
        )

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        # Caller 503s before reaching here; defensive.
        return [], "AI seed generation is not configured."

    user = build_user_message(
        topic=topic, description=description, steer=steer,
        org_description=org_description,
    )
    try:
        text = _call_anthropic(
            system=_SYSTEM_PROMPT, user=user, api_key=api_key, model=_model(),
        )
    except Exception as exc:  # noqa: BLE001 — degrade on any LLM/transport error
        log.warning("polis_seed_generator: LLM call failed: %s", exc)
        return [], (
            "The AI service could not be reached or timed out. Try again, or "
            "add statements manually below."
        )

    items = parse_llm_array(text)
    if items is None:
        return [], (
            "The AI response could not be parsed. Try again, or add statements "
            "manually below."
        )
    statements = _clean_statements(items)
    if not statements:
        return [], (
            "The AI returned no usable statements. Try a more specific topic or "
            "steer, or add statements manually below."
        )
    return statements, None
