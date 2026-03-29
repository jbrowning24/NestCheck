# NES-322: Wire Drive Fallbacks for Coffee & Grocery

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire `_COFFEE_DRIVE_KNOTS` and `_GROCERY_DRIVE_KNOTS` into their scoring functions so car-dependent addresses get partial credit instead of floor scores.

**Architecture:** Follow the fitness drive fallback pattern from NES-315. One key divergence: coffee has a quality ceiling that must be applied to the walk score *before* `max(walk, drive)` — the drive score bypasses the ceiling since venue diversity is irrelevant when driving. Grocery has no quality ceiling, so it's a straight copy of the fitness pattern minus the quality multiplier.

**Tech Stack:** Python, scoring_config.py piecewise curves, GoogleMapsClient.driving_time()

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `scoring_config.py:280-310` | Modify | Re-tune `_COFFEE_DRIVE_KNOTS` and `_GROCERY_DRIVE_KNOTS` ceilings from 10→6 |
| `scoring_config.py:381` | Modify | Bump model version 1.7.0 → 1.8.0 |
| `property_evaluator.py:40-49` | Modify | Add `_COFFEE_DRIVE_KNOTS`, `_GROCERY_DRIVE_KNOTS` to imports |
| `property_evaluator.py:4949-5129` | Modify | Wire drive fallback into `score_third_place_access()` |
| `property_evaluator.py:5430-5584` | Modify | Wire drive fallback into `score_provisioning_access()` |

No template changes — the existing `access_mode_annotation` Jinja macro and tiered walk/drive display in `_result_sections.html` already handle `access_mode`/`drive_time_min` from the NES-315 fitness implementation.

---

### Task 1: Re-tune drive knot ceilings in scoring_config.py

**Files:**
- Modify: `scoring_config.py:280-310` (drive knot tuples)
- Modify: `scoring_config.py:381` (model version)

- [ ] **Step 1: Re-tune `_COFFEE_DRIVE_KNOTS` ceiling from 10→6**

Replace lines 280-288 with the fitness-matching shape:

```python
_COFFEE_DRIVE_KNOTS = (
    PiecewiseKnot(0, 6),
    PiecewiseKnot(5, 6),
    PiecewiseKnot(10, 5),
    PiecewiseKnot(15, 3),
    PiecewiseKnot(20, 1),
    PiecewiseKnot(25, 0),
    PiecewiseKnot(30, 0),
)
```

- [ ] **Step 2: Re-tune `_GROCERY_DRIVE_KNOTS` ceiling from 10→6**

Replace lines 302-310 with the same shape:

```python
_GROCERY_DRIVE_KNOTS = (
    PiecewiseKnot(0, 6),
    PiecewiseKnot(5, 6),
    PiecewiseKnot(10, 5),
    PiecewiseKnot(15, 3),
    PiecewiseKnot(20, 1),
    PiecewiseKnot(25, 0),
    PiecewiseKnot(30, 0),
)
```

- [ ] **Step 3: Bump model version**

Change `version="1.7.0"` → `version="1.8.0"` at line 381.

- [ ] **Step 4: Run scoring config tests**

Run: `cd /Users/jeremybrowning/NestCheck && python -m pytest tests/test_scoring_config.py -v`
Expected: PASS — the existing test validates knot monotonicity and structure, which these tuples satisfy.

- [ ] **Step 5: Commit**

```
feat(scoring): re-tune coffee/grocery drive knot ceilings to 6 (NES-322)
```

---

### Task 2: Update imports in property_evaluator.py

**Files:**
- Modify: `property_evaluator.py:40-49` (import block)

- [ ] **Step 1: Add drive knot imports**

Add `_COFFEE_DRIVE_KNOTS` and `_GROCERY_DRIVE_KNOTS` to the `from scoring_config import` block, alongside the existing `_FITNESS_DRIVE_KNOTS`:

```python
from scoring_config import (
    SCORING_MODEL,
    apply_piecewise, apply_quality_multiplier,
    QualityCeilingConfig,
    CONFIDENCE_VERIFIED, CONFIDENCE_ESTIMATED, CONFIDENCE_SPARSE, CONFIDENCE_NOT_SCORED,
    VENUE_MIN_RATING, VENUE_MIN_REVIEWS,
    _FITNESS_DRIVE_KNOTS,
    _COFFEE_DRIVE_KNOTS,
    _GROCERY_DRIVE_KNOTS,
    WALK_DRIVE_BOTH_THRESHOLD,
    DRIVE_ONLY_CEILING,
)
```

- [ ] **Step 2: Verify import succeeds**

Run: `cd /Users/jeremybrowning/NestCheck && python -c "import property_evaluator; print('OK')"`
Expected: `OK` (verifies property_evaluator.py loads without import errors)

- [ ] **Step 3: Commit**

```
feat(scoring): import coffee/grocery drive knots into evaluator (NES-322)
```

---

### Task 3: Wire drive fallback into grocery scoring

Grocery is simpler (no quality ceiling), so do it first as the baseline pattern.

**Files:**
- Modify: `property_evaluator.py` — `score_provisioning_access()` function (~line 5430)

**Reference pattern:** `score_fitness_access()` lines 5729-5757.

**Note:** The early return paths (no stores found at line 5461, no eligible stores at line 5500) return 2-tuples `(Tier2Score, [])` or 3-tuples `(Tier2Score, [], _no_data)` — this inconsistency is pre-existing and not changed by this task. Only the main scoring path (line 5577) returns the full 3-tuple with `_details_data`.

- [ ] **Step 1: Add drive-time scoring block after walk scoring loop**

After the walk scoring loop (after `scored_stores.append(...)`, around line 5536), and before the `scored_stores.sort(...)` line, insert the drive-time fallback block. Note: capture `best_walk_score` before the drive block so we can compare later.

```python
        # Capture walk score before drive comparison
        best_walk_score = best_score

        # -- Drive-time scoring for the best store (NES-322) --------
        # Same pattern as fitness (NES-259): single driving_time() call
        # for the best walk-scored store when walk exceeds threshold.
        best_drive_time = None
        best_drive_score = 0
        if best_store and best_walk_time > WALK_DRIVE_BOTH_THRESHOLD:
            try:
                best_drive_time = maps.driving_time(
                    (lat, lng),
                    (best_store["geometry"]["location"]["lat"],
                     best_store["geometry"]["location"]["lng"]),
                    place_id=best_store.get("place_id"),
                )
                if best_drive_time and best_drive_time != 9999:
                    best_drive_score = apply_piecewise(
                        _GROCERY_DRIVE_KNOTS, best_drive_time)
                else:
                    best_drive_time = None
            except Exception:
                logger.warning("Grocery drive time lookup failed",
                               exc_info=True)
                best_drive_time = None
```

- [ ] **Step 2: Update score selection to use max(walk, drive) with DRIVE_ONLY_CEILING**

Replace the existing `capped_score = _apply_confidence_cap(best_score, conf)` block (around line 5566) with:

```python
        # Use the better of walk and drive scores
        if best_drive_score > best_walk_score:
            best_score = min(best_drive_score, DRIVE_ONLY_CEILING)

        # Cap score when data confidence is low (NES-sparse-data)
        capped_score = _apply_confidence_cap(best_score, conf)
```

- [ ] **Step 3: Update details string for drive display**

Replace the existing details formatting (around line 5554-5558) to handle drive. Use `best_walk_score` (captured in Step 1) for the comparison:

```python
        # Format details
        name = best_store.get("name", "Provisioning store")
        rating = best_store.get("rating", 0)
        reviews = best_store.get("user_ratings_total", 0)
        if best_drive_score > best_walk_score and best_drive_time:
            details = (
                f"{name} ({rating}★, {reviews} reviews)"
                f" — {best_drive_time} min drive"
            )
        else:
            details = (
                f"{name} ({rating}★, {reviews} reviews)"
                f" — {best_walk_time} min walk"
            )
```

- [ ] **Step 4: Thread drive_time_min into neighborhood_places for best store**

After the `neighborhood_places` list is built and sorted (around line 5552), add drive_time_min threading — same pattern as fitness lines 5793-5798:

```python
        # Attach drive time to the best store's neighborhood entry
        if best_drive_time and best_store:
            _best_pid = best_store.get("place_id")
            for np in neighborhood_places:
                if np.get("place_id") == _best_pid:
                    np["drive_time_min"] = best_drive_time
                    break
```

- [ ] **Step 5: Update _details_data dict**

Update the `_details_data` dict (around line 5571) to reflect drive mode when drive wins:

```python
        _details_data = {
            "access_mode": (
                "drive" if best_drive_score > best_walk_score else "walk"
            ) if best_store else None,
            "walk_time_min": best_walk_time if best_walk_time != 9999 else None,
            "drive_time_min": best_drive_time,
            "venue_name": best_store.get("name", "Provisioning store") if best_store else None,
        }
```

- [ ] **Step 6: Run scoring tests**

Run: `cd /Users/jeremybrowning/NestCheck && python -m pytest tests/test_scoring_config.py tests/test_scoring_regression.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```
feat(scoring): wire drive fallback into grocery scoring (NES-322)
```

---

### Task 4: Wire drive fallback into coffee scoring

Coffee requires careful ordering due to the quality ceiling. The CTO's prescribed order:
**walk_score → quality ceiling → max(ceilinged_walk, drive) → DRIVE_ONLY_CEILING → confidence cap → floor → round**

**Files:**
- Modify: `property_evaluator.py` — `score_third_place_access()` function (~line 4949)

**Reference pattern:** Grocery (Task 3) + quality ceiling interaction.

- [ ] **Step 1: Add drive-time scoring block after walk scoring loop**

After the walk scoring loop (after `scored_places.append(...)`, around line 5052), insert the drive block. This is identical to the grocery pattern:

```python
        # -- Drive-time scoring for the best place (NES-322) --------
        # Same pattern as fitness (NES-259) and grocery: single
        # driving_time() call for the best walk-scored place when walk
        # exceeds threshold.
        best_drive_time = None
        best_drive_score = 0
        if best_place and best_walk_time > WALK_DRIVE_BOTH_THRESHOLD:
            try:
                best_drive_time = maps.driving_time(
                    (lat, lng),
                    (best_place["geometry"]["location"]["lat"],
                     best_place["geometry"]["location"]["lng"]),
                    place_id=best_place.get("place_id"),
                )
                if best_drive_time and best_drive_time != 9999:
                    best_drive_score = apply_piecewise(
                        _COFFEE_DRIVE_KNOTS, best_drive_time)
                else:
                    best_drive_time = None
            except Exception:
                logger.warning("Coffee drive time lookup failed",
                               exc_info=True)
                best_drive_time = None
```

- [ ] **Step 2: Restructure the scoring pipeline for correct ceiling ordering**

This is the critical divergence from the fitness/grocery pattern. The current code applies quality ceiling then confidence cap to `best_score` (walk-only). We need to:

1. Apply quality ceiling to walk score first
2. Then take max(ceilinged_walk, drive)
3. Then apply DRIVE_ONLY_CEILING if drive won
4. Then confidence cap, floor, round

Replace the existing quality ceiling + confidence cap + points block (around lines 5100-5114) with:

```python
        # --- Quality ceiling (applied to walk score only) ---
        # CTO guidance: quality ceiling measures venue diversity around
        # the address — irrelevant when driving. Apply to walk score
        # before the walk/drive comparison, not after.
        best_walk_score = best_score  # capture before ceiling
        ceiling_config = SCORING_MODEL.coffee.quality_ceiling
        if ceiling_config is not None:
            quality_ceiling = _compute_quality_ceiling(
                eligible_places, ceiling_config,
                social_bucket_count=len(_all_buckets),
            )
            best_walk_score = min(best_walk_score, quality_ceiling)

        # Use the better of walk (post-ceiling) and drive scores
        final_score = best_walk_score
        if best_drive_score > best_walk_score:
            final_score = min(best_drive_score, DRIVE_ONLY_CEILING)

        # Cap score when data confidence is low (NES-sparse-data)
        capped_score = _apply_confidence_cap(final_score, conf)

        # Round to int for Tier2Score.points (piecewise returns float)
        points = int(max(SCORING_MODEL.coffee.floor, capped_score) + 0.5)
```

- [ ] **Step 3: Update details string for drive display**

Replace the existing details formatting (around line 5090-5093):

```python
        # Format details
        name = best_place.get("name", "Coffee spot")
        rating = best_place.get("rating", 0)
        reviews = best_place.get("user_ratings_total", 0)
        if best_drive_score > best_walk_score and best_drive_time:
            details = (
                f"{name} ({rating}★, {reviews} reviews)"
                f" — {best_drive_time} min drive"
            )
        else:
            details = (
                f"{name} ({rating}★, {reviews} reviews)"
                f" — {best_walk_time} min walk"
            )
```

Here `best_walk_score` is the post-ceiling walk score, so the comparison is correct: drive displays when it actually won.

- [ ] **Step 4: Thread drive_time_min into neighborhood_places for best place**

After the `neighborhood_places` list is built and sorted (around line 5069), add:

```python
        # Attach drive time to the best place's neighborhood entry
        if best_drive_time and best_place:
            _best_pid = best_place.get("place_id")
            for np in neighborhood_places:
                if np.get("place_id") == _best_pid:
                    np["drive_time_min"] = best_drive_time
                    break
```

- [ ] **Step 5: Update _details_data dict**

Update the `_details_data` dict (around line 5116) to reflect drive mode:

```python
        _details_data = {
            "access_mode": (
                "drive" if best_drive_score > best_walk_score else "walk"
            ) if best_place else None,
            "walk_time_min": best_walk_time if best_walk_time != 9999 else None,
            "drive_time_min": best_drive_time,
            "venue_name": best_place.get("name", "Coffee spot") if best_place else None,
        }
```

- [ ] **Step 6: Run all scoring tests**

Run: `cd /Users/jeremybrowning/NestCheck && python -m pytest tests/test_scoring_config.py tests/test_scoring_regression.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```
feat(scoring): wire drive fallback into coffee scoring with ceiling ordering (NES-322)
```

---

### Task 5: Final verification

- [ ] **Step 1: Run full scoring test suite**

Run: `cd /Users/jeremybrowning/NestCheck && make test-scoring`
Expected: All tests PASS

- [ ] **Step 2: Verify import consistency**

Run: `cd /Users/jeremybrowning/NestCheck && python -c "from property_evaluator import score_third_place_access, score_provisioning_access; print('Imports OK')"`
Expected: `Imports OK`

- [ ] **Step 3: Spot-check drive knot values**

Run: `cd /Users/jeremybrowning/NestCheck && python -c "from scoring_config import _COFFEE_DRIVE_KNOTS, _GROCERY_DRIVE_KNOTS, _FITNESS_DRIVE_KNOTS; print('Coffee ceiling:', _COFFEE_DRIVE_KNOTS[0].y); print('Grocery ceiling:', _GROCERY_DRIVE_KNOTS[0].y); print('Fitness ceiling:', _FITNESS_DRIVE_KNOTS[0].y); assert all(k[0].y == 6 for k in [_COFFEE_DRIVE_KNOTS, _GROCERY_DRIVE_KNOTS, _FITNESS_DRIVE_KNOTS]), 'All drive ceilings should be 6'"`
Expected: All ceilings = 6

- [ ] **Step 4: Commit final state if needed, then done**

---

## API Cost Impact

+2 conditional Distance Matrix calls per evaluation (one coffee, one grocery) when `best_walk_time > 20 min`. Urban walkable addresses: no change. Suburban car-dependent addresses (the target): +$0.01 worst case. Walk time cache (NES-292) absorbs most repeat-area cost.

## What's NOT in this plan (fast-follows)

- **Ground truth updates** for coffee/grocery drive paths — existing ground truth only covers walk-time curves
- **Refactor to `DimensionConfig.drive_knots`** — now that all three dimensions have drive knots, the underscore-prefixed cross-module imports should be cleaned up (per CTO and CLAUDE.md guidance)
