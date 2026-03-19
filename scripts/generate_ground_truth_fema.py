#!/usr/bin/env python3
"""
Generate ground-truth test cases for FEMA flood zone containment checks.

Samples real FEMA NFHL polygons from spatial.db and creates test points
inside (centroid) and outside (offset beyond bbox) polygon boundaries
with known expected results.

Unlike UST/HPMS (distance-based), this is polygon containment:
  - Inside Zone A*/V*   → FAIL
  - Inside Zone X shaded → WARNING
  - Outside all polygons  → PASS (if nearby data exists)

No API calls — everything comes from spatial.db.

Usage:
    python scripts/generate_ground_truth_fema.py
    python scripts/generate_ground_truth_fema.py --count 50
    python scripts/generate_ground_truth_fema.py --seed 42
    python scripts/generate_ground_truth_fema.py --output data/ground_truth/fema.json
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
# Zone classification — mirrors property_evaluator.py check_flood_zones()
# at approximately lines 2430-2438.
# Zone A*/V* = FAIL (Special Flood Hazard Area)
# Zone X shaded = WARNING (moderate risk)
# Everything else = PASS
# ---------------------------------------------------------------------------

# Distance for "outside" test points: offset from polygon bbox corner
# in meters. Must be far enough to guarantee the point is outside the
# polygon AND outside any neighboring flood zone polygon.
OUTSIDE_OFFSET_M = 500


def _classify_zone(fld_zone: str, zone_subtype: str) -> tuple:
    """Classify a FEMA flood zone into expected result.

    Returns (expected_result, expected_pass, zone_label).
    Mirrors the logic in check_flood_zones().
    """
    if fld_zone.startswith("A") or fld_zone.startswith("V"):
        return ("FAIL", False, f"Zone {fld_zone} (SFHA)")
    if (
        fld_zone.startswith("X")
        and zone_subtype
        and "SHADED" in zone_subtype.upper()
    ):
        return ("WARNING", False, "Zone X shaded (moderate risk)")
    # Zone X unshaded, Zone D, etc. — not flagged by check_flood_zones()
    return (None, None, None)  # Skip — these aren't testable as FAIL/WARNING


def _highest_severity(containing_zones: list) -> str:
    """Return the highest severity result for a list of containing zones.

    Args:
        containing_zones: list of (fld_zone, zone_subtype) tuples from
            _point_in_any_polygon().

    Returns "FAIL", "WARNING", or "PASS" using the same precedence as
    check_flood_zones(): A*/V* > X-shaded > everything else.
    """
    has_fail = any(
        z.startswith("A") or z.startswith("V")
        for z, _ in containing_zones
    )
    if has_fail:
        return "FAIL"
    has_warning = any(
        z.startswith("X") and st and "SHADED" in st.upper()
        for z, st in containing_zones
    )
    if has_warning:
        return "WARNING"
    return "PASS"


def _offset_point(lat: float, lng: float, distance_m: float, bearing_deg: float):
    """Generate a point at distance_m from (lat, lng) along bearing_deg."""
    bearing_rad = math.radians(bearing_deg)
    lat_rad = math.radians(lat)

    dlat = (distance_m / 111320.0) * math.cos(bearing_rad)
    dlng = (distance_m / (111320.0 * math.cos(lat_rad))) * math.sin(bearing_rad)

    return (lat + dlat, lng + dlng)


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


def _query_polygons(db_path: str) -> list:
    """Query facilities_fema_nfhl from spatial.db.

    Returns list of dicts with centroid, bbox, and zone metadata.
    Only returns polygons with testable zones (A*/V*/X-shaded).
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        conn.enable_load_extension(True)
        conn.load_extension("mod_spatialite")
    except Exception:
        pass

    try:
        rows = conn.execute(
            """SELECT
                    name,
                    Y(ST_Centroid(geometry)) as centroid_lat,
                    X(ST_Centroid(geometry)) as centroid_lng,
                    MbrMinY(geometry) as min_lat,
                    MbrMaxY(geometry) as max_lat,
                    MbrMinX(geometry) as min_lng,
                    MbrMaxX(geometry) as max_lng,
                    metadata_json
                FROM facilities_fema_nfhl"""
        ).fetchall()

        polygons = []
        for r in rows:
            clat, clng = r["centroid_lat"], r["centroid_lng"]
            if clat is None or clng is None:
                continue
            # Continental US sanity check
            if not (24.0 <= clat <= 50.0 and -125.0 <= clng <= -66.0):
                continue

            meta = {}
            if r["metadata_json"]:
                try:
                    meta = json.loads(r["metadata_json"])
                except (json.JSONDecodeError, TypeError):
                    pass

            fld_zone = meta.get("fld_zone", "")
            zone_subtype = meta.get("zone_subtype", "")

            # Only keep polygons with testable zones
            expected_result, expected_pass, zone_label = _classify_zone(
                fld_zone, zone_subtype
            )
            if expected_result is None:
                continue

            polygons.append({
                "name": r["name"] or f"FEMA Zone {fld_zone}",
                "centroid_lat": clat,
                "centroid_lng": clng,
                "min_lat": r["min_lat"],
                "max_lat": r["max_lat"],
                "min_lng": r["min_lng"],
                "max_lng": r["max_lng"],
                "fld_zone": fld_zone,
                "zone_subtype": zone_subtype,
                "expected_result": expected_result,
                "expected_pass": expected_pass,
                "zone_label": zone_label,
                "metadata": meta,
            })
        return polygons
    finally:
        conn.close()


def _point_in_any_polygon(conn, lat: float, lng: float) -> list:
    """Check if a point is inside any FEMA polygon.

    Returns list of (fld_zone, zone_subtype) tuples for all containing
    polygons, or empty list if outside all.
    """
    try:
        rows = conn.execute(
            """SELECT metadata_json
                FROM facilities_fema_nfhl
                WHERE ROWID IN (
                    SELECT ROWID FROM SpatialIndex
                    WHERE f_table_name = 'facilities_fema_nfhl'
                    AND f_geometry_column = 'geometry'
                    AND search_frame = MakePoint(?, ?, 4326)
                )
                AND ST_Contains(geometry, MakePoint(?, ?, 4326))""",
            (lng, lat, lng, lat),
        ).fetchall()

        results = []
        for r in rows:
            meta = {}
            if r[0]:
                try:
                    meta = json.loads(r[0])
                except (json.JSONDecodeError, TypeError):
                    pass
            results.append((
                meta.get("fld_zone", ""),
                meta.get("zone_subtype", ""),
            ))
        return results
    except Exception:
        return []


def main():
    parser = argparse.ArgumentParser(
        description="Generate ground-truth test cases for FEMA flood zone checks"
    )
    parser.add_argument(
        "--count", type=int, default=50,
        help="Number of polygons to sample (default: 50)",
    )
    parser.add_argument(
        "--output", type=str, default="data/ground_truth/fema.json",
        help="Output file path (default: data/ground_truth/fema.json)",
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

    print(f"Loading FEMA NFHL polygons from {db_path}...", flush=True)

    polygons = _query_polygons(db_path)

    if not polygons:
        print("Error: No testable FEMA NFHL polygons found.", file=sys.stderr)
        sys.exit(1)

    # Separate by zone type for balanced sampling
    fail_polygons = [p for p in polygons if p["expected_result"] == "FAIL"]
    warning_polygons = [p for p in polygons if p["expected_result"] == "WARNING"]

    print(
        f"Found {len(polygons)} testable polygons "
        f"({len(fail_polygons)} FAIL zones, "
        f"{len(warning_polygons)} WARNING zones).",
        flush=True,
    )

    # Sample: aim for ~60% FAIL, ~40% WARNING to get good coverage of both
    fail_count = min(len(fail_polygons), int(args.count * 0.6))
    warning_count = min(len(warning_polygons), args.count - fail_count)
    # Fill remainder from FAIL if WARNING is short
    if fail_count + warning_count < args.count:
        fail_count = min(len(fail_polygons), args.count - warning_count)

    sampled_fail = random.sample(fail_polygons, fail_count) if fail_count else []
    sampled_warning = (
        random.sample(warning_polygons, warning_count) if warning_count else []
    )
    sampled = sampled_fail + sampled_warning
    random.shuffle(sampled)

    total_expected = len(sampled) * 2  # 2 test points per polygon: inside + outside
    print(
        f"Sampled {len(sampled)} polygons "
        f"({len(sampled_fail)} FAIL, {len(sampled_warning)} WARNING). "
        f"Generating {total_expected} test points...",
        flush=True,
    )

    # Open a SpatiaLite connection for containment verification
    nn_conn = sqlite3.connect(db_path)
    try:
        nn_conn.enable_load_extension(True)
        nn_conn.load_extension("mod_spatialite")
    except Exception:
        nn_conn = None

    addresses = []
    idx = 0
    adjusted_count = 0

    for poly in sampled:
        # --- Inside point: use centroid ---
        idx += 1
        inside_lat = poly["centroid_lat"]
        inside_lng = poly["centroid_lng"]

        # Verify the centroid is actually inside a polygon
        # (it should be, but irregular shapes can have centroids outside)
        inside_expected = poly["expected_result"]
        inside_pass = poly["expected_pass"]
        inside_notes = f"centroid of {poly['zone_label']}"

        if nn_conn is not None:
            containing = _point_in_any_polygon(nn_conn, inside_lat, inside_lng)
            if containing:
                actual_expected = _highest_severity(containing)

                if actual_expected != inside_expected:
                    adjusted_count += 1
                    inside_expected = actual_expected
                    inside_pass = actual_expected == "PASS"
                    inside_notes += (
                        f" (adjusted: centroid is in "
                        f"{', '.join(z for z, _ in containing)})"
                    )
            else:
                # Centroid is outside all polygons — irregular shape
                adjusted_count += 1
                inside_expected = "PASS"
                inside_pass = True
                inside_notes += " (adjusted: centroid outside polygon boundary)"

        addresses.append({
            "id": f"gt-fema-{idx:04d}",
            "coordinates": {
                "lat": round(inside_lat, 7),
                "lng": round(inside_lng, 7),
            },
            "layer": 4,
            "layer_notes": (
                f"Synthetic — centroid of {poly['name']} "
                f"({poly['zone_label']})"
            ),
            "source_polygon": {
                "name": poly["name"],
                "fld_zone": poly["fld_zone"],
                "zone_subtype": poly["zone_subtype"],
                "zone_label": poly["zone_label"],
                "centroid": {
                    "lat": round(poly["centroid_lat"], 7),
                    "lng": round(poly["centroid_lng"], 7),
                },
                "position": "inside",
            },
            "tier1_health_checks": {
                "flood_zone": {
                    "expected_result": inside_expected,
                    "expected_pass": inside_pass,
                    "notes": inside_notes,
                    "source": "synthetic from spatial.db facilities_fema_nfhl",
                },
            },
            "tier2_scored_dimensions": {},
        })

        # --- Outside point: offset well beyond bbox ---
        idx += 1
        # Pick a random direction and offset from the nearest bbox corner
        bearing = random.uniform(0, 360)
        # Use the bbox corner farthest in the offset direction
        corner_lat = (
            poly["max_lat"] if bearing < 180 else poly["min_lat"]
        )
        corner_lng = (
            poly["max_lng"] if 90 < bearing < 270 else poly["min_lng"]
        )
        outside_lat, outside_lng = _offset_point(
            corner_lat, corner_lng, OUTSIDE_OFFSET_M, bearing
        )

        outside_expected = "PASS"
        outside_pass = True
        outside_notes = (
            f"{OUTSIDE_OFFSET_M}m outside bbox of "
            f"{poly['zone_label']}"
        )

        # Verify the outside point isn't accidentally inside another polygon
        if nn_conn is not None:
            containing = _point_in_any_polygon(
                nn_conn, outside_lat, outside_lng
            )
            if containing:
                actual_severity = _highest_severity(containing)
                if actual_severity != "PASS":
                    adjusted_count += 1
                    outside_expected = actual_severity
                    outside_pass = False
                    outside_notes += (
                        f" (adjusted: landed in "
                        f"{', '.join(z for z, _ in containing)})"
                    )

        addresses.append({
            "id": f"gt-fema-{idx:04d}",
            "coordinates": {
                "lat": round(outside_lat, 7),
                "lng": round(outside_lng, 7),
            },
            "layer": 4,
            "layer_notes": (
                f"Synthetic — {OUTSIDE_OFFSET_M}m outside "
                f"{poly['name']} ({poly['zone_label']})"
            ),
            "source_polygon": {
                "name": poly["name"],
                "fld_zone": poly["fld_zone"],
                "zone_subtype": poly["zone_subtype"],
                "zone_label": poly["zone_label"],
                "centroid": {
                    "lat": round(poly["centroid_lat"], 7),
                    "lng": round(poly["centroid_lng"], 7),
                },
                "position": "outside",
                "offset_m": OUTSIDE_OFFSET_M,
                "bearing_deg": round(bearing, 2),
            },
            "tier1_health_checks": {
                "flood_zone": {
                    "expected_result": outside_expected,
                    "expected_pass": outside_pass,
                    "notes": outside_notes,
                    "source": "synthetic from spatial.db facilities_fema_nfhl",
                },
            },
            "tier2_scored_dimensions": {},
        })

    if nn_conn is not None:
        nn_conn.close()

    output = {
        "_schema_version": "0.1.0",
        "_generated_at": datetime.now(timezone.utc).isoformat(),
        "_generator": "generate_ground_truth_fema.py",
        "_polygon_count": len(sampled),
        "_test_count": len(addresses),
        "_thresholds": {
            "zone_a_v": "FAIL (Special Flood Hazard Area)",
            "zone_x_shaded": "WARNING (moderate risk)",
            "outside": "PASS",
            "source": "property_evaluator.py check_flood_zones()",
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

    print(f"\nGenerated {len(addresses)} test points from "
          f"{len(sampled)} polygons.")
    if adjusted_count:
        print(f"Adjusted {adjusted_count} expected results via containment check.")
    print(f"Output: {out_path}")

    # Quick breakdown
    by_result = {}
    for a in addresses:
        r = a["tier1_health_checks"]["flood_zone"]["expected_result"]
        by_result[r] = by_result.get(r, 0) + 1
    for r, c in sorted(by_result.items()):
        print(f"  {r}: {c}")


if __name__ == "__main__":
    main()
