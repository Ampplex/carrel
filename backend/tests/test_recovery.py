"""Password reset and email verification. Zero quota, no network.

The dangerous parts of a reset flow are not the happy path. They are: leaking
whether an account exists, letting one link be used twice, letting an expired
link through, and leaving the old sessions alive afterwards so the reset
achieves nothing against the person you were resetting away from.
"""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from app import auth, email_tokens, mailer
from app.db import cursor
from app.main import app


@pytest.fixture
def mail(monkeypatch):
    """Capture outgoing mail instead of sending it."""
    sent: list[dict] = []

    def fake_send(to_email, subject, text, html=""):
        sent.append({"to": to_email, "subject": subject, "text": text})

    monkeypatch.setattr(mailer, "send", fake_send)
    monkeypatch.setattr(mailer, "configured", lambda: True)
    # The routes imported these names directly.
    import app.routes.recovery as recovery_routes

    monkeypatch.setattr(recovery_routes.mailer, "send", fake_send)
    monkeypatch.setattr(recovery_routes.mailer, "configured", lambda: True)
    return sent


def _token_from(email_text: str) -> str:
    for word in email_text.split():
        if "token=" in word:
            return word.split("token=")[1].strip()
    raise AssertionError(f"no token in email:\n{email_text}")


def test_a_reset_link_actually_changes_the_password(mail):
    auth.register("ada@example.com", "the old password")
    client = TestClient(app)

    assert client.post("/api/auth/forgot", json={"email": "ada@example.com"}).status_code == 200
    token = _token_from(mail[0]["text"])

    response = client.post("/reset", data={"token": token, "password": "a brand new one"})
    assert response.status_code == 200
    assert "Password changed" in response.text

    assert auth.login("ada@example.com", "a brand new one", "10.0.0.1")["token"]
    with pytest.raises(ValueError):
        auth.login("ada@example.com", "the old password", "10.0.0.1")


def test_resetting_signs_out_every_existing_session(mail):
    """If somebody is resetting because their account was taken, leaving the
    intruder's month-long token alive would make the reset theatre."""
    session = auth.register("ada@example.com", "the old password")
    assert auth.resolve(session["token"]) is not None

    client = TestClient(app)
    client.post("/api/auth/forgot", json={"email": "ada@example.com"})
    client.post("/reset", data={"token": _token_from(mail[0]["text"]), "password": "a new one"})

    assert auth.resolve(session["token"]) is None


def test_a_link_works_once(mail):
    auth.register("ada@example.com", "the old password")
    client = TestClient(app)
    client.post("/api/auth/forgot", json={"email": "ada@example.com"})
    token = _token_from(mail[0]["text"])

    assert "Password changed" in client.post(
        "/reset", data={"token": token, "password": "first new password"}
    ).text
    second = client.post("/reset", data={"token": token, "password": "second new password"})
    assert "Link expired" in second.text

    # And the second attempt changed nothing.
    assert auth.login("ada@example.com", "first new password", "10.0.0.1")["token"]


def test_showing_the_form_does_not_spend_the_token(mail):
    """A mail client's link preview fetches the URL. If GET consumed the token,
    the reset would be dead before the person ever saw the box."""
    auth.register("ada@example.com", "the old password")
    client = TestClient(app)
    client.post("/api/auth/forgot", json={"email": "ada@example.com"})
    token = _token_from(mail[0]["text"])

    client.get(f"/reset?token={token}")
    client.get(f"/reset?token={token}")

    assert "Password changed" in client.post(
        "/reset", data={"token": token, "password": "still works fine"}
    ).text


def test_an_expired_link_is_refused(mail):
    auth.register("ada@example.com", "the old password")
    client = TestClient(app)
    client.post("/api/auth/forgot", json={"email": "ada@example.com"})
    token = _token_from(mail[0]["text"])

    with cursor(commit=True) as cur:
        cur.execute(
            "UPDATE email_tokens SET created_at = %s",
            (time.time() - email_tokens.TTL_SECONDS[email_tokens.RESET] - 60,),
        )

    assert "Link expired" in client.post(
        "/reset", data={"token": token, "password": "should not work"}
    ).text
    assert auth.login("ada@example.com", "the old password", "10.0.0.1")["token"]


def test_asking_again_invalidates_the_first_link(mail):
    """Somebody who requests a second email expects the first to be dead — and
    an attacker who intercepted the first should find that it is."""
    auth.register("ada@example.com", "the old password")
    client = TestClient(app)

    client.post("/api/auth/forgot", json={"email": "ada@example.com"})
    first = _token_from(mail[0]["text"])
    client.post("/api/auth/forgot", json={"email": "ada@example.com"})
    second = _token_from(mail[1]["text"])

    assert "Link expired" in client.post(
        "/reset", data={"token": first, "password": "via the old link"}
    ).text
    assert "Password changed" in client.post(
        "/reset", data={"token": second, "password": "via the new link"}
    ).text


def test_forgot_never_reveals_whether_an_account_exists(mail):
    """Otherwise 'I forgot my password' becomes a way to ask 'is this person
    registered here?' — which login() is careful never to answer."""
    auth.register("real@example.com", "a password")
    auth.sign_in_with_google("google-only@example.com", subject="g-1")
    client = TestClient(app)

    responses = [
        client.post("/api/auth/forgot", json={"email": address})
        for address in ("real@example.com", "nobody@example.com", "google-only@example.com")
    ]

    assert {r.status_code for r in responses} == {200}
    assert len({r.json()["message"] for r in responses}) == 1

    # Only the account that actually has a password got mail.
    assert [m["to"] for m in mail] == ["real@example.com"]


def test_forgot_is_honest_when_email_is_not_configured(monkeypatch):
    """Telling somebody to check an inbox that will never receive anything is
    worse than admitting the deployment cannot send mail."""
    import app.routes.recovery as recovery_routes

    monkeypatch.setattr(recovery_routes.mailer, "configured", lambda: False)
    auth.register("ada@example.com", "a password")

    response = TestClient(app).post("/api/auth/forgot", json={"email": "ada@example.com"})
    assert response.status_code == 503


def test_a_completed_reset_counts_as_verifying_the_address(mail):
    """Reading the inbox is exactly what verification asks. Making somebody
    prove it twice is ceremony."""
    auth.register("ada@example.com", "the old password")
    client = TestClient(app)
    client.post("/api/auth/forgot", json={"email": "ada@example.com"})
    client.post("/reset", data={"token": _token_from(mail[0]["text"]), "password": "a new one"})

    with cursor() as cur:
        cur.execute("SELECT email_verified FROM users WHERE email = %s", ("ada@example.com",))
        assert cur.fetchone()["email_verified"] is True


def test_a_reset_clears_the_sign_in_lockout(mail):
    """Someone locked out by failed guesses, who then proves they own the inbox,
    must not stay locked out — they have shown stronger evidence than the
    failures that locked them."""
    auth.register("ada@example.com", "the old password")
    for _ in range(auth.MAX_FAILURES_PER_EMAIL):
        with pytest.raises(ValueError):
            auth.login("ada@example.com", "wrong", "10.0.0.1")
    with pytest.raises(auth.RateLimited):
        auth.login("ada@example.com", "the old password", "10.0.0.1")

    client = TestClient(app)
    client.post("/api/auth/forgot", json={"email": "ada@example.com"})
    client.post("/reset", data={"token": _token_from(mail[0]["text"]), "password": "a new one"})

    assert auth.login("ada@example.com", "a new one", "10.0.0.1")["token"]


def test_tokens_are_not_stored_in_a_usable_form(mail):
    """A live reset token is a working credential. A database dump, a backup or
    a stray log must not contain links somebody can click."""
    auth.register("ada@example.com", "a password")
    TestClient(app).post("/api/auth/forgot", json={"email": "ada@example.com"})
    token = _token_from(mail[0]["text"])

    with cursor() as cur:
        cur.execute("SELECT token_hash FROM email_tokens")
        stored = [row["token_hash"] for row in cur.fetchall()]

    assert stored
    assert token not in stored
    assert all(len(h) == 64 for h in stored)
