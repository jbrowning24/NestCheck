# NES-319: Empty State Copy Library Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create a standalone Python module (`copy_library.py`) containing 43 what/why/so_what copy entries for every empty state and failure mode in NestCheck evaluation reports.

**Architecture:** Single file, zero dependencies beyond stdlib. Frozen dataclass for entries, nested dict for lookup, alias dict for evaluator name resolution, one public function `get_copy()`. Follows the same standalone module pattern as `overflow.py`.

**Tech Stack:** Python 3.13, dataclasses, logging, pytest

**Spec:** `docs/superpowers/specs/2026-03-21-empty-state-copy-library-design.md`

---

## File Map

| File | Action | Responsibility |
|------|--------|---------------|
| `copy_library.py` | Create | CopyEntry dataclass, COPY_LIBRARY dict, CHECK_NAME_ALIASES, EVALUATION_FAILURE_COPY, get_copy() |
| `tests/test_copy_library.py` | Create | Structural tests, alias resolution, get_copy behavior, inventory completeness |

Two files total. No modifications to existing files — this is a standalone module.

---

### Task 1: CopyEntry dataclass + get_copy() function with tests

**Files:**
- Create: `tests/test_copy_library.py`
- Create: `copy_library.py`

- [ ] **Step 1: Write failing tests for CopyEntry and get_copy()**

```python
"""Tests for the empty state copy library (NES-319)."""

import pytest
from copy_library import CopyEntry, COPY_LIBRARY, CHECK_NAME_ALIASES, EVALUATION_FAILURE_COPY, get_copy


class TestCopyEntry:
    def test_frozen(self):
        entry = CopyEntry(what="a", why="b", so_what="c")
        with pytest.raises(AttributeError):
            entry.what = "changed"

    def test_combined(self):
        entry = CopyEntry(what="A.", why="B.", so_what="C.")
        assert entry.combined == "A. B. C."

    def test_fields_required(self):
        with pytest.raises(TypeError):
            CopyEntry(what="a", why="b")  # missing so_what


class TestGetCopy:
    def test_direct_key_hit(self):
        result = get_copy("flood_zone", "F1")
        assert result is not None
        assert isinstance(result, CopyEntry)
        assert result.what  # non-empty string

    def test_alias_resolution(self):
        result = get_copy("Flood zone", "F1")
        direct = get_copy("flood_zone", "F1")
        assert result == direct

    def test_miss_returns_none(self):
        assert get_copy("nonexistent_check", "F1") is None

    def test_wrong_failure_type_returns_none(self):
        assert get_copy("flood_zone", "F99") is None

    def test_ejscreen_alias_all_six(self):
        indicators = [
            "EJScreen PM2.5", "EJScreen cancer risk", "EJScreen diesel PM",
            "EJScreen lead paint", "EJScreen Superfund", "EJScreen hazardous waste",
        ]
        for name in indicators:
            result = get_copy(name, "F1")
            assert result is not None, f"Missing alias for {name}"
            assert result == get_copy("ejscreen", "F1")

    def test_hifld_alias(self):
        assert get_copy("hifld_power_lines", "F1") == get_copy("power_lines", "F1")

    def test_listing_amenity_aliases(self):
        assert get_copy("W/D in unit", "input_missing") is not None
        assert get_copy("Central air", "input_missing") is not None
        assert get_copy("Size", "input_missing") is not None
        assert get_copy("Bedrooms", "input_missing") is not None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/jeremybrowning/NestCheck && python -m pytest tests/test_copy_library.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'copy_library'`

- [ ] **Step 3: Implement CopyEntry, empty COPY_LIBRARY scaffold, CHECK_NAME_ALIASES, and get_copy()**

Create `copy_library.py` with:
- `CopyEntry` frozen dataclass with `what`, `why`, `so_what` fields and `combined` property
- Empty `COPY_LIBRARY: dict[str, dict[str, CopyEntry]]` (will be populated in Task 2)
- Full `CHECK_NAME_ALIASES` dict (all 21 aliases from spec)
- `EVALUATION_FAILURE_COPY` standalone entry
- `get_copy()` function with alias resolution and `logger.debug` on miss
- Add a single entry for `flood_zone` F1 so the direct-key and alias tests pass

```python
"""Empty state copy library for NestCheck evaluation reports (NES-319).

Provides what/why/so_what copy for every failure mode in the evaluation
pipeline. Organized by check name → failure type → CopyEntry. Zero
dependencies beyond stdlib.

See: docs/superpowers/specs/2026-03-21-empty-state-copy-library-design.md
"""

import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CopyEntry:
    """A single empty state message with three fields."""
    what: str
    why: str
    so_what: str

    @property
    def combined(self) -> str:
        """Joins fields into a single string for compact display contexts."""
        return f"{self.what} {self.why} {self.so_what}"


# --- Alias mapping: evaluator check names → copy library keys ---

CHECK_NAME_ALIASES: dict[str, str] = {
    # Legacy display names
    "Flood zone": "flood_zone",
    "Power lines": "power_lines",
    "Gas station": "gas_station",
    "Superfund (NPL)": "superfund",
    "High-traffic road": "high_traffic_road",
    "TRI facility": "tri_proximity",
    "Industrial zone": "industrial_zone",
    "Electrical substation": "electrical_substation",
    "Cell tower": "cell_tower",
    "Road Noise": "road_noise",
    # Phase 1B spatial names
    "hifld_power_lines": "power_lines",
    # Listing amenity display names
    "W/D in unit": "washer_dryer",
    "Central air": "central_air",
    "Size": "square_footage",
    "Bedrooms": "bedrooms",
    # EJScreen per-indicator names → block-group-level copy
    "EJScreen PM2.5": "ejscreen",
    "EJScreen cancer risk": "ejscreen",
    "EJScreen diesel PM": "ejscreen",
    "EJScreen lead paint": "ejscreen",
    "EJScreen Superfund": "ejscreen",
    "EJScreen hazardous waste": "ejscreen",
}


# --- Copy library: check_name → failure_type → CopyEntry ---
# Populated in Task 2. Scaffold with flood_zone for initial test pass.

COPY_LIBRARY: dict[str, dict[str, CopyEntry]] = {
    "flood_zone": {
        "F1": CopyEntry(
            what="Flood zone data is temporarily unavailable.",
            why="FEMA's mapping service isn't responding right now.",
            so_what="This check is not included in your health summary.",
        ),
    },
}


# --- F6: Complete evaluation failure (standalone, no check context) ---

EVALUATION_FAILURE_COPY = CopyEntry(
    what="We couldn't evaluate this address.",
    why="This may be due to a temporary issue, an unrecognizable address format, or an area we don't cover yet.",
    so_what="Try again in a few minutes. If the problem persists, report it so we can investigate.",
)


def get_copy(check_name: str, failure_type: str) -> Optional[CopyEntry]:
    """Look up empty state copy for a check and failure type.

    Resolves CHECK_NAME_ALIASES first, then looks up COPY_LIBRARY.
    Returns None on miss so the caller can fall back to generic text.
    """
    key = CHECK_NAME_ALIASES.get(check_name, check_name)
    check_entries = COPY_LIBRARY.get(key)
    if check_entries is None:
        logger.debug("copy_library miss: check_name=%r (key=%r) not found", check_name, key)
        return None
    entry = check_entries.get(failure_type)
    if entry is None:
        logger.debug(
            "copy_library miss: check_name=%r (key=%r) has no %r entry",
            check_name, key, failure_type,
        )
    return entry
```

- [ ] **Step 4: Run tests — most should pass, some will fail (missing entries)**

Run: `cd /Users/jeremybrowning/NestCheck && python -m pytest tests/test_copy_library.py -v`
Expected: CopyEntry tests PASS, direct key + alias for flood_zone PASS, other alias tests FAIL (entries not populated yet)

- [ ] **Step 5: Commit scaffold**

```bash
cd /Users/jeremybrowning/NestCheck
git add copy_library.py tests/test_copy_library.py
git commit -m "feat(NES-319): scaffold copy_library.py with CopyEntry, aliases, get_copy()"
```

---

### Task 2: Populate all 43 copy entries

**Files:**
- Modify: `copy_library.py` — replace the scaffold `COPY_LIBRARY` dict with all entries from spec

- [ ] **Step 1: Replace COPY_LIBRARY with the full 43-entry dict**

Replace the scaffold `COPY_LIBRARY` dict in `copy_library.py` with this exact code:

```python
COPY_LIBRARY: dict[str, dict[str, CopyEntry]] = {
    # ---------------------------------------------------------------
    # Tier 1 Health Checks (12 keys, 21 entries)
    # ---------------------------------------------------------------
    "flood_zone": {
        "F1": CopyEntry(
            what="Flood zone data is temporarily unavailable.",
            why="FEMA's mapping service isn't responding right now.",
            so_what="This check is not included in your health summary.",
        ),
        "F4": CopyEntry(
            what="FEMA flood maps don't cover this area.",
            why="Coverage is metro-based — addresses outside mapped metro areas fall outside the current dataset.",
            so_what="If you're financing a purchase, your lender may require a separate flood determination.",
        ),
    },
    "ust_proximity": {
        "F1": CopyEntry(
            what="Underground storage tank data could not be queried.",
            why="The environmental dataset encountered an error during lookup.",
            so_what="This check is not included in your health summary.",
        ),
        "F4": CopyEntry(
            what="Underground storage tank data is not available for this area.",
            why="EPA UST records have not been ingested for this state yet.",
            so_what="A Phase I environmental site assessment would cover underground storage tanks if this is a concern.",
        ),
    },
    "high_traffic_road": {
        "F1": CopyEntry(
            what="Traffic volume data could not be queried.",
            why="The federal highway dataset encountered an error during lookup.",
            so_what="This check is not included in your health summary.",
        ),
        "F4": CopyEntry(
            what="Traffic volume data is not available for this area.",
            why="Federal highway monitoring data has not been ingested for this state.",
            so_what="High-traffic roads can be assessed in person during peak commute hours.",
        ),
    },
    "power_lines": {
        "F1": CopyEntry(
            what="Transmission line data is temporarily unavailable.",
            why="The infrastructure dataset used for this check isn't responding right now.",
            so_what="This check is not included in your health summary.",
        ),
        "F4": CopyEntry(
            what="Transmission line data is not available for this area.",
            why="Federal transmission line records have not been loaded for this region.",
            so_what="High-voltage lines are visible on satellite imagery — check the map view.",
        ),
    },
    "electrical_substation": {
        "F1": CopyEntry(
            what="Electrical substation data is temporarily unavailable.",
            why="OpenStreetMap's data service isn't responding right now.",
            so_what="Substations are typically visible on satellite imagery.",
        ),
    },
    "cell_tower": {
        "F1": CopyEntry(
            what="Cell tower data is temporarily unavailable.",
            why="OpenStreetMap's data service isn't responding right now.",
            so_what="Cell towers are typically visible on satellite imagery.",
        ),
    },
    "industrial_zone": {
        "F1": CopyEntry(
            what="Industrial zone data could not be queried.",
            why="The environmental or land-use dataset encountered an error.",
            so_what="This check is not included in your health summary.",
        ),
        "F4": CopyEntry(
            what="Industrial facility data is not available for this area.",
            why="EPA Toxics Release Inventory data has not been ingested for this state.",
            so_what="Nearby industrial activity can be assessed from satellite imagery and local zoning maps.",
        ),
    },
    "tri_proximity": {
        "F1": CopyEntry(
            what="Toxic release facility data could not be queried.",
            why="The EPA TRI spatial dataset encountered an error.",
            so_what="This check is not included in your health summary.",
        ),
        "F4": CopyEntry(
            what="Toxic release facility data is not available for this area.",
            why="EPA TRI records have not been ingested for this state.",
            so_what="For properties near visible industrial sites, a Phase I environmental assessment would cover this.",
        ),
    },
    "superfund": {
        "F1": CopyEntry(
            what="Superfund site data could not be queried.",
            why="The EPA National Priorities List spatial dataset encountered an error.",
            so_what="This check is not included in your health summary.",
        ),
        "F4": CopyEntry(
            what="Superfund site data is not available for this area.",
            why="EPA NPL boundaries have not been ingested for this state.",
            so_what="Active Superfund sites are publicly listed on the EPA website by state.",
        ),
    },
    "rail_proximity": {
        "F1": CopyEntry(
            what="Rail corridor data could not be queried.",
            why="The federal rail dataset encountered an error.",
            so_what="This check is not included in your health summary.",
        ),
        "F4": CopyEntry(
            what="Rail corridor data is not available for this area.",
            why="FRA rail network data has not been ingested for this state.",
            so_what="Rail corridors are visible on satellite imagery and produce audible noise within a few hundred feet.",
        ),
    },
    "gas_station": {
        "F1": CopyEntry(
            what="Gas station proximity could not be verified.",
            why="The mapping service used for this check isn't responding.",
            so_what="Check the satellite view to inspect the immediate surroundings.",
        ),
    },
    "ejscreen": {
        "F1": CopyEntry(
            what="EPA environmental screening data is not available for this area.",
            why="EJScreen block group data has not been ingested for this census tract.",
            so_what="Area-level environmental indicators are not included in this evaluation.",
        ),
        "F2": CopyEntry(
            what="EPA environmental data for this area may be outdated.",
            why="EJScreen is refreshed annually. The current dataset reflects conditions as of {vintage_year}.",
            so_what="Indicator trends are generally stable year-to-year, but specific percentiles may shift.",
        ),
    },
    # ---------------------------------------------------------------
    # Tier 2 Dimensions (6 keys, 16 entries)
    # ---------------------------------------------------------------
    "coffee_social": {
        "F1": CopyEntry(
            what="Coffee and social spot data is temporarily unavailable.",
            why="The places service isn't responding right now.",
            so_what="This dimension is not included in your score.",
        ),
        "F3": CopyEntry(
            what="No coffee shops, cafes, or social spots found in the search area.",
            why="Residential areas outside town centers often lack dedicated third places within walking distance.",
            so_what="Newer or independent venues are sometimes missing from the index — check locally if this seems off.",
        ),
        "F5": CopyEntry(
            what="Not enough venue data to score this dimension.",
            why="Too few venues with sufficient review history were found to produce a reliable score.",
            so_what="This dimension is not included in your score.",
        ),
    },
    "provisioning": {
        "F1": CopyEntry(
            what="Grocery and daily essentials data is temporarily unavailable.",
            why="The places service isn't responding right now.",
            so_what="This dimension is not included in your score.",
        ),
        "F3": CopyEntry(
            what="No grocery stores found within the search radius.",
            why="Grocery stores tend to cluster near commercial corridors and may not be present within walking distance of every address.",
            so_what="Most residents at this distance drive for daily provisioning.",
        ),
        "F5": CopyEntry(
            what="Not enough grocery data to score this dimension.",
            why="Too few stores with sufficient review history were found to produce a reliable score.",
            so_what="This dimension is not included in your score.",
        ),
    },
    "fitness": {
        "F1": CopyEntry(
            what="Fitness facility data is temporarily unavailable.",
            why="The places service isn't responding right now.",
            so_what="This dimension is not included in your score.",
        ),
        "F3": CopyEntry(
            what="No gyms or fitness facilities found in the search area.",
            why="Gyms and fitness centers tend to cluster in commercial areas and may not be present within the search radius.",
            so_what="Home workouts or driving to a facility outside the search area are likely the primary options.",
        ),
        "F5": CopyEntry(
            what="Not enough fitness facility data to score this dimension.",
            why="Too few facilities with sufficient review history were found to produce a reliable score.",
            so_what="This dimension is not included in your score.",
        ),
    },
    "green_space": {
        "F1": CopyEntry(
            what="Park and green space data is temporarily unavailable.",
            why="The data services used for park discovery aren't responding right now.",
            so_what="This dimension is not included in your score.",
        ),
        "F3": CopyEntry(
            what="No parks or green spaces found within the search radius.",
            why="Formal parks may not exist nearby, and informal green spaces or trails are often not indexed.",
            so_what="Satellite imagery can help identify informal green spaces, trails, or preserved land nearby.",
        ),
        "F5": CopyEntry(
            what="Not enough park data to score this dimension.",
            why="Park data was found but lacked sufficient detail (boundaries, reviews) for a reliable score.",
            so_what="This dimension is not included in your score.",
        ),
    },
    "transit": {
        "F1": CopyEntry(
            what="Transit data is temporarily unavailable.",
            why="The transit data service isn't responding right now.",
            so_what="This dimension is not included in your score.",
        ),
        "F5": CopyEntry(
            what="No transit options found within walking distance.",
            why="This area does not appear to have fixed-route public transit coverage.",
            so_what="Driving will likely be the primary way to get around.",
        ),
    },
    "road_noise": {
        "F1": CopyEntry(
            what="Road noise data is temporarily unavailable.",
            why="The traffic data service isn't responding right now.",
            so_what="This dimension is not included in your score.",
        ),
        "F5": CopyEntry(
            what="Road noise could not be estimated for this area.",
            why="Traffic noise modeling requires road segment data that is not available for this state.",
            so_what="Road noise can be assessed in person — visit during weekday rush hours for a representative sample.",
        ),
    },
    # ---------------------------------------------------------------
    # User Input Gaps (5 keys, 5 entries)
    # ---------------------------------------------------------------
    "cost": {
        "input_missing": CopyEntry(
            what="Monthly cost was not provided.",
            why="No monthly housing cost was provided for this evaluation.",
            so_what="Cost is not factored into your overall score.",
        ),
    },
    "washer_dryer": {
        "input_missing": CopyEntry(
            what="Washer/dryer availability was not specified.",
            why="This information was not provided for this evaluation.",
            so_what="Check the listing details or ask the landlord directly.",
        ),
    },
    "central_air": {
        "input_missing": CopyEntry(
            what="Central air availability was not specified.",
            why="This information was not provided for this evaluation.",
            so_what="Check the listing details or ask the landlord directly.",
        ),
    },
    "square_footage": {
        "input_missing": CopyEntry(
            what="Square footage was not specified.",
            why="This information was not provided for this evaluation.",
            so_what="Verify square footage from the listing or during a tour.",
        ),
    },
    "bedrooms": {
        "input_missing": CopyEntry(
            what="Bedroom count was not specified.",
            why="This information was not provided for this evaluation.",
            so_what="Verify bedroom count from the listing or during a tour.",
        ),
    },
}
```

The ejscreen F2 entry contains `{vintage_year}` as a literal string in the `why` field. NES-264 wiring will handle interpolation at render time.

- [ ] **Step 2: Run tests**

Run: `cd /Users/jeremybrowning/NestCheck && python -m pytest tests/test_copy_library.py -v`
Expected: All tests PASS

- [ ] **Step 3: Commit**

```bash
cd /Users/jeremybrowning/NestCheck
git add copy_library.py
git commit -m "feat(NES-319): populate all 43 copy entries from approved spec"
```

---

### Task 3: Add inventory completeness tests

**Files:**
- Modify: `tests/test_copy_library.py`

These tests verify structural properties of the copy library — they'll catch drift if entries are accidentally deleted or keys renamed.

- [ ] **Step 1: Add completeness tests**

```python
class TestInventory:
    def test_total_entry_count(self):
        """43 entries total per spec."""
        count = sum(len(variants) for variants in COPY_LIBRARY.values())
        assert count == 43

    def test_tier1_check_keys(self):
        tier1_keys = {
            "flood_zone", "ust_proximity", "high_traffic_road", "power_lines",
            "electrical_substation", "cell_tower", "industrial_zone",
            "tri_proximity", "superfund", "rail_proximity", "gas_station", "ejscreen",
        }
        for key in tier1_keys:
            assert key in COPY_LIBRARY, f"Missing Tier 1 key: {key}"
            assert "F1" in COPY_LIBRARY[key], f"{key} missing F1 entry"

    def test_tier2_dimension_keys(self):
        tier2_keys = {
            "coffee_social", "provisioning", "fitness",
            "green_space", "transit", "road_noise",
        }
        for key in tier2_keys:
            assert key in COPY_LIBRARY, f"Missing Tier 2 key: {key}"
            assert "F1" in COPY_LIBRARY[key], f"{key} missing F1 entry"

    def test_input_missing_keys(self):
        input_keys = {"cost", "washer_dryer", "central_air", "square_footage", "bedrooms"}
        for key in input_keys:
            assert key in COPY_LIBRARY, f"Missing input_missing key: {key}"
            assert "input_missing" in COPY_LIBRARY[key], f"{key} missing input_missing entry"

    def test_f6_standalone(self):
        assert EVALUATION_FAILURE_COPY.what
        assert EVALUATION_FAILURE_COPY.why
        assert EVALUATION_FAILURE_COPY.so_what

    def test_all_entries_have_nonempty_fields(self):
        for check_name, variants in COPY_LIBRARY.items():
            for f_type, entry in variants.items():
                assert entry.what, f"{check_name}/{f_type} has empty 'what'"
                assert entry.why, f"{check_name}/{f_type} has empty 'why'"
                assert entry.so_what, f"{check_name}/{f_type} has empty 'so_what'"

    def test_no_alias_targets_missing_key(self):
        """Every alias target must exist in COPY_LIBRARY."""
        for evaluator_name, copy_key in CHECK_NAME_ALIASES.items():
            assert copy_key in COPY_LIBRARY, (
                f"Alias {evaluator_name!r} → {copy_key!r} but {copy_key!r} not in COPY_LIBRARY"
            )

    def test_ejscreen_vintage_placeholder(self):
        """The ejscreen F2 entry must contain the {vintage_year} placeholder."""
        entry = COPY_LIBRARY["ejscreen"]["F2"]
        assert "{vintage_year}" in entry.why
```

- [ ] **Step 2: Run all tests**

Run: `cd /Users/jeremybrowning/NestCheck && python -m pytest tests/test_copy_library.py -v`
Expected: All tests PASS

- [ ] **Step 3: Commit**

```bash
cd /Users/jeremybrowning/NestCheck
git add tests/test_copy_library.py
git commit -m "test(NES-319): add inventory completeness and structural tests"
```

---

### Task 4: Add to import sanity tests + final verification

**Files:**
- Modify: `tests/test_import_sanity.py`

- [ ] **Step 1: Add import sanity test for copy_library**

Add to `tests/test_import_sanity.py`:

```python
def test_copy_library_imports():
    """Copy library module must import without errors."""
    from copy_library import CopyEntry, COPY_LIBRARY, CHECK_NAME_ALIASES, EVALUATION_FAILURE_COPY, get_copy
    assert CopyEntry is not None
    assert len(COPY_LIBRARY) > 0
    assert len(CHECK_NAME_ALIASES) > 0
    assert EVALUATION_FAILURE_COPY is not None
    assert get_copy is not None
```

- [ ] **Step 2: Run full test suite**

Run: `cd /Users/jeremybrowning/NestCheck && python -m pytest tests/test_copy_library.py tests/test_import_sanity.py -v`
Expected: All tests PASS

- [ ] **Step 3: Commit**

```bash
cd /Users/jeremybrowning/NestCheck
git add tests/test_import_sanity.py
git commit -m "test(NES-319): add copy_library to import sanity checks"
```

- [ ] **Step 4: Run ruff to check formatting**

Run: `cd /Users/jeremybrowning/NestCheck && python -m ruff check copy_library.py tests/test_copy_library.py`
Expected: No errors (or fix any that surface)

- [ ] **Step 5: Final commit if ruff required changes**

```bash
cd /Users/jeremybrowning/NestCheck
git add copy_library.py tests/test_copy_library.py tests/test_import_sanity.py
git commit -m "style(NES-319): ruff formatting fixes"
```
