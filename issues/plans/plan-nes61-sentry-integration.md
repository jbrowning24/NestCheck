# NES-61: Integrate Sentry for Error Tracking

**Overall Progress:** 100% · **Status:** Complete
**Last updated:** Feb 13, 2025

## TLDR
Add Sentry error tracking to NestCheck, gated on `SENTRY_DSN` env var. Error tracking only (no performance monitoring). Covers Flask request errors, worker thread failures, and API client exceptions. Expected failures (geocoding not found, Overpass timeouts, rate limits) demoted to breadcrumbs/warnings — only unexpected exceptions become Sentry errors.

## Critical Decisions
- **Error tracking only** — `traces_sample_rate=0.0`, no Sentry Performance. We already have `nc_trace` for timing.
- **Env-gated** — No `SENTRY_DSN` = no Sentry init. Silent in local dev.
- **No PII scrubbing** — Addresses kept in events for reproduction. Small user base, own monitoring tool.
- **Render deploy** — Release tag from `RENDER_GIT_COMMIT` env var (not Railway).
- **Custom worker scope** — Manual Sentry scope in worker thread with `job_id`/`request_id` tags. No migration to Celery.
- **Noise filtering** — Expected failures are breadcrumbs/warnings via `before_send`. Unexpected exceptions are full errors.

## Tasks

- [ ] 🟩 **Phase 1: SDK Init & Dependency**
  - [ ] 🟩 Add `sentry-sdk[flask]` to `requirements.txt`
  - [ ] 🟩 Add Sentry init block in `app.py` after `load_dotenv()`, before `app = Flask(__name__)` — gated on `SENTRY_DSN` presence
  - [ ] 🟩 Set `traces_sample_rate=0.0`, `release` from `RENDER_GIT_COMMIT`, `environment` from `RENDER_ENVIRONMENT` (fallback `"production"`)
  - [ ] 🟩 No changes to existing error handling, routes, or templates

- [ ] 🟩 **Phase 2: Worker Thread Integration**
  - [ ] 🟩 In `worker.py` `_run_job()`: push a new Sentry scope with `job_id`, `request_id`, and `address` as tags
  - [ ] 🟩 In `_worker_loop()` outer except: call `sentry_sdk.capture_exception()` so unhandled worker errors reach Sentry
  - [ ] 🟩 Guard all Sentry calls with availability check (no-op when SDK not initialized)

- [ ] 🟩 **Phase 3: Noise Filtering (before_send)**
  - [ ] 🟩 Add a `before_send` callback to the `sentry_sdk.init()` call
  - [ ] 🟩 Demote expected errors to breadcrumbs (return `None`): geocoding `ValueError` for bad addresses, Overpass `requests.RequestException` timeouts, rate limit 429s
  - [ ] 🟩 Let unexpected exceptions pass through as full Sentry errors

- [ ] 🟩 **Phase 4: Verify & Deploy**
  - [ ] 🟩 Test locally: confirm app starts without `SENTRY_DSN` (no errors, no SDK init)
  - [ ] 🟩 Test locally: confirm with a dummy `SENTRY_DSN` that `sentry_sdk.init()` is called
  - [ ] 🟩 Add `SENTRY_DSN` to Render environment variables (render.yaml + README)
  - [ ] 🟩 Verification script: `python scripts/verify_sentry.py`
  - [ ] 🟥 Deploy and trigger a test error to confirm events appear in Sentry dashboard (manual)
