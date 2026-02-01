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
from datetime import datetime, timezone

DB_PATH = os.environ.get("NESTCHECK_DB_PATH", "nestcheck.db")


def _get_db():
    """Get a sqlite3 connection with WAL mode for concurrent reads."""
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
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
            verdict, final_score, passed_tier1, result_json)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            snapshot_id,
            address_input,
            address_norm or address_input,
            now,
            result_dict.get("verdict", ""),
            result_dict.get("final_score", 0),
            1 if result_dict.get("passed_tier1") else 0,
            json.dumps(result_dict, default=str),
        ),
    )
    conn.commit()
    conn.close()
    return snapshot_id


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
    data["result"] = json.loads(data["result_json"])
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
