"""Test database wiring.

The suite used to point the JSON stores at a tmp_path, which made isolation
free. Postgres has no equivalent, so this does the next best thing: every test
runs against a **separate database**, `carrel_test`, and every table is
truncated between tests.

The separate database matters more than it sounds. Pointing the suite at the
real one and trusting each test to clean up after itself is how a test run ends
up deleting somebody's account — and it only has to happen once. `carrel_test`
is created by hand (see the README); the suite refuses to run against anything
whose name is not `carrel_test`, so a misconfigured DATABASE_URL fails loudly
instead of truncating live data.
"""

from __future__ import annotations

import os
import pathlib

import pytest

# The app reads .env when app.config is imported. pytest gets here first, so
# conftest has to load it itself or DATABASE_URL is simply absent.
try:
    from dotenv import load_dotenv

    load_dotenv(pathlib.Path(__file__).resolve().parent.parent / ".env")
except ImportError:  # pragma: no cover - dotenv is a dev convenience
    pass

# Resolved before app.config is imported anywhere, so settings pick it up.
_URL = os.environ.get("TEST_DATABASE_URL") or os.environ.get("DATABASE_URL", "")
if _URL and not _URL.rstrip("/").endswith("/carrel_test"):
    _URL = _URL.rsplit("/", 1)[0] + "/carrel_test"
os.environ["DATABASE_URL"] = _URL


def pytest_configure(config):
    """Fail fast and clearly rather than three hundred confusing errors."""
    if not _URL:
        pytest.exit(
            "DATABASE_URL is not set. These tests need Postgres:\n"
            "  create the database once:  CREATE DATABASE carrel_test OWNER carrel;\n"
            "  then run:                  make test",
            returncode=1,
        )
    if not _URL.rstrip("/").endswith("/carrel_test"):
        pytest.exit(
            f"Refusing to run against {_URL.rsplit('/', 1)[-1]!r}. "
            "The suite truncates every table, so it only runs on 'carrel_test'.",
            returncode=1,
        )


@pytest.fixture(autouse=True)
def _clean_database():
    """A fresh, empty schema for every test.

    TRUNCATE ... CASCADE rather than dropping and recreating: it is far quicker,
    and the cascade means the order of the table list does not have to track the
    foreign keys.
    """
    from app import db

    db.init_schema()
    with db.cursor(commit=True) as cur:
        cur.execute(
            "TRUNCATE users, sessions, chats, messages, photos, pending_writes"
            " RESTART IDENTITY CASCADE"
        )
    yield
