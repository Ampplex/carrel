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
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel, Field

from app import auth, bounces, deliverability, email_tokens, mailer
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
        # Says what was done, and what to do when nothing arrives. Whether a
        # mailbox exists cannot be checked before sending, so the message must
        # not promise delivery it cannot know about.
        "message": (
            "If that address can receive mail, we have sent it something. "
            "Nothing after a few minutes usually means a typo — check the "
            "spelling and try again."
        ),
    }

    # Input validation, not account lookup. Whether a domain has a mail server
    # is public — anybody can run the same query — so saying so leaks nothing
    # about who has an account here. And the alternative is worse than a leak:
    # the neutral "check your email" was being shown to somebody who had
    # mistyped their own domain, and no message was ever coming, because there
    # was nowhere to send one. A typo is the most common reason to end up here.
    if not deliverability.looks_like_an_address(email):
        raise HTTPException(status_code=400, detail="That does not look like an email address.")
    if not deliverability.domain_can_receive_mail(email):
        domain = email.rpartition("@")[2]
        raise HTTPException(
            status_code=400,
            detail=f"No mail server found for {domain}. Check the spelling and try again.",
        )

    # The provider told us this one is dead, after some earlier attempt. That is
    # deliverability, not account state — the same category as a domain with no
    # mail server — so it can be said plainly.
    if bounces.has_bounced(email):
        raise HTTPException(
            status_code=400,
            detail=(
                "Mail to that address bounced last time. Check the spelling, "
                "or use a different address."
            ),
        )

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
            # Deliverability was already established above, so this cannot turn
            # into a hard bounce.
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


# The reset URL carries a live credential in its query string. Any request the
# page makes to another origin would put that URL in a Referer header, so the
# page loads nothing external — and says so to the browser as well, which also
# covers a link somebody clicks from the page.
_NO_REFERRER = {"Referrer-Policy": "no-referrer", "Cache-Control": "no-store"}


def _page(title: str, body: str) -> HTMLResponse:
    return HTMLResponse(
        content=f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="referrer" content="no-referrer">
<title>{escape(title)} · Carrel</title><style>{_PAGE_STYLE}</style></head>
<body><h1>{escape(title)}</h1>{body}</body></html>""",
        headers=_NO_REFERRER,
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

    # And say so, in a second email. If somebody else reset this password, this
    # is how the owner finds out while it is still worth acting on. It is also
    # the only message in this flow that carries no link and no token, so it is
    # safe to forward to anyone helping them.
    try:
        mailer.send(
            email,
            "Your Carrel password was changed",
            text=(
                "The password for this Carrel account was just changed, and every "
                "signed-in device was signed out.\n\n"
                "If that was you, there is nothing to do.\n\n"
                "If it was not, somebody has access to this inbox — change its "
                "password first, then reset your Carrel password again.\n"
            ),
        )
    except Exception as exc:  # noqa: BLE001 - the reset already succeeded
        log.warning("could not send the password-changed notice to %s: %s", email, exc)

    # Redirect rather than render. The token is in the POST body, but a browser
    # that renders this response keeps the form's URL in history and in the back
    # button; sending the browser to a clean URL means the spent token stops
    # travelling around. It also makes refresh harmless.
    return RedirectResponse("/reset/done", status_code=303)


@router.get("/reset/done", response_class=HTMLResponse)
def reset_done() -> HTMLResponse:
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


@router.post("/api/hooks/brevo/{secret}")
async def brevo_webhook(secret: str, request: Request) -> dict:
    """Where the mail provider reports what happened to a message.

    Authenticated by a secret in the path, because Brevo's webhooks carry no
    signature. It is a bearer credential in a URL, which is not lovely — but the
    endpoint only accepts event reports about addresses, and the alternative is
    an open endpoint anybody can use to mark somebody else's address dead.

    Unknown or transient events are ignored on purpose. A full mailbox says
    nothing lasting about an address, and refusing it forever on one bad day
    would be worse than the silence this is fixing.
    """
    if not settings.brevo_webhook_secret or secret != settings.brevo_webhook_secret:
        # 404, not 403: an endpoint that admits it exists invites guessing.
        raise HTTPException(status_code=404, detail="Not found.")

    try:
        payload = await request.json()
    except Exception:  # noqa: BLE001 - a malformed body is not our problem
        return {"ok": True}

    event = str(payload.get("event", "")).lower()
    email = str(payload.get("email", "")).strip().lower()
    if not email:
        return {"ok": True}

    if event in bounces.PERMANENT_EVENTS:
        bounces.record(email, reason=event)
    elif event in ("delivered", "request"):
        # It arrived. Whatever went wrong before has stopped being true.
        bounces.clear(email)

    return {"ok": True}
