# Neighborhood Map — Implementation Plan

**Overall Progress:** `100%`

## TLDR
Add a server-rendered static map (PNG via `staticmap` library) to evaluation results showing the property and color-coded POI markers. Generated server-side, base64-encoded, stored in snapshot, rendered as an `<img>` tag. No client-side JS or external map APIs needed.

## Critical Decisions
- **Server-side PNG via `staticmap`**: Avoids JS map libraries, works with Railway's ephemeral disk (base64 in SQLite snapshot)
- **Stage ordering**: Map generation runs as the final stage, after `neighborhood_places` is assembled (~line 3103), so all POI coordinates are available
- **Transit marker**: `PrimaryTransitOption` has `lat`/`lng` on the dataclass but it's **not serialized** in `_serialize_urban_access()` — we read it directly from `result.urban_access.primary_transit` during map generation (pre-serialization), no need to change serialization
- **User-Agent for OSM tiles**: `staticmap` accepts a `headers` param directly in constructor — no subclassing needed
- **Graceful degradation**: Map generation wrapped in try/except; `None` result shows fallback placeholder in template

## Tasks

- [x] 🟩 **Step 1: Add dependencies**
  - [x] 🟩 Add `staticmap==0.5.7` and `Pillow==12.1.0` to `requirements.txt`
  - [x] 🟩 Verified `from staticmap import StaticMap, CircleMarker` works

- [x] 🟩 **Step 2: Create `map_generator.py`**
  - [x] 🟩 Set User-Agent via `headers` param (no subclass needed)
  - [x] 🟩 Implement `generate_neighborhood_map(property_lat, property_lng, neighborhood_places, transit_lat, transit_lng, width=640, height=400) -> str | None`
  - [x] 🟩 Property marker: blue `CircleMarker` at `(lng, lat)` — size 14 outer blue + size 10 inner white
  - [x] 🟩 POI markers from `neighborhood_places` dict — color by category (coffee=brown, grocery=green, fitness=purple, parks=dark green), size 8, skip if lat/lng is None
  - [x] 🟩 Transit marker: accepts `transit_lat`/`transit_lng` params — orange, size 10
  - [x] 🟩 Render to PNG → `io.BytesIO` → `base64.b64encode` → return string
  - [x] 🟩 Wrap entire function in try/except, log errors, return `None` on failure

- [x] 🟩 **Step 3: Add field to `EvaluationResult`**
  - [x] 🟩 Add `neighborhood_map_b64: Optional[str] = None` to the dataclass (line 588 in `property_evaluator.py`)

- [x] 🟩 **Step 4: Integrate map generation stage into `evaluate_property()`**
  - [x] 🟩 After final score calculation, add `_timed_stage("map_generation")` call
  - [x] 🟩 Pass `lat`, `lng`, `result.neighborhood_places`, and transit coords from `result.urban_access.primary_transit`
  - [x] 🟩 Outer try/except ensures failures degrade gracefully

- [x] 🟩 **Step 5: Serialize map in `result_to_dict()`**
  - [x] 🟩 Add `'neighborhood_map': result.neighborhood_map_b64` to the result dict in `app.py`

- [x] 🟩 **Step 6: Render map in template**
  - [x] 🟩 Replaced placeholder div with conditional `{% if result.neighborhood_map is defined and result.neighborhood_map %}`
  - [x] 🟩 Map present: `<img>` with base64 data URI + OSM attribution
  - [x] 🟩 Map absent: "Map not available" fallback placeholder (handles old snapshots)

- [x] 🟩 **Step 7: Verify**
  - [x] 🟩 Standalone test: map generates successfully (~182 KB base64, ~248K chars)
  - [ ] 🟥 Full evaluation for "75 Holland Place, Hartsdale, NY 10530" — requires running server with API key
  - [ ] 🟥 Old snapshot backward compatibility — requires running server
