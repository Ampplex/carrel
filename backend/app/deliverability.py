"""Is this address worth sending to at all?

Carrel sends a reply to every forgot-password request, including addresses with
no account — otherwise somebody who mistyped their own address waits forever for
a message that was never coming. The cost of that choice is that garbage
addresses become **hard bounces**, and a sender with a high bounce rate gets
throttled or suspended by its provider. That penalty lands on the reset emails
that matter, so it is worth a DNS lookup to avoid.

Two checks, cheapest first:

  * **Syntax.** `not-an-email` reached the provider and came back 400, logging
    an error for what was only ever a typo.
  * **Domain.** An address whose domain has no MX and no A record cannot
    receive mail from anyone. Sending to it is a guaranteed bounce.

Deliberately NOT done: verifying the mailbox exists. That needs SMTP probing,
which is slow, widely blocked, treated as abuse by most providers, and — since
it distinguishes real addresses from fake ones — is itself an enumeration tool.

This never blocks a reset for a real account. It only decides whether to send
the courtesy "no account here" message to an address that has none.
"""

from __future__ import annotations

import logging
import re
import socket

log = logging.getLogger("carrel.deliverability")

# Deliberately permissive. Email syntax is far stranger than most patterns
# allow, and rejecting a valid-but-unusual address is worse than passing a
# doomed one to the provider — this is a courtesy check, not a gate.
_SYNTAX = re.compile(r"^[^@\s]+@[^@\s.]+(\.[^@\s.]+)+$")

_DNS_TIMEOUT_SECONDS = 3


def looks_like_an_address(email: str) -> bool:
    return bool(_SYNTAX.match((email or "").strip()))


def domain_can_receive_mail(email: str) -> bool:
    """Whether the domain resolves at all.

    Uses getaddrinfo rather than a real MX lookup: it needs no new dependency
    and catches the case that actually occurs — a mistyped or invented domain.
    A domain with an MX record but no A record would be judged wrongly here,
    which is rare, and the cost is one unsent courtesy email rather than a
    failed password reset.
    """
    domain = (email or "").rpartition("@")[2].strip().lower()
    if not domain:
        return False

    original = socket.getdefaulttimeout()
    try:
        socket.setdefaulttimeout(_DNS_TIMEOUT_SECONDS)
        socket.getaddrinfo(domain, None)
        return True
    except (socket.gaierror, socket.timeout, UnicodeError, ValueError):
        log.info("not sending to %s: domain does not resolve", domain)
        return False
    except OSError as exc:  # pragma: no cover - depends on the resolver
        # A resolver failure is not evidence the domain is bad. Assume it is
        # fine: a bounce costs reputation, but refusing to send to a real
        # address because DNS hiccuped costs somebody their account.
        log.warning("dns lookup failed for %s (%s); sending anyway", domain, exc)
        return True
    finally:
        socket.setdefaulttimeout(original)


def worth_sending_to(email: str) -> bool:
    return looks_like_an_address(email) and domain_can_receive_mail(email)
