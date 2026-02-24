"""Shared fixtures for NestCheck test suite.

Provides a Flask test client wired to a temporary SQLite database
and mocked Stripe SDK for payment flow tests.
"""

import atexit
import os
import tempfile

import pytest

# Point the DB at a temp file BEFORE importing app/models (they read DB_PATH at import time)
_test_db_fd, _test_db_path = tempfile.mkstemp(suffix=".db")
os.close(_test_db_fd)  # close the fd immediately; sqlite3 opens its own handle
os.environ["NESTCHECK_DB_PATH"] = _test_db_path
atexit.register(lambda: os.unlink(_test_db_path) if os.path.exists(_test_db_path) else None)

# Suppress the SECRET_KEY startup guard
os.environ.setdefault("SECRET_KEY", "test-secret-key")

# Ensure Google Maps key is present (index route checks this)
os.environ.setdefault("GOOGLE_MAPS_API_KEY", "fake-key-for-tests")

from app import app  # noqa: E402
from models import init_db, _get_db  # noqa: E402

# Base template expects csrf_token() to exist. Provide a benign test fallback.
app.jinja_env.globals.setdefault("csrf_token", lambda: "")


@pytest.fixture(autouse=True)
def _fresh_db():
    """Reset the database before every test.

    Drops all rows from tables that payment tests touch, keeping the
    schema intact so init_db() doesn't need to run every time.
    """
    init_db()
    conn = _get_db()
    for table in ("events", "snapshots"):
        conn.execute(f"DELETE FROM {table}")
    conn.commit()
    conn.close()
    yield


@pytest.fixture()
def client():
    """Flask test client with CSRF disabled (we're testing logic, not CSRF)."""
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    with app.test_client() as c:
        yield c
