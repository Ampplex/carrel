"""Account tests. Zero quota — nothing here touches Reeve.

The point of these is the boundary, not the happy path. A namespace is the only
thing separating one person's memory from another's, so the properties worth
pinning down are that it is derived rather than supplied, that it is stable for
an email and different for every other, and that a deleted account cannot be
reached by a token issued moments earlier.

The consent record is checked here too. Storing which wording somebody agreed
to is only worth anything if it is the wording their app actually showed them,
so the test asserts the client's value is what lands on disk.
"""

from __future__ import annotations

import pytest

from app import auth


@pytest.fixture(autouse=True)
def _isolated_store(tmp_path, monkeypatch):
    """Point the JSON stores at a temp dir.

    Without this the suite would write to the real `var/users.json` — the file
    holding live password hashes for whoever is using the app.
    """
    monkeypatch.setattr(auth, "_USERS", tmp_path / "users.json")
    monkeypatch.setattr(auth, "_SESSIONS", tmp_path / "sessions.json")
    yield


def test_registration_records_the_terms_version_the_client_displayed():
    auth.register("ada@example.com", "correct horse", terms_version="2026-08-14")

    user = auth._read(auth._USERS)["ada@example.com"]
    assert user["terms_version"] == "2026-08-14"
    assert user["terms_accepted_at"] > 0


def test_a_client_that_sends_no_version_can_still_register():
    """An older build predates the field. Recording an empty version is a truer
    account of what happened than refusing the sign-up or inventing one."""
    session = auth.register("grace@example.com", "a good password")

    assert session["token"]
    assert auth._read(auth._USERS)["grace@example.com"]["terms_version"] == ""


def test_namespace_is_stable_per_email_and_never_shared():
    a = auth.register("a@example.com", "password one")
    b = auth.register("b@example.com", "password two")

    assert a["namespace"] != b["namespace"]
    # Signing in again lands on the same memory, or the account would appear
    # empty on every new device.
    assert auth.login("a@example.com", "password one")["namespace"] == a["namespace"]


def test_email_case_does_not_create_a_second_account():
    auth.register("Mixed@Example.com", "password one")
    with pytest.raises(ValueError):
        auth.register("mixed@example.com", "password two")


def test_wrong_password_is_rejected_and_says_nothing_about_the_account():
    auth.register("someone@example.com", "the real password")

    with pytest.raises(ValueError) as wrong:
        auth.login("someone@example.com", "not the password")
    with pytest.raises(ValueError) as missing:
        auth.login("nobody@example.com", "not the password")

    # Identical wording, or the response tells an attacker which emails exist.
    assert str(wrong.value) == str(missing.value)


def test_short_password_is_refused():
    with pytest.raises(ValueError):
        auth.register("short@example.com", "1234567")


def test_deleting_an_account_kills_tokens_issued_before_it():
    session = auth.register("leaving@example.com", "a good password")
    assert auth.resolve(session["token"]) is not None

    auth.delete_account("leaving@example.com")

    # A live token outliving its account would be a session nobody can revoke.
    assert auth.resolve(session["token"]) is None


def test_deleting_one_account_leaves_another_signed_in():
    staying = auth.register("staying@example.com", "a good password")
    auth.register("going@example.com", "a good password")

    auth.delete_account("going@example.com")

    assert auth.resolve(staying["token"]) is not None
