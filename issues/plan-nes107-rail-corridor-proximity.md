# NES-107: Rail Corridor Proximity Check via Overpass

**Overall Progress:** `100%`

## TLDR
Add a Tier 1 proximity-hazard check for active rail lines using Overpass API (`railway=rail`). Queries 750m radius, reports nearest rail segment distance with four severity bands, and flags nearby level crossings for horn noise. Zero Google Maps API cost — uses existing `OverpassClient` with SQLite cache.

## Critical Decisions
- **Tier 1 check, not Tier 2 scored** — distance + severity label only, no scoring curve or dBA estimation. Keeps it consistent with `check_highway()` / `check_high_volume_roads()`.
- **750m search radius** — larger than road checks (200m) because rail noise (especially freight) carries further. Severity thresholds handle the "how close is concerning" part.
- **Four severity bands** — `<100m` high concern, `100-300m` moderate, `300-500m` notable, `500m+` clear. The 300-500m band matters for horn noise at crossings.
- **Level crossings included** — query `railway=level_crossing` in the same Overpass call; flag presence in result text. Horn noise at crossings is often the biggest complaint.
- **Filter conservatively** — `railway=rail` minus `abandoned=yes`, `disused=yes`, `railway=construction`. Keep sidings/yards/spurs (living near a rail yard is worth flagging).
- **Capture v2 tags without acting on them** — store `usage` and `service` tags in result for future enrichment, but don't differentiate severity yet.

## Tasks

- [x] 🟩 **Step 1: Add `check_rail_corridor()` function to `property_evaluator.py`**
  - [x] 🟩 Add Overpass query method `get_nearby_rail(lat, lng, radius_m=750)` to `OverpassClient` — queries `railway=rail` ways + `railway=level_crossing` nodes, with SQLite caching
  - [x] 🟩 Parse response: extract way geometry (node coords → polyline), way `name`/`usage`/`service` tags, and level crossing nodes
  - [x] 🟩 Calculate nearest-point distance (haversine point-to-polyline, reuse pattern from `road_noise.py`)
  - [x] 🟩 Filter out `abandoned=yes`, `disused=yes`, `construction=yes` in the query or parse step
  - [x] 🟩 Implement `check_rail_corridor(overpass, lat, lng)` returning `Tier1Check` with `distance_ft`, name (OSM `name` tag or "Active rail line" fallback), and level crossing flag in details text

- [x] 🟩 **Step 2: Wire into presentation layer**
  - [x] 🟩 Add `"Rail corridor"` to `SAFETY_CHECKS`, `CHECK_DISPLAY_NAMES`, `PROXIMITY_THRESHOLDS`, and `_SYNTHESIS_LABELS`
  - [x] 🟩 Add `_proximity_explanation()` branch for "Rail corridor" with band-aware prose (mention level crossing horn noise when applicable)
  - [x] 🟩 `_generate_headline()` — no custom branch needed; existing generic safety-check logic handles it automatically

- [x] 🟩 **Step 3: Integrate into evaluation pipeline**
  - [x] 🟩 Call `check_rail_corridor()` in the tier1_checks stage of `evaluate_property()`, alongside existing highway/road checks
  - [x] 🟩 Use the same retry/sentinel pattern as the existing road checks (share the Overpass failure handling)

- [x] 🟩 **Step 4: Verify end-to-end**
  - [x] 🟩 Overpass query returns Harlem Line (13 segments) near Scarsdale, zero near Saxon Woods
  - [x] 🟩 check_rail_corridor: 112 ft → FAIL/VERY_CLOSE, 801 ft → FAIL/NOTABLE, no rail → PASS
  - [x] 🟩 Presentation layer: headlines, explanations, and proximity bands all render correctly
  - [x] 🟩 Level crossing horn noise prose appended when crossings present
  - [x] 🟩 No changes needed to app.py or templates — existing generic safety-check rendering handles it
