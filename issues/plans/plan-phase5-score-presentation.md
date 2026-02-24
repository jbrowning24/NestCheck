# Phase 5: AQI-Style Score Presentation

**Overall Progress:** `100%`

## TLDR
Replace vague verdict strings, misleading percentiles, and hidden subscores with named score bands, plain-English dimension summaries, and a transparent methodology section — all visible without clicking anything.

## Critical Decisions
- **Score bands in app.py, not template:** Band logic lives in `get_score_band()` so both new evaluations and old snapshots can compute it
- **Dimension summaries from serialized dict:** `generate_dimension_summaries()` reads from the result dict (not raw objects), ensuring it works for snapshots with graceful fallbacks for missing data
- **Percentile removal:** Remove percentile entirely (no conditional display) — it was misleading at all score levels and the band name now communicates the same information more clearly
- **Snapshot backward compat via route-level patching:** The `/s/<snapshot_id>` route loads raw dicts from DB; we add `score_band` computation there since `result_to_dict()` only handles live `EvaluationResult` objects

## Data Available for Dimension Summaries
From the serialized result dict:
- **Parks:** `green_escape.best_park.name`, `.walk_time_min`
- **Coffee:** `neighborhood_places.coffee[]` — each has `name`, `walk_time_min`
- **Grocery:** `neighborhood_places.grocery[]` — same structure
- **Fitness:** `neighborhood_places.fitness[]` — same structure
- **Transit:** `urban_access.primary_transit.name`, `.walk_time_min`, `.frequency_class`; also `transit_access.primary_stop`, `.walk_minutes`, `.frequency_bucket`
- **Tier2 scores:** `tier2_scores[]` — each has `name`, `points`, `max`, `details`

## Tasks:

- [ ] 🟥 **Step 1: Add score band constant and helper** (`app.py`)
  - [ ] 🟥 Add `SCORE_BANDS` constant (5 bands: 85/70/55/40/0)
  - [ ] 🟥 Add `get_score_band(score: int) -> str` helper

- [ ] 🟥 **Step 2: Add `generate_dimension_summaries()` function** (`app.py`)
  - [ ] 🟥 Parks & Green Space summary from `green_escape.best_park`
  - [ ] 🟥 Coffee & Social Spots summary from `neighborhood_places.coffee`
  - [ ] 🟥 Daily Essentials summary from `neighborhood_places.grocery`
  - [ ] 🟥 Fitness & Recreation summary from `neighborhood_places.fitness`
  - [ ] 🟥 Getting Around summary from `urban_access.primary_transit` / `transit_access`
  - [ ] 🟥 Each entry: `{name, summary, score, max_score}` — score pulled from matching `tier2_scores[]`

- [ ] 🟥 **Step 3: Update `result_to_dict()` and `generate_verdict()`** (`app.py`)
  - [ ] 🟥 Add `score_band` and `dimension_summaries` to output dict
  - [ ] 🟥 Remove `percentile_top` and `percentile_label` from output
  - [ ] 🟥 Rewrite `generate_verdict()` to use `get_score_band()` + proximity concern suffix

- [ ] 🟥 **Step 4: Patch snapshot route for backward compat** (`app.py`)
  - [ ] 🟥 In `view_snapshot()`, compute `score_band` from `final_score` if missing
  - [ ] 🟥 Attempt `generate_dimension_summaries()` on old snapshot dicts (graceful if data missing)

- [ ] 🟥 **Step 5: Redesign verdict card in template** (`templates/_result_sections.html`)
  - [ ] 🟥 Replace score-circle/verdict/percentile with score-header (number + band + "out of 100")
  - [ ] 🟥 Add dimension-list below score-header with name/summary/score rows
  - [ ] 🟥 Backward compat: fall back to `result.verdict` when `score_band` missing

- [ ] 🟥 **Step 6: Simplify "How We Score" section** (`templates/_result_sections.html`)
  - [ ] 🟥 Replace tier2/tier3 subscore rows with brief explanation paragraph
  - [ ] 🟥 Add score band reference table (5 rows)
  - [ ] 🟥 Add proximity note
  - [ ] 🟥 Remove score bar visualization
  - [ ] 🟥 Keep section collapsed by default

- [ ] 🟥 **Step 7: Add CSS for new verdict card** (`templates/_result_sections.html` or `static/`)
  - [ ] 🟥 `.verdict-card`, `.score-header`, `.score-number`, `.score-band`, `.score-scale`
  - [ ] 🟥 `.dimension-list`, `.dimension-row`, `.dimension-name`, `.dimension-summary`, `.dimension-score`
  - [ ] 🟥 Mobile responsive: stack dimension rows at ≤600px
  - [ ] 🟥 Remove old score-circle, percentile-label CSS

- [ ] 🟥 **Step 8: Verification**
  - [ ] 🟥 Evaluate "75 Holland Place, Hartsdale, NY 10530" — confirm band, summaries, no percentile, score unchanged
  - [ ] 🟥 Evaluate a low-scoring address — confirm appropriate band, no misleading labels
  - [ ] 🟥 Load an old snapshot — confirm fallback to old verdict, no errors

## Files Modified
| File | Changes |
|------|---------|
| `app.py` | `SCORE_BANDS`, `get_score_band()`, `generate_dimension_summaries()`, update `generate_verdict()`, update `result_to_dict()`, patch `view_snapshot()` |
| `templates/_result_sections.html` | Redesign verdict card, simplify "How We Score", add CSS, remove old score bar |

## What NOT to Change
- Scoring logic / score values
- Evaluation pipeline
- "Your Neighborhood" section (Phase 3)
- Map (Phase 4)
- Proximity section (Phase 2)
- No new API calls
