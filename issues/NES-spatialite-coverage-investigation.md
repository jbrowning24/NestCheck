# Investigation: SpatiaLite Data Coverage & Duplicate Proximity Checks

**Date:** 2026-03-03
**Status:** Investigation complete — no code changes

## Context

User validation testing on four Westchester County addresses revealed:
1. Four safety checks consistently show "Unable to verify automatically": high-traffic road (FHWA), flood zone (FEMA), EPA Superfund (SEMS), and EPA TRI
2. Reports show contradictory results for TRI — both a ✓ pass AND a ⚠ unable-to-verify for the same evaluation
3. Grocery/provisioning reports "No grocery & essentials found within about 10 miles" despite real stores nearby

Test addresses: Scarsdale (~41.005, -73.784), Valhalla (~41.089, -73.773), Hawthorne (~41.107, -73.798), Briarcliff Manor (~41.143, -73.838)

---

## Findings Summary

### Issue 1 (Critical): `ensure_spatial_data()` never called

- **File:** `startup_ingest.py:46` — function is defined but never imported or called
- **Impact:** Spatial data is only loaded via manual script execution, not during deployment
- **Evidence:** Searched all .py files for `ensure_spatial_data` and `from startup_ingest` — zero imports found
- **Expected wiring:** `gunicorn_config.py:post_fork()` should call it, but only calls `start_worker()` and `start_monitor()`

### Issue 2 (High): FEMA bbox excludes Westchester County

- **File:** `scripts/ingest_fema.py:54` — `METRO_BBOXES["nyc"]` = `(-74.3, 40.45, -73.65, 40.95)`
- **Impact:** Max latitude 40.95 excludes all Westchester addresses (lat 41.0+)
- **Fix needed:** Extend bbox to cover Westchester (lat_max ~41.35)

### Issue 3 (High): Phase 1B checks produce false PASSes when data unavailable

- **Files:** `property_evaluator.py` — `check_ust_proximity()` (L1982), `check_tri_proximity()` (L2056), `check_hifld_power_lines()` (L2118), `check_rail_proximity()` (L2170)
- **Root cause:** These functions call `find_facilities_within()` / `lines_within()` which return `[]` when unavailable, then interpret empty results as "no nearby hazards" → PASS
- **Contrast:** Legacy checks (`check_high_traffic_road`, `check_flood_zones`, `check_superfund_npl`, `check_tri_facility_proximity`) correctly check `is_available()` or `last_query_failed()` before returning UNKNOWN

### Issue 4 (Medium): Duplicate TRI checks show contradictory results

- **Two functions query the same `facilities_tri` table:**
  - `check_tri_facility_proximity()` (L1889) — name `"TRI facility"`, checks `is_available()` → UNKNOWN when data missing
  - `check_tri_proximity()` (L2056) — name `"tri_proximity"`, no availability check → false PASS
- **Both unconditionally added** to `result.tier1_checks` (L4557-4598)
- **Display:** `"TRI facility"` collapsed to "EPA Toxic Release Inventory — Unable to verify automatically"; `"tri_proximity"` rendered individually as "No EPA toxic release facilities within 1 mile"
- **Note:** Superfund has explicit deduplication at L1325-1327; TRI has none

### Issue 5 (Medium): Grocery search radius vs display mismatch + aggressive filtering

- **File:** `property_evaluator.py:4031-4032` — actual radius: 3,000m (~1.86 miles)
- **File:** `templates/_result_sections.html:304` — display: "within about 10 miles"
- **Excluded types filter** (L4049): Supermarkets tagged with `gas_station` or `pharmacy` are excluded
- **Quality threshold** (L4068): Requires rating >= 4.0 AND >= 50 reviews — strict for suburban areas

---

## SpatiaLite Table Reference

| Table | Geometry | Check Function | Fallback? |
|---|---|---|---|
| `facilities_ust` | POINT | `check_gas_stations()`, `check_ust_proximity()` | Google Places (gas_stations only) |
| `facilities_tri` | POINT | `check_tri_facility_proximity()`, `check_tri_proximity()`, `check_industrial_zones()` | Overpass (industrial only) |
| `facilities_sems` | MULTIPOLYGON | `check_superfund_npl()` | None |
| `facilities_fema_nfhl` | MULTIPOLYGON | `check_flood_zones()` | None |
| `facilities_hpms` | MULTILINESTRING | `check_high_traffic_road()` | None |
| `facilities_hifld` | MULTILINESTRING | `check_power_lines()`, `check_hifld_power_lines()` | Overpass (power_lines only) |
| `facilities_fra` | MULTILINESTRING | `check_rail_proximity()` | None |
| `facilities_ejscreen` | POINT | `_query_ejscreen_block_group()` | None |

Checks that work for Westchester succeed because they either:
- Use Overpass/Google Places (substations, cell towers) — no SpatiaLite dependency
- Have fallbacks (gas stations → Google Places, power lines → Overpass, industrial → Overpass)
- Produce false PASSes from empty data (Phase 1B UST, TRI, HIFLD, rail)
