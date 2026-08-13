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
    api_key: str = field(default_factory=lambda: os.environ.get("REEVE_API_KEY", "").strip())
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
    max_chunks: int = 12
    chunk_pace_seconds: float = 1.5

    def require_api_key(self) -> None:
        if not self.api_key:
            raise RuntimeError(
                "REEVE_API_KEY is empty. Copy .env.example to backend/.env and set it. "
                "The key must never be sent to the browser."
            )


settings = Settings()
settings.photo_dir.mkdir(parents=True, exist_ok=True)
