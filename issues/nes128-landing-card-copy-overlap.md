# NES-128: Tighten Daily Errands vs Daily Essentials card copy

**Type:** improvement | **Priority:** low | **Effort:** small

## TL;DR

The "Daily Errands" and "Daily Essentials" landing page cards both mention groceries, which may feel redundant to users. Consider tightening copy so the distinction is clearer at a glance.

## Current State

- **Daily Errands:** "Walking distance to grocery stores, pharmacies, and everyday essentials."
- **Daily Essentials:** "Walkable groceries, cafes, fitness — the fabric of daily life."

Both reference groceries. The cards map to distinct backend evaluation categories, so the overlap is intentional — but the user-facing copy could differentiate better.

## Expected Outcome

Each card's copy clearly communicates its unique value without repeating "grocery/groceries."

## Relevant Files

- `templates/index.html` — landing page feature cards (lines 128-134)

## Notes

- Flagged during NES-127 peer review as optional follow-up
- No functional impact — purely copy polish
- Only act on this if users report confusion
