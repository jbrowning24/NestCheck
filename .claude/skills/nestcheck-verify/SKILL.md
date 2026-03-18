---
name: NestCheck Evaluation Verification
description: "NestCheck evaluation verification framework. 4-layer testing strategy, ground truth methodology, and calibration workflows. Trigger on: verify, check the scores, test this address, ground truth, run the validators, smoke test, sanity check, reference addresses, regression, scoring tests, validate, calibration, spot check, quality assurance, or any request to confirm scoring accuracy or data integrity."
---

# NestCheck Evaluation Verification

## 4-Layer Verification Framework

### Layer 1: Unit Tests (115 tests, CI gate)

Run with `make test-scoring` or `pytest tests/test_scoring_regression.py tests/test_scoring_config.py`.

Tests cover:
- `apply_piecewise()` interpolation correctness at knot boundaries and between knots
- `QualityCeilingConfig` ceiling computation with all bonus signal combinations
- `_apply_confidence_cap()` for verified/estimated/not_scored tiers
- `DimensionConfig` floor enforcement
- Composite score calculation (equal-weight, not_scored exclusion)
- Score band classification boundaries
- `Tier2Score` serialization round-trip
- `_dim_band()` threshold boundaries (strong >=8, moderate >=5, limited <5)

CI runs these on every push. Branch protection on `main` requires `scoring-tests` job to pass.

When adding new scoring test files, update both `.github/workflows/ci.yml` and `Makefile` (`test-scoring` target) in the same commit.

### Layer 2: Synthetic Validators

Run with `make validate` (requires `spatial.db`).

**Completed validators:**
- `validate_ground_truth_ust.py` — point geometry, single threshold axis (distance)
- `validate_ground_truth_hpms.py` — linestring geometry, dual threshold axes (distance AND AADT)
- `validate_ground_truth_coffee.py` — Tier 2 scoring function isolation (piecewise + ceiling + confidence + floor + round)
- `validate_ground_truth_grocery.py` — Same Tier 2 pattern as coffee

**Missing validators (Linear tickets):**
- **NES-267**: Fitness scoring validator
- **NES-268**: Green space / park scoring validator
- **NES-269**: Transit scoring validator
- **NES-270**: Road noise scoring validator
- **NES-271**: EJScreen indicator validator

Each validator parses `Matches:` / `Mismatches:` lines in stdout — `validate_all_ground_truth.py` depends on this format. Add new dimension labels to `_DIMENSION_LABELS` when adding validators.

### Layer 3: Reference Address Test Suite (185 addresses)

Run with `make regression` or `python scripts/regression_baseline.py`.

Addresses span: dense urban (Manhattan), suburban (Westchester, Long Island), rural fringe, multi-state (NY, CT, NJ, MI). Baseline stored in `data/regression_baseline.json`. Monthly cron updates baseline on Railway.

Record new baseline: `make regression-update`.

### Layer 4: Manual Spot Checks

Compare NestCheck results against Google Maps ground truth. Open the address in Google Maps, verify:
- Listed venues actually exist at reported distances
- Health hazard locations match spatial data
- Park boundaries and amenities are accurate
- Walk times are plausible (Google Maps directions vs. Distance Matrix API)

## Verification Workflows

### After a Scoring Change

```bash
# 1. Run unit tests (must pass — CI gate)
make test-scoring

# 2. Run ground truth validators (if spatial.db available)
make validate

# 3. Check regression impact on reference addresses
make regression
# Compare against baseline — look for score shifts > 2 points

# 4. Spot-check 3 addresses manually
# Pick one each from: dense urban, suburban, rural/fringe
```

### After a Data Ingestion Change

```bash
# 1. Verify row counts in spatial.db
sqlite3 data/spatial.db "SELECT COUNT(*) FROM facilities_<table>;"

# 2. Verify geographic distribution
sqlite3 data/spatial.db "SELECT COUNT(*),
  CASE WHEN MbrMinX(geometry) < -74.5 THEN 'west'
       WHEN MbrMinX(geometry) > -73.5 THEN 'east'
       ELSE 'central' END as region
  FROM facilities_<table> GROUP BY region;"

# 3. Check for state coverage
sqlite3 data/spatial.db "SELECT state, COUNT(*) FROM facilities_<table> GROUP BY state;"

# 4. Run affected validators
python scripts/validate_ground_truth_<dimension>.py

# 5. Evaluate a known address and compare to previous snapshot
```

### After Geographic Expansion to a New State

```bash
# 1. Verify all datasets ingested for new state
sqlite3 data/spatial.db <<'SQL'
SELECT 'tri' as dataset, COUNT(*) FROM facilities_tri WHERE state = 'MI'
UNION ALL
SELECT 'ust', COUNT(*) FROM facilities_ust WHERE state = 'MI'
UNION ALL
SELECT 'ejscreen', COUNT(*) FROM facilities_ejscreen WHERE state = 'MI'
UNION ALL
SELECT 'nces', COUNT(*) FROM facilities_nces WHERE STABR = 'MI'
UNION ALL
SELECT 'hpms', COUNT(*) FROM facilities_hpms WHERE state_code = '26';
SQL

# 2. Check education performance data
sqlite3 data/spatial.db "SELECT COUNT(*) FROM state_education_performance WHERE state = 'MI';"

# 3. Evaluate 5+ addresses in the new state covering urban/suburban/rural
# Verify: health checks trigger, venues found, parks scored, transit scored

# 4. Check Census place resolution for the state
# MI uses County Subdivisions (charter townships) — verify COUSUB fallback works

# 5. Verify GEOID crosswalk
python scripts/crosswalk_geoids.py --state MI --verify
```

### Post-Deploy Smoke Test

```bash
# Automated (Railway cron runs daily)
make smoke-test

# Manual checklist
# 1. Verify RAILWAY_GIT_COMMIT_SHA matches latest main
# 2. Load landing page — check for errors
# 3. Evaluate a known address (e.g., Westchester suburb)
# 4. Verify health checks render (both Tier 1 cards and Tier 2 collapsible)
# 5. Verify dimension scores display with correct bands
# 6. Check Sentry for new errors
# 7. Verify share/export buttons work
```

## SQL Snippets for Data Verification

### Row Counts by Dataset
```sql
SELECT 'tri' as dataset, COUNT(*) as rows FROM facilities_tri
UNION ALL SELECT 'ust', COUNT(*) FROM facilities_ust
UNION ALL SELECT 'sems', COUNT(*) FROM facilities_sems
UNION ALL SELECT 'hpms', COUNT(*) FROM facilities_hpms
UNION ALL SELECT 'hifld', COUNT(*) FROM facilities_hifld
UNION ALL SELECT 'fra', COUNT(*) FROM facilities_fra
UNION ALL SELECT 'fema', COUNT(*) FROM facilities_fema
UNION ALL SELECT 'ejscreen', COUNT(*) FROM facilities_ejscreen
UNION ALL SELECT 'parkserve', COUNT(*) FROM facilities_parkserve
UNION ALL SELECT 'nces', COUNT(*) FROM facilities_nces
UNION ALL SELECT 'education', COUNT(*) FROM state_education_performance;
```

### Geographic Bounding Box per Dataset
```sql
SELECT 'tri' as dataset,
  MIN(MbrMinX(geometry)) as min_lon, MAX(MbrMaxX(geometry)) as max_lon,
  MIN(MbrMinY(geometry)) as min_lat, MAX(MbrMaxY(geometry)) as max_lat
FROM facilities_tri
UNION ALL
SELECT 'hpms',
  MIN(MbrMinX(geometry)), MAX(MbrMaxX(geometry)),
  MIN(MbrMinY(geometry)), MAX(MbrMaxY(geometry))
FROM facilities_hpms;
```

### Venue Cache Health
```sql
-- Venue cache size and freshness
SELECT category, COUNT(*) as venues,
  MIN(last_verified) as oldest,
  MAX(last_verified) as newest
FROM venue_cache GROUP BY category;

-- Walk time cache hit rate potential
SELECT COUNT(*) as total,
  SUM(CASE WHEN walk_calculated_at IS NOT NULL THEN 1 ELSE 0 END) as walk_cached,
  SUM(CASE WHEN drive_calculated_at IS NOT NULL THEN 1 ELSE 0 END) as drive_cached
FROM walk_time_cache;
```

### Search Coverage Areas
```sql
-- Areas with prior API search coverage
SELECT category, COUNT(*) as search_areas,
  MIN(searched_at) as oldest_search,
  MAX(searched_at) as newest_search
FROM venue_search_areas GROUP BY category;
```

## Ground Truth Methodology

### Verifying Health Checks
1. Find the check's search radius and threshold in `property_evaluator.py`
2. Open the address in Google Maps
3. Search for the hazard type (e.g., "gas stations") within the threshold radius
4. Verify PASS/WARNING/FAIL matches what NestCheck reports
5. For spatial checks (UST, HPMS, HIFLD), cross-reference against the raw data source (EPA, FHWA, etc.)

### Verifying Venues
1. Open the address in Google Maps
2. Search for the venue category (e.g., "coffee shops")
3. Compare the top 5 results by distance to NestCheck's reported venues
4. Check that walk times are within 2 minutes of Google Maps walking directions
5. Verify no major chains are missing (NES-258 supplemental text search addresses this)

### Verifying Parks
1. Open Google Maps satellite view
2. Identify all green spaces within 1 mile
3. Compare to NestCheck's park list
4. Check park boundaries match ParkServe polygons
5. Verify amenity detection (playgrounds, dog parks, sports facilities) against OSM and Google

## Known Calibration Issues

### Suburban Coverage Gaps
- Google Places Nearby Search returns max 20 results ranked by "prominence" — suburban chains get dropped
- Mitigation: supplemental `text_search()` calls (NES-258, NES-259)
- Still affects dimensions without supplemental search wiring

### Google Places Misclassification
- Real estate offices tagged as `gym`, insurance agencies as `restaurant`
- Type-based eligibility filters catch these before scoring
- New misclassification patterns require adding to excluded types lists in BOTH `score_*()` and `get_neighborhood_snapshot()`

### Stale EPA Data
- TRI data is annual (published ~18 months after reporting year)
- UST data varies by state (NY is quarterly, others may be annual)
- EJScreen uses 5-year ACS estimates (inherent 2-3 year lag)
- Superfund (SEMS) sites persist for decades — staleness less of an issue

### Flood Zone Boundary Precision
- FEMA NFHL polygons have known precision issues at parcel boundaries
- Properties exactly on a zone boundary may flip between evaluations
- FEMA MapServer returns 500 for large bbox queries — some areas have incomplete coverage

### Road Noise Dual-Axis Sensitivity
- HPMS AADT values are segment-level averages — local variation within a segment is not captured
- The distance × AADT interaction can produce counterintuitive results (far from a highway but high AADT = WARNING)
- Ground truth validation (NES-266) caught a cascading distance filter bug — always use explicit upper bounds

## CI Integration Status (NES-278)

**Currently in CI:**
- `scoring-tests` job — pytest on `tests/test_scoring_regression.py` + `tests/test_scoring_config.py` (~30s, merge gate)

**Not yet in CI:**
- Ground truth validation (needs `spatial.db` — too heavy to build from external APIs in CI)
- Reference address regression (needs live API access)
- Smoke tests (post-deploy only)

`spatial.db` provisioning in CI is deferred. Run `make validate` locally before pushing spatial data changes.

## What NOT to Do

- Do NOT automate scoring logic fixes. Scoring changes require human judgment about calibration tradeoffs. Always verify manually after any scoring change.
- Do NOT skip Layer 1 tests before pushing. They are the CI gate — broken tests block all merges.
- Do NOT assume a passing unit test means the scoring is correct. Unit tests verify implementation, not calibration. Layer 3 (reference addresses) and Layer 4 (manual spot checks) verify calibration.
- Do NOT modify `data/ground_truth/*.json` files without regenerating from the generator script with `--seed 42`. Hand-edited ground truth files drift from the generator logic.
- Do NOT add a new validator without adding its label to `_DIMENSION_LABELS` in `validate_all_ground_truth.py`.
- Do NOT compare scoring results against old snapshots without running `_migrate_dimension_names()` and `_migrate_confidence_tiers()` first — field names and confidence tiers have changed across versions.
- Do NOT use `get_snapshot()` for high-frequency verification checks — it loads full `result_json` (100KB+). Use metadata-only queries for existence/freshness checks.
- Do NOT treat a smoke test pass as full verification. Smoke tests check page load and element presence, not scoring accuracy.
- Do NOT overfit ground truth fixtures to force a target band. Update `expected_band` to match the midpoint calculation — the model is authoritative, not the fixture.
