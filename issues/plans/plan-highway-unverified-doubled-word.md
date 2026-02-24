# Fix: Highway Proximity — "Unverified" + Doubled Word

**Overall Progress:** `100%` · **Status:** Complete
**Last updated:** 2026-02-09

## TLDR
Two bugs in the highway/road proximity check presentation. (1) The UNKNOWN explanation text says "highway proximity proximity" because `CHECK_DISPLAY_NAMES` already includes "Proximity" and `_proximity_explanation` appends it again. (2) When the initial Overpass call fails, `_roads_data` is set to `None`, causing `check_highways` and `check_high_volume_roads` to each re-call Overpass (plus `_retry_once` retries) — 4 redundant API calls to an already-failing endpoint, increasing latency and the chance of returning "Unverified".

## Critical Decisions
- **Fix doubled word by using `check.name` instead of `display`**: The UNKNOWN branch in `_proximity_explanation()` should use `check.name.lower()` (e.g. "highway") rather than `display.lower()` (e.g. "highway proximity") when constructing the sentence that already ends with "proximity". This avoids "highway proximity proximity".
- **Sentinel value for failed Overpass fetch**: When the shared Overpass call at line 3032 fails, pass a dedicated sentinel (e.g. a module-level `_OVERPASS_FAILED` object) instead of `None`. Check functions detect the sentinel and return UNKNOWN immediately — no redundant Overpass calls or retries on a known-down endpoint.
- **Add `raise_for_status()` to `_traced_post`**: Overpass sometimes returns HTML error pages (503, 429). Without `raise_for_status()`, `.json()` throws an opaque `JSONDecodeError`. Checking status first gives clearer log output.

## Tasks

- [x] 🟩 **Step 1: Fix doubled "proximity" in `_proximity_explanation()`**
  - [x] 🟩 Line 254 in `property_evaluator.py`: change `{display.lower()} proximity` to `{check.name.lower()} proximity` in the UNKNOWN branch (affects all three safety checks: Gas station, Highway, High-volume road)

- [x] 🟩 **Step 2: Add Overpass failure sentinel to avoid redundant calls**
  - [x] 🟩 Define a module-level sentinel `_OVERPASS_FAILED = object()` near the constants
  - [x] 🟩 In `evaluate_property()` (~line 3034): on exception, set `_roads_data = _OVERPASS_FAILED` instead of `None`
  - [x] 🟩 In `check_highways()` (~line 1108): if `roads_data is _OVERPASS_FAILED`, return UNKNOWN immediately with details "Overpass API unavailable"
  - [x] 🟩 In `check_high_volume_roads()` (~line 1149): same sentinel check
  - [x] 🟩 Skip `_retry_once` wrapping for highway/road checks when `_roads_data is _OVERPASS_FAILED` (retrying won't help — the shared fetch already failed)

- [x] 🟩 **Step 3: Add `raise_for_status()` to Overpass `_traced_post()`**
  - [x] 🟩 After `self.session.post(...)` at line 863, add `response.raise_for_status()` so non-200 responses produce clear `HTTPError` exceptions instead of opaque `JSONDecodeError`

- [x] 🟩 **Step 4: Verify fix**
  - [x] 🟩 Run existing tests to confirm no regressions (46 passed, 0 new failures)
  - [x] 🟩 Manually confirm the UNKNOWN explanation text no longer doubles "proximity"
