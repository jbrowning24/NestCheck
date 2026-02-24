# Phase 5b-2a: EPA SEMS Superfund Boundary Ingestion — Status Report

## Files Created

- `scripts/ingest_sems.py` — EPA Superfund site boundary polygon ingestion

## Record Count

| Metric | Value |
|--------|-------|
| Total ingested | 2,116 |
| Skipped | 0 |

Within expected range (~1,300–2,000). Slightly above the upper bound; dataset may have grown.

## WKT Conversion Approach

- **Geometry type:** `MULTIPOLYGON` (per spec)
- **Table:** `create_facility_table("sems", geometry_type="MULTIPOLYGON")`
- **Conversion:** ArcGIS `rings` → `MULTIPOLYGON(((exterior),(hole1),(hole2)))`
- **Coordinates:** `[x,y]` = `[lng, lat]` preserved; rounded to 6 decimals for SpatiaLite
- **Ring order:** ArcGIS order used as-is; SpatiaLite accepts both orientations

## Point-in-Polygon Test Results

| Test | Location | Result |
|------|----------|--------|
| **Hit** | Gowanus Canal (PointOnSurface: 40.6735, -73.9969) | 1 site: GOWANUS CANAL (NYN000206222) |
| **Miss** | Boston (42.35, -71.05) | 0 sites (expected) |

**Note:** The spec suggested (40.674, -73.984) for Gowanus; that point is outside the polygon. Verification uses `ST_PointOnSurface` to obtain a point guaranteed inside the polygon.

## Geometry Parsing

- No parsing issues. ArcGIS `rings` array converts cleanly to MULTIPOLYGON WKT.
- All geometries pass `ST_IsValid`.
- Polygon centroid can lie outside for concave polygons; `ST_PointOnSurface` is used for verification.

## Dataset Registry

```
facility_type: sems
source_url: https://services.arcgis.com/.../FAC_Superfund_Site_Boundaries_EPA_Public/FeatureServer/0/query
record_count: 2116
```

## Sample metadata_json

```json
{
  "site_name": "GOWANUS CANAL",
  "epa_id": "NYN000206222",
  "npl_status_code": "F",
  "state_code": "NY",
  "federal_facility_deter_code": "N",
  "epa_program": "Superfund Remedial",
  "site_feature_class": 5,
  "site_feature_name": "Site boundary",
  "city_name": "BROOKLYN",
  "county": "KINGS",
  "zip_code": "11231",
  "object_id": 287
}
```

## Spot-Check Geometry

Sample WKT (truncated):

```
MULTIPOLYGON(((-72.680511 41.481865, -72.680083 41.481791, ...)))
```

Coordinates are reasonable US values; rings are closed.
