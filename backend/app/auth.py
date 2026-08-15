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

What this is still NOT: email verification, password reset, or rate limiting on
login. Those matter for a product with real users and are listed in the README
as missing rather than half-implemented here, because a half-built auth flow is
worse than an obviously minimal one.
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


def login(email: str, password: str) -> dict:
    email = (email or "").strip().lower()
    with cursor() as cur:
        user = _get_user(cur, email)

    # Same message and comparable work whether or not the account exists, so the
    # response cannot be used to enumerate who has signed up.
    if user is None:
        _hash(password or "", secrets.token_bytes(16))
        raise ValueError("Email or password is wrong.")

    # An account created through Google has no password at all. Saying "that one
    # uses Google" would be friendlier and would also answer "does this person
    # have an account here?" for anyone who asks. The message stays true either
    # way: there is no password, so no password can be right.
    if not user.get("password_hash") or not user.get("salt"):
        _hash(password or "", secrets.token_bytes(16))
        raise ValueError("Email or password is wrong.")

    actual = _hash(password or "", bytes.fromhex(user["salt"]))
    if not hmac.compare_digest(user["password_hash"], actual):
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
    return _issue(email)


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
