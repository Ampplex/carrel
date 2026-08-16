"""Addresses the mail provider could not deliver to.

Whether a mailbox exists is unknowable at request time. `gmail.com` resolves,
so a typo in the part before the @ passes every check available synchronously —
the message is accepted, attempted, and rejected by Gmail seconds later. The
person who mistyped their own address sees "check your email" and waits for
something that will never arrive.

The provider tells us, just too late to answer the request that caused it. So
the answer is remembered instead: the first attempt on a dead address is silent,
and every attempt after it says so plainly.

This is deliverability, not account state. "That address bounced" reveals
nothing about who has an account — the same reasoning that allows saying a
domain has no mail server.
"""

from __future__ import annotations

import logging
import time

from app.db import cursor

log = logging.getLogger("carrel.bounces")

# What Brevo calls the events that mean "this address is dead", as opposed to a
# full mailbox or a transient failure, which say nothing lasting about it.
PERMANENT_EVENTS = {"hard_bounce", "invalid_email", "blocked", "unsubscribed", "spam"}


def record(email: str, reason: str = "") -> None:
    email = (email or "").strip().lower()
    if not email:
        return
    with cursor(commit=True) as cur:
        cur.execute(
            """
            INSERT INTO bounced_addresses (email, reason, bounced_at)
            VALUES (%s, %s, %s)
            ON CONFLICT (email) DO UPDATE SET reason = EXCLUDED.reason,
                                              bounced_at = EXCLUDED.bounced_at
            """,
            (email, reason[:200], time.time()),
        )
    log.info("recorded bounce for %s (%s)", email, reason or "no reason given")


def clear(email: str) -> None:
    """Forget a bounce.

    Called when an address successfully receives something again — a mailbox
    that was full, or a domain that was briefly misconfigured, should not be
    refused forever on the strength of one bad day.
    """
    with cursor(commit=True) as cur:
        cur.execute("DELETE FROM bounced_addresses WHERE email = %s", ((email or "").lower(),))


def has_bounced(email: str) -> bool:
    with cursor() as cur:
        cur.execute(
            "SELECT 1 FROM bounced_addresses WHERE email = %s", ((email or "").strip().lower(),)
        )
        return cur.fetchone() is not None
