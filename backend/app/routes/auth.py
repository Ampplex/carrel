"""Sign up, sign in, sign out.

Thin by design — the thinking is in `app/auth.py`. The one thing worth noticing
here is what the responses do NOT contain: no namespace is ever echoed back to
the client, because a client that knows its namespace is one step from trying
someone else's.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field

from app import auth

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


@router.post("/api/auth/register", response_model=Session)
def register(payload: Credentials) -> Session:
    try:
        result = auth.register(
            payload.email, payload.password, payload.name, payload.terms_version
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return Session(token=result["token"], email=result["email"], name=result["name"])


@router.post("/api/auth/login", response_model=Session)
def login(payload: Credentials) -> Session:
    try:
        result = auth.login(payload.email, payload.password)
    except ValueError as exc:
        # 401 rather than 400: the credentials were well-formed and rejected.
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    return Session(token=result["token"], email=result["email"], name=result["name"])


@router.post("/api/auth/logout")
def logout(authorization: str = Header(default="")) -> dict:
    if authorization.lower().startswith("bearer "):
        auth.logout(authorization[7:].strip())
    # Always 200: signing out of an already-dead session is not an error.
    return {"ok": True}


@router.get("/api/auth/me", response_model=Session)
def me(user: dict = Depends(auth.current_user)) -> Session:
    """Used on app launch to decide between the sign-in screen and the chat."""
    return Session(token="", email=user["email"], name=user["name"])
