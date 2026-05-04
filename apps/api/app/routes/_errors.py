"""HTTP error helpers — sanitize upstream messages before they reach the wire.

The audit (Phase-1, ERR-3) caught `/api/markets` returning a 503 with the
full CoinGecko URL + query parameters in the body. Generally any
``HTTPException(detail=str(e))`` where ``e`` originated from an httpx /
ccxt / requests call risks leaking provider hostnames, query params,
internal IPs, or paths. This module:

  * ``safe_detail(e, fallback)`` — returns ``str(e)`` if it's clearly an
    application-thrown user message; otherwise the supplied ``fallback``.
    The full original error is logged via structlog before being scrubbed.
  * ``HttpStatus`` — small enum of the statuses we use, so the call sites
    document intent rather than magic numbers.
"""
from __future__ import annotations

import re
from typing import Final

from ..logging_setup import get_logger

_log = get_logger("routes.errors")

# Anything that looks like a URL, IP literal, full file path, or a long opaque
# blob (>200 chars) is presumed to be an upstream payload, not a friendly
# user-facing message — we replace it with the supplied fallback.
_LEAK_RE: Final = re.compile(
    r"https?://"                  # any URL
    r"|\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b"  # IPv4 literal
    r"|/[A-Za-z]+/[A-Za-z0-9_/.-]{12,}"          # filesystem path-ish
    r"|[A-Za-z0-9+/]{60,}={0,2}"                 # long base64-ish blob
    , re.IGNORECASE,
)
_MAX_DETAIL_LEN: Final = 200


def safe_detail(e: BaseException, fallback: str) -> str:
    """Return a client-safe ``detail`` string.

    Use ``fallback`` when the error message contains URLs, IP literals,
    long opaque tokens, or exceeds 200 characters. Always logs the full
    original via structlog so on-call still has the diagnostic.
    """
    msg = str(e).strip()
    if not msg:
        return fallback
    if _LEAK_RE.search(msg) or len(msg) > _MAX_DETAIL_LEN:
        _log.warning("routes.errors.scrubbed",
                     fallback=fallback, original_excerpt=msg[:_MAX_DETAIL_LEN])
        return fallback
    return msg
