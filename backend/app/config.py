"""Settings, and the one import-order rule this project must not break.

`reeve/tools.py` snapshots `REEVE_API_KEY` from the environment at import time.
If anything imports `reeve` before the `.env` file is loaded, the SDK starts up
with no credential and every call fails with a 401 that looks like a server
problem rather than a local one.

So this module calls `load_dotenv()` at import, and `reeve_gateway` — the only
module allowed to import reeve — imports this module on its first line. The
ordering is structural rather than remembered.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parent.parent
REPO_DIR = BACKEND_DIR.parent

load_dotenv(BACKEND_DIR / ".env")


def _flag(name: str, default: bool = False) -> bool:
    return os.environ.get(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    # repr=False, because a frozen dataclass prints every field in any traceback
    # that mentions it — which is how the Reeve API key ended up in a pytest
    # failure. A secret that leaks into logs is a leaked secret.
    api_key: str = field(
        default_factory=lambda: os.environ.get("REEVE_API_KEY", "").strip(), repr=False
    )
    namespace: str = field(
        default_factory=lambda: os.environ.get("CARREL_NAMESPACE", "carrel-demo").strip()
    )
    allowed_origins: tuple[str, ...] = field(
        default_factory=lambda: tuple(
            origin.strip()
            for origin in os.environ.get("ALLOWED_ORIGINS", "http://localhost:5173").split(",")
            if origin.strip()
        )
    )
    allow_reset: bool = field(default_factory=lambda: _flag("CARREL_ALLOW_RESET"))
    demo_replay: bool = field(default_factory=lambda: _flag("CARREL_DEMO_REPLAY"))

    # Postgres. repr=False for the same reason as the API key: it carries a
    # password, and a dataclass prints every field into any traceback.
    database_url: str = field(
        default_factory=lambda: os.environ.get("DATABASE_URL", "").strip(), repr=False
    )

    # Where photo bytes live. Not on the application server: that box runs a
    # production MCP server on a 6GB volume, and photographs are the only thing
    # in this system that grows without bound.
    s3_bucket: str = field(default_factory=lambda: os.environ.get("CARREL_S3_BUCKET", "").strip())
    s3_prefix: str = field(
        default_factory=lambda: os.environ.get("CARREL_S3_PREFIX", "carrel/photos").strip()
    )
    s3_region: str = field(
        default_factory=lambda: os.environ.get("AWS_REGION", "ap-south-1").strip()
    )

    # Email. repr=False on the key for the same reason as everything else here:
    # a dataclass prints every field into any traceback that touches it.
    brevo_api_key: str = field(
        default_factory=lambda: os.environ.get("BREVO_API_KEY", "").strip(), repr=False
    )
    mail_from: str = field(default_factory=lambda: os.environ.get("CARREL_MAIL_FROM", "").strip())
    mail_from_name: str = field(
        default_factory=lambda: os.environ.get("CARREL_MAIL_FROM_NAME", "Carrel").strip()
    )
    # Where the links in those emails point. Must be the public origin, not the
    # container's own address: a reset link to 127.0.0.1 is a broken link in
    # somebody's inbox.
    # Shared secret in the webhook path. Empty means the endpoint 404s, so an
    # unconfigured deployment cannot be fed fake bounce reports.
    brevo_webhook_secret: str = field(
        default_factory=lambda: os.environ.get("BREVO_WEBHOOK_SECRET", "").strip(), repr=False
    )
    public_base_url: str = field(
        default_factory=lambda: os.environ.get(
            "CARREL_PUBLIC_BASE_URL", "https://carrel.reeve.co.in"
        ).rstrip("/")
    )

    # Every OAuth client allowed to mint an ID token this server will accept.
    # Plural because Google issues a separate client ID per platform, and the
    # `aud` claim carries whichever one the app was built with — the iOS client
    # on an iPhone, the Android client on a phone, the Web client in a browser.
    # Accepting a token whose audience is not on this list is the whole of the
    # security story here; see app/google_auth.py.
    google_client_ids: tuple[str, ...] = field(
        default_factory=lambda: tuple(
            client_id.strip()
            for client_id in os.environ.get("GOOGLE_CLIENT_IDS", "").split(",")
            if client_id.strip()
        )
    )

    var_dir: Path = BACKEND_DIR / "var"
    photo_dir: Path = BACKEND_DIR / "var" / "photos"

    # Mirrors the server's own limits so bad uploads fail locally, instantly,
    # with a useful message — rather than after a round trip.
    max_image_bytes: int = 4 * 1024 * 1024
    allowed_media_types: frozenset[str] = frozenset(
        {"image/jpeg", "image/png", "image/gif", "image/webp"}
    )

    # Long notes dilute their own key fact in retrieval, so the app chunks them.
    chunk_threshold_chars: int = 1200
    chunk_target_chars: int = 600
    # 120 chunks is roughly 72,000 characters — a long lecture transcript or a
    # whole chat export. It used to be 12, which rejected anything past about
    # 7,200 characters with "break it up yourself".
    #
    # The real limit was never the count: writes are paced to avoid throttling
    # upstream, so 120 chunks would have meant a request held open for two
    # minutes. They are written in the background now, which is what makes a
    # number this size usable rather than merely permitted.
    max_chunks: int = 120
    chunk_pace_seconds: float = 0.9

    def require_api_key(self) -> None:
        if not self.api_key:
            raise RuntimeError(
                "REEVE_API_KEY is empty. Copy .env.example to backend/.env and set it. "
                "The key must never be sent to the browser."
            )


settings = Settings()
settings.photo_dir.mkdir(parents=True, exist_ok=True)
