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

1. `/create-issue` - Capture bugs/features fast
2. `/exploration-phase` - Understand before building
3. `/create-plan` - Markdown plan with status tracking
4. `/execute-plan` - Hand off to Composer with @plan-file.md
5. `/review` - Self-review the changes
6. Get external review from Codex (branch review)
7. `/peer-review` - Evaluate combined feedback

## Coding Standards

- Python: Follow existing patterns in property_evaluator.py
- Use type hints for function signatures
- Add docstrings for public functions
- No print() in production - use logging
- All API calls need timeout handling
- Spatial metadata values may arrive as strings after JSON round-tripping — cast to `float()` before numeric formatting (`:,.0f`)
- When changing template element IDs, update `smoke_test.py` markers (`LANDING_REQUIRED_MARKERS`, `SNAPSHOT_REQUIRED_MARKERS`) in the same commit. Mismatches cause silent post-deploy smoke test failures.

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

### Data Caches (models.py)
- Pattern: `get_<name>_cache(key) → Optional[str]` / `set_<name>_cache(key, json) → None`
- Always swallow cache errors so they never break an evaluation.
- Each cache table has its own TTL constant (`_<NAME>_CACHE_TTL_DAYS`).
- Existing caches: weather (30-day), census (90-day).

### Spatial Ingest (startup_ingest.py + scripts/ingest_*.py)
- `startup_ingest.py` calls `ingest()` directly with keyword args — scripts must accept kwargs, not just argparse.
- State filter format varies by dataset: 2-letter (`"NY"`) for EJScreen/TRI, full name (`"New York"`) for UST. Always check the upstream API field.
- ArcGIS bbox filtering: `geometry` (JSON envelope), `geometryType=esriGeometryEnvelope`, `inSR=4326`. Server-side filter.
- Wiring pattern: lazy-import wrapper → `_table_has_data()` → `_run_ingest()`. One failure never blocks others.

## Decision Log

| Date | Decision | Rationale |
|------|----------|-----------|
| 2026-02 | DB-backed job queue | Safe with gunicorn workers > 1 |
| 2026-02 | 25s API timeout | Prevents indefinite hangs |
| 2026-02 | Census data is informational only | ACS demographics shown as context, never scored — avoids bias in property ratings |
| 2026-03 | Bbox filter for HIFLD/FRA ingest | Nationwide data (94K+/100K+ rows) too large for 5GB Railway volume; scope to Westchester area |
| 2026-03 | `railpack.json` for system deps | Railway uses Railpack (not Nixpacks); `nixpacks.toml` is silently ignored. Runtime apt packages go in `deploy.aptPackages` or `RAILPACK_DEPLOY_APT_PACKAGES` env var |

## When Unsure

- Ask clarifying questions before implementing
- Check existing patterns in the codebase first
- Prefer simple solutions over clever ones
