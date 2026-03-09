# NestCheck

Property evaluation tool for Westchester County rentals. Analyzes health, lifestyle, and budget criteria for Metro-North corridor properties.

## Tech Stack

- **Backend:** Python/Flask
- **Database:** SQLite with async evaluation queue
- **APIs:** Google Maps, Overpass (OpenStreetMap)
- **Frontend:** Jinja templates, vanilla JS
- **Hosting:** Railway

## Project Structure

```
NestCheck/
├── app.py              # Flask routes, API endpoints
├── models.py           # SQLite models, job queue
├── worker.py           # Background evaluation worker
├── property_evaluator.py  # Core evaluation logic, API clients
├── nc_trace.py         # Request tracing
├── templates/          # Jinja HTML templates
├── static/             # CSS, JS assets
└── issues/             # Local issue tracking (markdown)
```

## Our Workflow

1. `/exploration-phase` - Understand before building
2. `/create-plan` - Markdown plan with status tracking
3. `/execute` - Implement step by step with progress tracking
4. `/code-review` - Self-review the changes
5. `/pr-learn` - PR review + extract lessons for CLAUDE.md
6. `/review` (built-in) - PR review for code quality, security, and test coverage

## Claude Code Configuration

### Custom Commands & Hooks
- Custom slash commands in `.claude/commands/` must not shadow built-in commands (e.g., `/review`, `/compact`, `/init`). Check the built-in list before naming a new command. Shadowed built-ins become unreachable.
- PostToolUse hooks that reference `$CLAUDE_FILE_PATH` must guard with `test -n` and quote the variable. If unset, tools like `ruff format` will silently operate on the entire directory.
- Subagent definitions live in `.claude/agents/`. Each agent should have a single focused responsibility and explicit verification steps.
- SessionStart hooks that run `sudo apt install` will hang in environments requiring a password prompt. Always guard with `command -v <tool>` to skip installation when the tool already exists, and end with `|| true` so failures never block the session.

## Coding Standards

- Python: Follow existing patterns in property_evaluator.py
- Use type hints for function signatures
- Add docstrings for public functions
- No print() in production - use logging
- All API calls need timeout handling
- Spatial metadata values may arrive as strings after JSON round-tripping — cast to `float()` before numeric formatting (`:,.0f`)
- **scoring_config ↔ property_evaluator import sync**: When adding new constants to `scoring_config.py` that are referenced in `property_evaluator.py`, update the `from scoring_config import (...)` block in the same commit. Missing imports surface as `NameError` only at evaluation runtime (inside try/except), not at startup — so they silently produce 0/10 scores with error text in reports instead of crashing visibly.
- When changing template element IDs, update `smoke_test.py` markers (`LANDING_REQUIRED_MARKERS`, `SNAPSHOT_REQUIRED_MARKERS`) in the same commit. Mismatches cause silent post-deploy smoke test failures.
- When removing HTML elements from templates, remove the corresponding CSS rules in the same commit. Orphaned selectors (e.g., `.snippet-assessment-score` after removing the score div) accumulate silently.
- When relocating template sections to a different parent container, update surrounding copy (section headings, divider descriptions, context notes) to reflect the new contents. Stale copy (e.g., "Community and school data" after adding EJScreen) silently misleads users.
- Frontend `fetch()` calls that expect JSON must check `resp.ok` and content-type before calling `.json()`. Non-JSON error responses (CSRF 400, HTML 500) cause Safari-specific `TypeError` ("The string did not match the expected pattern") that hides the real error. Always guard: `if (!resp.ok) { /* handle non-JSON */ }` before `resp.json()`.
- Frontend polling loops must never give up on a single transient error (404, 5xx, network). Use retry counters with a cap before showing a failure. The job queue is eventually-consistent under load; a freshly-created job may not be visible to the poll endpoint for 1-2 cycles.
- Flask error handlers (`@app.errorhandler`) must return JSON when `_wants_json()` is true. Without this, JS clients get HTML error pages they can't parse. Add handlers for 400, 404, and 500 at minimum.

## Key Patterns

### Async Evaluation (job queue)
- **POST /** with address: creates a job in SQLite, returns `{job_id}` immediately (no client timeout).
- **GET /job/<job_id>**: returns `{status, current_stage?, snapshot_id?, error?}` for polling. status: `queued` | `running` | `done` | `failed`.
- **worker.py**: one background thread per gunicorn worker (started via `gunicorn_config.py` post_fork). Polls for queued jobs, claims atomically, runs `evaluate_property(listing, api_key, on_stage=...)`, updates `current_stage` in DB, then saves snapshot and marks job done or failed.
- Frontend: form submit → POST → get job_id → poll GET /job/{id} every 2s → show stage text → on done redirect to /s/{snapshot_id}.

### API Clients
- GoogleMapsClient wraps all Maps API calls
- Always use `timeout=API_REQUEST_TIMEOUT`
- Handle quota errors gracefully
- **Non-physical place filtering** (NES-211): `places_nearby()` and `text_search()` centrally filter out permanently closed and online-only businesses before caching/returning results. All downstream consumers get clean data without their own filter logic. To add a new online-only service, add to `_ONLINE_BUSINESS_EXACT_NAMES` (preferred) or `_ONLINE_BUSINESS_NAME_PATTERNS` (for regex). Filtered places are attached to `TraceContext.filtered_places` for audit.
- **Auditable heuristic filters**: When filtering API results by name/pattern heuristics, return a reason string (not just bool) so filtered items can be traced and false positives audited. Pattern: `_non_physical_reason() → Optional[str]` with typed reasons like `"closed_permanently"`, `"online_exact:<name>"`, `"online_pattern:<regex>"`.

### Venue Scoring Calibration (scoring_config.py + property_evaluator.py)
- **Venue eligibility thresholds**: `VENUE_MIN_REVIEWS` and `VENUE_MIN_RATING` dicts in `scoring_config.py` gate which venues enter scoring. Venues below thresholds are still returned for display — only excluded from headline selection and dimension score computation.
- **Search types ↔ eligibility types contract**: Every Google Places type accepted in the eligibility filter (e.g., `["cafe", "coffee_shop", "bakery"]` at line 4280) must have a corresponding `places_nearby()` query upstream. A type in the filter but missing from the search silently produces zero matches for that category — no error, just empty results. When adding a new accepted type, add the API query in both `score_third_place_access()` and `get_neighborhood_snapshot()`.
- **Quality ceiling pattern** (Phase 2): Walk-time proximity scores are capped by a diversity ceiling computed from two signals: (1) distinct social-category buckets via `_SOCIAL_BUCKET_MAP` → `THIRD_PLACE_CATEGORY_CEILINGS`, and (2) median review depth ±1 adjustment. `final_score = min(walk_time_score, ceiling)`. The ceiling is structurally bounded by search query types — only categories returned by the Google Places search can contribute buckets.
- **Suppressed dimensions** (`points=None`): When no venues pass eligibility, return `Tier2Score(points=None, suppressed_reason=...)` instead of `points=0`. Template shows "—", composite scoring excludes the dimension from aggregation (reduces effective max). This avoids penalizing addresses for data gaps.

### Narrative Insights (NES-191+)
- Insight generators are pure functions: `dict → str | None`. Keep them side-effect-free for testability.
- Place insight logic in dedicated modules (not `app.py`) — `app.py` is for routes/views.
- **Dict field-name contracts**: Insight functions that consume dicts from `present_checks()` must use the field names that function actually produces (`"name"`, `"result_type"`, `"category"`, etc.) — not alternative names like `"display_name"` or `"check_id"`. When adding a new consumer of presented-check dicts, verify field names against `present_checks()` output, not against `_PROXIMITY_LABELS` keys or other lookup tables. Always add a `or "this hazard"` (or similar) terminal fallback when interpolating dict values into user-facing sentences to prevent sentence fragments from malformed input.
- Avoid duplicating utility helpers across modules (e.g., Oxford-comma join) — use a shared module.

### Check Display Metadata (app.py)
- Each Tier1Check `name` in `property_evaluator.py` needs entries in app.py: `_SAFETY_CHECK_NAMES`, `_CLEAR_HEADLINES`, `_ISSUE_HEADLINES`, `_WARNING_HEADLINES`, `_HEALTH_CONTEXT`.
- Only add headline entries for result states the check can actually produce. `_build_health_context()` returns `None` silently for missing keys.
- **Naming split**: Legacy checks use display names (`"Power lines"`, `"Gas station"`). Phase 1B spatial checks use `snake_case` (`"ust_proximity"`, `"hifld_power_lines"`). Match the convention of the source check function.
- New checks NOT in `_CHECK_SOURCE_GROUP` render individually (not collapsed).
- **Tier1Check serialization paths**: `Tier1Check` is serialized in three places — `result_to_dict()` (main snapshot), the compare route's serialization loop, and CSV export. When adding a new field to the dataclass, update ALL three. The compare path is easy to miss.
- **Nullable field propagation**: When widening a dataclass field from non-optional to `Optional` (e.g., `points: int → Optional[int]`), audit every consumer: arithmetic aggregation (`sum()`), string formatting (`f"{x} pts"`), template division (`score / max`), and all serialization paths. Each needs a null guard or filter. The `_scorable = [s for s in scores if s.points is not None]` pattern keeps aggregation clean.
- **Search radius vs threshold** (NES-203): Search radius can be wider than the warning threshold to report "Nearest: X (Y ft)" on PASS. Set `show_detail=True` on those PASS results. When nothing is found even within the expanded radius, the detail string should match the `_CLEAR_HEADLINES` wording (use the threshold distance, not the search radius).
- **Presentation-layer suppression** (NES-196): To hide checks from display without changing evaluation or storage, filter in the route handler (e.g., `view_snapshot()`), not in `present_checks()` or `result_to_dict()`. Use `result = {**result, ...}` to shallow-copy the deserialized snapshot dict before modifying — never mutate it in-place, as a future caching layer would silently corrupt shared state. Suppressed metadata (e.g., count) should travel inside `result` dict, not as a separate template var, so Jinja includes and macros can access it without relying on inherited scope. Apply suppression to ALL routes that render the same data (snapshot, compare-health, etc.) to avoid inconsistent UX.
- **Confidence score caps** (NES-sparse-data): Dimension scores from data-confidence-aware scorers must be passed through `_apply_confidence_cap(score, confidence)` before building the `Tier2Score`. `estimated` caps at 8/10, `verified` uncapped, `not_scored` excluded from composite entirely. Apply consistently to every dimension that classifies confidence — omitting it lets sparse data produce artificially high ratings.
- **`apply_piecewise` returns float → round to int for `Tier2Score.points`**: `apply_piecewise()` and `apply_quality_multiplier()` return floats, but `Tier2Score.points` is `Optional[int]`. Every scoring path must round at the `Tier2Score` boundary: `points = int(max(cfg.floor, capped_score) + 0.5)`. The `score_road_noise` function established this pattern; all other dimensions using `apply_piecewise` must follow it. Omitting the round silently stores floats in an int field, causing "7.6/10" display artifacts and type-contract violations in serialization paths.
- **Snapshot migration functions must run on shallow copies**: Every route that deserializes a snapshot and runs migration functions (`_migrate_dimension_names`, `_migrate_confidence_tiers`) must shallow-copy first: `result = {**snapshot["result"]}`. There are currently 4 deserialization paths: `view_snapshot()`, `export_snapshot_json()`, `export_snapshot_csv()`, and the compare route. When adding a new migration function, wire it into ALL 4 paths — missing one causes silent data inconsistencies. The `view_snapshot` route copies via `{**result, ...}` during suppression; the others need explicit `{**snapshot["result"]}`.
- **Backfill ordering and safe template defaults**: Functions that compute derived fields from migrated data (e.g., `_compute_show_numeric_score` consuming `data_confidence`) must run *after* the relevant migration (`_migrate_confidence_tiers`). Do not add legacy tier names to the derived function's allowlist as a substitute for correct ordering — that masks wiring bugs silently. Template fallbacks for backfilled display flags should use the *restrictive* value (`false` / hide), so a missing backfill surfaces visibly rather than silently showing incorrect data.
- **Composite scoring exclusion for not_scored**: Dimensions with `data_confidence == CONFIDENCE_NOT_SCORED` are excluded from both the numerator and denominator of composite scoring. This prevents both inflation (invented scores pulling average up) and deflation (zero scores pulling average down). The `_scorable` filter in `evaluate_property()` handles this.
- **Dimension name renaming** (NES-210): When renaming a `Tier2Score.name`, update ALL construction sites in the scoring function, update `TIER2_NAME_TO_DIMENSION` (keep old name as backward-compat alias), and add the old→new mapping to `_LEGACY_DIMENSION_NAMES` + `_migrate_dimension_names()` in app.py. The migration must run in ALL snapshot deserialization paths: `view_snapshot()`, `export_snapshot_json()`, `export_snapshot_csv()`, and the compare route. In `view_snapshot()`, run migration AFTER the `{**result, ...}` shallow copy to avoid mutating stored snapshot dicts.
- **Pre-computed sidebar variables**: `_result_sections.html` pre-computes `show_score`, `band_class`, `band_label`, `safety_checks`, `clear_count`, `warning_count`, `issue_count`, `safety_concerns` at template top for reuse in both main column and sidebar. When adding new sidebar data, compute it in the top block — don't duplicate Jinja filter chains inside both column and sidebar sections.
- **Template weight badge lookup**: `dimension_summaries[].name` must match persona weight keys exactly. The template looks up `result.persona.weights[dim.name]` — if the internal Tier2Score name differs from the persona weight key (e.g., was `"Third Place"` vs weight key `"Coffee & Social Spots"`), the lookup fails silently and defaults to 1.0, hiding weight badges.

### SQLite Concurrency (models.py)
- `_get_db()` sets `PRAGMA busy_timeout=30000` (30s) for write contention under concurrent gunicorn workers + evaluation threads.
- Job-critical write functions (`create_job`) retry up to 3× on `OperationalError` with "locked"/"busy" in the message, with progressive backoff. Read functions (`get_job`) retry once.
- Pattern for retry-safe DB functions: open connection inside `try`, use `finally: conn.close()`, catch `sqlite3.OperationalError` outside the connection block.
- `sqlite3.connect(timeout=N)` and `PRAGMA busy_timeout` both set the busy timeout — use only the PRAGMA (more explicit, avoids redundancy).

### Data Caches (models.py)
- Pattern: `get_<name>_cache(key) → Optional[str]` / `set_<name>_cache(key, json) → None`
- Always swallow cache errors so they never break an evaluation.
- Each cache table has its own TTL constant (`_<NAME>_CACHE_TTL_DAYS`).
- Existing caches: weather (30-day), census (90-day).

### Spatial Ingest (startup_ingest.py + scripts/ingest_*.py)
- `startup_ingest.py` calls `ingest()` directly with keyword args — scripts must accept kwargs, not just argparse.
- State filter format varies by dataset: 2-letter (`"NY"`) for EJScreen/TRI/NCES, full name (`"New York"`) for UST, FIPS code (`"36"`) for TIGER, postal abbreviation (`STABR='NY'`) for NCES. Always check the upstream API field.
- ArcGIS bbox filtering: `geometry` (JSON envelope), `geometryType=esriGeometryEnvelope`, `inSR=4326`. Server-side filter.
- Wiring pattern: lazy-import wrapper → `_table_has_data()` → `_run_ingest()`. One failure never blocks others.
- **ArcGIS polygon ring orientation**: Clockwise = outer boundary, counter-clockwise = hole. Use shoelace formula (`_ring_is_clockwise()`) to classify rings when features may have disjoint parts (e.g., school districts with enclaves). The simpler `MULTIPOLYGON(((ring1),(ring2)))` pattern used by SEMS/FEMA only works when all rings belong to one contiguous polygon.
- **Two-table join pattern** (NES-206): Spatial polygon table (`facilities_school_districts`) for point-in-polygon → extract GEOID → join to a separate lookup table (`state_education_performance`) for enrichment data. Table contains multi-state data (NY, CT, NJ) with a `state` column; GEOID is unique across states. Different from single-table spatial checks.
- **Bundled CSV for data without stable APIs**: When upstream data is only available as Access DBs or manual downloads (e.g., NYSED), ship a curated CSV in `data/` and flag as `MANUAL REFRESH` in the `dataset_registry` notes. Include refresh cadence.
- **Point geometry ingest**: For point-location datasets (e.g., NCES schools), use `MakePoint(lon, lat, 4326)` instead of `GeomFromText('POINT(...)', 4326)`. Simpler and avoids WKT string building. Geometry comes as `{x: lon, y: lat}` from ArcGIS; always fall back to attribute fields (LAT/LON) if geometry is missing.
- **Derived percentages from upstream counts**: When computing percentages from two upstream fields (e.g., TOTFRL/MEMBER for FRL%), always cap at 100% — data quality issues in federal datasets can produce numerator > denominator.
- **Template component duplication**: When the same UI component renders in multiple conditional branches (e.g., school card inside vs. outside school district section), extract into a Jinja macro in `_macros.html` immediately. Copy-paste diverges silently on the next edit.
- **Multi-state shared table idempotency**: When multiple scripts write to the same table partitioned by `state` column, never use `DROP TABLE` — use `CREATE TABLE IF NOT EXISTS` + `DELETE FROM ... WHERE state = 'X'` + INSERT. The DROP pattern destroys other states' data when run standalone.
- **Per-state data checking in startup_ingest**: When a table has rows from multiple independent ingestion sources (e.g., `state_education_performance` with NY/NJ/CT), use `_table_has_state_data(db_path, table, state)` to check each state independently. Using `_table_has_data()` (checks total rows) will skip ingestion for state B if state A's data already exists.
- **Catch `IntegrityError` in CSV ingest loops**: When inserting from bundled CSVs into tables with UNIQUE constraints, always catch `sqlite3.IntegrityError` alongside `ValueError`/`KeyError`. A duplicate key in the CSV would otherwise crash the entire ingest, leaving partial data.
- **HPMS display-name resolution** (`_build_road_display_name`): HPMS `ROUTE_ID` is a coded segment identifier (e.g., "00000001__", "14000638__"), not a road name. Use `_looks_like_route_id()` to detect coded IDs — checks for `"__"` (double underscore, universal in HPMS route_ids across states) and pure-digit strings. Fallback chain: `route_name` (e.g., "SUNRISE HWY", "US 1") → `segment.name` (if not a route_id) → `"Route {route_number}"` → `route_id` as last resort. When building Tier1Check details for any result path (FAIL, WARNING, PASS-with-detail), always call `_build_road_display_name()` — don't inline the name resolution. Multiple code paths constructing the same detail string will diverge when the resolution logic changes. **NJ caveat**: NJ HPMS route_ids use `"00000001__"` format (8 zero-padded digits + `__`), which fails Python's `str.isdigit()`. Always use `_looks_like_route_id()` instead of `isdigit()` for route_id detection.
- **HPMS "Ref Rt" prefix cleaning**: NY HPMS encodes reference routes as `"Ref Rt 907M GRAND CNTRL PKWY"`. The ingest script strips the `"Ref Rt "` prefix and the numeric code (e.g., `"907M "`) to extract the human name. Other states may use different conventions.
- **Bundled CSV GEOIDs must match TIGER exactly**: The two-table join (`facilities_school_districts` → `state_education_performance`) uses string equality on GEOID. Fabricated or misformatted GEOIDs silently produce zero matches with no error. When adding or updating bundled education CSVs, verify GEOIDs against the TIGER WMS endpoint (`MapServer/14/query?where=GEOID='NNNNNNN'`). Use `scripts/crosswalk_geoids.py` as the reference crosswalk tool.

### Comparison View (app.py + compare.html)
- **Structured differential pattern** (NES-207): Multi-snapshot comparison views compute differential data in a pure helper (`_build_comparison_data()`) called from the route handler, not in Jinja templates. The helper returns typed data structures (health grid, dimension rows, key differences) — the template only renders. This keeps business logic testable and templates simple.
- **Legacy/Phase 1B dedup in comparison grids**: When the same check exists in both legacy (`"Power lines"`) and Phase 1B spatial (`"hifld_power_lines"`) forms, use `_SPATIAL_SUPERSEDES` to skip legacy rows when the spatial version exists in any snapshot. Also deduplicate by display label (`seen_labels`) to prevent duplicate rows.
- **`score_ring` macro requires `report.css`**: The `score_ring` macro from `_macros.html` depends on `.band-exceptional`, `.band-strong`, etc. classes defined in `report.css`. Any template using the macro must load `report.css` even if it doesn't render full report sections.
- **Comparative verdict** (NES-218): `_build_comparative_verdict()` is a pure function that synthesizes headline + body from already-computed comparison data. It does NOT call APIs or touch the DB. When adding new comparison prose, add a branch to this function and a corresponding unit test — don't put text-generation logic in the template.
- **Branch-priority ordering for score spreads**: When multiple `if spread <= N` branches exist, check tighter thresholds first (e.g., `<= 3` before `<= 5`) to avoid the looser condition swallowing the tighter one. This is a common bug in cascading numeric thresholds — always order from most specific to least specific.

### Quality Ceiling (scoring_config.py + property_evaluator.py)
- **Quality ceiling pattern**: `QualityCeilingConfig` caps a dimension's max score based on venue diversity + review depth. Applied *before* `_apply_confidence_cap()` so both constraints compose. To add a ceiling to another dimension: add `quality_ceiling=QualityCeilingConfig(...)` to its `DimensionConfig`, then call `_compute_quality_ceiling()` between the raw score and the confidence cap.
- **Threshold reachability**: Config thresholds must be reachable by the upstream classifier. If `_classify_coffee_sub_type()` returns at most 3 distinct types, a `(4, bonus)` diversity threshold is dead code. Always verify the input domain before defining threshold tiers.
- **Pre-filtered inputs shift threshold floors**: `eligible_places` is already filtered to `reviews >= 30` and `rating >= 4.0` before reaching the ceiling. Depth thresholds near the filter floor (e.g., `(50, 1.0)`) will almost always trigger. Account for upstream filters when tuning thresholds.

### Display Thresholds (scoring_config.py)
- `WALK_DRIVE_BOTH_THRESHOLD` and `WALK_DRIVE_ONLY_THRESHOLD` in `scoring_config.py` are the canonical walk/drive time display thresholds. All display logic (templates, drive-time fetching) should reference these, not hardcode magic numbers.
- **Scoring thresholds ≠ display thresholds**: `WALK_TIME_MARGINAL` (30 min, `green_space.py`) controls the walk-time *scoring curve*. `WALK_DRIVE_BOTH_THRESHOLD` (20 min) controls when drive times are *fetched and shown*. Don't conflate them — a constant can share a numeric value with a display threshold but serve a different purpose (scoring vs presentation).
- Transit drive-time fetch uses its own hardcoded threshold (`> 20` in `find_primary_transit`) — intentionally independent of the display constants. It follows a walk-primary/drive-secondary pattern where both are always shown when drive time exists.

## Decision Log

| Date | Decision | Rationale |
|------|----------|-----------|
| 2026-02 | DB-backed job queue | Safe with gunicorn workers > 1 |
| 2026-02 | 25s API timeout | Prevents indefinite hangs |
| 2026-02 | Census data is informational only | ACS demographics shown as context, never scored — avoids bias in property ratings |
| 2026-03 | Bbox filter for HIFLD/FRA ingest | Nationwide data (94K+/100K+ rows) too large for 5GB Railway volume; scope to Westchester area |
| 2026-03 | `railpack.json` for system deps | Railway uses Railpack (not Nixpacks); `nixpacks.toml` is silently ignored. Runtime apt packages go in `deploy.aptPackages` or `RAILPACK_DEPLOY_APT_PACKAGES` env var |
| 2026-03 | NYSED data as bundled CSV | NYSED publishes bulk data as Access DBs only (no API). Curated CSV for ~40 Westchester districts is pragmatic; refresh annually after Report Card release (~Dec) |
| 2026-03 | School district data is informational only | Like census demographics, shown as context under "Area Context" divider — never scored. FHA architectural separation from rated dimensions |
| 2026-03 | PostToolUse hook for ruff auto-format | Catches the last 10% of formatting issues Claude misses; `|| true` ensures it never blocks work |
| 2026-03 | Renamed `/review` → `/code-review` | Custom command was shadowing the built-in PR review; custom commands must use unique names |
| 2026-03 | Health checks promoted to top of report (NES-214) | Primary differentiator was buried at position #11. Now `id="health-safety"` section after Summary Narrative. Proximity & Environment dissolved: sidewalk→Getting Around, EJScreen→Area Context |
| 2026-03 | Centralized walk/drive display thresholds (NES-213) | `WALK_DRIVE_BOTH_THRESHOLD=20` and `WALK_DRIVE_ONLY_THRESHOLD=40` in `scoring_config.py`. Lowered park drive-time fetch from 30→20 to align with display band |
| 2026-03 | Compare view structured differentials (NES-207) | Replaced side-by-side full reports with health grid + dimension scores + key differences. Cuts 1,210 lines of `_result_sections.html` per column. Zero API cost — pure presentation over existing snapshots |
| 2026-03 | Comparative verdict as pure function (NES-218) | `_build_comparative_verdict()` synthesizes headline+body from existing comparison data. 6 priority-ordered branches (tier1 failure → health disparity → score spread). Pure function for testability, not a template filter |
| 2026-03 | Tri-state expansion (NY+CT+NJ) | All spatial datasets expanded from Westchester/NY to tri-state. State-filtered datasets use `states` list with IN clauses; bbox-filtered use `(-75.6, 38.9, -71.8, 42.1)`. Education performance uses shared `state_education_performance` table with per-state idempotent ingestion |
| 2026-03 | Quality ceiling for Coffee & Social Spots | Proximity alone shouldn't yield 10/10 with only delis. `QualityCeilingConfig` caps score via diversity + depth bonuses. Applied before confidence cap. Model version bumped to 1.5.0 |
| 2026-03 | Three-tier confidence system (Phase 3) | Replaced ad-hoc HIGH/MEDIUM/LOW with `verified`/`estimated`/`not_scored`. Estimated caps at 8/10, not_scored excluded from composite entirely. `_migrate_confidence_tiers()` handles legacy snapshots. Road noise changed from invented 7/10 fallback to not_scored |
| 2026-03 | HPMS road name display | HPMS `route_name` field has good coverage for high-AADT segments (e.g., "9A", "SUNRISE HWY", "FDR DRIVE"). Stored in both `name` column and `metadata_json.route_name`. `route_number` + `route_signing` provide fallback. Requires re-ingest for existing spatial.db data |
| 2026-03 | Health check citations in scoring_config | `HEALTH_CHECK_CITATIONS` dict maps check names → list of `{label, url}` sources. Rendered in "Why we check this" expandable. URLs must be verified as live before merge — gov sites restructure frequently |
| 2026-03 | Added "coffee_shop" Places API type | Google treats `coffee_shop` as distinct from `cafe` — many coffee chains (Blank Street, etc.) are only typed `coffee_shop`. Must search all three types (`cafe`, `bakery`, `coffee_shop`) to avoid zero-result gaps in dense urban areas |
| 2026-03 | Smooth piecewise scoring curves (Phase A2) | Replaced hardcoded step tables in coffee/grocery/fitness with `apply_piecewise()` from `scoring_config.py`. Eliminates cliff-edge score jumps (e.g., 10→7 at 16 min). Fitness uses multiplicative model: `base_curve × quality_multiplier`. All piecewise results rounded to int at `Tier2Score` boundary |
| 2026-03 | Two-column report layout with sidebar | `_result_sections.html` uses `report-grid` (CSS grid: `1fr 340px`). Main column has all content sections; sidebar has verdict card, health summary, walk scores, and map. Pre-compute sidebar variables (`show_score`, `band_class`, `safety_checks`, counts) at template top to avoid duplicate queries. `.report-layout` class hides internal sidebar when external rail exists (`@media min-width: 1200px`). Collapses to single column at 768px |

### Safari Mobile / Viewport (iOS)
- `_base.html` sets `viewport-fit=cover` — required for `env(safe-area-inset-*)` to work. Do not remove.
- Never use bare `100vh` for layout heights; always add a `100dvh` override on the next line. Safari iOS `100vh` includes the URL bar's hidden space, which breaks scroll detection and makes the address bar stick in its collapsed state.
- Fixed-position elements pinned to `bottom: 0` must include `padding-bottom: calc(<normal> + env(safe-area-inset-bottom, 0px))` so they clear Safari's bottom bar and home indicator. Currently applied to: cookie banner (`base.css`), compare tray (`_compare_tray.html`).
- When adding new `position: fixed; bottom: 0` elements, follow the same `env()` pattern.

## Workflow Orchestration

### 1. Plan Mode Default
- Enter plan mode for ANY non-trivial task (3+ steps or architectural decisions)
- If something goes sideways, STOP and re-plan immediately — don't keep pushing
- Use plan mode for verification steps, not just building
- Write detailed specs upfront to reduce ambiguity

### 2. Subagent Strategy
- Use subagents liberally to keep main context window clean
- Offload research, exploration, and parallel analysis to subagents
- For complex problems, throw more compute at it via subagents
- One task per subagent for focused execution

### 3. Self-Improvement Loop
- After ANY correction from the user: update CLAUDE.md with the pattern
- Write rules that prevent the same mistake
- Ruthlessly iterate on these lessons until mistake rate drops

### 4. Verification Before Done
- Never mark a task complete without proving it works
- Diff behavior between main and your changes when relevant
- Ask yourself: "Would a staff engineer approve this?"
- Run tests, check logs, demonstrate correctness

### 5. Demand Elegance (Balanced)
- For non-trivial changes: pause and ask "is there a more elegant way?"
- If a fix feels hacky: "Knowing everything I know now, implement the elegant solution"
- Skip this for simple, obvious fixes — don't over-engineer

## Core Principles

- **Simplicity First**: Make every change as simple as possible. Impact minimal code.
- **No Laziness**: Find root causes. No temporary fixes. Senior developer standards.
- **Minimal Impact**: Changes should only touch what's necessary. Avoid introducing bugs.

## When Unsure

- Ask clarifying questions before implementing
- Check existing patterns in the codebase first
- Prefer simple solutions over clever ones
