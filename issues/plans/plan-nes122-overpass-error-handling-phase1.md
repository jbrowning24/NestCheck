# Implementation Plan: NES-122 Phase 1 — Overpass Error Handling in _overpass_query()

**Progress:** 100% · **Status:** Complete  
**Last updated:** 2025-02-20

## TLDR

Add failure-mode awareness to `_overpass_query()` in `green_space.py`. The function currently cannot distinguish between success, HTTP errors (429, 504), and Overpass's pattern of returning HTTP 200 with an error in the JSON body (`osm3s.remark`). It also does not record failed requests in `nc_trace`. Phase 1 introduces two exception classes, validates responses before caching, records all failures in trace, and lets typed exceptions propagate for Phase 2 to handle.

## Scope

**In scope:**
- Add `OverpassRateLimitError` and `OverpassQueryError` exception classes
- Rewrite HTTP call and response validation in `_overpass_query()` to check status code and JSON body
- Record failed Overpass requests in `nc_trace` (with status code and error classification in `provider_status`)
- Let `OverpassRateLimitError` and `OverpassQueryError` propagate; wrap unexpected exceptions in `OverpassQueryError`

**Out of scope:**
- Changes to `batch_enrich_from_osm()` (Phase 2)
- Changes to `evaluate_green_escape()` (Phase 3)
- Changes to `enrich_from_osm()` — it calls `_overpass_query()` and will receive raised exceptions; Phase 2/3 will add handling
- Changes to any file other than `green_space.py`

## Key Decisions

| # | Decision | Rationale |
|---|----------|------------|
| 1 | Use `provider_status` for error classification | `APICallRecord` has no dedicated error field; `provider_status` is used by `weather.py` for "OK"/"ERROR"/"TIMEOUT" |
| 2 | Raise typed exceptions instead of returning `None` | Phase 2 needs to distinguish rate-limit vs other errors for retry/fallback decisions |
| 3 | Use `status_code=0` when no HTTP response (e.g. network error) | `APICallRecord.status_code` is `int`; `weather.py` uses 0 for timeout |
| 4 | Check `remark` for error substrings case-insensitively | Overpass error text varies; substring match is robust |

## Assumptions

- `enrich_from_osm()` will receive unhandled exceptions from `_overpass_query()` in Phase 1. Its callers (`batch_enrich_from_osm` fallback path, or any direct caller) will propagate to `evaluate_green_escape()`, which catches `Exception` and returns empty OSM data. No change to `enrich_from_osm()` in Phase 1.
- `nc_trace.record_api_call()` accepts `provider_status` as a string; error classifications (`rate_limit`, `timeout`, `body_error`, `http_error`, `parse_error`) will be stored there.
- Overpass error remarks appear in `osm3s.remark` or top-level `remark`; substring checks cover the known error patterns.

## Tasks

- [x] 🟩 **1. Add exception classes** · _[S]_
  Place two exception classes at module level in `green_space.py`, after imports and before any class/function definitions.
  - [x] 🟩 1.1 Add `OverpassRateLimitError(Exception)` with docstring: "Overpass returned 429 or equivalent rate limit signal."
  - [x] 🟩 1.2 Add `OverpassQueryError(Exception)` with docstring: "Overpass returned an error (HTTP error, timeout, or error in response body)."

- [x] 🟩 **2. Add HTTP status validation** · _[M]_
  After `session.post()` succeeds, before `resp.json()`, validate `resp.status_code`.
  - [x] 🟩 2.1 If 429: record trace (service=`overpass`, endpoint=`osm_enrich_query`, elapsed_ms, status_code=429, provider_status=`rate_limit`), then `raise OverpassRateLimitError("Overpass rate limit (429)")`
  - [x] 🟩 2.2 If 504: record trace (provider_status=`timeout`), then `raise OverpassQueryError("Overpass gateway timeout (504)")`
  - [x] 🟩 2.3 If any other non-2xx: record trace (provider_status=`http_error`), then `raise OverpassQueryError(f"Overpass HTTP {resp.status_code}")`
  - [x] 🟩 2.4 Do not call `resp.json()` or cache when status is non-2xx

- [x] 🟩 **3. Add JSON parse error handling** · _[S]_
  Wrap `resp.json()` in try/except for `ValueError` and `json.JSONDecodeError`.
  - [x] 🟩 3.1 On decode error: record trace (provider_status=`parse_error`, status_code=resp.status_code), then `raise OverpassQueryError(f"Overpass returned non-JSON response (HTTP {resp.status_code})")`

- [x] 🟩 **4. Add response body error check** · _[M]_
  After `resp.json()` succeeds, check for error in the response body before caching.
  - [x] 🟩 4.1 Extract `remark` from `data.get("osm3s", {})` (if dict) and `data.get("remark")` as fallback
  - [x] 🟩 4.2 If `remark` exists and contains (case-insensitive) any of: `"runtime error"`, `"timed out"`, `"out of memory"`, `"too many requests"`:
    - Do not cache
    - Record trace (provider_status=`body_error` for most; `rate_limit` if remark contains `"too many requests"`)
    - Raise `OverpassRateLimitError` if "too many requests", else `OverpassQueryError(f"Overpass body error: {remark[:200]}")`
  - [x] 🟩 4.3 Only cache and return when both status is 2xx and no error remark

- [x] 🟩 **5. Update exception handling** · _[S]_
  Replace the generic `except Exception` block so typed exceptions propagate and unexpected errors are wrapped.
  - [x] 🟩 5.1 Do NOT catch `OverpassRateLimitError` or `OverpassQueryError` — let them propagate
  - [x] 🟩 5.2 For `except Exception`: record trace (elapsed_ms from t0, status_code=0, provider_status=`http_error` or `parse_error` as appropriate), log warning, then `raise OverpassQueryError(...)` with a message derived from the original exception
  - [x] 🟩 5.3 Ensure network errors (e.g. `requests.Timeout`, `requests.ConnectionError`) are caught, traced, and re-raised as `OverpassQueryError`

- [x] 🟩 **6. Verify trace recording** · _[S]_
  Ensure no double-recording and correct behavior on success.
  - [x] 🟩 6.1 Success path: keep existing single `record_api_call` (unchanged)
  - [x] 🟩 6.2 Failure paths: each failure branch records exactly once before raising
  - [x] 🟩 6.3 Do not record in the generic `except` if an inner branch already recorded (e.g. status-code branch records before raising; generic except handles only pre-response failures like network errors)

## Verification

- [ ] `green_space.py` is the only file changed
- [ ] `_overpass_query()` and the two new exception classes are the only modifications
- [ ] HTTP 429 → trace recorded with `provider_status=rate_limit`, `OverpassRateLimitError` raised
- [ ] HTTP 504 → trace recorded with `provider_status=timeout`, `OverpassQueryError` raised
- [ ] HTTP 200 with `osm3s.remark` containing "timed out" → trace recorded with `provider_status=body_error`, `OverpassQueryError` raised, response not cached
- [ ] Non-JSON response body → trace recorded with `provider_status=parse_error`, `OverpassQueryError` raised
- [ ] Successful 200 with valid data → behavior unchanged (single trace record, cached, returned)
- [ ] Failed calls appear in trace output; successful calls are not double-recorded

## Status Report Format (for executor)

When done, report:
1. **Files changed** — should only be `green_space.py`
2. **Functions modified** — `_overpass_query()` plus the two new exception classes
3. **New behavior on each failure mode** — (as in Verification above)
4. **Trace recording** — confirm failed calls appear in trace, successful calls not double-recorded
5. **What was NOT tested** — e.g. live Overpass 429/504, real `remark` in response body
