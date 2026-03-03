# EJScreen: Store percentiles and use them for thresholds

**Type:** Tech debt
**Priority:** Medium
**Related:** health_compare.py `check_ejscreen_spatial()`

## Problem

The EJScreen ingest (`scripts/ingest_ejscreen.py`) stores raw EPA indicator values in `metadata_json`. The health comparison's `check_ejscreen_spatial()` uses approximate national 80th-percentile reference thresholds to flag elevated indicators. This is fragile — if stored values have different units or scales than assumed, every EJScreen result will be wrong.

## Fix

1. Modify `ingest_ejscreen.py` to also store the `P_` prefixed percentile columns from the EJScreen ArcGIS service (e.g., `P_PM25`, `P_OZONE`). These are pre-computed national percentiles (0–100).
2. Update `_get_indicator_fields()` field map to store both raw and percentile values with distinct keys (e.g., `PM25` for raw, `PM25_PCT` for percentile).
3. Update `check_ejscreen_spatial()` in `health_compare.py` to use percentile values directly: `>= 80` = WARNING, `>= 95` = "very high" note.
4. Remove the `EJSCREEN_INDICATORS` threshold dict — no longer needed with real percentiles.

## Current mitigation

- The check is `required=False` and only returns WARNING (never FAIL)
- Approximate thresholds sourced from EPA EJScreen 2024 Technical Documentation
- Needs validation against known Westchester addresses before shipping to users

## Also: display metadata for ejscreen_environmental

`ejscreen_environmental` (the check name used by `check_ejscreen_spatial()`) has no entries in `_CLEAR_HEADLINES`, `_WARNING_HEADLINES`, or `_SAFETY_CHECK_NAMES` in app.py. It falls back to generic patterns like `"ejscreen_environmental — Warning detected"`. Add proper entries during polish pass before validation testing.

## Acceptance criteria

- [ ] Percentile columns stored in spatial.db metadata
- [ ] Threshold logic uses actual percentiles, not approximate reference values
- [ ] `ejscreen_environmental` added to `_SAFETY_CHECK_NAMES`, `_CLEAR_HEADLINES`, `_WARNING_HEADLINES` in app.py
- [ ] Verified against 3+ known Westchester addresses with expected EJScreen profiles
