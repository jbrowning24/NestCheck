#!/usr/bin/env python3
"""Verify Sentry integration (run after pip install -r requirements.txt).

Usage:
  python scripts/verify_sentry.py

Checks:
  1. App starts without SENTRY_DSN (no errors, no SDK init)
  2. App starts with dummy SENTRY_DSN (sentry_sdk.init is called)
"""

import os
import sys

# Ensure we're in project root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_no_sentry_dsn():
    """Without SENTRY_DSN, app should import and Sentry should not be initialized."""
    os.environ["SENTRY_DSN"] = ""  # Empty beats pop — load_dotenv() won't override existing keys
    os.environ.setdefault("FLASK_DEBUG", "1")
    os.environ.setdefault("SECRET_KEY", "test-key-for-verify-sentry")
    os.environ.setdefault("NESTCHECK_DB_PATH", ":memory:")

    # Force re-import by clearing app from cache if it was imported with SENTRY_DSN
    for mod in list(sys.modules.keys()):
        if mod == "app" or mod.startswith("app."):
            del sys.modules[mod]
    if "sentry_sdk" in sys.modules:
        del sys.modules["sentry_sdk"]

    from app import app as flask_app
    import sentry_sdk

    # When SENTRY_DSN was never set, we never called init, so client is None
    client = sentry_sdk.Hub.current.client
    assert client is None, "Sentry should not be initialized when SENTRY_DSN is unset"
    print("  OK: App starts without SENTRY_DSN, Sentry not initialized")


def test_with_sentry_dsn():
    """With dummy SENTRY_DSN, app should import and Sentry init should be called."""
    os.environ["SENTRY_DSN"] = "https://invalid@o0.ingest.sentry.io/0"
    os.environ.setdefault("FLASK_DEBUG", "1")
    os.environ.setdefault("SECRET_KEY", "test-key-for-verify-sentry")
    os.environ.setdefault("NESTCHECK_DB_PATH", ":memory:")

    for mod in list(sys.modules.keys()):
        if mod == "app" or mod.startswith("app."):
            del sys.modules[mod]
    if "sentry_sdk" in sys.modules:
        del sys.modules["sentry_sdk"]

    from app import app as flask_app
    import sentry_sdk

    client = sentry_sdk.Hub.current.client
    assert client is not None, "Sentry should be initialized when SENTRY_DSN is set"
    print("  OK: App starts with SENTRY_DSN, sentry_sdk.init() was called")


if __name__ == "__main__":
    print("Verifying Sentry integration...")
    try:
        test_no_sentry_dsn()
        test_with_sentry_dsn()
        print("\nAll checks passed.")
    except Exception as e:
        print(f"\nFAIL: {e}")
        sys.exit(1)
