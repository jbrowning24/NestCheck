# EJScreen Integration Plan

> Wire EPA EJScreen block group data into evaluation pipeline: 6 Tier 1 checks + Environmental Profile card. Zero new API calls.

**Progress: 100%**

---

## Phase 0: Fix Ingestion Bug
- [x] 🟩 Fix ACSTOTPOP bug in `_get_indicator_fields()` (ingest_ejscreen.py)

## Phase 1: Data Access Layer
- [x] 🟩 Add `EJSCREEN_INDICATOR_FIELDS` mapping to property_evaluator.py
- [x] 🟩 Add `_query_ejscreen_block_group(lat, lng)` function
- [x] 🟩 Add `ejscreen_profile` field to `EvaluationResult`

## Phase 2: Evaluation Logic — 6 Check Indicators
- [x] 🟩 Add `_EJSCREEN_CHECK_INDICATORS` config
- [x] 🟩 Add `_check_ejscreen_indicators()` function
- [x] 🟩 Wire into `evaluate_property()` after SEMS check with Superfund dedup
- [x] 🟩 Register 6 checks in app.py: `_SAFETY_CHECK_NAMES`, `_CHECK_SOURCE_GROUP`, `_SOURCE_GROUP_LABELS`, `_CLEAR_HEADLINES`, `_ISSUE_HEADLINES`, `_WARNING_HEADLINES`

## Phase 3: Environmental Profile Card
- [x] 🟩 Serialize `ejscreen_profile` in `result_to_dict()`
- [x] 🟩 Add EPA Environmental Profile card to `_result_sections.html`
- [x] 🟩 Add CSS styles for `.ejscreen-*` classes in `report.css`

## Files Modified
| File | Changes |
|------|---------|
| `scripts/ingest_ejscreen.py` | Removed ACSTOTPOP from PM2.5 field candidates |
| `property_evaluator.py` | Added `_query_ejscreen_block_group()`, `_check_ejscreen_indicators()`, `EJSCREEN_INDICATOR_FIELDS`, `_EJSCREEN_CHECK_INDICATORS`, `ejscreen_profile` on `EvaluationResult`, wired into `evaluate_property()` |
| `app.py` | Registered 6 EJScreen checks in all presentation dicts, serialized `ejscreen_profile` in `result_to_dict()` |
| `templates/_result_sections.html` | Added EPA Environmental Profile card with collapsible indicators |
| `static/css/report.css` | Added `.ejscreen-*` styles |

## Notes
- EJScreen checks use `required=False` — they produce WARNING (not FAIL), so they don't block Tier 1 pass.
- Superfund dedup: `EJScreen Superfund` check is suppressed when SEMS containment already FAILed.
- 12 of 13 EPA indicators are supported; Extreme Heat and Drinking Water require an ingestion update (Phase 4 follow-up).
- Template card uses `{% if result.ejscreen_profile is defined and result.ejscreen_profile %}` guard for backward compat with old snapshots.
