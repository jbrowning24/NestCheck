"""
SQLite persistence for NestCheck snapshots and analytics events.

Lightweight, append-only design. No ORM — just raw sqlite3.
Works locally and on Railway without additional services.
"""

import sqlite3
import os
import json
import uuid
import time
from datetime import datetime, timezone, timedelta

DB_PATH = os.environ.get("NESTCHECK_DB_PATH", "nestcheck.db")


def _get_db():
    """Get a sqlite3 connection with WAL mode for concurrent reads."""
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def init_db():
    """Create tables if they don't exist. Safe to call on every startup."""
    conn = _get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS snapshots (
            snapshot_id     TEXT PRIMARY KEY,
            address_input   TEXT NOT NULL,
            address_norm    TEXT,
            created_at      TEXT NOT NULL,
            verdict         TEXT,
            final_score     INTEGER,
            passed_tier1    INTEGER NOT NULL DEFAULT 0,
            result_json     TEXT NOT NULL,
            view_count      INTEGER NOT NULL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS events (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            event_type  TEXT NOT NULL,
            snapshot_id TEXT,
            visitor_id  TEXT,
            metadata    TEXT,
            created_at  TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_events_type ON events(event_type);
        CREATE INDEX IF NOT EXISTS idx_events_snapshot ON events(snapshot_id);
        CREATE INDEX IF NOT EXISTS idx_events_visitor ON events(visitor_id);
        CREATE INDEX IF NOT EXISTS idx_snapshots_created ON snapshots(created_at);
    """)

    # --- Migrate: add async evaluation columns if missing ---
    cols = {row[1] for row in conn.execute("PRAGMA table_info(snapshots)").fetchall()}
    if "status" not in cols:
        conn.execute("ALTER TABLE snapshots ADD COLUMN status TEXT NOT NULL DEFAULT 'done'")
    if "modules_status" not in cols:
        conn.execute("ALTER TABLE snapshots ADD COLUMN modules_status TEXT DEFAULT '{}'")
    if "last_updated_at" not in cols:
        conn.execute("ALTER TABLE snapshots ADD COLUMN last_updated_at TEXT")
    if "trace_id" not in cols:
        conn.execute("ALTER TABLE snapshots ADD COLUMN trace_id TEXT")
    # v2: DB-backed job queue columns
    if "locked_by" not in cols:
        conn.execute("ALTER TABLE snapshots ADD COLUMN locked_by TEXT")
    if "locked_at" not in cols:
        conn.execute("ALTER TABLE snapshots ADD COLUMN locked_at TEXT")
    if "visitor_id" not in cols:
        conn.execute("ALTER TABLE snapshots ADD COLUMN visitor_id TEXT")

    # Index for the worker poll query: find queued jobs quickly
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_snapshots_status ON snapshots(status)"
    )

    conn.commit()
    conn.close()


def generate_snapshot_id():
    """Short, URL-safe snapshot ID (8 chars)."""
    return uuid.uuid4().hex[:8]


def save_snapshot(address_input, address_norm, result_dict):
    """
    Persist an evaluation snapshot. Returns the snapshot_id.

    result_dict is the full template-ready dict from result_to_dict().
    """
    snapshot_id = generate_snapshot_id()
    now = datetime.now(timezone.utc).isoformat()

    conn = _get_db()
    conn.execute(
        """INSERT INTO snapshots
           (snapshot_id, address_input, address_norm, created_at,
            verdict, final_score, passed_tier1, result_json,
            status, last_updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'done', ?)""",
        (
            snapshot_id,
            address_input,
            address_norm or address_input,
            now,
            result_dict.get("verdict", ""),
            result_dict.get("final_score", 0),
            1 if result_dict.get("passed_tier1") else 0,
            json.dumps(result_dict, default=str),
            now,
        ),
    )
    conn.commit()
    conn.close()
    return snapshot_id


def create_queued_snapshot(address_input, trace_id=None, modules_status=None,
                          visitor_id=None):
    """
    Create a snapshot in 'queued' state with no result yet.
    Returns snapshot_id. The background worker will pick it up from the DB.
    """
    snapshot_id = generate_snapshot_id()
    now = datetime.now(timezone.utc).isoformat()
    conn = _get_db()
    conn.execute(
        """INSERT INTO snapshots
           (snapshot_id, address_input, address_norm, created_at,
            verdict, final_score, passed_tier1, result_json,
            status, modules_status, last_updated_at, trace_id,
            visitor_id)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            snapshot_id,
            address_input,
            address_input,  # norm = input until geocode resolves
            now,
            "",   # verdict
            0,    # final_score
            0,    # passed_tier1
            "{}",  # empty result_json
            "queued",
            json.dumps(modules_status or {}),
            now,
            trace_id,
            visitor_id,
        ),
    )
    conn.commit()
    conn.close()
    return snapshot_id


def update_snapshot_status(snapshot_id, status, modules_status=None):
    """Update the evaluation status and optionally modules_status.

    Clears locked_by/locked_at on terminal states (done, failed) so
    stale-lock detection doesn't false-positive on finished jobs.
    """
    now = datetime.now(timezone.utc).isoformat()
    is_terminal = status in ("done", "failed")
    conn = _get_db()
    if modules_status is not None:
        conn.execute(
            """UPDATE snapshots
               SET status = ?, modules_status = ?, last_updated_at = ?,
                   locked_by = CASE WHEN ? THEN NULL ELSE locked_by END,
                   locked_at = CASE WHEN ? THEN NULL ELSE locked_at END
               WHERE snapshot_id = ?""",
            (status, json.dumps(modules_status), now,
             is_terminal, is_terminal, snapshot_id),
        )
    else:
        conn.execute(
            """UPDATE snapshots
               SET status = ?, last_updated_at = ?,
                   locked_by = CASE WHEN ? THEN NULL ELSE locked_by END,
                   locked_at = CASE WHEN ? THEN NULL ELSE locked_at END
               WHERE snapshot_id = ?""",
            (status, now, is_terminal, is_terminal, snapshot_id),
        )
    conn.commit()
    conn.close()


def update_snapshot_modules(snapshot_id, modules_status):
    """Update only the modules_status JSON (called per-stage)."""
    now = datetime.now(timezone.utc).isoformat()
    conn = _get_db()
    conn.execute(
        """UPDATE snapshots
           SET modules_status = ?, last_updated_at = ?
           WHERE snapshot_id = ?""",
        (json.dumps(modules_status), now, snapshot_id),
    )
    conn.commit()
    conn.close()


def update_snapshot_result(snapshot_id, result_dict, address_norm=None):
    """
    Fill in the completed evaluation result for a snapshot.
    Sets status='done', populates verdict/scores/result_json, clears lock.
    """
    now = datetime.now(timezone.utc).isoformat()
    conn = _get_db()
    conn.execute(
        """UPDATE snapshots
           SET status = 'done',
               address_norm = ?,
               verdict = ?,
               final_score = ?,
               passed_tier1 = ?,
               result_json = ?,
               last_updated_at = ?,
               locked_by = NULL,
               locked_at = NULL
           WHERE snapshot_id = ?""",
        (
            address_norm or "",
            result_dict.get("verdict", ""),
            result_dict.get("final_score", 0),
            1 if result_dict.get("passed_tier1") else 0,
            json.dumps(result_dict, default=str),
            now,
            snapshot_id,
        ),
    )
    conn.commit()
    conn.close()


def get_snapshot(snapshot_id):
    """
    Load a snapshot by ID. Returns dict with metadata + result_json parsed,
    or None if not found.
    """
    conn = _get_db()
    row = conn.execute(
        "SELECT * FROM snapshots WHERE snapshot_id = ?", (snapshot_id,)
    ).fetchone()
    conn.close()

    if not row:
        return None

    data = dict(row)
    try:
        data["result"] = json.loads(data["result_json"]) if data["result_json"] else {}
    except (json.JSONDecodeError, TypeError):
        data["result"] = {}
    try:
        data["modules_status"] = json.loads(data.get("modules_status") or "{}")
    except (json.JSONDecodeError, TypeError):
        data["modules_status"] = {}
    return data


def increment_view_count(snapshot_id):
    """Bump the view counter for a snapshot."""
    conn = _get_db()
    conn.execute(
        "UPDATE snapshots SET view_count = view_count + 1 WHERE snapshot_id = ?",
        (snapshot_id,),
    )
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# DB-backed job queue: claim / release / stale detection
# ---------------------------------------------------------------------------

def claim_next_job(worker_id):
    """
    Atomically claim the oldest queued snapshot for processing.

    Uses BEGIN IMMEDIATE to acquire a write lock, preventing two workers
    from claiming the same row — safe across multiple gunicorn processes.

    Returns a dict with snapshot_id, address_input, trace_id, visitor_id
    or None if no queued jobs exist.
    """
    conn = _get_db()
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            """SELECT snapshot_id, address_input, trace_id, visitor_id
               FROM snapshots
               WHERE status = 'queued'
                 AND (locked_by IS NULL OR locked_by = '')
               ORDER BY created_at ASC
               LIMIT 1""",
        ).fetchone()
        if not row:
            conn.rollback()
            return None

        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            """UPDATE snapshots
               SET status = 'running', locked_by = ?, locked_at = ?,
                   last_updated_at = ?
               WHERE snapshot_id = ?
                 AND status = 'queued'""",
            (worker_id, now, now, row["snapshot_id"]),
        )
        conn.commit()
        return dict(row)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def release_stale_jobs(stale_seconds=300):
    """
    Mark jobs stuck in 'running' with a stale lock as 'failed'.

    A job is stale if locked_at is older than `stale_seconds` and the
    status is still 'running'. This means the worker process died before
    completing the evaluation.

    Returns the number of jobs marked as failed.
    """
    cutoff = (datetime.now(timezone.utc) - timedelta(seconds=stale_seconds)).isoformat()
    conn = _get_db()
    cursor = conn.execute(
        """UPDATE snapshots
           SET status = 'failed', locked_by = NULL, locked_at = NULL,
               last_updated_at = ?
           WHERE status = 'running'
             AND locked_at IS NOT NULL
             AND locked_at < ?""",
        (datetime.now(timezone.utc).isoformat(), cutoff),
    )
    count = cursor.rowcount
    conn.commit()
    conn.close()
    return count


# ---------------------------------------------------------------------------
# Analytics events
# ---------------------------------------------------------------------------

def log_event(event_type, snapshot_id=None, visitor_id=None, metadata=None):
    """
    Append an analytics event.

    event_type: one of snapshot_created, snapshot_viewed, snapshot_shared,
                return_visit, evaluation_error
    metadata:   optional dict of extra info
    """
    now = datetime.now(timezone.utc).isoformat()
    conn = _get_db()
    conn.execute(
        """INSERT INTO events (event_type, snapshot_id, visitor_id, metadata, created_at)
           VALUES (?, ?, ?, ?, ?)""",
        (
            event_type,
            snapshot_id,
            visitor_id,
            json.dumps(metadata) if metadata else None,
            now,
        ),
    )
    conn.commit()
    conn.close()


def check_return_visit(visitor_id, days=7):
    """
    Check if this visitor created a snapshot within the last `days` days.
    Returns True if they did (meaning this is a return visit).
    """
    if not visitor_id:
        return False

    conn = _get_db()
    row = conn.execute(
        """SELECT COUNT(*) as cnt FROM events
           WHERE event_type = 'snapshot_created'
             AND visitor_id = ?
             AND created_at >= datetime('now', ?)""",
        (visitor_id, f"-{days} days"),
    ).fetchone()
    conn.close()
    return row["cnt"] > 0 if row else False


def get_event_counts():
    """
    Builder utility: get event counts by type.
    Returns dict like {"snapshot_created": 12, "snapshot_viewed": 45, ...}
    """
    conn = _get_db()
    rows = conn.execute(
        "SELECT event_type, COUNT(*) as cnt FROM events GROUP BY event_type"
    ).fetchall()
    conn.close()
    return {row["event_type"]: row["cnt"] for row in rows}


def get_recent_events(limit=50):
    """Builder utility: get recent events for inspection."""
    conn = _get_db()
    rows = conn.execute(
        "SELECT * FROM events ORDER BY created_at DESC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def get_recent_snapshots(limit=20):
    """Builder utility: get recent snapshots for inspection."""
    conn = _get_db()
    rows = conn.execute(
        """SELECT snapshot_id, address_input, address_norm, created_at,
                  verdict, final_score, passed_tier1, view_count
           FROM snapshots ORDER BY created_at DESC LIMIT ?""",
        (limit,),
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]
