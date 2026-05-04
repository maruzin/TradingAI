"""HTTP middleware — request-ID propagation and per-request structured logs.

Phase-2 audit (SEC-7): no correlation ID across web → api → worker meant
that diagnosing a single user-visible failure required cross-referencing
timestamps across separate log streams. This middleware:

  1. Reads ``X-Request-ID`` from the incoming request, or mints a fresh
     UUID4 if absent.
  2. Binds the ID into structlog's contextvars so every ``log.info`` /
     ``log.warning`` inside the request handler emits it as a structured
     field automatically.
  3. Echoes the ID back as ``X-Request-ID`` on the response so the
     frontend (and Sentry) can attach the same value to error reports.
  4. Logs a single ``http.request`` entry per request with method, path,
     status, latency_ms, and user_id (when an authed user binds it via
     ``deps.get_current_user``).
"""
from __future__ import annotations

import time
import uuid

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

from .logging_setup import get_logger

_HEADER = "x-request-id"
_log = get_logger("http")


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Bind a request ID into structlog context + emit a per-request log."""

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        request_id = request.headers.get(_HEADER) or uuid.uuid4().hex
        # Stash on request.state so downstream handlers can read it without
        # re-parsing the header.
        request.state.request_id = request_id

        # structlog contextvars: every log call inside this request will
        # automatically include request_id and route fields.
        structlog.contextvars.bind_contextvars(
            request_id=request_id,
            route=f"{request.method} {request.url.path}",
        )

        started = time.monotonic()
        status = 500
        try:
            response: Response = await call_next(request)
            status = response.status_code
            return response
        finally:
            latency_ms = int((time.monotonic() - started) * 1000)
            _log.info(
                "http.request",
                method=request.method,
                path=request.url.path,
                status=status,
                latency_ms=latency_ms,
            )
            # Echo the ID back so clients (and Sentry crash reports) can pin it.
            try:
                response.headers[_HEADER] = request_id  # type: ignore[possibly-undefined]
            except Exception:
                pass
            structlog.contextvars.clear_contextvars()
