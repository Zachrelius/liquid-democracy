"""smart_import.py — Phase 75b AI-assisted agenda → proposal extraction.

Converts unstructured meeting-agenda content (pasted text or a PDF) into the
structured ``ProposalCreate[]`` shape the Phase 72 import pipeline already
validates and renders. The semantic parsing (identify items, assign topics)
uses the Anthropic Messages API; PDF text extraction is deterministic
(pdfplumber), kept separate so the PDF step is fast and debuggable.

Design (spec §75b):
- LLM = Anthropic (Sonnet) via httpx — no new SDK dependency. Model is
  ``SMART_IMPORT_MODEL`` (default ``claude-sonnet-4-6``). ``ANTHROPIC_API_KEY``
  is required for the endpoint to function (the route 503s when unset).
- Graceful degradation: a malformed/empty/timeout LLM response yields an empty
  item list + a warning, never a 500 — the aide can fall back to manual import.
- The route reuses ``_preview_one_proposal`` for validation; this module only
  produces the ProposalCreate-shaped drafts + per-item ``ai_reasoning``.
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
_MAX_PROMPT_DOC_CHARS = 80_000  # truncate the document to fit context

# Caps (spec §D10).
MAX_TEXT_BYTES = 100 * 1024          # 100 KB pasted text
MAX_PDF_BYTES = 5 * 1024 * 1024      # 5 MB PDF
MAX_PROPOSALS = 50                   # matches Phase 72's array cap

_SYSTEM_PROMPT = """\
You are an assistant that parses meeting agendas and similar documents into
structured proposal items for a democratic decision-making platform.

Given a document and a list of available topics for the organization, extract
each substantive agenda item and produce structured JSON output.

Rules:
- SKIP procedural items: roll call, approval of minutes, adjournment,
  moment of silence, public comment period, consent agenda headers, etc.
- Extract a clear, concise title for each item (under 200 chars).
- Write a descriptive body paragraph (2-4 sentences) explaining what the
  item is about, suitable for voters who haven't read the full document.
  Include relevant context (dollar amounts, locations, affected parties)
  from the source text.
- Assign 1-3 topics from the available list. Use relevance scores:
  1.0 = primary topic, 0.4-0.8 = secondary/related. Only use topics
  from the provided list - do not invent new ones.
- Briefly explain your topic assignment reasoning.
- If no substantive items can be extracted, return an empty array.

Respond with ONLY a JSON array, no other text:
[
  {
    "title": "...",
    "body": "...",
    "topics": [
      {"topic_name": "...", "relevance": 0.8}
    ],
    "reasoning": "..."
  }
]
"""


def is_configured() -> bool:
    """True iff an Anthropic API key is available."""
    return bool(os.getenv("ANTHROPIC_API_KEY"))


def _model() -> str:
    return os.getenv("SMART_IMPORT_MODEL") or _DEFAULT_MODEL


def extract_pdf_text(raw_bytes: bytes) -> str:
    """Deterministic PDF → text via pdfplumber. Raises ValueError when the PDF
    can't be opened or yields no text (corrupt / encrypted / image-only)."""
    import io

    try:
        import pdfplumber
    except ImportError as exc:  # pragma: no cover - dependency missing
        raise ValueError("PDF support is not installed on the server.") from exc

    try:
        parts: list[str] = []
        with pdfplumber.open(io.BytesIO(raw_bytes)) as pdf:
            for page in pdf.pages:
                txt = page.extract_text() or ""
                if txt:
                    parts.append(txt)
    except Exception as exc:  # noqa: BLE001 - any pdfplumber failure is a bad file
        raise ValueError(
            "Could not extract text from the uploaded PDF. The file may be "
            "corrupt, encrypted, or contain only scanned images."
        ) from exc

    text = "\n\n".join(parts).strip()
    if not text:
        raise ValueError(
            "Could not extract text from the uploaded PDF. The file may be "
            "corrupt, encrypted, or contain only scanned images."
        )
    return text


def build_user_message(
    *, topics: list[dict], document_text: str, instructions: Optional[str],
) -> str:
    """Compose the user message: org topic taxonomy + the document (truncated)
    + optional importer instructions."""
    lines = ["## Available topics for this organization:"]
    if topics:
        for t in topics:
            name = t.get("name") or t.get("topic_name") or ""
            purpose = (t.get("purpose") or "").strip()
            lines.append(f"- {name}: {purpose}" if purpose else f"- {name}")
    else:
        lines.append("(no topics defined)")

    doc = document_text[:_MAX_PROMPT_DOC_CHARS]
    lines.append("\n## Document to parse:")
    lines.append(doc)

    if instructions and instructions.strip():
        lines.append("\n## Additional instructions from the importer:")
        lines.append(instructions.strip())

    return "\n".join(lines)


def _call_anthropic(*, system: str, user: str, api_key: str, model: str) -> str:
    """POST to the Anthropic Messages API; return the concatenated text content.

    Isolated so tests can monkeypatch this without a real network call. Raises
    on transport / HTTP error (the caller degrades gracefully)."""
    resp = httpx.post(
        _ANTHROPIC_URL,
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": model,
            "max_tokens": 4096,
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
    # Fast path: the whole thing is the array.
    stripped = text.strip()
    candidates = [stripped]
    # Fallback: slice from first '[' to last ']'.
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


def extracted_items_to_drafts(
    items: list, *, meeting_date: Optional[str],
) -> list[dict]:
    """Turn the LLM's extracted items into ProposalCreate-shaped dicts +
    stashed ``ai_reasoning``. Capped at MAX_PROPOSALS."""
    drafts: list[dict] = []
    for raw in items[:MAX_PROPOSALS]:
        if not isinstance(raw, dict):
            continue
        topics = []
        for t in raw.get("topics") or []:
            if isinstance(t, dict) and t.get("topic_name"):
                topics.append({
                    "topic_name": t["topic_name"],
                    "relevance": t.get("relevance", 1.0),
                })
        draft = {
            "title": (raw.get("title") or "").strip(),
            "body": (raw.get("body") or "").strip(),
            "voting_method": "binary",
            "topics": topics,
        }
        if meeting_date:
            draft["voting_end_date"] = meeting_date
        drafts.append({
            "draft": draft,
            "ai_reasoning": (raw.get("reasoning") or "").strip(),
        })
    return drafts


def generate_drafts(
    *,
    document_text: str,
    topics: list[dict],
    meeting_date: Optional[str],
    instructions: Optional[str],
) -> tuple[list[dict], Optional[str]]:
    """Call the LLM and return (drafts, warning).

    ``drafts`` is a list of ``{draft, ai_reasoning}``. ``warning`` is non-null
    when the LLM produced nothing usable (the caller returns 200 + empty items
    + this warning — graceful degradation, never a 500)."""
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        # Caller should 503 before reaching here; defensive.
        return [], "Smart import is not configured."

    system = _SYSTEM_PROMPT
    user = build_user_message(
        topics=topics, document_text=document_text, instructions=instructions,
    )
    try:
        text = _call_anthropic(system=system, user=user, api_key=api_key, model=_model())
    except Exception as exc:  # noqa: BLE001 - degrade on any LLM/transport error
        log.warning("smart_import: LLM call failed: %s", exc)
        return [], (
            "The AI service could not be reached or timed out. Try again, or "
            "use the structured JSON import."
        )

    items = parse_llm_array(text)
    if items is None:
        return [], (
            "The AI could not parse the document into structured proposals. "
            "Try pasting the text in a different format, or use the structured "
            "JSON import."
        )
    if not items:
        return [], (
            "No agenda items could be extracted from the provided content."
        )
    return extracted_items_to_drafts(items, meeting_date=meeting_date), None
