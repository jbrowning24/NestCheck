# Phase 5b-2b: HIFLD Transmission Line Ingestion — Status Report

## Files Created

- `scripts/ingest_hifld.py` — HIFLD electric power transmission line ingestion

## Record Count

| Metric | Value |
|--------|-------|
| Total ingested | 74,553 |
| Skipped (null geometry) | 0 |

Below expected ~94,000; API may have fewer records now or pagination changed.

## WKT Conversion Approach

- **Geometry type:** `MULTILINESTRING`
- **Table:** `create_facility_table("hifld", geometry_type="MULTILINESTRING")`
- **Conversion:** ArcGIS `paths` → `MULTILINESTRING((path1),(path2),...)`
- **Coordinates:** `[x,y]` = `[lng, lat]` preserved; rounded to 6 decimals
- **outSR=4326:** Critical — source is Web Mercator (102100)

## Proximity Test Results

| Test | Location | Result |
|------|----------|--------|
| **Hit** | Manhattan (40.7128, -74.0060), 2 km | 4 lines; nearest ~475 m (345 kV) |
| **Miss** | Grand Canyon area (36.5, -112.0), 5 km | 0 lines |

## VOLTAGE Range

| Metric | Value |
|--------|-------|
| Valid (>0 kV) | 2.5 – 1,000 kV (51,089 records) |
| Sentinel (unknown) | -999999 (23,464 records) |

## Pagination / Geometry

- Pagination: offset-based, 2,000 records per page; 38 pages for full ingest
- No geometry parsing issues; ArcGIS `paths` convert cleanly to MULTILINESTRING
- `--limit N` caps pages for testing

## Surprises

1. **Record count:** ~74.5K vs expected ~94K — dataset may have been updated
2. **VOLTAGE sentinel:** Many records use -999999 for unknown voltage; evaluation pipeline should filter at query time
3. **Name field:** "NOT AVAILABLE" appears for VOLT_CLASS/OWNER when missing

## Dataset Registry

```
facility_type: hifld
source_url: https://services2.arcgis.com/.../HIFLD_US_Electric_Power_Transmission_Lines/FeatureServer/0/query
record_count: 74553
```

## Spot-Check

Sample record: `345 - NOT AVAILABLE`, MULTILINESTRING with reasonable US coordinates; metadata includes `voltage`, `volt_class`, `owner`, `sub_1`, `sub_2`.
