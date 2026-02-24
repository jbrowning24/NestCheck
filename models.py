"""
SQLite persistence for NestCheck snapshots and analytics events.

Lightweight, append-only design. No ORM — just raw sqlite3.
Works locally and on Railway without additional services.
"""

import hashlib
import sqlite3
import os
import json
import logging
import uuid
import time
from datetime import datetime, timezone, timedelta
from typing import Optional

logger = logging.getLogger(__name__)

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
            place_id        TEXT,
            evaluated_at    TEXT,
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

        CREATE TABLE IF NOT EXISTS overpass_cache (
            cache_key     TEXT PRIMARY KEY,
            response_json TEXT NOT NULL,
            created_at    TEXT
        );
        CREATE TABLE IF NOT EXISTS weather_cache (
            cache_key     TEXT PRIMARY KEY,
            summary_json  TEXT NOT NULL,
            created_at    TEXT
        );
    """)

    # Migration for pre-place_id databases.
    cols = {
        row["name"]
        for row in conn.execute("PRAGMA table_info(snapshots)").fetchall()
    }
    if "place_id" not in cols:
        conn.execute("ALTER TABLE snapshots ADD COLUMN place_id TEXT")
    if "evaluated_at" not in cols:
        conn.execute("ALTER TABLE snapshots ADD COLUMN evaluated_at TEXT")

    # Legacy rows should be treated as previously evaluated at created_at.
    conn.execute(
        """UPDATE snapshots
           SET evaluated_at = COALESCE(evaluated_at, created_at)
           WHERE evaluated_at IS NULL"""
    )
    conn.execute(
        """CREATE UNIQUE INDEX IF NOT EXISTS idx_snapshots_place_id
           ON snapshots(place_id)
           WHERE place_id IS NOT NULL"""
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
           (snapshot_id, address_input, address_norm, place_id, evaluated_at, created_at,
            verdict, final_score, passed_tier1, result_json)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            snapshot_id,
            address_input,
            address_norm or address_input,
            None,
            now,
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


def get_snapshots_by_ids(snapshot_ids):
    """
    Load multiple snapshots by ID in one query.

    Returns a list in the same order as snapshot_ids, skipping IDs not found.
    """
    if not snapshot_ids:
        return []

    placeholders = ",".join(["?"] * len(snapshot_ids))
    conn = _get_db()
    rows = conn.execute(
        f"SELECT * FROM snapshots WHERE snapshot_id IN ({placeholders})",
        tuple(snapshot_ids),
    ).fetchall()
    conn.close()

    by_id = {}
    for row in rows:
        data = dict(row)
        data["result"] = json.loads(data["result_json"])
        by_id[data["snapshot_id"]] = data

    ordered = []
    for snapshot_id in snapshot_ids:
        snap = by_id.get(snapshot_id)
        if snap:
            ordered.append(snap)
    return ordered


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
                return_visit, evaluation_error, snapshot_reused
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
                  place_id, evaluated_at, verdict, final_score, passed_tier1, view_count
           FROM snapshots ORDER BY created_at DESC LIMIT ?""",
        (limit,),
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def get_snapshot_by_place_id(place_id):
    """Load a snapshot by canonical Google place_id."""
    if not place_id:
        return None

    conn = _get_db()
    row = conn.execute(
        "SELECT * FROM snapshots WHERE place_id = ? LIMIT 1", (place_id,)
    ).fetchone()
    conn.close()

    if not row:
        return None

    data = dict(row)
    data["result"] = json.loads(data["result_json"])
    return data


def _parse_utc(ts):
    """Parse supported timestamp strings into timezone-aware UTC datetimes."""
    if not ts:
        return None
    parsed = None
    try:
        parsed = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed = datetime.strptime(str(ts), "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def is_snapshot_fresh(snapshot, ttl_days, now_utc):
    """Return True when snapshot.evaluated_at is within ttl_days of now_utc."""
    if not snapshot:
        return False

    evaluated_at = _parse_utc(snapshot.get("evaluated_at"))
    if evaluated_at is None:
        return False

    cutoff = now_utc - timedelta(days=ttl_days)
    return evaluated_at >= cutoff


def save_snapshot_for_place(
    place_id,
    address_input,
    address_norm,
    evaluated_at,
    result_dict,
    existing_snapshot_id=None,
):
    """
    Persist a canonical snapshot keyed by place_id.

    If existing_snapshot_id is provided, update in place and return the same id.
    Otherwise, insert a new row and return the new snapshot_id.
    """
    now = datetime.now(timezone.utc).isoformat()
    evaluated_ts = evaluated_at or now
    norm = address_norm or address_input

    conn = _get_db()
    try:
        if existing_snapshot_id:
            conn.execute(
                """UPDATE snapshots
                   SET address_input = ?, address_norm = ?, place_id = ?,
                       evaluated_at = ?, created_at = ?,
                       verdict = ?, final_score = ?, passed_tier1 = ?, result_json = ?
                   WHERE snapshot_id = ?""",
                (
                    address_input,
                    norm,
                    place_id,
                    evaluated_ts,
                    now,
                    result_dict.get("verdict", ""),
                    result_dict.get("final_score", 0),
                    1 if result_dict.get("passed_tier1") else 0,
                    json.dumps(result_dict, default=str),
                    existing_snapshot_id,
                ),
            )
            conn.commit()
            return existing_snapshot_id

        snapshot_id = generate_snapshot_id()
        conn.execute(
            """INSERT INTO snapshots
               (snapshot_id, address_input, address_norm, place_id, evaluated_at, created_at,
                verdict, final_score, passed_tier1, result_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                snapshot_id,
                address_input,
                norm,
                place_id,
                evaluated_ts,
                now,
                result_dict.get("verdict", ""),
                result_dict.get("final_score", 0),
                1 if result_dict.get("passed_tier1") else 0,
                json.dumps(result_dict, default=str),
            ),
        )
        conn.commit()
        return snapshot_id
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Overpass cache (7-day TTL)
# ---------------------------------------------------------------------------

_OVERPASS_CACHE_TTL_DAYS = 7


def overpass_cache_key(query_string: str) -> str:
    """Generate a deterministic cache key from an Overpass query string."""
    return hashlib.sha256(query_string.encode()).hexdigest()


def _check_cache_ttl(created_str, ttl_days: int) -> bool:
    """Return True if a cache entry is still valid (younger than TTL).

    Shared helper for overpass_cache and weather_cache TTL checks.
    """
    if not created_str:
        return True  # No timestamp → assume valid
    try:
        if isinstance(created_str, datetime):
            created = created_str
        else:
            created = datetime.fromisoformat(str(created_str))
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        age = datetime.now(timezone.utc) - created
        return age <= timedelta(days=ttl_days)
    except (ValueError, TypeError):
        return True  # Can't parse → return data anyway


def get_overpass_cache(cache_key: str) -> Optional[str]:
    """Look up a cached Overpass response by key.

    Returns the raw JSON string if found and younger than TTL, else None.
    Cache errors are swallowed so they never break an evaluation.
    """
    try:
        conn = _get_db()
        try:
            row = conn.execute(
                """SELECT response_json, created_at FROM overpass_cache
                   WHERE cache_key = ?""",
                (cache_key,),
            ).fetchone()
            if not row:
                return None
            if not _check_cache_ttl(row["created_at"], _OVERPASS_CACHE_TTL_DAYS):
                return None
            return row["response_json"]
        finally:
            conn.close()
    except Exception:
        logger.warning("Overpass cache lookup failed", exc_info=True)
        return None


def set_overpass_cache(cache_key: str, response_json: str) -> None:
    """Store an Overpass response in the persistent cache.

    Cache errors are swallowed so they never break an evaluation.
    """
    try:
        conn = _get_db()
        try:
            now = datetime.now(timezone.utc).isoformat()
            conn.execute(
                """INSERT OR REPLACE INTO overpass_cache (cache_key, response_json, created_at)
                   VALUES (?, ?, ?)""",
                (cache_key, response_json, now),
            )
            conn.commit()
        finally:
            conn.close()
    except Exception:
        logger.warning("Overpass cache write failed", exc_info=True)


# ---------------------------------------------------------------------------
# Weather cache (90-day TTL)
# ---------------------------------------------------------------------------

_WEATHER_CACHE_TTL_DAYS = 90


def get_weather_cache(cache_key: str) -> Optional[str]:
    """Look up cached weather summary by rounded-coordinate key.

    Returns the raw JSON string if found and younger than TTL, else None.
    Cache errors are swallowed so they never break an evaluation.
    """
    try:
        conn = _get_db()
        try:
            row = conn.execute(
                """SELECT summary_json, created_at FROM weather_cache
                   WHERE cache_key = ?""",
                (cache_key,),
            ).fetchone()
            if not row:
                return None
            if not _check_cache_ttl(row["created_at"], _WEATHER_CACHE_TTL_DAYS):
                return None
            return row["summary_json"]
        finally:
            conn.close()
    except Exception:
        logger.warning("Weather cache lookup failed", exc_info=True)
        return None


def set_weather_cache(cache_key: str, summary_json: str) -> None:
    """Store a weather summary in the persistent cache.

    Cache errors are swallowed so they never break an evaluation.
    """
    try:
        conn = _get_db()
        try:
            now = datetime.now(timezone.utc).isoformat()
            conn.execute(
                """INSERT OR REPLACE INTO weather_cache (cache_key, summary_json, created_at)
                   VALUES (?, ?, ?)""",
                (cache_key, summary_json, now),
            )
            conn.commit()
        finally:
            conn.close()
    except Exception:
        logger.warning("Weather cache write failed", exc_info=True)
