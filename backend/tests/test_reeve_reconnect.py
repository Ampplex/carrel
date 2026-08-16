"""Reconnecting after Reeve restarts underneath us. Zero quota — nothing here
reaches the network.

The failure this pins down happened in production. Reeve was redeployed, which
force-recreated its container and destroyed every SSE session it knew about.
Carrel went on posting to /messages/?session_id=<gone>, got 404 every time, and
answered "Reeve returned an error" to everything the phone asked — until
somebody restarted the container by hand.

The SDK reconnects when a session expires from idleness. A server that vanished
underneath a perfectly healthy session is a different case, and it was not
covered.
"""

from __future__ import annotations

import pytest

from app import reeve_gateway


class _FakeResponse:
    def __init__(self, status_code):
        self.status_code = status_code


class _HttpError(Exception):
    """Shaped like requests.HTTPError: the status lives on `.response`."""

    def __init__(self, status_code):
        super().__init__(f"{status_code} Client Error")
        self.response = _FakeResponse(status_code)


def test_a_dead_session_is_retried_once_and_succeeds():
    calls = []

    def flaky(*args, **kwargs):
        calls.append(args)
        if len(calls) == 1:
            raise _HttpError(404)  # the session the server forgot
        return "answer"

    assert reeve_gateway._retrying(flaky, "question", speaker="ns") == "answer"
    assert len(calls) == 2


def test_it_retries_exactly_once():
    """If the second attempt fails the same way, the session is not the problem
    and retrying forever turns a clear error into a slow one."""
    calls = []

    def always_404(*args, **kwargs):
        calls.append(args)
        raise _HttpError(404)

    with pytest.raises(_HttpError):
        reeve_gateway._retrying(always_404, "question")

    assert len(calls) == 2


def test_other_failures_are_not_retried():
    """A 500, a timeout, a bad request — none of those are fixed by a new
    session, and retrying them doubles the load on something already unhappy."""
    for error in (_HttpError(500), _HttpError(400), ValueError("bad argument")):
        calls = []

        def failing(*args, **kwargs):
            calls.append(args)
            raise error

        with pytest.raises(type(error)):
            reeve_gateway._retrying(failing, "question")

        assert len(calls) == 1, f"{error} should not have been retried"


def test_a_successful_call_is_not_retried():
    calls = []

    def fine(*args, **kwargs):
        calls.append(args)
        return "ok"

    assert reeve_gateway._retrying(fine, "question") == "ok"
    assert len(calls) == 1


def test_reconnect_actually_empties_the_client_cache():
    """Guards a bug this test's first version had.

    That version invented an attribute (`reeve_tools._client = object()`), then
    asserted the reconnect cleared it — so it passed against an implementation
    that cleared three names the SDK has never used and left the real cache
    untouched. The app stayed broken and the suite stayed green.

    This asserts on the cache the SDK genuinely keeps, so if a future version
    renames it the test fails instead of the reconnect quietly doing nothing.
    """
    import reeve.tools as reeve_tools

    assert hasattr(reeve_tools, "_client_cache"), "SDK no longer caches in _client_cache"

    closed = []

    class _StubClient:
        # reset_client_cache closes each client before dropping it, so a bare
        # object() fails here — which is itself evidence the reconnect reaches
        # the real cache rather than a name nobody uses.
        def close(self):
            closed.append(True)

    reeve_tools._client_cache[("http://example", "key")] = _StubClient()

    reeve_gateway._reconnect()

    assert reeve_tools._client_cache == {}
    assert closed == [True], "the old connection should be closed, not just forgotten"
