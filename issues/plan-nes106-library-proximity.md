# NES-106: Library Proximity via Overpass

**Overall Progress:** `100%`

## TLDR
Add public library proximity as an informational section using the existing Overpass API client. Shows nearest libraries with estimated walk times. Zero Google API cost — haversine distance only with walk time estimation (~3 mph). Follows the emergency services (NES-50) pattern exactly.

## Critical Decisions
- **Informational only** — no Tier 2 scoring impact; can promote later if needed
- **Zero API cost** — haversine distance + estimated walk time (~3 mph), no Google Distance Matrix calls
- **Filter `access=private|customers`** — most public libraries won't have an `access` tag at all, so only exclude explicitly private ones
- **2km radius** — `LIBRARY_SEARCH_RADIUS_M = 2000` constant, easy to tune
- **Cap display at 3** — show all if ≤3, otherwise show nearest 3 + count within radius
- **"~" prefix on walk times** — clearly communicate estimates vs Google-sourced times elsewhere

## Tasks

- [x] 🟩 **Step 1: Overpass query — `OverpassClient.get_nearby_libraries()`**
  - [x] 🟩 Add `LIBRARY_SEARCH_RADIUS_M = 2000` constant near existing radius constants
  - [x] 🟩 Add `get_nearby_libraries(lat, lng, radius_meters=LIBRARY_SEARCH_RADIUS_M)` method to `OverpassClient` (~line 1375, after `_parse_emergency_services`)
  - [x] 🟩 Query: `node["amenity"="library"]` + `way["amenity"="library"]` with `out center;` — same structure as emergency services
  - [x] 🟩 Add `_parse_libraries()` static method — extract name/lat/lng, filter out `access=private` and `access=customers`, fallback name "Public Library"
  - [x] 🟩 Use existing SQLite cache pattern (SHA-256 key, 7-day TTL) and `_traced_post()`

- [x] 🟩 **Step 2: Processing function — `get_library_proximity()`**
  - [x] 🟩 Add `NearbyLibrary` dataclass after `EmergencyService` (~line 699): `name`, `distance_ft`, `est_walk_min`, `lat`, `lng`
  - [x] 🟩 Add `nearby_libraries` field to `EvaluationResult` (~line 774, after `emergency_services`): `Optional[List[NearbyLibrary]] = None`
  - [x] 🟩 Add `get_library_proximity(overpass, lat, lng)` function after `get_emergency_services()` (~line 1491) — no `maps` param needed since we're not calling Google
  - [x] 🟩 Sort by haversine distance (reuse haversine math from `distance_feet`), return up to 3 nearest as `NearbyLibrary` objects + total count within radius
  - [x] 🟩 Estimated walk time: `round(distance_ft / 5280 / 3.0 * 60)` (3 mph walking speed)
  - [x] 🟩 Return `[]` for none found, `None` on failure (same 3-state convention)

- [x] 🟩 **Step 3: Wire into evaluation pipeline**
  - [x] 🟩 Add parallel stage in `evaluate_property()` ThreadPoolExecutor (~line 3883, after emergency_services): `futures["nearby_libraries"] = pool.submit(_threaded_stage, "nearby_libraries", get_library_proximity, overpass, lat, lng)`
  - [x] 🟩 Note: no `maps` argument needed — function only uses `overpass` client (thread-safe, stateless)
  - [x] 🟩 Add result collection in the futures loop (~line 3912, after emergency_services): `result.nearby_libraries = stage_result`

- [x] 🟩 **Step 4: Serialization — `result_to_dict()`**
  - [x] 🟩 Add serialization block in `app.py` `result_to_dict()` (~line 1140, after emergency_services block)
  - [x] 🟩 Serialize each `NearbyLibrary` to dict: `name`, `distance_ft`, `est_walk_min`, `lat`, `lng`
  - [x] 🟩 Include `library_count` (total count within radius) alongside the list
  - [x] 🟩 Follow same `None` vs `[]` three-state pattern

- [x] 🟩 **Step 5: Template section**
  - [x] 🟩 Add section in `_result_sections.html` after emergency services block (~line 408) with comment `{# ── 5.6 NEARBY LIBRARIES ──`
  - [x] 🟩 Three-state guard: `{% if result.nearby_libraries is defined and result.nearby_libraries is not none %}`
  - [x] 🟩 Hub-row layout per library: name on left, `~X min walk` on right (tilde prefix signals estimate)
  - [x] 🟩 Count context line below the list: e.g., "3 libraries within 1.2 mi" (convert 2km to display miles)
  - [x] 🟩 Empty state: "No public libraries found within 1.2 mi."
