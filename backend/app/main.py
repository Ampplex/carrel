"""Carrel — a coursework memory built on the Reeve SDK.

Run:  uvicorn app.main:app --reload --port 8000
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.errors import reeve_error_handler
from app.routes import account, ask, auth, capture, chats, legal, photos, recovery, status

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("Carrel")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Open the Reeve connection before serving traffic.

    Two reasons this is not left to the first request. The SDK's connect guard
    is an unsynchronised boolean, so two simultaneous cold requests can each
    start a listener thread; and the SSE handshake takes long enough that the
    first answer of a demo would otherwise be the slowest one.
    """
    from app import db, reeve_gateway

    # Tables before traffic. Idempotent, and it means a fresh database needs no
    # separate migration step to be a working deployment.
    db.init_schema()
    log.info("database ready")

    try:
        config = reeve_gateway.warm()
        app.state.reeve_warm = True
        log.info(
            "reeve ready · model=%s · vision=%s · retention=%s · namespace=%s",
            config.get("chat_model"),
            config.get("vision_enabled"),
            config.get("image_retention_enabled"),
            settings.namespace,
        )
    except Exception as exc:  # noqa: BLE001 - startup must not hard-fail
        app.state.reeve_warm = False
        # Deliberately not fatal: the UI reports an unreachable service far more
        # usefully than a container that refuses to boot.
        log.warning("reeve not reachable at startup: %s", exc)

    yield


app = FastAPI(title="Carrel", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.allowed_origins),
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Every unhandled exception becomes a classified, honest error payload rather
# than a bare 500 — quota exhaustion and model throttling are normal conditions
# here, not bugs, and they need to read differently in the UI.
app.add_exception_handler(Exception, reeve_error_handler)

app.include_router(legal.router)
app.include_router(recovery.router)
app.include_router(auth.router)
app.include_router(account.router)
app.include_router(chats.router)
app.include_router(status.router)
app.include_router(capture.router)
app.include_router(ask.router)
app.include_router(photos.router)

# In development the frontend runs on its own Vite server and talks across CORS.
# For a demo, `npm run build` produces dist/ and the whole app is served from
# this one process — one URL, no CORS, nothing to explain on stage.
_DIST = settings.var_dir.parent.parent / "frontend" / "dist"
if _DIST.exists():
    app.mount("/", StaticFiles(directory=_DIST, html=True), name="frontend")
