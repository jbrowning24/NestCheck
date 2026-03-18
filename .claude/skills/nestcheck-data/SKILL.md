---
name: NestCheck Data & Scoring Reference
description: "NestCheck's data source reference, API patterns, scoring architecture, and ground truth testing framework. Trigger on: ingest, data source, EPA, FEMA, EJScreen, HIFLD, FRA, TRI, UST, HPMS, ParkServe, spatial.db, scoring, buffer distance, ground truth, data quality, coverage, hazard types, NCES, Census, Google Places, Overpass, Walk Score, scoring_config, piecewise, geographic expansion, or any mention of specific environmental hazard datasets in the NestCheck context."
---

# NestCheck Data & Scoring Reference

## Data Sources & Ingestion

Every external dataset lands in `spatial.db` (SpatiaLite) via `startup_ingest.py` on Railway deploy. Each ingest script lives in `scripts/ingest_*.py` and accepts kwargs (not just argparse) so `startup_ingest.py` can call them directly.

### Federal Environmental & Infrastructure Datasets

| Dataset | Source | Format | State Filter | Table(s) in spatial.db | Ingest Script |
|---------|--------|--------|-------------|----------------------|---------------|
| **EPA TRI** | EPA Envirofacts REST | JSON/point | 2-letter (`"NY"`) | `facilities_tri` | `ingest_tri.py` |
| **UST** (Underground Storage Tanks) | State bulk downloads | Varies, full name (`"New York"`) | `facilities_ust` | `ingest_ust.py` |
| **EPA SEMS** (Superfund) | EPA ArcGIS REST | JSON/polygon | ArcGIS bbox | `facilities_sems` | `ingest_sems.py` |
| **HPMS** (Highway Performance) | FHWA ArcGIS REST | JSON/linestring | State FIPS | `facilities_hpms` | `ingest_hpms.py` |
| **HIFLD** (Power infrastructure) | HIFLD ArcGIS REST | JSON/point | ArcGIS bbox | `facilities_hifld` | `ingest_hifld.py` |
| **FRA** (Railroad crossings) | FRA ArcGIS REST | JSON/point | ArcGIS bbox | `facilities_fra` | `ingest_fra.py` |
| **FEMA NFHL** (Flood zones) | FEMA MapServer | JSON/polygon | ArcGIS bbox | `facilities_fema` | `ingest_fema.py` |
| **EJScreen** | EPA ArcGIS (PEDP fallback) | JSON/polygon | 2-letter | `facilities_ejscreen` | `ingest_ejscreen.py` |
| **ParkServe** (TPL) | TPL ArcGIS REST | JSON/polygon | ArcGIS bbox | `facilities_parkserve` | `ingest_parkserve.py` |

### Education & Census Datasets

| Dataset | Source | Format | State Filter | Table(s) | Ingest Script |
|---------|--------|--------|-------------|----------|---------------|
| **NCES** (Schools) | NCES EDGE ArcGIS | JSON/point | `STABR='NY'` | `facilities_nces` | `ingest_nces.py` |
| **Education Performance** | Bundled CSV (`data/`) | CSV | Per-state | `state_education_performance` | `ingest_*_performance.py` |
| **Census ACS** | Census Geocoder + ACS API | JSON | N/A (point query) | Cached in `nestcheck.db` | `census.py` (runtime) |

### Runtime API Sources (not in spatial.db)

| Source | Client | Cache | Purpose |
|--------|--------|-------|---------|
| **Google Places** | `GoogleMapsClient` | `venue_cache` in spatial.db (NES-291) + in-memory per-eval | Venues, walk/drive times |
| **Google Distance Matrix** | `GoogleMapsClient` | `walk_time_cache` in spatial.db (NES-292) | Walk/drive time scoring |
| **Overpass (OSM)** | `OverpassHTTPClient` | In-memory per-eval | Sidewalks, bike infra, green space geometry |
| **Census ACS** | `census.py` | `census_cache` in nestcheck.db (90-day TTL) | City demographics |
| **Weather** | Direct API | `weather_cache` in nestcheck.db (30-day TTL) | Climate context |

### Key Ingestion Rules

- `TARGET_STATES` in `startup_ingest.py` is the single source of truth for geographic scope (NES-281).
- State filter format varies by dataset — check upstream API field before coding.
- Bbox is an AND filter with `where` clauses — never pass bbox from state-filtered startup wrappers.
- ArcGIS `outFields` with nonexistent field names returns 400 with no indication of which field. Always verify with `outFields=*&resultRecordCount=1` first.
- `create_facility_table()` is NOT idempotent for SpatiaLite DDL — never run multiple ingest scripts concurrently.
- Multi-state shared tables: use `CREATE TABLE IF NOT EXISTS` + `DELETE FROM ... WHERE state = 'X'` + INSERT. Never `DROP TABLE`.
- FEMA MapServer returns 500 for bboxes larger than ~0.5 degrees. Chunk large areas.

### EJScreen PEDP Fallback (NES-282)

EPA removed the combined EJScreen endpoint in Feb 2025. PEDP community mirror at `services2.arcgis.com/w4yiQqB14ZaAGzJq` serves V2.32. Field changes: `CANCER`/`RESP` removed, replaced by `RSEI_AIR`. `ingest_ejscreen.py` probes combined first, falls back to PEDP.

## Health Check Buffer Distances

Buffer distances are evidence-based. Each check in `property_evaluator.py` has a search radius and threshold distance.

| Check | Search Radius | FAIL Threshold | WARNING Threshold | Evidence Basis |
|-------|--------------|----------------|-------------------|----------------|
| UST proximity | Expanded | Direct | Secondary | EPA groundwater contamination plume data |
| HPMS road noise | 600m | 150m (+ AADT) | 300m (+ AADT) | FHWA noise modeling, dual-axis (distance AND traffic volume) |
| HIFLD power lines | Varies | Direct | Secondary | EMF exposure research, visual impact |
| FRA railroad | Varies | Direct | Secondary | FRA safety statistics, noise contours |
| FEMA flood zones | Point-in-polygon | Zone A/V | Zone X-shaded | FEMA risk classifications |
| EJScreen indicators | Block group level | Percentile thresholds | Lower percentile | EPA environmental justice screening |
| TRI facilities | Varies | Direct | Secondary | EPA toxic release inventory risk data |
| SEMS/Superfund | Varies | Direct | Secondary | EPA site contamination boundaries |

Cascading distance filters must use explicit upper bounds — a filter like `distance > FAIL_RADIUS and aadt >= THRESHOLD` without `and distance <= WARN_RADIUS` silently extends the warning zone to the full search radius.

## Scoring System Architecture (v1.6.0)

### Source of Truth

`scoring_config.py` is the canonical source for all scoring parameters. `property_evaluator.py` imports and applies them.

### Smooth Piecewise Curves

All venue dimensions use `apply_piecewise()` from `scoring_config.py`. Knot points define the curve; linear interpolation between them eliminates cliff-edge score jumps.

```
apply_piecewise(knots, value) → float
```

`apply_piecewise` returns float — round to int at `Tier2Score` boundary: `points = int(max(cfg.floor, capped_score) + 0.5)`.

### Scoring Pipeline (per dimension)

1. **Piecewise base score** from walk time via dimension-specific knots
2. **Quality ceiling** via `QualityCeilingConfig` (sub-type diversity + social bucket diversity + review depth bonuses)
3. **Confidence cap** via `_apply_confidence_cap()` (estimated caps at 8/10, not_scored excluded)
4. **Floor** from `DimensionConfig.floor`
5. **Round** to int at `Tier2Score` boundary

Pipeline composition tests in ground truth catch double-application bugs that sub-function tests miss.

### Drive-Time Scoring (NES-259)

When `best_walk_time > WALK_DRIVE_BOTH_THRESHOLD`, fetch one `driving_time()` call for the best facility. `best_score = max(walk_score, drive_score)` — drive can only help, never hurt. Currently wired for fitness; coffee and grocery have knots defined but not yet wired.

### Composite Score

Equal-weight across all scorable dimensions. `tier2_total / tier2_max * 100`. Dimensions with `data_confidence == CONFIDENCE_NOT_SCORED` excluded from both numerator and denominator.

### Three-Band Dimension Classification

`_dim_band()` at module level: strong (>=8), moderate (>=5), limited (<5). Distinct from composite `ScoreBand` (0-100 scale).

## Ground Truth Testing Framework

### Four Layers

| Layer | What | Count | Location | Automation |
|-------|------|-------|----------|------------|
| **Layer 1** | Unit tests for scoring logic | 115 | `tests/test_scoring_regression.py`, `tests/test_scoring_config.py` | CI gate (`make test-scoring`) |
| **Layer 2** | Synthetic spatial validators | UST, HPMS, coffee, grocery done | `scripts/validate_ground_truth_*.py` + `data/ground_truth/` | `make validate` (needs spatial.db) |
| **Layer 3** | Reference address test suite | 185 addresses | `scripts/regression_baseline.py` | `make regression` |
| **Layer 4** | Manual spot checks | Ad hoc | Google Maps comparison | Human |

### Missing Validators (Linear Tickets)

- **NES-267**: Fitness scoring validator
- **NES-268**: Green space / park scoring validator
- **NES-269**: Transit scoring validator
- **NES-270**: Road noise scoring validator
- **NES-271**: EJScreen indicator validator

### Ground Truth Methodology

- **Tier 1 generators**: Create synthetic coordinates against spatial.db, test pass/fail checks.
- **Tier 2 generators**: Test scoring functions in isolation with synthetic scalar inputs — no API calls, no spatial.db.
- Generator/validator pairs per check. Generator creates `data/ground_truth/<dimension>.json` with `--seed 42`.
- Nearest-neighbor adjustment after generating test points — dense areas need correction.
- HPMS uses perpendicular offset from linestring centroids for test point generation.
- Always add new dimension labels to `_DIMENSION_LABELS` in `validate_all_ground_truth.py`.

### CI Integration (NES-278)

`.github/workflows/ci.yml` has two parallel jobs:
- `scoring-tests` — merge gate, runs pytest (~30s)
- `ground-truth-validation` — runs when `spatial.db` available, skips with warning annotation when absent

`spatial.db` is not in CI (generated from external APIs). Ground truth provisioning in CI is deferred.

## Geographic Expansion Framework

### Critical Path

```
NES-281 (TARGET_STATES refactor) → NES-282 (EJScreen PEDP) → NES-284 (Michigan first)
```

### Expansion Tickets

| Ticket | Scope | Status |
|--------|-------|--------|
| **NES-281** | `TARGET_STATES` as single source of truth | Done |
| **NES-282** | EJScreen PEDP fallback after EPA takedown | Done |
| **NES-283** | Bbox removal from state-filtered datasets | Partial (EJScreen, NCES done) |
| **NES-284** | Michigan onboarding (first non-tri-state) | Done |
| **NES-285** | CT education data integration | Pending |
| **NES-286** | NJ education data integration | Done |
| **NES-287** | MI education data (EdFacts federal) | Done |
| **NES-288** | Bbox-filtered dataset refactoring (FEMA, HIFLD, FRA) | Pending |

### Adding a New State Checklist

1. Add to `TARGET_STATES` in `startup_ingest.py` (FIPS + full name)
2. Create `data/<st>_district_performance.csv` + `scripts/ingest_<st>_performance.py`
3. Add lazy-import wrapper + wire into `_STATE_EDUCATION_INGEST`
4. Add to `CSV_FILES` in `crosswalk_geoids.py` with state-specific suffix patterns
5. Verify no bbox is passed from startup wrappers for state-filtered datasets
6. Validate GEOIDs against TIGER WMS endpoint

## Common Failure Modes

### 0 Rows in spatial.db After Ingest
- ArcGIS field names changed between dataset years. Run `outFields=*&resultRecordCount=1` to verify.
- Bbox AND filter excluded the target state. Remove bbox from state-filtered wrappers.
- `DROP TABLE` in concurrent ingest destroyed another script's data. Run sequentially.

### Stale Overpass Cache
- Overpass data is cached in-memory per evaluation only. No persistent cache.
- Overpass HTTP timeouts produce empty results, not errors. Check `OverpassHTTPClient` timeout settings.

### Google Places Misclassification
- Real estate offices tagged as `gym`. Use type-based eligibility filters before rating/review filters.
- Online-only businesses appearing in results. `_ONLINE_BUSINESS_EXACT_NAMES` and `_ONLINE_BUSINESS_NAME_PATTERNS` filter these centrally.
- 20-result Nearby Search prominence cap drops known chains. Add supplemental `text_search()` calls (NES-258, NES-259).

### Buffer Distance Unit Errors
- Google Distance Matrix returns meters. `_distance_feet()` uses haversine in feet.
- Overpass queries use meters. SpatiaLite `ST_Distance` returns degrees unless coordinates are projected.
- Always verify the unit chain end-to-end when adding or modifying a proximity check.

### Venue Cache Misses
- `_PLACE_TYPE_TO_CATEGORY` or `_TEXT_QUERY_CATEGORY_RULES` missing for new query types stores venues with raw Google type as category. Add mappings in the same commit as new API calls.
- `venue_search_areas` table tracks prior search coverage. Empty-area results return `[]` (not `None`) to prevent re-querying.

### scoring_config ↔ property_evaluator Import Sync
- New constants in `scoring_config.py` not imported in `property_evaluator.py` surface as `NameError` only at evaluation runtime inside try/except — silently producing 0/10 scores with error text.

## What NOT to Do

- Do NOT hardcode buffer distances in `property_evaluator.py` — they belong in `scoring_config.py`.
- Do NOT add a new spatial dataset without adding its `facility_type` to `_VALID_FACILITY_TYPES` in `spatial_data.py`.
- Do NOT run `create_facility_table()` calls concurrently from parallel shell processes.
- Do NOT assume ArcGIS field names are stable across dataset years — always verify first.
- Do NOT pass bbox to state-filtered startup wrappers — bbox is an AND filter that excludes states outside the envelope.
- Do NOT skip the `_validate_facility_type()` whitelist for SQL table name interpolation.
- Do NOT add a `places_nearby()` or `text_search()` call without updating `_PLACE_TYPE_TO_CATEGORY` or `_TEXT_QUERY_CATEGORY_RULES` in the same commit.
- Do NOT trust Google Places `radius` parameter as a strict filter — always validate proximity with `_distance_feet()`.
- Do NOT bump ACS vintage without verifying all queried variable codes still exist in the new schema.
