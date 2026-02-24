# Your Neighborhood — Phase 3 Implementation Plan

**Overall Progress:** `100%` · **Status:** Complete
**Last updated:** 2026-02-09

## TLDR
Surface place data (cafes, grocery, fitness, parks) that is already fetched during scoring but currently discarded after picking the single best. Display as Apple-style cards grouped by category in the "Your Neighborhood" section of the results page.

## Critical Decisions
- **Tuple return:** Each scoring function returns `(Tier2Score, list[dict])` instead of just `Tier2Score` — clean, no side effects, easy to unwire
- **Cap 5 places per category:** Enough to be useful, keeps cards scannable
- **CSS in both templates:** Styles go into `index.html` and `snapshot.html` `<style>` blocks (no external CSS files exist)
- **Backward compat:** Template checks `result.neighborhood_places` existence; old snapshots show fallback message
- **fitness_access lacks pre_fetched_places:** Walk times are already computed for all places inside the function, so we collect there directly
- **Parks from green_escape:** Extract from `evaluation.nearby_green_spaces` (GreenSpaceResult already has lat/lng)

## Tasks

- [x] 🟩 **Step 1: Add `neighborhood_places` field to EvaluationResult**
  - [x] 🟩 Add `neighborhood_places: Optional[Dict] = None` to dataclass (~line 582 of property_evaluator.py)

- [x] 🟩 **Step 2: Modify `score_third_place_access()` to return place list**
  - [x] 🟩 After walk times are computed (~line 2323), collect up to 5 eligible places with: name, rating, review_count, walk_time_min, lat, lng — sorted by walk-time score then walk time
  - [x] 🟩 Change return to `(Tier2Score, places_list)` — scoring logic untouched

- [x] 🟩 **Step 3: Modify `score_provisioning_access()` to return place list**
  - [x] 🟩 Same pattern: after walk times (~line 2574), collect up to 5 stores with all fields
  - [x] 🟩 Change return to `(Tier2Score, places_list)`

- [x] 🟩 **Step 4: Modify `score_fitness_access()` to return place list**
  - [x] 🟩 Same pattern: after walk times (~line 2651), collect up to 5 facilities with all fields
  - [x] 🟩 Change return to `(Tier2Score, places_list)`

- [x] 🟩 **Step 5: Update `evaluate_property()` to collect neighborhood places**
  - [x] 🟩 Unpack tuples from the three scoring functions: `(score, places) = ...`
  - [x] 🟩 Append `score` to `tier2_scores` as before (preserves scoring)
  - [x] 🟩 Build `result.neighborhood_places = {"coffee": [...], "grocery": [...], "fitness": [...]}`
  - [x] 🟩 Extract parks from `result.green_escape_evaluation.nearby_green_spaces` into `"parks"` key (name, rating, user_ratings_total, walk_time_min, lat, lng)

- [x] 🟩 **Step 6: Serialize `neighborhood_places` in `result_to_dict()`**
  - [x] 🟩 Add `neighborhood_places` to output dict in app.py (~line 355)
  - [x] 🟩 Pass through as-is (already plain dicts); default to `None` if absent
  - [x] 🟩 Confirm `coordinates` already present (line 286 — verified)

- [x] 🟩 **Step 7: Render "Your Neighborhood" section in template**
  - [x] 🟩 Replace placeholder div in `_result_sections.html` (lines 33-36) with category-grouped place cards
  - [x] 🟩 Categories: coffee, grocery, fitness, parks — each with icon, label, up to 5 cards
  - [x] 🟩 Each card shows: name, rating + review count, walk/drive time
  - [x] 🟩 Fallback message for old snapshots without neighborhood_places

- [x] 🟩 **Step 8: Add neighborhood card CSS**
  - [x] 🟩 Add `.neighborhood-category`, `.category-label`, `.place-cards`, `.place-card`, `.place-name`, `.place-meta`, `.place-rating`, `.place-reviews`, `.place-time` styles to `index.html` `<style>` block
  - [x] 🟩 Add same styles to `snapshot.html` `<style>` block
  - [x] 🟩 Mobile responsive: stack cards at `max-width: 600px`

- [x] 🟩 **Step 9: Verify**
  - [x] 🟩 Confirm Tier2Score values unchanged (scoring logic untouched)
  - [x] 🟩 Confirm no new API calls added
  - [x] 🟩 Test old snapshot loads without error (fallback message shown)
