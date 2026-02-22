# Phase 5b-3: FHWA HPMS Traffic Count Ingestion — Status Report

## Files Created

- `scripts/ingest_hpms.py` — FHWA HPMS road segment ingestion (per-state ArcGIS REST)

## URL Format Discovery

The spec suggested `{StateCode}_2018_PR` (e.g. `MA_2018_PR`). The actual geo.dot.gov API uses **full state names**: `{StateName}_2018_PR` (e.g. `Massachusetts_2018_PR`). A `STATE_TO_SERVICE` mapping was added to translate state codes to service names.

## Per-State Record Counts (MA full run)

| State | Segments | Skipped |
|-------|----------|---------|
| MA    | 137,837  | 1,197   |

## Three-State Test (limit 3 pages each)

| State | Segments |
|-------|----------|
| MA    | 5,948    |
| CA    | 3,786    |
| NY    | 5,998    |
| **Total** | 15,732 |

## AADT Coverage

| Metric | Value |
|--------|-------|
| Non-null AADT | 86.6% (119,389 / 137,837) |
| Null AADT     | 13.4% (18,448 / 137,837) |

## AADT Range (non-null, non-sentinel)

- **Min:** 31
- **Max:** 260,824

## Field Name Variations

- **MA:** Uses lowercase keys (`aadt`, `route_id`, `state_code`, etc.). `aadt` preferred over `aadt_single_unit`.
- **state_code:** Stored as FIPS numeric (e.g. 25 for MA) when provided by API.
- Case-insensitive `_attr()` helper added for cross-state compatibility.

## Null Geometry Skip Count

- **MA:** 1,197 segments skipped (null or invalid geometry)

## Wall-Clock Time

- **MA full:** ~1.3 min (137,837 segments)
- **Three-state (limit 3):** ~0.2 min (15,732 segments)

## States That 404 or Fail

- **AK (Alaska):** "Service not found" — `Alaska_2018_PR` does not exist; only `Alaska_2018_PR_test` is available. Script skips gracefully.

## Proximity Test (Boston)

```
store.lines_within(42.35, -71.05, 1000, "hpms")
→ 482 segments within 1km
→ Sample: N121 NB AADT=19,531, dist=10m
→ Some segments have AADT=None (ingested per spec)
```

## Spot-Check Geometry

Sample: `SR1A NB | AADT: 18257 | MULTILINESTRING((-71.184108 42.232993, ...))` — coordinates are reasonable US values.

## Dataset Registry

```
facility_type: hpms
record_count: 137837 (MA only)
notes: states=1
```

## Full National Run

Not executed in this session. Estimated: 52 states × ~2–5 min each → 2–4+ hours. User can run `python scripts/ingest_hpms.py` for full national ingest.

## Surprises

1. **URL format:** State codes (MA) map to full names (Massachusetts) for the 2018_PR services.
2. **Skipped segments:** ~0.9% of MA segments have null geometry (likely point-only or invalid polyline records).
3. **Alaska:** No production `Alaska_2018_PR` service; only test version exists.
