"""Error-classification tests. Zero quota.

These exist because the SDK erases exception types — a server-side failure
arrives as a `RuntimeError` carrying a message string — so classification is
string matching, and string matching rots silently. A wrong mapping is not
cosmetic: it tells the user to fix the wrong thing.
"""

from __future__ import annotations

from app.errors import classify


def test_401_wrapped_in_connectionerror_is_an_auth_problem_not_a_network_one():
    """The SDK raises ConnectionError for a rejected key.

    Trusting the exception type here would send the user to check their wifi
    when the actual fix is REEVE_API_KEY. Measured against the real message the
    SDK produced.
    """
    exc = ConnectionError(
        "Failed to connect to Reeve server at https://mcp.reeve.co.in/sse: "
        "401 Client Error: Unauthorized for url: https://mcp.reeve.co.in/sse"
    )
    error = classify(exc)
    assert error.code == "reeve_auth"
    assert "REEVE_API_KEY" in error.user_message


def test_genuine_network_failure_still_reads_as_unreachable():
    error = classify(ConnectionError("Failed to connect: [Errno 61] Connection refused"))
    assert error.code == "reeve_unreachable"
    assert error.retryable


def test_quota_and_token_quota_are_distinguished():
    assert classify(RuntimeError("RPC Error: monthly quota exceeded")).code == "query_quota_exceeded"
    assert classify(RuntimeError("RPC Error: token quota exhausted")).code == "token_quota_exceeded"


def test_throttling_is_retryable_with_a_delay():
    error = classify(RuntimeError("RPC Error: ThrottlingException from Bedrock"))
    assert error.code == "model_throttled"
    assert error.retryable
    assert error.retry_after


def test_timeout_maps_to_504():
    assert classify(TimeoutError("no response in 180s")).status == 504


def test_api_keys_are_never_echoed_back():
    """A key must not reach a browser, a log line, or a screenshot in a report."""
    error = classify(RuntimeError("RPC Error: bad key sk-Nv9tSECRETVALUE1234 rejected"))
    assert "sk-Nv9tSECRETVALUE1234" not in error.detail
    assert "sk-***" in error.detail


def test_unknown_errors_still_classify():
    error = classify(RuntimeError("something nobody predicted"))
    assert error.status == 502
    assert error.code == "reeve_error"
