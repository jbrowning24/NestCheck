#!/usr/bin/env python3
"""
Generate ground-truth test cases for SEMS Superfund NPL containment checks.

Samples real SEMS facility polygons from spatial.db and creates test points
inside NPL sites (FAIL), outside all sites (PASS), and inside non-NPL sites
(PASS) with known expected results.

Unlike UST/HPMS (distance-based), this is polygon containment:
  - Inside NPL site (npl_status F/P)     → FAIL
  - Outside all SEMS polygons             → PASS
  - Inside non-NPL site                   → PASS

No API calls — everything comes from spatial.db.

Usage:
    python scripts/generate_ground_truth_sems.py
    python scripts/generate_ground_truth_sems.py --count 30
    python scripts/generate_ground_truth_sems.py --seed 42
    python scripts/generate_ground_truth_sems.py --output data/ground_truth/sems.json
"""

import argparse
import json
import math
import os
import random
import sqlite3
import sys
from datetime import datetime, timezone

# Project root for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ---------------------------------------------------------------------------
# NPL status classification — mirrors property_evaluator.py check_superfund_npl()
# at approximately line 2479. NPL status codes "F" (Final) and "P" (Proposed)
# trigger FAIL. Everything else is not on the NPL → no fail.
# ---------------------------------------------------------------------------
NPL_STATUS_CODES = ("F", "P")


def _find_spatial_db() -> str:
    """Locate spatial.db using the same resolution as spatial_data.py."""
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    candidates = [
        os.path.join(project_root, "data", "spatial.db"),
        os.path.join(project_root, "spatial.db"),
        "/data/spatial.db",  # Railway volume mount
    ]
    for p in candidates:
        if os.path.exists(p):
            return p
    return candidates[0]  # Return default for error message


def _offset_point(lat: float, lng: float, distance_m: float, bearing_deg: float):
    """Generate a point at distance_m from (lat, lng) along bearing_deg.

    Uses simplified haversine offset (accurate for short distances).
    """
    bearing_rad = math.radians(bearing_deg)
    lat_rad = math.radians(lat)

    dlat = (distance_m / 111320.0) * math.cos(bearing_rad)
    dlng = (distance_m / (111320.0 * math.cos(lat_rad))) * math.sin(bearing_rad)

    return (lat + dlat, lng + dlng)


def _query_facilities(conn, is_npl: bool, state_filter: str = None) -> list:
    """Query facilities_sems from spatial.db.

    Returns list of dicts with inside-point coords, centroid, bbox, and metadata.
    """
    if is_npl:
        npl_clause = (
            "json_extract(metadata_json, '$.npl_status_code') IN ('F', 'P')"
        )
    else:
        npl_clause = (
            "(json_extract(metadata_json, '$.npl_status_code') NOT IN ('F', 'P') "
            "OR json_extract(metadata_json, '$.npl_status_code') IS NULL)"
        )

    state_clause = ""
    params = []
    if state_filter:
        state_clause = (
            " AND json_extract(metadata_json, '$.state_code') = ?"
        )
        params.append(state_filter.upper())

    sql = f"""SELECT
                name,
                metadata_json,
                Y(ST_PointOnSurface(geometry)) as inside_lat,
                X(ST_PointOnSurface(geometry)) as inside_lng,
                Y(ST_Centroid(geometry)) as centroid_lat,
                X(ST_Centroid(geometry)) as centroid_lng,
                MbrMinY(geometry) as min_lat,
                MbrMaxY(geometry) as max_lat,
                MbrMinX(geometry) as min_lng,
                MbrMaxX(geometry) as max_lng
            FROM facilities_sems
            WHERE {npl_clause}{state_clause}"""

    rows = conn.execute(sql, params).fetchall()

    facilities = []
    for r in rows:
        inside_lat = r["inside_lat"]
        inside_lng = r["inside_lng"]
        if inside_lat is None or inside_lng is None:
            continue
        # Continental US sanity check
        if not (24.0 <= inside_lat <= 50.0 and -125.0 <= inside_lng <= -66.0):
            continue

        meta = {}
        if r["metadata_json"]:
            try:
                meta = json.loads(r["metadata_json"])
            except (json.JSONDecodeError, TypeError):
                pass

        facilities.append({
            "name": r["name"] or meta.get("site_name", "Unknown SEMS Site"),
            "inside_lat": inside_lat,
            "inside_lng": inside_lng,
            "centroid_lat": r["centroid_lat"],
            "centroid_lng": r["centroid_lng"],
            "min_lat": r["min_lat"],
            "max_lat": r["max_lat"],
            "min_lng": r["min_lng"],
            "max_lng": r["max_lng"],
            "metadata": meta,
        })
    return facilities


def _point_in_any_npl_polygon(conn, lat: float, lng: float) -> bool:
    """Check if a point is inside any NPL (F/P) SEMS polygon."""
    try:
        row = conn.execute(
            """SELECT COUNT(*) FROM facilities_sems
                WHERE ROWID IN (
                    SELECT ROWID FROM SpatialIndex
                    WHERE f_table_name = 'facilities_sems'
                    AND f_geometry_column = 'geometry'
                    AND search_frame = MakePoint(?, ?, 4326)
                )
                AND ST_Contains(geometry, MakePoint(?, ?, 4326))
                AND json_extract(metadata_json, '$.npl_status_code') IN ('F', 'P')""",
            (lng, lat, lng, lat),
        ).fetchone()
        return row[0] > 0 if row else False
    except Exception:
        return False


def _point_in_any_sems_polygon(conn, lat: float, lng: float) -> bool:
    """Check if a point is inside ANY SEMS polygon (NPL or non-NPL)."""
    try:
        row = conn.execute(
            """SELECT COUNT(*) FROM facilities_sems
                WHERE ROWID IN (
                    SELECT ROWID FROM SpatialIndex
                    WHERE f_table_name = 'facilities_sems'
                    AND f_geometry_column = 'geometry'
                    AND search_frame = MakePoint(?, ?, 4326)
                )
                AND ST_Contains(geometry, MakePoint(?, ?, 4326))""",
            (lng, lat, lng, lat),
        ).fetchone()
        return row[0] > 0 if row else False
    except Exception:
        return False


def _point_inside_facility(conn, lat: float, lng: float, facility_name: str) -> bool:
    """Verify a point is inside the specific facility polygon (sanity check)."""
    try:
        row = conn.execute(
            """SELECT COUNT(*) FROM facilities_sems
                WHERE name = ?
                AND ST_Contains(geometry, MakePoint(?, ?, 4326))""",
            (facility_name, lng, lat),
        ).fetchone()
        return row[0] > 0 if row else False
    except Exception:
        return False


def _bbox_diagonal_m(fac: dict) -> float:
    """Compute the bounding box diagonal in approximate meters."""
    dlat = fac["max_lat"] - fac["min_lat"]
    dlng = fac["max_lng"] - fac["min_lng"]
    # Convert degrees to approximate meters at the facility latitude
    mid_lat = (fac["min_lat"] + fac["max_lat"]) / 2.0
    lat_m = dlat * 111320.0
    lng_m = dlng * 111320.0 * math.cos(math.radians(mid_lat))
    return math.sqrt(lat_m ** 2 + lng_m ** 2)


def main():
    parser = argparse.ArgumentParser(
        description="Generate ground-truth test cases for SEMS Superfund NPL checks"
    )
    parser.add_argument(
        "--count", type=int, default=30,
        help="Number of facilities to sample per category (default: 30)",
    )
    parser.add_argument(
        "--state", type=str, default=None,
        help="Filter by state abbreviation (e.g., NY, NJ, CT)",
    )
    parser.add_argument(
        "--output", type=str, default="data/ground_truth/sems.json",
        help="Output file path (default: data/ground_truth/sems.json)",
    )
    parser.add_argument(
        "--seed", type=int, default=None,
        help="Random seed for reproducibility",
    )
    args = parser.parse_args()

    if args.seed is not None:
        random.seed(args.seed)

    db_path = _find_spatial_db()
    if not os.path.exists(db_path):
        print(f"Error: spatial.db not found at {db_path}", file=sys.stderr)
        print("Run ingest scripts first or set correct path.", file=sys.stderr)
        sys.exit(1)

    # Open SpatiaLite connection
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        conn.enable_load_extension(True)
        conn.load_extension("mod_spatialite")
    except Exception as e:
        print(f"Error loading SpatiaLite: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"Loading SEMS facilities from {db_path}...", flush=True)

    npl_facilities = _query_facilities(conn, is_npl=True, state_filter=args.state)
    non_npl_facilities = _query_facilities(conn, is_npl=False, state_filter=args.state)

    print(
        f"Found {len(npl_facilities)} NPL facilities, "
        f"{len(non_npl_facilities)} non-NPL facilities.",
        flush=True,
    )

    if not npl_facilities:
        state_msg = f" for state '{args.state}'" if args.state else ""
        print(f"Error: No NPL facilities found{state_msg}.", file=sys.stderr)
        sys.exit(1)

    # Sampling: split --count across 3 categories
    # Category 1 (inside NPL): ~40% of count
    # Category 2 (outside): ~40% of count (one per NPL site, for pairing)
    # Category 3 (inside non-NPL): ~20% of count
    cat1_count = max(1, int(args.count * 0.4))
    cat2_count = cat1_count  # One outside point per inside-NPL site
    cat3_count = max(1, args.count - cat1_count - cat2_count)

    # Sample NPL facilities for categories 1 and 2
    npl_sample_count = min(cat1_count, len(npl_facilities))
    sampled_npl = random.sample(npl_facilities, npl_sample_count)

    # Sample non-NPL facilities for category 3
    non_npl_sample_count = min(cat3_count, len(non_npl_facilities))
    sampled_non_npl = (
        random.sample(non_npl_facilities, non_npl_sample_count)
        if non_npl_sample_count > 0
        else []
    )

    total_expected = npl_sample_count * 2 + len(sampled_non_npl)
    print(
        f"Sampled {npl_sample_count} NPL + {len(sampled_non_npl)} non-NPL facilities. "
        f"Generating ~{total_expected} test points...",
        flush=True,
    )

    addresses = []
    idx = 0
    skipped_inside = 0
    skipped_outside = 0
    skipped_non_npl = 0

    # ---- Category 1: Inside NPL → FAIL ----
    for fac in sampled_npl:
        inside_lat = fac["inside_lat"]
        inside_lng = fac["inside_lng"]

        # Sanity check: verify the point is actually inside this polygon
        if not _point_inside_facility(conn, inside_lat, inside_lng, fac["name"]):
            print(
                f"  Warning: ST_PointOnSurface not inside polygon for "
                f"{fac['name']}, skipping.",
                file=sys.stderr,
            )
            skipped_inside += 1
            continue

        idx += 1
        meta = fac["metadata"]
        addresses.append({
            "id": f"gt-sems-{idx:04d}",
            "coordinates": {
                "lat": round(inside_lat, 7),
                "lng": round(inside_lng, 7),
            },
            "layer": 4,
            "layer_notes": (
                f"Synthetic — inside NPL Superfund site {fac['name']}"
            ),
            "source_facility": {
                "name": fac["name"],
                "epa_id": meta.get("epa_id", ""),
                "npl_status_code": meta.get("npl_status_code", ""),
                "containment_type": "inside_npl",
                "coordinates": {
                    "lat": round(fac["centroid_lat"], 7),
                    "lng": round(fac["centroid_lng"], 7),
                },
            },
            "tier1_health_checks": {
                "superfund_npl": {
                    "expected_result": "FAIL",
                    "expected_pass": False,
                    "notes": (
                        f"Point inside NPL site polygon "
                        f"({meta.get('npl_status_code', '?')})"
                    ),
                    "source": "synthetic from spatial.db facilities_sems",
                },
            },
            "tier2_scored_dimensions": {},
        })

    # ---- Category 2: Outside all SEMS polygons → PASS ----
    for fac in sampled_npl:
        centroid_lat = fac["centroid_lat"]
        centroid_lng = fac["centroid_lng"]
        offset_distance_m = 2.0 * _bbox_diagonal_m(fac)
        # Minimum offset: 500m to avoid tiny polygons landing nearby
        offset_distance_m = max(offset_distance_m, 500.0)

        success = False
        for attempt in range(5):
            bearing = random.uniform(0, 360)
            out_lat, out_lng = _offset_point(
                centroid_lat, centroid_lng, offset_distance_m, bearing
            )

            # Verify NOT inside ANY SEMS polygon
            if not _point_in_any_sems_polygon(conn, out_lat, out_lng):
                success = True
                break

        if not success:
            print(
                f"  Warning: Could not find outside point for {fac['name']} "
                f"after 5 attempts, skipping.",
                file=sys.stderr,
            )
            skipped_outside += 1
            continue

        idx += 1
        meta = fac["metadata"]
        addresses.append({
            "id": f"gt-sems-{idx:04d}",
            "coordinates": {
                "lat": round(out_lat, 7),
                "lng": round(out_lng, 7),
            },
            "layer": 4,
            "layer_notes": (
                f"Synthetic — outside all SEMS polygons, "
                f"offset from {fac['name']}"
            ),
            "source_facility": {
                "name": fac["name"],
                "epa_id": meta.get("epa_id", ""),
                "npl_status_code": meta.get("npl_status_code", ""),
                "containment_type": "outside",
                "coordinates": {
                    "lat": round(fac["centroid_lat"], 7),
                    "lng": round(fac["centroid_lng"], 7),
                },
            },
            "tier1_health_checks": {
                "superfund_npl": {
                    "expected_result": "PASS",
                    "expected_pass": True,
                    "notes": (
                        f"Point outside all SEMS polygons "
                        f"(offset {offset_distance_m:.0f}m from "
                        f"{fac['name']} at bearing {bearing:.0f}°)"
                    ),
                    "source": "synthetic from spatial.db facilities_sems",
                },
            },
            "tier2_scored_dimensions": {},
        })

    # ---- Category 3: Inside non-NPL → PASS ----
    for fac in sampled_non_npl:
        inside_lat = fac["inside_lat"]
        inside_lng = fac["inside_lng"]

        # Edge case: verify the point is NOT inside any NPL polygon
        # (overlapping polygons are possible)
        if _point_in_any_npl_polygon(conn, inside_lat, inside_lng):
            print(
                f"  Warning: Non-NPL site {fac['name']} point is inside "
                f"an NPL polygon (overlap), skipping.",
                file=sys.stderr,
            )
            skipped_non_npl += 1
            continue

        idx += 1
        meta = fac["metadata"]
        addresses.append({
            "id": f"gt-sems-{idx:04d}",
            "coordinates": {
                "lat": round(inside_lat, 7),
                "lng": round(inside_lng, 7),
            },
            "layer": 4,
            "layer_notes": (
                f"Synthetic — inside non-NPL SEMS site {fac['name']}"
            ),
            "source_facility": {
                "name": fac["name"],
                "epa_id": meta.get("epa_id", ""),
                "npl_status_code": meta.get("npl_status_code", "N/A"),
                "containment_type": "inside_non_npl",
                "coordinates": {
                    "lat": round(fac["centroid_lat"], 7),
                    "lng": round(fac["centroid_lng"], 7),
                },
            },
            "tier1_health_checks": {
                "superfund_npl": {
                    "expected_result": "PASS",
                    "expected_pass": True,
                    "notes": (
                        f"Point inside non-NPL site polygon "
                        f"(status: {meta.get('npl_status_code', 'N/A')})"
                    ),
                    "source": "synthetic from spatial.db facilities_sems",
                },
            },
            "tier2_scored_dimensions": {},
        })

    conn.close()

    # Count unique facilities used
    facility_names = set()
    for a in addresses:
        facility_names.add(a["source_facility"]["name"])

    output = {
        "_schema_version": "0.1.0",
        "_generated_at": datetime.now(timezone.utc).isoformat(),
        "_generator": "generate_ground_truth_sems.py",
        "_facility_count": len(facility_names),
        "_test_count": len(addresses),
        "_thresholds": {
            "containment": "polygon point-in-polygon",
            "npl_status_codes": list(NPL_STATUS_CODES),
            "source": "property_evaluator.py check_superfund_npl()",
        },
        "addresses": addresses,
    }

    # Ensure output directory exists
    out_path = args.output
    if not os.path.isabs(out_path):
        project_root = os.path.dirname(
            os.path.dirname(os.path.abspath(__file__))
        )
        out_path = os.path.join(project_root, out_path)

    os.makedirs(os.path.dirname(out_path), exist_ok=True)

    with open(out_path, "w") as f:
        json.dump(output, f, indent=2)

    # Summary
    print(f"\nGenerated {len(addresses)} test points from "
          f"{len(facility_names)} facilities.")
    if skipped_inside:
        print(f"Skipped {skipped_inside} inside-NPL points "
              f"(ST_PointOnSurface outside polygon).")
    if skipped_outside:
        print(f"Skipped {skipped_outside} outside points "
              f"(could not escape all polygons).")
    if skipped_non_npl:
        print(f"Skipped {skipped_non_npl} non-NPL points "
              f"(overlapping NPL polygon).")
    print(f"Output: {out_path}")

    # Breakdown by category and result
    by_type = {}
    by_result = {}
    for a in addresses:
        ct = a["source_facility"]["containment_type"]
        by_type[ct] = by_type.get(ct, 0) + 1
        r = a["tier1_health_checks"]["superfund_npl"]["expected_result"]
        by_result[r] = by_result.get(r, 0) + 1

    print("\nBy category:")
    for ct, c in sorted(by_type.items()):
        print(f"  {ct}: {c}")
    print("\nBy expected result:")
    for r, c in sorted(by_result.items()):
        print(f"  {r}: {c}")


if __name__ == "__main__":
    main()
