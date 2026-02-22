# Phase 5b-1 Status Report: POLYGON and LINESTRING Support

## Functions Added/Modified

### Modified

| Function | Signature | Change |
|----------|------------|--------|
| `create_facility_table` | `create_facility_table(facility_type, extra_columns="", geometry_type="POINT")` | Added `geometry_type` parameter. Valid values: `"POINT"`, `"POLYGON"`, `"LINESTRING"`, `"MULTILINESTRING"`, `"MULTIPOLYGON"`. Default `"POINT"` preserves backward compatibility. Raises `ValueError` for invalid geometry type. |

### Added

| Method | Signature | Purpose |
|--------|-----------|---------|
| `point_in_polygons` | `point_in_polygons(self, lat, lng, facility_type) -> List[FacilityRecord]` | Return all polygon features that contain the given point. Uses R-tree pre-filter with `MakePoint` as search_frame, then `ST_Contains` for exact test. |
| `nearest_line` | `nearest_line(self, lat, lng, facility_type, max_radius_meters=5000) -> Optional[FacilityRecord]` | Return the closest line feature within max_radius_meters. Delegates to `lines_within` and returns first result. |
| `lines_within` | `lines_within(self, lat, lng, radius_meters, facility_type) -> List[FacilityRecord]` | Return all line features within radius_meters of the point. Same R-tree + `ST_Distance` pattern as `find_facilities_within`. Uses `ST_Centroid(geometry)` for lat/lng (lines have no single point). |

## FacilityRecord

**No change.** `FacilityRecord` already has `distance_meters` and `distance_feet`. All new methods populate these fields:
- `point_in_polygons`: distance 0 (point is inside polygon)
- `lines_within` / `nearest_line`: `ST_Distance(geometry, MakePoint(...), 1)` in meters

For polygon/line geometry, `lat`/`lng` use `ST_Centroid(geometry)` as the representative point.

## Backward Compatibility

| Test | Result |
|------|--------|
| `tests/test_spatial_data.py` | PASSED — all existing POINT tests pass |
| `scripts/ingest_ust.py --state Massachusetts --limit 100` | Completed without error |
| `scripts/ingest_tri.py --limit 50` | Completed without error |
| `find_facilities_within(42.36, -71.06, 100000, "ust")` | Returns 36 facilities (expected; 100 MA records in Cape Cod area) |

`create_facility_table("ust")` and `create_facility_table("tri")` work unchanged (default `geometry_type="POINT"`).

## Polygon Test Results

| Test | Expected | Actual |
|------|----------|--------|
| `point_in_polygons(42.35, -71.05, "test_poly")` — point inside Boston-area square | 1 polygon | 1 polygon ✓ |
| `point_in_polygons(40.0, -74.0, "test_poly")` — point in NYC | 0 polygons | 0 polygons ✓ |

Test polygon: `POLYGON((-71.1 42.3, -71.0 42.3, -71.0 42.4, -71.1 42.4, -71.1 42.3))`

## Line Test Results

| Test | Expected | Actual |
|------|----------|--------|
| `nearest_line(42.35, -71.05, "test_line")` | 1 line with distance | Test Line, 0 m ✓ |
| `lines_within(42.35, -71.05, 10000, "test_line")` | 1 line | 1 line ✓ |
| `lines_within(40.0, -74.0, 1000, "test_line")` | 0 lines | 0 lines ✓ |

Test line: `LINESTRING(-71.1 42.3, -71.0 42.4)`. Point (42.35, -71.05) lies on the line segment, hence 0 m distance.

## SpatiaLite Quirks

- **R-tree search_frame for point-in-polygon:** Using `MakePoint(lng, lat, 4326)` as `search_frame` works. SpatiaLite's SpatialIndex returns geometries whose MBR intersects the search_frame envelope; for a point, that yields polygons whose MBR contains the point.
- **DisableSpatialIndex / DiscardGeometryColumn:** On first run (no existing table), these emit "error" messages but are caught and ignored. Expected behavior.
- **ST_Centroid for lines:** Works for LINESTRING. For MULTILINESTRING, SpatiaLite returns the centroid of the combined geometry.

## Cleanup

Test tables `facilities_test_poly` and `facilities_test_line` were dropped after verification. Verification script: `scripts/verify_phase5b1.py` (can be re-run for regression).
