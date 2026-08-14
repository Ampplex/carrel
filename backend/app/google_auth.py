"""Turning a Google ID token into an email this server is willing to believe.

The whole security argument lives in one line — the audience check — so it is
worth stating why, because the obvious alternative is a trap.

A client could instead hand us a Google *access* token and we could ask Google
"whose token is this?" via the userinfo endpoint. That returns a real, correct
profile, which makes it look safe. It is not. An access token does not say which
application it was issued to, so any other app holding a Google token for a user
— including an app an attacker wrote and persuaded someone to sign in to — can
present it here, and this server would happily hand back a session for that
person's account. The deputy is confused: it verified that the token is genuine
without verifying that it was meant for us.

An ID token is a signed JWT carrying an `aud` claim naming the OAuth client it
was minted for. Checking that claim against our own client IDs is what closes
the hole, and `verify_oauth2_token` does it along with the signature, the
issuer, and the expiry. So: ID tokens only, and no fallback. A fallback to the
access-token path would reopen exactly what this is written to prevent.

`email_verified` is required too. Google will assert an email it has not
verified for some account types, and Carrel keys a person's entire memory off
their address — an unverified one would let somebody claim a namespace by
naming it.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.config import settings


class GoogleAuthError(Exception):
    """The token is absent, malformed, expired, or meant for somebody else."""


class GoogleNotConfigured(Exception):
    """No client IDs are set, so no token could ever be checked properly."""


@dataclass(frozen=True)
class GoogleIdentity:
    email: str
    name: str
    subject: str  # Google's stable per-account id, kept for the audit trail


def configured() -> bool:
    return bool(settings.google_client_ids)


def verify(raw_token: str) -> GoogleIdentity:
    """Verify a Google ID token and return who it says they are.

    Raises rather than returning None: every failure here means "do not sign
    this person in", and a None that someone forgets to check is a login bypass.
    """
    if not configured():
        raise GoogleNotConfigured(
            "GOOGLE_CLIENT_IDS is empty, so Google sign-in is switched off on "
            "this server. Set it in backend/.env to the OAuth client IDs the "
            "app is built with."
        )
    if not raw_token or not raw_token.strip():
        raise GoogleAuthError("No Google token was sent.")

    # Imported here rather than at module scope so that a backend without the
    # dependency still starts, and fails only on the route that needs it.
    try:
        from google.auth.transport import requests as google_requests
        from google.oauth2 import id_token
    except ImportError as exc:  # pragma: no cover - depends on the environment
        raise GoogleNotConfigured(
            "google-auth is not installed. Reinstall the backend: "
            'pip install -e "backend[dev]"'
        ) from exc

    last_error: Exception | None = None
    for client_id in settings.google_client_ids:
        try:
            claims = id_token.verify_oauth2_token(
                raw_token.strip(), google_requests.Request(), client_id
            )
            break
        except Exception as exc:  # noqa: BLE001 - the library raises broadly
            last_error = exc
    else:
        # Every configured audience rejected it. Deliberately one message for
        # every cause: a client that learns *why* its forged token failed is
        # being told how to forge a better one.
        raise GoogleAuthError("That Google sign-in could not be verified.") from last_error

    if not claims.get("email"):
        raise GoogleAuthError("That Google account has no email address on it.")
    if not claims.get("email_verified"):
        raise GoogleAuthError("That Google account's email address is not verified.")

    return GoogleIdentity(
        email=str(claims["email"]).strip().lower(),
        name=str(claims.get("name") or "").strip()[:60],
        subject=str(claims.get("sub") or ""),
    )
