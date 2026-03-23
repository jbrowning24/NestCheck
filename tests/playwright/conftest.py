"""Playwright test fixtures for NestCheck report rendering.

Provides a live Flask server, fixture data loading, and snapshot URL generation.
The parent tests/conftest.py handles DB setup (NESTCHECK_DB_PATH, SECRET_KEY,
GOOGLE_MAPS_API_KEY) and the autouse _fresh_db fixture.
"""

import json
import threading
import time
import urllib.request

import pytest
from pathlib import Path

# Parent conftest.py already set NESTCHECK_DB_PATH, SECRET_KEY, GOOGLE_MAPS_API_KEY
# and imported app/models before we get here.
from app import app as flask_app
from models import save_snapshot, init_db

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"
_SERVER_PORT = 5556


@pytest.fixture(scope="session")
def _live_server():
    """Start Flask dev server in a background thread for Playwright."""
    flask_app.config["TESTING"] = True
    flask_app.config["WTF_CSRF_ENABLED"] = False

    init_db()

    server_thread = threading.Thread(
        target=flask_app.run,
        kwargs={"port": _SERVER_PORT, "use_reloader": False, "threaded": True},
        daemon=True,
    )
    server_thread.start()

    # Wait for server readiness
    base = f"http://127.0.0.1:{_SERVER_PORT}"
    for _ in range(50):
        try:
            urllib.request.urlopen(base + "/robots.txt", timeout=2)
            break
        except Exception:
            time.sleep(0.2)
    else:
        raise RuntimeError(f"Flask test server failed to start on port {_SERVER_PORT}")

    yield base


@pytest.fixture(scope="session")
def base_url(_live_server):
    """Override pytest-playwright's base_url."""
    return _live_server


@pytest.fixture(scope="session")
def browser_context_args(browser_context_args):
    """Set a consistent desktop viewport for screenshots."""
    return {**browser_context_args, "viewport": {"width": 1280, "height": 900}}


@pytest.fixture
def healthy_result():
    """Load the healthy evaluation fixture."""
    return json.loads((FIXTURES_DIR / "eval_result_healthy.json").read_text())


@pytest.fixture
def concerning_result():
    """Load the concerning evaluation fixture."""
    return json.loads((FIXTURES_DIR / "eval_result_concerning.json").read_text())


def _save_fixture_snapshot(result_dict):
    """Persist a result dict as a snapshot and return the snapshot_id."""
    with flask_app.app_context():
        return save_snapshot(
            address_input=result_dict["address"],
            address_norm=result_dict["address"],
            result_dict=result_dict,
        )


@pytest.fixture
def healthy_report_url(healthy_result, base_url):
    """Save the healthy fixture as a snapshot and return its URL."""
    snapshot_id = _save_fixture_snapshot(healthy_result)
    return f"{base_url}/s/{snapshot_id}"


@pytest.fixture
def concerning_report_url(concerning_result, base_url):
    """Save the concerning fixture as a snapshot and return its URL."""
    snapshot_id = _save_fixture_snapshot(concerning_result)
    return f"{base_url}/s/{snapshot_id}"
