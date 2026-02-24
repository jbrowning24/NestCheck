# NES-11: Replace Green Space PASS/FAIL Badges with Distance-Based Labels

**Overall Progress:** `100%`

## TLDR
The "Other nearby green spaces" list in the Parks & Green Space section shows PASS/FAIL/BORDERLINE badges based on internal scoring criteria. These are meaningless to users. Replace them with distance-based labels (e.g. "Very Close", "Walkable", "Moderate", "Drive") derived from `walk_time_min` / `drive_time_min` data that already exists on each green space.

## Critical Decisions
- **Template-only change**: The `criteria_status` field stays in the backend (still used by `score_park_access` details and best-daily-park logic). We only change what the nearby list *displays*.
- **Label thresholds based on existing constants**: Use the same walk-time tiers already defined in `green_space.py` (`WALK_TIME_EXCELLENT=10`, `WALK_TIME_GOOD=20`, `WALK_TIME_MARGINAL=30`) to derive labels.
- **Reuse existing badge CSS classes**: Map distance labels to existing badge styles (`badge-pass` → green, `badge-borderline` → orange, `badge-fail` → red) rather than creating new CSS.

## Distance Label Mapping

| Walk Time       | Condition                          | Label        | Badge Style       |
|----------------|------------------------------------|--------------|-------------------|
| ≤ 10 min       | —                                  | Very Close   | `badge-pass` (green)  |
| 11–20 min      | —                                  | Walkable     | `badge-pass` (green)  |
| 21–30 min      | —                                  | Moderate     | `badge-borderline` (orange) |
| > 30 min       | —                                  | Drive Only   | `badge-fail` (red)    |

## Tasks

- [x] 🟩 **Step 1: Update nearby list badge in template**
  - [x] 🟩 Replace the `criteria_status` badge on line 280 of `_result_sections.html` with distance-based label using `space.walk_time_min`
  - [x] 🟩 Use Jinja conditionals to select label text and badge class per the mapping above

- [x] 🟩 **Step 2: Verify and test**
  - [x] 🟩 Confirmed only one template reference to `criteria_status` for the nearby list (line 280)
  - [x] 🟩 Backend `criteria_status` untouched — still used in `green_space.py`, `property_evaluator.py`, `app.py`, and tests
