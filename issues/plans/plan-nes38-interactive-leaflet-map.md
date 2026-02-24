# NES-38: Replace Static Map with Interactive Leaflet.js Map

**Overall Progress:** `100%`

## TLDR
Replace the server-rendered static PNG map with an interactive Leaflet.js map using CartoDB Positron tiles. Users can zoom, pan, click markers for details, and toggle POI categories. Same data, no new API calls, no layout changes.

## Critical Decisions
- **Leaflet.js + CartoDB Positron tiles** — free, lightweight (~40KB), no API key, muted palette that won't compete with markers
- **CDN delivery** — load Leaflet CSS/JS from `unpkg.com/leaflet`, consistent with existing external CDN usage (Google Fonts)
- **Keep `map_generator.py`** — stop rendering static `<img>` in HTML but retain the module for future PDF export
- **Built-in Leaflet layer control** — standard checkbox panel for category toggling, no custom UI
- **No sticky/scroll-sync** — basic map in current position, scrolls with content
- **No green space polygons** — pin markers only for all categories

## Tasks

- [x] 🟩 **Step 1: Add Leaflet CSS/JS to base templates**
  - [x] 🟩 Add Leaflet CSS `<link>` to `_base.html` `head_extra` or directly in `<head>` (before page CSS so we can override)
  - [x] 🟩 Add Leaflet JS `<script>` to `_base.html` before `{% block scripts %}` so it's available in both `index.html` and `snapshot.html`
  - [x] 🟩 Use versioned CDN URLs (e.g., `unpkg.com/leaflet@1.9.4/dist/...`)

- [x] 🟩 **Step 2: Fix transit `lat`/`lng` serialization gap**
  - [x] 🟩 Add `lat` and `lng` to the `primary_transit` dict in `_serialize_urban_access()` ([app.py:998-1009](app.py#L998-L1009))
  - [x] 🟩 Verify the `PrimaryTransitOption` dataclass has `lat`/`lng` fields (confirmed: [property_evaluator.py:594-595](property_evaluator.py#L594-L595))

- [x] 🟩 **Step 3: Create `static/js/neighborhood-map.js`**
  - [x] 🟩 Initialize Leaflet map on `#neighborhood-map-leaflet` div with CartoDB Positron tile layer
  - [x] 🟩 Add property marker (blue circleMarker, white border)
  - [x] 🟩 Add POI markers per category with distinct colors matching map_generator.py scheme
  - [x] 🟩 Add transit marker (orange) if transit data present
  - [x] 🟩 Create popups showing name, rating, review count, walk time
  - [x] 🟩 Wire up `L.control.layers` with overlay groups per category + transit
  - [x] 🟩 Auto-fit bounds with padding, maxZoom 16
  - [x] 🟩 Zoom constraints min:12, max:18; scroll-wheel zoom disabled until click
  - [x] 🟩 Data via `#nc-map-data` JSON script block

- [x] 🟩 **Step 4: Update `_result_sections.html` map section**
  - [x] 🟩 Replace static `<img>` with `#neighborhood-map-leaflet` div container
  - [x] 🟩 Embed map data as `#nc-map-data` JSON script block (coordinates, places, transit)
  - [x] 🟩 Fallback placeholder preserved for old snapshots / missing data
  - [x] 🟩 Attribution handled by Leaflet tile layer config (OSM + CARTO)

- [x] 🟩 **Step 5: Update CSS**
  - [x] 🟩 `.map-leaflet` at 400px height; removed unused `.map-image` / `.map-attribution`
  - [x] 🟩 Leaflet layer control styled with `--font-sans`, `--font-size-body-5`, `--radius-sm`
  - [x] 🟩 Mobile: 300px height at ≤640px breakpoint (touch zoom inherent in Leaflet)

- [x] 🟩 **Step 6: Verify both rendering paths**
  - [x] 🟩 Leaflet script included in both `index.html` and `snapshot.html` via `_base.html` + per-page scripts
  - [x] 🟩 Template syntax verified (Jinja parse OK for all 4 templates)
  - [x] 🟩 JS syntax verified (node --check passes)
  - [x] 🟩 Backward compatibility: old snapshots without `coordinates`/`neighborhood_places` fall through to placeholder
