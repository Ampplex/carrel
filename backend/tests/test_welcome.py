"""The first thing Carrel ever says to somebody. Zero quota, no network.

It used to be a bare "confirm your email", which is a chore dressed up as a
greeting — and accounts created through Google got nothing at all, despite that
being the path most people take.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import auth, mailer
from app.db import cursor
from app.main import app


@pytest.fixture
def mail(monkeypatch):
    sent: list[dict] = []

    def fake_send(to_email, subject, text, html=""):
        sent.append({"to": to_email, "subject": subject, "text": text})

    import app.routes.auth as auth_routes

    monkeypatch.setattr(auth_routes.mailer, "send", fake_send)
    monkeypatch.setattr(auth_routes.mailer, "configured", lambda: True)
    monkeypatch.setattr(mailer, "send", fake_send)
    monkeypatch.setattr(mailer, "configured", lambda: True)
    return sent


def test_registering_sends_one_welcome_with_the_confirm_link(mail):
    """One email, not two. A greeting and a confirmation in the same message,
    with the confirmation as a footnote rather than the entire point."""
    TestClient(app).post(
        "/api/auth/register",
        json={"email": "ada@example.com", "password": "a good password", "name": "Ada Lovelace"},
    )

    assert len(mail) == 1
    message = mail[0]
    assert message["to"] == "ada@example.com"
    assert message["subject"] == "Welcome to Carrel"
    assert "Welcome to Carrel, Ada." in message["text"], "greets by first name"
    assert "/verify?token=" in message["text"]


def test_a_person_with_no_name_still_gets_a_sentence_that_reads(mail):
    """Name is optional on the sign-up form, so the greeting must not become
    'Welcome to Carrel, .'"""
    TestClient(app).post(
        "/api/auth/register", json={"email": "nameless@example.com", "password": "a good password"}
    )

    assert "Welcome to Carrel." in mail[0]["text"]
    assert "Carrel, ." not in mail[0]["text"]


def test_signing_up_with_google_is_welcomed_without_busywork(mail):
    """Google proved the address to issue the token at all. Asking somebody to
    confirm an address that is demonstrably theirs is ceremony."""
    auth.sign_in_with_google("new@example.com", name="New Person", subject="g-1")
    # The route is what sends; call it the way the app does.
    import app.routes.auth as auth_routes

    result = {"email": "new@example.com", "name": "New Person", "created": True}
    auth_routes._send_welcome(result["email"], result["name"], confirm=False)

    assert mail[-1]["subject"] == "Welcome to Carrel"
    assert "/verify?token=" not in mail[-1]["text"]


def test_a_google_address_is_recorded_as_verified(mail):
    """Google will not issue a token for an unverified address, so there is
    nothing left for Carrel to confirm."""
    auth.sign_in_with_google("new@example.com", subject="g-1")

    with cursor() as cur:
        cur.execute("SELECT email_verified FROM users WHERE email = %s", ("new@example.com",))
        assert cur.fetchone()["email_verified"] is True


def test_only_the_first_google_sign_in_reports_a_new_account(mail):
    """Signing in every morning must not send a welcome every morning."""
    first = auth.sign_in_with_google("new@example.com", subject="g-1")
    assert first["created"] is True

    again = auth.sign_in_with_google("new@example.com", subject="g-1")
    assert again["created"] is False


def test_a_failing_mail_provider_never_blocks_a_sign_up(monkeypatch):
    """The account is what matters. A greeting that could not be delivered is
    not a reason to refuse somebody an account."""
    import app.routes.auth as auth_routes

    def explode(*args, **kwargs):
        raise mailer.MailFailed("provider is down")

    monkeypatch.setattr(auth_routes.mailer, "configured", lambda: True)
    monkeypatch.setattr(auth_routes.mailer, "send", explode)

    response = TestClient(app).post(
        "/api/auth/register", json={"email": "ada@example.com", "password": "a good password"}
    )

    assert response.status_code == 200
    assert response.json()["token"]
