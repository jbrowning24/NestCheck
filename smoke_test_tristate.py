#!/usr/bin/env python3
"""
Tri-state smoke test checklist for NestCheck Phase 3 expansion.

Submits evaluations for one address per state (NY existing, NY new, CT, NJ),
polls for completion, then verifies rendered snapshot pages contain expected
sections and data.

Usage:
    python smoke_test_tristate.py                          # prod URL
    python smoke_test_tristate.py http://localhost:5000     # local
    make smoke-tristate                                     # via Makefile

Exit codes:
    0 = all checks passed
    1 = one or more checks failed

Requires GOOGLE_MAPS_API_KEY (or app must have one configured) for
evaluations to succeed.

Expected incomplete data (not bugs — tracked in NES-219/220/221):
    - School performance data missing for most NJ/CT addresses
    - School performance data missing for NY addresses outside Westchester
"""
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
DEFAULT_BASE_URL = "https://web-production-2a60f5.up.railway.app"

# Max time to wait for a single evaluation to complete (seconds)
EVAL_TIMEOUT_SECONDS = 180
POLL_INTERVAL_SECONDS = 3

# Test addresses — one per state, plus a regression address
TEST_ADDRESSES = [
    {
        "label": "NY-existing (White Plains)",
        "address": "White Plains, NY 10601",
        "state": "NY",
        "is_regression": True,
        "expect_school_performance": True,
        "why": "Existing coverage, regression check",
    },
    {
        "label": "NY-new (Albany)",
        "address": "Albany, NY 12207",
        "state": "NY",
        "is_regression": False,
        "expect_school_performance": False,
        "why": "Outside Westchester — tests expanded NY spatial data",
    },
    {
        "label": "CT (Stamford)",
        "address": "Stamford, CT 06901",
        "state": "CT",
        "is_regression": False,
        "expect_school_performance": False,
        "why": "Metro-North corridor, likely has school district match",
    },
    {
        "label": "NJ (Hoboken)",
        "address": "Hoboken, NJ 07030",
        "state": "NJ",
        "is_regression": False,
        "expect_school_performance": False,
        "why": "Dense urban, should hit all spatial datasets",
    },
]

# Section markers that MUST appear in every snapshot page
CORE_SECTION_MARKERS = [
    ("verdict-card", "Verdict card"),
    ("dimension-score", "Dimension scores"),
    ("health-safety", "Health & Safety section"),
    ("how-we-score", "Scoring methodology"),
]

# Section markers that SHOULD appear (warn if missing, don't fail)
EXPECTED_SECTION_MARKERS = [
    ("your-neighborhood", "Your Neighborhood section"),
    ("getting-around", "Getting Around section"),
    ("parks-green-space", "Parks & Green Space section"),
    ("emergency-services", "Emergency Services section"),
]

# Spatial/environmental markers — evidence that spatial datasets loaded
SPATIAL_MARKERS = [
    ("health-safety", "Health checks rendered"),
]

# School district markers
SCHOOL_DISTRICT_MARKERS = [
    ("school-district", "School district section"),
]

# EJScreen markers
EJSCREEN_MARKERS = [
    ("ejscreen-profile", "EJScreen environmental profile"),
]

# Minimum page size
MIN_SNAPSHOT_SIZE_BYTES = 10_000


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def fetch(url: str, method: str = "GET",
          data: bytes | None = None,
          content_type: str | None = None,
          timeout: int = 30) -> tuple[int, str]:
    """Fetch a URL, return (status_code, body_text)."""
    headers = {"User-Agent": "NestCheck-SmokeTristate/1.0"}
    if content_type:
        headers["Content-Type"] = content_type
    req = urllib.request.Request(url, headers=headers, method=method, data=data)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8", errors="replace")
        except Exception:
            pass
        return e.code, body
    except Exception as e:
        print(f"  FETCH ERROR: {e}")
        return 0, ""


def submit_evaluation(base_url: str, address: str) -> str | None:
    """Submit an address for evaluation, return job_id or None on failure."""
    form_data = urllib.parse.urlencode({"address": address}).encode("utf-8")
    status, body = fetch(
        f"{base_url}/",
        method="POST",
        data=form_data,
        content_type="application/x-www-form-urlencoded",
    )
    if status == 200 and body:
        try:
            data = json.loads(body)
            return data.get("job_id")
        except (json.JSONDecodeError, KeyError):
            pass
    print(f"  Submit failed: HTTP {status}")
    return None


def poll_job(base_url: str, job_id: str,
             timeout: int = EVAL_TIMEOUT_SECONDS) -> dict | None:
    """Poll job status until done/failed or timeout. Return final job dict."""
    start = time.monotonic()
    while time.monotonic() - start < timeout:
        status, body = fetch(f"{base_url}/job/{job_id}")
        if status == 200 and body:
            try:
                data = json.loads(body)
                job_status = data.get("status", "")
                stage = data.get("current_stage", "")
                if stage:
                    print(f"  ... {job_status}: {stage}")
                if job_status == "done":
                    return data
                if job_status == "failed":
                    print(f"  Job failed: {data.get('error', 'unknown')}")
                    return data
            except (json.JSONDecodeError, KeyError):
                pass
        elif status == 404:
            # Job not yet visible (eventual consistency)
            pass
        time.sleep(POLL_INTERVAL_SECONDS)
    print(f"  TIMEOUT after {timeout}s")
    return None


def check_section_markers(
    body: str,
    markers: list[tuple[str, str]],
) -> tuple[list[str], list[str]]:
    """Check for section markers. Return (found_labels, missing_labels)."""
    found = []
    missing = []
    for marker, label in markers:
        if marker in body:
            found.append(label)
        else:
            missing.append(label)
    return found, missing


# ---------------------------------------------------------------------------
# Checklist verification for a single snapshot
# ---------------------------------------------------------------------------
def verify_snapshot(
    base_url: str,
    snapshot_id: str,
    test_config: dict,
) -> tuple[bool, list[str], list[str]]:
    """Verify a snapshot page. Returns (passed, failures, warnings)."""
    failures: list[str] = []
    warnings: list[str] = []
    label = test_config["label"]

    snapshot_url = f"{base_url}/s/{snapshot_id}"
    print(f"\n  Verifying snapshot: {snapshot_url}")

    status, body = fetch(snapshot_url)

    # 1. HTTP 200
    if status != 200:
        failures.append(f"[{label}] HTTP {status} (expected 200)")
        return False, failures, warnings

    # 2. Minimum page size
    if len(body) < MIN_SNAPSHOT_SIZE_BYTES:
        failures.append(
            f"[{label}] Page only {len(body)} bytes "
            f"(min {MIN_SNAPSHOT_SIZE_BYTES})"
        )
        return False, failures, warnings

    print(f"  Page loaded: {len(body):,} bytes")

    # 3. Core sections (FAIL if missing)
    found, missing = check_section_markers(body, CORE_SECTION_MARKERS)
    for f in found:
        print(f"    [ok] {f}")
    for m in missing:
        print(f"    [FAIL] {m} — MISSING")
        failures.append(f"[{label}] Missing core section: {m}")

    # 4. Expected sections (WARN if missing)
    found, missing = check_section_markers(body, EXPECTED_SECTION_MARKERS)
    for f in found:
        print(f"    [ok] {f}")
    for m in missing:
        print(f"    [warn] {m} — missing (non-fatal)")
        warnings.append(f"[{label}] Missing expected section: {m}")

    # 5. Health checks (spatial data)
    found, missing = check_section_markers(body, SPATIAL_MARKERS)
    if missing:
        failures.append(f"[{label}] Health checks section missing")
        print(f"    [FAIL] Health checks not rendered")
    else:
        print(f"    [ok] Health checks rendered")

    # 6. School district (TIGER polygon lookup)
    found, missing = check_section_markers(body, SCHOOL_DISTRICT_MARKERS)
    if found:
        print(f"    [ok] School district identified")
        # Check for performance data if expected
        if test_config.get("expect_school_performance"):
            if "graduation" in body.lower() or "proficiency" in body.lower():
                print(f"    [ok] School performance data present")
            else:
                warnings.append(
                    f"[{label}] School performance data not found "
                    f"(expected for this address)"
                )
                print(f"    [warn] School performance data not found")
        else:
            # Performance data optional — check for graceful handling
            if "graduation" in body.lower() or "proficiency" in body.lower():
                print(f"    [ok] School performance data present (bonus)")
            else:
                print(
                    f"    [info] No school performance data "
                    f"(expected — NES-219/220/221)"
                )
    else:
        warnings.append(f"[{label}] School district section missing")
        print(f"    [warn] School district not identified")

    # 7. EJScreen environmental data
    found, missing = check_section_markers(body, EJSCREEN_MARKERS)
    if found:
        print(f"    [ok] EJScreen profile present")
    else:
        warnings.append(f"[{label}] EJScreen profile missing")
        print(f"    [warn] EJScreen profile missing")

    # 8. Nearby schools (NCES)
    if "nearby-schools" in body:
        print(f"    [ok] Nearby schools listed")
    else:
        warnings.append(f"[{label}] Nearby schools section missing")
        print(f"    [warn] Nearby schools not listed")

    passed = len(failures) == 0
    return passed, failures, warnings


# ---------------------------------------------------------------------------
# JSON export verification (structural check)
# ---------------------------------------------------------------------------
def verify_json_export(
    base_url: str,
    snapshot_id: str,
    label: str,
) -> tuple[bool, list[str]]:
    """Verify the JSON export endpoint returns valid data."""
    failures: list[str] = []
    status, body = fetch(f"{base_url}/api/snapshot/{snapshot_id}/json")
    if status != 200:
        failures.append(f"[{label}] JSON export HTTP {status}")
        return False, failures

    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        failures.append(f"[{label}] JSON export returned invalid JSON")
        return False, failures

    required_keys = ["snapshot_id", "address_input", "verdict", "result"]
    missing_keys = [k for k in required_keys if k not in data]
    if missing_keys:
        failures.append(
            f"[{label}] JSON export missing keys: {missing_keys}"
        )
        return False, failures

    result = data.get("result", {})

    # Check for tier1_checks (health checks)
    if "tier1_checks" not in result:
        failures.append(f"[{label}] JSON export missing tier1_checks")
    else:
        n_checks = len(result["tier1_checks"])
        print(f"    [ok] JSON export valid ({n_checks} health checks)")

    # Check for tier2_scores (dimensions)
    if "tier2_scores" not in result:
        failures.append(f"[{label}] JSON export missing tier2_scores")
    else:
        n_dims = len(result["tier2_scores"])
        print(f"    [ok] {n_dims} dimension scores in JSON")

    return len(failures) == 0, failures


# ---------------------------------------------------------------------------
# Main test runner
# ---------------------------------------------------------------------------
def run_tristate_tests(base_url: str) -> bool:
    all_passed = True
    all_failures: list[str] = []
    all_warnings: list[str] = []
    results_summary: list[dict] = []

    for i, test in enumerate(TEST_ADDRESSES, 1):
        label = test["label"]
        address = test["address"]
        print(f"\n{'=' * 60}")
        print(f"[{i}/{len(TEST_ADDRESSES)}] {label}")
        print(f"  Address: {address}")
        print(f"  Why: {test['why']}")
        print("-" * 60)

        # Submit evaluation
        print(f"  Submitting evaluation...")
        job_id = submit_evaluation(base_url, address)
        if not job_id:
            all_failures.append(f"[{label}] Failed to submit evaluation")
            all_passed = False
            results_summary.append({
                "label": label, "status": "SUBMIT_FAILED",
            })
            continue

        print(f"  Job ID: {job_id}")

        # Poll for completion
        job_result = poll_job(base_url, job_id)
        if not job_result:
            all_failures.append(f"[{label}] Evaluation timed out")
            all_passed = False
            results_summary.append({
                "label": label, "status": "TIMEOUT",
            })
            continue

        if job_result.get("status") == "failed":
            all_failures.append(
                f"[{label}] Evaluation failed: "
                f"{job_result.get('error', 'unknown')}"
            )
            all_passed = False
            results_summary.append({
                "label": label, "status": "EVAL_FAILED",
                "error": job_result.get("error"),
            })
            continue

        snapshot_id = job_result.get("snapshot_id")
        if not snapshot_id:
            all_failures.append(f"[{label}] No snapshot_id in completed job")
            all_passed = False
            results_summary.append({
                "label": label, "status": "NO_SNAPSHOT",
            })
            continue

        print(f"  Evaluation complete. Snapshot: {snapshot_id}")

        # Verify snapshot page
        passed, failures, warnings = verify_snapshot(
            base_url, snapshot_id, test
        )
        all_failures.extend(failures)
        all_warnings.extend(warnings)
        if not passed:
            all_passed = False

        # Verify JSON export
        json_ok, json_failures = verify_json_export(
            base_url, snapshot_id, label
        )
        all_failures.extend(json_failures)
        if not json_ok:
            all_passed = False

        results_summary.append({
            "label": label,
            "status": "PASS" if passed and json_ok else "FAIL",
            "snapshot_id": snapshot_id,
            "snapshot_url": f"{base_url}/s/{snapshot_id}",
            "failures": failures,
            "warnings": warnings,
        })

    # --- Summary ---
    print(f"\n{'=' * 60}")
    print("TRI-STATE SMOKE TEST SUMMARY")
    print("=" * 60)

    for r in results_summary:
        status_icon = "PASS" if r["status"] == "PASS" else "FAIL"
        print(f"  [{status_icon}] {r['label']}")
        if r.get("snapshot_url"):
            print(f"         {r['snapshot_url']}")
        if r.get("error"):
            print(f"         Error: {r['error']}")

    if all_warnings:
        print(f"\nWarnings ({len(all_warnings)}):")
        for w in all_warnings:
            print(f"  - {w}")

    if all_failures:
        print(f"\nFailures ({len(all_failures)}):")
        for f in all_failures:
            print(f"  - {f}")

    return all_passed


def main():
    base_url = (
        sys.argv[1].rstrip("/") if len(sys.argv) > 1 else DEFAULT_BASE_URL
    )
    print("NestCheck Tri-State Smoke Test (Phase 3)")
    print(f"Target: {base_url}")
    print(f"Addresses: {len(TEST_ADDRESSES)}")

    ok = run_tristate_tests(base_url)

    print("\n" + "=" * 60)
    if ok:
        print("ALL TRI-STATE CHECKS PASSED")
        sys.exit(0)
    else:
        print("ONE OR MORE TRI-STATE CHECKS FAILED")
        sys.exit(1)


if __name__ == "__main__":
    main()
