"""audit_log repository — write-only helper for app-level events.

Database writes (briefs, alerts, theses, ai_calls, exchange_keys, holdings)
auto-log via triggers in migration 011. Use this helper for events that don't
correspond to a row mutation: LLM calls, key decryption, external API calls
that touched user data, admin actions, etc.

We never let an audit-log failure surface to the caller — the audit trail is
best-effort and must not break the user-visible operation.
"""
from __future__ import annotations

import json
from typing import Any

from .. import db
from ..logging_setup import get_logger

log = get_logger("audit")


async def write(
    *,
    user_id: str | None,
    actor: str = "agent",
    action: str,
    target: str | None = None,
    args: dict[str, Any] | None = None,
    result: dict[str, Any] | None = None,
) -> None:
    """Insert one row into audit_log. Swallows all errors.

    `actor` ∈ {"user","system","agent"}; defaults to "agent" since this helper
    is mostly called from AI-initiated code paths.
    """
    try:
        await db.execute(
            """
            insert into audit_log (user_id, actor, action, target, args_summary, result_summary)
            values ($1::uuid, $2, $3, $4, $5::jsonb, $6::jsonb)
            """,
            user_id,
            actor,
            action,
            target,
            json.dumps(_redact(args or {})),
            json.dumps(_redact(result or {})),
        )
    except Exception as e:
        log.warning("audit.write_failed", action=action, error=str(e))


# Field name fragments that should never appear in an audit row even
# truncated. We replace their values with the literal "[redacted]".
_REDACT_KEYS = (
    "key", "secret", "token", "password", "passphrase",
    "api_key", "private", "jwt", "auth", "cookie",
)


def _redact(obj: Any) -> Any:
    """Recursively scrub secret-shaped values out of a dict/list."""
    if isinstance(obj, dict):
        return {
            k: ("[redacted]" if any(t in k.lower() for t in _REDACT_KEYS) else _redact(v))
            for k, v in obj.items()
        }
    if isinstance(obj, list):
        return [_redact(v) for v in obj]
    if isinstance(obj, str) and len(obj) > 500:
        return obj[:500] + "…"
    return obj
