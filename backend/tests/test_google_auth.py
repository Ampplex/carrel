"""Google sign-in. Zero quota, and no network — Google's verifier is stubbed.

What is worth testing here is not the happy path. It is the set of tokens that
must NOT produce a session: one minted for a different application, one whose
email Google has not verified, and anything at all when the server has no client
IDs configured. Each of those is a login bypass if it slips through, and none of
them looks like a failure from the client's side.

The audience case is the one to keep. Verification against Google succeeding is
not the same as the token having been meant for us, and a verifier that ignores
`aud` will pass every other test in this file.
"""

from __future__ import annotations

import dataclasses

import pytest

from app import auth, google_auth

def _stored(email: str) -> dict:
    """One account, straight from the database.

    The tests used to read `users.json`. Reading the row keeps them asserting on
    what was actually persisted rather than on what the API chose to return —
    which is the point of checking the consent record at all.
    """
    from app.db import cursor

    with cursor() as cur:
        cur.execute("SELECT * FROM users WHERE email = %s", (email,))
        return cur.fetchone() or {}



# Isolation comes from conftest: a separate carrel_test database, wiped
# between tests.


@pytest.fixture
def google(monkeypatch):
    """A stand-in for Google's verifier, honouring the audience it is given.

    Mirrors the real contract: `verify_oauth2_token` raises unless the token was
    issued for the client id passed to it.
    """
    issued: dict[str, dict] = {}

    def fake_verify(token, _request, client_id):
        claims = issued.get(token)
        if claims is None:
            raise ValueError("Could not verify token signature.")
        if claims["aud"] != client_id:
            raise ValueError("Token has wrong audience.")
        return claims

    class FakeIdToken:
        verify_oauth2_token = staticmethod(fake_verify)

    class FakeRequests:
        Request = staticmethod(lambda: None)

    import sys
    import types

    monkeypatch.setitem(sys.modules, "google.oauth2", types.SimpleNamespace(id_token=FakeIdToken))
    monkeypatch.setitem(
        sys.modules, "google.auth.transport", types.SimpleNamespace(requests=FakeRequests)
    )

    def mint(token: str, *, aud: str, email: str, verified: bool = True, name: str = ""):
        issued[token] = {
            "aud": aud,
            "email": email,
            "email_verified": verified,
            "name": name,
            "sub": f"sub-{email}",
        }
        return token

    return mint


def _configure(monkeypatch, *client_ids: str):
    """Settings is frozen, so swap the whole object rather than a field on it."""
    monkeypatch.setattr(
        google_auth,
        "settings",
        dataclasses.replace(google_auth.settings, google_client_ids=tuple(client_ids)),
    )


OURS = "ours.apps.googleusercontent.com"
THEIRS = "someone-elses.apps.googleusercontent.com"


def test_a_token_for_our_client_signs_in(monkeypatch, google):
    _configure(monkeypatch, OURS)
    google("tok", aud=OURS, email="Ada@Example.com", name="Ada")

    identity = google_auth.verify("tok")

    assert identity.email == "ada@example.com"  # normalised, or namespaces split
    assert identity.name == "Ada"


def test_a_token_minted_for_a_different_app_is_refused(monkeypatch, google):
    """The one that matters.

    This token is genuine, unexpired and signed by Google. It was simply issued
    to somebody else's application. Accepting it would let any app holding a
    Google token for a user take over that user's Carrel account.
    """
    _configure(monkeypatch, OURS)
    google("tok", aud=THEIRS, email="ada@example.com")

    with pytest.raises(google_auth.GoogleAuthError):
        google_auth.verify("tok")


def test_any_of_several_configured_clients_is_accepted(monkeypatch, google):
    """iOS, Android and Web each get their own client id, and the token carries
    whichever one the app was built with."""
    _configure(monkeypatch, OURS, THEIRS)
    google("tok", aud=THEIRS, email="ada@example.com")

    assert google_auth.verify("tok").email == "ada@example.com"


def test_an_unverified_email_is_refused(monkeypatch, google):
    """The namespace is derived from the address, so an unverified one would let
    somebody claim another person's memory by naming it."""
    _configure(monkeypatch, OURS)
    google("tok", aud=OURS, email="ada@example.com", verified=False)

    with pytest.raises(google_auth.GoogleAuthError):
        google_auth.verify("tok")


def test_nothing_verifies_when_no_client_ids_are_set(monkeypatch, google):
    _configure(monkeypatch)
    google("tok", aud=OURS, email="ada@example.com")

    with pytest.raises(google_auth.GoogleNotConfigured):
        google_auth.verify("tok")


def test_garbage_is_refused_without_saying_why(monkeypatch, google):
    _configure(monkeypatch, OURS)

    with pytest.raises(google_auth.GoogleAuthError) as exc:
        google_auth.verify("not-a-token")

    # No detail about which check failed: that is a hint for the next attempt.
    assert "could not be verified" in str(exc.value)


# ── the account side ────────────────────────────────────────────────────────


def test_first_google_sign_in_creates_an_account():
    session = auth.sign_in_with_google("new@example.com", "New Person", "sub-1", "2026-08-14")

    stored = _stored("new@example.com")
    assert stored["google_sub"] == "sub-1"
    assert stored["terms_version"] == "2026-08-14"
    assert session["token"]


def test_signing_in_again_reuses_the_same_memory():
    first = auth.sign_in_with_google("repeat@example.com", "Person", "sub-1")
    second = auth.sign_in_with_google("repeat@example.com", "Person", "sub-1")

    assert first["namespace"] == second["namespace"]
    assert _count_users() == 1


def test_google_links_to_an_existing_password_account():
    """Same address, same namespace. Anything else would strand the notes the
    person already has behind a login they can no longer reach."""
    password_account = auth.register("both@example.com", "a good password")

    google_account = auth.sign_in_with_google("both@example.com", "Both", "sub-9")

    assert google_account["namespace"] == password_account["namespace"]
    assert _count_users() == 1


def test_linking_revokes_the_password_and_keeps_the_chosen_name():
    """This reverses an earlier decision, deliberately.

    It used to assert that linking left the password working, on the reasoning
    that somebody who set one should keep both ways in. That reasoning assumed
    the password belonged to the same person as the Google account, and nothing
    here establishes that: addresses are never verified at registration, so a
    password on an address proves only that somebody typed it.

    Google proves ownership. An unverified password does not. When they
    disagree, the password is the one to drop — otherwise an impostor who
    registered someone else's address keeps a working key to the account its
    real owner is now filling with memories.

    What survives linking is the name they chose here, which was the other half
    of the original test and is still right: Google's display name must not
    overwrite a name somebody set deliberately.
    """
    auth.register("both@example.com", "a good password", "Chosen Name")
    session = auth.sign_in_with_google("both@example.com", "Google Name", "sub-9")

    assert session["name"] == "Chosen Name"
    assert session["password_revoked"] is True

    with pytest.raises(ValueError):
        auth.login("both@example.com", "a good password")


def test_a_google_only_account_cannot_be_password_guessed():
    """No hash exists, so every password must fail — and must fail with the same
    wording as an account that does not exist at all."""
    auth.sign_in_with_google("google-only@example.com", "Person", "sub-1")

    with pytest.raises(ValueError) as google_only:
        auth.login("google-only@example.com", "any password at all")
    with pytest.raises(ValueError) as missing:
        auth.login("nobody@example.com", "any password at all")

    assert str(google_only.value) == str(missing.value)


def test_a_google_account_can_be_deleted_like_any_other():
    session = auth.sign_in_with_google("leaving@example.com", "Person", "sub-1")

    assert auth.delete_account("leaving@example.com") is True
    assert auth.resolve(session["token"]) is None


# ── the route ───────────────────────────────────────────────────────────────
#
# Two cases, both about wiring rather than logic: that the field really is
# called `id_token`, and that the two failures a client must tell apart — "your
# token is bad" and "this server cannot check tokens at all" — arrive as
# different status codes.


def _client():
    from fastapi.testclient import TestClient

    from app.main import app

    # No context manager: entering one runs the lifespan, which warms up Reeve
    # and would put a network call in a suite that promises not to make any.
    return TestClient(app)


def test_route_signs_in_and_returns_a_session(monkeypatch, google):
    _configure(monkeypatch, OURS)
    google("tok", aud=OURS, email="route@example.com", name="Route")

    r = _client().post("/api/auth/google", json={"id_token": "tok", "terms_version": "2026-08-14"})

    assert r.status_code == 200, r.text
    assert r.json()["email"] == "route@example.com"
    assert r.json()["token"]


def test_route_separates_a_bad_token_from_an_unconfigured_server(monkeypatch, google):
    _configure(monkeypatch, OURS)
    assert _client().post("/api/auth/google", json={"id_token": "rubbish"}).status_code == 401

    _configure(monkeypatch)
    assert _client().post("/api/auth/google", json={"id_token": "rubbish"}).status_code == 503


def _count_users() -> int:
    from app.db import cursor

    with cursor() as cur:
        return cur.execute("SELECT count(*) AS n FROM users").fetchone()["n"]
