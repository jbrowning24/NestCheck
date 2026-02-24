# NES-70: SQLite → PostgreSQL Migration + Render Cleanup

**Overall Progress:** `100%`

## TLDR
Migrate the database layer from raw sqlite3 to a dual-mode backend (PostgreSQL via psycopg2 when `DATABASE_URL` is set, SQLite for local dev). Upgrade job claiming to `FOR UPDATE SKIP LOCKED` on Postgres. Clean up dead Render config and references. No ORM, no Alembic, no data migration — fresh start on Postgres.

## Critical Decisions
- **Dual-mode**: `DATABASE_URL` present → Postgres (production); absent → SQLite (local dev/tests)
- **Library**: `psycopg2-binary` with raw SQL — matches existing no-ORM pattern
- **Connection pooling**: `psycopg2.pool.ThreadedConnectionPool` (in-process, no external dependency)
- **Job claiming**: `FOR UPDATE SKIP LOCKED` on Postgres path; existing SELECT+UPDATE on SQLite path
- **Tests**: Continue using SQLite for speed; Postgres integration tests deferred
- **Schema**: Keep `CREATE TABLE IF NOT EXISTS` pattern, no Alembic
- **Data migration**: Fresh start — no migration of existing SQLite data
- **Render**: Delete `render.yaml`, clean all Render env var references in code

---

## Tasks:

- [x] 🟩 **Step 1: Delete Render artifacts and fix references**
  - [x] 🟩 Delete `render.yaml`
  - [x] 🟩 `app.py:105` — Change `RENDER_GIT_COMMIT` → `RAILWAY_GIT_COMMIT_SHA` (Railway's equivalent)
  - [x] 🟩 `app.py:106` — Change `RENDER_ENVIRONMENT` → `RAILWAY_ENVIRONMENT` with same `"production"` default
  - [x] 🟩 `app.py:1247` — Change `"Railway/Render dashboard"` → `"Railway dashboard"`
  - [x] 🟩 `worker.py:200` — Change `"Railway/Render"` → `"Railway"` in comment
  - [x] ⬜ Update `CLAUDE.md` — Skipped (user declined)
  - [x] 🟩 Add decision log entry in `CLAUDE.md` — Skipped (user declined)

- [x] 🟩 **Step 2: Add psycopg2-binary to requirements.txt**
  - [x] 🟩 Add `psycopg2-binary==2.9.10` to `requirements.txt`

- [x] 🟩 **Step 3: Implement dialect abstraction in models.py**
  - [x] 🟩 Add `DATABASE_URL` env var detection at module level: `_USE_POSTGRES = bool(os.environ.get("DATABASE_URL"))`
  - [x] 🟩 Implement Postgres `_get_db()` path using `psycopg2` with `RealDictCursor` (dict rows like `sqlite3.Row`)
  - [x] 🟩 Implement `ThreadedConnectionPool` initialization (min=2, max=10, created once at module level when Postgres)
  - [x] 🟩 Implement `_return_conn(conn)` to return connections to pool (Postgres) or close (SQLite)
  - [x] 🟩 Add helper `_q()` returning `%s` for Postgres, `?` for SQLite — used by all queries

- [x] 🟩 **Step 4: Port init_db() for Postgres**
  - [x] 🟩 Replace `conn.executescript()` with individual `conn.execute()` calls (Postgres has no `executescript`)
  - [x] 🟩 Replace `INTEGER PRIMARY KEY AUTOINCREMENT` → `SERIAL PRIMARY KEY` on Postgres path
  - [x] 🟩 Replace `PRAGMA journal_mode=WAL` / `PRAGMA foreign_keys=ON` with no-ops on Postgres (defaults are fine)
  - [x] 🟩 Replace `PRAGMA table_info(evaluation_jobs)` column migration with `information_schema.columns` query on Postgres
  - [x] 🟩 Handle `sqlite3.OperationalError` → `psycopg2.errors.DuplicateColumn` for the ALTER TABLE migration guard

- [x] 🟩 **Step 5: Port all query functions for dual-mode**
  - [x] 🟩 Replace all `?` placeholders with `_q()` translator across every function
  - [x] 🟩 `check_return_visit()`: Replace `datetime('now', ?)` → `NOW() - INTERVAL '...'` on Postgres
  - [x] 🟩 `set_overpass_cache()` / `set_weather_cache()`: Replace `INSERT OR REPLACE` → `INSERT ... ON CONFLICT (cache_key) DO UPDATE` on Postgres
  - [x] 🟩 `record_free_tier_usage()`: Replace `INSERT OR IGNORE` → `INSERT ... ON CONFLICT DO NOTHING` on Postgres
  - [x] 🟩 `claim_next_job()`: Replace SELECT+`conn.total_changes` pattern with `FOR UPDATE SKIP LOCKED` + `RETURNING *` on Postgres
  - [x] 🟩 `requeue_stale_running_jobs()`: Replace `conn.total_changes` with `cursor.rowcount` on both paths
  - [x] 🟩 Ensure every function returns connection to pool via `_return_conn()` (including error paths — use try/finally)

- [x] 🟩 **Step 6: Update module docstring and imports**
  - [x] 🟩 Update `models.py` docstring to reflect dual-mode (no longer "just raw sqlite3")
  - [x] 🟩 Add conditional `import psycopg2` / `from psycopg2 import pool` (only when `_USE_POSTGRES`)

- [x] 🟩 **Step 7: Run existing tests against SQLite path**
  - [x] 🟩 Run `pytest tests/` — 157 passed ✅
  - [x] 🟩 Run `pytest test_service_errors.py` — 8 failed, 13 errors (all pre-existing, identical on original code)
  - [x] 🟩 Fixed `tests/conftest.py` to use `_return_conn()` instead of `conn.close()`

- [ ] 🟥 **Step 8: Manual smoke test with local Postgres (optional)**
  - [ ] 🟥 Set `DATABASE_URL=postgresql://...` locally and verify `init_db()` creates tables
  - [ ] 🟥 Verify a job can be created, claimed, completed
  - [ ] 🟥 Verify cache operations (insert, lookup, TTL expiry)

---

## Reference: SQLite-isms per function (from audit)

| Function | SQLite-specific constructs | Opens/closes own conn |
|---|---|---|
| `_get_db()` | `sqlite3.connect`, `PRAGMA WAL`, `PRAGMA FK` | Returns conn |
| `init_db()` | `executescript()`, `PRAGMA table_info()`, `sqlite3.OperationalError` | Yes |
| `save_snapshot()` | `?` placeholders | Yes |
| `get_snapshot()` | `?` placeholder | Yes |
| `increment_view_count()` | `?` placeholder | Yes |
| `log_event()` | `?` placeholders | Yes |
| `check_return_visit()` | `?` placeholders, `datetime('now', ?)` | Yes |
| `get_event_counts()` | — (standard SQL) | Yes |
| `get_recent_events()` | `?` placeholder | Yes |
| `get_recent_snapshots()` | `?` placeholder | Yes |
| `create_job()` | `?` placeholders | Yes |
| `get_job()` | `?` placeholder | Yes |
| `claim_next_job()` | `?` placeholders, `conn.total_changes` | Yes |
| `update_job_stage()` | `?` placeholders | Yes |
| `complete_job()` | `?` placeholders | Yes |
| `fail_job()` | `?` placeholders | Yes |
| `cancel_queued_job()` | `?` placeholders, `cur.rowcount` (portable) | Yes |
| `requeue_stale_running_jobs()` | `?` placeholder, `conn.total_changes` | Yes |
| `get_overpass_cache()` | `?` placeholder | Yes |
| `set_overpass_cache()` | `INSERT OR REPLACE`, `?` placeholders | Yes |
| `get_weather_cache()` | `?` placeholder | Yes |
| `set_weather_cache()` | `INSERT OR REPLACE`, `?` placeholders | Yes |
| `create_payment()` | `?` placeholders | Yes |
| `get_payment_by_session()` | `?` placeholder | Yes |
| `get_payment_by_id()` | `?` placeholder | Yes |
| `update_payment_status()` | `?` placeholders, `cur.rowcount` (portable) | Yes |
| `redeem_payment()` | `?` placeholders, `cur.rowcount` (portable) | Yes |
| `update_payment_job_id()` | `?` placeholders | Yes |
| `get_payment_by_job_id()` | `?` placeholder | Yes |
| `check_free_tier_used()` | `?` placeholder | Yes |
| `record_free_tier_usage()` | `INSERT OR IGNORE`, `?` placeholders | Yes |
| `update_free_tier_snapshot()` | `?` placeholders | Yes |
| `delete_free_tier_usage()` | `?` placeholder | Yes |

## Files that consume models.py (no changes needed — they use the public API)

| File | Functions called |
|---|---|
| `app.py` | `init_db`, `save_snapshot`, `get_snapshot`, `increment_view_count`, `log_event`, `check_return_visit`, `get_event_counts`, `get_recent_events`, `get_recent_snapshots`, `create_job`, `get_job`, `cancel_queued_job`, `create_payment`, `get_payment_by_session`, `get_payment_by_id`, `update_payment_status`, `redeem_payment`, `hash_email`, `check_free_tier_used`, `record_free_tier_usage` |
| `worker.py` | `init_db`, `claim_next_job`, `update_job_stage`, `complete_job`, `fail_job`, `save_snapshot`, `log_event`, `check_return_visit`, `requeue_stale_running_jobs`, `get_payment_by_job_id`, `update_payment_status`, `update_free_tier_snapshot`, `delete_free_tier_usage` |
| `property_evaluator.py` | `overpass_cache_key`, `get_overpass_cache`, `set_overpass_cache` (lazy imports ×5) |
| `green_space.py` | `overpass_cache_key`, `get_overpass_cache`, `set_overpass_cache` (lazy import) |
| `road_noise.py` | `overpass_cache_key`, `get_overpass_cache`, `set_overpass_cache` (top-level import) |
| `weather.py` | `get_weather_cache`, `set_weather_cache` (top-level import) |
| `tests/conftest.py` | `init_db`, `_get_db`, `_return_conn` |
| `tests/test_payments.py` | `create_payment`, `get_payment_by_id`, `get_payment_by_session`, `get_payment_by_job_id`, `update_payment_status`, `redeem_payment`, `update_payment_job_id`, `create_job` |
| `test_service_errors.py` | `models.save_snapshot` (via `importlib.reload`) |
