# NES-50: Emergency Services Proximity — Implementation Plan

**Overall Progress:** `100%`

## TLDR
Add fire station and police station proximity as an informational (non-scored) section in property evaluations. Uses Overpass API (free) to find stations within 5 km, then Google Distance Matrix for drive times. Displays nearest 1 fire + 1 police station with drive time between Parks & Green Space and Proximity & Environment sections.

## Critical Decisions
- **Informational only** — displayed but does not affect the livability score
- **Overpass-only for v1** — `amenity=fire_station` + `amenity=police` (zero Overpass cost; 0-1 Distance Matrix calls)
- **Drive time, not walk time** — the relevant metric is "how fast can a truck get here"
- **Nearest 1 of each type** — user story is "how close is help," not a directory listing
- **5 km radius, no auto-expand** — show "none found within 3 miles" if empty
- **Parallel execution** — Overpass query runs in the existing ThreadPoolExecutor alongside other enrichment stages

## Files Affected
| File | Changes |
|------|---------|
| `property_evaluator.py` | New `EmergencyService` dataclass, new `get_nearby_emergency_services()` on `OverpassClient`, new `get_emergency_services()` function, new field on `EvaluationResult`, new parallel stage in `evaluate_property()` |
| `app.py` | New `emergency_services` key in `result_to_dict()` |
| `templates/_result_sections.html` | New section between Parks & Green Space and Proximity & Environment |

## Tasks

- [x] :green_square: **Phase 1: Backend Data Pipeline** (`property_evaluator.py`)
  - [x] :green_square: Add `EmergencyService` dataclass after `UrbanAccessProfile` (~line 615)
    - Fields: `name: str`, `service_type: str` ("fire"/"police"), `drive_time_min: int`, `lat: float`, `lng: float`
  - [x] :green_square: Add `OverpassClient.get_nearby_emergency_services(lat, lng, radius_meters=5000)`
    - Overpass query: both `node` and `way` for `amenity=fire_station` and `amenity=police`
    - Use `out center;` so ways return centroid coordinates
    - Same cache pattern as `get_nearby_roads()` (SHA-256 key, 7-day TTL, swallowed failures)
    - Parser: nodes use `element["lat"]`/`element["lon"]`, ways use `element["center"]["lat"]`/`element["center"]["lon"]`
    - Name fallback: "Fire Station" or "Police Station" if no `name` tag (log when this happens)
    - Returns `List[Dict]` with keys: `name`, `type`, `lat`, `lng`
  - [x] :green_square: Add `get_emergency_services(maps, overpass, lat, lng) -> List[EmergencyService]`
    - Calls `overpass.get_nearby_emergency_services(lat, lng)`
    - Groups by type, picks nearest 1 of each using haversine distance (`maps.distance_feet`)
    - If stations found: calls `maps.driving_times_batch(origin, destinations)` for the 1-2 stations
    - Returns 0-2 `EmergencyService` objects
    - Entire function wrapped in try/except returning `[]` on failure

- [x] :green_square: **Phase 2: Wiring & Serialization** (`property_evaluator.py` + `app.py`)
  - [x] :green_square: Add `emergency_services: Optional[List[EmergencyService]] = None` field on `EvaluationResult`
  - [x] :green_square: Add parallel stage in `evaluate_property()` ThreadPoolExecutor block
    - Submit `get_emergency_services` as a new future
    - Bump `max_workers` from 6 to 7
    - `_threaded_stage` auto-swaps `maps` arg; `overpass` passes through unchanged (stateless, thread-safe)
    - In collection loop: `result.emergency_services = stage_result`
  - [x] :green_square: Add serialization in `result_to_dict()` (app.py)
    - New key: `output["emergency_services"]` — list of dicts with `name`, `type`, `drive_time_min`, `lat`, `lng`
    - Empty list `[]` when no stations found (not `None` — distinguishes "searched, found nothing" from "key missing on old snapshot")

- [x] :green_square: **Phase 3: Template Rendering** (`templates/_result_sections.html`)
  - [x] :green_square: Insert new section between Parks & Green Space and Proximity & Environment
    - Outer guard: `{% if result.emergency_services is defined %}` (backward compat for old snapshots)
    - Inner guard: `{% if result.emergency_services %}` for found vs. not-found
    - Each station rendered using `.hub-row` / `.hub-info` / `.hub-name` / `.hub-detail` / `.hub-time` pattern
    - Empty state: "No fire or police stations found within 3 miles." (uses `.section-empty`)
    - No new CSS file needed

- [x] :green_square: **Phase 4: Verify**
  - [x] :green_square: Python syntax check — `property_evaluator.py` and `app.py` compile cleanly
  - [x] :green_square: Import validation — `EmergencyService`, `get_emergency_services`, `OverpassClient` method all importable
  - [x] :green_square: Parser unit test — handles nodes, ways with center, unnamed stations, ways without center (skipped)
  - [x] :green_square: Serialization test — `result_to_dict` pattern handles both populated and `None` cases
  - [x] :green_square: Jinja template syntax — `_result_sections.html` parses without errors

## Risks & Mitigations
| Risk | Mitigation |
|------|------------|
| Overpass `out center;` doesn't populate `center` on nodes | Parser checks for `element["lat"]` first, falls back to `element["center"]` |
| Unnamed stations in OSM | Fallback names + debug logging to track frequency |
| `_threaded_stage` auto-swaps `GoogleMapsClient` but not `OverpassClient` | Use wrapper function that creates per-thread Maps client and passes shared Overpass instance |
| Old snapshots missing `emergency_services` key | Template `is defined` guard hides section entirely |
