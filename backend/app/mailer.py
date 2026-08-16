"""Sending email, via Brevo's transactional API.

The API rather than SMTP: one HTTPS POST with an API key, no connection state, no
port 587 to get blocked by a host. `requests` is already a dependency; an SMTP
client would be another moving part for the same three emails a week.

Unconfigured is a first-class state. Without BREVO_API_KEY this raises
MailNotConfigured, and the routes turn that into an honest "password reset is
not available on this deployment" rather than a 500 or, worse, a cheerful
"check your email" for a message that was never sent. Telling somebody to check
an inbox that will stay empty is the failure mode worth designing against.

What is deliberately not here: retries, queues, bounce handling. A reset email
that fails should fail visibly and be retried by the person clicking the button
again, which they will.
"""

from __future__ import annotations

import logging

import requests

from app.config import settings

log = logging.getLogger("carrel.mail")

_ENDPOINT = "https://api.brevo.com/v3/smtp/email"
_TIMEOUT_SECONDS = 15


class MailNotConfigured(RuntimeError):
    """No API key, so this deployment cannot send email at all."""


class MailFailed(RuntimeError):
    """The provider rejected the message or could not be reached."""


def configured() -> bool:
    return bool(settings.brevo_api_key and settings.mail_from)


def send(to_email: str, subject: str, text: str, html: str = "") -> None:
    if not configured():
        raise MailNotConfigured(
            "Email is not configured on this deployment (BREVO_API_KEY / CARREL_MAIL_FROM)."
        )

    payload = {
        "sender": {"email": settings.mail_from, "name": settings.mail_from_name},
        "to": [{"email": to_email}],
        "subject": subject,
        "textContent": text,
    }
    if html:
        payload["htmlContent"] = html

    try:
        response = requests.post(
            _ENDPOINT,
            json=payload,
            headers={"api-key": settings.brevo_api_key, "accept": "application/json"},
            timeout=_TIMEOUT_SECONDS,
        )
    except requests.RequestException as exc:
        raise MailFailed(f"Could not reach the mail provider: {exc}") from exc

    if response.status_code >= 300:
        # The body carries the reason (unverified sender, quota, bad key) and is
        # worth logging — but never the API key, and never the message body,
        # which for a reset email contains a working credential.
        log.error("brevo rejected the message: %s %s", response.status_code, response.text[:300])
        raise MailFailed(f"The mail provider refused the message ({response.status_code}).")

    log.info("sent %r to %s", subject, to_email)
