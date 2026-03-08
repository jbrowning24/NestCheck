# Plan: Confidence Tiers & Citation Links

**Issue**: Phase 3 — Replace ad-hoc uncertainty language with unified three-tier confidence system. Add hyperlinked citations to health check "Why we check this" expandables.

**Status**: Planning

---

## Current State Analysis

### Existing confidence system (NES-189)
- `Tier2Score` dataclass already has `data_confidence` (HIGH/MEDIUM/LOW) and `data_confidence_note` fields
- `DimensionResult` (scoring_config.py) also has these fields
- `_apply_confidence_cap()` caps scores: LOW→6, MEDIUM→8, HIGH→uncapped
- Template renders badges: HIGH=hidden, MEDIUM="Limited data", LOW="Sparse data"
- `data_confidence_summary` aggregates weakest-link across dimensions

### Road noise (score_road_noise)
- When `road_noise_assessment is None`: returns 7/10 with "benefit of the doubt" detail, data_confidence="LOW"
- When assessment exists: maps dBA through piecewise curve, data_confidence="HIGH"

### Ad-hoc language instances found
1. `property_evaluator.py:4367` — `"Road noise data unavailable — benefit of the doubt"` (road noise None case)
2. `property_evaluator.py:3906` — Comment `"sparse data — cap at 6/10"` (comment only, not user-facing)
3. `templates/_result_sections.html:103` — `{% if dim.data_confidence == 'MEDIUM' %}Limited data{% else %}Sparse data{% endif %}`

### Health context / "Why we check this"
- `_HEALTH_CONTEXT` dict in app.py maps `(check_name, result_category)` to paragraph dicts
- `_build_health_context()` extracts paragraphs in stable order: why, regulatory, exposure, who, distance, invisible, nuance, practical
- Template renders as collapsible with `{% for paragraph in pc.health_context %}`
- Citations are currently inline text (e.g., "Hilpert et al.") but NOT hyperlinked

### Composite score calculation
- `result.tier2_total = sum(s.points for s in result.tier2_scores)` — simple sum
- Weighted: `sum(s.points * weight for s in tier2_scores)` / `sum(s.max_points * weight)`
- If a dimension has `points=None`, this would crash. Currently all dimensions always have integer points.

### Serialization paths for tier2_scores
1. `result_to_dict()` (app.py:1550): serializes name, points, max, details, data_confidence, data_confidence_note
2. Compare route (app.py:398): reads `s["points"]` from deserialized snapshot
3. CSV export (app.py:2633): exports data_confidence and data_confidence_note
4. CLI JSON output (property_evaluator.py:5692): only name, points, max, details

---

## Implementation Plan

### Step 1: Map confidence tiers to existing data_confidence field

The task defines three tiers: **Verified** (no badge), **Estimated** (badge), **Not scored** (suppress score). The existing system uses HIGH/MEDIUM/LOW. The mapping:

| New Tier | Old Level | Badge | Score behavior |
|----------|-----------|-------|----------------|
| Verified | HIGH | None (hidden) | Show score normally |
| Estimated | MEDIUM | "Estimated" | Show score + one-line explanation |
| Not scored | LOW (special) | "Not scored" | Suppress numeric score, show what we know |

**Key insight**: We don't need a new field. We can evolve the existing `data_confidence` values:
- HIGH → "verified" (no badge, same as today)
- MEDIUM → "estimated" (badge text changes from "Limited data" to "Estimated")
- But "Not scored" is new — it means `points=None`. Currently LOW still shows a numeric score (capped at 6). The task says "Not scored" should suppress the numeric score entirely.

**Decision**: Add a new confidence tier value. Change from HIGH/MEDIUM/LOW to a clearer enum-like string system:
- `"verified"` — replaces HIGH
- `"estimated"` — replaces MEDIUM
- `"not_scored"` — new, replaces LOW for cases where we truly can't score (road noise with no data)
- Keep LOW as a backward-compat alias for "estimated" in deserialization

**Files**: `property_evaluator.py` (Tier2Score, _apply_confidence_cap, _classify_places_confidence, all scoring functions), `scoring_config.py` (DimensionResult)

### Step 2: Update road noise to return not_scored when no data

Change `score_road_noise()` when `road_noise_assessment is None`:
- Return `Tier2Score(name="Road Noise", points=0, max_points=10, data_confidence="not_scored", data_confidence_note="No road data available from OpenStreetMap — unable to estimate noise exposure", details="Road noise data unavailable")`
- Points=0 with max_points=10 but the dimension should be EXCLUDED from composite scoring (not treated as zero)

**Files**: `property_evaluator.py`

### Step 3: Handle not_scored dimensions in composite calculation

Modify the composite score calculation (property_evaluator.py ~line 5278-5295) to exclude dimensions with `data_confidence == "not_scored"` from both the sum and the max:

```python
_scorable = [s for s in result.tier2_scores if getattr(s, 'data_confidence', None) != 'not_scored']
result.tier2_total = sum(s.points for s in _scorable)
result.tier2_max = sum(s.max_points for s in _scorable)
# weighted calc also filters
```

This way, a missing road noise dimension doesn't inflate or deflate the score — it's simply excluded.

**Files**: `property_evaluator.py`

### Step 4: Update confidence_cap and classification functions

- Update `_CONFIDENCE_SCORE_CAP` to use new tier names
- Update `_classify_places_confidence()` to return new tier names
- Update all scoring functions that set data_confidence to use new tier names
- Add backward-compat handling in deserialization

**Files**: `property_evaluator.py`

### Step 5: Add backward-compat migration for old snapshots

In `view_snapshot()`, `export_snapshot_json()`, `export_snapshot_csv()`, and compare route — add migration for old HIGH/MEDIUM/LOW values to new tier names. Similar to `_migrate_dimension_names()`.

**Files**: `app.py`

### Step 6: Update template badge rendering

Change `_result_sections.html` line 101-104:
- `data_confidence == 'estimated'` → show "Estimated" badge
- `data_confidence == 'not_scored'` → show "Not scored" badge, suppress numeric score
- `data_confidence == 'verified'` or absent → no badge (current behavior for HIGH)

Also handle backward-compat: LOW→not_scored display, MEDIUM→estimated display.

**Files**: `templates/_result_sections.html`

### Step 7: Add HEALTH_CHECK_CITATIONS to scoring_config.py

Add a dict mapping check names to citation lists:

```python
HEALTH_CHECK_CITATIONS = {
    "Gas station": [
        {"label": "Hilpert et al. 2019", "url": "https://doi.org/10.1016/j.scitotenv.2019.05.316"},
        {"label": "IARC Monograph 100F (Benzene)", "url": "https://publications.iarc.fr/123"},
    ],
    "Highway": [
        {"label": "HEI Panel on Traffic-Related Air Pollution, 2010", "url": "https://www.healtheffects.org/publication/traffic-related-air-pollution-critical-review-literature"},
    ],
    # ... more checks
}
```

**Files**: `scoring_config.py`

### Step 8: Attach citations in present_checks()

Modify `present_checks()` in app.py to attach citations from `HEALTH_CHECK_CITATIONS` to each check's presentation dict:

```python
from scoring_config import HEALTH_CHECK_CITATIONS
# in present_checks():
citations = HEALTH_CHECK_CITATIONS.get(name, [])
presented.append({
    ...existing fields...,
    "citations": citations,
})
```

**Files**: `app.py`

### Step 9: Render citation links in template

In `_result_sections.html`, after the health_context paragraphs inside the "Why we check this" collapsible, render citations as hyperlinks:

```html
{% if pc.citations %}
<div class="health-citations">
  <span class="health-citations-label">Sources:</span>
  {% for cite in pc.citations %}
    <a href="{{ cite.url }}" target="_blank" rel="noopener" class="health-citation-link">{{ cite.label }}</a>{% if not loop.last %}, {% endif %}
  {% endfor %}
</div>
{% endif %}
```

**Files**: `templates/_result_sections.html`, `static/report.css`

### Step 10: Remove all ad-hoc uncertainty language

1. `property_evaluator.py:4367` — Replace "benefit of the doubt" with proper not_scored tier (done in Step 2)
2. `templates/_result_sections.html:103` — Replace "Sparse data"/"Limited data" with "Estimated"/"Not scored" (done in Step 6)
3. Any remaining "sparse data" or "benefit of the doubt" user-facing strings

### Step 11: Update serialization paths

Ensure all three serialization paths include the new confidence tier values:
1. `result_to_dict()` — already serializes data_confidence (no change needed, just new values)
2. Compare route — reads tier2_scores from snapshots (add migration)
3. CSV export — already exports data_confidence (no change needed)
4. CLI JSON output — add data_confidence to the dict

**Files**: `property_evaluator.py`, `app.py`

### Step 12: Update tests

- Update `test_road_noise.py` / `test_data_confidence.py` for new tier names
- Add test for composite score excluding not_scored dimensions
- Add test for citation attachment in present_checks

**Files**: `tests/test_data_confidence.py`, `tests/test_road_noise.py`, `tests/test_property_evaluator.py`

---

## Risk Mitigation

1. **Composite score with missing dimensions**: Excluding not_scored dimensions changes the denominator. If Road Noise is not_scored, the max drops from 60 to 50, so the percentage is calculated from 5 dimensions instead of 6. This is correct — we're not inflating with fake data.

2. **Old snapshots**: The backward-compat migration ensures old HIGH/MEDIUM/LOW values display correctly. Add `_migrate_confidence_tiers()` similar to `_migrate_dimension_names()`.

3. **Persona weights**: When a dimension is not_scored, its weight is excluded from both numerator and denominator in the weighted calculation, so persona weights still work correctly.

---

## Files Changed Summary

| File | Changes |
|------|---------|
| `property_evaluator.py` | Tier2Score confidence values, score_road_noise not_scored, composite calc exclusion, _apply_confidence_cap update, CLI JSON export |
| `scoring_config.py` | HEALTH_CHECK_CITATIONS dict, DimensionResult confidence values |
| `app.py` | present_checks() citations, _migrate_confidence_tiers(), backward compat |
| `templates/_result_sections.html` | Badge text, not_scored display, citation links |
| `static/report.css` | Citation link styles |
| `tests/test_data_confidence.py` | Updated tier names |
| `tests/test_road_noise.py` | Not_scored test case |
