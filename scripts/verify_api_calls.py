#!/usr/bin/env python3
"""Verify API call counts per evaluation via /debug/eval trace data.

Usage:
  1. Start local server:  flask run  (or python app.py)
  2. Run this script:     python scripts/verify_api_calls.py

Hits POST /debug/eval with a benchmark address, parses the full trace,
and prints a summary table with pass/fail against the 38-60 target from
the NES-187 API call reduction work.

Requires the local server to be running with valid GOOGLE_MAPS_API_KEY
and WALKSCORE_API_KEY in .env.
"""

import json
import sys
from collections import defaultdict

import requests

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

BASE_URL = "http://localhost:5001"
DEBUG_EVAL_URL = f"{BASE_URL}/debug/eval"
BENCHMARK_ADDRESS = "10 Byron Place, Larchmont, NY 10538"

# Builder auth — default secret from app.py
BUILDER_SECRET = "nestcheck-builder-2024"

# Target from NES-187 API call reduction (batch + cache + spatial DB)
TARGET_LOW = 38
TARGET_HIGH = 60


def run_evaluation() -> dict:
    """Hit /debug/eval and return the full JSON response."""
    print(f"Running evaluation for: {BENCHMARK_ADDRESS}")
    print(f"Endpoint: {DEBUG_EVAL_URL}")
    print("(This takes 30-60s — full synchronous evaluation)\n")

    try:
        resp = requests.post(
            DEBUG_EVAL_URL,
            json={"address": BENCHMARK_ADDRESS},
            cookies={"nc_builder": BUILDER_SECRET},
            timeout=120,
        )
    except requests.ConnectionError:
        print(f"ERROR: Could not connect to {BASE_URL}")
        print("Start the local server first:  python app.py")
        sys.exit(1)

    if resp.status_code != 200:
        print(f"ERROR: /debug/eval returned {resp.status_code}")
        print(resp.text[:500])
        sys.exit(1)

    return resp.json()


def print_summary(data: dict):
    """Parse trace and print summary tables."""
    trace = data.get("trace", {})
    api_calls = trace.get("api_calls", [])
    stages = trace.get("stages", [])
    total = trace.get("total_api_calls", len(api_calls))
    elapsed = trace.get("total_elapsed_ms", 0)

    # --- Header ---
    print("=" * 60)
    print("  NES-187 API Call Verification")
    print("=" * 60)
    print(f"  Address:       {data.get('address', '?')}")
    print(f"  Final score:   {data.get('final_score', '?')}")
    print(f"  Passed Tier 1: {data.get('passed_tier1', '?')}")
    print(f"  Total elapsed: {elapsed:,}ms")
    print(f"  Total API calls: {total}")
    print(f"  Target range:  {TARGET_LOW}-{TARGET_HIGH}")
    print()

    # --- By service ---
    by_service: defaultdict[str, int] = defaultdict(int)
    for call in api_calls:
        by_service[call["service"]] += 1

    print("-" * 40)
    print("  Calls by service")
    print("-" * 40)
    for svc in sorted(by_service, key=lambda s: -by_service[s]):
        print(f"  {svc:<20} {by_service[svc]:>4}")
    print()

    # --- By (service, endpoint) ---
    by_endpoint: defaultdict[tuple, int] = defaultdict(int)
    for call in api_calls:
        by_endpoint[(call["service"], call["endpoint"])] += 1

    print("-" * 50)
    print("  Calls by service/endpoint")
    print("-" * 50)
    for (svc, ep) in sorted(by_endpoint, key=lambda k: (-by_endpoint[k], k[0], k[1])):
        print(f"  {svc}/{ep:<30} {by_endpoint[(svc, ep)]:>4}")
    print()

    # --- By stage ---
    print("-" * 50)
    print("  Calls by stage")
    print("-" * 50)
    for stage in stages:
        name = stage["stage"]
        calls = stage["api_calls"]
        ms = stage["elapsed_ms"]
        err = stage.get("error")
        suffix = f"  ERROR: {err}" if err else ""
        print(f"  {name:<30} {calls:>4} calls  {ms:>6}ms{suffix}")
    print()

    # --- Verdict ---
    print("=" * 60)
    if total <= TARGET_HIGH:
        print(f"  PASS — {total} calls is within the {TARGET_LOW}-{TARGET_HIGH} target")
    elif total <= TARGET_HIGH * 1.1:  # within 10% over
        print(f"  MARGINAL — {total} calls is slightly over the {TARGET_HIGH} target")
    else:
        print(f"  OVER TARGET — {total} calls exceeds the {TARGET_HIGH} target by {total - TARGET_HIGH}")
        # Show top offenders
        print()
        print("  Top call sources:")
        top = sorted(by_endpoint.items(), key=lambda x: -x[1])[:5]
        for (svc, ep), count in top:
            print(f"    {svc}/{ep}: {count}")
    print("=" * 60)

    return total


def main():
    data = run_evaluation()
    total = print_summary(data)

    # Dump full trace to file for reference
    outfile = "scripts/trace_output.json"
    with open(outfile, "w") as f:
        json.dump(data, f, indent=2)
    print(f"\nFull trace saved to {outfile}")

    sys.exit(0 if total <= TARGET_HIGH else 1)


if __name__ == "__main__":
    main()
