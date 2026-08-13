"""Counts what this app spends against Reeve's monthly query quota.

Reads cost quota; writes do not. Specifically `query_memory`,
`retrieve_memory_context` and `backup_memory` each count as one query, so
"ask with evidence" costs two, not one.

Two reasons to track it rather than guess. During development it stops a stray
polling loop from quietly burning the month's allowance. During the project
write-up it turns "how much did this cost to build" into a measured number.

The ledger is a small JSON file under `var/` and is intentionally not a database.
"""

from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timezone

from app.config import settings

_LEDGER = settings.var_dir / "quota.json"
_lock = threading.Lock()


def _load() -> dict:
    if _LEDGER.exists():
        try:
            return json.loads(_LEDGER.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return {"total": 0, "by_month": {}, "by_kind": {}, "started": time.time()}


def _month() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")


def spend(kind: str, queries: int = 1) -> int:
    """Record `queries` spent on `kind`. Returns the running total this month."""
    with _lock:
        data = _load()
        month = _month()
        data["total"] = data.get("total", 0) + queries
        data["by_month"][month] = data["by_month"].get(month, 0) + queries
        data["by_kind"][kind] = data["by_kind"].get(kind, 0) + queries
        settings.var_dir.mkdir(parents=True, exist_ok=True)
        _LEDGER.write_text(json.dumps(data, indent=2))
        return data["by_month"][month]


def snapshot() -> dict:
    with _lock:
        data = _load()
    return {
        "total_all_time": data.get("total", 0),
        "this_month": data.get("by_month", {}).get(_month(), 0),
        "by_kind": data.get("by_kind", {}),
    }
