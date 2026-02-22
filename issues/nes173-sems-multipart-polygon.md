# NES-173: SEMS Multipart Polygon Geometry Handling

**Type:** Bug
**Priority:** Low
**Effort:** Small

## TL;DR

`_rings_to_multipolygon_wkt` in the SEMS ingestion script treats all rings after the first as holes, but ArcGIS polygons can contain multiple exterior rings (multipart geometries). Disjoint Superfund site boundaries get incorrectly merged into a single polygon-with-holes.

## Current Behavior

All rings are joined into one WKT polygon group:
```
MULTIPOLYGON(((exterior), (ring2_treated_as_hole), (ring3_treated_as_hole)))
```

When a Superfund site has two disjoint land parcels (two exterior rings), ring #2 becomes a hole in ring #1 instead of a separate polygon part. This can produce invalid geometry or false negatives in `point_in_polygons` containment checks.

## Expected Behavior

Detect ring orientation (clockwise = exterior, counterclockwise = hole per ArcGIS spec) and group rings into separate polygon parts:
```
MULTIPOLYGON(((exterior1), (hole1)), ((exterior2)))
```

## Approach

Use the [Shoelace formula](https://en.wikipedia.org/wiki/Shoelace_formula) to compute signed area of each ring:
- Positive (clockwise in ArcGIS lon/lat space) → exterior ring → starts a new polygon part
- Negative (counterclockwise) → hole → appended to the current polygon part

## Files

- `scripts/ingest_sems.py` — `_rings_to_multipolygon_wkt()` (lines 55–79)

## Notes

- Low practical impact today: most EPA Superfund sites have single contiguous boundaries
- Surfaced during external code review of Phase 5b-2a/5b-3
- Similar logic may apply to any future ArcGIS polygon ingestion scripts
