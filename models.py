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
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

DB_PATH = os.environ.get("NESTCHECK_DB_PATH", "nestcheck.db")


def _get_db():
    """Get a sqlite3 connection with WAL mode for concurrent reads."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
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
            view_count      INTEGER NOT NULL DEFAULT 0,
            email           TEXT,
            email_sent_at   TEXT
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
        CREATE TABLE IF NOT EXISTS census_cache (
            cache_key     TEXT PRIMARY KEY,
            data_json     TEXT NOT NULL,
            created_at    TEXT
        );

        CREATE TABLE IF NOT EXISTS evaluation_jobs (
            job_id          TEXT PRIMARY KEY,
            address         TEXT NOT NULL,
            status          TEXT NOT NULL DEFAULT 'queued',
            current_stage   TEXT,
            snapshot_id     TEXT,
            error           TEXT,
            visitor_id      TEXT,
            request_id      TEXT,
            place_id        TEXT,
            email_hash      TEXT,
            persona         TEXT,
            email_raw       TEXT,
            created_at      TEXT NOT NULL,
            started_at      TEXT,
            completed_at    TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_jobs_status ON evaluation_jobs(status);

        CREATE TABLE IF NOT EXISTS users (
            id              TEXT PRIMARY KEY,
            email           TEXT UNIQUE NOT NULL,
            name            TEXT,
            picture_url     TEXT,
            google_sub      TEXT UNIQUE,
            created_at      TEXT DEFAULT (datetime('now')),
            last_login_at   TEXT
        );

        CREATE TABLE IF NOT EXISTS payments (
            id                TEXT PRIMARY KEY,
            stripe_session_id TEXT UNIQUE,
            visitor_id        TEXT,
            address           TEXT,
            snapshot_id       TEXT,
            job_id            TEXT,
            status            TEXT NOT NULL DEFAULT 'pending',
            redeemed_at       TEXT,
            created_at        TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS free_tier_usage (
            email_hash   TEXT PRIMARY KEY,
            email_raw    TEXT,
            job_id       TEXT,
            snapshot_id  TEXT,
            created_at   TEXT NOT NULL
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
    if "email" not in cols:
        conn.execute("ALTER TABLE snapshots ADD COLUMN email TEXT")
    if "email_sent_at" not in cols:
        conn.execute("ALTER TABLE snapshots ADD COLUMN email_sent_at TEXT")
    if "user_id" not in cols:
        conn.execute("ALTER TABLE snapshots ADD COLUMN user_id TEXT REFERENCES users(id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_snapshots_user_id ON snapshots(user_id)")

    # Migration for evaluation_jobs: add user_id column
    job_cols = {
        row["name"]
        for row in conn.execute("PRAGMA table_info(evaluation_jobs)").fetchall()
    }
    if "user_id" not in job_cols:
        conn.execute("ALTER TABLE evaluation_jobs ADD COLUMN user_id TEXT")

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


def save_snapshot(address_input, address_norm, result_dict, email=None, **kwargs):
    """
    Persist an evaluation snapshot. Returns the snapshot_id.

    result_dict is the full template-ready dict from result_to_dict().
    email: optional address to send report link to.
    **kwargs: accepts is_preview, email_hash, email_raw (from worker) for forward compat.
    """
    email = email or kwargs.get("email_raw")
    user_id = kwargs.get("user_id")
    snapshot_id = generate_snapshot_id()
    now = datetime.now(timezone.utc).isoformat()

    conn = _get_db()
    conn.execute(
        """INSERT INTO snapshots
           (snapshot_id, address_input, address_norm, place_id, evaluated_at, created_at,
            verdict, final_score, passed_tier1, result_json, email, user_id)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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
            email,
            user_id,
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


def check_snapshots_exist(snapshot_ids):
    """Check which snapshot IDs exist without loading full result data.

    Returns a set of snapshot IDs that were found in the database.
    """
    if not snapshot_ids:
        return set()

    placeholders = ",".join(["?"] * len(snapshot_ids))
    conn = _get_db()
    rows = conn.execute(
        f"SELECT snapshot_id FROM snapshots WHERE snapshot_id IN ({placeholders})",
        tuple(snapshot_ids),
    ).fetchall()
    conn.close()
    return {row["snapshot_id"] for row in rows}


def update_snapshot_email_sent(snapshot_id: str) -> None:
    """Mark that the report email was sent for this snapshot."""
    now = datetime.now(timezone.utc).isoformat()
    conn = _get_db()
    conn.execute(
        "UPDATE snapshots SET email_sent_at = ? WHERE snapshot_id = ?",
        (now, snapshot_id),
    )
    conn.commit()
    conn.close()


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
    email=None,
    user_id=None,
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
                       verdict = ?, final_score = ?, passed_tier1 = ?, result_json = ?,
                       email = COALESCE(?, email)
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
                    email,
                    existing_snapshot_id,
                ),
            )
            conn.commit()
            return existing_snapshot_id

        snapshot_id = generate_snapshot_id()
        conn.execute(
            """INSERT INTO snapshots
               (snapshot_id, address_input, address_norm, place_id, evaluated_at, created_at,
                verdict, final_score, passed_tier1, result_json, email, user_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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
                email,
                user_id,
            ),
        )
        conn.commit()
        return snapshot_id
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Evaluation job queue
# ---------------------------------------------------------------------------

def create_job(address: str, visitor_id: str = None, request_id: str = None,
               place_id: str = None, email_hash: str = None,
               persona: str = None, email_raw: str = None,
               user_id: str = None) -> str:
    """Insert a new evaluation job and return its job_id.

    Retries up to 3 times on transient SQLite busy errors to handle
    concurrent writes from multiple gunicorn workers.
    """
    job_id = uuid.uuid4().hex[:12]
    now = datetime.now(timezone.utc).isoformat()
    last_err = None
    for attempt in range(3):
        try:
            conn = _get_db()
            try:
                conn.execute(
                    """INSERT INTO evaluation_jobs
                       (job_id, address, status, visitor_id, request_id, place_id,
                        email_hash, persona, email_raw, user_id, created_at)
                       VALUES (?, ?, 'queued', ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (job_id, address, visitor_id, request_id, place_id,
                     email_hash, persona, email_raw, user_id, now),
                )
                conn.commit()
                return job_id
            finally:
                conn.close()
        except sqlite3.OperationalError as e:
            last_err = e
            if "locked" in str(e) or "busy" in str(e):
                logger.warning("create_job retry %d/3: %s", attempt + 1, e)
                time.sleep(0.5 * (attempt + 1))
                continue
            raise
    raise last_err


def get_job(job_id: str) -> Optional[dict]:
    """Return job row as a dict, or None.

    Retries once on transient SQLite errors to handle concurrent access.
    """
    for attempt in range(2):
        try:
            conn = _get_db()
            try:
                row = conn.execute(
                    "SELECT * FROM evaluation_jobs WHERE job_id = ?", (job_id,)
                ).fetchone()
                return dict(row) if row else None
            finally:
                conn.close()
        except sqlite3.OperationalError as e:
            if attempt == 0 and ("locked" in str(e) or "busy" in str(e)):
                logger.warning("get_job retry: %s", e)
                time.sleep(0.3)
                continue
            raise
    return None


def claim_next_job() -> Optional[dict]:
    """Atomically claim the oldest queued job. Returns the job dict or None."""
    now = datetime.now(timezone.utc).isoformat()
    conn = _get_db()
    try:
        row = conn.execute(
            """SELECT job_id FROM evaluation_jobs
               WHERE status = 'queued'
               ORDER BY created_at ASC LIMIT 1"""
        ).fetchone()
        if not row:
            return None
        job_id = row["job_id"]
        conn.execute(
            """UPDATE evaluation_jobs
               SET status = 'running', started_at = ?
               WHERE job_id = ? AND status = 'queued'""",
            (now, job_id),
        )
        conn.commit()
        if conn.total_changes == 0:
            return None
        full = conn.execute(
            "SELECT * FROM evaluation_jobs WHERE job_id = ?", (job_id,)
        ).fetchone()
        return dict(full) if full else None
    finally:
        conn.close()


def update_job_stage(job_id: str, stage: str) -> None:
    """Update the current_stage for a running job (progress reporting)."""
    conn = _get_db()
    conn.execute(
        "UPDATE evaluation_jobs SET current_stage = ? WHERE job_id = ?",
        (stage, job_id),
    )
    conn.commit()
    conn.close()


def complete_job(job_id: str, snapshot_id: str) -> None:
    """Mark a job as done with its resulting snapshot_id."""
    now = datetime.now(timezone.utc).isoformat()
    conn = _get_db()
    conn.execute(
        """UPDATE evaluation_jobs
           SET status = 'done', snapshot_id = ?, completed_at = ?
           WHERE job_id = ?""",
        (snapshot_id, now, job_id),
    )
    conn.commit()
    conn.close()


def fail_job(job_id: str, error: str) -> None:
    """Mark a job as failed with an error message."""
    now = datetime.now(timezone.utc).isoformat()
    conn = _get_db()
    conn.execute(
        """UPDATE evaluation_jobs
           SET status = 'failed', error = ?, completed_at = ?
           WHERE job_id = ?""",
        (error, now, job_id),
    )
    conn.commit()
    conn.close()


def requeue_stale_running_jobs(max_age_seconds: int = 300) -> int:
    """Re-queue jobs stuck in 'running' longer than max_age_seconds.

    Returns the number of jobs re-queued.
    """
    conn = _get_db()
    cutoff = (
        datetime.now(timezone.utc) - timedelta(seconds=max_age_seconds)
    ).isoformat()
    conn.execute(
        """UPDATE evaluation_jobs
           SET status = 'queued', started_at = NULL, current_stage = NULL
           WHERE status = 'running' AND started_at < ?""",
        (cutoff,),
    )
    swept = conn.total_changes
    conn.commit()
    conn.close()
    return swept


# ---------------------------------------------------------------------------
# Payment operations
# ---------------------------------------------------------------------------

def create_payment(
    payment_id: str,
    stripe_session_id: str,
    visitor_id: str,
    address: str,
    snapshot_id: Optional[str] = None,
) -> None:
    """Insert a new payment row in 'pending' status."""
    now = datetime.now(timezone.utc).isoformat()
    conn = _get_db()
    try:
        conn.execute(
            """INSERT INTO payments
               (id, stripe_session_id, visitor_id, address, snapshot_id, status, created_at)
               VALUES (?, ?, ?, ?, ?, 'pending', ?)""",
            (payment_id, stripe_session_id, visitor_id, address, snapshot_id, now),
        )
        conn.commit()
    finally:
        conn.close()


def get_payment_by_id(payment_id: str) -> Optional[dict]:
    """Look up a payment by its primary key. Returns dict or None."""
    conn = _get_db()
    try:
        row = conn.execute(
            "SELECT * FROM payments WHERE id = ?", (payment_id,)
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_payment_by_session(session_id: str) -> Optional[dict]:
    """Look up a payment by Stripe Checkout session ID. Returns dict or None."""
    conn = _get_db()
    try:
        row = conn.execute(
            "SELECT * FROM payments WHERE stripe_session_id = ?", (session_id,)
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_payment_by_job_id(job_id: str) -> Optional[dict]:
    """Look up a payment by linked evaluation job ID. Returns dict or None."""
    conn = _get_db()
    try:
        row = conn.execute(
            "SELECT * FROM payments WHERE job_id = ?", (job_id,)
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def update_payment_status(
    payment_id: str, status: str, expected_status: Optional[str] = None
) -> bool:
    """Transition a payment to a new status.

    If expected_status is provided, the update is atomic (CAS): it only
    succeeds when the current status matches expected_status.
    Returns True if a row was updated, False otherwise.
    """
    conn = _get_db()
    try:
        if expected_status is not None:
            cur = conn.execute(
                "UPDATE payments SET status = ? WHERE id = ? AND status = ?",
                (status, payment_id, expected_status),
            )
        else:
            cur = conn.execute(
                "UPDATE payments SET status = ? WHERE id = ?",
                (status, payment_id),
            )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def redeem_payment(payment_id: str, job_id: Optional[str] = None) -> bool:
    """Atomically transition a payment from paid/failed_reissued to redeemed.

    Only payments in 'paid' or 'failed_reissued' status can be redeemed.
    Sets redeemed_at timestamp and optionally links a job_id.
    Returns True if redemption succeeded, False otherwise.
    """
    now = datetime.now(timezone.utc).isoformat()
    conn = _get_db()
    try:
        cur = conn.execute(
            """UPDATE payments
               SET status = 'redeemed', redeemed_at = ?, job_id = ?
               WHERE id = ? AND status IN ('paid', 'failed_reissued')""",
            (now, job_id, payment_id),
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def update_payment_job_id(payment_id: str, job_id: str) -> None:
    """Link a payment to an evaluation job (e.g. after job creation)."""
    conn = _get_db()
    try:
        conn.execute(
            "UPDATE payments SET job_id = ? WHERE id = ?",
            (job_id, payment_id),
        )
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Free tier usage
# ---------------------------------------------------------------------------

def hash_email(email: str) -> str:
    """Deterministic, case-insensitive SHA-256 hash of an email address."""
    normalised = email.strip().lower()
    return hashlib.sha256(normalised.encode()).hexdigest()


def check_free_tier_used(email_hash: str) -> bool:
    """Return True if the given email hash has already used its free evaluation."""
    conn = _get_db()
    try:
        row = conn.execute(
            "SELECT 1 FROM free_tier_usage WHERE email_hash = ?", (email_hash,)
        ).fetchone()
        return row is not None
    finally:
        conn.close()


def record_free_tier_usage(
    email_hash: str, email_raw: str, job_id: str
) -> bool:
    """Record a free-tier evaluation claim. Returns True if inserted, False if duplicate."""
    now = datetime.now(timezone.utc).isoformat()
    conn = _get_db()
    try:
        conn.execute(
            """INSERT INTO free_tier_usage (email_hash, email_raw, job_id, created_at)
               VALUES (?, ?, ?, ?)""",
            (email_hash, email_raw, job_id, now),
        )
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()


def delete_free_tier_usage(job_id: str) -> bool:
    """Delete a free-tier claim by job_id (for reissue on failure).

    Returns True if a row was deleted, False otherwise.
    """
    conn = _get_db()
    try:
        cur = conn.execute(
            "DELETE FROM free_tier_usage WHERE job_id = ?", (job_id,)
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def update_free_tier_snapshot(email_hash: str, snapshot_id: str) -> None:
    """Backfill the snapshot_id on a free-tier usage row after evaluation completes."""
    conn = _get_db()
    try:
        conn.execute(
            "UPDATE free_tier_usage SET snapshot_id = ? WHERE email_hash = ?",
            (snapshot_id, email_hash),
        )
        conn.commit()
    finally:
        conn.close()


def _return_conn(conn) -> None:
    """Close a DB connection. Convenience alias used by tests."""
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


def get_overpass_cache(cache_key: str, ttl_days: Optional[int] = None) -> Optional[str]:
    """Look up a cached Overpass response by key.

    Returns the raw JSON string if found and younger than TTL, else None.
    Cache errors are swallowed so they never break an evaluation.
    ttl_days: override TTL for this lookup; if None, uses _OVERPASS_CACHE_TTL_DAYS.
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
            effective_ttl = ttl_days if ttl_days is not None else _OVERPASS_CACHE_TTL_DAYS
            if not _check_cache_ttl(row["created_at"], effective_ttl):
                return None
            return row["response_json"]
        finally:
            conn.close()
    except Exception:
        logger.warning("Overpass cache lookup failed", exc_info=True)
        return None


def get_overpass_cache_stale(cache_key: str) -> Optional[Tuple[str, Optional[str]]]:
    """Return cached data regardless of TTL expiration.

    Returns (json_text, created_at_iso) if entry exists, None if no entry at all.
    Used as fallback when Overpass API is unreachable and fresh cache has expired.
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
            return (row["response_json"], row["created_at"])
        finally:
            conn.close()
    except Exception:
        logger.warning("Overpass stale cache lookup failed", exc_info=True)
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


# ---------------------------------------------------------------------------
# Census cache (90-day TTL)
# ---------------------------------------------------------------------------

_CENSUS_CACHE_TTL_DAYS = 90


def get_census_cache(cache_key: str) -> Optional[str]:
    """Look up cached census data by tract/county key.

    Returns the raw JSON string if found and younger than TTL, else None.
    Cache errors are swallowed so they never break an evaluation.
    """
    try:
        conn = _get_db()
        try:
            row = conn.execute(
                """SELECT data_json, created_at FROM census_cache
                   WHERE cache_key = ?""",
                (cache_key,),
            ).fetchone()
            if not row:
                return None
            if not _check_cache_ttl(row["created_at"], _CENSUS_CACHE_TTL_DAYS):
                return None
            return row["data_json"]
        finally:
            conn.close()
    except Exception:
        logger.warning("Census cache lookup failed", exc_info=True)
        return None


def set_census_cache(cache_key: str, data_json: str) -> None:
    """Store census data in the persistent cache.

    Cache errors are swallowed so they never break an evaluation.
    """
    try:
        conn = _get_db()
        try:
            now = datetime.now(timezone.utc).isoformat()
            conn.execute(
                """INSERT OR REPLACE INTO census_cache (cache_key, data_json, created_at)
                   VALUES (?, ?, ?)""",
                (cache_key, data_json, now),
            )
            conn.commit()
        finally:
            conn.close()
    except Exception:
        logger.warning("Census cache write failed", exc_info=True)


# ---------------------------------------------------------------------------
# User accounts
# ---------------------------------------------------------------------------

def get_user_by_id(user_id: str) -> Optional[dict]:
    """Return user dict by primary key, or None."""
    conn = _get_db()
    try:
        row = conn.execute(
            "SELECT * FROM users WHERE id = ?", (user_id,)
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_user_by_google_sub(google_sub: str) -> Optional[dict]:
    """Return user dict by Google subject ID, or None."""
    conn = _get_db()
    try:
        row = conn.execute(
            "SELECT * FROM users WHERE google_sub = ?", (google_sub,)
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_or_create_user(email: str, name: str = None,
                       picture_url: str = None,
                       google_sub: str = None) -> Tuple[dict, bool]:
    """Find or create a user. Returns (user_dict, created).

    Lookup order: google_sub → email → create new.
    Updates last_login_at on every call.
    """
    now = datetime.now(timezone.utc).isoformat()
    conn = _get_db()
    try:
        # Try google_sub first (stable identifier)
        if google_sub:
            row = conn.execute(
                "SELECT * FROM users WHERE google_sub = ?", (google_sub,)
            ).fetchone()
            if row:
                conn.execute(
                    "UPDATE users SET last_login_at = ?, name = COALESCE(?, name), "
                    "picture_url = COALESCE(?, picture_url) WHERE id = ?",
                    (now, name, picture_url, row["id"]),
                )
                conn.commit()
                user = dict(row)
                user["last_login_at"] = now
                return user, False

        # Try email
        row = conn.execute(
            "SELECT * FROM users WHERE email = ?", (email,)
        ).fetchone()
        if row:
            conn.execute(
                "UPDATE users SET last_login_at = ?, google_sub = COALESCE(?, google_sub), "
                "name = COALESCE(?, name), picture_url = COALESCE(?, picture_url) WHERE id = ?",
                (now, google_sub, name, picture_url, row["id"]),
            )
            conn.commit()
            user = dict(row)
            user["last_login_at"] = now
            return user, False

        # Create new user
        user_id = uuid.uuid4().hex
        conn.execute(
            """INSERT INTO users (id, email, name, picture_url, google_sub, created_at, last_login_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (user_id, email, name, picture_url, google_sub, now, now),
        )
        conn.commit()
        return {
            "id": user_id,
            "email": email,
            "name": name,
            "picture_url": picture_url,
            "google_sub": google_sub,
            "created_at": now,
            "last_login_at": now,
        }, True
    finally:
        conn.close()


def claim_snapshots_for_user(user_id: str, email: str) -> int:
    """Link unclaimed snapshots to a user by matching email.

    Returns the number of snapshots claimed.
    """
    conn = _get_db()
    try:
        cursor = conn.execute(
            "UPDATE snapshots SET user_id = ? WHERE user_id IS NULL AND email = ?",
            (user_id, email),
        )
        conn.commit()
        return cursor.rowcount
    finally:
        conn.close()


def get_user_snapshots(user_id: str, limit: int = 50) -> list:
    """Return snapshots owned by a user, newest first.

    Returns lightweight dicts (no result_json blob).
    """
    conn = _get_db()
    try:
        rows = conn.execute(
            """SELECT snapshot_id, address_input, address_norm, place_id,
                      evaluated_at, created_at, verdict, final_score, passed_tier1
               FROM snapshots
               WHERE user_id = ?
               ORDER BY created_at DESC
               LIMIT ?""",
            (user_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()
