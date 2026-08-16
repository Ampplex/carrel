"""Accounts, and the reason they exist at all.

The namespace is derived from the authenticated account and **the client never
names it**, so a request can only ever reach the memory belonging to whoever is
holding the token. A namespace partitions data inside a Reeve account; it does
not secure it, so the security has to live here.

This used to keep users and sessions in two JSON files, which was the right
call for one laptop and the wrong one for a server. `write_text` is not atomic:
an overlapping write, or a crash between truncate and flush, leaves the file
holding every account on the deployment half-written. Postgres makes a write
either happen or not, and the session foreign key means deleting an account
cannot leave a working token behind — that used to be application code
remembering to do the right thing.

Sign-in is rate limited (see below). What this is still NOT: email verification
or password reset. Those matter for a product with real users and are listed in
the README as missing rather than half-implemented here, because a half-built
auth flow is worse than an obviously minimal one.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import time

from fastapi import Header, HTTPException

from app.db import cursor

# scrypt parameters. n=2**14 keeps a login around a tenth of a second on this
# hardware — slow enough to make guessing expensive, fast enough that signing in
# does not feel broken.
_SCRYPT_N = 2**14
_SCRYPT_R = 8
_SCRYPT_P = 1

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

SESSION_TTL_SECONDS = 60 * 60 * 24 * 30  # a month; this is a notebook, not a bank

# Rate limiting on sign-in.
#
# scrypt makes each guess cost about a tenth of a second, which is a real
# barrier to an offline attack on a stolen hash and no barrier at all to an
# online one: a script can still try tens of thousands of passwords a day
# against a public endpoint, and this endpoint has been public and unprotected
# since the subdomain went live — scanners found it within minutes.
#
# Two limits, because they stop different things. Per-email stops somebody
# grinding one account from many addresses. Per-IP stops one host spraying a
# common password across many accounts, which per-email limits never see.
RATE_WINDOW_SECONDS = 15 * 60
MAX_FAILURES_PER_EMAIL = 10
MAX_FAILURES_PER_IP = 30


class RateLimited(Exception):
    """Too many recent failures. Deliberately not a ValueError: the route has to
    answer 429 rather than 401, or a client cannot tell 'wrong password' from
    'stop asking'."""

    def __init__(self, retry_after: int):
        super().__init__("Too many sign-in attempts. Try again in a few minutes.")
        self.retry_after = retry_after


def _record_failure(email: str, client_ip: str) -> None:
    now = time.time()
    with cursor(commit=True) as cur:
        cur.execute(
            "INSERT INTO login_failures (email, client_ip, at) VALUES (%s, %s, %s)",
            (email, client_ip, now),
        )
        # Swept here rather than by a cron: this table is only ever written on
        # failure, so the write path is the natural place to keep it small.
        cur.execute("DELETE FROM login_failures WHERE at < %s", (now - RATE_WINDOW_SECONDS * 4,))


def _check_rate_limit(email: str, client_ip: str) -> None:
    since = time.time() - RATE_WINDOW_SECONDS
    with cursor() as cur:
        cur.execute(
            "SELECT count(*) AS n FROM login_failures WHERE email = %s AND at > %s",
            (email, since),
        )
        by_email = cur.fetchone()["n"]
        by_ip = 0
        if client_ip:
            cur.execute(
                "SELECT count(*) AS n FROM login_failures WHERE client_ip = %s AND at > %s",
                (client_ip, since),
            )
            by_ip = cur.fetchone()["n"]

    if by_email >= MAX_FAILURES_PER_EMAIL or by_ip >= MAX_FAILURES_PER_IP:
        raise RateLimited(retry_after=RATE_WINDOW_SECONDS)


def _hash(password: str, salt: bytes) -> str:
    return hashlib.scrypt(
        password.encode("utf-8"), salt=salt, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P
    ).hex()


def _namespace_for(email: str) -> str:
    """A stable, opaque namespace per account.

    Hashed rather than derived from the email so the memory store never carries
    a personal identifier in a field that ends up in logs and error messages.
    """
    return "u" + hashlib.sha256(email.lower().encode("utf-8")).hexdigest()[:16]


def set_password(email: str, password: str) -> bool:
    """Replace an account's password, used by the reset flow.

    Every existing session is revoked. If somebody is resetting because their
    account was taken, leaving the intruder's month-long token alive would make
    the reset theatre.
    """
    if len(password or "") < 8:
        raise ValueError("Use at least 8 characters.")

    salt = secrets.token_bytes(16)
    with cursor(commit=True) as cur:
        cur.execute(
            "UPDATE users SET salt = %s, password_hash = %s WHERE email = %s",
            (salt.hex(), _hash(password, salt), email),
        )
        if cur.rowcount == 0:
            return False
        cur.execute("DELETE FROM sessions WHERE email = %s", (email,))
        # A successful reset also clears the lockout: the person proved they can
        # read the inbox, which is stronger evidence than the failures that
        # locked them out in the first place.
        cur.execute("DELETE FROM login_failures WHERE email = %s", (email,))
    return True


def mark_email_verified(email: str) -> bool:
    with cursor(commit=True) as cur:
        cur.execute("UPDATE users SET email_verified = TRUE WHERE email = %s", (email,))
        return cur.rowcount > 0


def account_exists(email: str) -> bool:
    """Whether any account uses this address, password or not.

    Only ever used to decide which email to send — never to shape an HTTP
    response, which must look identical whatever the answer.
    """
    with cursor() as cur:
        cur.execute("SELECT 1 FROM users WHERE email = %s", (email,))
        return cur.fetchone() is not None


def has_password(email: str) -> bool:
    with cursor() as cur:
        cur.execute(
            "SELECT 1 FROM users WHERE email = %s AND password_hash IS NOT NULL", (email,)
        )
        return cur.fetchone() is not None


def _get_user(cur, email: str) -> dict | None:
    cur.execute("SELECT * FROM users WHERE email = %s", (email,))
    return cur.fetchone()


def register(email: str, password: str, name: str = "", terms_version: str = "") -> dict:
    email = (email or "").strip().lower()
    if not _EMAIL_RE.match(email):
        raise ValueError("That does not look like an email address.")
    if len(password or "") < 8:
        raise ValueError("Use at least 8 characters.")

    salt = secrets.token_bytes(16)
    now = time.time()
    with cursor(commit=True) as cur:
        if _get_user(cur, email) is not None:
            raise ValueError("There is already an account with that email.")
        cur.execute(
            """
            INSERT INTO users (email, name, salt, password_hash, namespace,
                               terms_version, terms_accepted_at, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                email,
                (name or "").strip()[:60],
                salt.hex(),
                _hash(password, salt),
                _namespace_for(email),
                # Which wording was on screen when this account was created. The
                # client sends it because the client is what displayed it; the
                # server's own copy may have moved on by the time anyone looks.
                (terms_version or "").strip()[:40],
                now,
                now,
            ),
        )
    return _issue(email)


def login(email: str, password: str, client_ip: str = "") -> dict:
    email = (email or "").strip().lower()

    # Checked before any work is done, including the decoy hash below. A limiter
    # that still spends a tenth of a second per rejected attempt is a denial of
    # service against the server rather than against the attacker.
    _check_rate_limit(email, client_ip)

    with cursor() as cur:
        user = _get_user(cur, email)

    # Same message and comparable work whether or not the account exists, so the
    # response cannot be used to enumerate who has signed up.
    if user is None:
        _hash(password or "", secrets.token_bytes(16))
        _record_failure(email, client_ip)
        raise ValueError("Email or password is wrong.")

    # An account created through Google has no password at all. Saying "that one
    # uses Google" would be friendlier and would also answer "does this person
    # have an account here?" for anyone who asks. The message stays true either
    # way: there is no password, so no password can be right.
    if not user.get("password_hash") or not user.get("salt"):
        _hash(password or "", secrets.token_bytes(16))
        _record_failure(email, client_ip)
        raise ValueError("Email or password is wrong.")

    actual = _hash(password or "", bytes.fromhex(user["salt"]))
    if not hmac.compare_digest(user["password_hash"], actual):
        _record_failure(email, client_ip)
        raise ValueError("Email or password is wrong.")

    return _issue(email)


def sign_in_with_google(
    email: str,
    name: str = "",
    subject: str = "",
    terms_version: str = "",
    picture: str = "",
) -> dict:
    """Find or create the account behind an already-verified Google identity.

    The caller must have verified the token first — this function trusts the
    email it is handed completely, because the namespace is derived from it.
    See app/google_auth.py for what that verification has to include.

    An address that already has a password account is *linked*, not rejected:
    same email, same namespace, same memories, now reachable two ways. Refusing
    would announce that an account exists, which login() is careful never to do.

    The honest caveat: Carrel does not verify the email addresses used at
    registration, so somebody could sign up with an address they do not own and
    a later Google sign-in by the real owner would join that account rather than
    a fresh one. Verifying addresses at registration is the fix, and it is listed
    as missing rather than half-built.
    """
    email = (email or "").strip().lower()
    if not _EMAIL_RE.match(email):
        raise ValueError("That Google account has no usable email address.")

    now = time.time()
    with cursor(commit=True) as cur:
        # Does this address already carry a password nobody ever proved they own?
        #
        # Carrel does not verify addresses at registration, so anybody can sign
        # up as anybody. Google has just proved ownership of this address; the
        # password holder never did. So the password loses: it is cleared and
        # every existing session is revoked, which evicts whoever set it.
        #
        # Without this, somebody could register with an address they do not own
        # and wait. The real owner's first Google sign-in would join that same
        # account — same email, same namespace — handing the impostor a live
        # password to it, and to everything written into it afterwards.
        #
        # The cost falls on honest users too: set a password, sign in with
        # Google once, and the password stops working. Google still signs you
        # in, which is the trade — an inconvenience in the honest case against a
        # silent takeover in the dishonest one. Verifying addresses at
        # registration removes the trade entirely, and needs a mail sender this
        # deployment does not have.
        cur.execute(
            "SELECT 1 FROM users WHERE email = %s AND password_hash IS NOT NULL",
            (email,),
        )
        password_revoked = cur.fetchone() is not None
        if password_revoked:
            cur.execute(
                "UPDATE users SET salt = NULL, password_hash = NULL WHERE email = %s",
                (email,),
            )
            cur.execute("DELETE FROM sessions WHERE email = %s", (email,))

        cur.execute(
            """
            INSERT INTO users (email, name, namespace, google_sub, avatar_url,
                               terms_version, terms_accepted_at, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (email) DO UPDATE SET
                google_sub = COALESCE(NULLIF(EXCLUDED.google_sub, ''), users.google_sub),
                -- Refreshed every sign-in: people change their Google photo,
                -- and a stale one is worse than none.
                avatar_url = COALESCE(NULLIF(EXCLUDED.avatar_url, ''), users.avatar_url),
                -- Only fills a gap; never overwrites a name chosen here.
                name = CASE WHEN users.name = '' THEN EXCLUDED.name ELSE users.name END
            """,
            (
                email,
                (name or "").strip()[:60],
                _namespace_for(email),
                subject,
                picture,
                (terms_version or "").strip()[:40],
                now,
                now,
            ),
        )

    session = _issue(email)
    # Reported so the client can explain why a password stopped working. A
    # password that silently stops working reads as a bug, and arrives as a
    # support message rather than as the security measure it is.
    session["password_revoked"] = password_revoked
    return session


def _issue(email: str) -> dict:
    token = secrets.token_urlsafe(32)
    now = time.time()
    with cursor(commit=True) as cur:
        # Opportunistic sweep: expired tokens are useless and this is the only
        # moment the table is already being written to.
        cur.execute("DELETE FROM sessions WHERE created_at < %s", (now - SESSION_TTL_SECONDS,))
        cur.execute(
            "INSERT INTO sessions (token, email, created_at) VALUES (%s, %s, %s)",
            (token, email, now),
        )
        user = _get_user(cur, email)
    return {
        "token": token,
        "email": email,
        "name": user.get("name", ""),
        "namespace": user["namespace"],
        "avatar_url": user.get("avatar_url", ""),
    }


def logout(token: str) -> None:
    if not token:
        return
    with cursor(commit=True) as cur:
        cur.execute("DELETE FROM sessions WHERE token = %s", (token,))


def delete_account(email: str) -> bool:
    """Remove the login. Sessions go with it, by the foreign key rather than by
    remembering to delete them — a token issued minutes ago must not outlive the
    account it belongs to."""
    email = (email or "").strip().lower()
    with cursor(commit=True) as cur:
        cur.execute("DELETE FROM users WHERE email = %s", (email,))
        return cur.rowcount > 0


def resolve(token: str) -> dict | None:
    """Token → account, or None if unknown or expired."""
    if not token:
        return None
    with cursor(commit=True) as cur:
        cur.execute(
            """
            SELECT s.created_at AS session_created, u.*
            FROM sessions s JOIN users u ON u.email = s.email
            WHERE s.token = %s
            """,
            (token,),
        )
        row = cur.fetchone()
        if row is None:
            return None
        if time.time() - row["session_created"] >= SESSION_TTL_SECONDS:
            cur.execute("DELETE FROM sessions WHERE token = %s", (token,))
            return None
    return {
        "email": row["email"],
        "name": row.get("name", ""),
        "namespace": row["namespace"],
        "avatar_url": row.get("avatar_url", ""),
    }


def current_user(authorization: str = Header(default="")) -> dict:
    """FastAPI dependency. Every memory route depends on this.

    It returns the namespace, and routes pass that to the gateway — which is why
    no endpoint accepts a namespace in its body. The only way to reach a memory
    is to hold the token for the account that owns it.
    """
    token = ""
    if authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()

    user = resolve(token)
    if user is None:
        raise HTTPException(status_code=401, detail="Sign in to continue.")
    return user
