# Implementation Plan: NES-189 Data Confidence Indicators

**Progress:** `[----------] 0%`
**Created:** 2026-02-28

## TL;DR
Add systematic data confidence indicators (HIGH / MEDIUM / LOW) to every scoring dimension so users can distinguish scores backed by rich data from those based on sparse data. Follows the existing sidewalk coverage confidence pattern. Each dimension score gains a confidence level and explanatory note, displayed as subtle badges in the verdict card and section headers.

## Critical Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Where confidence lives | Optional fields on `Tier2Score` | Backward-compatible (None default), co-located with score, no return-signature changes |
| Confidence vocabulary | HIGH / MEDIUM / LOW strings | Matches existing sidewalk pattern; simple, unambiguous |
| Scoring function changes | Add confidence to each `score_*` function directly | Functions have the richest intermediate data (place counts, review counts, search result quality) |
| Template behavior for old snapshots | Missing confidence silently hidden | `{% if dim.data_confidence is defined %}` guard — same pattern as `score_band`, `presented_checks` |
| Aggregate confidence | Weakest-link (lowest dimension confidence) | If one dimension has LOW confidence, the overall score is unreliable |

## Tasks

### Phase 1: Foundation — Data Model + Confidence Classifiers

- [ ] 🟥 **Step 1: Add confidence fields to `Tier2Score` and `DimensionResult`**
  - Files: `property_evaluator.py:172-186`, `scoring_config.py:70-98`
  - Add `data_confidence: Optional[str] = None` and `data_confidence_note: Optional[str] = None` to `Tier2Score` dataclass
  - Add same fields to `DimensionResult` dataclass
  - Acceptance: Both dataclasses accept confidence fields; existing tests pass unchanged

- [ ] 🟥 **Step 2: Add confidence classifier for Google Places dimensions (coffee, grocery, fitness)**
  - Files: `property_evaluator.py` (new helper near line 3210)
  - Create `_classify_places_confidence(eligible_count: int, best_review_count: int) -> Tuple[str, str]`
  - Thresholds:
    - HIGH: ≥3 eligible places AND best place has ≥100 reviews
    - MEDIUM: ≥1 eligible place AND best place has ≥30 reviews
    - LOW: 0 eligible places OR best place has <30 reviews
  - Acceptance: Unit test with representative inputs returns expected levels

- [ ] 🟥 **Step 3: Add confidence classifier for transit dimension**
  - Files: `property_evaluator.py` (new helper near line 3370)
  - Create `_classify_transit_confidence(transit_access, urban_access) -> Tuple[str, str]`
  - Thresholds:
    - HIGH: walk time computed + frequency from OSM density ≥10 nodes
    - MEDIUM: walk time computed + some frequency data
    - LOW: no transit data at all OR walk time missing
  - Acceptance: Unit test covering each level

- [ ] 🟥 **Step 4: Add confidence classifier for parks dimension**
  - Files: `property_evaluator.py` (new helper near line 3130)
  - Create `_classify_park_confidence(green_escape_eval) -> Tuple[str, str]`
  - Thresholds:
    - HIGH: OSM-enriched best park + ≥100 reviews + measured (not estimated) acreage
    - MEDIUM: best park found but some subscores estimated OR <100 reviews
    - LOW: no parks found OR all subscores estimated
  - Acceptance: Unit test covering each level

- [ ] 🟥 **Step 5: Add confidence classifier for cost dimension**
  - Files: `property_evaluator.py` (inline in `score_cost`)
  - Simple: HIGH if cost provided, LOW if cost is None
  - Acceptance: Unit test

### Phase 2: Wire Confidence Into Scoring Functions

- [ ] 🟥 **Step 6: Wire confidence into `score_third_place_access()`**
  - Files: `property_evaluator.py:3211-3338`
  - After filtering eligible_places, call `_classify_places_confidence(len(eligible_places), best_review_count)`
  - Set `data_confidence` and `data_confidence_note` on the returned `Tier2Score`
  - Acceptance: Scoring function returns populated confidence; existing score values unchanged

- [ ] 🟥 **Step 7: Wire confidence into `score_provisioning_access()`**
  - Files: `property_evaluator.py:3488-3615`
  - Same pattern as Step 6
  - Acceptance: Scoring function returns populated confidence; existing score values unchanged

- [ ] 🟥 **Step 8: Wire confidence into `score_fitness_access()`**
  - Files: `property_evaluator.py:3617-3728`
  - Same pattern as Step 6
  - Acceptance: Scoring function returns populated confidence; existing score values unchanged

- [ ] 🟥 **Step 9: Wire confidence into `score_park_access()`**
  - Files: `property_evaluator.py:3134-3209`
  - Call `_classify_park_confidence(green_escape_evaluation)` when using new engine
  - Acceptance: Scoring function returns populated confidence

- [ ] 🟥 **Step 10: Wire confidence into `score_cost()`**
  - Files: `property_evaluator.py:3340-3369`
  - Inline: `data_confidence="HIGH"` if cost provided, `"LOW"` if None
  - Acceptance: Scoring function returns populated confidence

- [ ] 🟥 **Step 11: Wire confidence into `score_transit_access()`**
  - Files: `property_evaluator.py:3371-3486`
  - Call `_classify_transit_confidence(transit_access, urban_access)`
  - Acceptance: Scoring function returns populated confidence

### Phase 3: Serialization + Template Display

- [ ] 🟥 **Step 12: Serialize confidence in `result_to_dict()`**
  - Files: `app.py:952-955`
  - Extend tier2_scores serialization to include `data_confidence` and `data_confidence_note`:
    ```python
    {"name": s.name, "points": s.points, "max": s.max_points,
     "details": s.details,
     "data_confidence": s.data_confidence,
     "data_confidence_note": s.data_confidence_note}
    ```
  - Acceptance: Snapshot JSON contains confidence per dimension; old snapshots have None

- [ ] 🟥 **Step 13: Compute and serialize aggregate confidence**
  - Files: `app.py` (in `result_to_dict()`, after tier2_scores serialization)
  - Add `data_confidence_summary` to output dict: weakest-link across all dimensions
  - Structure: `{"level": "HIGH|MEDIUM|LOW", "note": "...", "low_confidence_dimensions": [...]}`
  - Acceptance: Aggregate confidence is present in result dict

- [ ] 🟥 **Step 14: Display confidence badges on dimension summaries**
  - Files: `templates/_result_sections.html:80-100`
  - Add small confidence badge next to each `dim.score/dim.max_score` in the dimension list
  - Only show for MEDIUM and LOW (HIGH is the default, doesn't need a badge)
  - Badge: `<span class="confidence-badge confidence-{{ level|lower }}" title="{{ note }}">{{ "Limited data" if level == "MEDIUM" else "Sparse data" }}</span>`
  - Acceptance: Badges appear for MEDIUM/LOW dimensions; hidden for HIGH; old snapshots render without error

- [ ] 🟥 **Step 15: Display aggregate confidence on verdict card**
  - Files: `templates/_result_sections.html:14-45`
  - Below the score ring, add a one-line note when aggregate confidence is not HIGH:
    `"Data confidence: Limited — some dimensions have sparse coverage data"`
  - Hidden when all dimensions are HIGH
  - Acceptance: Note appears when any dimension is LOW or MEDIUM; hidden when all HIGH

- [ ] 🟥 **Step 16: Add confidence indicator CSS**
  - Files: `static/css/report.css`
  - `.confidence-badge` — small pill, muted text, inline with dimension score
  - `.confidence-medium` — amber/warning color (use existing `--color-warning-text`)
  - `.confidence-low` — muted red (use existing `--color-danger`)
  - `.confidence-summary` — small text below score ring
  - Acceptance: Visual check on new evaluation; badges styled correctly

### Phase 4: Tests

- [ ] 🟥 **Step 17: Unit tests for confidence classifiers**
  - Files: `tests/test_data_confidence.py` (new file)
  - Test `_classify_places_confidence`: HIGH/MEDIUM/LOW boundary cases, zero-place edge case
  - Test `_classify_transit_confidence`: with/without transit data, with/without walk time
  - Test `_classify_park_confidence`: OSM-enriched vs estimated, review count thresholds
  - Acceptance: All classifiers tested with boundary and edge cases

- [ ] 🟥 **Step 18: Integration tests for scoring function confidence**
  - Files: `tests/test_property_evaluator.py` (extend existing)
  - For each scoring function, verify confidence is set on the returned Tier2Score
  - For error/exception paths, verify confidence is LOW with appropriate note
  - Acceptance: Each scoring function has at least one confidence assertion

- [ ] 🟥 **Step 19: Serialization round-trip test**
  - Files: `tests/test_app_helpers.py` or `tests/test_service_errors.py`
  - Verify `result_to_dict()` includes confidence fields in serialized tier2_scores
  - Verify old snapshot dicts (missing confidence) render without errors
  - Acceptance: Round-trip test passes; backward compat confirmed

## Testing Checklist
- [ ] Unit tests for all 4 confidence classifiers (places, transit, parks, cost)
- [ ] Each scoring function returns non-None confidence for happy path
- [ ] Each scoring function returns LOW confidence for error/empty paths
- [ ] `result_to_dict()` serializes confidence correctly
- [ ] Old snapshots render without errors (missing confidence fields)
- [ ] Template renders badges for MEDIUM/LOW, hides for HIGH
- [ ] Visual QA: badges look correct on desktop and mobile
- [ ] Existing test suite passes with no regressions

## What NOT to Change
- Scoring logic / actual score values — confidence is metadata only
- Sidewalk coverage confidence — already implemented, leave as-is
- Green space `is_estimate` flags — keep as-is, these feed into the new parks confidence classifier
- Road noise / emergency services / libraries / pharmacies — these are informational sections without scores, not part of the dimension confidence system

## Files Modified Summary
| File | Changes |
|------|---------|
| `property_evaluator.py` | Add confidence fields to `Tier2Score`; 4 classifier functions; wire into 6 scoring functions |
| `scoring_config.py` | Add `data_confidence` + `data_confidence_note` to `DimensionResult` |
| `app.py` | Extend `result_to_dict()` serialization; add aggregate confidence |
| `templates/_result_sections.html` | Confidence badges on dimension summaries + verdict card |
| `static/css/report.css` | Confidence badge styles |
| `tests/test_data_confidence.py` | New: classifier unit tests |
| `tests/test_property_evaluator.py` | Extend: confidence assertions on scoring functions |
| `tests/test_app_helpers.py` | Extend: serialization round-trip |
