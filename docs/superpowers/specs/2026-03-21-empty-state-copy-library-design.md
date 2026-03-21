# NES-319: Empty State Copy Library Design

**Date:** 2026-03-21
**Status:** Approved
**Blocked by:** NES-264 (StageDegradation dataclass) for wiring — copy library is standalone

## Problem

When data is unavailable or a section can't render, the report shows generic messages like "data unavailable" or "could not be verified" without explaining why or what the user should do. This fails as UX (user is confused) and as marketing (shared evaluations look broken).

## Solution

A standalone Python module (`copy_library.py`) containing a lookup table mapping `(check_name, failure_type) → CopyEntry`. Each entry provides three fields — **what** happened, **why** it happened, and **so_what** (what it means for the user). The module has zero dependencies and is ready to wire into templates once NES-264 lands.

## Design Decisions

### Approach: Per-check copy with failure-type variants (Approach C)

Organized by check/section first, with failure-type variants nested inside. The template's natural question is "I'm rendering this check and it failed — what do I show?" — not "I have an F4, what checks does that affect?"

Rejected alternatives:
- **Approach A (flat `(F-type, check)` tuple keys):** Maximum editorial control but ~80 entries with duplicated F1 boilerplate. Maintenance burden without proportional benefit.
- **Approach B (shared F-type templates + overrides):** Two lookup paths add complexity. Risk of generic fallback when specific copy would be better.

### Failure taxonomy

Maps 1:1 to UI Design Spec Section 4.12.1, with one addition:

| Type | Meaning | Applies to |
|------|---------|------------|
| `F1` | API temporarily unavailable | Health checks, dimensions |
| `F2` | Data source stale or outdated | EJScreen |
| `F3` | Google Places returning zero POI results | Places-backed dimensions |
| `F4` | Health check with no data source coverage | Health checks |
| `F5` | Entire section has insufficient data to render | Dimensions |
| `F6` | Complete evaluation failure | Standalone (whole-page) |
| `input_missing` | User/listing input not provided | Listing amenity checks |

`input_missing` is distinct from F5 because it represents a user input gap, not a system/pipeline failure. They trigger different UI treatments — F5 gets the informational callout pattern, `input_missing` renders as a quiet absence with a hint. Overloading F5 would create confusion at NES-264 wiring time.

### Tone

Per UI spec Section 4.11 and the copy audit voice guide:
- **Interpret, don't editorialize.** "Most residents drive for daily errands at this distance" — not "This is a terrible location for groceries."
- **Confident analyst, not customer support.** Matter-of-fact about scope limitations. No "sorry," no "unfortunately."
- **F5 is a finding, not an error.** The absence of data IS the evaluation. "We didn't find transit options within walking distance. Driving will likely be the primary way to get around."
- **Actionable when possible.** F4 `so_what` entries point to concrete next steps (satellite imagery, Phase I ESA, lender requirements).

### F6 is standalone

F6 (complete evaluation failure) has no check context — it's a whole-page state. Stored as `EVALUATION_FAILURE_COPY` at module level, not nested under a check name.

## Module Structure

**File:** `copy_library.py` (project root, alongside `property_evaluator.py`)

### Exports

```python
from dataclasses import dataclass

@dataclass(frozen=True)
class CopyEntry:
    what: str
    why: str
    so_what: str

    @property
    def combined(self) -> str:
        """Joins fields into a single string for compact display contexts."""
        return f"{self.what} {self.why} {self.so_what}"
```

- `CopyEntry` — frozen dataclass. Typos in field names fail at construction, not at render time.
- `COPY_LIBRARY: dict[str, dict[str, CopyEntry]]` — `check_name → failure_type → CopyEntry`
- `CHECK_NAME_ALIASES: dict[str, str]` — maps evaluator check names to copy library keys (see Key Naming below)
- `EVALUATION_FAILURE_COPY: CopyEntry` — standalone F6 entry
- `get_copy(check_name: str, failure_type: str) -> CopyEntry | None` — resolves aliases, then looks up. Returns `None` on miss so the caller can fall back to current generic text during migration. Logs a `logger.debug` on miss to track migration completeness and surface key mismatch bugs.

### Key naming and aliases

Copy library keys use clean snake_case identifiers (`flood_zone`, `ust_proximity`, `tri_proximity`). The evaluator uses inconsistent names — legacy checks have display names (`"Power lines"`, `"Gas station"`, `"Superfund (NPL)"`), Phase 1B spatial checks use snake_case (`"hifld_power_lines"`, `"ust_proximity"`), and listing amenity checks use display names (`"W/D in unit"`, `"Central air"`, `"Size"`, `"Bedrooms"`).

`CHECK_NAME_ALIASES` maps evaluator names to copy library keys:

```python
CHECK_NAME_ALIASES = {
    # Legacy display names → copy library keys
    "Flood zone": "flood_zone",
    "Power lines": "power_lines",
    "Gas station": "gas_station",
    "Superfund (NPL)": "superfund",
    "High-traffic road": "high_traffic_road",
    "TRI facility": "tri_proximity",
    "Industrial zone": "industrial_zone",
    "Electrical substation": "electrical_substation",
    "Cell tower": "cell_tower",
    # Phase 1B spatial names (already snake_case, but some differ)
    "hifld_power_lines": "power_lines",
    # Listing amenity display names
    "W/D in unit": "washer_dryer",
    "Central air": "central_air",
    "Size": "square_footage",
    "Bedrooms": "bedrooms",
    # EJScreen per-indicator names all resolve to block-group-level copy
    "EJScreen PM2.5": "ejscreen",
    "EJScreen cancer risk": "ejscreen",
    "EJScreen diesel PM": "ejscreen",
    "EJScreen lead paint": "ejscreen",
    "EJScreen Superfund": "ejscreen",
    "EJScreen hazardous waste": "ejscreen",
}
```

`get_copy()` resolves aliases first: `key = CHECK_NAME_ALIASES.get(check_name, check_name)`, then looks up `COPY_LIBRARY[key][failure_type]`. Names already matching a copy library key (e.g., `"flood_zone"`) pass through unchanged.

**EJScreen note:** The six per-indicator EJScreen check names all resolve to the single `ejscreen` entry. F1 fires only when the entire block group query fails — individual indicator checks don't independently produce F1/F2.

### `combined` property note

Space-separated concatenation works for most entries, but F4/F5 entries with actionable `so_what` strings (e.g., flood zone lender guidance) can feel abrupt when concatenated after a `why`. Flagged for CMO review. The NES-264 template wiring will almost certainly use the three-field version.

### Adding new checks

When adding a new health check or dimension to the evaluator, add corresponding copy entries to `copy_library.py` in the same commit. If the evaluator check name differs from the copy library key, add an alias to `CHECK_NAME_ALIASES`.

## Copy Inventory

### Tier 1 Health Checks (12 check keys, 21 entries)

Note: `power_lines` serves both legacy `"Power lines"` and spatial `"hifld_power_lines"` via aliases. `electrical_substation` and `cell_tower` have F1 only — zero Overpass results for these checks are treated as PASS (no nearby hazard), not as a failure state.

#### `flood_zone`

| F-type | what | why | so_what |
|--------|------|-----|---------|
| F1 | Flood zone data is temporarily unavailable. | FEMA's mapping service isn't responding right now. | This check is not included in your health summary. |
| F4 | FEMA flood maps don't cover this area. | Coverage is metro-based — addresses outside mapped metro areas fall outside the current dataset. | If you're financing a purchase, your lender may require a separate flood determination. |

#### `ust_proximity`

| F-type | what | why | so_what |
|--------|------|-----|---------|
| F1 | Underground storage tank data could not be queried. | The environmental dataset encountered an error during lookup. | This check is not included in your health summary. |
| F4 | Underground storage tank data is not available for this area. | EPA UST records have not been ingested for this state yet. | A Phase I environmental site assessment would cover underground storage tanks if this is a concern. |

#### `high_traffic_road`

| F-type | what | why | so_what |
|--------|------|-----|---------|
| F1 | Traffic volume data could not be queried. | The federal highway dataset encountered an error during lookup. | This check is not included in your health summary. |
| F4 | Traffic volume data is not available for this area. | Federal highway monitoring data has not been ingested for this state. | High-traffic roads can be assessed in person during peak commute hours. |

#### `power_lines` / `hifld_power_lines`

| F-type | what | why | so_what |
|--------|------|-----|---------|
| F1 | Transmission line data is temporarily unavailable. | The infrastructure dataset used for this check isn't responding right now. | This check is not included in your health summary. |
| F4 | Transmission line data is not available for this area. | Federal transmission line records have not been loaded for this region. | High-voltage lines are visible on satellite imagery — check the map view. |

#### `electrical_substation`

| F-type | what | why | so_what |
|--------|------|-----|---------|
| F1 | Electrical substation data is temporarily unavailable. | OpenStreetMap's data service isn't responding right now. | Substations are typically visible on satellite imagery. |

#### `cell_tower`

| F-type | what | why | so_what |
|--------|------|-----|---------|
| F1 | Cell tower data is temporarily unavailable. | OpenStreetMap's data service isn't responding right now. | Cell towers are typically visible on satellite imagery. |

#### `industrial_zone`

| F-type | what | why | so_what |
|--------|------|-----|---------|
| F1 | Industrial zone data could not be queried. | The environmental or land-use dataset encountered an error. | This check is not included in your health summary. |
| F4 | Industrial facility data is not available for this area. | EPA Toxics Release Inventory data has not been ingested for this state. | Nearby industrial activity can be assessed from satellite imagery and local zoning maps. |

#### `tri_proximity`

| F-type | what | why | so_what |
|--------|------|-----|---------|
| F1 | Toxic release facility data could not be queried. | The EPA TRI spatial dataset encountered an error. | This check is not included in your health summary. |
| F4 | Toxic release facility data is not available for this area. | EPA TRI records have not been ingested for this state. | For properties near visible industrial sites, a Phase I environmental assessment would cover this. |

#### `superfund`

| F-type | what | why | so_what |
|--------|------|-----|---------|
| F1 | Superfund site data could not be queried. | The EPA National Priorities List spatial dataset encountered an error. | This check is not included in your health summary. |
| F4 | Superfund site data is not available for this area. | EPA NPL boundaries have not been ingested for this state. | Active Superfund sites are publicly listed on the EPA website by state. |

#### `rail_proximity`

| F-type | what | why | so_what |
|--------|------|-----|---------|
| F1 | Rail corridor data could not be queried. | The federal rail dataset encountered an error. | This check is not included in your health summary. |
| F4 | Rail corridor data is not available for this area. | FRA rail network data has not been ingested for this state. | Rail corridors are visible on satellite imagery and produce audible noise within a few hundred feet. |

#### `gas_station` (legacy Google Places fallback)

| F-type | what | why | so_what |
|--------|------|-----|---------|
| F1 | Gas station proximity could not be verified. | The mapping service used for this check isn't responding. | Check the satellite view to inspect the immediate surroundings. |

#### `ejscreen`

| F-type | what | why | so_what |
|--------|------|-----|---------|
| F1 | EPA environmental screening data is not available for this area. | EJScreen block group data has not been ingested for this census tract. | Area-level environmental indicators are not included in this evaluation. |
| F2 | EPA environmental data for this area may be outdated. | EJScreen is refreshed annually. The current dataset reflects conditions as of {vintage_year}. | Indicator trends are generally stable year-to-year, but specific percentiles may shift. |

Note: `{vintage_year}` is a placeholder. NES-264 wiring will inject the actual vintage year from ingestion metadata.

### Tier 2 Dimensions (6 dimensions, 16 entries)

#### `coffee_social`

| F-type | what | why | so_what |
|--------|------|-----|---------|
| F1 | Coffee and social spot data is temporarily unavailable. | The places service isn't responding right now. | This dimension is not included in your score. |
| F3 | No coffee shops, cafes, or social spots found in the search area. | Residential areas outside town centers often lack dedicated third places within walking distance. | Newer or independent venues are sometimes missing from the index — check locally if this seems off. |
| F5 | Not enough venue data to score this dimension. | Too few venues with sufficient review history were found to produce a reliable score. | This dimension is not included in your score. |

#### `provisioning`

| F-type | what | why | so_what |
|--------|------|-----|---------|
| F1 | Grocery and daily essentials data is temporarily unavailable. | The places service isn't responding right now. | This dimension is not included in your score. |
| F3 | No grocery stores found within the search radius. | Grocery stores tend to cluster near commercial corridors and may not be present within walking distance of every address. | Most residents at this distance drive for daily provisioning. |
| F5 | Not enough grocery data to score this dimension. | Too few stores with sufficient review history were found to produce a reliable score. | This dimension is not included in your score. |

#### `fitness`

| F-type | what | why | so_what |
|--------|------|-----|---------|
| F1 | Fitness facility data is temporarily unavailable. | The places service isn't responding right now. | This dimension is not included in your score. |
| F3 | No gyms or fitness facilities found in the search area. | Gyms and fitness centers tend to cluster in commercial areas and may not be present within the search radius. | Home workouts or driving to a facility outside the search area are likely the primary options. |
| F5 | Not enough fitness facility data to score this dimension. | Too few facilities with sufficient review history were found to produce a reliable score. | This dimension is not included in your score. |

#### `green_space`

| F-type | what | why | so_what |
|--------|------|-----|---------|
| F1 | Park and green space data is temporarily unavailable. | The data services used for park discovery aren't responding right now. | This dimension is not included in your score. |
| F3 | No parks or green spaces found within the search radius. | Formal parks may not exist nearby, and informal green spaces or trails are often not indexed. | Satellite imagery can help identify informal green spaces, trails, or preserved land nearby. |
| F5 | Not enough park data to score this dimension. | Park data was found but lacked sufficient detail (boundaries, reviews) for a reliable score. | This dimension is not included in your score. |

#### `transit`

| F-type | what | why | so_what |
|--------|------|-----|---------|
| F1 | Transit data is temporarily unavailable. | The transit data service isn't responding right now. | This dimension is not included in your score. |
| F5 | No transit options found within walking distance. | This area does not appear to have fixed-route public transit coverage. | Driving will likely be the primary way to get around. |

#### `road_noise`

| F-type | what | why | so_what |
|--------|------|-----|---------|
| F1 | Road noise data is temporarily unavailable. | The traffic data service isn't responding right now. | This dimension is not included in your score. |
| F5 | Road noise could not be estimated for this area. | Traffic noise modeling requires road segment data that is not available for this state. | Road noise can be assessed in person — visit during weekday rush hours for a representative sample. |

### User Input Gaps (5 checks, 5 entries)

These use `input_missing` — distinct from F5 because they represent a user input gap, not a system/pipeline failure. Includes listing amenity checks and the cost dimension (which depends on user-provided data, not an API or data pipeline).

#### `cost`

| F-type | what | why | so_what |
|--------|------|-----|---------|
| input_missing | Monthly cost was not provided. | No monthly housing cost was provided for this evaluation. | Cost is not factored into your overall score. |

#### `washer_dryer`

| F-type | what | why | so_what |
|--------|------|-----|---------|
| input_missing | Washer/dryer availability was not specified. | This information was not provided for this evaluation. | Check the listing details or ask the landlord directly. |

#### `central_air`

| F-type | what | why | so_what |
|--------|------|-----|---------|
| input_missing | Central air availability was not specified. | This information was not provided for this evaluation. | Check the listing details or ask the landlord directly. |

#### `square_footage`

| F-type | what | why | so_what |
|--------|------|-----|---------|
| input_missing | Square footage was not specified. | This information was not provided for this evaluation. | Verify square footage from the listing or during a tour. |

#### `bedrooms`

| F-type | what | why | so_what |
|--------|------|-----|---------|
| input_missing | Bedroom count was not specified. | This information was not provided for this evaluation. | Verify bedroom count from the listing or during a tour. |

### F6 — Complete Evaluation Failure (standalone)

| Field | Copy |
|-------|------|
| what | We couldn't evaluate this address. |
| why | This may be due to a temporary issue, an unrecognizable address format, or an area we don't cover yet. |
| so_what | Try again in a few minutes. If the problem persists, report it so we can investigate. |

## Wiring Notes (for NES-264)

1. **`get_copy()` returns `None` on miss.** During migration, the template can fall back to current generic text. The copy library can be incomplete and still safe.
2. **`StageDegradation` metadata tells the template which `(check_name, failure_type)` to look up.** The copy library provides the content; the degradation dataclass provides the key.
3. **`{vintage_year}` placeholder** in ejscreen F2 — inject from ingestion metadata at render time.
4. **`input_missing` vs `F5`** — these need different UI treatments. F5 gets the informational callout pattern (caution variant per spec 4.12.1). `input_missing` renders as a quiet absence with a hint (no callout, no severity signal).
5. **`combined` property** — use the three-field version in templates. Reserve `combined` for contexts that genuinely need a single string (e.g., meta descriptions, tooltips).
6. **F3 "suspected bad data"** (misclassified POI with caution badge) is handled by the confidence badge system, not the copy library. The copy library covers F3 zero-results only.
7. **Walk Score** is listed in the UI spec F1 examples but is not a current data source. No copy entry needed unless Walk Score is added as a dimension.

## Inventory

| Category | Checks/Sections | F-types | Entries |
|----------|-----------------|---------|---------|
| Tier 1 health | 12 check keys | F1, F2, F4 | 21 |
| Tier 2 dimensions | 6 | F1, F3, F5 | 16 |
| User input gaps | 5 | input_missing | 5 |
| F6 standalone | 1 | F6 | 1 |
| **Total** | **24** | **7 types** | **43** |
