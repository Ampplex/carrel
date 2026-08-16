"""The only module in this project that imports `reeve`.

Every function takes an explicit `namespace`, and that is the whole security
model. The hosted server composes identity as `uid:namespace`: the `uid` comes
from the API key and cannot be forged, but the namespace half is whatever the
caller passes. So the namespace is a partition, not a boundary — which means the
boundary has to be enforced here, by only ever passing a namespace that came
from `auth.current_user` and never from a request body.

There is deliberately no default value on any namespace parameter. A default is
exactly the kind of convenience that later turns into "this one endpoint forgot
to pass it and quietly read someone else's memory".

Two calls also reach past the published SDK surface: `query_memory` and
`search_image_memories` accept `image_path`/`image_url` but not `image_base64`,
while the MCP tools underneath accept all three. A web backend holds uploaded
bytes in memory, so the published signature would force a temp file just to have
the SDK read it back. Both uses are confined to this file, which is why `reeve`
is pinned `>=0.1.41,<0.2`.
"""

from __future__ import annotations

# Imported first, on purpose: this loads .env before `reeve` snapshots the key.
from app.config import settings

settings.require_api_key()

import logging  # noqa: E402
from typing import Any  # noqa: E402

from reeve.tools import (  # noqa: E402
    _get_client,
    memory_config,
    query_memory,
    retrieve_memory_context,
    search_image_memories,
    store_memory,
)

log = logging.getLogger("carrel.reeve")


def _is_dead_session(exc: BaseException) -> bool:
    """Did this fail because our SSE session no longer exists on the server?

    Reeve's transport keeps a long-lived SSE session and posts each call to
    /messages/?session_id=... . When the server restarts — a deploy, a reboot —
    every session it knew about is gone, and that URL starts answering 404. The
    SDK reconnects when a session expires from *idleness*, but a server that
    went away underneath a perfectly healthy session is a different case, and it
    left this app returning "Reeve returned an error" to every request until
    somebody restarted it by hand.
    """
    response = getattr(exc, "response", None)
    return getattr(response, "status_code", None) == 404


def _reconnect() -> None:
    """Drop the cached client so the next call performs a fresh handshake.

    `reset_client_cache` is the SDK's own supported way to do this — it closes
    each cached client and empties the cache, and exists for "tests and identity
    switches". A dead session is the same need: throw away the connection and
    let the next call build a new one.
    """
    from reeve.tools import reset_client_cache

    reset_client_cache()


def _retrying(call, *args, **kwargs):
    """Run a Reeve call, re-handshaking once if the session turned out to be dead.

    Exactly one retry. If the second attempt fails the same way, the problem is
    not a stale session and pretending otherwise would turn a clear error into a
    slow one.
    """
    try:
        return call(*args, **kwargs)
    except Exception as exc:  # noqa: BLE001 - the SDK raises requests' HTTPError
        if not _is_dead_session(exc):
            raise
        log.info("reeve session was gone (404); reconnecting and retrying once")
        _reconnect()
        return call(*args, **kwargs)


def _call_tool(name: str, arguments: dict[str, Any]) -> Any:
    return _retrying(lambda: _get_client().call_tool(name, arguments))


# ── Writes (free — they do not count against the query quota) ────────────────


def store_note(text: str, namespace: str) -> dict[str, Any]:
    """Store a text memory. Returns immediately with a pending pointer."""
    return _retrying(store_memory, text, speaker=namespace)


def store_photo(caption: str, image_base64: str, media_type: str, namespace: str) -> dict[str, Any]:
    """Store a photo and its caption as ONE memory.

    Reeve fuses the caption with a vision-model description of the image, embeds
    the pair, and retains the original — which is what makes it possible to ask
    a question later that nobody anticipated when the caption was written.
    """
    return _retrying(
        store_memory,
        caption,
        speaker=namespace,
        image_base64=image_base64,
        image_media_type=media_type,
    )


# ── Reads (each of these costs one query against the monthly quota) ──────────


def ask(question: str, namespace: str) -> str:
    """Narrated answer."""
    return _retrying(query_memory, question, speaker=namespace)


def context(question: str, namespace: str) -> str:
    """Raw ranked context — the layer that owns retrieval truth.

    Where the `(superseded)` markers and the pending-write block live, so it is
    the evidence the UI shows when a claim needs proving.
    """
    return _retrying(retrieve_memory_context, question, speaker=namespace)


def ask_with_photo(question: str, image_base64: str, media_type: str, namespace: str) -> str:
    """Ask with a photo attached — reaches the vision model deterministically
    rather than waiting for the image lane to select the photo on its own."""
    return _call_tool(
        "query_memory",
        {
            "question": question,
            "speaker": namespace,
            "image_base64": image_base64,
            "image_media_type": media_type,
        },
    )


def search_photos(query: str, namespace: str) -> str:
    """Text-to-image search. Bypasses the image lane's admission gate."""
    return _retrying(search_image_memories, query=query, speaker=namespace)


def search_photos_by_image(image_base64: str, media_type: str, namespace: str) -> str:
    """Image-to-image: find the stored photo that looks like this one."""
    return _call_tool(
        "search_image_memories",
        {
            "query": "",
            "speaker": namespace,
            "image_base64": image_base64,
            "image_media_type": media_type,
        },
    )


# ── Operational ───────────────────────────────────────────────────────────────


def config() -> dict[str, Any]:
    """Live capability report — account-wide, so it takes no namespace."""
    return _retrying(memory_config)


def warm() -> dict[str, Any]:
    """Force the SSE handshake during startup rather than on a user's request.

    `_ensure_connected` guards on a plain boolean with no lock, so two
    simultaneous cold requests can each spawn a listener thread. Connecting once
    in the app's lifespan sidesteps that and keeps the handshake latency out of
    the first answer.
    """
    return _retrying(memory_config)


def erase(namespace: str) -> dict[str, Any]:
    """Delete one account's memories.

    Deliberately not behind CARREL_ALLOW_RESET. That flag guards the operator's
    blunt reset tool; this is a person deleting their own data, which the
    product owes them and must not depend on a server setting being switched on.
    Authorisation is the token — the namespace comes from the session and can
    never be supplied by a client.

    Broader than it sounds: this also cancels the account's queued writes and
    sweeps the photos Reeve retained, so nothing lands after the erase and
    resurrects what was just removed.
    """
    return _call_tool("clear_memory", {"speaker": namespace, "dry_run": False})


def reset(namespace: str, confirm: str) -> dict[str, Any]:
    """Wipe one account's memory. Irreversible.

    Deliberately awkward to reach: `reeve.tools` exposes no `clear_memory`, and
    this also cancels queued writes and sweeps retained photos.
    """
    if not settings.allow_reset:
        raise PermissionError("Reset is disabled. Set Carrel_ALLOW_RESET=true to enable it.")
    if confirm != "DELETE MY MEMORY":
        raise ValueError("Confirmation must be exactly: DELETE MY MEMORY")
    return _call_tool("clear_memory", {"speaker": namespace, "dry_run": False})
