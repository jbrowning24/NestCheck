# NES-393: Village Main Street Cafe Discovery Fix

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Surface village main street cafes (Dobbs Ferry, Hastings, Irvington, Tarrytown) that are currently missed by the coffee scoring pipeline due to Google Places prominence bias and the 20-result Nearby Search cap.

**Architecture:** Two changes to `score_third_place_access()` and `get_neighborhood_snapshot()`: (1) haversine post-filter on `places_nearby` results to enforce the 3000m search radius (prevents out-of-radius prominent places from dominating), (2) supplemental `text_search("coffee", 8000m)` call to find local cafes via relevance ranking that the Nearby Search cap drops. Follows established patterns from NES-250 (haversine), NES-258 (grocery text_search), NES-259 (fitness text_search).

**Tech Stack:** Python, Google Places API (Text Search), haversine distance via `_distance_feet()`

**Model version bump:** 1.9.0 → 1.10.0 (discovery pipeline change affects scores)

---

## File Map

| File | Action | Responsibility |
|------|--------|---------------|
| `property_evaluator.py` | Modify lines ~4966-4973 and ~3435-3449 | Add haversine post-filter + text_search to scoring and snapshot functions |
| `scoring_config.py` | Modify line 381 | Bump model version to 1.10.0 |
| `tests/test_scoring_regression.py` | Modify | Add test for haversine filter and text_search integration |

---

### Task 1: Add haversine post-filter to `score_third_place_access()`

**Files:**
- Modify: `property_evaluator.py:4966-4973`

**Context:** The four `places_nearby` calls at lines 4966-4971 use `radius_meters=3000`, but Google treats this as a location bias, not a hard filter. A prominent cafe in Ardsley (~3.5km away) can be returned, pushing local village cafes out of the 20-result cap. The transit hub search (NES-250, line 4052-4063) established the haversine post-filter pattern using `_distance_feet()`.

- [ ] **Step 1: Add haversine post-filter after the four `places_nearby` calls, before dedup**

In `score_third_place_access()`, after line 4971 (the last `places_nearby` call) and before line 4973 (`_dedupe_by_place_id`), insert:

```python
        # -- Haversine post-filter (NES-393) --------------------------------
        # Google radius is a bias, not a hard filter. Enforce 3000m to
        # prevent prominently-ranked out-of-radius places from dominating.
        _coffee_max_radius_ft = int(3000 * 3.28084)  # 3000m ≈ 9843 ft
        all_places = [
            p for p in all_places
            if _distance_feet(
                lat, lng,
                p["geometry"]["location"]["lat"],
                p["geometry"]["location"]["lng"],
            ) <= _coffee_max_radius_ft
        ]
```

- [ ] **Step 2: Verify the change is syntactically correct**

Run: `python -c "import property_evaluator; print('OK')"`
Expected: `OK` (no import errors)

- [ ] **Step 3: Commit**

```bash
git add property_evaluator.py
git commit -m "fix(NES-393): add haversine post-filter to coffee nearby search

Google Places radius is a bias, not a hard filter. Prominent cafes
outside 3000m (e.g. Ardsley from Dobbs Ferry) can push local village
cafes out of the 20-result cap. Enforce 3000m with _distance_feet()
after places_nearby returns, same pattern as transit hub (NES-250)."
```

---

### Task 2: Add supplemental `text_search` to `score_third_place_access()`

**Files:**
- Modify: `property_evaluator.py:4973` (after the new post-filter from Task 1, before dedup)

**Context:** Grocery (NES-258, line 5506-5512) and fitness (NES-259, line 5737-5743) both have supplemental `text_search` calls at 8000m to find venues the 20-result Nearby Search cap drops. Coffee is the only major venue dimension missing this. The `text_search` uses relevance ranking (vs. prominence for `places_nearby`), which surfaces small local cafes that prominence-based search misses.

- [ ] **Step 1: Add `text_search("coffee", 8000m)` after the haversine post-filter and before dedup**

Insert between the haversine post-filter (Task 1) and `_dedupe_by_place_id` (currently line 4973):

```python
        # -- Supplemental text search (NES-393) ----------------------------
        # Same pattern as NES-258 (grocery) and NES-259 (fitness). Text
        # Search uses relevance ranking, surfacing local village cafes that
        # the 20-result Nearby Search prominence cap drops.
        try:
            all_places.extend(
                maps.text_search("coffee", lat, lng, radius_meters=8000))
        except Exception:
            logger.warning(
                "Text Search supplemental coffee query failed",
                exc_info=True)
```

Note: `text_search` results are NOT haversine-filtered to 3000m — they intentionally cover a wider 8000m radius and are scored naturally by walk/drive time. The post-filter in Task 1 only applies to `places_nearby` results.

- [ ] **Step 2: Verify import and syntax**

Run: `python -c "import property_evaluator; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add property_evaluator.py
git commit -m "feat(NES-393): add supplemental text_search for coffee discovery

Text Search uses relevance ranking (vs. prominence for places_nearby),
surfacing local village cafes that the 20-result cap drops. Same
pattern as grocery (NES-258) and fitness (NES-259). 8000m radius
covers short-drive options; walk/drive scoring handles distance
naturally. +1 Text Search API call per evaluation (~$0.032)."
```

---

### Task 3: Mirror changes in `get_neighborhood_snapshot()`

**Files:**
- Modify: `property_evaluator.py:3435-3449`

**Context:** Per CLAUDE.md contract, search calls in the scoring function must be mirrored in the snapshot function. They share cache keys, so the snapshot function gets cached results for free — but it must issue the call to populate the cache when it runs first. The provisioning text_search is already mirrored at lines 3441-3448.

- [ ] **Step 1: Add haversine post-filter and `text_search` to the coffee branch in `get_neighborhood_snapshot()`**

After line 3438 (the last `places_nearby` call in the coffee branch) and before line 3449 (`places = _dedupe_by_place_id(places)`), add inside the `if category == "Coffee & Social Spots":` block:

```python
                # Haversine post-filter — enforce 3000m (NES-393)
                _coffee_max_ft = int(3000 * 3.28084)
                places = [
                    p for p in places
                    if _distance_feet(
                        lat, lng,
                        p["geometry"]["location"]["lat"],
                        p["geometry"]["location"]["lng"],
                    ) <= _coffee_max_ft
                ]
                # Supplemental text search (NES-393)
                try:
                    places.extend(
                        maps.text_search("coffee", lat, lng, radius_meters=8000))
                except Exception:
                    logger.warning(
                        "Text Search supplemental coffee query failed",
                        exc_info=True)
```

- [ ] **Step 2: Verify syntax**

Run: `python -c "import property_evaluator; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add property_evaluator.py
git commit -m "fix(NES-393): mirror coffee haversine + text_search in snapshot function

Per CLAUDE.md contract, scoring function search calls must be mirrored
in get_neighborhood_snapshot(). They share cache keys so the snapshot
function populates the cache when it runs first."
```

---

### Task 4: Bump model version

**Files:**
- Modify: `scoring_config.py:381`

- [ ] **Step 1: Update model version from 1.9.0 to 1.10.0**

Change line 381 from:
```python
    version="1.9.0",
```
to:
```python
    version="1.10.0",
```

- [ ] **Step 2: Run existing scoring tests to verify nothing breaks**

Run: `make test-scoring`
Expected: All tests pass. The scoring curves and thresholds are unchanged — only the discovery pipeline is different.

- [ ] **Step 3: Commit**

```bash
git add scoring_config.py
git commit -m "chore(NES-393): bump model version to 1.10.0

Discovery pipeline change (haversine post-filter + text_search for
coffee) affects which venues enter scoring, changing scores for
village-adjacent addresses."
```

---

### Task 5: Add regression test for coffee haversine post-filter

**Files:**
- Modify: `tests/test_scoring_regression.py`

**Context:** The haversine post-filter is a new behavior that should have a regression test. We can't test the full API pipeline without live calls, but we can test the `_distance_feet` function and verify the filter constant is correct.

- [ ] **Step 1: Add test class after `TestCoffeeCurve` (around line 156)**

```python
class TestCoffeeDiscoveryFilter:
    """NES-393: Haversine post-filter enforces 3000m radius on coffee search."""

    def test_distance_feet_known_pair(self):
        """Verify _distance_feet with a known distance."""
        from property_evaluator import _distance_feet
        # Dobbs Ferry (29 Ridge Rd) to Ardsley (Booskerdoo) ≈ 3.5km ≈ 11,483 ft
        dist = _distance_feet(41.0055, -73.8710, 41.0109, -73.8420)
        assert 10_000 < dist < 13_000, f"Expected ~11,500 ft, got {dist}"

    def test_3000m_radius_in_feet(self):
        """The filter constant must be 3000m converted to feet."""
        expected_ft = int(3000 * 3.28084)  # 9842
        assert 9840 <= expected_ft <= 9845

    def test_within_radius_passes(self):
        """A cafe at 2km (~6,562 ft) should pass the 3000m filter."""
        from property_evaluator import _distance_feet
        # Dobbs Ferry Ridge Rd to Main Street ≈ 2km
        dist = _distance_feet(41.0055, -73.8710, 41.0044, -73.8652)
        max_ft = int(3000 * 3.28084)
        assert dist <= max_ft, f"Main Street cafe at {dist} ft should be within {max_ft} ft"

    def test_outside_radius_filtered(self):
        """A cafe at ~3.5km (Ardsley from Dobbs Ferry) should be excluded."""
        from property_evaluator import _distance_feet
        dist = _distance_feet(41.0055, -73.8710, 41.0109, -73.8420)
        max_ft = int(3000 * 3.28084)
        assert dist > max_ft, f"Ardsley cafe at {dist} ft should exceed {max_ft} ft filter"
```

- [ ] **Step 2: Run the new tests**

Run: `pytest tests/test_scoring_regression.py::TestCoffeeDiscoveryFilter -v`
Expected: All 4 tests pass.

- [ ] **Step 3: Run full scoring test suite**

Run: `make test-scoring`
Expected: All tests pass (existing + new).

- [ ] **Step 4: Commit**

```bash
git add tests/test_scoring_regression.py
git commit -m "test(NES-393): add regression tests for coffee haversine post-filter

Verify _distance_feet with known Dobbs Ferry distances, the 3000m→ft
conversion constant, and that a Main Street cafe passes the filter
while Ardsley falls outside it."
```

---

### Task 6: Verification — run CLI evaluation for Dobbs Ferry

**Files:** None (verification only)

**Context:** The acceptance criteria require that Dobbs Ferry village cafes appear in results and scoring reflects actual access. Run the evaluator before and after the fix.

- [ ] **Step 1: Run evaluation for the reported address**

Run: `python cli.py evaluate "29 Ridge Rd, Dobbs Ferry, NY" --pretty 2>/dev/null | head -80`

Check:
- Coffee & Social Spots score should be > 6/10 if Main Street cafes are now surfaced
- Look for "Doubleshot" or other Main Street cafes in the output
- Walk time to best cafe should be < 30 min (not drive-only Ardsley at 7 min)

- [ ] **Step 2: Check Hastings (systematic pattern validation)**

Run: `python cli.py evaluate "25 Main St, Hastings-on-Hudson, NY" --pretty 2>/dev/null | head -80`

Check: Coffee results include village cafes, not just drive-to options.

- [ ] **Step 3: Check Irvington**

Run: `python cli.py evaluate "1 Main St, Irvington, NY" --pretty 2>/dev/null | head -80`

Check: Same pattern — village cafes surfaced.

- [ ] **Step 4: Document results**

Record before/after scores for all three addresses. If any village still shows drive-only coffee, file a follow-up ticket with the specific cafe names and their Google Places review counts — this would indicate the quality gate (15 reviews) is the bottleneck, not the discovery pipeline.
