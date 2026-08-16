"""Single-use links: verify an address, or reset a password.

Both are the same shape — a secret in a URL that proves the person can read a
particular inbox — so they share one table and one set of rules:

  * The token is random and long enough that guessing is not a strategy.
  * Only its **hash** is stored. A live reset token is a working credential for
    an account, so a database dump, a backup or a stray log must not contain
    usable links. Same argument as password hashes, applied to the thing that
    can replace a password.
  * Single use. Consumed atomically, so two clicks on the same link cannot both
    succeed — a reset link forwarded or left in an inbox is spent.
  * Short-lived. An hour for a reset, a day for a verification: the reset token
    is the more dangerous of the two, so it lives the shorter life.
  * Issuing a new one invalidates the account's earlier unused tokens of the
    same kind, so a stolen old email stops working the moment somebody asks for
    a fresh link.
"""

from __future__ import annotations

import hashlib
import secrets
import time

from app.db import cursor

VERIFY = "verify"
RESET = "reset"

TTL_SECONDS = {
    VERIFY: 60 * 60 * 24,  # a day; missing it costs nothing but another email
    RESET: 60 * 60,  # an hour; this one can take over an account
}


def _hash(token: str) -> str:
    """SHA-256, not scrypt.

    Deliberate: this is a 256-bit random value, not a human-chosen password, so
    there is no dictionary to attack and nothing for a slow hash to buy. What
    matters is that the stored form cannot be replayed.
    """
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def issue(email: str, purpose: str) -> str:
    """Create a token and return the raw value — the only time it exists."""
    token = secrets.token_urlsafe(32)
    now = time.time()
    with cursor(commit=True) as cur:
        # Any earlier unused link of this kind stops working now. Somebody who
        # asks for a second reset email expects the first to be dead, and an
        # attacker who intercepted the first should find it is.
        cur.execute(
            "DELETE FROM email_tokens WHERE email = %s AND purpose = %s AND used_at IS NULL",
            (email, purpose),
        )
        cur.execute(
            "INSERT INTO email_tokens (token_hash, email, purpose, created_at)"
            " VALUES (%s, %s, %s, %s)",
            (_hash(token), email, purpose, now),
        )
    return token


def consume(token: str, purpose: str) -> str | None:
    """Spend a token, returning the email it belongs to, or None.

    The UPDATE ... WHERE used_at IS NULL RETURNING is what makes this safe: the
    database decides the winner, so two simultaneous clicks cannot both be
    served. Checking first and updating after would leave exactly that gap.
    """
    if not token:
        return None

    cutoff = time.time() - TTL_SECONDS.get(purpose, 3600)
    with cursor(commit=True) as cur:
        cur.execute(
            """
            UPDATE email_tokens SET used_at = %s
            WHERE token_hash = %s AND purpose = %s AND used_at IS NULL AND created_at > %s
            RETURNING email
            """,
            (time.time(), _hash(token), purpose, cutoff),
        )
        row = cur.fetchone()

        # Housekeeping on the write path, as elsewhere: spent and expired rows
        # have no further use and this is the only moment the table is open.
        cur.execute(
            "DELETE FROM email_tokens WHERE created_at < %s",
            (time.time() - max(TTL_SECONDS.values()) * 2,),
        )
    return row["email"] if row else None


# Throttling for the endpoint that sends these, kept here rather than in auth.py
# because it protects something different: not password guessing, but flooding
# somebody's inbox and burning the deployment's mail quota.
MAIL_WINDOW_SECONDS = 60 * 60
MAX_MAILS_PER_EMAIL = 5
MAX_MAILS_PER_IP = 20


class TooManyRequests(Exception):
    def __init__(self, retry_after: int):
        super().__init__("Too many reset requests. Try again later.")
        self.retry_after = retry_after


def check_mail_quota(email: str, client_ip: str) -> None:
    """Deliberately separate from the sign-in limiter.

    They were shared once, and the result was that anybody locked out by wrong
    passwords could not ask for a reset — locking out the one person with a
    legitimate reason to be there.
    """
    since = time.time() - MAIL_WINDOW_SECONDS
    with cursor() as cur:
        cur.execute(
            "SELECT count(*) AS n FROM mail_requests WHERE email = %s AND at > %s", (email, since)
        )
        by_email = cur.fetchone()["n"]
        by_ip = 0
        if client_ip:
            cur.execute(
                "SELECT count(*) AS n FROM mail_requests WHERE client_ip = %s AND at > %s",
                (client_ip, since),
            )
            by_ip = cur.fetchone()["n"]

    if by_email >= MAX_MAILS_PER_EMAIL or by_ip >= MAX_MAILS_PER_IP:
        raise TooManyRequests(retry_after=MAIL_WINDOW_SECONDS)


def record_mail_request(email: str, client_ip: str) -> None:
    now = time.time()
    with cursor(commit=True) as cur:
        cur.execute(
            "INSERT INTO mail_requests (email, client_ip, at) VALUES (%s, %s, %s)",
            (email, client_ip, now),
        )
        cur.execute("DELETE FROM mail_requests WHERE at < %s", (now - MAIL_WINDOW_SECONDS * 4,))
