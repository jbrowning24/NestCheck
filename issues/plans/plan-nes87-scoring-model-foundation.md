# NES-87: Scoring Model Foundation — Phase 1 Implementation Plan

**Overall Progress:** `100%` · **Status:** Complete
**Last updated:** 2026-02-13

## TLDR

Replace ad-hoc hardcoded scoring thresholds in `property_evaluator.py` with a parameterized, config-driven scoring framework. Phase 1 extracts constants into `scoring_config.py`, replaces step-function cliffs with smooth piecewise linear curves, introduces a richer `DimensionResult` return type, and adds a regression harness validated against the 30-address reference suite.

## Critical Decisions

- **Piecewise linear, not sigmoid** — Transparent breakpoints over elegant-but-opaque curves. Easier to reason about when tuning. Can upgrade to sigmoids in Phase 3 with experimentation tooling.
- **`scoring_config.py` with frozen dataclasses** — Not YAML/JSON (we want type checking and IDE support). Not inline in `property_evaluator.py` (already 3500+ lines).
- **Extract boundary: scoring constants only** — Search parameters (radii, type filters, quality gates), presentation thresholds, and transit constants stay in `property_evaluator.py`. Config module owns only values that affect the score number.
- **Fitness: multiplicative, not additive** — `distance_curve(walk_time) × quality_multiplier(rating)`, not two independent subscores. Proximity dominates; quality modifies. No quality gate added to search — all gyms scored, unlike coffee/grocery.
- **Transit stays structurally different** — 3-subcomponent composite (walk + frequency + hub) remains unique. Transit keeps `Tier2Score` return type; not migrated to `DimensionResult` in Phase 1.
- **Green space untouched** — Already the most principled scoring model. Left as-is in Phase 1.
- **Smooth immediately, validate against reference ranges** — Not byte-identical to old scores. Reference suite `expected_range` bounds are the acceptance criteria.
- **Scoring functions stay in `property_evaluator.py`** — Only config extracted now. File reorg is Phase 1.5 after harness confirms curves are correct (one variable at a time).
- **Reference range tightening happens after, not before** — Ship curves → build harness → first run establishes baselines → tighten ranges as follow-up.

## Tasks

### Phase 1a: Config Extraction (zero behavior change)

- [x] 🟩 **Step 1: Create `scoring_config.py`**
  - [x] 🟩 Define frozen dataclasses: `PiecewiseKnot`, `QualityMultiplier`, `DimensionConfig`, `Tier1Thresholds`, `Tier3Bonuses`, `ScoreBand`, `ScoringModel`
  - [x] 🟩 Create `SCORING_MODEL` module-level instance with current step-function values reproduced as knots:
    - Coffee: `(0,10),(15,10),(15.01,7),(20,7),(20.01,4),(30,4),(30.01,2),(60,2)` floor=2.0
    - Grocery: identical to coffee
    - Fitness: `(0,10),(15,10),(15.01,6),(20,6),(20.01,3),(30,3),(30.01,0),(60,0)` floor=0.0, with `quality_multipliers` `[4.2→1.0, 4.0→0.6, 0.0→0.3]`
    - Tier 1: all 500ft
    - Tier 3: parking=5, outdoor=5, bedroom=5, threshold=3, max=15
    - Score bands: `[(85,"Exceptional Daily Fit"),(70,"Strong Daily Fit"),(55,"Moderate — Some Trade-offs"),(40,"Limited — Car Likely Needed"),(0,"Significant Gaps")]`
  - [x] 🟩 Document fitness multiplier discrepancy in code comment (4.0★ at 20min: multiplicative gives 3.6, current gives 6 — acceptable because if/elif still runs in 1a, multipliers consumed in 1b)

- [x] 🟩 **Step 2: Wire `property_evaluator.py` to `SCORING_MODEL`**
  - [x] 🟩 `from scoring_config import SCORING_MODEL` at top
  - [x] 🟩 Replace `GAS_STATION_MIN_DISTANCE_FT`, `HIGHWAY_MIN_DISTANCE_FT`, `HIGH_VOLUME_ROAD_MIN_DISTANCE_FT` → `SCORING_MODEL.tier1.*`
  - [x] 🟩 Replace magic numbers in `score_third_place_access()` if/elif chain with `SCORING_MODEL.coffee` references (keep control flow identical)
  - [x] 🟩 Replace magic numbers in `score_provisioning_access()` if/elif chain with `SCORING_MODEL.grocery` references
  - [x] 🟩 Replace magic numbers in `score_fitness_access()` if/elif chain with `SCORING_MODEL.fitness` references (rating thresholds from `quality_multipliers`, walk times from knots)
  - [x] 🟩 Replace hardcoded bonus values in `calculate_bonuses()` → `SCORING_MODEL.tier3.*`
  - [x] 🟩 Replace `SCORE_BANDS` list → `SCORING_MODEL.score_bands`
  - [x] 🟩 Do NOT touch: search radii, type filters, quality gates, presentation thresholds, transit constants, template files

- [x] 🟩 **Step 3: Verify zero behavior change**
  - [x] 🟩 Run existing test suite (`test_import_sanity.py`, `test_green_space.py`, `test_transit_access.py`, `test_service_errors.py`)
  - [x] 🟩 Confirm no import errors or runtime failures

### Phase 1b: Smooth Curves + DimensionResult

- [x] 🟩 **Step 4: Implement `apply_piecewise()` function**
  - [x] 🟩 Add to `scoring_config.py`: pure function `apply_piecewise(knots: List[PiecewiseKnot], x: float) -> float` — linear interpolation between knots, clamp to first/last y values outside range
  - [x] 🟩 Add `apply_quality_multiplier(multipliers: List[QualityMultiplier], rating: float) -> float` — returns highest multiplier whose `min_rating ≤ rating`
  - [x] 🟩 Unit tests for both functions with edge cases (exact knot values, between knots, outside range, no multiplier match)

- [x] 🟩 **Step 5: Replace step-function knots with smooth piecewise linear curves**
  - [x] 🟩 Update `SCORING_MODEL` knots in `scoring_config.py`:
    - Coffee: `(0,10),(10,10),(15,8),(20,6),(30,4),(45,2),(60,2)` floor=2.0
    - Grocery: identical to coffee
    - Fitness: `(0,10),(10,10),(20,6),(30,3),(45,1),(60,1)` floor=0.0, quality multipliers revised: `[4.5→1.0, 4.2→1.0, 4.0→0.8, 3.5→0.6, 0.0→0.3]`
  - [x] 🟩 Bump `ScoringModel.version` to `"1.1.0"`

- [x] 🟩 **Step 6: Create `DimensionResult` dataclass**
  - [x] 🟩 Define in `scoring_config.py`:
    ```
    DimensionResult:
      score: float              # 0-10
      max_score: float          # 10.0
      name: str
      details: str              # backwards-compat with Tier2Score
      scoring_inputs: dict      # {"walk_time_min": 18, "rating": 4.3}
      subscores: dict | None    # {"proximity": 7.2, "quality": 0.8} for fitness
      model_version: str
    ```
  - [x] 🟩 Do NOT delete `Tier2Score` — transit still uses it

- [x] 🟩 **Step 7: Refactor scoring functions to use curves + DimensionResult**
  - [x] 🟩 `score_third_place_access()`: replace if/elif with `apply_piecewise(SCORING_MODEL.coffee.knots, walk_time)`, return `Tuple[DimensionResult, List[Dict]]`, `subscores=None`
  - [x] 🟩 `score_provisioning_access()`: same pattern with `SCORING_MODEL.grocery`, `subscores=None`
  - [x] 🟩 `score_fitness_access()`: `apply_piecewise(SCORING_MODEL.fitness.knots, walk_time) * apply_quality_multiplier(SCORING_MODEL.fitness.quality_multipliers, rating)`, return `Tuple[DimensionResult, List[Dict]]`, `subscores={"proximity": <curve_value>, "quality_mult": <multiplier>}`. Do NOT add a min_rating filter to the search — current behavior scores all gyms regardless of rating, quality_multipliers handle differentiation post-search
  - [x] 🟩 Only the three scoring functions change (construct `DimensionResult` instead of `Tier2Score`). Do NOT modify any consumer code — `DimensionResult` exposes the same interface via `.name`, `.points` (property), `.max_points` (property), `.details`
  - [x] 🟩 Update `EvaluationResult.tier2_scores` type annotation to `List[Union[Tier2Score, DimensionResult]]`

- [x] 🟩 **Step 8: Verify consumer compatibility (read-only audit, no code changes)**
  - [x] 🟩 `evaluate_property()`: `sum(s.points for s in result.tier2_scores)` → `.points` property returns `round(self.score)`, works
  - [x] 🟩 `format_result()`: reads `.name`, `.points`, `.details` → all present on `DimensionResult`
  - [x] 🟩 `app.py` serialization (line ~964): reads `.name`, `.points`, `.max_points`, `.details` → all present
  - [x] 🟩 `app.py` `generate_dimension_summaries()` / `_tier2_lookup()`: reads dict keys `"name"`, `"points"`, `"max"` → serialization produces these, works
  - [x] 🟩 `app.py` CSV export: same dict keys → works
  - [x] 🟩 `test_service_errors.py`: uses mock dicts → unaffected
  - [x] 🟩 Do NOT extend serialization to include new fields (`score`, `subscores`, `scoring_inputs`) — deferred until templates/snapshots are ready to consume them
  - [x] 🟩 If any consumer accesses a `Tier2Score` field that `DimensionResult` does NOT expose, flag it — do not silently drop data
  - [x] 🟩 Run existing test suite

### Phase 1c: Regression Harness

- [x] 🟩 **Step 9: Create `tests/test_scoring_regression.py`**
  - [x] 🟩 Unit tests for `apply_piecewise()` with synthetic inputs covering: exact knot hits, midpoints between knots, values before first knot, values after last knot
  - [x] 🟩 Unit tests for `apply_quality_multiplier()` covering: exact threshold match, between thresholds, below all thresholds
  - [x] 🟩 Parametrized tests for coffee/grocery/fitness curves: feed representative walk times (5, 12, 15, 17, 20, 25, 30, 40, 60 min) through `apply_piecewise()` and assert outputs are within expected ranges from reference suite metadata
  - [x] 🟩 Fitness-specific: test multiplicative model at key rating×walk-time combos (4.5★×8min, 4.2★×15min, 4.0★×20min, 3.5★×25min, any×35min)
  - [x] 🟩 Score band test: feed known scores through `get_score_band()` and assert correct band labels

- [x] 🟩 **Step 10: Run harness, confirm green**
  - [x] 🟩 All tests pass (79/79)
  - [x] 🟩 No regressions in existing test suite (18/18)

### Phase 1d: Model Version in Trace/Snapshot

- [x] 🟩 **Step 11: Add `model_version` to evaluation output**
  - [x] 🟩 Add `model_version: str` field to `EvaluationResult` dataclass, populated from `SCORING_MODEL.version`
  - [x] 🟩 Include `model_version` in `result_to_dict()` serialization in `app.py`
  - [x] 🟩 Include `model_version` in trace output via `nc_trace.py` if trace is active

### Phase 1e: Post-Review Fixes

- [x] 🟩 **Fix 1: Tier 2 total rounding mismatch**
  - [x] 🟩 `evaluate_property()` now computes `tier2_total = sum(s.points for s in tier2_scores)` — "round then sum" matches displayed per-dimension points, eliminating visible mismatch (e.g. 38 vs 39)
  - [x] 🟩 Removed `_raw_score()` / `_raw_max()` helpers that bypassed `DimensionResult.points`

- [x] 🟩 **Fix 2: `model_version` in CLI JSON output**
  - [x] 🟩 Added `"model_version": result.model_version` to CLI `--json` output dict in `property_evaluator.py`

- [x] 🟩 **Fix 3: Serialization consistency regression tests**
  - [x] 🟩 `TestTier2Aggregation`: round-then-sum invariant with synthetic DimensionResult + Tier2Score mixes, parametrized across 5 score vectors including the concrete repro case (10+10+9.6+2.88+6)
  - [x] 🟩 `TestModelVersionPresence`: version is set, is valid semver, and propagates through DimensionResult
  - [x] 🟩 Test count: 61 → 71 (all green)

---

## Future Phases (not built now — context for Phase 1 decisions)

**Phase 2 — Explicit Composite Weights:** Replace equal weighting (all 1.0) with config-driven `dimension_weights` dict. Document rationale per weight. `ScoringModel.dimension_weights` already has the slot.

**Phase 3 — Experimentation Tooling:** Diff tool comparing two `ScoringModel` versions against the reference suite. Visualization of curves. A/B scoring on the same address.

**Phase 0 (done) — Reference Address Suite:** 30 addresses in `tests/fixtures/reference_addresses.json` with per-dimension `expected_range` and `expected_band`.
