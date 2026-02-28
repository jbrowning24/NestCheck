#!/usr/bin/env python3
"""
Find demo addresses for the landing page.

Searches the snapshot database for evaluations where health proximity checks
returned real findings (not UNKNOWN). Prioritizes:
  1. Gas station FAIL — most reliable (Google Places, independent of Overpass)
  2. Highway or high-volume road FAIL — requires Overpass to have been responsive

Usage:
  python scripts/find_demo_addresses.py              # Query existing DB
  python scripts/find_demo_addresses.py --evaluate  # Run batch eval on candidate addresses
"""

import json
import os
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Candidate addresses likely to trigger health findings (from reference_addresses.json)
CANDIDATE_ADDRESSES = [
    # Gas station candidates (Google Places — most reliable)
    "655 East Tremont Avenue, Bronx, NY 10457",  # Tremont Ave commercial strip
    "1200 East Colfax Avenue, Denver, CO 80218",  # Colfax Ave, "longest commercial street"
    # Road proximity candidates (Overpass — need to run when Overpass is up)
    "20 Whistler Road, Blue Hill, ME 04614",     # Route 15 / 172 corridor
    "100 Route 22, Armonk, NY 10504",            # Route 22 corridor
    "500 Hutchinson River Parkway, Bronx, NY",    # Hutchinson River Parkway
]


def get_db_path():
    return os.environ.get("NESTCHECK_DB_PATH", "nestcheck.db")


def query_snapshots_with_findings():
    """Query DB for snapshots where Gas station, Highway, or High-volume road = FAIL or WARNING."""
    db_path = get_db_path()
    if not os.path.exists(db_path):
        print(f"No database at {db_path}. Run evaluations first.")
        return []

    import sqlite3
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT snapshot_id, address_input, address_norm, created_at, result_json FROM snapshots"
    ).fetchall()
    conn.close()

    results = []
    for row in rows:
        try:
            result = json.loads(row["result_json"])
        except (json.JSONDecodeError, TypeError):
            continue

        tier1 = result.get("tier1_checks", [])
        findings = []
        for c in tier1:
            name = c.get("name", "")
            res = c.get("result", "")
            if name in ("Gas station", "Highway", "High-volume road") and res in ("FAIL", "WARNING"):
                findings.append({"name": name, "result": res, "details": c.get("details", "")})

        if findings:
            results.append({
                "snapshot_id": row["snapshot_id"],
                "address_input": row["address_input"],
                "address_norm": row["address_norm"],
                "created_at": row["created_at"],
                "findings": findings,
            })

    return results


def run_batch_evaluate():
    """Run evaluations on candidate addresses. Requires GOOGLE_MAPS_API_KEY."""
    api_key = os.environ.get("GOOGLE_MAPS_API_KEY")
    if not api_key:
        print("GOOGLE_MAPS_API_KEY required for --evaluate. Set in .env or environment.")
        return

    from property_evaluator import PropertyListing, evaluate_property, CheckResult

    print("Evaluating candidate addresses (this may take a few minutes)...\n")
    for addr in CANDIDATE_ADDRESSES:
        print(f"  {addr}")
        try:
            listing = PropertyListing(address=addr)
            result = evaluate_property(listing, api_key)
            tier1 = result.tier1_checks
            for c in tier1:
                if c.name in ("Gas station", "Highway", "High-volume road"):
                    status = "✓" if c.result == CheckResult.PASS else "✗" if c.result == CheckResult.FAIL else "?"
                    print(f"    {c.name}: {status} {c.result.value} — {c.details[:60]}...")
            # Check for any real finding
            has_finding = any(
                c.name in ("Gas station", "Highway", "High-volume road")
                and c.result in (CheckResult.FAIL, CheckResult.WARNING)
                for c in tier1
            )
            if has_finding:
                print(f"    >>> DEMO CANDIDATE: Has real health finding")
            print()
        except Exception as e:
            print(f"    Error: {e}\n")


def main():
    if "--evaluate" in sys.argv:
        run_batch_evaluate()
        return

    results = query_snapshots_with_findings()
    if not results:
        print("No snapshots with Gas station / Highway / High-volume road findings found.")
        print("\nTo discover demo addresses:")
        print("  1. Run: python scripts/find_demo_addresses.py --evaluate")
        print("     (Evaluates candidate addresses; requires GOOGLE_MAPS_API_KEY)")
        print("  2. Or evaluate addresses manually via the app, then re-run this script.")
        print("\nCandidate addresses to try:")
        for addr in CANDIDATE_ADDRESSES:
            print(f"  • {addr}")
        return

    print(f"Found {len(results)} snapshot(s) with health proximity findings:\n")
    for r in results:
        print(f"  {r['address_norm'] or r['address_input']}")
        print(f"  Snapshot: /s/{r['snapshot_id']}  |  Created: {r['created_at']}")
        for f in r["findings"]:
            print(f"    • {f['name']}: {f['result']} — {f['details'][:80]}...")
        print()


if __name__ == "__main__":
    main()
