# NES-35: Unit Tests for Insight Generator Functions

**Overall Progress:** `100%`

## TLDR
Add unit tests for all six untested insight pipeline functions in `tests/test_insights.py`. All are pure functions (dict in → string/None out), so no mocking needed — just construct input dicts and assert on output substrings.

## Critical Decisions
- **Single file:** All tests stay in `tests/test_insights.py` alongside existing `_insight_neighborhood` tests
- **Substring assertions:** Follow existing `assertIn` pattern — verify branch routing and key data, not frozen prose
- **Priority order:** `_insight_getting_around` → `_insight_parks` → `generate_insights` → `proximity_synthesis` → `_weather_context` → helpers

## Tasks:

- [x] 🟩 **Step 1: `_insight_getting_around()` tests** (app.py:600-711, 5 branches)
  - [x] 🟩 Strong rail (score ≥7): station name, walk time, freq_label, hub travel time
  - [x] 🟩 Moderate rail (score 4-6): station name, "service runs at" freq, backup option advice
  - [x] 🟩 Weak rail (score <3): "nearest transit option", "driving for most trips"
  - [x] 🟩 Bus-only fallback: stop name, walk_minutes, frequency_bucket; low-score "plan on driving"
  - [x] 🟩 No transit at all: "Transit options are limited"
  - [x] 🟩 Bike score ≥70 adds bike note
  - [x] 🟩 Walk description included when score ≥4, omitted when <4
  - [x] 🟩 Edge case: no urban and no transit → returns None

- [x] 🟩 **Step 2: `_insight_parks()` tests** (app.py:811-880, 5 branches)
  - [x] 🟩 Strong + close (score ≥7, walk ≤15): park name, walk time, "go for a run"
  - [x] 🟩 Good but far (score <7, walk >20): "weekend destination"
  - [x] 🟩 Moderate (score ≥4): "regular visits"
  - [x] 🟩 Weak (score <4): "Green space is limited"
  - [x] 🟩 No park found: "No parks or green spaces were found"
  - [x] 🟩 OSM enrichment: acreage (≥5 acres), trails, path count (≥3)
  - [x] 🟩 Nearby green spaces: 0, 1 ("another green space"), 2+ ("{n} other green spaces")
  - [x] 🟩 Edge case: None/empty green_escape → returns None

- [x] 🟩 **Step 3: `generate_insights()` orchestrator tests** (app.py:883-909)
  - [x] 🟩 Returns dict with all 4 keys (your_neighborhood, getting_around, parks, proximity)
  - [x] 🟩 Empty result_dict → all values None
  - [x] 🟩 Populated result_dict → each key gets a non-None string from its sub-function

- [x] 🟩 **Step 4: `proximity_synthesis()` tests** (property_evaluator.py:541-610, 4 branches)
  - [x] 🟩 All clear: "No environmental concerns"
  - [x] 🟩 Unverified only (1 check): display_name + "could not be verified"
  - [x] 🟩 Unverified only (2 checks): joined names + "could not be verified"
  - [x] 🟩 Unverified only (3 checks): "None of the proximity checks"
  - [x] 🟩 Confirmed only (with clears remaining): "close to {name}. Remaining checks are clear"
  - [x] 🟩 Confirmed only (no clears): "close to {name}." (no remaining note)
  - [x] 🟩 Confirmed + unverified mix: both concern names and unverified names
  - [x] 🟩 No safety checks → returns None

- [x] 🟩 **Step 5: `_weather_context()` tests** (app.py:750-808)
  - [x] 🟩 None/empty weather → returns None
  - [x] 🟩 No triggers → returns None
  - [x] 🟩 Snow + freezing combined: single sentence with month range
  - [x] 🟩 Snow only: "notable snow" + month range
  - [x] 🟩 Freezing only: "freezing temperatures"
  - [x] 🟩 Extreme heat: "Summers are hot" + month range
  - [x] 🟩 Rain (without snow): "frequent rain year-round"
  - [x] 🟩 Rain suppressed when snow present
  - [x] 🟩 Max 2 sentences when multiple triggers fire

- [x] 🟩 **Step 6: Helper function tests** (`_nearest_walk_time`, `_join_labels`)
  - [x] 🟩 `_nearest_walk_time`: list with times → min; empty list → None; None walk_time_min entries skipped
  - [x] 🟩 `_join_labels`: 1 item, 2 items ("and"), 3+ items (Oxford comma), custom conjunction

- [x] 🟩 **Step 7: Run full test suite, verify green**
  - [x] 🟩 All 84 tests pass (18 existing + 66 new) in 0.19s
