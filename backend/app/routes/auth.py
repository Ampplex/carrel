"""Sign up, sign in, sign out.

Thin by design — the thinking is in `app/auth.py`. The one thing worth noticing
here is what the responses do NOT contain: no namespace is ever echoed back to
the client, because a client that knows its namespace is one step from trying
someone else's.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field

from app import auth, google_auth

router = APIRouter()


class Credentials(BaseModel):
    email: str = Field(min_length=3, max_length=200)
    password: str = Field(min_length=1, max_length=200)
    name: str = ""
    # Sent by the sign-up form, ignored on sign-in. Optional so a client that
    # predates the field can still register rather than being turned away.
    terms_version: str = Field(default="", max_length=40)


class Session(BaseModel):
    token: str
    email: str
    name: str
    # True when a Google sign-in cleared a password that had been set on this
    # address. The client says so, because a password that stops working
    # without explanation reads as a bug and generates a support message.
    password_revoked: bool = False
    # Google-hosted, empty for password accounts. The client renders it; the
    # server never fetches or stores the image itself.
    avatar_url: str = ""


@router.post("/api/auth/register", response_model=Session)
def register(payload: Credentials) -> Session:
    try:
        result = auth.register(
            payload.email, payload.password, payload.name, payload.terms_version
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return Session(
        token=result["token"],
        email=result["email"],
        name=result["name"],
        avatar_url=result.get("avatar_url", ""),
    )


def _client_ip(request: Request) -> str:
    """The caller's address, as far as it can be trusted.

    nginx sets X-Forwarded-For and is the only thing that can reach this app —
    the container publishes on 127.0.0.1 and the firewall allows 22/80/443 — so
    the left-most entry is what nginx saw. If this app were ever exposed
    directly, the header would be attacker-controlled and this would have to
    stop trusting it.
    """
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()[:45]
    return request.client.host if request.client else ""


@router.post("/api/auth/login", response_model=Session)
def login(payload: Credentials, request: Request) -> Session:
    try:
        result = auth.login(payload.email, payload.password, _client_ip(request))
    except auth.RateLimited as exc:
        # 429, not 401. A client that cannot tell "wrong password" from "stop
        # asking" will keep asking, and a person who cannot tell will keep
        # retyping a password that was right all along.
        raise HTTPException(
            status_code=429,
            detail=str(exc),
            headers={"Retry-After": str(exc.retry_after)},
        ) from exc
    except ValueError as exc:
        # 401 rather than 400: the credentials were well-formed and rejected.
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    return Session(
        token=result["token"],
        email=result["email"],
        name=result["name"],
        avatar_url=result.get("avatar_url", ""),
    )


class GoogleIn(BaseModel):
    # An ID token, not an access token. app/google_auth.py explains why the
    # difference is the entire security argument rather than a detail.
    id_token: str = Field(min_length=1, max_length=8192)
    terms_version: str = Field(default="", max_length=40)


@router.post("/api/auth/google", response_model=Session)
def google_sign_in(payload: GoogleIn) -> Session:
    """Exchange a verified Google ID token for a Carrel session."""
    try:
        identity = google_auth.verify(payload.id_token)
    except google_auth.GoogleNotConfigured as exc:
        # 503, not 401: nothing is wrong with the token or the person holding
        # it — the server simply has not been given any client IDs to check it
        # against, and the app should say so rather than "sign-in failed".
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except google_auth.GoogleAuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc

    try:
        result = auth.sign_in_with_google(
            identity.email,
            identity.name,
            identity.subject,
            payload.terms_version,
            identity.picture,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return Session(
        token=result["token"],
        email=result["email"],
        name=result["name"],
        avatar_url=result.get("avatar_url", ""),
        password_revoked=result.get("password_revoked", False),
    )


@router.post("/api/auth/logout")
def logout(authorization: str = Header(default="")) -> dict:
    if authorization.lower().startswith("bearer "):
        auth.logout(authorization[7:].strip())
    # Always 200: signing out of an already-dead session is not an error.
    return {"ok": True}


@router.get("/api/auth/me", response_model=Session)
def me(user: dict = Depends(auth.current_user)) -> Session:
    """Used on app launch to decide between the sign-in screen and the chat."""
    return Session(
        token="", email=user["email"], name=user["name"], avatar_url=user.get("avatar_url", "")
    )
