# NES-31: Transit Accessibility Data — Implementation Plan

**Overall Progress:** `100%`

## TLDR
Add wheelchair-accessible entrance and elevator presence data to the transit card for rail stations. Two data sources (Google Places field addition + new Overpass query), displayed as two inline annotation lines. No scoring impact, no new API costs.

## Critical Decisions
- **Google Places + Overpass only** — GTFS feeds deferred; universal sources work for any address without per-agency feed management
- **Rail stations only** — bus stops are street-level; vehicle accessibility data unavailable, so annotations would just add noise
- **No scoring impact** — data too spotty to penalize scores; purely informational for V1
- **Always show both lines** — consistency over brevity; user sees same structure whether confirmed, denied, or unverified
- **Overpass 150m radius** — query for `node["elevator"="yes"]` near station coords; zero results = unverified, not absent

## Tasks

- [x] 🟩 **Step 1: Extend `PrimaryTransitOption` dataclass**
  - [x] 🟩 Add `wheelchair_accessible_entrance: Optional[bool] = None` field
  - [x] 🟩 Add `elevator_available: Optional[bool] = None` field

- [x] 🟩 **Step 2: Add `wheelchair_accessible_entrance` to Google Places call**
  - [x] 🟩 Add field to `place_details` fields list (refactored `get_parking_availability` → `get_station_details`)
  - [x] 🟩 Map result onto `PrimaryTransitOption.wheelchair_accessible_entrance`

- [x] 🟩 **Step 3: New Overpass query for elevator nodes**
  - [x] 🟩 Add `has_nearby_elevators()` to OverpassClient — `out count` for efficiency
  - [x] 🟩 Return `True` if count > 0, `None` if zero (unverified, not absent)
  - [x] 🟩 Thread `overpass` through `get_urban_access_profile` → `find_primary_transit`

- [x] 🟩 **Step 4: Serialize new fields in `app.py`**
  - [x] 🟩 Add `wheelchair_accessible_entrance` and `elevator_available` to `_serialize_urban_access()` primary_transit dict

- [x] 🟩 **Step 5: Render accessibility lines on transit card**
  - [x] 🟩 Add two-line accessibility annotation below station info in `_result_sections.html`
  - [x] 🟩 Three states per line: "Yes" / "No" / "Unverified — check with transit agency"
  - [x] 🟩 Only render when primary transit exists (rail stations)

- [x] 🟩 **Step 6: Test with reference addresses**
  - [x] 🟩 All 15 existing transit tests pass — no regressions
  - [x] 🟩 Dataclass defaults, explicit values, and serialization verified
  - [x] 🟩 Jinja2 tri-state rendering (True/False/None) confirmed correct
  - [x] 🟩 162/178 tests pass (16 failures pre-existing, unrelated)
