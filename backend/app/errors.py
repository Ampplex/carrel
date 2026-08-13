"""Turn SDK failures into honest HTTP responses.

The SDK erases exception types on the way out: a server-side error arrives as
`RuntimeError("RPC Error: {...}")`, so the only thing left to match on is the
message string. That is unpleasant but it is the real interface, and pretending
otherwise would mean showing users "500 Internal Server Error" when the actual
situation is "your monthly quota ran out" or "the model is throttled, try again
in two seconds".

The table below is ordered — first predicate that matches wins.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from fastapi import Request
from fastapi.responses import JSONResponse


@dataclass
class ReeveError(Exception):
    """A classified failure, ready to render."""

    status: int
    code: str
    user_message: str
    detail: str = ""
    retryable: bool = False
    retry_after: int | None = None

    def __str__(self) -> str:  # pragma: no cover - debugging aid
        return f"{self.code}: {self.detail or self.user_message}"


def _has(*needles: str):
    lowered = [n.lower() for n in needles]
    return lambda text: any(n in text for n in lowered)


# (predicate over lowercased message, status, code, user message, retryable, retry_after)
_RULES: list[tuple] = [
    (
        _has("token quota"),
        429,
        "token_quota_exceeded",
        "Reeve's monthly token allowance is used up. Storing photos costs far more "
        "than storing text, so that is usually the cause.",
        False,
        None,
    ),
    (
        _has("quota exceeded", "monthly quota"),
        429,
        "query_quota_exceeded",
        "Reeve's monthly query quota is used up. Asking with evidence costs two "
        "queries instead of one.",
        False,
        None,
    ),
    (
        _has("rate limit", "too many requests", "429"),
        429,
        "rate_limited",
        "Too many requests in a short window. Wait about 30 seconds.",
        True,
        30,
    ),
    (
        _has("throttling", "throttlingexception"),
        503,
        "model_throttled",
        "The language model is throttled right now. This usually clears in a few seconds.",
        True,
        5,
    ),
    (
        _has("401", "unauthorized", "invalid api key"),
        502,
        "reeve_auth",
        "Reeve rejected this server's credentials. Check REEVE_API_KEY in backend/.env.",
        False,
        None,
    ),
    (
        _has("failed to connect", "connection", "sse"),
        503,
        "reeve_unreachable",
        "Cannot reach the Reeve service. Check your network.",
        True,
        None,
    ),
]


def classify(exc: Exception) -> ReeveError:
    """Map any exception raised by the SDK onto a ReeveError."""
    if isinstance(exc, ReeveError):
        return exc

    if isinstance(exc, TimeoutError):
        return ReeveError(
            status=504,
            code="reeve_timeout",
            user_message="Reeve took too long to answer. Try again.",
            detail=str(exc),
            retryable=True,
        )

    message = str(exc).lower()

    # The SDK reports a rejected credential as a ConnectionError wrapping a 401,
    # so type alone is misleading here: an isinstance check would tell the user
    # to check their network when the real fix is their API key. Inspect the
    # message before trusting the type.
    if isinstance(exc, ConnectionError) and not _has("401", "unauthorized", "403")(message):
        return ReeveError(
            status=503,
            code="reeve_unreachable",
            user_message="Cannot reach the Reeve service. Check your network.",
            detail=_redact(str(exc)),
            retryable=True,
        )
    for predicate, status, code, user_message, retryable, retry_after in _RULES:
        if predicate(message):
            return ReeveError(
                status=status,
                code=code,
                user_message=user_message,
                detail=_redact(str(exc)),
                retryable=retryable,
                retry_after=retry_after,
            )

    return ReeveError(
        status=502,
        code="reeve_error",
        user_message="Reeve returned an error.",
        detail=_redact(str(exc)),
    )


_KEY_PATTERN = re.compile(r"sk-[A-Za-z0-9_\-]{6,}")


def _redact(text: str) -> str:
    """An API key must never reach a browser, a log line or a screenshot."""
    return _KEY_PATTERN.sub("sk-***", text)


async def reeve_error_handler(_: Request, exc: Exception) -> JSONResponse:
    error = classify(exc)
    headers = {"Retry-After": str(error.retry_after)} if error.retry_after else None
    return JSONResponse(
        status_code=error.status,
        headers=headers,
        content={
            "code": error.code,
            "user_message": error.user_message,
            "detail": error.detail,
            "retryable": error.retryable,
        },
    )
