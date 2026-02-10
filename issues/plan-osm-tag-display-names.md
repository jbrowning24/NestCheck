# NES-17: Translate Raw OSM Tags to Human-Readable Descriptions

**Overall Progress:** `100%`

## TLDR
The Nature Feel subscore in the green space section displays raw OSM tag strings like `natural=wood` and `waterway=river` in its reason text. We need a display-name mapping so users see friendly labels like "Woodland" and "River" instead.

## Critical Decisions
- **Mapping location:** Add an `OSM_TAG_DISPLAY_NAMES` dict in `green_space.py` alongside the existing `NATURE_OSM_TAGS` constant — keeps all OSM tag knowledge co-located.
- **Mapping approach:** Single flat dict keyed by `"key=value"` strings (matching the existing tag format stored in `nature_tags`) rather than nested dicts — simpler lookup, no refactoring of the tag storage format needed.
- **Fallback:** If a tag has no mapping entry, title-case the value portion (e.g. `landuse=grass` → "Grass") so new tags degrade gracefully without code changes.

## Tasks

- [ ] 🟥 **Step 1: Add OSM tag display-name mapping**
  - [ ] 🟥 Add `OSM_TAG_DISPLAY_NAMES` dict in `green_space.py` near `NATURE_OSM_TAGS` (~line 133), covering all values from `NATURE_OSM_TAGS`:
    - `leisure=park` → "Park", `leisure=nature_reserve` → "Nature Reserve", `leisure=garden` → "Garden"
    - `landuse=forest` → "Forest", `landuse=meadow` → "Meadow", `landuse=grass` → "Grassland", `landuse=nature_reserve` → "Nature Reserve", `landuse=conservation` → "Conservation Area"
    - `natural=wood` → "Woodland", `natural=wetland` → "Wetland", `natural=water` → "Water", `natural=scrub` → "Scrubland", `natural=heath` → "Heathland", `natural=grassland` → "Grassland", `natural=tree_row` → "Tree Row"
    - `waterway=river` → "River", `waterway=stream` → "Stream", `waterway=canal` → "Canal"
    - `boundary=national_park` → "National Park"
  - [ ] 🟥 Add a small helper function `_display_tag(tag: str) -> str` that looks up the dict and falls back to title-casing the value portion.

- [ ] 🟥 **Step 2: Update `_score_nature_feel()` reason strings**
  - [ ] 🟥 Lines 978, 981, 984: Replace raw tag strings with `_display_tag()` calls in the reason text (e.g. `', '.join(_display_tag(t) for t in forest_water[:3])`).

- [ ] 🟥 **Step 3: Verify & test**
  - [ ] 🟥 Run a local evaluation to confirm subscore reason text shows human-readable labels.
  - [ ] 🟥 Spot-check fallback behavior for any unmapped tag.
