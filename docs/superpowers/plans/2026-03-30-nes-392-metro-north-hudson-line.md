# NES-392: Metro-North Hudson Line Stations Missing — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix `find_primary_transit()` to discover Metro-North stations that Google Places types as `transit_station` instead of `train_station`, so Hudson Line towns (Dobbs Ferry, Hastings, Irvington, Croton) surface their rail stations instead of falling back to bus stops.

**Architecture:** Add `transit_station` to `find_primary_transit()`'s search types with commuter-rail radius (16km), then post-filter results using `_classify_mode()` to keep only rail-classified stations. Dedup by `place_id` to avoid double-counting stations that appear in both `train_station` and `transit_station` results.

**Tech Stack:** Python, Google Places API, pytest with mocked clients

---

## Root Cause

`find_primary_transit()` (`property_evaluator.py:3876`) searches Google Places for three types: `train_station`, `subway_station`, `light_rail_station`. Metro-North stations are frequently typed by Google as `transit_station` (the generic type) rather than `train_station` (the specific type). When no rail station is found, the template (`_result_sections.html:583`) falls back to showing `evaluate_transit_access()`'s primary_stop — which picks the closest transit stop by walk time, typically a bus stop.

The downstream damage compounds: the GCT commute time is calculated from the property address (no transit station coordinates to route through), producing ~72 min instead of ~48 min.

## File Structure

| File | Action | Responsibility |
|------|--------|---------------|
| `property_evaluator.py:3869-3970` | Modify | Add `transit_station` to search types, post-filter to rail, dedup |
| `property_evaluator.py:4206-4231` | Modify | Fix `_classify_mode()` commuter rail check for `transit_station` types |
| `tests/test_transit_access.py` | Modify | Add tests for `find_primary_transit()` and `_classify_mode()` fixes |

Three changes across two files. No new files needed.

**API cost**: +1 Places Nearby call per evaluation (~$0.032) for the `transit_station` search.

## Key Design Decisions

1. **`transit_station` with rail-only post-filter** — `transit_station` is a catch-all Google type that includes bus stops. We add it to the search but filter each result through `_classify_mode()`, keeping only rail modes (`Train`, `Subway`, `Light Rail`, `Commuter Rail`). This catches Metro-North stations typed as `transit_station` while excluding bus stops.

2. **Priority 2 for `transit_station` rail results** — If the same station appears in both `train_station` (priority 1) and `transit_station` (priority 2) results, the `train_station` version wins due to the `(priority, walk_time)` sort. This prevents behavior changes for stations that ARE correctly typed.

3. **Dedup by `place_id`** — A station found via `train_station` search shouldn't also appear via `transit_station` search. Dedup before the walking time batch API call to avoid wasting Distance Matrix API budget.

4. **16km radius for `transit_station`** — Same as `train_station`. Commuter rail has drive-to catchments; a 5km radius would miss many Hudson Line stations from properties in adjacent towns.

5. **No changes to `evaluate_transit_access()`** — The density scorer already searches `transit_station` within 1.2km and works correctly for its purpose. The bug is only in `find_primary_transit()`'s display path.

6. **Fix `_classify_mode()` commuter rail check for `transit_station` types** — Currently, the commuter rail keyword check (`"metro-north"`, `"nj transit"`, etc.) only fires when `"train_station" in types`. A Metro-North station typed as `transit_station` with "Metro-North" in its name would skip the commuter rail branch, then hit `"metro" in name` at line 4218 and be misclassified as "Subway". Fix: extend the commuter rail check to also trigger on `transit_station` types.

7. **Known limitation: bare `transit_station` bus stops** — A bus stop typed as bare `transit_station` (no `bus_station` type, no "bus" in name) would default to "Train" in `_classify_mode()` and leak through the rail filter. In practice, Google almost always includes `bus_station` type or "bus" in the name for bus stops. Acceptable risk at current scale.

---

### Task 1: Fix `_classify_mode()` commuter rail check for `transit_station` types

**Files:**
- Modify: `property_evaluator.py:4206-4231`
- Modify: `tests/test_transit_access.py`

- [ ] **Step 1: Write failing test — Metro-North station typed as `transit_station` classified correctly**

Add to `TestClassifyMode` in `tests/test_transit_access.py`:

```python
def test_commuter_rail_keyword_on_transit_station_type(self):
    """Metro-North station typed as transit_station (not train_station) → Commuter Rail."""
    place = _make_place(
        "Dobbs Ferry Metro-North Station", "df1",
        ["transit_station", "point_of_interest"],
        41.0042, -73.8799,
    )
    self.assertEqual(_classify_mode(place), "Commuter Rail")

def test_metro_north_name_not_misclassified_as_subway(self):
    """'Metro-North' in name should NOT trigger the 'metro' → Subway branch."""
    place = _make_place(
        "Hastings-on-Hudson Metro-North", "hoh1",
        ["transit_station"],
        41.0015, -73.8835,
    )
    # Should be Commuter Rail, NOT Subway
    self.assertNotEqual(_classify_mode(place), "Subway")
    self.assertEqual(_classify_mode(place), "Commuter Rail")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/jeremybrowning/NestCheck && python -m pytest tests/test_transit_access.py::TestClassifyMode -v`
Expected: FAIL — `_classify_mode()` returns "Subway" (matches "metro" in "metro-north")

- [ ] **Step 3: Fix `_classify_mode()` to check commuter rail keywords on `transit_station` types**

In `property_evaluator.py`, modify `_classify_mode()` (line 4213):

Change:
```python
    if "train_station" in types and any(kw in name for kw in commuter_kw):
        return "Commuter Rail"
```

To:
```python
    if ("train_station" in types or "transit_station" in types) and any(kw in name for kw in commuter_kw):
        return "Commuter Rail"
```

This ensures commuter rail keywords are checked BEFORE the `"metro" in name` branch (line 4218) for `transit_station`-typed places.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/jeremybrowning/NestCheck && python -m pytest tests/test_transit_access.py::TestClassifyMode -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add property_evaluator.py tests/test_transit_access.py
git commit -m "fix: _classify_mode() commuter rail check for transit_station types (NES-392)

Commuter rail keywords (metro-north, nj transit, etc.) were only checked
when train_station was in the place types. A Metro-North station typed as
transit_station would skip the commuter rail branch, then hit the 'metro'
substring check and be misclassified as Subway.

Extend the commuter rail precondition to: train_station OR transit_station."
```

---

### Task 2: Add tests for `find_primary_transit()` with transit_station results

**Files:**
- Modify: `tests/test_transit_access.py`

- [ ] **Step 1: Write failing test — Metro-North station typed as `transit_station` is found**

Add `find_primary_transit` and `TRANSIT_SEARCH_RADII` to the existing import block. Then add a new test class `TestFindPrimaryTransit`:

```python
from property_evaluator import find_primary_transit, TRANSIT_SEARCH_RADII


class TestFindPrimaryTransit(unittest.TestCase):
    """Tests for find_primary_transit() rail station discovery."""

    def _mock_client(self, places_by_type, walk_times=None):
        """Return a GoogleMapsClient mock that returns different results per place type."""
        client = MagicMock(spec=GoogleMapsClient)

        def _places_nearby(lat, lng, place_type, radius_meters=2000):
            return places_by_type.get(place_type, [])

        client.places_nearby.side_effect = _places_nearby
        default_walk = walk_times or [10]
        client.walking_times_batch.side_effect = (
            lambda origin, destinations, place_ids=None: default_walk[:len(destinations)]
        )
        client.driving_time.return_value = 9999
        client.walking_time.return_value = default_walk[0] if default_walk else 10
        return client

    def test_transit_station_typed_metro_north_found(self):
        """Metro-North station typed as transit_station (not train_station) should be found."""
        dobbs_ferry_station = _make_place(
            "Dobbs Ferry Metro-North Station", "df1",
            ["transit_station", "point_of_interest"],
            41.0042, -73.8799,
            user_ratings_total=200,
        )
        client = self._mock_client(
            places_by_type={
                "train_station": [],
                "subway_station": [],
                "light_rail_station": [],
                "transit_station": [dobbs_ferry_station],
            },
            walk_times=[12],
        )
        result = find_primary_transit(client, 41.0043, -73.8726)
        self.assertIsNotNone(result)
        self.assertIn("Dobbs Ferry", result.name)
        self.assertEqual(result.mode, "Commuter Rail")

    def test_transit_station_bus_stops_filtered_out(self):
        """Bus stops typed as transit_station should be excluded from primary transit."""
        bus_stop = _make_place(
            "Ashford Ave @ Storm St", "bus1",
            ["transit_station", "bus_station"],
            41.0050, -73.8710,
            user_ratings_total=10,
        )
        client = self._mock_client(
            places_by_type={
                "train_station": [],
                "subway_station": [],
                "light_rail_station": [],
                "transit_station": [bus_stop],
            },
            walk_times=[5],
        )
        result = find_primary_transit(client, 41.0043, -73.8726)
        # Bus stop should be filtered out, returning None
        self.assertIsNone(result)

    def test_train_station_preferred_over_transit_station_duplicate(self):
        """Same station in both train_station and transit_station: deduped, train_station mode used."""
        station_as_train = _make_place(
            "Scarsdale Metro-North", "sc1",
            ["train_station", "transit_station"],
            40.9901, -73.7735,
            user_ratings_total=500,
        )
        station_as_transit = _make_place(
            "Scarsdale Metro-North", "sc1",
            ["transit_station", "point_of_interest"],
            40.9901, -73.7735,
            user_ratings_total=500,
        )
        client = self._mock_client(
            places_by_type={
                "train_station": [station_as_train],
                "subway_station": [],
                "light_rail_station": [],
                "transit_station": [station_as_transit],
            },
            walk_times=[8],
        )
        result = find_primary_transit(client, 40.9901, -73.7735)
        self.assertIsNotNone(result)
        self.assertIn("Scarsdale", result.name)
        # train_station search has priority 1 (wins), mode = Commuter Rail
        self.assertEqual(result.mode, "Commuter Rail")

    def test_transit_station_search_uses_train_radius(self):
        """transit_station search should use the same 16km radius as train_station."""
        self.assertEqual(
            TRANSIT_SEARCH_RADII["transit_station"],
            TRANSIT_SEARCH_RADII["train_station"],
        )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/jeremybrowning/NestCheck && python -m pytest tests/test_transit_access.py::TestFindPrimaryTransit -v`
Expected: FAIL — `transit_station` not in `TRANSIT_SEARCH_RADII`, `find_primary_transit` doesn't search it

- [ ] **Step 3: Commit failing tests**

```bash
git add tests/test_transit_access.py
git commit -m "test: add failing tests for transit_station search in find_primary_transit (NES-392)"
```

---

### Task 3: Add `transit_station` to `find_primary_transit()` with rail-only post-filter

**Files:**
- Modify: `property_evaluator.py:3869-3925`

- [ ] **Step 1: Add `transit_station` to `TRANSIT_SEARCH_RADII`**

In `property_evaluator.py`, modify `TRANSIT_SEARCH_RADII` (line 3869):

```python
TRANSIT_SEARCH_RADII = {
    "train_station": 16000,        # ~10 mi — commuter rail (drive-to)
    "subway_station": 5000,        # ~3 mi — urban subway (walk-to)
    "light_rail_station": 5000,    # ~3 mi — light rail (walk-to)
    "transit_station": 16000,      # ~10 mi — catch rail stations Google doesn't type as train_station
}
```

- [ ] **Step 2: Add `transit_station` to search_types with rail-only post-filter and dedup**

Modify `find_primary_transit()` (starting at line 3876). The changes are:

1. Add a set of rail modes for filtering
2. Add `transit_station` to `search_types` with `mode=None` (signals: classify individually)
3. Dedup by `place_id` across all search types
4. For `transit_station` results, classify mode via `_classify_mode()` and skip non-rail

Replace the function body from `search_types` through the candidate-building loop:

```python
def find_primary_transit(
    maps: GoogleMapsClient,
    lat: float,
    lng: float
) -> Optional[PrimaryTransitOption]:
    """Find the best nearby transit option with preference for rail."""
    # mode=None signals "classify each result individually via _classify_mode"
    search_types = [
        ("train_station", "Train", 1),
        ("subway_station", "Subway", 1),
        ("light_rail_station", "Light Rail", 1),
        ("transit_station", None, 2),      # catch rail stations mis-typed by Google
    ]

    _RAIL_MODES = {"Train", "Subway", "Light Rail", "Commuter Rail"}

    raw_candidates: List[Tuple[int, Dict, str]] = []
    _seen_place_ids: set = set()
    _last_exc: Optional[Exception] = None
    _searches_attempted = 0
    _searches_failed = 0
    for place_type, mode, priority in search_types:
        _searches_attempted += 1
        try:
            radius = TRANSIT_SEARCH_RADII[place_type]
            places = maps.places_nearby(lat, lng, place_type, radius_meters=radius)
        except Exception as exc:
            _searches_failed += 1
            _last_exc = exc
            continue
        for place in places:
            pid = place.get("place_id")
            if pid and pid in _seen_place_ids:
                continue  # dedup across search types
            if pid:
                _seen_place_ids.add(pid)

            if mode is None:
                # Classify individually; keep only rail modes
                classified = _classify_mode(place)
                if classified not in _RAIL_MODES:
                    continue
                raw_candidates.append((priority, place, classified))
            else:
                raw_candidates.append((priority, place, mode))
```

The rest of the function (from `if not raw_candidates:` onward) remains unchanged.

- [ ] **Step 3: Run tests to verify they pass**

Run: `cd /Users/jeremybrowning/NestCheck && python -m pytest tests/test_transit_access.py -v`
Expected: ALL PASS (including new TestFindPrimaryTransit tests)

- [ ] **Step 4: Run full scoring test suite to check for regressions**

Run: `cd /Users/jeremybrowning/NestCheck && python -m pytest tests/test_scoring_regression.py tests/test_scoring_config.py tests/test_drive_time_fallback.py tests/test_transit_access.py tests/test_urban_access.py tests/test_data_confidence.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add property_evaluator.py
git commit -m "fix: add transit_station to find_primary_transit with rail-only filter (NES-392)

Metro-North Hudson Line stations are frequently typed as transit_station
instead of train_station by Google Places. This caused find_primary_transit()
to miss them entirely, making the template fall back to showing the nearest
bus stop from evaluate_transit_access().

Changes:
- Add transit_station to TRANSIT_SEARCH_RADII (16km, same as train_station)
- Add transit_station to search_types with priority 2 and per-result mode
  classification via _classify_mode()
- Filter transit_station results to rail modes only (Train, Subway,
  Light Rail, Commuter Rail) — bus stops excluded
- Dedup by place_id across search types to avoid double-counting

Fixes: NES-392"
```

---

### Task 4: Verify with transit ground truth and existing tests

**Files:**
- Read-only: `data/ground_truth/transit.json`, `scripts/validate_ground_truth_transit.py`

- [ ] **Step 1: Run transit ground truth validator**

Run: `cd /Users/jeremybrowning/NestCheck && python scripts/validate_ground_truth_transit.py`
Expected: All existing test cases still pass. The ground truth tests exercise `compute_transit_score()` (the pure scoring function), not `find_primary_transit()`, so they should be unaffected. Confirm no regressions.

- [ ] **Step 2: Run browser tests**

Run: `cd /Users/jeremybrowning/NestCheck && python -m pytest tests/playwright/ -v -k transit`
Expected: PASS (null transit handling test should still work)

- [ ] **Step 3: Run full CI suite**

Run: `cd /Users/jeremybrowning/NestCheck && make ci`
Expected: ALL PASS
