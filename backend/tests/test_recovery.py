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


@pytest.fixture
def webhook_secret():
    """Settings is a frozen dataclass, so monkeypatch cannot assign to it —
    frozen on purpose, since configuration changing under a running server is a
    class of bug nobody enjoys. Tests reach past it deliberately and put it back.
    """
    from app.config import settings

    previous = settings.brevo_webhook_secret
    object.__setattr__(settings, "brevo_webhook_secret", "the-real-secret")
    yield "the-real-secret"
    object.__setattr__(settings, "brevo_webhook_secret", previous)


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

    response = client.post("/reset", data={"token": token, "password": "a brand new one", "confirm": "a brand new one"})
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
    client.post("/reset", data={"token": _token_from(mail[0]["text"]), "password": "a new one", "confirm": "a new one"})

    assert auth.resolve(session["token"]) is None


def test_a_link_works_once(mail):
    auth.register("ada@example.com", "the old password")
    client = TestClient(app)
    client.post("/api/auth/forgot", json={"email": "ada@example.com"})
    token = _token_from(mail[0]["text"])

    assert "Password changed" in client.post(
        "/reset", data={"token": token, "password": "first new password", "confirm": "first new password"}
    ).text
    second = client.post("/reset", data={"token": token, "password": "second new password", "confirm": "second new password"})
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
        "/reset", data={"token": token, "password": "still works fine", "confirm": "still works fine"}
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
        "/reset", data={"token": token, "password": "should not work", "confirm": "should not work"}
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
        "/reset", data={"token": first, "password": "via the old link", "confirm": "via the old link"}
    ).text
    assert "Password changed" in client.post(
        "/reset", data={"token": second, "password": "via the new link", "confirm": "via the new link"}
    ).text


def test_forgot_never_reveals_whether_an_account_exists(mail):
    """Otherwise 'I forgot my password' becomes a way to ask 'is this person
    registered here?' — which login() is careful never to answer.

    The HTTP response is what must not vary. What arrives in the inbox may, and
    does: only the person who can read it learns which case they are in.
    """
    auth.register("real@example.com", "a password")
    auth.sign_in_with_google("google-only@example.com", subject="g-1")
    client = TestClient(app)

    responses = [
        client.post("/api/auth/forgot", json={"email": address})
        for address in ("real@example.com", "nobody@example.com", "google-only@example.com")
    ]

    assert {r.status_code for r in responses} == {200}
    assert len({r.json()["message"] for r in responses}) == 1


def test_every_case_gets_an_email_that_says_what_happened(mail):
    """Nobody is left waiting for a message that is never coming.

    The case that forced this: an account created through Google has no
    password, so the earlier version sent nothing while saying "check your
    email". Somebody who had forgotten they used Google would wait forever.
    """
    auth.register("real@example.com", "a password")
    auth.sign_in_with_google("google-only@example.com", subject="g-1")
    client = TestClient(app)

    for address in ("real@example.com", "google-only@example.com", "nobody@example.com"):
        client.post("/api/auth/forgot", json={"email": address})

    by_address = {m["to"]: m for m in mail}
    assert set(by_address) == {"real@example.com", "google-only@example.com", "nobody@example.com"}

    assert "token=" in by_address["real@example.com"]["text"]

    google_only = by_address["google-only@example.com"]
    assert "token=" not in google_only["text"], "a Google-only account has nothing to reset"
    assert "Google" in google_only["subject"]

    missing = by_address["nobody@example.com"]
    assert "token=" not in missing["text"], "no account means no reset link"
    assert "no Carrel account" in missing["text"]


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
    client.post("/reset", data={"token": _token_from(mail[0]["text"]), "password": "a new one", "confirm": "a new one"})

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
    client.post("/reset", data={"token": _token_from(mail[0]["text"]), "password": "a new one", "confirm": "a new one"})

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


def test_mismatched_passwords_are_refused_without_burning_the_link(mail):
    """A single-use token makes a typo expensive: the earlier version spent the
    token first, so mistyping left somebody with a password they did not know
    and no way to change it without another email."""
    auth.register("ada@example.com", "the old password")
    client = TestClient(app)
    client.post("/api/auth/forgot", json={"email": "ada@example.com"})
    token = _token_from(mail[0]["text"])

    rejected = client.post(
        "/reset", data={"token": token, "password": "one password", "confirm": "another one"}
    )
    assert "do not match" in rejected.text
    # Old password still works: nothing was changed.
    assert auth.login("ada@example.com", "the old password", "10.0.0.1")["token"]

    # And the link survived, so the retry needs no new email.
    assert "Password changed" in client.post(
        "/reset", data={"token": token, "password": "matching one", "confirm": "matching one"}
    ).text
    assert auth.login("ada@example.com", "matching one", "10.0.0.1")["token"]


def test_a_short_password_also_leaves_the_link_alive(mail):
    auth.register("ada@example.com", "the old password")
    client = TestClient(app)
    client.post("/api/auth/forgot", json={"email": "ada@example.com"})
    token = _token_from(mail[0]["text"])

    assert "at least 8" in client.post(
        "/reset", data={"token": token, "password": "short", "confirm": "short"}
    ).text.lower()

    assert "Password changed" in client.post(
        "/reset", data={"token": token, "password": "long enough now", "confirm": "long enough now"}
    ).text


def test_the_form_asks_for_confirmation(mail):
    auth.register("ada@example.com", "a password")
    client = TestClient(app)
    client.post("/api/auth/forgot", json={"email": "ada@example.com"})
    body = client.get(f"/reset?token={_token_from(mail[0]['text'])}").text

    assert 'name="password"' in body
    assert 'name="confirm"' in body


def test_an_undeliverable_address_is_reported_rather_than_swallowed(mail):
    """The bug this fixes was visible on the phone: type a mistyped domain, get
    "check your email", and wait forever — nothing had been sent, because there
    was nowhere to send it.

    Saying so leaks nothing. Whether a domain has a mail server is public; it
    says nothing about who has an account here.
    """
    client = TestClient(app)

    broken = client.post("/api/auth/forgot", json={"email": "not-an-email"})
    assert broken.status_code == 400
    assert "email address" in broken.json()["detail"]

    dead = client.post(
        "/api/auth/forgot", json={"email": "nobody@qwerty-not-a-real-domain-8842.com"}
    )
    assert dead.status_code == 400
    assert "qwerty-not-a-real-domain-8842.com" in dead.json()["detail"]

    assert mail == []


def test_garbage_addresses_are_not_handed_to_the_mail_provider(mail, monkeypatch):
    """Two costs, both avoidable.

    A syntactically broken address came back 400 from the provider and logged an
    error for what was only ever a typo. An address on a domain that does not
    exist is worse: the provider accepts it, attempts delivery, and it hard
    bounces — and a sender with a high bounce rate gets throttled, which lands
    on the reset emails that actually matter.
    """
    client = TestClient(app)

    for address in ("not-an-email", "someone@this-domain-does-not-exist-9x7q.invalid"):
        assert client.post("/api/auth/forgot", json={"email": address}).status_code == 400

    assert mail == [], f"nothing should have been sent, got {[m['to'] for m in mail]}"


def test_a_real_account_is_never_gated_on_dns(mail, monkeypatch):
    """The deliverability check guards the courtesy note only.

    A resolver hiccup must never be the reason somebody cannot reset a password
    — they already receive mail from us, so the address is known good.
    """
    from app import deliverability

    auth.register("ada@example.com", "a password")
    monkeypatch.setattr(deliverability, "worth_sending_to", lambda email: False)

    TestClient(app).post("/api/auth/forgot", json={"email": "ada@example.com"})

    assert [m["to"] for m in mail] == ["ada@example.com"]
    assert "token=" in mail[0]["text"]


def test_the_owner_is_told_when_the_password_changes(mail):
    """If somebody else reset it, this is how the owner finds out while it is
    still worth acting on."""
    auth.register("ada@example.com", "the old password")
    client = TestClient(app)
    client.post("/api/auth/forgot", json={"email": "ada@example.com"})
    client.post(
        "/reset",
        data={
            "token": _token_from(mail[0]["text"]),
            "password": "a new one",
            "confirm": "a new one",
        },
        follow_redirects=True,
    )

    notice = [m for m in mail if "was changed" in m["subject"]]
    assert notice, [m["subject"] for m in mail]
    assert "token=" not in notice[0]["text"], "the notice must carry no credential"


def test_a_successful_reset_redirects_so_the_token_leaves_the_url(mail):
    """Rendering the result would leave the form's URL — token and all — in
    history and in the back button."""
    auth.register("ada@example.com", "the old password")
    client = TestClient(app)
    client.post("/api/auth/forgot", json={"email": "ada@example.com"})

    response = client.post(
        "/reset",
        data={
            "token": _token_from(mail[0]["text"]),
            "password": "a new one",
            "confirm": "a new one",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/reset/done"
    assert "token" not in response.headers["location"]


def test_reset_pages_forbid_referrer_leakage(mail):
    """The reset URL carries a live credential in its query string; a Referer
    header would carry it to anywhere the page links."""
    client = TestClient(app)
    response = client.get("/reset?token=whatever")

    assert response.headers["referrer-policy"] == "no-referrer"
    assert response.headers["cache-control"] == "no-store"


def test_an_address_that_bounced_before_is_refused_plainly(mail):
    """The case no synchronous check can catch.

    `gmail.com` resolves, so a typo before the @ passes everything available at
    request time — the message is accepted, attempted, and rejected seconds
    later. The provider tells us, just too late to answer the request that
    caused it. So the first attempt is silent and every one after it is not.
    """
    from app import bounces

    client = TestClient(app)
    first = client.post("/api/auth/forgot", json={"email": "no-such-person-88xyz@gmail.com"})
    assert first.status_code == 200  # nothing knowable yet

    bounces.record("no-such-person-88xyz@gmail.com", reason="hard_bounce")

    second = client.post("/api/auth/forgot", json={"email": "no-such-person-88xyz@gmail.com"})
    assert second.status_code == 400
    assert "bounced" in second.json()["detail"].lower()


def test_a_recovered_address_is_forgiven(mail):
    """A full mailbox or a briefly broken domain must not blacklist somebody
    forever on the strength of one bad day."""
    from app import bounces

    bounces.record("ada@example.com", reason="hard_bounce")
    assert bounces.has_bounced("ada@example.com")

    bounces.clear("ada@example.com")

    auth.register("ada@example.com", "a password")
    assert TestClient(app).post(
        "/api/auth/forgot", json={"email": "ada@example.com"}
    ).status_code == 200


def test_the_bounce_webhook_needs_the_secret(webhook_secret):
    """Otherwise it is an open endpoint for marking anybody's address dead."""
    client = TestClient(app)

    wrong = client.post(
        "/api/hooks/brevo/guessed", json={"event": "hard_bounce", "email": "victim@example.com"}
    )
    assert wrong.status_code == 404, "and 404 rather than 403, so it does not confirm it exists"

    from app import bounces

    assert not bounces.has_bounced("victim@example.com")


def test_the_bounce_webhook_records_and_clears(webhook_secret):
    from app import bounces

    client = TestClient(app)

    client.post(
        "/api/hooks/brevo/the-real-secret",
        json={"event": "hard_bounce", "email": "dead@example.com"},
    )
    assert bounces.has_bounced("dead@example.com")

    client.post(
        "/api/hooks/brevo/the-real-secret",
        json={"event": "delivered", "email": "dead@example.com"},
    )
    assert not bounces.has_bounced("dead@example.com")


def test_transient_events_are_ignored(webhook_secret):
    """A deferred message or a full mailbox says nothing lasting."""
    from app import bounces

    TestClient(app).post(
        "/api/hooks/brevo/the-real-secret",
        json={"event": "soft_bounce", "email": "busy@example.com"},
    )
    assert not bounces.has_bounced("busy@example.com")
