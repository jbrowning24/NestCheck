# NES-361: validation_feedback table + POST /api/feedback endpoint

## Overview

Database table and API endpoint for storing validation feedback from testers — both inline reactions and detailed survey responses. This is backend-only infrastructure; the frontend UI that submits to this endpoint is a separate ticket (NES-360 parent).

## Approach

All-in-`models.py` — table DDL in `init_db()`, four helper functions in `models.py`, one endpoint in `app.py`. Follows the existing pattern used by every other `nestcheck.db` table.

## Database Schema

Added to `init_db()` in `models.py`:

```sql
CREATE TABLE IF NOT EXISTS validation_feedback (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_id TEXT NOT NULL,
    respondent_email TEXT,
    feedback_type TEXT NOT NULL,  -- 'inline_reaction' | 'detailed_survey'
    told_something_new INTEGER,   -- 1=yes, 0=no, NULL=not answered
    would_pay INTEGER,            -- 1=yes, 0=no, NULL=not answered
    would_pay_amount TEXT,        -- '5' | '10' | '15' | '25' | NULL
    dimension_ratings TEXT,       -- JSON: {"green_space": 4, "coffee": 3, ...} (1-5 accuracy)
    overall_accuracy INTEGER,     -- 1-5 scale, NULL for inline
    free_text TEXT,
    submitted_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (snapshot_id) REFERENCES snapshots(snapshot_id)
);
CREATE INDEX IF NOT EXISTS idx_feedback_snapshot
    ON validation_feedback(snapshot_id);
CREATE INDEX IF NOT EXISTS idx_feedback_type
    ON validation_feedback(feedback_type);
```

- FK constraint provides referential integrity at the DB layer (`PRAGMA foreign_keys=ON` already set in `_get_db()`).
- `snapshot_id` index supports `get_feedback_for_snapshot()`.
- `feedback_type` index supports filtered aggregation in `get_validation_summary()`.

## Helper Functions (`models.py`)

### `snapshot_exists(snapshot_id: str) -> bool`

Lightweight existence check — `SELECT 1 FROM snapshots WHERE snapshot_id = ?`. No `result_json` load. Swallows errors, returns `False` on failure.

### `save_validation_feedback(data: dict) -> Optional[int]`

INSERT into `validation_feedback`. `json.dumps()` the `dimension_ratings` dict before storage. Returns the new row `id`, or `None` on error. Swallows DB errors with `logger.exception()`.

### `get_feedback_for_snapshot(snapshot_id: str) -> list[dict]`

SELECT all rows for a snapshot, ordered by `submitted_at DESC`. `json.loads()` the `dimension_ratings` back to dict. Returns `[]` on error.

### `get_all_validation_feedback() -> list[dict]`

SELECT all rows, ordered by `submitted_at DESC`. Same JSON parsing on `dimension_ratings`. Returns `[]` on error.

### `get_validation_summary() -> dict`

Fetches all rows, aggregates in Python (not `json_extract()` in SQL — matches existing pattern for JSON blob handling). Returns:

```python
{
    "told_new_count": int,
    "would_pay_count": int,
    "total_responses": int,
    "dimension_avg_ratings": dict  # {"green_space": 3.8, "coffee": 4.1, ...}
}
```

Returns zeroed dict on error.

## API Endpoint (`app.py`)

### `POST /api/feedback`

Placed alongside existing `/api/*` routes.

**Request**: JSON body with feedback fields.

**Validation**:
1. `snapshot_id` present → 400 if missing
2. `snapshot_exists(snapshot_id)` → 404 if not found
3. `feedback_type` is `"inline_reaction"` or `"detailed_survey"` → 400 if invalid

**Response**: `201` with `{"status": "saved"}` on success.

**Error handling**: If `save_validation_feedback()` returns `None` (DB error), still returns 201 to the user. Feedback submission never shows the user an error. The DB error is already logged inside the helper.

**CSRF**: Standard `csrfFetch` pattern — no `@csrf.exempt` needed.

**Auth**: None required. Testers access via report link.

**No** rate limiting, IP logging, or spam protection. Validation-phase endpoint for known testers.

## Design Decisions

| Decision | Rationale |
|----------|-----------|
| All in `models.py` | Follows 100% of existing patterns for `nestcheck.db` tables |
| `snapshot_exists()` + FK constraint | Lightweight 404 for API consumers + defense-in-depth at DB layer |
| `dimension_ratings` aggregated in Python | Matches existing `result_json` / `metadata_json` handling pattern. `json_extract()` in SQL is fragile if dimension names change |
| No validation on `would_pay_amount` values | UI-driven choices that may change. Store whatever client sends |
| Silent 201 on DB errors | Per ticket: "Feedback submission should never show the user an error page" |

## Files Changed

- `models.py` — table DDL in `init_db()`, `snapshot_exists()`, 4 helper functions
- `app.py` — `POST /api/feedback` route

## Testing

- Unit tests for all four helper functions
- Endpoint tests: valid submission (201), missing snapshot_id (400), invalid feedback_type (400), nonexistent snapshot (404)
- Verify FK constraint blocks orphan feedback at DB level
