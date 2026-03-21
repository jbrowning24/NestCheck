# SEMS Superfund Ground Truth Generator + Validator

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create a ground truth generator and validator pair for the SEMS Superfund NPL polygon containment check.

**Architecture:** Generator samples real SEMS polygons from spatial.db, creates test points inside NPL sites (expected FAIL), outside all polygons (expected PASS), and inside non-NPL polygons (expected PASS). Validator calls `check_superfund_npl()` against each point and compares results. Follows existing TRI generator/validator patterns adapted for polygon containment instead of distance-based proximity.

**Tech Stack:** Python, SpatiaLite, spatial.db

---

### Task 1: Generator Script

**Files:**
- Create: `scripts/generate_ground_truth_sems.py`

**Reference patterns:**
- `scripts/generate_ground_truth_tri.py` — overall structure, CLI args, JSON output format, `_find_spatial_db()`
- `property_evaluator.py:2479-2549` — `check_superfund_npl()` for NPL filter logic (npl_status_code in F/P)

**Key differences from TRI pattern:**
- Polygon containment (not distance thresholds) — no CLOSE/MIDDLE/FAR distance variants
- Three test categories instead of one axis:
  1. Inside NPL polygon → FAIL (use `ST_PointOnSurface()`)
  2. Outside all polygons → PASS (offset from centroid, verify with `NOT ST_Contains()`, retry on failure)
  3. Inside non-NPL polygon → PASS (use `ST_PointOnSurface()` on non-NPL sites)
- No nearest-neighbor adjustment needed (containment is binary)

- [ ] **Step 1: Create the generator script**

The script must:

1. **CLI args** (same pattern as TRI): `--count` (default 30), `--state`, `--output` (default `data/ground_truth/sems.json`), `--seed`

2. **Query facilities from spatial.db:**
   - NPL sites: `WHERE json_extract(metadata_json, '$.npl_status_code') IN ('F', 'P')`
   - Non-NPL sites: `WHERE json_extract(metadata_json, '$.npl_status_code') NOT IN ('F', 'P') OR json_extract(metadata_json, '$.npl_status_code') IS NULL`
   - For each: extract `name`, `metadata_json`, use `ST_PointOnSurface(geometry)` for inside-point coords, `ST_Centroid(geometry)` + bounding box diagonal for offset distance

3. **Generate test points per category:**

   **Category 1 (Inside NPL → FAIL):** For each sampled NPL site, use `ST_PointOnSurface(geometry)` to get a guaranteed-inside point. Verify with `ST_Contains()` as a sanity check.

   **Category 2 (Outside → PASS):** For each sampled NPL site, compute offset distance as 2x the bounding box diagonal (`sqrt((MbrMaxX-MbrMinX)^2 + (MbrMaxY-MbrMinY)^2)` in degrees, converted to feet). Offset from centroid at random bearing. Verify `NOT ST_Contains()` for ALL SEMS polygons (not just the source one). Retry up to 5 times with different bearings. Skip and warn if all attempts fail.

   **Category 3 (Inside non-NPL → PASS):** For each sampled non-NPL site, use `ST_PointOnSurface(geometry)`. Verify the point is NOT inside any NPL polygon (edge case: overlapping polygons). If it is, skip with a warning.

4. **Output JSON** (same schema as TRI but adapted fields):
   ```json
   {
     "_schema_version": "0.1.0",
     "_generated_at": "ISO timestamp",
     "_generator": "generate_ground_truth_sems.py",
     "_facility_count": 45,
     "_test_count": 90,
     "_thresholds": {
       "containment": "polygon point-in-polygon",
       "npl_status_codes": ["F", "P"],
       "source": "property_evaluator.py check_superfund_npl()"
     },
     "addresses": [
       {
         "id": "gt-sems-0001",
         "coordinates": {"lat": 40.7123, "lng": -73.9876},
         "layer": 4,
         "layer_notes": "Synthetic — inside NPL Superfund site ...",
         "source_facility": {
           "name": "Site Name",
           "epa_id": "NJD...",
           "npl_status_code": "F",
           "containment_type": "inside_npl",
           "coordinates": {"lat": 40.71, "lng": -73.99}
         },
         "tier1_health_checks": {
           "superfund_npl": {
             "expected_result": "FAIL",
             "expected_pass": false,
             "notes": "Point inside NPL site polygon (Final)",
             "source": "synthetic from spatial.db facilities_sems"
           }
         },
         "tier2_scored_dimensions": {}
       }
     ]
   }
   ```

   `containment_type` values: `"inside_npl"`, `"outside"`, `"inside_non_npl"`

- [ ] **Step 2: Run the generator**

```bash
cd /Users/jeremybrowning/NestCheck
python scripts/generate_ground_truth_sems.py --seed 42 --output data/ground_truth/sems.json
```

Expected: Creates `data/ground_truth/sems.json` with test points across all three categories. Print summary showing FAIL/PASS counts per category.

- [ ] **Step 3: Verify output**

Inspect the JSON — confirm:
- All `inside_npl` points have `expected_result: "FAIL"`
- All `outside` and `inside_non_npl` points have `expected_result: "PASS"`
- Coordinates are reasonable (continental US range)
- No duplicate IDs

---

### Task 2: Validator Script

**Files:**
- Create: `scripts/validate_ground_truth_sems.py`

**Reference pattern:** `scripts/validate_ground_truth_tri.py` — nearly identical structure

- [ ] **Step 1: Create the validator script**

The script must:

1. **CLI args** (same as TRI): `--input` (default `data/ground_truth/sems.json`), `--output`, `--verbose`

2. **Load ground truth JSON**, iterate addresses

3. **For each test point:**
   - Call `check_superfund_npl(lat, lng)` — note this function creates its own `SpatialDataStore()` internally, unlike TRI which takes `spatial_store` param
   - Extract result: `tier1.result.value` ("PASS", "FAIL", "UNKNOWN")
   - Compare with `expected_result`
   - Track: MATCH, MISMATCH, UNKNOWN

4. **Per-category tracking:** Track by `containment_type` from `source_facility` (inside_npl, outside, inside_non_npl) for detailed breakdown

5. **Summary output** (must match format parsed by `validate_all_ground_truth.py`):
   ```
   Matches:           N
   Mismatches:        N
   ```

6. **Mismatch details:** Print up to 20 mismatches with coordinates, expected/actual, facility name

7. **Exit code:** Non-zero on mismatches (CI-friendly)

- [ ] **Step 2: Run the validator**

```bash
cd /Users/jeremybrowning/NestCheck
python scripts/validate_ground_truth_sems.py --verbose
```

Expected: All test points match. If mismatches occur on `inside_npl` or `outside` categories, investigate — likely NES-173 (multipart polygon bug). Document in output but don't block.

---

### Task 3: Wire Into Aggregate Runner

**Files:**
- Modify: `scripts/validate_all_ground_truth.py:28-39` — add to `_DIMENSION_LABELS`

- [ ] **Step 1: Add SEMS label**

Add to `_DIMENSION_LABELS` dict:
```python
"sems": "SEMS Superfund NPL",
```

- [ ] **Step 2: Verify aggregate runner discovers the new validator**

```bash
cd /Users/jeremybrowning/NestCheck
python scripts/validate_all_ground_truth.py
```

Expected: SEMS appears in the aggregate summary alongside existing validators.

- [ ] **Step 3: Commit all files**

```bash
git add scripts/generate_ground_truth_sems.py scripts/validate_ground_truth_sems.py data/ground_truth/sems.json scripts/validate_all_ground_truth.py
git commit -m "feat(NES-271): add SEMS Superfund ground truth generator + validator

Generate synthetic test points inside/outside NPL Superfund site polygons.
Three test categories: inside NPL (FAIL), outside (PASS), inside non-NPL (PASS).
Validator calls check_superfund_npl() and compares results.
Wired into validate_all_ground_truth.py aggregate runner."
```
