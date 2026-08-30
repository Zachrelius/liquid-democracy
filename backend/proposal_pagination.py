"""Shared proposal ordering and opaque keyset cursor primitives.

Phase 103 introduced the ordering contract for compact proposal feeds. Phase
104 reuses the exact same expressions for management pagination and keeps the
legacy arrays on a stable ordering. Keeping these primitives neutral prevents
the member and management feeds from growing subtly different cursor rules.
"""
from __future__ import annotations

import base64
import binascii
import json
from datetime import datetime
from urllib.parse import urlencode

from fastapi import HTTPException
from sqlalchemy import and_, case, func, or_

import models


CURSOR_VERSION = 1
FUTURE = datetime(9999, 12, 31, 23, 59, 59)

TERMINAL_STATUSES = frozenset({
    "passed", "failed", "withdrawn", "unresolved", "expired_unsigned",
})


def ordering_expressions():
    p = models.Proposal
    group = case(
        (p.status == "voting", 0),
        (p.status == "deliberation", 1),
        (p.status.in_(tuple(TERMINAL_STATUSES)), 2),
        else_=3,
    )
    asc_key = case(
        (p.status == "voting", func.coalesce(p.voting_end, FUTURE)),
        else_=FUTURE,
    )
    desc_key = case(
        (p.status == "deliberation", p.created_at),
        (
            p.status.in_(tuple(TERMINAL_STATUSES)),
            func.coalesce(p.updated_at, p.created_at),
        ),
        else_=p.created_at,
    )
    return group, asc_key, desc_key


def proposal_row_key(
    proposal: models.Proposal,
) -> tuple[int, datetime, datetime, datetime, str]:
    status = proposal.status
    group = (
        0 if status == "voting"
        else 1 if status == "deliberation"
        else 2 if status in TERMINAL_STATUSES
        else 3
    )
    asc_key = (proposal.voting_end or FUTURE) if group == 0 else FUTURE
    desc_key = (
        proposal.created_at if group in {1, 3}
        else (proposal.updated_at or proposal.created_at) if group == 2
        else proposal.created_at
    )
    return group, asc_key, desc_key, proposal.created_at, proposal.id


def encode_proposal_cursor(proposal: models.Proposal) -> str:
    group, asc_key, desc_key, created_at, proposal_id = proposal_row_key(proposal)
    raw = json.dumps({
        "v": CURSOR_VERSION,
        "g": group,
        "a": asc_key.isoformat(),
        "d": desc_key.isoformat(),
        "c": created_at.isoformat(),
        "i": proposal_id,
    }, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_proposal_cursor(
    value: str,
    *,
    error_code: str = "invalid_feed_cursor",
    error_message: str = "Malformed proposal feed cursor",
) -> tuple[int, datetime, datetime, datetime, str]:
    try:
        raw = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
        data = json.loads(raw)
        if data.get("v") != CURSOR_VERSION or not isinstance(data.get("i"), str):
            raise ValueError
        group = int(data["g"])
        if group not in range(4):
            raise ValueError
        return (
            group,
            datetime.fromisoformat(data["a"]),
            datetime.fromisoformat(data["d"]),
            datetime.fromisoformat(data["c"]),
            data["i"],
        )
    except (
        ValueError,
        TypeError,
        KeyError,
        json.JSONDecodeError,
        binascii.Error,
        UnicodeDecodeError,
    ):
        raise HTTPException(
            status_code=422,
            detail={"code": error_code, "message": error_message},
        ) from None


def proposal_after_cursor(
    cursor: tuple[int, datetime, datetime, datetime, str],
):
    group, asc_key, desc_key, created_at, proposal_id = cursor
    g, a, d = ordering_expressions()
    p = models.Proposal
    return or_(
        g > group,
        and_(g == group, a > asc_key),
        and_(g == group, a == asc_key, d < desc_key),
        and_(g == group, a == asc_key, d == desc_key, p.created_at < created_at),
        and_(
            g == group,
            a == asc_key,
            d == desc_key,
            p.created_at == created_at,
            p.id > proposal_id,
        ),
    )


def proposal_ordering():
    group, asc_key, desc_key = ordering_expressions()
    return (
        group.asc(),
        asc_key.asc(),
        desc_key.desc(),
        models.Proposal.created_at.desc(),
        models.Proposal.id.asc(),
    )


def encode_created_cursor(proposal: models.Proposal) -> str:
    raw = json.dumps({
        "v": CURSOR_VERSION,
        "o": "created_desc",
        "c": proposal.created_at.isoformat(),
        "i": proposal.id,
    }, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_created_cursor(
    value: str,
    *,
    error_code: str,
    error_message: str,
) -> tuple[datetime, str]:
    try:
        raw = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
        data = json.loads(raw)
        if (
            data.get("v") != CURSOR_VERSION
            or data.get("o") != "created_desc"
            or not isinstance(data.get("i"), str)
        ):
            raise ValueError
        return datetime.fromisoformat(data["c"]), data["i"]
    except (
        ValueError,
        TypeError,
        KeyError,
        json.JSONDecodeError,
        binascii.Error,
        UnicodeDecodeError,
    ):
        raise HTTPException(
            status_code=422,
            detail={"code": error_code, "message": error_message},
        ) from None


def created_after_cursor(cursor: tuple[datetime, str]):
    created_at, proposal_id = cursor
    return or_(
        models.Proposal.created_at < created_at,
        and_(
            models.Proposal.created_at == created_at,
            models.Proposal.id > proposal_id,
        ),
    )


def set_legacy_pagination_headers(
    response,
    request,
    *,
    limit: int,
    offset: int,
    has_more: bool,
) -> None:
    """Attach compatibility pagination and deprecation headers."""
    response.headers["Deprecation"] = "true"
    response.headers["X-Has-More"] = "true" if has_more else "false"
    if not has_more:
        return
    next_offset = offset + limit
    response.headers["X-Next-Offset"] = str(next_offset)
    # Emit an origin-relative target.  Reusing ``request.url`` would trust
    # the proxy-supplied authority and can expose an internal Railway host in
    # a public response. Preserve every filter (including repeated values),
    # replacing only the pagination controls owned by this helper.
    query_items = [
        (key, value)
        for key, value in request.query_params.multi_items()
        if key not in {"limit", "offset"}
    ]
    query_items.extend((("limit", str(limit)), ("offset", str(next_offset))))
    relative_target = f"{request.url.path}?{urlencode(query_items)}"
    response.headers["Link"] = f'<{relative_target}>; rel="next"'
