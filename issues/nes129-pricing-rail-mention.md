# NES-129: Add rail to pricing health & safety feature line

**Type:** improvement | **Priority:** low | **Effort:** small

## TL;DR

The landing page "Proximity & Safety" card mentions "rail corridors" but the pricing page's corresponding feature line says "highways, gas stations, roads" — omitting rail. Minor copy inconsistency.

## Current State

- **Landing card:** "Distance from highways, gas stations, high-traffic roads, and rail corridors."
- **Pricing feature:** "Health & safety screening (highways, gas stations, roads)"

## Expected Outcome

Pricing feature line includes rail for consistency, e.g.:
"Health & safety screening (highways, gas stations, roads, rail)"

## Relevant Files

- `templates/pricing.html` — pricing feature list (line 41)
- `templates/index.html` — landing page card (line 125) — reference only

## Notes

- Flagged during NES-127 peer review as optional follow-up
- The pricing list is intentionally abbreviated, so this is cosmetic
- Low priority — can bundle with any future copy pass
