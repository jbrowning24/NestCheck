# Fitness Ground Truth (NES-274) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create ground-truth generator + validator for the fitness scoring dimension (Tier 2), testing the 2D scoring surface (walk distance × quality rating) plus drive-time fallback.

**Architecture:** Follows the established coffee ground-truth pattern. Generator creates ~66 deterministic test cases exercising knot boundaries, interpolation, monotonicity, clamping, quality multiplier brackets, drive-time knots, walk-vs-drive interaction, floor, confidence cap, and full pipeline composition. Validator dispatches each test type to a dedicated handler and reports matches/mismatches with the standard stdout format for the aggregate runner.

**Tech Stack:** Python, scoring_config.py (SCORING_MODEL.fitness, apply_piecewise, apply_quality_multiplier), property_evaluator.py (_apply_confidence_cap, _FITNESS_DRIVE_KNOTS)

---

## File Structure

| File | Action | Purpose |
|------|--------|---------|
| `scripts/generate_ground_truth_fitness.py` | Create | Generator: ~66 test cases for fitness scoring |
| `scripts/validate_ground_truth_fitness.py` | Create | Validator: dispatches by test_type, reports matches/mismatches |
| `data/ground_truth/fitness.json` | Create (generated) | Ground-truth file, seed=42 |
| `scripts/validate_all_ground_truth.py` | Modify | Add "fitness" to `_DIMENSION_LABELS` |

---

### Task 1: Create the fitness ground-truth generator

**Files:**
- Create: `scripts/generate_ground_truth_fitness.py`

**Fitness pipeline (from `score_fitness_access()`):**
```
Walk:  base = apply_piecewise(FITNESS_KNOTS, walk_time)
       mult = apply_quality_multiplier(FITNESS_MULTIPLIERS, rating)
       walk_score = base * mult

Drive: drive_base = apply_piecewise(FITNESS_DRIVE_KNOTS, drive_time)
       drive_mult = apply_quality_multiplier(FITNESS_MULTIPLIERS, rating)
       drive_score = drive_base * drive_mult

best_score = max(walk_score, drive_score)   # quality applied BEFORE max
capped = _apply_confidence_cap(best_score, confidence)
points = int(max(0.0, capped) + 0.5)
```

**Config constants to import:**
- `SCORING_MODEL.fitness.knots` = `(0,10), (10,10), (20,6), (30,3), (45,1), (60,1)`
- `SCORING_MODEL.fitness.floor` = `0.0`
- `SCORING_MODEL.fitness.quality_multipliers` = 4.5+→1.0, 4.2+→1.0, 4.0+→0.8, 3.5+→0.6, 0.0+→0.3
- `_FITNESS_DRIVE_KNOTS` = `(0,10), (5,10), (10,8), (15,6), (20,3), (25,1), (30,0)`

**Test categories to generate:**

1. **`knot_boundary`** (6 tests): Exact knot x-values from `FITNESS_KNOTS`, at rating 4.5 (mult=1.0) so expected = knot.y
2. **`interpolation`** (4 tests): Midpoints between non-flat knot segments, at rating 4.5
3. **`monotonicity`** (~15 tests): Ordered walk-time pairs at constant quality (rating 4.5, mult=1.0). score(t1) >= score(t2) when t1 < t2
4. **`clamping`** (2 tests): Before first / after last knot at rating 4.5
5. **`quality_multiplier`** (5 tests): Same walk_time=5 (base=10), each rating bracket:
   - 4.5★ → mult=1.0 → score=10.0
   - 4.2★ → mult=1.0 → score=10.0
   - 4.0★ → mult=0.8 → score=8.0
   - 3.5★ → mult=0.6 → score=6.0
   - 2.0★ → mult=0.3 → score=3.0
6. **`interaction`** (~8 tests): 2D grid of distances × ratings, verify score = piecewise × multiplier
   - 3 distances (5min=10, 15min=8, 25min=4.5) × 3 ratings (4.5, 4.0, 3.5)
   - Minus redundant cases, ~8 useful combinations
7. **`drive_knot_boundary`** (7 tests): Exact knot values from `FITNESS_DRIVE_KNOTS` at rating 4.5
8. **`drive_interaction`** (4 tests): Drive time × quality multiplier at different ratings
9. **`walk_vs_drive_max`** (4 tests): Verify `max(walk_score, drive_score)` at same rating:
   - Walk 25min (base=4.5, mult=1.0 → 4.5) vs drive 5min (base=10, mult=1.0 → 10) → drive wins
   - Walk 15min (base=8, mult=1.0 → 8) vs drive 10min (base=8, mult=1.0 → 8) → tie
   - Walk 10min (base=10, mult=0.6 → 6) vs drive 15min (base=6, mult=0.6 → 3.6) → walk wins
   - Walk 30min (base=3, mult=0.8 → 2.4) vs drive 8min (base=8.8, mult=0.8 → 7.04) → drive wins
10. **`floor`** (2 tests): No gym (score=0), far gym with bad rating (score near 0)
11. **`confidence_cap`** (3 tests): verified/estimated/sparse with high base score
    - verified: base 10 → capped 10
    - estimated: base 10 → capped 8
    - sparse: base 10 → capped 6
12. **`pipeline_composition`** (6 tests): Full pipeline with all intermediate values
    - High proximity + good rating + verified → no cap, full score
    - High proximity + bad rating + verified → quality mult reduces
    - Moderate proximity + moderate rating + estimated → confidence cap bites (3 of 6 must hit confidence cap)
    - Long walk + moderate drive + good rating → drive path wins after quality mult
    - Walk beats drive: close walk + far drive at same rating
    - Zero-floor: no gym found → score=0

**Implementation notes:**
- Follow coffee generator structure exactly (argparse, seed, schema_version 0.2.0)
- Import `apply_quality_multiplier` from `scoring_config`
- Import `_FITNESS_DRIVE_KNOTS` from `property_evaluator` with try/except fallback
- IDs: `gt-fitness-<type>-NN` pattern
- For quality_multiplier/interaction/drive tests, inputs include `rating` field
- For walk_vs_drive_max tests, inputs include `walk_time_min`, `drive_time_min`, `rating`
- For pipeline tests, inputs include `walk_time_min`, `drive_time_min` (nullable), `rating`, `confidence`

- [ ] **Step 1:** Write `scripts/generate_ground_truth_fitness.py` with all 12 test categories
- [ ] **Step 2:** Run `cd /Users/jeremybrowning/NestCheck && source venv/bin/activate && python scripts/generate_ground_truth_fitness.py --seed 42`. Expected: prints test counts per category, writes `data/ground_truth/fitness.json`
- [ ] **Step 3:** Verify the JSON: `python -c "import json; d=json.load(open('data/ground_truth/fitness.json')); print(d['_test_count'])"` — should print ~66

---

### Task 2: Create the fitness ground-truth validator

**Files:**
- Create: `scripts/validate_ground_truth_fitness.py`

**Validator dispatch table** (one handler per test_type):
- `knot_boundary` → apply_piecewise at knot x-values (at quality 1.0)
- `interpolation` → apply_piecewise at midpoints (at quality 1.0)
- `monotonicity` → score(t1) >= score(t2) at constant quality
- `clamping` → apply_piecewise outside range (at quality 1.0)
- `quality_multiplier` → apply_quality_multiplier at each rating bracket
- `interaction` → piecewise × multiplier = expected
- `drive_knot_boundary` → apply_piecewise with drive knots
- `drive_interaction` → drive piecewise × multiplier
- `walk_vs_drive_max` → max(walk_path, drive_path) after both apply quality
- `floor` → final score >= 0
- `confidence_cap` → _apply_confidence_cap reduces score correctly
- `pipeline_composition` → full pipeline, check all 6 intermediate values

**Implementation notes:**
- Follow coffee validator structure exactly (argparse, TOLERANCE=0.001, ctx dict, dispatch table)
- Import `apply_quality_multiplier` from `scoring_config`
- Import `_FITNESS_DRIVE_KNOTS, _apply_confidence_cap` from `property_evaluator`
- Output `Matches:` / `Mismatches:` lines for aggregate runner parsing
- Uses `SCORING_MODEL.fitness` for knots/floor/quality_multipliers context

- [ ] **Step 1:** Write `scripts/validate_ground_truth_fitness.py`
- [ ] **Step 2:** Run `cd /Users/jeremybrowning/NestCheck && source venv/bin/activate && python scripts/validate_ground_truth_fitness.py --verbose`. Expected: all tests MATCH, exit code 0
- [ ] **Step 3:** Run via aggregate runner: `python scripts/validate_all_ground_truth.py --dimension fitness`. Expected: passes (may warn about missing label — fixed in Task 3)

---

### Task 3: Wire into aggregate runner

**Files:**
- Modify: `scripts/validate_all_ground_truth.py` (~line 28-33)

- [ ] **Step 1:** Add `"fitness": "Fitness scoring (Tier 2)"` to `_DIMENSION_LABELS` dict
- [ ] **Step 2:** Run `python scripts/validate_all_ground_truth.py`. Expected: fitness appears in aggregate output, all dimensions pass
- [ ] **Step 3:** Commit all three files + generated JSON

---

### Task 4: Verification

- [ ] **Step 1:** Run full validation: `python scripts/validate_all_ground_truth.py --verbose`
- [ ] **Step 2:** Run `make test-scoring` to verify no regressions
- [ ] **Step 3:** Spot-check 2-3 pipeline composition cases manually against the scoring function logic
