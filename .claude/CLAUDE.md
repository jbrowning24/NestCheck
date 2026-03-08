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

## Coding Standards

- Python: Follow existing patterns in property_evaluator.py
- Use type hints for function signatures
- Add docstrings for public functions
- No print() in production - use logging
- All API calls need timeout handling
- Spatial metadata values may arrive as strings after JSON round-tripping — cast to `float()` before numeric formatting (`:,.0f`)
- When changing template element IDs, update `smoke_test.py` markers (`LANDING_REQUIRED_MARKERS`, `SNAPSHOT_REQUIRED_MARKERS`) in the same commit. Mismatches cause silent post-deploy smoke test failures.
- When removing HTML elements from templates, remove the corresponding CSS rules in the same commit. Orphaned selectors (e.g., `.snippet-assessment-score` after removing the score div) accumulate silently.
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

### Narrative Insights (NES-191+)
- Insight generators are pure functions: `dict → str | None`. Keep them side-effect-free for testability.
- Place insight logic in dedicated modules (not `app.py`) — `app.py` is for routes/views.
- Avoid duplicating utility helpers across modules (e.g., Oxford-comma join) — use a shared module.

### Check Display Metadata (app.py)
- Each Tier1Check `name` in `property_evaluator.py` needs entries in app.py: `_SAFETY_CHECK_NAMES`, `_CLEAR_HEADLINES`, `_ISSUE_HEADLINES`, `_WARNING_HEADLINES`, `_HEALTH_CONTEXT`.
- Only add headline entries for result states the check can actually produce. `_build_health_context()` returns `None` silently for missing keys.
- **Naming split**: Legacy checks use display names (`"Power lines"`, `"Gas station"`). Phase 1B spatial checks use `snake_case` (`"ust_proximity"`, `"hifld_power_lines"`). Match the convention of the source check function.
- New checks NOT in `_CHECK_SOURCE_GROUP` render individually (not collapsed).
- **Tier1Check serialization paths**: `Tier1Check` is serialized in three places — `result_to_dict()` (main snapshot), the compare route's serialization loop, and CSV export. When adding a new field to the dataclass, update ALL three. The compare path is easy to miss.
- **Search radius vs threshold** (NES-203): Search radius can be wider than the warning threshold to report "Nearest: X (Y ft)" on PASS. Set `show_detail=True` on those PASS results. When nothing is found even within the expanded radius, the detail string should match the `_CLEAR_HEADLINES` wording (use the threshold distance, not the search radius).
- **Presentation-layer suppression** (NES-196): To hide checks from display without changing evaluation or storage, filter in the route handler (e.g., `view_snapshot()`), not in `present_checks()` or `result_to_dict()`. Use `result = {**result, ...}` to shallow-copy the deserialized snapshot dict before modifying — never mutate it in-place, as a future caching layer would silently corrupt shared state. Suppressed metadata (e.g., count) should travel inside `result` dict, not as a separate template var, so Jinja includes and macros can access it without relying on inherited scope. Apply suppression to ALL routes that render the same data (snapshot, compare-health, etc.) to avoid inconsistent UX.
- **Confidence score caps** (NES-sparse-data): Dimension scores from data-confidence-aware scorers must be passed through `_apply_confidence_cap(score, confidence)` before building the `Tier2Score`. LOW caps at 6/10, MEDIUM at 8/10, HIGH uncapped. Apply consistently to every dimension that classifies confidence — omitting it lets sparse data produce artificially high ratings.

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
- **Two-table join pattern** (NES-206): Spatial polygon table (`facilities_school_districts`) for point-in-polygon → extract GEOID → join to a separate lookup table (`nysed_performance`) for enrichment data. Different from single-table spatial checks.
- **Bundled CSV for data without stable APIs**: When upstream data is only available as Access DBs or manual downloads (e.g., NYSED), ship a curated CSV in `data/` and flag as `MANUAL REFRESH` in the `dataset_registry` notes. Include refresh cadence.
- **Point geometry ingest**: For point-location datasets (e.g., NCES schools), use `MakePoint(lon, lat, 4326)` instead of `GeomFromText('POINT(...)', 4326)`. Simpler and avoids WKT string building. Geometry comes as `{x: lon, y: lat}` from ArcGIS; always fall back to attribute fields (LAT/LON) if geometry is missing.
- **Derived percentages from upstream counts**: When computing percentages from two upstream fields (e.g., TOTFRL/MEMBER for FRL%), always cap at 100% — data quality issues in federal datasets can produce numerator > denominator.
- **Template component duplication**: When the same UI component renders in multiple conditional branches (e.g., school card inside vs. outside school district section), extract into a Jinja macro in `_macros.html` immediately. Copy-paste diverges silently on the next edit.

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
| 2026-03 | NCES replaces Google Places for school discovery | NCES EDGE ArcGIS API provides geocoded school locations (zero API calls at eval time vs ~200+ Google Places calls). 2022-23 vintage is acceptable for established schools; show data year in attribution |

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
