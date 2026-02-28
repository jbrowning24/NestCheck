# Phase 1: Unified Flask CLI Ingestion Command

**Goal:** `flask ingest --dataset sems fema ust tri ...` runs any combination of
the 13 ingest scripts against the configured volume path.
**Deploy:** `railway run flask ingest --dataset sems fema` to populate `spatial.db`.

## Progress: 100%

## Tasks

| # | Task | Status |
|---|------|--------|
| 1 | Create tracking document | ✅ Done |
| 2 | Expand `flask ingest` CLI to all 13 datasets | ✅ Done |
| 3 | Verify implementation (syntax + unit tests + CLI) | ✅ Done |

## Dataset Registry (all 13)

| Dataset | Script | State | Limit | Metro | BBox | Extra |
|---------|--------|:-----:|:-----:|:-----:|:----:|-------|
| ust | ingest_ust.py | ✅ | ✅ | | | |
| tri | ingest_tri.py | ✅ | ✅ | | | |
| sems | ingest_sems.py | ✅ | ✅ | | | |
| hpms | ingest_hpms.py | ✅ | ✅ | | | `--states`, `--dry-run` |
| fema | ingest_fema.py | | ✅ | ✅ | ✅ | |
| hifld | ingest_hifld.py | | ✅ | | | |
| fra | ingest_fra.py | | ✅ | | | `--us-only` |
| ejscreen | ingest_ejscreen.py | ✅ | ✅ | | | |
| walkability | ingest_walkability.py | ✅ | ✅ | | | |
| nlcd | ingest_nlcd.py | ✅ | ✅ | | | |
| parkserve | ingest_parkserve.py | ✅ | ✅ | | | |
| tiger | ingest_tiger.py | ✅ | ✅ | | ✅ | `--county` |
| census_acs | ingest_census_acs.py | ✅ | ✅ | | | |

## Architecture

- Keeps existing subprocess-per-script pattern (no import gymnastics)
- Declarative registry maps dataset name → script + supported CLI flags
- Generic `_build_script_args()` filters options per-dataset
- `--list` flag shows all available datasets
