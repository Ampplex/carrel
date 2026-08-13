"""The only module in this project that imports `reeve`.

Everything the app knows about Reeve lives behind these functions. Two reasons
that boundary is worth enforcing:

  1. **The namespace is owned here.** The hosted server composes the real
     identity as `uid:namespace`, where `uid` comes from the API key and cannot
     be forged by a client. The namespace half, however, is whatever the caller
     passes — so if an HTTP handler could supply it, any browser could read any
     other namespace in this account. It is a partition, not a security
     boundary. No function here accepts a speaker argument.

  2. **Two calls reach past the public SDK surface** (see `_call_tool` below).
     Keeping them in one file means a future SDK rename breaks exactly one
     module instead of being scattered through the routes.
"""

from __future__ import annotations

# Imported first, on purpose: this loads .env before `reeve` snapshots the key.
from app.config import settings

settings.require_api_key()

from typing import Any  # noqa: E402

from reeve.tools import (  # noqa: E402
    _get_client,
    memory_config,
    query_memory,
    retrieve_memory_context,
    search_image_memories,
    store_memory,
)

NAMESPACE = settings.namespace


# ── Escape hatch ──────────────────────────────────────────────────────────────
# The SDK's `query_memory`, `retrieve_memory_context` and `search_image_memories`
# accept `image_path` and `image_url` but NOT `image_base64` — while the MCP tool
# underneath accepts all three. A web backend holds uploaded bytes in memory, so
# the published signature would force us to write a temp file just to have the
# SDK base64 it straight back. Calling the tool directly avoids that round trip.
# This is a private name; `reeve` is pinned to >=0.1.41,<0.2 because of it.
def _call_tool(name: str, arguments: dict[str, Any]) -> Any:
    return _get_client().call_tool(name, arguments)


# ── Writes (free — they do not count against the query quota) ────────────────


def store_note(text: str) -> dict[str, Any]:
    """Store a text memory. Returns immediately with a pending pointer."""
    return store_memory(text, speaker=NAMESPACE)


def store_photo(caption: str, image_base64: str, media_type: str) -> dict[str, Any]:
    """Store a photo and its caption as ONE memory.

    Reeve fuses the caption with a vision-model description of the image, embeds
    the pair, and retains the original — which is what makes it possible to ask
    a question later that nobody anticipated when the caption was written.
    """
    return store_memory(
        caption,
        speaker=NAMESPACE,
        image_base64=image_base64,
        image_media_type=media_type,
    )


# ── Reads (each of these costs one query against the monthly quota) ──────────


def ask(question: str) -> str:
    """Narrated answer."""
    return query_memory(question, speaker=NAMESPACE)


def context(question: str) -> str:
    """Raw ranked context — the layer that owns retrieval truth.

    This is where `(superseded)` markers and the pending-write block live, so it
    is the evidence the UI shows when a claim needs proving.
    """
    return retrieve_memory_context(question, speaker=NAMESPACE)


def ask_with_photo(question: str, image_base64: str, media_type: str) -> str:
    """Ask a question with a photo attached.

    Attaching the image makes the vision path deterministic: the server routes
    to the vision model directly rather than waiting for the image retrieval
    lane to select the photo on its own.
    """
    return _call_tool(
        "query_memory",
        {
            "question": question,
            "speaker": NAMESPACE,
            "image_base64": image_base64,
            "image_media_type": media_type,
        },
    )


def search_photos(query: str) -> str:
    """Text-to-image search. Bypasses the image lane's admission gate."""
    return search_image_memories(query=query, speaker=NAMESPACE)


def search_photos_by_image(image_base64: str, media_type: str) -> str:
    """Image-to-image search: find the stored photo that looks like this one."""
    return _call_tool(
        "search_image_memories",
        {
            "query": "",
            "speaker": NAMESPACE,
            "image_base64": image_base64,
            "image_media_type": media_type,
        },
    )


# ── Operational ───────────────────────────────────────────────────────────────


def config() -> dict[str, Any]:
    """Live capability report. Drives the UI's capability badges.

    Worth calling on every page load: photo retention and vision are operator
    controlled, so a capability can disappear underneath a running demo. The
    failure mode without this is silent — answers quietly stop being grounded in
    the image and nothing errors.
    """
    return memory_config()


def warm() -> dict[str, Any]:
    """Force the SSE handshake during startup rather than on a user's request.

    `_ensure_connected` guards on a plain boolean with no lock, so two
    simultaneous cold requests can each spawn a listener thread. Connecting once
    in the app's lifespan, before any traffic, sidesteps that and also keeps the
    handshake latency out of the first answer.
    """
    return memory_config()


def reset(confirm: str) -> dict[str, Any]:
    """Wipe this namespace. Irreversible.

    Deliberately awkward to reach: `reeve.tools` exposes no `clear_memory`, and
    this also cancels queued writes and sweeps retained photos.
    """
    if not settings.allow_reset:
        raise PermissionError("Reset is disabled. Set CARREL_ALLOW_RESET=true to enable it.")
    if confirm != f"DELETE {NAMESPACE}":
        raise ValueError(f"Confirmation must be exactly: DELETE {NAMESPACE}")
    return _call_tool("clear_memory", {"speaker": NAMESPACE, "dry_run": False})
