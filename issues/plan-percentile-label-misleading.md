# NES-14: Remove Misleading Percentile Label

**Overall Progress:** `100%` · **Status:** Complete
**Last updated:** 2026-02-09

## TLDR
Remove the leftover `estimate_percentile()` function and `percentile_top`/`percentile_label` fields from `property_evaluator.py`. Phase 5 already replaced percentile with score bands in the web UI — this cleans up the dead code still living in the evaluator and CLI output.

## Critical Decisions
- **No new band logic in property_evaluator.py:** The CLI `format_result()` will import `get_score_band()` from `app.py` rather than duplicating the band table — single source of truth
- **CLI JSON output updated:** Replace `percentile_top`/`percentile_label` keys with `score_band` string so any downstream consumers get the correct label

## Tasks:

- [x] 🟩 **Step 1: Remove percentile from EvaluationResult** (`property_evaluator.py`)
  - [x] 🟩 Delete `percentile_top` and `percentile_label` fields from the dataclass (~line 584-585)
  - [x] 🟩 Delete the `estimate_percentile()` function (~line 2891-2908)
  - [x] 🟩 Delete the call `result.percentile_top, result.percentile_label = estimate_percentile(...)` (~line 3231)

- [x] 🟩 **Step 2: Update CLI output** (`property_evaluator.py`)
  - [x] 🟩 In `format_result()`, replace `result.percentile_label` reference (~line 3306) with score band from `app.get_score_band()`
  - [x] 🟩 In CLI JSON block (~line 3506-3507), replace `percentile_top`/`percentile_label` with `score_band`

- [x] 🟩 **Step 3: Verify no other references remain**
  - [x] 🟩 Grep for any remaining `percentile_top`, `percentile_label`, or `estimate_percentile` references across the codebase
  - [x] 🟩 Confirm templates and app.py have no lingering percentile usage

## Files Modified
| File | Changes |
|------|---------|
| `property_evaluator.py` | Remove `estimate_percentile()`, remove dataclass fields, update `format_result()` and CLI JSON output |
