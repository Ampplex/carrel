"""What happens when a Google sign-in lands on an address that already has a
password. Zero quota.

Carrel does not verify email addresses at registration, which means anybody can
sign up as anybody. That is survivable on its own — an impostor holds an account
nobody uses. It stops being survivable at the moment the real owner signs in
with Google: same address, same derived namespace, so they join the impostor's
account, and the impostor still knows the password to it.

Google proves ownership of an address. An unverified password proves nothing. So
the password loses.
"""

from __future__ import annotations

import pytest

from app import auth
from app.db import cursor


def test_the_squatters_password_stops_working():
    """The attack, start to finish.

    Somebody registers with an address they do not own and waits. The owner
    arrives through Google. Before this fix, the impostor kept a working
    password to the account the owner was now filling with their memories.
    """
    auth.register("victim@example.com", "squatter-chosen-password")

    session = auth.sign_in_with_google("victim@example.com", name="Real Owner", subject="g-1")
    assert session["token"]
    assert session["password_revoked"] is True

    with pytest.raises(ValueError):
        auth.login("victim@example.com", "squatter-chosen-password", "10.0.0.1")


def test_the_squatters_existing_sessions_are_revoked():
    """Clearing the password is not enough on its own: a token issued minutes
    earlier would outlive it and keep working for a month."""
    squatter = auth.register("victim@example.com", "squatter-chosen-password")
    assert auth.resolve(squatter["token"]) is not None

    auth.sign_in_with_google("victim@example.com", subject="g-1")

    assert auth.resolve(squatter["token"]) is None


def test_the_owner_keeps_the_account_and_its_memories():
    """Not a fresh empty account: the namespace is derived from the address, so
    the owner arrives at the same memories either way. That is the behaviour
    being protected, not a side effect."""
    auth.register("victim@example.com", "squatter-chosen-password")
    before = auth.login("victim@example.com", "squatter-chosen-password", "10.0.0.1")["namespace"]

    after = auth.sign_in_with_google("victim@example.com", subject="g-1")

    assert after["namespace"] == before


def test_a_google_only_account_is_untouched():
    """Nothing to revoke, and the flag says so — the client should not announce
    a password change to somebody who never had one."""
    first = auth.sign_in_with_google("new@example.com", subject="g-2")
    assert first["password_revoked"] is False

    again = auth.sign_in_with_google("new@example.com", subject="g-2")
    assert again["password_revoked"] is False


def test_signing_in_twice_only_reports_the_revocation_once():
    """The second sign-in has no password left to clear, so it must not keep
    telling the person their password was removed."""
    auth.register("both@example.com", "a good password")

    assert auth.sign_in_with_google("both@example.com", subject="g-3")["password_revoked"] is True
    assert auth.sign_in_with_google("both@example.com", subject="g-3")["password_revoked"] is False


def test_the_password_is_gone_from_the_database_not_just_unusable():
    """Cleared, not merely bypassed. A hash left behind is a hash that leaks."""
    auth.register("victim@example.com", "squatter-chosen-password")
    auth.sign_in_with_google("victim@example.com", subject="g-1")

    with cursor() as cur:
        cur.execute(
            "SELECT salt, password_hash FROM users WHERE email = %s", ("victim@example.com",)
        )
        row = cur.fetchone()

    assert row["salt"] is None
    assert row["password_hash"] is None


def test_other_accounts_are_not_disturbed():
    auth.register("bystander@example.com", "their own password")
    auth.register("victim@example.com", "squatter-chosen-password")

    auth.sign_in_with_google("victim@example.com", subject="g-1")

    assert auth.login("bystander@example.com", "their own password", "10.0.0.9")["token"]
