#!/usr/bin/env python3
"""Verification script for Phase 5b-1: POLYGON and LINESTRING support."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from spatial_data import (
    create_facility_table,
    SpatialDataStore,
    _connect,
)


def main():
    store = SpatialDataStore()
    if not store.is_available():
        print("ERROR: Spatial DB not available")
        sys.exit(1)

    # --- Polygon tests ---
    print("Creating facilities_test_poly (POLYGON)...")
    create_facility_table("test_poly", geometry_type="POLYGON")
    conn = _connect()
    conn.execute(
        """
        INSERT INTO facilities_test_poly (name, geometry, metadata_json)
        VALUES ('Test', GeomFromText('POLYGON((-71.1 42.3, -71.0 42.3, -71.0 42.4, -71.1 42.4, -71.1 42.3))', 4326), '{}')
        """
    )
    conn.commit()
    conn.close()

    # Point inside polygon (Boston area)
    results = store.point_in_polygons(42.35, -71.05, "test_poly")
    assert len(results) == 1, f"Expected 1 polygon, got {len(results)}"
    assert results[0].name == "Test"
    assert results[0].distance_meters == 0.0
    print("  point_in_polygons(42.35, -71.05): OK — 1 polygon")

    # Point outside polygon (NYC)
    results = store.point_in_polygons(40.0, -74.0, "test_poly")
    assert len(results) == 0, f"Expected 0 polygons, got {len(results)}"
    print("  point_in_polygons(40.0, -74.0): OK — 0 polygons")

    # --- Line tests ---
    print("\nCreating facilities_test_line (LINESTRING)...")
    create_facility_table("test_line", geometry_type="LINESTRING")
    conn = _connect()
    conn.execute(
        """
        INSERT INTO facilities_test_line (name, geometry, metadata_json)
        VALUES ('Test Line', GeomFromText('LINESTRING(-71.1 42.3, -71.0 42.4)', 4326), '{}')
        """
    )
    conn.commit()
    conn.close()

    # Point near line (Boston area)
    nearest = store.nearest_line(42.35, -71.05, "test_line")
    assert nearest is not None
    assert nearest.name == "Test Line"
    assert nearest.distance_meters >= 0
    print(f"  nearest_line(42.35, -71.05): OK — {nearest.name}, {nearest.distance_meters:.0f} m")

    lines = store.lines_within(42.35, -71.05, 10000, "test_line")
    assert len(lines) == 1
    assert lines[0].name == "Test Line"
    print(f"  lines_within(42.35, -71.05, 10000): OK — 1 line")

    # Point far from line (NYC)
    lines = store.lines_within(40.0, -74.0, 1000, "test_line")
    assert len(lines) == 0
    print(f"  lines_within(40.0, -74.0, 1000): OK — 0 lines")

    # --- Cleanup ---
    print("\nCleaning up test tables...")
    conn = _connect()
    try:
        conn.execute("SELECT DisableSpatialIndex('facilities_test_poly', 'geometry')")
    except Exception:
        pass
    try:
        conn.execute("SELECT DiscardGeometryColumn('facilities_test_poly', 'geometry')")
    except Exception:
        pass
    conn.execute("DROP TABLE IF EXISTS facilities_test_poly")

    try:
        conn.execute("SELECT DisableSpatialIndex('facilities_test_line', 'geometry')")
    except Exception:
        pass
    try:
        conn.execute("SELECT DiscardGeometryColumn('facilities_test_line', 'geometry')")
    except Exception:
        pass
    conn.execute("DROP TABLE IF EXISTS facilities_test_line")

    conn.commit()
    conn.close()
    print("  Done.")

    print("\n=== Phase 5b-1 verification PASSED ===")


if __name__ == "__main__":
    main()
