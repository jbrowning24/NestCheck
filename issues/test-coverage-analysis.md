# Test Coverage Analysis

**Date:** 2026-02-26
**Status:** Analysis complete — proposals ready for review

---

## Executive Summary

NestCheck has a solid testing foundation: **27 test files** covering database persistence, payment flows, scoring regression, tracing, and several domain modules. However, the **largest and most critical module** — `property_evaluator.py` (3,671 lines) — has **zero direct unit tests**. Its behavior is only exercised indirectly through integration tests and regression snapshots. Several other high-value modules also have significant gaps.

This document identifies **7 priority areas** where additional tests would have the highest impact on reliability and confidence during refactoring.

---

## Current Test Inventory

| Module | Lines | Direct Test File | Test Lines | Estimated Coverage |
|--------|-------|-----------------|-----------|-------------------|
| models.py | 558 | test_models.py | 584 | ~95% |
| nc_trace.py | 263 | test_nc_trace.py | 267 | ~95% |
| scoring_config.py | 370 | test_scoring_regression.py | 505 | ~90% |
| app.py (payments) | — | test_payments.py | 614 | ~85% (payment routes) |
| app.py (insights) | — | test_insights.py | 1,099 | ~90% (insight generation) |
| app.py (service errors) | — | test_service_errors.py | 266 | ~80% (error handling routes) |
| app.py (compare) | — | test_compare.py | 91 | ~70% (compare route) |
| app.py (dedupe) | — | test_dedupe.py | 273 | ~80% (deduplication) |
| worker.py | 280 | test_worker.py | 214 | ~80% |
| health_monitor.py | 414 | test_health_monitor.py | 396 | ~80% |
| green_space.py | 1,501 | test_green_space.py | 603 | ~60% |
| weather.py | 433 | test_weather.py | 297 | ~75% |
| road_noise.py | 368 | test_road_noise.py | 320 | ~85% |
| census.py | 631 | test_census.py | 380 | ~70% |
| overpass_http.py | 375 | test_overpass_http.py | 239 | ~80% |
| sidewalk_coverage.py | 284 | test_sidewalk.py | 236 | ~75% |
| map_generator.py | 120 | test_map_generator.py | 156 | ~80% |
| og_image.py | 111 | test_og_image.py | 123 | ~80% |
| spatial_data.py | 510 | test_spatial_data.py | 80 | ~30% |
| **property_evaluator.py** | **3,671** | **None** | **0** | **~0% direct** |
| urban_access.py | 397 | None | 0 | ~0% direct |
| email_service.py | 82 | None (mocked only) | 0 | ~0% direct |

**Total source:** ~13,300 lines | **Total test:** ~6,700 lines | **Test:source ratio:** ~0.50

---

## Priority 1: property_evaluator.py — Tier 1 Check Functions

**Impact: Critical** | **Effort: Medium** | **Risk addressed: Silent regression in safety checks**

The Tier 1 checks are the most important feature in the product — they determine whether a property passes or fails environmental safety criteria. None of them have direct unit tests.

### What to test

**Pure-logic helpers (no mocking needed):**
- `_distance_feet(lat1, lng1, lat2, lng2)` — Haversine calculation. Test with known coordinate pairs.
- `_closest_distance_to_way_ft(prop_lat, prop_lng, way_node_ids, all_nodes)` — Way geometry distance. Test with synthetic node dicts: simple 2-node way, missing nodes (should return `inf`), empty list.
- `_parse_max_voltage(voltage_str)` — Parses OSM voltage tags like `"115000"`, `"115000;230000"`, `""`, and garbage strings. Should return max int or 0 on failure.
- `_element_distance_ft(prop_lat, prop_lng, el, all_nodes)` — Distance to an OSM element. Test node vs way elements, missing node references.

**Check functions (mock GoogleMapsClient / OverpassClient):**
- `check_gas_stations(maps, lat, lng)` — Test: no stations nearby → PASS, station at 400 ft → FAIL, station at 600 ft → PASS, API error → UNKNOWN.
- `check_highways(maps, overpass, lat, lng)` — Test: no motorways → PASS, motorway at 300 ft → FAIL, trunk road at 300 ft → FAIL, only secondary → PASS.
- `check_high_volume_roads(overpass, lat, lng)` — Test: no roads → PASS, primary road within 500 ft → FAIL, residential 4-lane → FAIL, lanes tag parsing edge cases.
- `check_power_lines(hazard_results, lat, lng)` — Test: no power lines → PASS, 115kV line at 150 ft → WARNING, low-voltage line → PASS, hazard_results is None → UNKNOWN.
- `check_substations(hazard_results, lat, lng)` — Similar: within 300 ft → WARNING, beyond → PASS.
- `check_cell_towers(hazard_results, lat, lng)` — Within 500 ft → WARNING.
- `check_industrial_zones(hazard_results, lat, lng)` — Within 500 ft → WARNING.

**Listing requirements (no mocking needed):**
- `check_listing_requirements(listing)` — Test: all fields None, all fields set, boundary values for sqft/bedrooms/cost.

### Why this matters

A regression in `check_highways` or `check_gas_stations` could silently approve a property that should fail. These checks are the product's core safety promise. Currently the only guard is the scoring regression suite, which tests outputs but not individual check logic.

---

## Priority 2: property_evaluator.py — Tier 2 Scoring Functions

**Impact: High** | **Effort: Medium** | **Risk addressed: Score drift, incorrect point awards**

The Tier 2 scoring functions produce the numeric scores that users see. `test_scoring_regression.py` tests the piecewise curve math and persona weights, but the actual `score_*` functions that call APIs and compute points are untested directly.

### What to test

- `score_cost(cost)` — Pure function, no mocking needed. Test thresholds: `None` → 0, below COST_IDEAL → max points, above COST_MAX → 0, interpolation between brackets.
- `score_park_access(maps, lat, lng, ...)` — Mock maps client. Test: no parks → 0, high-quality nearby park → max, borderline walk time.
- `score_third_place_access(maps, lat, lng)` — Mock maps client. Test: no cafes → 0, cafe at 5 min → high score, type/keyword filtering (exclude fast food).
- `score_provisioning_access(maps, lat, lng)` — Mock maps client. Test: grocery at 10 min → high, no grocery → 0, quality filtering (rating < 3.5 excluded).
- `score_fitness_access(maps, lat, lng)` — Mock maps client. Test: gym at 10 min with 4.5 rating → high, gym at 35 min → low.
- `score_transit_access(maps, lat, lng, ...)` — Mock maps client. Test both the legacy path (transit_keywords) and new path (TransitAccessResult).

### Why this matters

When the scoring model is updated (new brackets, weight changes), having unit tests for each scoring function prevents accidental regressions in dimensions that weren't intentionally changed.

---

## Priority 3: property_evaluator.py — GoogleMapsClient

**Impact: High** | **Effort: Medium** | **Risk addressed: Silent API failures, batch chunking bugs**

GoogleMapsClient wraps all Google Maps API interactions. Its batch methods auto-chunk at 25 destinations per request — a critical correctness boundary that has no test coverage.

### What to test

- `_distance_matrix_batch(origin, destinations, mode, name)` — Mock `_traced_get`. Test:
  - Empty destinations → empty list
  - 1 destination → single request
  - 25 destinations → single request
  - 26 destinations → two requests, results merged correctly
  - One element returns "NOT_FOUND" → 9999 for that position
  - API returns error status → 9999 for all
- `geocode(address)` — Mock `_traced_get`. Test: valid response, ZERO_RESULTS → ValueError, non-OK status.
- `places_nearby(lat, lng, type, radius)` — Mock `_traced_get`. Test: results returned, ZERO_RESULTS → empty list.
- `walking_time(origin, dest)` — Mock `_traced_get`. Test: valid time extraction, "NOT_FOUND" element → 9999.

### Why this matters

The batch chunking logic in `_distance_matrix_batch` is subtle — an off-by-one error could silently misalign walk times with their corresponding destinations. This has happened before in similar codebases.

---

## Priority 4: urban_access.py — Full Module

**Impact: Medium** | **Effort: Medium** | **Risk addressed: Untested commute calculations**

`urban_access.py` (397 lines) has **zero direct tests**. It calculates commute times to major hubs (NYC, airports, hospitals) — a key dimension in the evaluation.

### What to test

- `_verdict(minutes, category)` — Pure function. Test: boundary values for "Great" / "OK" / "Painful" per category.
- `_load_airport_hubs()` — Test: default hubs when env var missing, valid JSON override, malformed JSON fallback.
- `UrbanAccessEngine._best_travel(dest)` — Mock maps client. Test: transit works → transit chosen, transit unreachable → driving fallback, both unreachable → None.
- `UrbanAccessEngine._nearest_airport()` — Mock maps client. Test: multiple airports → nearest selected, all unreachable → None.
- `UrbanAccessEngine.evaluate()` — Integration test with mocked maps. Verify output structure and primary hub identification.

### Why this matters

Urban access is a scored dimension that affects the overall property score. Without tests, changes to commute calculation logic can silently break the "Getting Around" section of reports.

---

## Priority 5: app.py — Presentation & Route Coverage Gaps

**Impact: Medium** | **Effort: Low-Medium** | **Risk addressed: Template rendering failures, serialization bugs**

While `app.py` has good coverage for payments, insights, and error handling, several core helpers and routes are untested.

### What to test

**Presentation helpers (no mocking needed):**
- `generate_verdict(result_dict)` — Test all score bands (0-39, 40-54, 55-69, 70-84, 85-100) with both passed_tier1=True and False.
- `present_checks(tier1_checks)` — Test each CheckResult type (PASS, FAIL, WARNING, UNKNOWN) and each check category (proximity, listing, environmental).
- `_serialize_green_escape(evaluation)` — Test None input, evaluation with no parks, evaluation with best_park.
- `_serialize_urban_access(urban_access)` — Test None input, full profile.
- `result_to_dict(result)` — Test with a minimal EvaluationResult, verify all expected keys present.

**Untested routes:**
- `GET /builder/dashboard` — Verify 404 for non-builders, 200 for builders with expected content.
- `GET /debug/trace/<id>` — Verify builder-only access.
- `POST /debug/eval` — Verify evaluation with trace capture (currently tested in test_dedupe.py only for dedupe bypass).
- `POST /api/event` — Verify event type whitelist, valid event recording, invalid type → 400.
- `GET /pricing` — Verify 200.

### Why this matters

`result_to_dict` is the single serialization chokepoint between the evaluation engine and every output format (HTML, JSON, CSV). A bug there breaks all three. `present_checks` determines the human-readable display of safety checks.

---

## Priority 6: email_service.py — Direct Tests

**Impact: Medium** | **Effort: Low** | **Risk addressed: Email failures silently swallowed**

`email_service.py` (82 lines) is currently only tested indirectly via mocking in `test_worker.py`. The actual email construction and error handling have no coverage.

### What to test

- `send_report_email(to_email, snapshot_id, address)` — Mock `resend.Emails.send`. Test:
  - Missing RESEND_API_KEY → returns False (no crash)
  - Successful send → returns True
  - API raises exception → returns False, exception logged
  - HTML content includes snapshot_id and address (verify template correctness)
  - Address with special characters (verify HTML escaping)

### Why this matters

Email is the primary delivery mechanism for evaluation reports. If `send_report_email` silently starts returning False due to a template bug, users won't receive their reports and there's no test to catch it.

---

## Priority 7: spatial_data.py — Expanded Coverage

**Impact: Low-Medium** | **Effort: Medium** | **Risk addressed: Spatial query correctness**

`test_spatial_data.py` has only one integration test (80 lines) that tests basic point queries. The polygon containment, line distance, and availability caching logic are untested.

### What to test

- `SpatialDataStore.is_available()` — Test: DB exists → True, DB missing → False, caching behavior (second call uses cache).
- `point_in_polygons(lat, lng, type)` — Test with synthetic polygon geometry: point inside → returned, point outside → empty.
- `lines_within(lat, lng, radius, type)` — Test with synthetic line geometry: line within radius → returned with distance.
- `nearest_line(lat, lng, type)` — Test: returns closest line, no lines → None.
- `create_facility_table(type, extra_columns, geometry_type)` — Test: valid geometry types, invalid type → error.

### Why this matters

Spatial queries power the environmental hazard checks when SpatiaLite data is available. Incorrect spatial queries could cause false positives or negatives in the proximity checks.

---

## Cross-Cutting Gaps

Beyond the 7 priority areas, these patterns are worth addressing:

### No end-to-end job flow test
There's no single test that exercises: `POST /` → job created → worker picks up → evaluate_property runs → snapshot saved → `GET /s/<id>` renders. This could be a single integration test with mocked APIs.

### No concurrency test for job claiming
`claim_next_job()` uses atomic SQL, but multi-threaded claiming is never tested. A test spinning up 5 threads all calling `claim_next_job()` simultaneously would verify that exactly one succeeds.

### Builder route access control
Builder-only routes (`/builder/dashboard`, `/debug/*`) lack tests verifying that non-builder requests get 404. This is a minor security concern.

### Test organization
Root-level test files (`test_dedupe.py`, `test_green_space.py`, etc.) duplicate some tests in `tests/` directory. Consider consolidating to a single location.

---

## Recommended Implementation Order

| Phase | Area | Files to Create/Modify | Est. Tests |
|-------|------|----------------------|-----------|
| 1 | Tier 1 checks + helpers | `tests/test_property_evaluator.py` | ~35 |
| 2 | Tier 2 scoring + cost | Add to `tests/test_property_evaluator.py` | ~25 |
| 3 | GoogleMapsClient batch | `tests/test_google_maps_client.py` | ~15 |
| 4 | Urban access module | `tests/test_urban_access.py` | ~20 |
| 5 | App presentation helpers | `tests/test_app_helpers.py` | ~20 |
| 6 | Email service | `tests/test_email_service.py` | ~8 |
| 7 | Spatial data expanded | Extend `tests/test_spatial_data.py` | ~10 |

**Total: ~133 new tests** across 5 new files and 1 expanded file.

This would bring the test:source ratio from ~0.50 to ~0.65 and — more importantly — provide direct coverage for the most critical business logic in the codebase.
