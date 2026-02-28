# NES-189: Implement Systematic Data Confidence Indicators Across Dimensions

## Exploration Summary

### What the Issue Asks For
From the PRD and issue title: Every dimension score should include explicit data confidence indicators showing users where the assessment is based on rich data versus sparse data. A score for a property with dense Google Places coverage, many reviews, and OSM enrichment is categorically different from a score in a data-sparse area — NestCheck should communicate this honestly rather than generating uniform-looking scores of varying reliability.

---

## Current State

### Existing Confidence Mechanisms
1. **Sidewalk Coverage** (`sidewalk_coverage.py`): Has a full `data_confidence` system (HIGH/MEDIUM/LOW) based on what fraction of road segments have OSM sidewalk tags. Displayed in the template with color-coded text. This is the **gold standard pattern** to replicate across dimensions.

2. **Green Space Subscores** (`green_space.py`): `DailyWalkSubscore.is_estimate` flag indicates when acreage is estimated vs. measured from OSM. Shown with "(est)" label in the template.

3. **Tier 1 Check Result Types**: CLEAR / CONFIRMED_ISSUE / WARNING_DETECTED / VERIFICATION_NEEDED — the last one indicates data-source uncertainty, but this isn't a confidence score per se.

### What's Missing (No Confidence Indicators)
- **Coffee & Social Spots** — no indication of how many cafes were searched vs. found
- **Daily Essentials (Grocery)** — no indication of search completeness
- **Fitness & Recreation** — no indication of search completeness
- **Parks & Green Space (dimension score)** — park subscore has `is_estimate` but the overall dimension score has no aggregate confidence
- **Getting Around (Transit)** — no indication of OSM data density confidence
- **Road Noise** — no indication when estimation is based on sparse road data
- **Cost** — no indication that "cost not specified" means 0 confidence
- **Overall score** — no aggregate confidence indicator

---

## Architecture Analysis

### How Dimensions are Scored (data flow)
1. `evaluate_property()` in `property_evaluator.py` runs all stages
2. Each scoring function returns a `Tier2Score(name, points, max_points, details)` or `DimensionResult` (richer type with `scoring_inputs` and `subscores`)
3. `result_to_dict()` in `app.py` serializes the `EvaluationResult` to a plain dict
4. The dict is stored as JSON in the `snapshots` table
5. On render, `view_snapshot()` loads the dict and backfills missing fields
6. Template `_result_sections.html` renders using `result.*` fields

### Key Files to Modify

| File | Purpose | Changes Needed |
|------|---------|----------------|
| `property_evaluator.py` | Scoring functions | Add confidence metadata to each scoring function's return |
| `scoring_config.py` | Scoring model config | Add `ConfidenceLevel` enum and confidence thresholds |
| `app.py` | Serialization + rendering | Serialize confidence data in `result_to_dict()`, backfill in `view_snapshot()` |
| `templates/_result_sections.html` | Result display | Show confidence indicators per dimension |
| `static/css/report.css` | Styling | Add confidence indicator CSS |

### Confidence Signal Sources Per Dimension

| Dimension | Confidence Signals | High | Medium | Low |
|-----------|-------------------|------|--------|-----|
| **Coffee / Third Place** | # eligible places found, best rating review count | ≥3 places, ≥100 reviews on best | 1-2 places, ≥30 reviews | 0 places or <30 reviews |
| **Grocery / Provisioning** | # eligible stores found, best rating review count | ≥2 stores, ≥200 reviews on best | 1 store, ≥50 reviews | 0 stores or <50 reviews |
| **Fitness** | # eligible facilities found, best rating review count | ≥2 facilities, ≥50 reviews | 1 facility, ≥20 reviews | 0 facilities or <20 reviews |
| **Parks / Green Space** | Whether OSM enrichment succeeded, review count, whether acreage is estimated | OSM enriched, ≥100 reviews, measured area | Partial data (some estimates) | No OSM data, no reviews, all estimated |
| **Transit / Getting Around** | OSM node density, whether walk time was computed, frequency bucket source | Walk time computed, frequency from schedule data | Walk time computed, frequency approximated | Walk time missing, no frequency data |
| **Road Noise** | # roads found, distance to nearest road | ≥3 roads within radius, nearest < 500ft | 1-2 roads found | No roads found (returns None) |
| **Cost** | Whether cost was user-provided | Cost provided | N/A | Cost not specified |

### Existing Pattern to Follow (Sidewalk Coverage)

```python
# sidewalk_coverage.py — the existing pattern
@dataclass
class SidewalkCoverageResult:
    ...
    data_confidence: str            # "HIGH" / "MEDIUM" / "LOW"
    data_confidence_note: str       # explanation of confidence level
    methodology_note: str           # static methodology text

def _classify_confidence(roads_with_sidewalk, roads_without_sidewalk, total) -> tuple:
    """Returns (confidence_level, confidence_note) tuple."""
    if total == 0:
        return "LOW", "No road segments found"
    tagged_fraction = (roads_with_sidewalk + roads_without_sidewalk) / total
    if tagged_fraction >= CONFIDENCE_HIGH_THRESHOLD:
        return "HIGH", f"{tagged_fraction:.0%} of roads have sidewalk tags"
    elif tagged_fraction >= CONFIDENCE_MEDIUM_THRESHOLD:
        return "MEDIUM", f"Only {tagged_fraction:.0%} of roads have sidewalk tags"
    else:
        return "LOW", f"Only {tagged_fraction:.0%} of roads have sidewalk tags"
```

Template rendering:
```html
<div class="proximity-detail sidewalk-confidence sidewalk-confidence-{{ sc.data_confidence|lower }}">
  Data confidence: {{ sc.data_confidence }} — {{ sc.data_confidence_note }}
</div>
```

CSS:
```css
.sidewalk-confidence-high { color: var(--color-pass-text); }
.sidewalk-confidence-medium { color: var(--color-warning-text); }
.sidewalk-confidence-low { color: var(--color-danger); }
```

---

## Implementation Approach

### Option A: Per-Dimension Confidence in Scoring Functions (Recommended)
Each scoring function computes and returns a `data_confidence` field alongside the score. This is the most accurate because the scoring function has direct access to search result counts, review counts, and data quality signals.

**Pros:** Most accurate, co-located with scoring logic, follows existing sidewalk pattern
**Cons:** Touches many scoring functions, needs `Tier2Score` or serialization changes

### Option B: Post-Hoc Confidence in `result_to_dict()`
Compute confidence from the serialized result dict by inspecting neighborhood_places counts, review counts, etc.

**Pros:** Single location for all confidence logic, no scoring function changes
**Cons:** Less accurate (loses intermediate data), more fragile (depends on serialization format)

### Option C: Confidence as a Separate Module
A `data_confidence.py` module that takes the full `EvaluationResult` and returns per-dimension confidence.

**Pros:** Clean separation, testable
**Cons:** Needs access to raw evaluation data, adds another module

**Recommendation:** **Option A** — follows the existing sidewalk pattern, most accurate signals, and co-locates confidence with the code that knows the data best.

### UI Design Approach
- **Dimension summary row** (verdict card): Add a small confidence badge next to each dimension score (e.g., colored dot or text like "High confidence" / "Limited data")
- **Neighborhood place cards**: Optional confidence note when data is sparse
- **Overall score**: Aggregate confidence indicator considering all dimensions

### Backward Compatibility
- Old snapshots won't have `data_confidence` fields — template guards with `is defined` checks (existing pattern)
- Can optionally backfill in `view_snapshot()` using post-hoc analysis on stored data

---

## Risks & Considerations

1. **User confusion**: Need clear, simple language. "HIGH/MEDIUM/LOW" works for sidewalk but may be too technical for dimension confidence. Consider "Strong data" / "Limited data" / "Sparse data" or icon-based indicators.

2. **Score trust erosion**: Showing "LOW confidence" on a dimension might make users distrust the entire evaluation. Need to frame it as transparency, not uncertainty.

3. **Performance**: Confidence classification should be pure computation on already-available data. No additional API calls.

4. **Testing**: Each confidence classifier needs unit tests. The sidewalk module has good test coverage in `tests/test_sidewalk.py` — replicate that pattern.

5. **Snapshot size**: Adding ~6 confidence objects to the result JSON is minimal overhead.

---

## Estimated Scope

| Component | Effort |
|-----------|--------|
| `scoring_config.py`: ConfidenceLevel enum + thresholds | Small |
| `property_evaluator.py`: Confidence in 6 scoring functions | Medium |
| `app.py`: Serialize + backfill confidence | Small |
| `templates/_result_sections.html`: Display indicators | Medium |
| `static/css/report.css`: Confidence indicator styles | Small |
| Tests: Unit tests for confidence classifiers | Medium |
| **Total** | **Medium-Large** |

## Files Referenced
- `property_evaluator.py:3134-3728` — Tier 2 scoring functions
- `property_evaluator.py:182-186` — Tier2Score dataclass
- `scoring_config.py:70-98` — DimensionResult dataclass
- `app.py:892-985` — result_to_dict serialization
- `app.py:1185-1225` — view_snapshot backfill
- `sidewalk_coverage.py:196-282` — Existing confidence pattern
- `templates/_result_sections.html:79-100` — Dimension summary display
- `static/css/report.css:378-385` — Existing confidence CSS
