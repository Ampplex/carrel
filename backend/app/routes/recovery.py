"""Password reset and email verification.

The reset happens in a **browser**, on a page this server renders, rather than
through a deep link back into the app. That is the whole design decision here.
A deep link needs a scheme the app claims, an app installed on the device that
opened the mail, and a route inside it that handles the token — three things
that go wrong independently, on a phone, while somebody is locked out and
frustrated. A web page works from any device with any mail client.

Two rules run through every endpoint below.

**The forgot endpoint never says whether an account exists.** It answers the
same way for a real address, an unknown one, and a Google-only account. Anything
else turns "I forgot my password" into a way to ask "does this person have an
account here?" — which is exactly what login() is careful not to answer.

**A token is spent when it is used, not when the page is shown.** Rendering the
form on GET must not consume it, or a mail client's link preview would burn the
reset before the person ever saw the box.
"""

from __future__ import annotations

import logging
from html import escape

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from app import auth, email_tokens, mailer
from app.config import settings

router = APIRouter()
log = logging.getLogger("carrel.recovery")


class ForgotIn(BaseModel):
    email: str = Field(min_length=3, max_length=254)


def _send_reset(email: str) -> None:
    token = email_tokens.issue(email, email_tokens.RESET)
    link = f"{settings.public_base_url}/reset?token={token}"
    mailer.send(
        email,
        "Reset your Carrel password",
        text=(
            "Somebody asked to reset the password for this Carrel account.\n\n"
            f"{link}\n\n"
            "The link works once and expires in an hour. If this was not you, "
            "ignore this email — nothing has changed, and your password still works.\n"
        ),
        html=(
            "<p>Somebody asked to reset the password for this Carrel account.</p>"
            f'<p><a href="{escape(link)}">Choose a new password</a></p>'
            "<p>The link works once and expires in an hour. If this was not you, "
            "ignore this email — nothing has changed, and your password still works.</p>"
        ),
    )


@router.post("/api/auth/forgot")
def forgot(payload: ForgotIn, request: Request) -> dict:
    """Ask for a reset link. Always answers the same, whatever is true."""
    email = payload.email.strip().lower()
    same_answer = {
        "ok": True,
        "message": "If there is an account with that address, a reset link is on its way.",
    }

    if not mailer.configured():
        # Honest rather than silently pretending. Telling somebody to check an
        # inbox that will never receive anything is the worst of both worlds.
        raise HTTPException(
            status_code=503,
            detail="Password reset is not available on this deployment yet.",
        )

    # Throttled on its own counter, NOT the sign-in one. Sharing them meant a
    # person locked out by wrong passwords could not ask for a reset, which is
    # backwards: they are exactly who the reset exists for.
    client_ip = _client_ip(request)
    try:
        email_tokens.check_mail_quota(email, client_ip)
    except email_tokens.TooManyRequests as exc:
        raise HTTPException(
            status_code=429, detail=str(exc), headers={"Retry-After": str(exc.retry_after)}
        ) from exc
    email_tokens.record_mail_request(email, client_ip)

    # Something is always sent, and only the content differs. The HTTP response
    # stays identical either way, so the endpoint still reveals nothing — but
    # nobody is left staring at an inbox that will never receive anything.
    #
    # The case that forced this: an account created through Google has no
    # password, so the old version sent nothing and said "check your email".
    # Someone who had forgotten they used Google would wait forever for a
    # message that was never coming.
    #
    # Only the person who can read the inbox learns which case they are in,
    # which is the property worth protecting. The mail quota check above bounds
    # the cost at five per address an hour, so this cannot be used to flood
    # somebody or burn the sending allowance.
    try:
        if auth.has_password(email):
            _send_reset(email)
        elif auth.account_exists(email):
            _send_google_only_notice(email)
        else:
            _send_no_account_notice(email)
    except mailer.MailFailed as exc:
        # Logged, not surfaced. The failure is ours, and the response must stay
        # identical in every case.
        log.error("reset email failed for %s: %s", email, exc)

    return same_answer


def _send_google_only_notice(email: str) -> None:
    """For an account that only ever signs in with Google.

    There is no password to reset, and saying so in the HTTP response would
    confirm the address is registered. Saying it in the inbox tells only the
    person who owns it.
    """
    mailer.send(
        email,
        "Your Carrel account uses Google sign-in",
        text=(
            "Somebody asked to reset the password for this Carrel account.\n\n"
            "This account has no password — it signs in with Google. Open Carrel "
            'and tap "Continue with Google" instead.\n\n'
            "If this was not you, nothing has changed and there is nothing to do.\n"
        ),
        html=(
            "<p>Somebody asked to reset the password for this Carrel account.</p>"
            "<p>This account has no password — it signs in with Google. Open Carrel "
            'and tap <strong>Continue with Google</strong> instead.</p>'
            "<p>If this was not you, nothing has changed and there is nothing to do.</p>"
        ),
    )


def _send_no_account_notice(email: str) -> None:
    """For an address with no account at all.

    Worth sending rather than staying silent: somebody who mistyped their
    address, or used a different one to sign up, otherwise waits for a message
    that is never coming and concludes the app is broken.
    """
    mailer.send(
        email,
        "No Carrel account for this address",
        text=(
            "Somebody asked to reset a Carrel password for this email address, "
            "but there is no Carrel account here.\n\n"
            "If that was you, check whether you signed up with a different "
            "address — or create an account in the app.\n\n"
            "If it was not you, you can ignore this. Nothing has been created "
            "or changed.\n"
        ),
    )

def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()[:45]
    return request.client.host if request.client else ""


_PAGE_STYLE = """
:root { color-scheme: light dark; }
body { margin:0 auto; padding:3rem 1.25rem; max-width:26rem;
  font:16px/1.6 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  background:#fff; color:#1a1c1a; }
@media (prefers-color-scheme: dark) { body { background:#0f110f; color:#e8eae8; }
  input { background:#1a1c1a; color:#e8eae8; border-color:#2c302c; } }
h1 { font-size:1.5rem; margin:0 0 1.5rem; }
label { display:block; font-size:.875rem; margin-bottom:.35rem; }
input { width:100%; padding:.7rem .8rem; font-size:1rem; border-radius:.5rem;
  border:1px solid #d5dad5; box-sizing:border-box; margin-bottom:1rem; }
button { width:100%; padding:.75rem; font-size:1rem; font-weight:600; border:0;
  border-radius:999px; background:#1f7a53; color:#fff; cursor:pointer; }
.note { font-size:.875rem; color:#6b706b; margin-top:1.5rem; }
.bad { color:#b3261e; }
"""


def _page(title: str, body: str) -> HTMLResponse:
    return HTMLResponse(
        f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(title)} · Carrel</title><style>{_PAGE_STYLE}</style></head>
<body><h1>{escape(title)}</h1>{body}</body></html>"""
    )


def _reset_form_page(token: str, error: str = "") -> HTMLResponse:
    """The form, optionally carrying an error from a rejected attempt.

    The token is passed straight back through, unspent, so a typo costs a
    retry rather than a whole new email.
    """
    problem = f"<p class='bad'>{escape(error)}</p>" if error else ""
    return _page(
        "Choose a new password",
        f"""{problem}<form method="post" action="/reset">
<input type="hidden" name="token" value="{escape(token)}">
<label for="password">New password</label>
<input id="password" name="password" type="password" minlength="8" required
       autocomplete="new-password" placeholder="At least 8 characters">
<label for="confirm">Confirm new password</label>
<input id="confirm" name="confirm" type="password" minlength="8" required
       autocomplete="new-password" placeholder="Type it again">
<button type="submit">Set password</button>
</form>
<p class="note">This link works once and expires an hour after it was sent.
Setting a new password signs out every device.</p>""",
    )


@router.get("/reset", response_class=HTMLResponse)
def reset_form(token: str = "") -> HTMLResponse:
    """The form. Deliberately does NOT spend the token — see the module docstring."""
    if not token:
        return _page("Link not valid", "<p class='bad'>That link is missing its token.</p>")
    return _reset_form_page(token)


@router.post("/reset", response_class=HTMLResponse)
def reset_submit(
    token: str = Form(""), password: str = Form(""), confirm: str = Form("")
) -> HTMLResponse:
    # Everything that can be judged without the token is judged first, and the
    # form comes back with the token intact. Spending it on a mistyped password
    # would mean a typo costs another email — and worse, the earlier version
    # could leave somebody holding an account whose password they had just
    # mistyped twice and could no longer change.
    if len(password) < 8:
        return _reset_form_page(token, "Use at least 8 characters.")
    if password != confirm:
        return _reset_form_page(token, "Those two passwords do not match.")

    email = email_tokens.consume(token, email_tokens.RESET)
    if email is None:
        return _page(
            "Link expired",
            "<p class='bad'>That link has already been used or has expired.</p>"
            "<p class='note'>Ask for a new one from the app's sign-in screen.</p>",
        )

    try:
        auth.set_password(email, password)
    except ValueError as exc:
        # Only reachable if the rules here and in auth diverge; the token is
        # spent by this point, so send them for a fresh link rather than to a
        # form that can no longer work.
        return _page(
            "Password not accepted",
            f"<p class='bad'>{escape(str(exc))}</p>"
            "<p class='note'>Ask for a new link and try again.</p>",
        )

    # Reaching here proves the person can read that inbox, which is the same
    # thing verification asks — so record it rather than making them do it twice.
    auth.mark_email_verified(email)

    return _page(
        "Password changed",
        "<p>You can sign in with your new password now.</p>"
        "<p class='note'>Every device that was signed in has been signed out.</p>",
    )


@router.get("/verify", response_class=HTMLResponse)
def verify(token: str = "") -> HTMLResponse:
    email = email_tokens.consume(token, email_tokens.VERIFY)
    if email is None:
        return _page(
            "Link expired",
            "<p class='bad'>That verification link has already been used or has expired.</p>",
        )

    auth.mark_email_verified(email)
    return _page("Email confirmed", "<p>Thanks — this address is confirmed.</p>")
