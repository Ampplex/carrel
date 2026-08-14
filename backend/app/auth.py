"""Accounts, and the reason they exist at all.

Until now the namespace was a server-side constant: one deployment, one memory.
Accounts change that — each person gets their own namespace, and the important
property is that **the client never names it**. It is derived from the
authenticated account, so a request can only ever reach the memory belonging to
whoever is holding the token. A namespace partitions data inside a Reeve
account; it does not secure it, so the security has to live here.

Deliberately small: scrypt from the standard library, users and sessions in two
JSON files. No ORM, no migrations, no third-party auth dependency. This is a
project backend serving one deployment, and a database would be more moving
parts than the problem has.

What this is NOT: a password reset flow, email verification, rate limiting on
login, or refresh-token rotation. Those matter for a product with real users and
are listed in the README as missing rather than half-implemented here, because a
half-built auth flow is worse than an obviously minimal one.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import threading
import time

from fastapi import Header, HTTPException

from app.config import settings

_USERS = settings.var_dir / "users.json"
_SESSIONS = settings.var_dir / "sessions.json"
_lock = threading.Lock()

# scrypt parameters. n=2**14 keeps a login around a tenth of a second on this
# hardware — slow enough to make guessing expensive, fast enough that signing in
# does not feel broken.
_SCRYPT_N = 2**14
_SCRYPT_R = 8
_SCRYPT_P = 1

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

SESSION_TTL_SECONDS = 60 * 60 * 24 * 30  # a month; this is a notebook, not a bank


def _read(path) -> dict:
    if path.exists():
        try:
            return json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def _write(path, data: dict) -> None:
    settings.var_dir.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2))
    try:
        os.chmod(path, 0o600)  # password hashes and live tokens
    except OSError:
        pass


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


def register(email: str, password: str, name: str = "") -> dict:
    email = (email or "").strip().lower()
    if not _EMAIL_RE.match(email):
        raise ValueError("That does not look like an email address.")
    if len(password or "") < 8:
        raise ValueError("Use at least 8 characters.")

    with _lock:
        users = _read(_USERS)
        if email in users:
            raise ValueError("There is already an account with that email.")
        salt = secrets.token_bytes(16)
        users[email] = {
            "name": (name or "").strip()[:60],
            "salt": salt.hex(),
            "hash": _hash(password, salt),
            "namespace": _namespace_for(email),
            "created_at": time.time(),
        }
        _write(_USERS, users)
    return _issue(email)


def login(email: str, password: str) -> dict:
    email = (email or "").strip().lower()
    with _lock:
        users = _read(_USERS)
        user = users.get(email)

    # Same message and comparable work whether or not the account exists, so the
    # response cannot be used to enumerate who has signed up.
    if user is None:
        _hash(password or "", secrets.token_bytes(16))
        raise ValueError("Email or password is wrong.")

    expected = user["hash"]
    actual = _hash(password or "", bytes.fromhex(user["salt"]))
    if not hmac.compare_digest(expected, actual):
        raise ValueError("Email or password is wrong.")

    return _issue(email)


def _issue(email: str) -> dict:
    token = secrets.token_urlsafe(32)
    with _lock:
        sessions = _read(_SESSIONS)
        now = time.time()
        # Opportunistic sweep: expired tokens are useless and this is the only
        # moment the file is already open.
        sessions = {
            t: s for t, s in sessions.items() if now - s.get("created_at", 0) < SESSION_TTL_SECONDS
        }
        sessions[token] = {"email": email, "created_at": now}
        _write(_SESSIONS, sessions)
        users = _read(_USERS)
        user = users[email]
    return {
        "token": token,
        "email": email,
        "name": user.get("name", ""),
        "namespace": user["namespace"],
    }


def logout(token: str) -> None:
    with _lock:
        sessions = _read(_SESSIONS)
        if sessions.pop(token, None) is not None:
            _write(_SESSIONS, sessions)


def delete_account(email: str) -> bool:
    """Remove the login and every session it holds.

    Sessions go too, or a token issued minutes ago would keep working against an
    account that no longer exists.
    """
    email = (email or "").strip().lower()
    with _lock:
        users = _read(_USERS)
        if users.pop(email, None) is None:
            return False
        _write(_USERS, users)

        sessions = _read(_SESSIONS)
        remaining = {t: s for t, s in sessions.items() if s.get("email") != email}
        if len(remaining) != len(sessions):
            _write(_SESSIONS, remaining)
    return True


def resolve(token: str) -> dict | None:
    """Token → account, or None if unknown or expired."""
    if not token:
        return None
    with _lock:
        sessions = _read(_SESSIONS)
        session = sessions.get(token)
        if session is None:
            return None
        if time.time() - session.get("created_at", 0) >= SESSION_TTL_SECONDS:
            sessions.pop(token, None)
            _write(_SESSIONS, sessions)
            return None
        user = _read(_USERS).get(session["email"])
    if user is None:
        return None
    return {
        "email": session["email"],
        "name": user.get("name", ""),
        "namespace": user["namespace"],
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
