# Implementation Plan: Composite Score Dimension Annotation (NES-394)

**Progress:** [=========-] 90%
**Created:** 2026-04-01
**Linear:** NES-394

## TL;DR

When dimensions are excluded from the composite score (not_scored or suppressed), the verdict card silently omits them. Add a visible annotation below the verdict badge: "Score based on N of 6 dimensions — [dimension] data was unavailable." Pure display-layer change; scoring math is already correct.

## Critical Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Exclusion types | Both `not_scored` AND `suppressed` | Both exclude from composite — user doesn't care why, just *that* |
| Placement | Below verdict badge, above scoring key | Footnote to the score, not a headline |
| Multiple dimensions | List all by name | Max 6 dims, realistically ≤2-3 excluded. Names are the useful signal |
| M value | Derive from `len(TIER2_NAME_TO_DIMENSION)` | Only 6 dims exist; adding a 7th auto-updates |
| Scoring key | No changes | Acceptance criteria satisfied by verdict annotation alone |

## Tasks

### Phase 1: Backend — Capture Excluded Dimensions

- [x] 🟩 **Task 1.1: Add `TIER2_DIMENSION_COUNT` constant to `scoring_config.py`**
  - Files: `scoring_config.py`
  - Added `TIER2_DIMENSION_COUNT = len(TIER2_NAME_TO_DIMENSION)` after the dict
  - Acceptance: Constant exists, imported in `app.py` ✓

- [x] 🟩 **Task 1.2: Build `excluded_dimensions` list in `result_to_dict()`**
  - Files: `app.py` (lines ~2628-2680)
  - Extended confidence summary loop to capture `points is None` (suppressed) dims
  - Added `excluded_dimensions`, `scored_dimension_count`, `total_dimension_count` to `data_confidence_summary`
  - Acceptance: Fields populated correctly ✓

- [x] 🟩 **Task 1.3: Propagate to `_prepare_snapshot_for_display()` migration path**
  - Files: `app.py` (lines ~2334-2349)
  - Backfill runs after `_migrate_confidence_tiers()` so confidence values are normalized
  - Scans `tier2_scores` for `points=None` or `data_confidence="not_scored"`
  - Acceptance: Old snapshots get correct annotation ✓

### Phase 2: Template — Render the Annotation

- [x] 🟩 **Task 2.1: Add annotation block to `_result_sections.html`**
  - Files: `templates/_result_sections.html` (after verdict badge, before scoring key)
  - Correct grammar for 1 dim ("was") vs 2+ ("were"), Oxford comma for 3+
  - Style: `.verdict-dimension-note` — `--type-detail`, `--color-text-muted`, centered
  - Acceptance: Annotation visible below verdict badge when dims excluded ✓

- [x] 🟩 **Task 2.2: Add annotation to sidebar verdict card**
  - Files: `templates/_result_sections.html` (sidebar section)
  - Compact version: "Based on N of 6 dimensions"
  - Style: `.sidebar-dimension-note` — `--type-caption`, `--color-text-faint`
  - Acceptance: Sidebar card shows annotation when dims excluded ✓

### Phase 3: Verification

- [ ] 🟨 **Task 3.1: Test with real evaluation**
  - Evaluate an address known to produce a suppressed or not_scored dimension
  - Verify annotation appears in both main verdict and sidebar
  - Verify annotation is absent on a clean 6-of-6 evaluation

- [ ] 🟨 **Task 3.2: Test snapshot backward compatibility**
  - Load an existing pre-NES-394 snapshot via `/s/{id}`
  - Verify backfill produces correct annotation (or no annotation if all dims scored)

- [x] 🟩 **Task 3.3: Smoke test + scoring tests**
  - `make test-scoring` — 162 passed ✓
  - `app.py` imports cleanly ✓

## Testing Checklist

- [x] `make test-scoring` passes (162/162)
- [ ] New annotation appears for eval with excluded dimensions
- [ ] Annotation hidden for eval with all 6 dimensions scored
- [ ] Old snapshots render correctly (backfill works)
- [ ] Grammar correct for 1 excluded dim vs. 2+ excluded dims
- [ ] Mobile rendering: annotation doesn't overflow or break layout
