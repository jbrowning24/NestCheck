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

## Decision Log

| Date | Decision | Rationale |
|------|----------|-----------|
| 2026-02 | DB-backed job queue | Safe with gunicorn workers > 1 |
| 2026-02 | 25s API timeout | Prevents indefinite hangs |

## When Unsure

- Ask clarifying questions before implementing
- Check existing patterns in the codebase first
- Prefer simple solutions over clever ones
