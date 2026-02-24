# AGENTS.md

## Cursor Cloud specific instructions

### Overview

NestCheck is a Python/Flask web app that evaluates U.S. address livability. Single service — no Docker, no external databases, no monorepo.

### Running the app

```bash
python3 app.py
# Starts Flask dev server on http://localhost:5001 (debug mode via FLASK_DEBUG=1)
```

The app uses SQLite (auto-created `nestcheck.db`), so no database setup is needed.

### Running tests

```bash
pytest tests/ -v
```

Tests use mocked APIs and a temporary SQLite DB — no API keys required. Seven test files currently fail to collect due to stale imports from refactored code (`test_census.py`, `test_insights.py`, `test_models.py`, `test_payments.py`, `test_scoring_regression.py`, `test_worker.py`, `test_zillow_graphql.py`). This is a known pre-existing issue. To skip them:

```bash
pytest tests/ -v --ignore=tests/test_census.py --ignore=tests/test_insights.py --ignore=tests/test_models.py --ignore=tests/test_payments.py --ignore=tests/test_scoring_regression.py --ignore=tests/test_worker.py --ignore=tests/test_zillow_graphql.py
```

### Environment variables

Copy `.env.example` to `.env`. The only required variable for full functionality is `GOOGLE_MAPS_API_KEY`. Without it, the app still starts and serves pages, but address evaluations will fail with a user-friendly error. Tests do not require it (they use `fake-key-for-tests`).

### System dependencies

`libspatialite-dev` and `libsqlite3-mod-spatialite` must be installed (via `apt`) for SpatiaLite spatial queries. These are not Python packages.

### Key gotchas

- `pytest` is not in `requirements.txt` — install it separately.
- Python packages install to `~/.local/bin` (user install); ensure `$HOME/.local/bin` is on `PATH`.
- The `BUILDER_MODE=true` env var (set in `.env.example`) enables the `/builder/dashboard` route for analytics.
- No linter configuration exists in the repo (no flake8/ruff/pylint config files). Code quality checks are informal.
- Pre-existing template bug: `templates/snapshot.html` references a `snapshot_og_image` Flask endpoint that does not exist in `app.py`. Viewing a snapshot page (`/s/<id>`) crashes with a `BuildError`. The evaluation pipeline itself works correctly — data is saved to the DB and accessible via `/api/snapshot/<id>/json`.
- Evaluations take 2–3 minutes due to hundreds of real API calls (Google Maps, Overpass, Open-Meteo). The `FLASK_DEBUG=1` auto-reloader is fine for development.
