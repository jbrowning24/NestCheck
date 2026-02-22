#!/usr/bin/env python3
"""Test SpatialDataStore with synthetic facility data."""

import os
import sys
import json
import tempfile

# Point to a temp DB for testing
TEST_DB = os.path.join(tempfile.gettempdir(), "test_spatial.db")
os.environ["NESTCHECK_SPATIAL_DB_PATH"] = TEST_DB

# Clean up any previous test DB
if os.path.exists(TEST_DB):
    os.remove(TEST_DB)

# Add project root to path so we can import spatial_data
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from spatial_data import (
    SpatialDataStore, init_spatial_db, create_facility_table, _connect
)


def test_basic_spatial_queries():
    # Initialize DB
    init_spatial_db()
    create_facility_table("ust")

    # Insert 3 synthetic gas stations around lower Manhattan
    conn = _connect()
    stations = [
        ("Station A", -74.0060, 40.7128, {"status": "active"}),
        ("Station B", -74.0050, 40.7138, {"status": "active"}),
        ("Station C", -73.9900, 40.7200, {"status": "closed"}),
    ]
    for name, lng, lat, meta in stations:
        conn.execute(
            """INSERT INTO facilities_ust (name, geometry, metadata_json)
               VALUES (?, MakePoint(?, ?, 4326), ?)""",
            (name, lng, lat, json.dumps(meta)),
        )
    conn.commit()
    conn.close()

    store = SpatialDataStore()
    assert store.is_available(), "SpatialDataStore should be available"

    # Test find_facilities_within — 500m radius
    results = store.find_facilities_within(40.7128, -74.0060, 500, "ust")
    assert len(results) == 2, f"Expected 2 within 500m, got {len(results)}"
    assert results[0].name == "Station A", "Nearest should be Station A"
    assert results[0].distance_meters < 10, "Station A should be very close"
    assert results[1].name == "Station B", "Second should be Station B"

    # Test nearest_facility
    nearest = store.nearest_facility(40.7128, -74.0060, "ust")
    assert nearest is not None
    assert nearest.name == "Station A"

    # Test facility_count_within
    count_500 = store.facility_count_within(40.7128, -74.0060, 500, "ust")
    assert count_500 == 2
    count_2000 = store.facility_count_within(40.7128, -74.0060, 2000, "ust")
    assert count_2000 == 3

    # Test graceful degradation — missing table
    results_missing = store.find_facilities_within(
        40.7128, -74.0060, 500, "nonexistent"
    )
    assert results_missing == [], "Missing table should return empty list"

    print("ALL TESTS PASSED")

    # Cleanup
    os.remove(TEST_DB)


if __name__ == "__main__":
    test_basic_spatial_queries()
