"""Sign-in rate limiting. Zero quota.

scrypt makes each guess cost about a tenth of a second, which stops an offline
attack on a stolen hash and does nothing about an online one — a script can
still try tens of thousands of passwords a day against a public endpoint. This
endpoint is public.

The properties worth pinning down are that the limit actually engages, that it
is not trivially sidestepped by changing one field, and that it never locks out
somebody who knows their password.
"""

from __future__ import annotations

import time

import pytest

from app import auth


def _register(email="ada@example.com", password="correct horse"):
    auth.register(email, password)


def _fail(email="ada@example.com", ip="10.0.0.1", times=1):
    for _ in range(times):
        with pytest.raises(ValueError):
            auth.login(email, "wrong password", ip)


def test_wrong_passwords_are_eventually_refused_outright():
    _register()
    _fail(times=auth.MAX_FAILURES_PER_EMAIL)

    with pytest.raises(auth.RateLimited):
        auth.login("ada@example.com", "wrong password", "10.0.0.1")


def test_the_limit_holds_even_for_the_right_password():
    """Deliberate, and worth being explicit about: once the limit engages it
    applies to every attempt, not just wrong ones. Letting a correct password
    through would turn the limiter into an oracle that confirms a guess."""
    _register()
    _fail(times=auth.MAX_FAILURES_PER_EMAIL)

    with pytest.raises(auth.RateLimited):
        auth.login("ada@example.com", "correct horse", "10.0.0.1")


def test_a_new_address_does_not_reset_a_grinding_attack():
    """Per-email, so rotating through a botnet does not buy fresh attempts."""
    _register()
    for i in range(auth.MAX_FAILURES_PER_EMAIL):
        with pytest.raises(ValueError):
            auth.login("ada@example.com", "wrong", f"10.0.0.{i}")

    with pytest.raises(auth.RateLimited):
        auth.login("ada@example.com", "wrong", "10.0.99.99")


def test_one_host_spraying_many_accounts_is_stopped_by_the_ip_limit():
    """The case a per-email limit never sees: one password, tried once each
    against hundreds of accounts, never tripping any single email's counter."""
    for i in range(auth.MAX_FAILURES_PER_IP):
        with pytest.raises(ValueError):
            auth.login(f"nobody{i}@example.com", "password123", "10.0.0.7")

    _register("victim@example.com", "correct horse")
    with pytest.raises(auth.RateLimited):
        auth.login("victim@example.com", "password123", "10.0.0.7")


def test_an_untouched_account_is_unaffected():
    """One person's failures must not lock out anybody else."""
    _register("ada@example.com")
    _register("grace@example.com", "another good password")
    _fail("ada@example.com", times=auth.MAX_FAILURES_PER_EMAIL)

    session = auth.login("grace@example.com", "another good password", "10.0.0.2")
    assert session["token"]


def test_failures_age_out_of_the_window():
    """A lockout that never expires is a support ticket, not security."""
    from app.db import cursor

    _register()
    _fail(times=auth.MAX_FAILURES_PER_EMAIL)

    with cursor(commit=True) as cur:
        cur.execute(
            "UPDATE login_failures SET at = %s",
            (time.time() - auth.RATE_WINDOW_SECONDS - 60,),
        )

    session = auth.login("ada@example.com", "correct horse", "10.0.0.1")
    assert session["token"]


def test_a_successful_sign_in_is_not_recorded():
    """Only failures count. Somebody who signs in every morning from the same
    address must never accumulate their way into a lockout."""
    from app.db import cursor

    _register()
    for _ in range(5):
        auth.login("ada@example.com", "correct horse", "10.0.0.1")

    with cursor() as cur:
        cur.execute("SELECT count(*) AS n FROM login_failures")
        assert cur.fetchone()["n"] == 0
