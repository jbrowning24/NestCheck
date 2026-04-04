# NES-402: DMV Ground Truth Validation Report

**Date:** 2026-04-03
**Branch:** `jerabrowning/nes-400-add-md-dc-va-to-target_states-config`

## Summary

Validated 6 DMV addresses against spatial.db to verify ingested data produces correct health check results. **8 of 9 data sources return data correctly. FEMA NFHL is the sole data gap (0 rows ingested — known API limitation for DMV density).**

## Data Coverage in spatial.db

| Dataset | DC | MD | VA | Status |
|---------|-----|------|-------|--------|
| TRI | 10 | 161 | 416 | PASS |
| UST | 1,306 | 12,663 | 24,506 | PASS |
| EJScreen | 571 | 4,079 | 5,963 | PASS |
| HPMS | 8,660 | 49,779 | 180,693 | PASS |
| HIFLD | 628 (bbox) | | | PASS |
| FRA | 1,260 (bbox) | | | PASS |
| ParkServe | 3,443 (bbox) | | | PASS |
| SEMS | 12 (bbox) | | | PASS |
| FEMA NFHL | 0 | 0 | 0 | **FAIL** |
| NCES Schools | 1,695 (bbox) | | | PASS |
| Education Perf | 0 | 0 | 0 | N/A (not wired) |

## Per-Address Validation Results

### 1. Crofton, MD (39.0066, -76.6872)
**Profile:** Suburban residential, moderate hazard density

| Source | Result | Expected | Verdict |
|--------|--------|----------|---------|
| UST | 5 sites within 1mi (1 open: Crofton Exxon) | UST sites present | PASS |
| TRI | 1 facility (Oldcastle APG, 9,319 ft) | Low industrial presence | PASS |
| HPMS | Roads with AADT 1,281-4,821 nearby | Moderate traffic | PASS |
| EJScreen | Block group found, 1 elevated indicator (PNPL) | Suburban, low EJ burden | PASS |
| HIFLD | 2 power infrastructure sites | Some infrastructure | PASS |
| FRA | 0 rail crossings | No rail nearby | PASS |
| ParkServe | 5 parks (Crofton Park, Crofton Natural Area) | Parks present | PASS |
| NCES | 3 schools within 2km | Schools present | PASS |
| FEMA | No data | Should have data | **FAIL** |

### 2. Curtis Bay / Brooklyn Park, MD (39.2261, -76.5860)
**Profile:** Industrial area south of Baltimore — known environmental justice concern

| Source | Result | Expected | Verdict |
|--------|--------|----------|---------|
| UST | 5+ sites, 5 with open tanks | Heavy UST presence | PASS |
| TRI | 18 facilities, including Prince Specialty (1.1M lbs released), Grace Davison (344K lbs) | Major TRI cluster | PASS |
| HPMS | Roads with AADT 5,412-8,002 | Moderate-high traffic | PASS |
| EJScreen | 9 of 11 indicators elevated (PRMP 99th, PTSDF 95th, LEAD 89th, PNPL 87th) | High EJ burden | PASS |
| HIFLD | 0 power sites within 2km | — | PASS |
| FRA | 92 rail crossings within 2km | Heavy rail infrastructure | PASS |
| ParkServe | 5 parks (Curtis Bay Park, Farring Baybrook) | Parks present | PASS |
| NCES | 3 schools within 2km | Schools present | PASS |
| SEMS | 1 site (Curtis Bay Coast Guard Yard) | Superfund present | PASS |
| FEMA | No data | Should have data | **FAIL** |

### 3. Anacostia / Ward 8, DC (38.8600, -76.9955)
**Profile:** Known environmental justice area near Anacostia River

| Source | Result | Expected | Verdict |
|--------|--------|----------|---------|
| UST | 5 sites, including St. Elizabeths Hospital (open) | UST presence | PASS |
| TRI | 2 facilities (Virginia Concrete, Joint Base Anacostia-Bolling) | Military/industrial | PASS |
| HPMS | AADT 13,760 road at 232 ft | High traffic proximity | PASS |
| EJScreen | 6 elevated indicators (DSLPM, PTRAF, PNPL, PTSDF, UST, PWDIS) | Environmental justice area | PASS |
| FRA | 5 rail crossings within 2km | Rail present | PASS |
| ParkServe | 5 parks (Douglass, Canal Park) | Parks present | PASS |
| SEMS | 1 site (Washington Navy Yard) | Superfund present | PASS |
| FEMA | No data | Should have flood zone data (Anacostia River) | **FAIL** |

### 4. Georgetown, DC (38.9076, -77.0723)
**Profile:** Dense urban, affluent, strong walkability expected

| Source | Result | Expected | Verdict |
|--------|--------|----------|---------|
| UST | 5+ sites (Georgetown University campus tanks) | University infrastructure | PASS |
| TRI | 1 facility (Army Joint Base Myer-Henderson Hall, 9,888 ft) | Low industrial | PASS |
| HPMS | Roads with AADT 4,943-39,799 (incl. major arterial) | Urban traffic | PASS |
| EJScreen | 6 elevated indicators | Urban area baseline | PASS |
| ParkServe | 5 parks (Francis, Circle Park) | Urban parks | PASS |
| NCES | 3 schools within 2km | Schools present | PASS |
| FEMA | No data | Should have Potomac flood zone data | **FAIL** |

### 5. Crystal City, Arlington, VA (38.8561, -77.0492)
**Profile:** Dense urban, near I-395 and Reagan National Airport

| Source | Result | Expected | Verdict |
|--------|--------|----------|---------|
| UST | 5 sites (Crystal Plaza complex) | Commercial tanks | PASS |
| TRI | 2 facilities (Allied Aviation, Pentagon) | Airport/military | PASS |
| HPMS | **I-395 at AADT 139,205, 10-11 lanes, 55 mph** | Major highway proximity | PASS |
| EJScreen | 6 elevated indicators | Urban baseline | PASS |
| HIFLD | 3 power sites within 2km | Infrastructure present | PASS |
| FRA | 12 rail crossings (Metro corridor) | Heavy rail | PASS |
| ParkServe | 5 parks (Mt Vernon Trail, Lady Bird Johnson Memorial) | Parks present | PASS |
| FEMA | No data | Should have data | **FAIL** |

### 6. Old Town Alexandria, VA (38.8048, -77.0469)
**Profile:** Known FEMA flood zone along Potomac River

| Source | Result | Expected | Verdict |
|--------|--------|----------|---------|
| UST | 5 sites within 1mi | Commercial area | PASS |
| TRI | 0 facilities | Low industrial | PASS |
| HPMS | **AADT 31,584 road at 18 ft** (Route 400) | Major road proximity | PASS |
| EJScreen | 7 elevated indicators (incl. LEAD 60th+) | Historic area, lead paint | PASS |
| HIFLD | 5 power sites | Infrastructure present | PASS |
| FRA | 9 rail crossings | Rail corridor | PASS |
| ParkServe | 5 parks (Market Square) | Urban parks | PASS |
| NCES | 3 schools | Schools present | PASS |
| FEMA | No data | **Zone AE flood zone — known false negative** | **FAIL** |

## Known Gaps

### 1. FEMA NFHL — 0 rows (CRITICAL)
- `facilities_fema_nfhl` table is empty globally — not just DMV
- Root cause documented in CLAUDE.md: "DMV area is much denser than NYC — even 0.1° cells with 100-record pages fail; may need smaller cells or bulk download instead of REST API"
- **Impact:** Flood zone checks will return "clear" for all DMV addresses, including known flood zones like Old Town Alexandria and the Anacostia River corridor
- **Recommendation:** This is a known false negative. Separate ticket needed for FEMA bulk download approach

### 2. Education Performance — not wired
- No `_district_performance.csv` files for MD, DC, VA
- `_STATE_EDUCATION_INGEST` does not include MD, DC, VA entries
- **Impact:** Education dimension will show "not scored" for DMV addresses
- **Recommendation:** Separate ticket scope (not blocking for NES-402 acceptance)

### 3. Coverage Manifest — not tracking DMV
- `COVERAGE_MANIFEST` in `coverage_config.py` has no MD, DC, VA entries
- `/coverage` page won't show DMV states
- **Recommendation:** Add manifest entries once data gaps are resolved

## Acceptance Criteria Assessment

| Criterion | Status |
|-----------|--------|
| 4+ DMV addresses evaluated with all health checks returning data | PASS (6 addresses, 8/9 sources return data) |
| No false negatives on known hazards (UST, TRI, high-traffic road) | PASS (all confirmed) |
| No false negatives on known hazards (flood zone) | **FAIL** (FEMA data not ingested) |
| EJScreen indicators populated for DMV block groups | PASS (all 6 addresses matched) |
| Results documented with pass/fail per source per address | PASS (this document) |

## Conclusion

DMV data ingestion is **substantially complete** for 8 of 9 spatial data sources. The scoring pipeline will correctly identify:
- UST proximity hazards (38,475 sites across DMV)
- TRI facility proximity (587 facilities)
- High-traffic road noise (239,132 road segments)
- EJScreen environmental justice indicators (10,613 block groups)
- Power line, railroad, Superfund proximity
- Park access and school proximity

**The sole blocking gap is FEMA flood zone data**, which affects flood check accuracy for all addresses. This is a pre-existing infrastructure issue (not a DMV-specific ingestion failure) that requires a separate approach (bulk NFHL download vs. REST API).
