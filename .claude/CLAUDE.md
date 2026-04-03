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
├── cli.py              # CLI entry point (python cli.py evaluate "...")
├── overflow.py         # Presentation-layer list truncation utility (NES-263)
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

Full-length versions: `docs/CLAUDE-DECISION-ARCHIVE.md`

- Follow existing patterns in `property_evaluator.py`. Type hints, docstrings, no `print()`, timeouts on all API calls.
- **No predictable secret defaults**: Use `os.environ.get("VAR")` (returns `None`), not `get("VAR", "default")`. Guard with `if VAR`.
- **SQL table names must use whitelists**: Validate against `_VALID_FACILITY_TYPES` before f-string interpolation. Add new types in same commit.
- **Never store raw `str(e)` in user-visible DB fields**: Use `_sanitize_error(e)` in `worker.py`. Full details to `logger.exception` only.
- **Class-level caches need eviction**: Use `OrderedDict` LRU or `lru_cache`. Reference: `urban_access.py` `_cache_set()`.
- **`lru_cache` on spatial.db metadata must be invalidated after ingestion**: Add `fn.cache_clear()` in `startup_ingest.py`.
- **Module-level caches must return copies**: Return shallow copies on cache hit to prevent caller mutation corrupting the cache.
- **scoring_config ↔ property_evaluator import sync**: Update `from scoring_config import (...)` in same commit as new constants.
- Template element ID changes → update `smoke_test.py` markers in same commit.
- Removing HTML → remove corresponding CSS in same commit. Promoting CSS to `base.css` → remove page-specific dupes.
- **Reverting a migration must restore ALL artifacts**: `git diff` across ALL files, then invert every change.
- Inlining logic that replaces helpers → grep for old function name, delete if zero call sites remain.
- External links always need `rel="noopener noreferrer"` on `target="_blank"`.
- **Score display**: `/10` scores as integers (`%.0f`). Google star ratings keep one decimal (`%.1f`).
- **No hover effects on non-interactive elements**: Only add `:hover` transitions to genuinely clickable elements.
- **Use `color` tokens for text hierarchy, not `opacity`**: Reserve `opacity` for overlays and disabled states only.
- Relocating template sections → update surrounding copy (headings, divider descriptions) to reflect new contents.
- Frontend `fetch()` must check `resp.ok` and content-type before `.json()`. Guard non-JSON error responses.
- Frontend polling loops must retry on transient errors with a cap. Jobs may not be visible for 1-2 poll cycles.
- **Duplicate Flask route URLs shadow silently**: Grep `@app.route` for the URL before adding a new POST endpoint.
- Flask error handlers must return JSON when `_wants_json()` is true. Add for 400, 404, 500 at minimum.
- **Removing env var fallbacks requires deployment coordination**: Verify var is set in all envs before removing fallback.
- **Local commits on `main` get overwritten by PR merges**: Use a branch + PR for changes that must survive concurrent merges.
- **Never use synthetic DOM events**: Call the handler function directly instead of `dispatchEvent(new Event(...))`.
- **Template ↔ backend data contract**: Grep backend for field name before writing Jinja code that consumes it.
- **Three template data mechanisms**: (1) `jinja_env.globals` for static config, (2) `render_template(key=val)` per-route, (3) `result` dict for per-eval data.
- **Canonical domain redirect**: Add infra endpoints (webhooks, health probes) to `_CANONICAL_EXEMPT_PATHS` in `app.py`.
- **Jinja2 `| safe` macros must document XSS contract**: External data MUST be escaped via `markupsafe.escape()` first.
- **Jinja2 cannot import underscore-prefixed macros**: Use public names (e.g., `a_an` not `_a_an`).
- **Jinja2 macro names must not collide with context variables**: Use verb prefixes (`freshness_caption`, not `section_freshness`).
- **Avoid `*:hover` universal selectors**: Scope hover to actual parent elements (`a:hover .icon`).
- **Token replacement on dark backgrounds must check contrast**: Verify resolved value against the element's background color.
- **Supported-state lists must derive from `COVERAGE_MANIFEST`**, not hardcoded sets that drift silently.
- **Cached snapshot reuse must replicate side effects**: New worker side effects must also go in cached-snapshot path in `app.py:index()`.
- **`_prepare_snapshot_for_display()` is the canonical migration pipeline**: 7 deserialization paths must all use it.

## Key Patterns

Full-length versions: `docs/CLAUDE-DECISION-ARCHIVE.md`

### Async Evaluation (job queue)
- POST `/` creates job → returns `{job_id}`. GET `/job/<id>` for polling (`queued|running|done|failed`).
- `worker.py`: one background thread per gunicorn worker. Polls, claims atomically, runs `evaluate_property()`, saves snapshot.
- **Worker watchdog**: `before_request` checks `ensure_worker_alive()` every 30s. Dead worker thread is silent — jobs queue forever.
- Frontend: POST → poll every 2s → show stage text → redirect to `/s/{snapshot_id}` on done.

### API Clients
- `GoogleMapsClient` wraps all Maps API calls. Always use `timeout=API_REQUEST_TIMEOUT`. Handle quota errors gracefully.
- **Non-physical place filtering**: `places_nearby()`/`text_search()` centrally filter closed + online-only businesses. Add to `_ONLINE_BUSINESS_EXACT_NAMES`.
- **Heuristic filters must return reason strings** (not just bool) for audit via `TraceContext.filtered_places`.
- **Google `radius` is a bias, not a strict filter**: Always validate proximity with `_distance_feet()` (haversine) before accepting.
- **Supplemental Text Search**: Nearby Search caps at 20 results. Add `text_search()` alongside `places_nearby()` for each dimension.
- **Coffee/grocery/fitness discovery parity**: All three need both haversine post-filter + supplemental `text_search("...", 8000m)`.
- **OSM queries must include both `node` and `way`**: Amenities like playgrounds are often mapped as area polygons.
- **Census place resolution order**: Incorporated Places → CDPs → County Subdivisions. MI townships are MCDs (3rd tier).
- **COUSUB FIPS codes are unique per county, not per state**: Include county FIPS in cache keys.
- **Census place name cleaning**: Strip type suffixes. Order longer patterns before shorter (`charter township` before `township`).
- **ACS vintage pinning**: When bumping `_ACS_BASE` year, verify all variable codes still exist in the new schema.
- **Venue cache write**: New `places_nearby()`/`text_search()` calls need entries in `_PLACE_TYPE_TO_CATEGORY`/`_TEXT_QUERY_CATEGORY_RULES`.
- **Venue cache read**: Checks `VenueCache.query_venues()` before API calls. TTLs: 30d businesses, 90d public amenities.
- **Walk time cache**: `WalkTimeCache` in `spatial_data.py`. Keyed by rounded origin + `place_id`. Partial hits supported. TTLs: 180d walk, 90d drive.
- **`walking_times_batch` spans multiple modules**: Called from both `property_evaluator.py` and `green_space.py`. Grep all modules when changing params.

### Venue Scoring Calibration (scoring_config.py + property_evaluator.py)
- **Eligibility thresholds**: `VENUE_MIN_REVIEWS`/`VENUE_MIN_RATING` gate scoring only — sub-threshold venues still shown in display.
- **Search types ↔ eligibility types must match**: Every type in the eligibility filter needs a `places_nearby()` query upstream.
- **Excluded types must sync across scoring + snapshot functions**: Update both `score_*()` and `get_neighborhood_snapshot()`.
- **Type filters before rating/review filters**: Misclassified businesses (e.g., real estate tagged `gym`) removed from both scoring AND display.
- **Quality ceiling**: `QualityCeilingConfig` caps score via sub-type diversity + social bucket diversity + review depth. Base(4) + bonuses, cap 10.
- **Suppressed dimensions**: No eligible venues → `Tier2Score(points=None, suppressed_reason=...)`. Template shows "—", excluded from composite.
- **Drive-time scoring**: All venue dims have drive fallback. Pattern: walk score → quality ceiling (coffee only) → `max(walk, drive)` → `DRIVE_ONLY_CEILING(6)`.
- **Coffee ceiling ordering**: `walk → quality_ceiling → max(ceilinged_walk, drive)` — ceiling must NOT apply to drive score.

### Check Display Metadata (app.py)
- New `Tier1Check.name` needs entries in `_SAFETY_CHECK_NAMES`, `_CLEAR_HEADLINES`, `_ISSUE_HEADLINES`, `_WARNING_HEADLINES`, `_HEALTH_CONTEXT`.
- Legacy checks use display names (`"Power lines"`). Phase 1B spatial checks use snake_case (`"hifld_power_lines"`).
- **Hazard tier**: `_TIER_2_CHECKS` = area-level (EJScreen). All others default Tier 1. Backfill `hazard_tier` in `view_snapshot()`.
- **Tier1Check serialized in 3 places**: `result_to_dict()`, compare route, CSV export. Update ALL when adding fields.
- **Nullable field propagation**: Audit all consumers (`sum()`, `f"{x}"`, `score/max`, serialization) when widening to `Optional`.
- **Cascading distance filters need explicit upper bounds**: Both lower AND upper bound required to prevent silent zone extension.
- **Presentation-layer suppression**: Filter in route handler, not `present_checks()`. Shallow-copy first. Apply to ALL rendering routes.
- **Required checks bypass suppression**: Set `required=True` on checks that must never be silently omitted (flood, superfund).
- **Confidence caps**: `_apply_confidence_cap()` before building `Tier2Score`. Estimated→8/10, verified→uncapped, not_scored→excluded.
- **`apply_piecewise` → round to int**: Every scoring path must round at `Tier2Score` boundary: `int(max(cfg.floor, score) + 0.5)`.
- **Snapshot migrations must run on shallow copies**: `{**snapshot["result"]}` first. Wire into ALL deserialization paths.
- **Shallow copy only covers top-level keys**: Nested dicts/lists are shared refs. Copy nested structures before mutating.
- **Shared helpers for serialization + backfill**: Extract to module-level (e.g., `_dim_band()`). Don't duplicate inside `result_to_dict()`.
- **Backfill ordering matters**: Derived fields must run AFTER the migration they depend on. Template defaults should be restrictive.
- **EJScreen cross-refs**: `_EJSCREEN_CROSS_REFS` maps check names → EJScreen fields. Threshold: 60th pctl. Runs AFTER hazard_tier backfill.
- **Composite scoring**: Equal-weight. `not_scored` excluded from both numerator and denominator.
- **Dimension renaming**: Update ALL construction sites, `TIER2_NAME_TO_DIMENSION`, `_LEGACY_DIMENSION_NAMES`, all deserialization paths.
- **Sidebar variables**: Pre-compute at template top. Don't duplicate filter chains in column and sidebar.
- **JSON-LD**: Pre-filter loops into `{% set %}` to avoid trailing commas. `BreadcrumbList` requires absolute URLs.
- **HTML closing tags must stay inside their Jinja branch**: Stray `</div>` after `{% endif %}` breaks layout silently.
- **Cross-`try`-block variable scoping**: Initialize shared variables before the first `try` block.
- **OG image generation must never block job completion**: Runs AFTER `complete_job()`, wrapped in `try/except`.

### Schema Migrations (models.py `init_db()`)
- **`CREATE TABLE IF NOT EXISTS` never updates existing tables**: Every migration-added column needs `ALTER TABLE ADD COLUMN`.
- **Pattern**: PRAGMA table_info → ALTER TABLE if missing → CREATE INDEX IF NOT EXISTS. Consolidate PRAGMA calls per table.
- `/healthz` must always return 200 (liveness probe). Never block deployment with non-200 for missing env vars.
- Deployment failures: read Deploy Logs first, not Build Logs. Healthcheck timeouts are a symptom.

### Spatial Ingest (startup_ingest.py + scripts/ingest_*.py)
- `startup_ingest.py` calls `ingest()` with kwargs. Scripts must accept kwargs, not just argparse.
- State filter format varies: 2-letter (EJScreen/TRI), full name (UST), FIPS (TIGER), STABR (NCES). Check upstream field.
- **UST state name inconsistency**: `"NewYork"` vs `"New Jersey"`. `ingest_ust.py` handles both; `_build_state_normalizer()` fixes at insert. DC is stored as `"Washington DC"` (not `"District of Columbia"`) — handled via `_UST_STATE_ALIASES`.
- **Per-state missing detection required**: Use `_missing_states_abbr()`/`_missing_states_fips()` for multi-state tables. `_table_has_data()` is insufficient.
- **Normalizing stored data → update all downstream readers in same commit**: Grep old value pattern across entire project.
- **ArcGIS bbox is an AND filter with WHERE**: State-filtered startup wrappers must NOT pass bbox.
- **New state checklist**: (1) `TARGET_STATES`, (2) CSV + ingest script, (3) `_STATE_EDUCATION_INGEST`, (4) `crosswalk_geoids.py`, (5) no bbox.
- Wiring: lazy-import → `_table_has_data()` → `_run_ingest()`. One failure never blocks others.
- **SpatiaLite DDL is NOT idempotent**: Wrap `AddGeometryColumn()`/`CreateSpatialIndex()` in `try/except`.
- **ArcGIS polygon rings**: Clockwise = outer boundary, counter-clockwise = hole. Use `_ring_is_clockwise()`.
- **Two-table join**: Spatial polygon → GEOID → lookup table. GEOIDs unique across states.
- **Bundled CSV**: For data without stable APIs. Flag as `MANUAL REFRESH` in `dataset_registry`.
- **Point geometry**: Use `MakePoint(lon, lat, 4326)` not `GeomFromText`. Fall back to attribute fields if geometry missing.
- **ArcGIS field name drift**: Fields rename between releases. Check with `outFields=*&resultRecordCount=1` before hardcoding. ParkServe removed `State` field entirely — now derive from `park_place_fips` (first 2 digits = state FIPS).
- **NCES suppression codes**: Negative integers (`-1`, `-2`) in numeric fields. Filter `< 0` before arithmetic.
- **Derived percentages**: Cap at 100%, filter negatives.
- Extract duplicated template components into Jinja macros immediately. Inline HTML strings in macros need `| safe`.
- **Multi-state shared tables**: Never `DROP TABLE`. Use `DELETE FROM ... WHERE state = 'X'` + INSERT.
- **Per-state data checking**: Use `_table_has_state_data()` not `_table_has_data()` for multi-source tables.
- **Catch `IntegrityError` in CSV ingest loops** alongside `ValueError`/`KeyError`.
- **HPMS road names**: Use `_build_road_display_name()`. Use `_looks_like_route_id()` not `isdigit()`.
- **Bundled CSV GEOIDs must match TIGER exactly**: Verify with `crosswalk_geoids.py`.
- **EJScreen**: EPA endpoint removed Feb 2025. PEDP fallback at `services2.arcgis.com`. V2.32: CANCER/RESP → RSEI_AIR.
- **ArcGIS WHERE clauses fail silently on value mismatches**: Verify with `returnCountOnly=true` first.
- **FEMA NFHL**: Chunk bboxes to ≤0.5°. Per-metro ingestion via `METRO_TO_STATES`. Version-based re-ingestion. DMV area is much denser than NYC — even 0.1° cells with 100-record pages fail; may need smaller cells or bulk download instead of REST API.
- **`TARGET_STATES` is single source of truth**: One dict entry to add a new state. FEMA uses per-metro bboxes.
- **`json_extract()` is expensive**: Never in page-rendering paths. Use static config for display, DB queries for admin only.
- **Don't declare planned-but-not-started sources in `_SOURCE_METADATA`**: Phantom coverage penalties.
- **Never run `create_facility_table()` concurrently**: Serialized via `startup_ingest.py`.
- **`create_facility_table()` drops the existing table**: Never use `flask ingest -d <X> --state <S>` for per-state ingestion of multi-state tables (TRI, UST, EJScreen, etc.) — it will destroy all other states' data. Use `startup_ingest` wrappers which pass all `TARGET_STATES` at once.
- **Coverage manifest auto-sync**: `sync_manifest_from_db()` after ingestion. Skips national/FEMA datasets.

### Quality Ceiling (scoring_config.py + property_evaluator.py)
- Formula: `base(4) + sub_type_bonus + social_bucket_bonus + depth_bonus`, capped at 10. Applied before confidence cap.
- **Threshold reachability**: Sub-type diversity max 3. Social bucket max 5. Verify input domain before defining tiers.
- **Pre-filtered inputs shift floors**: Eligible places already filtered to reviews≥15, rating≥4.0. Account for upstream filters.

### Display Thresholds (scoring_config.py)
- Walk/drive tiers: walk-only (≤20), walk-first (20–25), drive-first (25–40), drive-only (>40). Use constants, not magic numbers.
- **Scoring thresholds ≠ display thresholds**: `WALK_TIME_MARGINAL` (30) = scoring curve. `WALK_DRIVE_BOTH_THRESHOLD` (20) = display.
- Transit drive-time fetch: own hardcoded `> 20` threshold, intentionally independent of display constants.
- **Transit search radii**: `train_station`/`transit_station` → 16km. `subway_station`/`light_rail_station` → 5km. Add to `TRANSIT_SEARCH_RADII`.
- **`_classify_mode()` keyword ordering**: Commuter rail keywords checked BEFORE generic `"metro"` → Subway branch.
- **Transit display fallback**: `urban_access.primary_transit` (rail) → `transit_access.primary_stop` (all transit, closest by walk).
- **Display-time derivation**: Cross-cutting widgets derived in `view_snapshot()`, not stored. Pattern: `_build_*(result) → dict | None`.
- **`_best_walk_time()` filters by `rating is not None`**: Excludes placeholder "No X nearby" entries with `walk_time_min: 0`.

### CI Pipeline (`.github/workflows/ci.yml`)
- **Three jobs**: `scoring-tests` (merge gate), `browser-tests` (Playwright), `ground-truth-validation` (when `spatial.db` available).
- **Makefile mirrors CI**: `make test-scoring`, `make test-browser`, `make validate`, `make ci`. Run `make test-scoring` before push.
- `spatial.db` not in CI (`.gitignore`). `conftest.py` loads Flask app for all tests — CI sets `SECRET_KEY`/`GOOGLE_MAPS_API_KEY`.
- **New tables → add to `_fresh_db` fixture cleanup list** in `tests/conftest.py`. New test files → update CI + Makefile in same commit.
- **Schema migration test**: New columns → DON'T update `_OLDEST_SCHEMA`. New tables → DO copy into `_OLDEST_SCHEMA`.
- 3 pre-existing test failures in `test_drive_time_fallback.py`/`test_data_confidence.py` — MagicMock setup issues, not scoring bugs.

### Safari Mobile / Viewport (iOS)
- `viewport-fit=cover` in `_base.html` required for `env(safe-area-inset-*)`. Do not remove.
- Never use bare `100vh`. Always add `100dvh` override on next line.
- `position: fixed; bottom: 0` → add `padding-bottom: calc(<normal> + env(safe-area-inset-bottom, 0px))`.


## Decision Log

Full history: `docs/CLAUDE-DECISION-ARCHIVE.md`

Recent active decisions kept here — archive entries once their lessons are encoded in Coding Standards or Key Patterns.

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

- **Simplicity Bias**: Before implementing any solution, ask: "How can we make this simpler and dumber while still achieving the goal?" Prefer the dumbest thing that works. If a feature needs a config system, ask if a hardcoded value works first. If a function needs three parameters, ask if it can work with one. Complexity must be justified — simplicity is the default.
- **No Laziness**: Find root causes. No temporary fixes. Senior developer standards.
- **Minimal Impact**: Changes should only touch what's necessary. Avoid introducing bugs.

## When Unsure

- Ask clarifying questions before implementing
- Check existing patterns in the codebase first
- Prefer simple solutions over clever ones
