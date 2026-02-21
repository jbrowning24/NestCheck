# NES-126: Landing Page Real Evaluation Preview — Status Report

## Files Changed

| File | Changes |
|------|---------|
| `app.py` | Lines 188–189: Added `LANDING_PREVIEW_SNAPSHOT_ID`. Lines 913–948: Added `_backfill_result()`. Lines 1565–1568: Refactored `view_snapshot()` to call `_backfill_result()`. Lines 1248–1258: Added preview loading block in `index()`. All `render_template("index.html", ...)` calls: Added `preview_result` and `preview_snapshot_id` (approx. 12 call sites). |
| `templates/_verdict_preview.html` | **New file** — verdict card partial for landing preview. |
| `templates/index.html` | Lines 113–145: Replaced `.features` block with `{% if preview_result %}...{% include '_verdict_preview.html' %}...{% else %}...<div class="features">...{% endif %}`. |
| `static/css/index.css` | Lines 151–178: Added `.landing-preview`, `.landing-preview-label`, `.landing-preview-cta` styles. |

## Functions Added/Modified

- **Added:** `_backfill_result(result)` — Applies standard backfills (score_band, dimension_summaries, presented_checks, structured_summary, insights) to a snapshot result dict. Mutates in place.
- **Modified:** `view_snapshot()` — Replaced inline backfill block with `_backfill_result(result)`.
- **Modified:** `index()` — Added preview loading when `result is None` and `LANDING_PREVIEW_SNAPSHOT_ID` is set; passes `preview_result` and `preview_snapshot_id` to all index template renders.

## view_snapshot() Behavior

Behavior is unchanged. The previous inline backfill logic was moved into `_backfill_result()` and is invoked in the same way. Snapshot view tests pass.

## Verdict Preview vs _result_sections.html

The verdict card markup in `_verdict_preview.html` matches `_result_sections.html` lines 11–67, with these differences:

- Uses `preview_result` instead of `result` for all variable references.
- Uses `show_preview_score` instead of `show_score` (same logic).
- Wraps the verdict card in `.landing-preview` and adds `.landing-preview-label` ("Example Evaluation") and `.landing-preview-cta` ("See the full report →").
- Does not include the surrounding `<div class="report">` from `_result_sections.html`; the verdict card is inside a local `<div class="report">` for layout.

CSS classes on the verdict card itself (`.verdict-card`, `.score-ring-container`, `.dimension-list`, `.verdict-proximity-flags`, etc.) are unchanged so `report.css` styles apply.

## What Was NOT Tested

- Missing or invalid `LANDING_PREVIEW_SNAPSHOT_ID` (e.g. snapshot deleted, ID typo) — expected: fallback to feature cards; exception is caught and logged.
- Preview with a snapshot that lacks `tier1_checks` or other optional fields — backfill should handle missing data.
- Visual layout of the preview at different viewport sizes.
- `increment_view_count` is not called for the preview (correct; only `view_snapshot()` does that).
