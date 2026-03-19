#!/usr/bin/env python3
"""
Generate ground-truth test cases for schools spatial data lookups.

Tests two functions from property_evaluator.py:
  1. get_school_district() — point-in-polygon on facilities_school_districts
     + GEOID join to state_education_performance
  2. get_nearby_schools() — proximity search on facilities_nces_schools
     within 3219m (2 miles)

No API calls — everything comes from spatial.db.

Usage:
    python scripts/generate_ground_truth_schools.py
    python scripts/generate_ground_truth_schools.py --count 30 --seed 42
    python scripts/generate_ground_truth_schools.py --output data/ground_truth/schools.json
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
# Thresholds — canonical values from property_evaluator.py
# _NEARBY_SCHOOLS_RADIUS_M = 3219 (line ~3074)
# _NEARBY_SCHOOLS_MAX = 10 (line ~3075)
# ---------------------------------------------------------------------------
NEARBY_SCHOOLS_RADIUS_M = 3219  # 2 miles
NEARBY_SCHOOLS_MAX = 10

# Test distances in feet
CLOSE_FT = 500     # ~152m, well inside 3219m radius
FAR_FT = 15000     # ~4572m, well outside 3219m radius

FEET_TO_METERS = 0.3048

# Coordinate bounding box — covers NY, CT, NJ, MI
LAT_MIN, LAT_MAX = 38.0, 47.0
LNG_MIN, LNG_MAX = -90.0, -71.0


def _offset_point(lat: float, lng: float, distance_ft: float, bearing_deg: float):
    """Generate a point at distance_ft from (lat, lng) along bearing_deg.

    Uses simplified haversine offset (accurate for short distances).
    """
    distance_m = distance_ft * FEET_TO_METERS
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
        "/data/spatial.db",
    ]
    for p in candidates:
        if os.path.exists(p):
            return p
    return candidates[0]


def _load_spatialite(conn):
    """Load SpatiaLite extension on a connection."""
    try:
        conn.enable_load_extension(True)
        conn.load_extension("mod_spatialite")
    except Exception:
        pass


def _query_districts(db_path: str, count: int) -> list:
    """Query school district polygons from spatial.db.

    Returns list of dicts: {name, geoid, centroid_lat, centroid_lng, lograde, higrade}
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    _load_spatialite(conn)
    try:
        rows = conn.execute(
            """SELECT name,
                      Y(ST_Centroid(geometry)) as centroid_lat,
                      X(ST_Centroid(geometry)) as centroid_lng,
                      metadata_json
               FROM facilities_school_districts
               WHERE ST_Centroid(geometry) IS NOT NULL"""
        ).fetchall()

        districts = []
        for r in rows:
            lat, lng = r["centroid_lat"], r["centroid_lng"]
            if lat is None or lng is None:
                continue
            if not (LAT_MIN <= lat <= LAT_MAX and LNG_MIN <= lng <= LNG_MAX):
                continue
            meta = {}
            if r["metadata_json"]:
                try:
                    meta = json.loads(r["metadata_json"])
                except (json.JSONDecodeError, TypeError):
                    pass
            geoid = meta.get("geoid", "")
            if not geoid:
                continue
            districts.append({
                "name": r["name"] or "Unknown District",
                "geoid": geoid,
                "centroid_lat": lat,
                "centroid_lng": lng,
                "lograde": meta.get("lograde", ""),
                "higrade": meta.get("higrade", ""),
            })
        return districts
    finally:
        conn.close()


def _query_schools(db_path: str, count: int) -> list:
    """Query NCES school points from spatial.db.

    Returns list of dicts: {name, ncessch, lat, lng, level, metadata}
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    _load_spatialite(conn)
    try:
        rows = conn.execute(
            """SELECT name,
                      Y(geometry) as lat,
                      X(geometry) as lng,
                      metadata_json
               FROM facilities_nces_schools"""
        ).fetchall()

        schools = []
        for r in rows:
            lat, lng = r["lat"], r["lng"]
            if lat is None or lng is None:
                continue
            if not (LAT_MIN <= lat <= LAT_MAX and LNG_MIN <= lng <= LNG_MAX):
                continue
            meta = {}
            if r["metadata_json"]:
                try:
                    meta = json.loads(r["metadata_json"])
                except (json.JSONDecodeError, TypeError):
                    pass
            ncessch = str(meta.get("ncessch", ""))
            if not ncessch:
                continue
            schools.append({
                "name": r["name"] or "Unknown School",
                "ncessch": ncessch,
                "lat": lat,
                "lng": lng,
                "level": str(meta.get("level", "Other")),
                "metadata": meta,
            })
        return schools
    finally:
        conn.close()


def _check_performance_data(db_path: str, geoid: str) -> bool:
    """Check if state_education_performance has non-NULL data for this GEOID.

    Matches the validator's logic: at least one of graduation_rate_pct,
    ela_proficiency_pct, or math_proficiency_pct must be non-NULL.
    """
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            """SELECT graduation_rate_pct, ela_proficiency_pct,
                      math_proficiency_pct
               FROM state_education_performance WHERE geoid = ?""",
            (geoid,),
        ).fetchone()
        if not row:
            return False
        return any(v is not None for v in row)
    except Exception:
        return False
    finally:
        conn.close()


def _actual_containing_district(conn, lat: float, lng: float):
    """Find actual containing district at a point via ST_Contains.

    Returns (geoid, name) or (None, None).
    """
    try:
        row = conn.execute(
            """SELECT name, metadata_json
               FROM facilities_school_districts
               WHERE ROWID IN (
                   SELECT ROWID FROM SpatialIndex
                   WHERE f_table_name = 'facilities_school_districts'
                   AND f_geometry_column = 'geometry'
                   AND search_frame = MakePoint(?, ?, 4326)
               )
               AND ST_Contains(geometry, MakePoint(?, ?, 4326))
               LIMIT 1""",
            (lng, lat, lng, lat),
        ).fetchone()
        if row:
            meta = {}
            if row[1]:
                try:
                    meta = json.loads(row[1])
                except (json.JSONDecodeError, TypeError):
                    pass
            return (meta.get("geoid", ""), row[0] or "Unknown District")
        return (None, None)
    except Exception:
        return (None, None)


def _actual_nearby_school_ids(conn, lat: float, lng: float, radius_m: float) -> set:
    """Find NCESSCH IDs of schools within radius_m of (lat, lng)."""
    try:
        radius_deg = radius_m / 80000.0
        rows = conn.execute(
            """SELECT metadata_json
               FROM facilities_nces_schools
               WHERE ROWID IN (
                   SELECT ROWID FROM SpatialIndex
                   WHERE f_table_name = 'facilities_nces_schools'
                   AND f_geometry_column = 'geometry'
                   AND search_frame = BuildCircleMbr(?, ?, ?, 4326)
               )
               AND ST_Distance(geometry, MakePoint(?, ?, 4326), 1) <= ?""",
            (lng, lat, radius_deg, lng, lat, radius_m),
        ).fetchall()
        ids = set()
        for r in rows:
            if r[0]:
                try:
                    meta = json.loads(r[0])
                    ncessch = str(meta.get("ncessch", ""))
                    if ncessch:
                        ids.add(ncessch)
                except (json.JSONDecodeError, TypeError):
                    pass
        return ids
    except Exception:
        return set()


def main():
    parser = argparse.ArgumentParser(
        description="Generate ground-truth test cases for schools spatial lookups"
    )
    parser.add_argument(
        "--count", type=int, default=30,
        help="Number of districts/schools to sample per category (default: 30)",
    )
    parser.add_argument(
        "--output", type=str, default="data/ground_truth/schools.json",
        help="Output file path (default: data/ground_truth/schools.json)",
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
        sys.exit(1)

    print(f"Loading data from {db_path}...", flush=True)

    # ------------------------------------------------------------------
    # Category A: School District Containment
    # ------------------------------------------------------------------
    districts = _query_districts(db_path, args.count)
    if not districts:
        print("Error: No school districts found in spatial.db.", file=sys.stderr)
        sys.exit(1)
    print(f"Found {len(districts)} school districts.", flush=True)

    if args.count > len(districts):
        print(
            f"Warning: requested {args.count} districts but only "
            f"{len(districts)} available. Using all.",
            file=sys.stderr,
        )
        sampled_districts = districts
    else:
        sampled_districts = random.sample(districts, args.count)

    # ------------------------------------------------------------------
    # Category B: Nearby Schools Proximity
    # ------------------------------------------------------------------
    schools = _query_schools(db_path, args.count)
    if not schools:
        print("Error: No NCES schools found in spatial.db.", file=sys.stderr)
        sys.exit(1)
    print(f"Found {len(schools)} NCES schools.", flush=True)

    if args.count > len(schools):
        print(
            f"Warning: requested {args.count} schools but only "
            f"{len(schools)} available. Using all.",
            file=sys.stderr,
        )
        sampled_schools = schools
    else:
        sampled_schools = random.sample(schools, args.count)

    # Open SpatiaLite connection for nearest-neighbor validation
    nn_conn = sqlite3.connect(db_path)
    _load_spatialite(nn_conn)

    test_cases = []
    idx = 0
    adjusted_count = 0

    # ------------------------------------------------------------------
    # Generate district containment tests
    # ------------------------------------------------------------------
    print(
        f"Generating district containment tests from "
        f"{len(sampled_districts)} districts...",
        flush=True,
    )
    for district in sampled_districts:
        # INSIDE test: use polygon centroid
        idx += 1
        inside_lat = district["centroid_lat"]
        inside_lng = district["centroid_lng"]

        # Nearest-neighbor adjustment: check actual containing district
        actual_geoid, actual_name = _actual_containing_district(
            nn_conn, inside_lat, inside_lng
        )
        has_perf = _check_performance_data(db_path, district["geoid"])

        if actual_geoid is not None:
            # Centroid is inside some district
            if actual_geoid != district["geoid"]:
                adjusted_count += 1
            expected_geoid = actual_geoid
            expected_name = actual_name
            expected_found = True
            has_perf = _check_performance_data(db_path, actual_geoid)
            notes = "centroid"
            if actual_geoid != district["geoid"]:
                notes += (
                    f" (adjusted: centroid falls in district "
                    f"{actual_geoid}, not {district['geoid']})"
                )
        else:
            # Centroid is outside all district polygons (rare but possible
            # for irregular shapes)
            expected_geoid = None
            expected_name = None
            expected_found = False
            has_perf = False
            notes = "centroid (outside all polygons)"

        test_cases.append({
            "id": f"gt-schools-dist-{idx:04d}",
            "test_type": "district_containment",
            "coordinates": {
                "lat": round(inside_lat, 7),
                "lng": round(inside_lng, 7),
            },
            "expected": {
                "district_found": expected_found,
                "geoid": expected_geoid,
                "district_name": expected_name,
                "has_performance_data": has_perf,
            },
            "source": {
                "district_name": district["name"],
                "geoid": district["geoid"],
                "offset": notes,
            },
        })

        # OUTSIDE test: offset 50km (~164,042 ft) from centroid
        idx += 1
        far_distance_ft = 164042  # ~50km
        bearing = random.uniform(0, 360)
        outside_lat, outside_lng = _offset_point(
            district["centroid_lat"], district["centroid_lng"],
            far_distance_ft, bearing,
        )

        # Check if the outside point lands in a different district
        outside_geoid, outside_name = _actual_containing_district(
            nn_conn, outside_lat, outside_lng
        )
        if outside_geoid is not None:
            # Landed in another district
            outside_has_perf = _check_performance_data(db_path, outside_geoid)
            test_cases.append({
                "id": f"gt-schools-dist-{idx:04d}",
                "test_type": "district_containment",
                "coordinates": {
                    "lat": round(outside_lat, 7),
                    "lng": round(outside_lng, 7),
                },
                "expected": {
                    "district_found": True,
                    "geoid": outside_geoid,
                    "district_name": outside_name,
                    "has_performance_data": outside_has_perf,
                },
                "source": {
                    "district_name": district["name"],
                    "geoid": district["geoid"],
                    "offset": (
                        f"50km offset at bearing {bearing:.1f}deg "
                        f"(landed in {outside_geoid})"
                    ),
                },
            })
        else:
            # No district at offset point
            test_cases.append({
                "id": f"gt-schools-dist-{idx:04d}",
                "test_type": "district_containment",
                "coordinates": {
                    "lat": round(outside_lat, 7),
                    "lng": round(outside_lng, 7),
                },
                "expected": {
                    "district_found": False,
                    "geoid": None,
                    "district_name": None,
                    "has_performance_data": False,
                },
                "source": {
                    "district_name": district["name"],
                    "geoid": district["geoid"],
                    "offset": f"50km offset at bearing {bearing:.1f}deg (no district)",
                },
            })

    # ------------------------------------------------------------------
    # Generate nearby schools proximity tests
    # ------------------------------------------------------------------
    print(
        f"Generating nearby schools tests from "
        f"{len(sampled_schools)} schools...",
        flush=True,
    )
    test_distances = [
        ("close", CLOSE_FT, True),
        ("far", FAR_FT, False),
    ]

    for school in sampled_schools:
        for label, dist_ft, expect_in_results in test_distances:
            idx += 1
            bearing = random.uniform(0, 360)
            new_lat, new_lng = _offset_point(
                school["lat"], school["lng"], dist_ft, bearing,
            )

            # Nearest-neighbor adjustment: check if the source school
            # is actually within radius at the generated point
            actual_nearby_ids = _actual_nearby_school_ids(
                nn_conn, new_lat, new_lng, NEARBY_SCHOOLS_RADIUS_M,
            )
            actual_in_results = school["ncessch"] in actual_nearby_ids

            if actual_in_results != expect_in_results:
                adjusted_count += 1

            notes = (
                f"Generated {dist_ft}ft ({label}) from "
                f"{school['name']}"
            )
            if actual_in_results != expect_in_results:
                notes += (
                    f" (adjusted: school {'found' if actual_in_results else 'not found'}"
                    f" at generated point)"
                )

            test_cases.append({
                "id": f"gt-schools-nearby-{idx:04d}",
                "test_type": "nearby_schools",
                "coordinates": {
                    "lat": round(new_lat, 7),
                    "lng": round(new_lng, 7),
                },
                "expected": {
                    "source_school_in_results": actual_in_results,
                    "source_ncessch": school["ncessch"],
                },
                "source": {
                    "name": school["name"],
                    "ncessch": school["ncessch"],
                    "level": school["level"],
                    "coordinates": {
                        "lat": round(school["lat"], 7),
                        "lng": round(school["lng"], 7),
                    },
                    "distance_ft": dist_ft,
                    "bearing_deg": round(bearing, 2),
                    "notes": notes,
                },
            })

    nn_conn.close()

    # ------------------------------------------------------------------
    # Write output
    # ------------------------------------------------------------------
    output = {
        "_schema_version": "0.1.0",
        "_generated_at": datetime.now(timezone.utc).isoformat(),
        "_generator": "generate_ground_truth_schools.py",
        "_district_count": len(sampled_districts),
        "_school_count": len(sampled_schools),
        "_test_count": len(test_cases),
        "_thresholds": {
            "nearby_radius_m": NEARBY_SCHOOLS_RADIUS_M,
            "nearby_max": NEARBY_SCHOOLS_MAX,
            "close_ft": CLOSE_FT,
            "far_ft": FAR_FT,
            "source": "property_evaluator.py get_school_district() + get_nearby_schools()",
        },
        "test_cases": test_cases,
    }

    out_path = args.output
    if not os.path.isabs(out_path):
        project_root = os.path.dirname(
            os.path.dirname(os.path.abspath(__file__))
        )
        out_path = os.path.join(project_root, out_path)

    os.makedirs(os.path.dirname(out_path), exist_ok=True)

    with open(out_path, "w") as f:
        json.dump(output, f, indent=2)

    print(f"\nGenerated {len(test_cases)} test cases.")
    if adjusted_count:
        print(f"Adjusted {adjusted_count} expected results due to spatial overlap.")
    print(f"Output: {out_path}")

    # Quick breakdown
    by_type = {}
    for tc in test_cases:
        t = tc["test_type"]
        by_type[t] = by_type.get(t, 0) + 1
    for t, c in sorted(by_type.items()):
        print(f"  {t}: {c}")


if __name__ == "__main__":
    main()
