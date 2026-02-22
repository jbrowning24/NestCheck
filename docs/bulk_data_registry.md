# NestCheck Bulk Data Registry

Tracks the 13 priority spatial datasets for local ingestion. Each dataset
replaces or supplements real-time API calls with pre-indexed local spatial
queries.

**Database:** SpatiaLite (separate file from operational DB)
**Location:** `{RAILWAY_VOLUME_MOUNT_PATH}/spatial.db` (prod) or `data/spatial.db` (local)
**Query interface:** `spatial_data.py` → `SpatialDataStore`

## Priority Tiers

- **P0 — Health hazard proximity (ship first):** Enables Tier Zero health
  disqualifiers from the PRD. Directly replaces or upgrades existing
  Google Places and Overpass checks.
- **P1 — Green space + parks:** Enhances green_space.py with richer park
  data. Requires polygon support.
- **P2 — Census + walkability + streets:** Contextual layers. Largest
  datasets. Deferred until P0 and P1 are validated.

## Dataset Registry

### P0: Health Hazard Proximity

| # | Dataset | Provides | Source URL | Format | ~Size | Refresh | Status | Module | Notes |
|---|---------|----------|------------|--------|-------|---------|--------|--------|-------|
| 1 | EPA UST Finder | 2.2M active/historic underground storage tanks across 800K facilities with point coordinates | gispub.epa.gov/ustfinder | CSV/shapefile | ~500MB indexed | Quarterly | Not started | spatial_data.py | Replaces `check_gas_stations()` Google Places call. Direct coordinate match. Highest-value first migration. |
| 2 | EPA TRI | 800+ chemical releases from ~21K facilities annually | data.epa.gov/efservice/ | REST API (JSON/CSV, no key, 10K row default) | ~50MB indexed | Quarterly | Not started | spatial_data.py | Net-new capability. No existing check for industrial chemical facilities. |
| 3 | EPA SEMS | ~1,300 NPL (Superfund) sites + thousands non-NPL with boundary polygons | epa.gov/enviro/sems-search | Shapefile/CSV | ~100MB indexed | Updated every 2 hours (ingest quarterly) | Not started | spatial_data.py | Net-new capability. First dataset with polygons — SpatiaLite polygon test. |
| 4 | FHWA HPMS | Annual Average Daily Traffic (AADT) counts at road-segment level for all public roads | fhwa.dot.gov/policyinformation/hpms.cfm | Shapefile | ~2GB raw, ~200MB filtered (AADT>50K only) | Annually | Not started | spatial_data.py | Upgrades existing Overpass highway check from road classification to actual traffic volume. Filter to AADT > 50K segments only to manage size. |

### P1: Green Space + Parks

| # | Dataset | Provides | Source URL | Format | ~Size | Refresh | Status | Module | Notes |
|---|---------|----------|------------|--------|-------|---------|--------|--------|-------|
| 5 | ParkServe park polygons | Park boundaries, 10-min walk service areas, amenity data, equity analysis at block group level | tpl.org/park-data-downloads | Shapefile/ArcGIS | ~500MB | Annually | Not started | green_space.py | Supplements existing Google Places park discovery. Complex polygons — PostGIS may be needed. |
| 6 | NLCD tree canopy cover | 30m resolution canopy coverage nationally | mrlc.gov | GeoTIFF raster | ~1GB for target metros | Annually | Not started | spatial_data.py | Raster data — different query pattern than point/polygon. May need to pre-compute block-group averages. |
| 7 | FEMA NFHL flood zones | Flood zone designations at parcel/polygon level | hazards.fema.gov/gis/nfhl/rest/services/ | ArcGIS REST / shapefile | ~1GB for target metros | Semi-annually | Not started | spatial_data.py | Complex polygons with zone classifications. Point-in-polygon query. |

### P2: Census + Walkability + Streets

| # | Dataset | Provides | Source URL | Format | ~Size | Refresh | Status | Module | Notes |
|---|---------|----------|------------|--------|-------|---------|--------|--------|-------|
| 8 | Census ACS 5-year | Income, education, age, housing tenure, commute mode at block group level | api.census.gov | API (free key) / bulk CSV | ~200MB for key tables | Annually (Dec release) | Not started | TBD | Architecturally separated from evaluation scores per PRD Fair Housing guardrails. |
| 9 | EPA National Walkability Index | Walkability scores 1-20 per census block group | epa.gov/smartgrowth/national-walkability-index | CSV/shapefile | ~100MB | Periodic | Not started | spatial_data.py | Baseline walkability. Supplements Walk Score API. |
| 10 | Census TIGER/Line streets | Street network for block length and intersection density calculations | census.gov/geographies/mapping-files/time-series/geo/tiger-line-file.html | Shapefile | ~2GB nationally, ~200MB per metro | Annually | Not started | spatial_data.py | Needed for independent walkability scoring (post-Walk Score dependency). |
| 11 | EJScreen block group data | 13 environmental indicators (PM2.5, ozone, diesel PM, air toxics, traffic proximity, lead paint, Superfund proximity, etc.) | epa.gov/ejscreen | CSV/shapefile | ~300MB | Annually | Not started | spatial_data.py | Single most valuable free dataset per PRD. Pre-combined environmental + demographic indicators. |
| 12 | HIFLD transmission lines | 69kV-765kV power lines nationally | hifld-geoplatform.opendata.arcgis.com | Shapefile | ~100MB | Periodic snapshots | Not started | spatial_data.py | Net-new capability. Line geometry — distance-to-nearest-line query. |
| 13 | FRA rail lines | National rail network | safetydata.fra.dot.gov | Shapefile | ~50MB | Periodic | Not started | spatial_data.py | Supplements existing Overpass rail corridor check with authoritative federal data. |

## Integration Status Legend

- **Not started** — Dataset identified, not yet downloaded or ingested
- **Downloaded** — Raw data obtained, not yet loaded into SpatiaLite
- **Ingested** — Loaded into spatial.db with spatial index
- **Shadow mode** — Queried during evaluation alongside existing checks, results logged but not user-facing
- **Live** — Replaces or supplements existing checks in production evaluations

## Architecture Notes

- Spatial DB is a separate SpatiaLite file from the operational DB (nestcheck.db)
- All spatial queries go through `SpatialDataStore` in `spatial_data.py`
- Ingestion scripts live in `scripts/ingest_{dataset}.py`, one per dataset
- Scripts are idempotent: drop table + recreate on each run
- Railway volume limit is 5GB — monitor cumulative spatial.db size
- P0 datasets estimated at ~850MB indexed, leaving room for operational DB + future datasets

---

Status report format:
- Files created: (list)
- Files modified: (list)
- What was tested: (describe)
- What was NOT tested: (describe)
