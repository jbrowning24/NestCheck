#!/usr/bin/env python3
"""
NestCheck post-deploy smoke test.
Fetches known pages and asserts critical content markers are present.
Catches the class of bug where a template refactor silently removes
the evaluation body while leaving header/nav/footer intact.
Usage:
    python smoke_test.py                          # uses default prod URL
    python smoke_test.py https://your-url.app     # custom base URL
    make smoke                                     # if wired into Makefile
Exit codes:
    0 = all checks passed
    1 = one or more checks failed

Webhook alerting:
    Set SMOKE_ALERT_WEBHOOK to a Slack or Discord webhook URL.
    On failure, a JSON payload is POSTed with a "text" field summary.
    If unset, alerting is silently skipped.
"""
import json
import os
import sys
import urllib.request
import urllib.error
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
DEFAULT_BASE_URL = "https://web-production-2a60f5.up.railway.app"

# Hardcoded fallback snapshot ID (used when the dynamic lookup fails).
FALLBACK_SNAPSHOT_ID = "6c8f67a6"

# Content markers that MUST be present in a correctly rendered snapshot.
# If any of these are missing, the evaluation body was likely stripped.
SNAPSHOT_REQUIRED_MARKERS = [
    "verdict-card",           # Verdict section
    "dimension-score",        # Scored dimension rows (parks, transit, etc.)
    "how-we-score",           # Scoring methodology section
]

# We check for at least N of these
SNAPSHOT_MIN_MARKERS = 2

# Content markers for the landing page
LANDING_REQUIRED_MARKERS = [
    'id="address"',           # The address input form
    "Evaluate",               # Submit button text
]

# Minimum response size (bytes) to catch empty/error pages
MIN_PAGE_SIZE_BYTES = 5000


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def fetch(url: str) -> tuple[int, str]:
    """Fetch a URL, return (status_code, body_text)."""
    req = urllib.request.Request(url, headers={"User-Agent": "NestCheck-Smoke/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status, resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        return e.code, ""
    except Exception as e:
        print(f"  FETCH ERROR: {e}")
        return 0, ""


def resolve_snapshot_id(base_url: str) -> str | None:
    """Ask the app for the most recent snapshot ID, fall back to hardcoded.

    Returns None when the API explicitly reports no snapshots (empty DB).
    Falls back to FALLBACK_SNAPSHOT_ID only when the API call itself fails.
    """
    status, body = fetch(f"{base_url}/healthz/latest-snapshot")
    if status == 200 and body:
        try:
            data = json.loads(body)
            if "snapshot_id" in data:
                return data["snapshot_id"]  # may be None — means DB is empty
        except (json.JSONDecodeError, KeyError):
            pass
    # Network/parse failure — fall back to hardcoded ID
    return FALLBACK_SNAPSHOT_ID


def check_markers(body: str, markers: list[str], min_required: int) -> list[str]:
    """Return list of missing markers. Passes if len(found) >= min_required."""
    found = [m for m in markers if m in body]
    if len(found) >= min_required:
        return []
    missing = [m for m in markers if m not in body]
    return missing


def send_webhook_alert(failures: list[str]) -> None:
    """POST a failure summary to SMOKE_ALERT_WEBHOOK. Fire-and-forget."""
    webhook_url = os.environ.get("SMOKE_ALERT_WEBHOOK", "").strip()
    if not webhook_url:
        return

    commit = os.environ.get("RAILWAY_GIT_COMMIT_SHA", "unknown")[:7]
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    details = "; ".join(failures)
    text = (
        f"\U0001f6a8 NestCheck smoke test failed on deploy {commit} "
        f"at {timestamp} \u2014 {details}"
    )

    payload = json.dumps({"text": text}).encode("utf-8")
    req = urllib.request.Request(
        webhook_url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=5):
            pass
    except Exception as e:
        print(f"  ALERT WARN: webhook POST failed ({e})")


# ---------------------------------------------------------------------------
# Test runner
# ---------------------------------------------------------------------------
def run_tests(base_url: str) -> bool:
    passed = True
    failures: list[str] = []

    # --- Test 1: Landing page loads ---
    print(f"\n[1] Landing page: {base_url}/")
    status, body = fetch(f"{base_url}/")
    if status != 200:
        print(f"  FAIL: status {status} (expected 200)")
        failures.append(f"Test 1 (landing page): HTTP {status}, expected 200")
        passed = False
    elif len(body) < MIN_PAGE_SIZE_BYTES:
        print(f"  FAIL: response only {len(body)} bytes (minimum {MIN_PAGE_SIZE_BYTES})")
        failures.append(f"Test 1 (landing page): {len(body)} bytes, minimum {MIN_PAGE_SIZE_BYTES}")
        passed = False
    else:
        missing = check_markers(body, LANDING_REQUIRED_MARKERS, len(LANDING_REQUIRED_MARKERS))
        if missing:
            print(f"  FAIL: missing markers: {missing}")
            failures.append(f"Test 1 (landing page): missing markers {missing}")
            passed = False
        else:
            print(f"  PASS ({len(body):,} bytes, all markers present)")

    # --- Test 2: Snapshot page renders full evaluation ---
    snapshot_id = resolve_snapshot_id(base_url)
    if not snapshot_id:
        print(f"\n[2] Snapshot page: SKIP (no snapshots in database)")
    else:
        snapshot_url = f"{base_url}/s/{snapshot_id}"
        print(f"\n[2] Snapshot page: {snapshot_url}")
        status, body = fetch(snapshot_url)
        if status == 404:
            # Snapshot ID from DB/fallback no longer exists — warn, don't fail
            print(f"  WARN: snapshot {snapshot_id} returned 404 (may have been purged)")
        elif status != 200:
            print(f"  FAIL: status {status} (expected 200)")
            failures.append(f"Test 2 (snapshot rendering): HTTP {status}, expected 200")
            passed = False
        elif len(body) < MIN_PAGE_SIZE_BYTES:
            print(f"  FAIL: response only {len(body)} bytes (minimum {MIN_PAGE_SIZE_BYTES})")
            failures.append(f"Test 2 (snapshot rendering): {len(body)} bytes, minimum {MIN_PAGE_SIZE_BYTES}")
            passed = False
        else:
            missing = check_markers(body, SNAPSHOT_REQUIRED_MARKERS, SNAPSHOT_MIN_MARKERS)
            if missing:
                print(f"  FAIL: missing markers (need {SNAPSHOT_MIN_MARKERS}): {missing}")
                print(f"  This likely means _result_sections.html was removed from snapshot.html")
                failures.append(f"Test 2 (snapshot rendering): missing markers {missing}")
                passed = False
            else:
                print(f"  PASS ({len(body):,} bytes, evaluation body present)")

    # --- Test 3: 404 page returns 404 ---
    print(f"\n[3] 404 page: {base_url}/s/nonexistent-id-12345")
    status, body = fetch(f"{base_url}/s/nonexistent-id-12345")
    if status == 404:
        print(f"  PASS (returned 404)")
    elif status == 200:
        print(f"  WARN: returned 200 for nonexistent snapshot (not fatal)")
    else:
        print(f"  WARN: returned {status}")

    # --- Send webhook alert on failure ---
    if failures:
        send_webhook_alert(failures)

    return passed


def main():
    base_url = sys.argv[1].rstrip("/") if len(sys.argv) > 1 else DEFAULT_BASE_URL
    print(f"NestCheck Smoke Test")
    print(f"Target: {base_url}")
    print("=" * 60)

    ok = run_tests(base_url)

    print("\n" + "=" * 60)
    if ok:
        print("ALL CHECKS PASSED")
        sys.exit(0)
    else:
        print("ONE OR MORE CHECKS FAILED")
        sys.exit(1)


if __name__ == "__main__":
    main()
