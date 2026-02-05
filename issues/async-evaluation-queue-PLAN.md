# Async Evaluation Queue Implementation Plan

**Overall Progress:** `100%`

## TLDR

Convert synchronous property evaluation to an async job queue architecture. User submits address → gets job ID immediately → frontend polls for completion → shows results. Eliminates client-side timeout issues regardless of how long evaluation takes.

## Problem Statement

Current evaluation makes 100+ sequential API calls (106 in `neighborhood` stage alone = 8.2s). Total evaluation exceeds the 2-minute client-side JavaScript timeout. Individual API timeouts (25s each) don't help because the *cumulative* time is the problem.

## Critical Decisions

- **SQLite-backed queue** - Reuse existing models.py pattern; safe with gunicorn workers; no Redis dependency
- **Single worker thread per gunicorn worker** - Simple; scales with `--workers N`; avoids multiprocessing complexity
- **Polling over WebSockets** - Simpler to implement; works with existing infrastructure; 2-second poll interval
- **Stage-level progress** - Report which stage is running so users see progress, not just a spinner

## Architecture

```
┌─────────────┐     POST /         ┌─────────────┐
│   Browser   │ ─────────────────► │   app.py    │
│             │ ◄───────────────── │             │
│             │   {job_id: "xyz"}  │  (queues    │
│             │                    │   job)      │
│             │     GET /job/xyz   │             │
│             │ ─────────────────► │             │
│             │ ◄───────────────── │             │
│             │   {status, stage}  └─────────────┘
└─────────────┘                           │
      │                                   │
      │ polls every 2s                    │ reads/writes
      │                                   ▼
      │                          ┌─────────────────┐
      │                          │   SQLite DB     │
      │                          │  (jobs table)   │
      │                          └─────────────────┘
      │                                   ▲
      │                                   │ polls for work
      │                                   │
      │         result ready       ┌─────────────┐
      └──────────────────────────► │  worker.py  │
           redirect to /s/{id}     │  (thread)   │
                                   └─────────────┘
```

## Tasks

- [x] 🟩 **Step 1: Add jobs table to models.py**
  - [x] 🟩 Create `evaluation_jobs` table: job_id, address, status (queued/running/done/failed), current_stage, result_snapshot_id, error, created_at, started_at, completed_at
  - [x] 🟩 Add `create_job()`, `get_job()`, `claim_next_job()`, `update_job_stage()`, `complete_job()`, `fail_job()` functions
  - [x] 🟩 Add DB migration/init for new table in `init_db()`

- [x] 🟩 **Step 2: Create worker.py**
  - [x] 🟩 Worker thread polls DB for queued jobs via `claim_next_job()`
  - [x] 🟩 Claims job (atomic SELECT + UPDATE with WHERE status='queued')
  - [x] 🟩 Calls `evaluate_property(listing, api_key, on_stage=...)` with stage callbacks
  - [x] 🟩 Updates `current_stage` in DB as evaluation progresses
  - [x] 🟩 On success: saves snapshot, marks job done with snapshot_id
  - [x] 🟩 On failure: marks job failed with error message
  - [x] 🟩 Graceful shutdown via `_stop_event` in worker loop

- [x] 🟩 **Step 3: Modify app.py routes**
  - [x] 🟩 Change `POST /` to create job and return `{job_id}` immediately (or redirect with ?job_id= for non-JS)
  - [x] 🟩 Add `GET /job/<job_id>` endpoint returning `{status, current_stage, snapshot_id, error}`
  - [x] 🟩 Keep existing `/s/<snapshot_id>` route unchanged

- [x] 🟩 **Step 4: Update frontend (index.html)**
  - [x] 🟩 On form submit: POST, get job_id, start polling
  - [x] 🟩 Poll `GET /job/{id}` every 2 seconds
  - [x] 🟩 Update loading text with current stage name (STAGE_DISPLAY map)
  - [x] 🟩 On status=done: redirect to `/s/{snapshot_id}`
  - [x] 🟩 On status=failed: show error message
  - [x] 🟩 Removed client-side AbortController timeout; support ?job_id= on load to resume polling

- [x] 🟩 **Step 5: Start worker on boot**
  - [x] 🟩 `gunicorn_config.py` with `post_fork` starts worker thread in each gunicorn worker
  - [x] 🟩 Dev server: `app.py` starts worker in `if __name__ == "__main__"`
  - [x] 🟩 Procfile and render.yaml use `-c gunicorn_config.py`

- [x] 🟩 **Step 6: Update CLAUDE.md**
  - [x] 🟩 Documented async flow (POST → job_id, GET /job/<id>, worker.py, frontend polling)
  - [x] 🟩 worker.py now exists and is the canonical background worker

## Stage Names for Progress Display

Map internal stage names to user-friendly messages:
| Stage | Display Text |
|-------|--------------|
| geocode | Locating address... |
| bike_score | Checking bike infrastructure... |
| neighborhood | Analyzing nearby amenities... |
| schools | Finding schools and childcare... |
| urban_access | Calculating commute times... |
| transit_access | Evaluating transit options... |
| green_spaces | Discovering parks and trails... |
| green_escape | Finding your daily green escape... |
| transit_score | Getting transit scores... |
| walk_scores | Getting walkability scores... |
| tier1_checks | Running safety checks... |
| tier2_scoring | Calculating lifestyle scores... |
| tier3_bonuses | Adding bonus points... |
| saving | Saving your results... |

## Success Criteria

1. Evaluation completes regardless of duration (no client timeout)
2. User sees meaningful progress updates during evaluation
3. Existing functionality unchanged (same results, same snapshot URLs)
4. No new external dependencies (no Redis, no Celery)
5. Works correctly with `gunicorn --workers 2`

## Risks & Mitigations

| Risk | Mitigation |
|------|------------|
| Job stuck in "running" if worker crashes | Add `started_at` timestamp; requeue jobs running >5 min |
| Multiple workers claim same job | Use atomic SQL UPDATE with WHERE status='queued' |
| DB locked during heavy writes | SQLite WAL mode (already enabled); keep transactions short |
| User refreshes page mid-evaluation | Job continues; polling resumes on page load if job_id in URL/session |

## Out of Scope (Future)

- Job cancellation
- Retry failed jobs automatically
- Priority queue for builder accounts
- WebSocket push instead of polling
