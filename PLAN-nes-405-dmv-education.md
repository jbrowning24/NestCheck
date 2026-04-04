# Implementation Plan: NES-405 — Wire MD, DC, VA Education Performance Data

**Progress:** [==========] 100%
**Created:** 2026-04-03

## TL;DR
Add education performance data for Maryland, DC, and Virginia to the existing `state_education_performance` pipeline. This involves building a federal data fetcher script (Urban Institute API), creating 3 CSVs, 3 thin ingest wrappers, wiring into `startup_ingest.py`, and adding GEOID crosswalk entries. No changes needed to `property_evaluator.py` or templates — the JOIN is already state-agnostic.

## Critical Decisions
| Decision | Choice | Rationale |
|----------|--------|-----------|
| Data source | Federal APIs (Urban Institute educationdata.urban.org) | Consistent across all 3 states, same pattern as `build_nysed_statewide_csv.py`. State portals have inconsistent formats. |
| DC handling | Single row (GEOID `1100030`, DCPS aggregate) | TIGER has one unified school district polygon for DC. One row is correct. |
| VA county field | City name for independent cities | Schema allows any string; field is display-only. No special casing needed. |
| CSV approach | Real data, not placeholders | CTO guidance: don't repeat CA/TX/FL/IL placeholder pattern. Ship real data or don't create. |

## Tasks

### Phase 1: Build Federal Data Fetcher
- [x] 🟩 **Task 1.1: Create `scripts/build_dmv_education_csv.py`**
  - Files: `scripts/build_dmv_education_csv.py`
  - Pattern: Follow `build_nysed_statewide_csv.py` — CCD directory, EDFacts grad rates, CCD finance
  - Fetch for MD (FIPS 24), DC (FIPS 11), VA (FIPS 51)
  - Output: `data/md_district_performance.csv`, `data/dc_district_performance.csv`, `data/va_district_performance.csv`
  - Acceptance: Script runs with `--dry-run`, logs district counts and coverage stats for all 3 states

### Phase 2: Generate CSVs
- [x] 🟩 **Task 2.1: Run builder script to generate CSVs**
  - Files: `data/md_district_performance.csv`, `data/dc_district_performance.csv`, `data/va_district_performance.csv`
  - Results: MD=24 districts, DC=1 district, VA=132 districts. All GEOIDs FIPS-prefixed correctly.
  - Spot-check: GEOIDs start with correct FIPS prefix (24, 11, 51)

### Phase 3: Ingest Wiring
- [x] 🟩 **Task 3.1: Create thin ingest wrapper scripts**
  - Files: `scripts/ingest_md_performance.py`, `scripts/ingest_dc_performance.py`, `scripts/ingest_va_performance.py`
  - Pattern: Exact copy of `ingest_nj_performance.py` with state-specific substitutions
  - All 3 import successfully, define `ingest()` and `verify()`

- [x] 🟩 **Task 3.2: Wire into `_STATE_EDUCATION_INGEST` in `startup_ingest.py`**
  - Files: `startup_ingest.py`
  - Added 3 lazy-import wrapper functions and 3 dict entries
  - Verified: `_STATE_EDUCATION_INGEST` now has 11 states

- [x] 🟩 **Task 3.3: Add to `CSV_FILES` in `crosswalk_geoids.py`**
  - Files: `scripts/crosswalk_geoids.py`
  - Added 3 entries: MD/24, DC/11, VA/51
  - `CSV_FILES` list now has 11 entries

### Phase 4: Validation
- [x] 🟩 **Task 4.1: Verify pipeline**
  - All 3 ingest scripts import without errors
  - `_STATE_EDUCATION_INGEST` contains MD, DC, VA
  - `make test-scoring`: 162 tests passed, 0 regressions

## Testing Checklist
- [x] Builder script runs successfully (fetched real data from federal APIs)
- [x] CSVs have correct headers and FIPS-prefixed GEOIDs
- [x] DC CSV has exactly 1 row (GEOID `1100030`)
- [x] Ingest scripts run without import errors
- [x] `make test-scoring` passes (162/162)
