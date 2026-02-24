# NES-65: API Call Deduplication — Verification Plan

**Overall Progress:** `50%`

## TLDR
The 7 deduplication fixes from the original audit have already been implemented in prior work. NES-65 is now a verification ticket: run a real evaluation through `nc_trace`, count actual API calls, compare against the ~85-90 target, and document the results. Conditional Phase 2 only if numbers are significantly over target.

## Critical Decisions
- **Use `/debug/eval` endpoint, not a standalone instrumentation script** — the endpoint already runs a synchronous evaluation and returns `full_trace_dict()` with per-call and per-stage breakdowns. No temp instrumentation needed.
- **Write a small client script** — hits the local endpoint, parses the JSON response, prints a summary table. Disposable tooling, not production code.
- **Test address: 10 Byron Place, Larchmont, NY 10538** — standard benchmarking address, representative suburban Westchester evaluation across all stages.
- **Document in Linear issue, not dashboard** — no dashboard work needed. Pass/fail against 85-90 target documented in NES-65 comments.
- **Don't persist full traces to snapshots** — separate concern with its own tradeoffs. Out of scope.

## Tasks

- [x] 🟩 **Step 1: Write verification script**
  - [x] 🟩 Create `scripts/verify_api_calls.py` — hits `POST /debug/eval` with the test address and builder auth cookie
  - [x] 🟩 Parse `trace.api_calls` from response JSON
  - [x] 🟩 Print summary table: total calls, breakdown by service, breakdown by (service, endpoint), breakdown by stage
  - [x] 🟩 Print pass/fail verdict against 85-90 target

- [ ] 🟨 **Step 2: Run verification**
  - [x] 🟩 Verified script runs and gives clean error without server (no `.env` with API keys on disk)
  - [ ] 🟥 Start local Flask server with valid `.env` (`python app.py`)
  - [ ] 🟥 Execute: `python scripts/verify_api_calls.py` — capture output
  - [ ] 🟥 If over target: identify which stages/endpoints account for the excess

- [ ] 🟥 **Step 3: Document results in NES-65**
  - [ ] 🟥 Post summary table and pass/fail to NES-65 Linear issue as a comment
  - [ ] 🟥 If on target: mark NES-65 as done
  - [ ] 🟥 If over target: add findings and recommend next steps (e.g., Fix #7 radius mismatch worth pursuing or not)
