"""
Database persistence for NestCheck snapshots and analytics events.

Dual-mode backend (NES-70):
  - PostgreSQL when DATABASE_URL is set (production on Railway)
  - SQLite when DATABASE_URL is absent (local dev, tests)

Lightweight, append-only design. No ORM — raw SQL via psycopg2 or sqlite3.
All public functions return plain dicts; callers are backend-agnostic.
"""

import sqlite3
import os
import json
import uuid
import hashlib
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Backend detection — decided once at import time
# ---------------------------------------------------------------------------

DATABASE_URL = os.environ.get("DATABASE_URL")
_USE_POSTGRES = bool(DATABASE_URL)

if _USE_POSTGRES:
    import psycopg2
    import psycopg2.extras
    import psycopg2.pool

# SQLite fallback path (local dev / tests)
# Railway: use persistent volume when RAILWAY_VOLUME_MOUNT_PATH is set
if os.environ.get("RAILWAY_VOLUME_MOUNT_PATH"):
    DB_PATH = os.path.join(os.environ["RAILWAY_VOLUME_MOUNT_PATH"], "nestcheck.db")
else:
    DB_PATH = os.environ.get("NESTCHECK_DB_PATH", "nestcheck.db")
print(f"DATABASE PATH: {DB_PATH}")

# ---------------------------------------------------------------------------
# Connection management
# ---------------------------------------------------------------------------

# Postgres connection pool — created lazily on first _get_db() call.
# ThreadedConnectionPool is safe for gunicorn workers (2 workers × 1 thread each
# + 1 background worker thread = ~3 concurrent connections per process).
_pg_pool: Optional["psycopg2.pool.ThreadedConnectionPool"] = None


def _init_pg_pool() -> None:
    """Create the Postgres connection pool (called once per process)."""
    global _pg_pool
    if _pg_pool is not None:
        return
    _pg_pool = psycopg2.pool.ThreadedConnectionPool(
        minconn=2,
        maxconn=10,
        dsn=DATABASE_URL,
    )
    logger.info("PostgreSQL connection pool created (min=2, max=10)")


def _get_db():
    """Get a database connection.

    Postgres: borrows from the ThreadedConnectionPool, returns a connection
              with RealDictCursor (rows are dicts, like sqlite3.Row).
    SQLite:   opens a new connection with WAL mode for concurrent reads.

    Callers MUST call _return_conn(conn) when done (use try/finally).
    """
    if _USE_POSTGRES:
        _init_pg_pool()
        conn = _pg_pool.getconn()
        conn.autocommit = False
        return conn
    else:
        conn = sqlite3.connect(DB_PATH, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn


def _return_conn(conn) -> None:
    """Return a connection to the pool (Postgres) or close it (SQLite).

    On Postgres, rollback any uncommitted transaction first so the
    connection is returned in a clean state.  Without this, a failed
    query leaves the transaction aborted and the next caller would
    get 'current transaction is aborted' errors.
    """
    if _USE_POSTGRES:
        try:
            conn.rollback()
        except Exception:
            pass  # Connection may already be broken; pool handles cleanup
        _pg_pool.putconn(conn)
    else:
        conn.close()


def _cursor(conn):
    """Get a cursor appropriate for the backend.

    Postgres: RealDictCursor so rows are dicts (matches sqlite3.Row behavior).
    SQLite:   default cursor (sqlite3.Row factory handles dict access).
    """
    if _USE_POSTGRES:
        return conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    else:
        return conn.cursor()


# ---------------------------------------------------------------------------
# SQL dialect helpers
# ---------------------------------------------------------------------------

def _q(sql: str) -> str:
    """Translate a query from SQLite-style ? placeholders to the active backend.

    On Postgres, replaces ? with %s (but not ?? or ?-inside-strings, which
    don't appear in our queries). On SQLite, returns the query unchanged.
    """
    if _USE_POSTGRES:
        return sql.replace("?", "%s")
    return sql


# ---------------------------------------------------------------------------
# Schema initialization
# ---------------------------------------------------------------------------

# Shared DDL — works on both backends (TEXT, INTEGER, TIMESTAMP are valid in both)
_TABLES_SQL = [
    """CREATE TABLE IF NOT EXISTS snapshots (
        snapshot_id     TEXT PRIMARY KEY,
        address_input   TEXT NOT NULL,
        address_norm    TEXT,
        created_at      TEXT NOT NULL,
        verdict         TEXT,
        final_score     INTEGER,
        passed_tier1    INTEGER NOT NULL DEFAULT 0,
        is_preview      INTEGER NOT NULL DEFAULT 0,
        result_json     TEXT NOT NULL,
        view_count      INTEGER NOT NULL DEFAULT 0
    )""",
    """CREATE TABLE IF NOT EXISTS events (
        id          {auto_pk},
        event_type  TEXT NOT NULL,
        snapshot_id TEXT,
        visitor_id  TEXT,
        metadata    TEXT,
        created_at  TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS evaluation_jobs (
        job_id           TEXT PRIMARY KEY,
        address          TEXT NOT NULL,
        visitor_id       TEXT,
        request_id       TEXT,
        place_id         TEXT,
        email_hash       TEXT,
        status           TEXT NOT NULL DEFAULT 'queued',
        current_stage    TEXT,
        result_snapshot_id TEXT,
        error            TEXT,
        created_at       TEXT NOT NULL,
        started_at       TEXT,
        completed_at     TEXT
    )""",
    """CREATE TABLE IF NOT EXISTS overpass_cache (
        cache_key     TEXT PRIMARY KEY,
        response_json TEXT NOT NULL,
        created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""",
    """CREATE TABLE IF NOT EXISTS weather_cache (
        cache_key    TEXT PRIMARY KEY,
        summary_json TEXT NOT NULL,
        created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""",
    """CREATE TABLE IF NOT EXISTS payments (
        id                TEXT PRIMARY KEY,
        stripe_session_id TEXT UNIQUE,
        visitor_id        TEXT,
        address           TEXT NOT NULL,
        status            TEXT NOT NULL DEFAULT 'pending',
        created_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        redeemed_at       TIMESTAMP,
        job_id            TEXT,
        snapshot_id       TEXT
    )""",
    """CREATE TABLE IF NOT EXISTS free_tier_usage (
        id          {auto_pk},
        email_hash  TEXT UNIQUE NOT NULL,
        email_raw   TEXT NOT NULL,
        job_id      TEXT,
        snapshot_id TEXT,
        created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""",
]

_INDEXES_SQL = [
    "CREATE INDEX IF NOT EXISTS idx_events_type ON events(event_type)",
    "CREATE INDEX IF NOT EXISTS idx_events_snapshot ON events(snapshot_id)",
    "CREATE INDEX IF NOT EXISTS idx_events_visitor ON events(visitor_id)",
    "CREATE INDEX IF NOT EXISTS idx_snapshots_created ON snapshots(created_at)",
    "CREATE INDEX IF NOT EXISTS idx_jobs_status ON evaluation_jobs(status)",
    "CREATE INDEX IF NOT EXISTS idx_jobs_created ON evaluation_jobs(created_at)",
    "CREATE INDEX IF NOT EXISTS idx_payments_session ON payments(stripe_session_id)",
    "CREATE INDEX IF NOT EXISTS idx_payments_visitor ON payments(visitor_id)",
    "CREATE INDEX IF NOT EXISTS idx_payments_status ON payments(status)",
    "CREATE INDEX IF NOT EXISTS idx_payments_job ON payments(job_id)",
    "CREATE INDEX IF NOT EXISTS idx_free_tier_email ON free_tier_usage(email_hash)",
]


def init_db():
    """Create tables if they don't exist. Safe to call on every startup.

    On Postgres, uses SERIAL PRIMARY KEY for auto-increment columns.
    On SQLite, uses INTEGER PRIMARY KEY AUTOINCREMENT.
    Also runs column migration for evaluation_jobs (add columns if missing).
    """
    auto_pk = "SERIAL PRIMARY KEY" if _USE_POSTGRES else "INTEGER PRIMARY KEY AUTOINCREMENT"
    conn = _get_db()
    try:
        cur = _cursor(conn)
        for ddl in _TABLES_SQL:
            cur.execute(ddl.format(auto_pk=auto_pk))
        for idx in _INDEXES_SQL:
            cur.execute(idx)

        # Migrate evaluation_jobs — add columns that may be missing on older
        # schemas. Uses try/except per column to handle the race where multiple
        # gunicorn workers run init_db() concurrently.
        if _USE_POSTGRES:
            cur.execute(
                """SELECT column_name FROM information_schema.columns
                   WHERE table_name = 'evaluation_jobs'"""
            )
            cols = {row["column_name"] for row in cur.fetchall()}
            for col in ("visitor_id", "request_id", "place_id", "email_hash"):
                if col not in cols:
                    try:
                        cur.execute(
                            f"ALTER TABLE evaluation_jobs ADD COLUMN {col} TEXT"
                        )
                    except psycopg2.errors.DuplicateColumn:
                        conn.rollback()  # Clear the failed transaction
        else:
            cols = {
                row["name"]
                for row in conn.execute(
                    "PRAGMA table_info(evaluation_jobs)"
                ).fetchall()
            }
            for col in ("visitor_id", "request_id", "place_id", "email_hash"):
                if col not in cols:
                    try:
                        conn.execute(
                            f"ALTER TABLE evaluation_jobs ADD COLUMN {col} TEXT"
                        )
                    except sqlite3.OperationalError:
                        pass  # Another process already added it

        # Migrate snapshots — add is_preview column (NES-132: free preview tier).
        if _USE_POSTGRES:
            cur.execute(
                """SELECT column_name FROM information_schema.columns
                   WHERE table_name = 'snapshots'"""
            )
            snap_cols = {row["column_name"] for row in cur.fetchall()}
            if "is_preview" not in snap_cols:
                try:
                    cur.execute(
                        "ALTER TABLE snapshots ADD COLUMN is_preview INTEGER NOT NULL DEFAULT 0"
                    )
                except psycopg2.errors.DuplicateColumn:
                    conn.rollback()
        else:
            snap_cols = {
                row["name"]
                for row in conn.execute("PRAGMA table_info(snapshots)").fetchall()
            }
            if "is_preview" not in snap_cols:
                try:
                    conn.execute(
                        "ALTER TABLE snapshots ADD COLUMN is_preview INTEGER NOT NULL DEFAULT 0"
                    )
                except sqlite3.OperationalError:
                    pass

        # Migrate payments — add snapshot_id column (NES-132: link payment to preview snapshot).
        if _USE_POSTGRES:
            cur.execute(
                """SELECT column_name FROM information_schema.columns
                   WHERE table_name = 'payments'"""
            )
            pay_cols = {row["column_name"] for row in cur.fetchall()}
            if "snapshot_id" not in pay_cols:
                try:
                    cur.execute(
                        "ALTER TABLE payments ADD COLUMN snapshot_id TEXT"
                    )
                except psycopg2.errors.DuplicateColumn:
                    conn.rollback()
        else:
            pay_cols = {
                row["name"]
                for row in conn.execute("PRAGMA table_info(payments)").fetchall()
            }
            if "snapshot_id" not in pay_cols:
                try:
                    conn.execute(
                        "ALTER TABLE payments ADD COLUMN snapshot_id TEXT"
                    )
                except sqlite3.OperationalError:
                    pass

        conn.commit()
    finally:
        _return_conn(conn)


# ---------------------------------------------------------------------------
# Snapshots
# ---------------------------------------------------------------------------

def generate_snapshot_id():
    """Short, URL-safe snapshot ID (8 chars)."""
    return uuid.uuid4().hex[:8]


def save_snapshot(address_input, address_norm, result_dict, is_preview=False):
    """Persist an evaluation snapshot. Returns the snapshot_id.

    result_dict is the full template-ready dict from result_to_dict().
    is_preview: if True, snapshot is saved as a gated preview (NES-132).
    """
    snapshot_id = generate_snapshot_id()
    now = datetime.now(timezone.utc).isoformat()
    conn = _get_db()
    try:
        cur = _cursor(conn)
        cur.execute(
            _q("""INSERT INTO snapshots
                   (snapshot_id, address_input, address_norm, created_at,
                    verdict, final_score, passed_tier1, is_preview, result_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)"""),
            (
                snapshot_id,
                address_input,
                address_norm or address_input,
                now,
                result_dict.get("verdict", ""),
                result_dict.get("final_score", 0),
                1 if result_dict.get("passed_tier1") else 0,
                1 if is_preview else 0,
                json.dumps(result_dict, default=str),
            ),
        )
        conn.commit()
        return snapshot_id
    finally:
        _return_conn(conn)


def get_snapshot(snapshot_id):
    """Load a snapshot by ID. Returns dict with metadata + result_json parsed,
    or None if not found.
    """
    print(f"GET_SNAPSHOT: looking for {snapshot_id!r}, db_path={DB_PATH!r}")
    conn = _get_db()
    try:
        cur = _cursor(conn)
        cur.execute(
            _q("SELECT * FROM snapshots WHERE snapshot_id = ?"),
            (snapshot_id,),
        )
        row = cur.fetchone()
        if not row:
            return None
        data = dict(row)
        try:
            data["result"] = json.loads(data["result_json"])
        except (json.JSONDecodeError, TypeError) as e:
            logger.error("Corrupted result_json for snapshot %s: %s", snapshot_id, e)
            return None
        return data
    finally:
        _return_conn(conn)


def unlock_snapshot(snapshot_id: str) -> bool:
    """Flip a preview snapshot to unlocked (NES-132).

    Returns True if a row was actually updated (was a preview).
    Idempotent: calling on an already-unlocked snapshot returns False.
    """
    conn = _get_db()
    try:
        cur = _cursor(conn)
        cur.execute(
            _q("UPDATE snapshots SET is_preview = 0 WHERE snapshot_id = ? AND is_preview = 1"),
            (snapshot_id,),
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        _return_conn(conn)


def increment_view_count(snapshot_id):
    """Bump the view counter for a snapshot."""
    conn = _get_db()
    try:
        cur = _cursor(conn)
        cur.execute(
            _q("UPDATE snapshots SET view_count = view_count + 1 WHERE snapshot_id = ?"),
            (snapshot_id,),
        )
        conn.commit()
    finally:
        _return_conn(conn)


# ---------------------------------------------------------------------------
# Analytics events
# ---------------------------------------------------------------------------

def log_event(event_type, snapshot_id=None, visitor_id=None, metadata=None):
    """Append an analytics event.

    event_type: one of snapshot_created, snapshot_viewed, snapshot_shared,
                return_visit, evaluation_error
    metadata:   optional dict of extra info
    """
    now = datetime.now(timezone.utc).isoformat()
    conn = _get_db()
    try:
        cur = _cursor(conn)
        cur.execute(
            _q("""INSERT INTO events (event_type, snapshot_id, visitor_id, metadata, created_at)
                   VALUES (?, ?, ?, ?, ?)"""),
            (
                event_type,
                snapshot_id,
                visitor_id,
                json.dumps(metadata) if metadata else None,
                now,
            ),
        )
        conn.commit()
    finally:
        _return_conn(conn)


def check_return_visit(visitor_id, days=7):
    """Check if this visitor created a snapshot within the last `days` days.
    Returns True if they did (meaning this is a return visit).
    """
    if not visitor_id:
        return False
    conn = _get_db()
    try:
        cur = _cursor(conn)
        if _USE_POSTGRES:
            cur.execute(
                """SELECT COUNT(*) as cnt FROM events
                   WHERE event_type = 'snapshot_created'
                     AND visitor_id = %s
                     AND created_at >= (NOW() - %s * INTERVAL '1 day')""",
                (visitor_id, days),
            )
        else:
            cur.execute(
                """SELECT COUNT(*) as cnt FROM events
                   WHERE event_type = 'snapshot_created'
                     AND visitor_id = ?
                     AND created_at >= datetime('now', ?)""",
                (visitor_id, f"-{days} days"),
            )
        row = cur.fetchone()
        return row["cnt"] > 0 if row else False
    finally:
        _return_conn(conn)


def get_event_counts():
    """Builder utility: get event counts by type.
    Returns dict like {"snapshot_created": 12, "snapshot_viewed": 45, ...}
    """
    conn = _get_db()
    try:
        cur = _cursor(conn)
        cur.execute(
            "SELECT event_type, COUNT(*) as cnt FROM events GROUP BY event_type"
        )
        rows = cur.fetchall()
        return {row["event_type"]: row["cnt"] for row in rows}
    finally:
        _return_conn(conn)


def get_recent_events(limit=50):
    """Builder utility: get recent events for inspection."""
    conn = _get_db()
    try:
        cur = _cursor(conn)
        cur.execute(
            _q("SELECT * FROM events ORDER BY created_at DESC LIMIT ?"),
            (limit,),
        )
        return [dict(row) for row in cur.fetchall()]
    finally:
        _return_conn(conn)


def get_recent_snapshots(limit=20):
    """Builder utility: get recent snapshots for inspection."""
    conn = _get_db()
    try:
        cur = _cursor(conn)
        cur.execute(
            _q("""SELECT snapshot_id, address_input, address_norm, created_at,
                          verdict, final_score, passed_tier1, view_count
                   FROM snapshots ORDER BY created_at DESC LIMIT ?"""),
            (limit,),
        )
        return [dict(row) for row in cur.fetchall()]
    finally:
        _return_conn(conn)


# ---------------------------------------------------------------------------
# Evaluation job queue (async evaluation)
# ---------------------------------------------------------------------------

def create_job(address, visitor_id=None, request_id=None, place_id=None, email_hash=None):
    """Enqueue an evaluation job. Returns job_id.

    address: raw address string from the user.
    place_id: optional Google Places place_id for direct geocoding.
    email_hash: optional SHA-256 hash of the user's email (free tier tracking).
    """
    job_id = uuid.uuid4().hex[:12]
    now = datetime.now(timezone.utc).isoformat()
    conn = _get_db()
    try:
        cur = _cursor(conn)
        cur.execute(
            _q("""INSERT INTO evaluation_jobs
                   (job_id, address, visitor_id, request_id, place_id, email_hash, status, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, 'queued', ?)"""),
            (job_id, address, visitor_id, request_id, place_id, email_hash, now),
        )
        conn.commit()
        return job_id
    finally:
        _return_conn(conn)


def get_job(job_id):
    """Load a job by ID. Returns dict or None if not found."""
    conn = _get_db()
    try:
        cur = _cursor(conn)
        cur.execute(
            _q("SELECT * FROM evaluation_jobs WHERE job_id = ?"),
            (job_id,),
        )
        row = cur.fetchone()
        return dict(row) if row else None
    finally:
        _return_conn(conn)


def claim_next_job():
    """Atomically claim the next queued job (set status to 'running').

    Postgres: uses FOR UPDATE SKIP LOCKED for true atomic claim.
    SQLite: uses SELECT + conditional UPDATE with rowcount check.
    Returns the job dict or None if no queued job.
    """
    now = datetime.now(timezone.utc).isoformat()
    conn = _get_db()
    try:
        cur = _cursor(conn)

        if _USE_POSTGRES:
            # Single atomic UPDATE ... FROM (SELECT ... FOR UPDATE SKIP LOCKED)
            # guarantees exactly one worker claims each job.
            cur.execute(
                """UPDATE evaluation_jobs
                   SET status = 'running', started_at = %s
                   FROM (
                       SELECT job_id FROM evaluation_jobs
                       WHERE status = 'queued'
                       ORDER BY created_at ASC
                       LIMIT 1
                       FOR UPDATE SKIP LOCKED
                   ) AS next_job
                   WHERE evaluation_jobs.job_id = next_job.job_id
                   RETURNING evaluation_jobs.*""",
                (now,),
            )
            row = cur.fetchone()
            conn.commit()
            return dict(row) if row else None
        else:
            # SQLite path: SELECT then conditional UPDATE
            cur.execute(
                "SELECT job_id FROM evaluation_jobs WHERE status = 'queued' ORDER BY created_at ASC LIMIT 1"
            )
            row = cur.fetchone()
            if not row:
                return None
            job_id = row["job_id"]
            cur.execute(
                "UPDATE evaluation_jobs SET status = 'running', started_at = ? WHERE job_id = ? AND status = 'queued'",
                (now, job_id),
            )
            if cur.rowcount == 0:
                return None  # Another worker claimed it
            conn.commit()
            cur.execute(
                "SELECT * FROM evaluation_jobs WHERE job_id = ?", (job_id,)
            )
            job = cur.fetchone()
            return dict(job) if job else None
    finally:
        _return_conn(conn)


def update_job_stage(job_id, current_stage):
    """Update the current_stage for a running job (for progress display)."""
    conn = _get_db()
    try:
        cur = _cursor(conn)
        cur.execute(
            _q("UPDATE evaluation_jobs SET current_stage = ? WHERE job_id = ? AND status = 'running'"),
            (current_stage, job_id),
        )
        conn.commit()
    finally:
        _return_conn(conn)


def complete_job(job_id, result_snapshot_id):
    """Mark job as done and store the snapshot ID."""
    now = datetime.now(timezone.utc).isoformat()
    conn = _get_db()
    try:
        cur = _cursor(conn)
        cur.execute(
            _q("""UPDATE evaluation_jobs
                   SET status = 'done', result_snapshot_id = ?, completed_at = ?, current_stage = NULL
                   WHERE job_id = ?"""),
            (result_snapshot_id, now, job_id),
        )
        conn.commit()
    finally:
        _return_conn(conn)


def fail_job(job_id, error_message):
    """Mark job as failed and store the error message."""
    now = datetime.now(timezone.utc).isoformat()
    conn = _get_db()
    try:
        cur = _cursor(conn)
        cur.execute(
            _q("""UPDATE evaluation_jobs
                   SET status = 'failed', error = ?, completed_at = ?, current_stage = NULL
                   WHERE job_id = ?"""),
            (error_message[:2000] if error_message else None, now, job_id),
        )
        conn.commit()
    finally:
        _return_conn(conn)


def cancel_queued_job(job_id: str, reason: str) -> bool:
    """Fail a job only if it is still queued (not yet claimed by the worker).

    Returns True if the job was cancelled, False if the worker already
    claimed it.  The status guard (WHERE status = 'queued') prevents
    clobbering a job that transitioned to 'running' between create_job()
    and this call.
    """
    now = datetime.now(timezone.utc).isoformat()
    conn = _get_db()
    try:
        cur = _cursor(conn)
        cur.execute(
            _q("""UPDATE evaluation_jobs
                   SET status = 'failed', error = ?, completed_at = ?
                   WHERE job_id = ? AND status = 'queued'"""),
            (reason[:2000] if reason else None, now, job_id),
        )
        changed = cur.rowcount
        conn.commit()
        return changed > 0
    finally:
        _return_conn(conn)


def requeue_stale_running_jobs(max_age_seconds=300):
    """Requeue jobs stuck in 'running' beyond max_age_seconds.
    Returns the number of jobs reset.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=max_age_seconds)
    cutoff_iso = cutoff.isoformat()
    conn = _get_db()
    try:
        cur = _cursor(conn)
        cur.execute(
            _q("""UPDATE evaluation_jobs
                   SET status = 'queued',
                       started_at = NULL,
                       completed_at = NULL,
                       current_stage = NULL,
                       error = NULL
                   WHERE status = 'running' AND started_at IS NOT NULL AND started_at <= ?"""),
            (cutoff_iso,),
        )
        count = cur.rowcount
        conn.commit()
        return count
    finally:
        _return_conn(conn)


# ---------------------------------------------------------------------------
# Overpass API response cache (second-level persistent cache)
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
        # Postgres returns datetime objects; SQLite returns ISO strings
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
            cur = _cursor(conn)
            cur.execute(
                _q("""SELECT response_json, created_at FROM overpass_cache
                       WHERE cache_key = ?"""),
                (cache_key,),
            )
            row = cur.fetchone()
            if not row:
                return None
            if not _check_cache_ttl(row["created_at"], _OVERPASS_CACHE_TTL_DAYS):
                return None
            return row["response_json"]
        finally:
            _return_conn(conn)
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
            cur = _cursor(conn)
            now = datetime.now(timezone.utc).isoformat()
            if _USE_POSTGRES:
                cur.execute(
                    """INSERT INTO overpass_cache (cache_key, response_json, created_at)
                       VALUES (%s, %s, %s)
                       ON CONFLICT (cache_key) DO UPDATE
                       SET response_json = EXCLUDED.response_json,
                           created_at = EXCLUDED.created_at""",
                    (cache_key, response_json, now),
                )
            else:
                cur.execute(
                    """INSERT OR REPLACE INTO overpass_cache (cache_key, response_json, created_at)
                       VALUES (?, ?, ?)""",
                    (cache_key, response_json, now),
                )
            conn.commit()
        finally:
            _return_conn(conn)
    except Exception:
        logger.warning("Overpass cache write failed", exc_info=True)


# ---------------------------------------------------------------------------
# Weather climate normals cache (NES-32)
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
            cur = _cursor(conn)
            cur.execute(
                _q("""SELECT summary_json, created_at FROM weather_cache
                       WHERE cache_key = ?"""),
                (cache_key,),
            )
            row = cur.fetchone()
            if not row:
                return None
            if not _check_cache_ttl(row["created_at"], _WEATHER_CACHE_TTL_DAYS):
                return None
            return row["summary_json"]
        finally:
            _return_conn(conn)
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
            cur = _cursor(conn)
            now = datetime.now(timezone.utc).isoformat()
            if _USE_POSTGRES:
                cur.execute(
                    """INSERT INTO weather_cache (cache_key, summary_json, created_at)
                       VALUES (%s, %s, %s)
                       ON CONFLICT (cache_key) DO UPDATE
                       SET summary_json = EXCLUDED.summary_json,
                           created_at = EXCLUDED.created_at""",
                    (cache_key, summary_json, now),
                )
            else:
                cur.execute(
                    """INSERT OR REPLACE INTO weather_cache (cache_key, summary_json, created_at)
                       VALUES (?, ?, ?)""",
                    (cache_key, summary_json, now),
                )
            conn.commit()
        finally:
            _return_conn(conn)
    except Exception:
        logger.warning("Weather cache write failed", exc_info=True)


# ---------------------------------------------------------------------------
# Payments (Stripe one-time evaluation credits)
# ---------------------------------------------------------------------------

def create_payment(
    payment_id: str,
    stripe_session_id: str,
    visitor_id: str,
    address: str,
    snapshot_id: str = None,
) -> None:
    """Insert a new payment row with status 'pending'.

    Called when a Stripe Checkout session is created, before the user pays.
    snapshot_id: optional — set when this payment unlocks a preview snapshot (NES-132).
    """
    now = datetime.now(timezone.utc).isoformat()
    conn = _get_db()
    try:
        cur = _cursor(conn)
        cur.execute(
            _q("""INSERT INTO payments
                   (id, stripe_session_id, visitor_id, address, status, created_at, snapshot_id)
                   VALUES (?, ?, ?, ?, 'pending', ?, ?)"""),
            (payment_id, stripe_session_id, visitor_id, address, now, snapshot_id),
        )
        conn.commit()
    finally:
        _return_conn(conn)


def get_payment_by_session(stripe_session_id: str) -> Optional[dict]:
    """Look up a payment by Stripe Checkout session ID. Returns dict or None."""
    conn = _get_db()
    try:
        cur = _cursor(conn)
        cur.execute(
            _q("SELECT * FROM payments WHERE stripe_session_id = ?"),
            (stripe_session_id,),
        )
        row = cur.fetchone()
        return dict(row) if row else None
    finally:
        _return_conn(conn)


def get_payment_by_id(payment_id: str) -> Optional[dict]:
    """Look up a payment by its internal ID (the payment token). Returns dict or None."""
    conn = _get_db()
    try:
        cur = _cursor(conn)
        cur.execute(
            _q("SELECT * FROM payments WHERE id = ?"),
            (payment_id,),
        )
        row = cur.fetchone()
        return dict(row) if row else None
    finally:
        _return_conn(conn)


def update_payment_status(payment_id: str, status: str, expected_status: Optional[str] = None) -> bool:
    """Update the status of a payment row. Returns True if a row was updated.

    When expected_status is provided, the update is atomic: it only succeeds
    if the current status matches, preventing TOCTOU races (e.g. webhook
    overwriting a status that changed between the read and the write).
    """
    conn = _get_db()
    try:
        cur = _cursor(conn)
        if expected_status is not None:
            cur.execute(
                _q("UPDATE payments SET status = ? WHERE id = ? AND status = ?"),
                (status, payment_id, expected_status),
            )
        else:
            cur.execute(
                _q("UPDATE payments SET status = ? WHERE id = ?"),
                (status, payment_id),
            )
        changed = cur.rowcount
        conn.commit()
        return changed > 0
    finally:
        _return_conn(conn)


def redeem_payment(payment_id: str, job_id: Optional[str] = None) -> bool:
    """Atomically redeem a payment credit (status paid -> redeemed).

    Sets redeemed_at to now and optionally links to a job_id.
    Returns True if the UPDATE affected exactly one row (status was 'paid'
    or 'failed_reissued'), False otherwise.  Uses cursor.rowcount so
    concurrent double-redeem attempts are rejected.
    """
    now = datetime.now(timezone.utc).isoformat()
    conn = _get_db()
    try:
        cur = _cursor(conn)
        cur.execute(
            _q("""UPDATE payments
                   SET status = 'redeemed', redeemed_at = ?, job_id = ?
                   WHERE id = ? AND status IN ('paid', 'failed_reissued')"""),
            (now, job_id, payment_id),
        )
        changed = cur.rowcount
        conn.commit()
        return changed > 0
    finally:
        _return_conn(conn)


def update_payment_job_id(payment_id: str, job_id: str) -> None:
    """Link a payment to the evaluation job it funded."""
    conn = _get_db()
    try:
        cur = _cursor(conn)
        cur.execute(
            _q("UPDATE payments SET job_id = ? WHERE id = ?"),
            (job_id, payment_id),
        )
        conn.commit()
    finally:
        _return_conn(conn)


def get_payment_by_job_id(job_id: str) -> Optional[dict]:
    """Look up a payment by the evaluation job it funded. Returns dict or None."""
    conn = _get_db()
    try:
        cur = _cursor(conn)
        cur.execute(
            _q("SELECT * FROM payments WHERE job_id = ?"),
            (job_id,),
        )
        row = cur.fetchone()
        return dict(row) if row else None
    finally:
        _return_conn(conn)


# ---------------------------------------------------------------------------
# Free tier usage (one evaluation per email, lifetime)
# ---------------------------------------------------------------------------

def hash_email(email: str) -> str:
    """Deterministic SHA-256 hash of a lowercased, stripped email address."""
    return hashlib.sha256(email.lower().strip().encode()).hexdigest()


def check_free_tier_used(email_hash: str) -> bool:
    """Return True if this email hash has already claimed a free evaluation."""
    conn = _get_db()
    try:
        cur = _cursor(conn)
        cur.execute(
            _q("SELECT 1 FROM free_tier_usage WHERE email_hash = ?"),
            (email_hash,),
        )
        return cur.fetchone() is not None
    finally:
        _return_conn(conn)


def record_free_tier_usage(email_hash: str, email_raw: str, job_id: str) -> bool:
    """Atomically record a free tier claim. Returns True if inserted, False if duplicate.

    Uses INSERT ... ON CONFLICT DO NOTHING (Postgres) or INSERT OR IGNORE (SQLite)
    + rowcount so two concurrent requests with the same email hash cannot both succeed.
    """
    conn = _get_db()
    try:
        cur = _cursor(conn)
        if _USE_POSTGRES:
            cur.execute(
                """INSERT INTO free_tier_usage (email_hash, email_raw, job_id)
                   VALUES (%s, %s, %s)
                   ON CONFLICT (email_hash) DO NOTHING""",
                (email_hash, email_raw, job_id),
            )
        else:
            cur.execute(
                """INSERT OR IGNORE INTO free_tier_usage (email_hash, email_raw, job_id)
                   VALUES (?, ?, ?)""",
                (email_hash, email_raw, job_id),
            )
        inserted = cur.rowcount > 0
        conn.commit()
        return inserted
    finally:
        _return_conn(conn)


def delete_free_tier_usage(job_id: str) -> bool:
    """Remove a free tier claim by job_id so the user can retry.

    Called when an evaluation fails, mirroring _reissue_payment_if_needed.
    Returns True if a row was deleted.
    """
    conn = _get_db()
    try:
        cur = _cursor(conn)
        cur.execute(
            _q("DELETE FROM free_tier_usage WHERE job_id = ?"),
            (job_id,),
        )
        deleted = cur.rowcount > 0
        conn.commit()
        return deleted
    finally:
        _return_conn(conn)


def update_free_tier_snapshot(email_hash: str, snapshot_id: str) -> None:
    """Link a free tier usage row to its completed snapshot."""
    conn = _get_db()
    try:
        cur = _cursor(conn)
        cur.execute(
            _q("UPDATE free_tier_usage SET snapshot_id = ? WHERE email_hash = ?"),
            (snapshot_id, email_hash),
        )
        conn.commit()
    finally:
        _return_conn(conn)
