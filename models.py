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

from coverage_config import _STATE_FIPS

logger = logging.getLogger(__name__)

# Reverse lookup: FIPS code → state abbreviation (e.g., "36" → "NY")
_FIPS_TO_STATE = {v: k for k, v in _STATE_FIPS.items()}


def _extract_city_state(result_dict):
    """Extract city name and state abbreviation from result demographics."""
    demographics = result_dict.get("demographics") or {}
    city = demographics.get("place_name") or None
    state_fips = demographics.get("state_fips") or ""
    state_abbr = _FIPS_TO_STATE.get(state_fips)
    return city, state_abbr

DB_PATH = os.environ.get("NESTCHECK_DB_PATH", "nestcheck.db")

# Payment status constants — use these instead of bare strings.
PAYMENT_PENDING = "pending"
PAYMENT_PAID = "paid"
PAYMENT_REDEEMED = "redeemed"
PAYMENT_FAILED_REISSUED = "failed_reissued"


def _get_db():
    """Get a sqlite3 connection with WAL mode for concurrent reads."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _return_conn(conn):
    """Close a DB connection returned by _get_db().

    Convenience for test code that needs direct DB access.
    """
    conn.close()


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
        CREATE TABLE IF NOT EXISTS canopy_cache (
            cache_key     TEXT PRIMARY KEY,
            data_json     TEXT NOT NULL,
            created_at    TEXT NOT NULL DEFAULT (datetime('now'))
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

        CREATE INDEX IF NOT EXISTS idx_payments_stripe_session
            ON payments(stripe_session_id);
        CREATE INDEX IF NOT EXISTS idx_payments_job_id
            ON payments(job_id);

        CREATE TABLE IF NOT EXISTS evaluation_coverage (
            evaluation_id          TEXT,
            address                TEXT,
            latitude               REAL,
            longitude              REAL,
            evaluated_at           TEXT,
            categories_from_cache  TEXT,
            categories_from_api    TEXT,
            api_calls_saved        INTEGER,
            api_calls_made         INTEGER,
            total_duration_seconds REAL
        );
        CREATE INDEX IF NOT EXISTS idx_eval_coverage_addr
            ON evaluation_coverage(address);

        CREATE TABLE IF NOT EXISTS state_requests (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            email       TEXT NOT NULL,
            state_code  TEXT NOT NULL,
            created_at  TEXT NOT NULL
        );
        CREATE UNIQUE INDEX IF NOT EXISTS idx_state_requests_email_state
            ON state_requests(email, state_code);

        CREATE TABLE IF NOT EXISTS state_votes (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            state       TEXT NOT NULL,
            created_at  TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_state_votes_state
            ON state_votes(state);

        CREATE TABLE IF NOT EXISTS feedback (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            snapshot_id TEXT NOT NULL,
            feedback_type TEXT NOT NULL,
            response_json TEXT NOT NULL,
            address_norm TEXT,
            visitor_id  TEXT,
            created_at  TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_feedback_snapshot
            ON feedback(snapshot_id);
        CREATE INDEX IF NOT EXISTS idx_feedback_type
            ON feedback(feedback_type);
    """)

    # Subscriptions table (NES-327)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS subscriptions (
            id                    TEXT PRIMARY KEY,
            user_email            TEXT NOT NULL,
            email_hash            TEXT,
            stripe_subscription_id TEXT UNIQUE,
            stripe_customer_id    TEXT,
            status                TEXT NOT NULL DEFAULT 'active',
            period_start          TEXT NOT NULL,
            period_end            TEXT NOT NULL,
            created_at            TEXT NOT NULL,
            updated_at            TEXT
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_subscriptions_email
        ON subscriptions(user_email)
    """)

    # Migration for subscriptions: add updated_at column (NES-340)
    sub_cols = {
        row["name"]
        for row in conn.execute("PRAGMA table_info(subscriptions)").fetchall()
    }
    if "updated_at" not in sub_cols:
        conn.execute("ALTER TABLE subscriptions ADD COLUMN updated_at TEXT")
        conn.execute(
            "UPDATE subscriptions SET updated_at = created_at "
            "WHERE updated_at IS NULL"
        )

    # Migration for subscriptions: add email_hash column (NES-383)
    if "email_hash" not in sub_cols:
        conn.execute("ALTER TABLE subscriptions ADD COLUMN email_hash TEXT")
        # Backfill cannot use hash_email() in SQL — do it in Python
        rows = conn.execute(
            "SELECT id, user_email FROM subscriptions WHERE email_hash IS NULL"
        ).fetchall()
        for row in rows:
            conn.execute(
                "UPDATE subscriptions SET email_hash = ? WHERE id = ?",
                (hash_email(row["user_email"]), row["id"]),
            )
        conn.commit()
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_subscriptions_email_hash
        ON subscriptions(email_hash)
    """)

    # Free tier counter migration (NES-327)
    try:
        conn.execute("ALTER TABLE free_tier_usage ADD COLUMN eval_count INTEGER DEFAULT 1")
    except sqlite3.OperationalError:
        pass  # column already exists
    try:
        conn.execute("ALTER TABLE free_tier_usage ADD COLUMN window_start TEXT")
    except sqlite3.OperationalError:
        pass  # column already exists
    conn.execute(
        "UPDATE free_tier_usage SET eval_count = 1, window_start = created_at "
        "WHERE eval_count IS NULL"
    )

    # Index for payment→snapshot join (NES-327)
    # (snapshot_id migration merged into the job_cols block below)

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
    if "is_preview" not in cols:
        conn.execute("ALTER TABLE snapshots ADD COLUMN is_preview INTEGER NOT NULL DEFAULT 0")
    if "og_image" not in cols:
        conn.execute("ALTER TABLE snapshots ADD COLUMN og_image BLOB")
    if "city" not in cols:
        conn.execute("ALTER TABLE snapshots ADD COLUMN city TEXT")
    if "state_abbr" not in cols:
        conn.execute("ALTER TABLE snapshots ADD COLUMN state_abbr TEXT")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_snapshots_city_state "
        "ON snapshots(state_abbr, city)"
    )

    # Migration for users: add stripe_customer_id column
    user_cols = {
        row["name"]
        for row in conn.execute("PRAGMA table_info(users)").fetchall()
    }
    if "stripe_customer_id" not in user_cols:
        conn.execute("ALTER TABLE users ADD COLUMN stripe_customer_id TEXT")

    # Migration for evaluation_jobs: add columns missing from original schema
    job_cols = {
        row["name"]
        for row in conn.execute("PRAGMA table_info(evaluation_jobs)").fetchall()
    }
    if "user_id" not in job_cols:
        conn.execute("ALTER TABLE evaluation_jobs ADD COLUMN user_id TEXT")
    if "snapshot_id" not in job_cols:
        conn.execute("ALTER TABLE evaluation_jobs ADD COLUMN snapshot_id TEXT")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_user_id ON evaluation_jobs(user_id)")
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_evaluation_jobs_snapshot_id
        ON evaluation_jobs(snapshot_id)
    """)

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
    # Migration: ensure UNIQUE index on free_tier_usage.email_hash
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_free_tier_email_hash "
        "ON free_tier_usage(email_hash)"
    )

    # Migration: add walk time cache tracking columns to evaluation_coverage (NES-292)
    eval_cov_cols = {
        row["name"]
        for row in conn.execute("PRAGMA table_info(evaluation_coverage)").fetchall()
    }
    if "walk_times_from_cache" not in eval_cov_cols:
        conn.execute(
            "ALTER TABLE evaluation_coverage "
            "ADD COLUMN walk_times_from_cache INTEGER DEFAULT 0"
        )
    if "walk_times_from_api" not in eval_cov_cols:
        conn.execute(
            "ALTER TABLE evaluation_coverage "
            "ADD COLUMN walk_times_from_api INTEGER DEFAULT 0"
        )

    # Migration: add NES-362 columns to feedback table
    fb_cols = {
        row["name"]
        for row in conn.execute("PRAGMA table_info(feedback)").fetchall()
    }
    if "user_id" not in fb_cols:
        conn.execute("ALTER TABLE feedback ADD COLUMN user_id INTEGER")
    if "told_something_new" not in fb_cols:
        conn.execute("ALTER TABLE feedback ADD COLUMN told_something_new INTEGER")
    if "free_text" not in fb_cols:
        conn.execute("ALTER TABLE feedback ADD COLUMN free_text TEXT")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_feedback_snapshot_user "
        "ON feedback(snapshot_id, user_id)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_feedback_snapshot_visitor "
        "ON feedback(snapshot_id, visitor_id)"
    )

    conn.commit()
    conn.close()

    backfill_city_state()


def backfill_city_state():
    """Backfill city/state_abbr from result_json demographics.
    Runs on every startup. Returns quickly (0 rows) once populated.
    """
    conn = _get_db()
    try:
        rows = conn.execute(
            "SELECT snapshot_id, result_json FROM snapshots "
            "WHERE city IS NULL AND is_preview = 0"
        ).fetchall()
        if not rows:
            return
        logger.info("Backfilling city/state_abbr for %d snapshots", len(rows))
        for row in rows:
            try:
                result = json.loads(row["result_json"])
            except (json.JSONDecodeError, TypeError):
                continue
            city, state_abbr = _extract_city_state(result)
            if city or state_abbr:
                conn.execute(
                    "UPDATE snapshots SET city = ?, state_abbr = ? WHERE snapshot_id = ?",
                    (city, state_abbr, row["snapshot_id"]),
                )
        conn.commit()
        logger.info("Backfill complete")
    finally:
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
    is_preview = 1 if kwargs.get("is_preview") else 0
    snapshot_id = generate_snapshot_id()
    now = datetime.now(timezone.utc).isoformat()
    city, state_abbr = _extract_city_state(result_dict)

    conn = _get_db()
    conn.execute(
        """INSERT INTO snapshots
           (snapshot_id, address_input, address_norm, place_id, evaluated_at, created_at,
            verdict, final_score, passed_tier1, result_json, email, user_id, is_preview,
            city, state_abbr)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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
            is_preview,
            city,
            state_abbr,
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


def unlock_snapshot(snapshot_id: str) -> bool:
    """Unlock a preview snapshot (set is_preview=0).

    Returns True if the snapshot was actually unlocked (was a preview),
    False if it was already unlocked or doesn't exist.
    """
    conn = _get_db()
    try:
        cursor = conn.execute(
            "UPDATE snapshots SET is_preview = 0 WHERE snapshot_id = ? AND is_preview = 1",
            (snapshot_id,),
        )
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


def get_og_image(snapshot_id: str) -> Optional[bytes]:
    """Return the OG image bytes for a snapshot, or None."""
    conn = _get_db()
    try:
        row = conn.execute(
            "SELECT og_image FROM snapshots WHERE snapshot_id = ?",
            (snapshot_id,),
        ).fetchone()
        if row and row["og_image"]:
            return bytes(row["og_image"])
        return None
    finally:
        conn.close()


def save_og_image(snapshot_id: str, image_data: bytes) -> None:
    """Save an OG image for a snapshot."""
    conn = _get_db()
    try:
        conn.execute(
            "UPDATE snapshots SET og_image = ? WHERE snapshot_id = ?",
            (image_data, snapshot_id),
        )
        conn.commit()
    finally:
        conn.close()


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


def save_feedback(snapshot_id, feedback_type, response_json,
                  address_norm=None, visitor_id=None):
    """Save a user feedback submission to the feedback table."""
    now = datetime.now(timezone.utc).isoformat()
    for attempt in range(3):
        try:
            conn = _get_db()
            conn.execute(
                """INSERT INTO feedback
                   (snapshot_id, feedback_type, response_json,
                    address_norm, visitor_id, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (snapshot_id, feedback_type, response_json,
                 address_norm, visitor_id, now),
            )
            conn.commit()
            return
        except sqlite3.OperationalError as e:
            if ("locked" in str(e).lower() or "busy" in str(e).lower()) and attempt < 2:
                time.sleep(0.1 * (attempt + 1))
            else:
                raise
        finally:
            conn.close()


# ---------------------------------------------------------------------------
# Inline feedback (NES-362)
# ---------------------------------------------------------------------------

def has_inline_feedback(snapshot_id: str, user_id=None, visitor_id=None) -> bool:
    """Check if inline feedback already exists for this snapshot + identity."""
    if not user_id and not visitor_id:
        return False
    conn = _get_db()
    try:
        if user_id:
            row = conn.execute(
                "SELECT 1 FROM feedback WHERE snapshot_id = ? AND user_id = ?"
                " AND feedback_type = 'inline_reaction'",
                (snapshot_id, user_id),
            ).fetchone()
            if row:
                return True
        if visitor_id:
            row = conn.execute(
                "SELECT 1 FROM feedback WHERE snapshot_id = ? AND visitor_id = ?"
                " AND feedback_type = 'inline_reaction'",
                (snapshot_id, visitor_id),
            ).fetchone()
            if row:
                return True
        return False
    finally:
        conn.close()


def save_inline_feedback(snapshot_id: str, user_id, visitor_id,
                         feedback_type: str, told_something_new: int,
                         free_text=None) -> bool:
    """Save inline feedback. Returns True on success, False if duplicate."""
    if has_inline_feedback(snapshot_id, user_id, visitor_id):
        return False

    now = datetime.now(timezone.utc).isoformat()
    last_err = None
    for attempt in range(3):
        try:
            conn = _get_db()
            try:
                conn.execute(
                    """INSERT INTO feedback
                       (snapshot_id, user_id, visitor_id, feedback_type,
                        told_something_new, free_text, response_json, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, '{}', ?)""",
                    (snapshot_id, user_id, visitor_id, feedback_type,
                     told_something_new, free_text, now),
                )
                conn.commit()
                return True
            finally:
                conn.close()
        except sqlite3.OperationalError as e:
            last_err = e
            if "locked" in str(e) or "busy" in str(e):
                logger.warning("save_inline_feedback retry %d/3: %s",
                               attempt + 1, e)
                time.sleep(0.5 * (attempt + 1))
                continue
            raise
    raise last_err


# ---------------------------------------------------------------------------
# Feedback digest (NES-387)
# ---------------------------------------------------------------------------

def get_feedback_digest():
    """Aggregate feedback data for the builder dashboard and CLI.

    Returns a dict with:
      - total_inline: count of inline_reaction submissions
      - total_survey: count of detailed_survey submissions
      - told_new_yes / told_new_no: inline reaction counts
      - wtp: dict of willingness-to-pay response counts
      - dim_accuracy: list of {name, avg, count} sorted by avg ascending
      - overall_accuracy_avg: float or None
      - recent_comments: list of {text, snapshot_id, created_at} (last 10)
    """
    conn = _get_db()
    try:
        # Inline reaction counts
        row = conn.execute(
            "SELECT COUNT(*) FROM feedback WHERE feedback_type = 'inline_reaction'"
        ).fetchone()
        total_inline = row[0] if row else 0

        row = conn.execute(
            "SELECT"
            " SUM(CASE WHEN told_something_new = 1 THEN 1 ELSE 0 END),"
            " SUM(CASE WHEN told_something_new = 0 THEN 1 ELSE 0 END)"
            " FROM feedback WHERE feedback_type = 'inline_reaction'"
        ).fetchone()
        told_new_yes = (row[0] or 0) if row else 0
        told_new_no = (row[1] or 0) if row else 0

        # Survey counts
        row = conn.execute(
            "SELECT COUNT(*) FROM feedback WHERE feedback_type = 'detailed_survey'"
        ).fetchone()
        total_survey = row[0] if row else 0

        # WTP + dimension accuracy + overall accuracy from survey response_json
        wtp_counts = {}
        dim_totals = {}  # {name: [sum, count]}
        overall_scores = []

        surveys = conn.execute(
            "SELECT response_json FROM feedback"
            " WHERE feedback_type = 'detailed_survey'"
        ).fetchall()
        for (rj,) in surveys:
            try:
                data = json.loads(rj)
            except (json.JSONDecodeError, TypeError):
                continue
            # WTP
            wp = data.get("wtp_would_pay")
            if wp:
                wtp_counts[wp] = wtp_counts.get(wp, 0) + 1
            # Overall accuracy
            oa = data.get("overall_accuracy")
            if oa is not None:
                try:
                    overall_scores.append(float(oa))
                except (ValueError, TypeError):
                    pass
            # Dimension accuracy
            dims = data.get("dimensions", {})
            for dim_name, dim_data in dims.items():
                acc = dim_data.get("accuracy") if isinstance(dim_data, dict) else None
                if acc is not None:
                    try:
                        acc_f = float(acc)
                    except (ValueError, TypeError):
                        continue
                    if dim_name not in dim_totals:
                        dim_totals[dim_name] = [0.0, 0]
                    dim_totals[dim_name][0] += acc_f
                    dim_totals[dim_name][1] += 1

        dim_accuracy = sorted(
            [
                {"name": name, "avg": round(s / c, 1), "count": c}
                for name, (s, c) in dim_totals.items()
                if c > 0
            ],
            key=lambda d: d["avg"],
        )

        overall_accuracy_avg = (
            round(sum(overall_scores) / len(overall_scores), 1)
            if overall_scores
            else None
        )

        # Recent free-text comments (inline + survey)
        comments = []
        rows = conn.execute(
            "SELECT free_text, snapshot_id, created_at FROM feedback"
            " WHERE free_text IS NOT NULL AND free_text != ''"
            " ORDER BY created_at DESC LIMIT 10"
        ).fetchall()
        for text, sid, created in rows:
            comments.append({
                "text": text,
                "snapshot_id": sid,
                "created_at": created,
            })

        return {
            "total_inline": total_inline,
            "total_survey": total_survey,
            "told_new_yes": told_new_yes,
            "told_new_no": told_new_no,
            "wtp": wtp_counts,
            "dim_accuracy": dim_accuracy,
            "overall_accuracy_avg": overall_accuracy_avg,
            "recent_comments": comments,
        }
    finally:
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


def get_sitemap_snapshots(limit=2000):
    """Return lightweight snapshot metadata for sitemap.xml generation.

    Only returns snapshots that passed tier1 (have scores) since those
    are the meaningful marketing surfaces. Skips the heavy result_json
    column entirely.
    """
    conn = _get_db()
    try:
        rows = conn.execute(
            """SELECT snapshot_id, address_norm, created_at
               FROM snapshots
               WHERE passed_tier1 = 1
               ORDER BY created_at DESC
               LIMIT ?""",
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


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
    city, state_abbr = _extract_city_state(result_dict)

    conn = _get_db()
    try:
        if existing_snapshot_id:
            conn.execute(
                """UPDATE snapshots
                   SET address_input = ?, address_norm = ?, place_id = ?,
                       evaluated_at = ?, created_at = ?,
                       verdict = ?, final_score = ?, passed_tier1 = ?, result_json = ?,
                       email = COALESCE(?, email),
                       city = ?, state_abbr = ?
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
                    city,
                    state_abbr,
                    existing_snapshot_id,
                ),
            )
            conn.commit()
            return existing_snapshot_id

        snapshot_id = generate_snapshot_id()
        conn.execute(
            """INSERT INTO snapshots
               (snapshot_id, address_input, address_norm, place_id, evaluated_at, created_at,
                verdict, final_score, passed_tier1, result_json, email, user_id,
                city, state_abbr)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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
                city,
                state_abbr,
            ),
        )
        conn.commit()
        return snapshot_id
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# City page queries (NES-352)
# ---------------------------------------------------------------------------


def get_city_snapshots(state_abbr: str, city_name: str) -> list:
    """Return lightweight snapshot metadata for a city. No result_json parsing."""
    conn = _get_db()
    try:
        rows = conn.execute(
            """SELECT snapshot_id, address_norm, final_score, passed_tier1,
                      evaluated_at, city, state_abbr
               FROM snapshots
               WHERE state_abbr = ? AND city = ? AND is_preview = 0
               ORDER BY evaluated_at DESC""",
            (state_abbr, city_name),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_city_stats(state_abbr: str, city_name: str) -> dict:
    """Return aggregate stats for a city."""
    conn = _get_db()
    try:
        row = conn.execute(
            """SELECT COUNT(*) as eval_count,
                      ROUND(AVG(final_score)) as avg_score,
                      SUM(CASE WHEN passed_tier1 = 1 THEN 1 ELSE 0 END) as health_pass_count
               FROM snapshots
               WHERE state_abbr = ? AND city = ? AND is_preview = 0""",
            (state_abbr, city_name),
        ).fetchone()
        d = dict(row)
        d["avg_score"] = int(d["avg_score"]) if d["avg_score"] is not None else 0
        return d
    finally:
        conn.close()


def get_cities_with_snapshots(min_count: int = 3) -> list:
    """Return cities meeting the minimum snapshot threshold."""
    conn = _get_db()
    try:
        rows = conn.execute(
            """SELECT state_abbr, city, COUNT(*) as snapshot_count
               FROM snapshots
               WHERE city IS NOT NULL AND state_abbr IS NOT NULL AND is_preview = 0
               GROUP BY state_abbr, city
               HAVING COUNT(*) >= ?
               ORDER BY state_abbr, city""",
            (min_count,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_city_name_by_slug(state_abbr: str, city_slug: str, min_count: int = 3):
    """Resolve a URL slug to canonical city name for a given state.
    Returns the city name if found and meets threshold, else None.
    """
    import re

    def _slugify(name):
        return re.sub(r'[^a-z0-9]+', '-', name.lower()).strip('-')

    conn = _get_db()
    try:
        rows = conn.execute(
            """SELECT city, COUNT(*) as cnt
               FROM snapshots
               WHERE state_abbr = ? AND city IS NOT NULL AND is_preview = 0
               GROUP BY city
               HAVING cnt >= ?""",
            (state_abbr, min_count),
        ).fetchall()
        for row in rows:
            if _slugify(row["city"]) == city_slug:
                return row["city"]
        return None
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Evaluation job queue
# ---------------------------------------------------------------------------

def create_job(address: str, visitor_id: str = None, request_id: str = None,
               place_id: str = None, email_hash: str = None,
               email_raw: str = None, user_id: str = None) -> str:
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
                        email_hash, email_raw, user_id, created_at)
                       VALUES (?, ?, 'queued', ?, ?, ?, ?, ?, ?, ?)""",
                    (job_id, address, visitor_id, request_id, place_id,
                     email_hash, email_raw, user_id, now),
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
        "UPDATE evaluation_jobs SET current_stage = ? WHERE job_id = ? AND status = 'running'",
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
           SET status = 'done', snapshot_id = ?, completed_at = ?,
               current_stage = NULL
           WHERE job_id = ?""",
        (snapshot_id, now, job_id),
    )
    conn.commit()
    conn.close()


def fail_job(job_id: str, error: str) -> None:
    """Mark a job as failed with an error message."""
    now = datetime.now(timezone.utc).isoformat()
    error = error[:2000] if error else error
    conn = _get_db()
    conn.execute(
        """UPDATE evaluation_jobs
           SET status = 'failed', error = ?, completed_at = ?
           WHERE job_id = ?""",
        (error, now, job_id),
    )
    conn.commit()
    conn.close()


def cancel_queued_job(job_id: str, reason: str) -> bool:
    """Cancel a job that is still queued. Returns True if cancelled, False if not queued."""
    now = datetime.now(timezone.utc).isoformat()
    conn = _get_db()
    cur = conn.execute(
        """UPDATE evaluation_jobs
           SET status = 'failed', error = ?, completed_at = ?
           WHERE job_id = ? AND status = 'queued'""",
        (reason, now, job_id),
    )
    changed = cur.rowcount > 0
    conn.commit()
    conn.close()
    return changed


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
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (payment_id, stripe_session_id, visitor_id, address, snapshot_id, PAYMENT_PENDING, now),
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
               SET status = ?, redeemed_at = ?, job_id = ?
               WHERE id = ? AND status IN (?, ?)""",
            (PAYMENT_REDEEMED, now, job_id, payment_id, PAYMENT_PAID, PAYMENT_FAILED_REISSUED),
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


_FREE_TIER_MAX_EVALS = 10
_FREE_TIER_WINDOW_DAYS = 30


def check_free_tier_available(email_hash: str) -> bool:
    """Return True if the email has free evals remaining in the current window."""
    conn = _get_db()
    try:
        row = conn.execute(
            "SELECT eval_count, window_start FROM free_tier_usage "
            "WHERE email_hash = ?",
            (email_hash,),
        ).fetchone()
        if row is None:
            return True
        eval_count = row[0] or 0
        window_start = row[1]
        if window_start:
            try:
                ws = datetime.fromisoformat(window_start)
                if ws.tzinfo is None:
                    ws = ws.replace(tzinfo=timezone.utc)
                if datetime.now(timezone.utc) - ws > timedelta(days=_FREE_TIER_WINDOW_DAYS):
                    return True
            except (ValueError, TypeError):
                return True
        return eval_count < _FREE_TIER_MAX_EVALS
    finally:
        conn.close()


def record_free_tier_usage(email_hash: str, email_raw: str) -> None:
    """Atomically increment the free tier counter for this email."""
    conn = _get_db()
    try:
        conn.execute(
            "INSERT INTO free_tier_usage (email_hash, email_raw, created_at, "
            "eval_count, window_start) "
            "VALUES (?, ?, datetime('now'), 1, datetime('now')) "
            "ON CONFLICT(email_hash) DO UPDATE SET "
            "eval_count = CASE "
            "  WHEN window_start < datetime('now', '-30 days') THEN 1 "
            "  ELSE eval_count + 1 "
            "END, "
            "window_start = CASE "
            "  WHEN window_start < datetime('now', '-30 days') THEN datetime('now') "
            "  ELSE window_start "
            "END",
            (email_hash, email_raw),
        )
        conn.commit()
    finally:
        conn.close()


def decrement_free_tier_usage(email_hash: str) -> None:
    """Return one free tier credit (e.g., when a job fails)."""
    conn = _get_db()
    try:
        conn.execute(
            "UPDATE free_tier_usage SET eval_count = MAX(0, eval_count - 1) "
            "WHERE email_hash = ?",
            (email_hash,),
        )
        conn.commit()
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
# Canopy cache (90-day TTL)
# ---------------------------------------------------------------------------

_CANOPY_CACHE_TTL_DAYS = 90


def get_canopy_cache(cache_key: str) -> Optional[str]:
    """Look up cached NLCD canopy cover data by coordinate key.

    Returns the raw JSON string if found and younger than TTL, else None.
    Cache errors are swallowed so they never break an evaluation.
    """
    try:
        conn = _get_db()
        try:
            row = conn.execute(
                """SELECT data_json, created_at FROM canopy_cache
                   WHERE cache_key = ?""",
                (cache_key,),
            ).fetchone()
            if not row:
                return None
            if not _check_cache_ttl(row["created_at"], _CANOPY_CACHE_TTL_DAYS):
                return None
            return row["data_json"]
        finally:
            conn.close()
    except Exception:
        logger.warning("Canopy cache lookup failed", exc_info=True)
        return None


def set_canopy_cache(cache_key: str, data_json: str) -> None:
    """Store NLCD canopy cover data in the persistent cache.

    Cache errors are swallowed so they never break an evaluation.
    """
    try:
        conn = _get_db()
        try:
            now = datetime.now(timezone.utc).isoformat()
            conn.execute(
                """INSERT OR REPLACE INTO canopy_cache (cache_key, data_json, created_at)
                   VALUES (?, ?, ?)""",
                (cache_key, data_json, now),
            )
            conn.commit()
        finally:
            conn.close()
    except Exception:
        logger.warning("Canopy cache write failed", exc_info=True)


# ---------------------------------------------------------------------------
# Evaluation coverage (NES-291)
# ---------------------------------------------------------------------------


def save_evaluation_coverage(data: dict) -> None:
    """Record cache hit/miss analytics for a single evaluation.

    Swallows all errors — never impacts evaluation.
    """
    try:
        conn = _get_db()
        try:
            conn.execute(
                """
                INSERT INTO evaluation_coverage
                    (evaluation_id, address, latitude, longitude,
                     evaluated_at, categories_from_cache,
                     categories_from_api, api_calls_saved,
                     api_calls_made, total_duration_seconds,
                     walk_times_from_cache, walk_times_from_api)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    data.get("evaluation_id"),
                    data.get("address"),
                    data.get("latitude"),
                    data.get("longitude"),
                    data.get("evaluated_at"),
                    json.dumps(data.get("categories_from_cache", [])),
                    json.dumps(data.get("categories_from_api", [])),
                    data.get("api_calls_saved", 0),
                    data.get("api_calls_made", 0),
                    data.get("total_duration_seconds"),
                    data.get("walk_times_from_cache", 0),
                    data.get("walk_times_from_api", 0),
                ),
            )
            conn.commit()
        finally:
            conn.close()
    except Exception as e:
        logger.warning("Failed to save evaluation coverage: %s", e)


# ---------------------------------------------------------------------------
# State coverage requests (waitlist)
# ---------------------------------------------------------------------------


def save_state_request(email: str, state_code: str) -> bool:
    """Record a state coverage request. Returns True on success, False on duplicate."""
    now = datetime.now(timezone.utc).isoformat()
    conn = _get_db()
    try:
        conn.execute(
            """INSERT INTO state_requests (email, state_code, created_at)
               VALUES (?, ?, ?)""",
            (email.strip().lower(), state_code.upper(), now),
        )
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()


def get_state_request_counts() -> dict:
    """Return {state_code: count} for all state requests."""
    conn = _get_db()
    try:
        rows = conn.execute(
            "SELECT state_code, COUNT(*) as cnt FROM state_requests GROUP BY state_code"
        ).fetchall()
        return {row["state_code"]: row["cnt"] for row in rows}
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# State votes (anonymous demand signal)
# ---------------------------------------------------------------------------

# Valid 2-letter US state abbreviations (all 50 states)
_US_STATES = {
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA",
    "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD",
    "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ",
    "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC",
    "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY",
}


def record_state_vote(state: str) -> bool:
    """Record an anonymous state demand vote. Returns True on success.

    Validates that state is a valid 2-letter US state abbreviation.
    Returns False if the state code is invalid.
    """
    state = state.strip().upper()
    if state not in _US_STATES:
        return False
    now = datetime.now(timezone.utc).isoformat()
    conn = _get_db()
    try:
        conn.execute(
            "INSERT INTO state_votes (state, created_at) VALUES (?, ?)",
            (state, now),
        )
        conn.commit()
        return True
    finally:
        conn.close()


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
        try:
            conn.execute(
                """INSERT INTO users (id, email, name, picture_url, google_sub, created_at, last_login_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (user_id, email, name, picture_url, google_sub, now, now),
            )
            conn.commit()
        except sqlite3.IntegrityError:
            # Concurrent insert won — re-fetch the winner's row.
            conn.rollback()
            row = None
            if google_sub:
                row = conn.execute(
                    "SELECT * FROM users WHERE google_sub = ?", (google_sub,)
                ).fetchone()
            if not row:
                row = conn.execute(
                    "SELECT * FROM users WHERE email = ?", (email,)
                ).fetchone()
            if row:
                return dict(row), False
            raise  # Unexpected constraint — re-raise
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


def get_user_by_stripe_customer(stripe_customer_id: str) -> Optional[dict]:
    """Return user dict by Stripe customer ID, or None."""
    conn = _get_db()
    try:
        row = conn.execute(
            "SELECT * FROM users WHERE stripe_customer_id = ?",
            (stripe_customer_id,),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def update_user_stripe_customer(user_id: str, stripe_customer_id: str) -> None:
    """Set the Stripe customer ID on a user record."""
    conn = _get_db()
    try:
        conn.execute(
            "UPDATE users SET stripe_customer_id = ? WHERE id = ?",
            (stripe_customer_id, user_id),
        )
        conn.commit()
    finally:
        conn.close()


# --- Subscription functions (NES-327) ---

SUBSCRIPTION_ACTIVE = "active"
SUBSCRIPTION_CANCELED = "canceled"
SUBSCRIPTION_PAST_DUE = "past_due"
SUBSCRIPTION_EXPIRED = "expired"


def create_subscription(
    subscription_id: str,
    user_email: str,
    stripe_subscription_id: str,
    stripe_customer_id: str | None,
    period_start: str,
    period_end: str,
) -> None:
    """Create a new subscription record."""
    conn = _get_db()
    try:
        now = datetime.now(timezone.utc).isoformat()
        email_h = hash_email(user_email)
        conn.execute(
            "INSERT INTO subscriptions "
            "(id, user_email, email_hash, stripe_subscription_id, "
            "stripe_customer_id, status, period_start, period_end, "
            "created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (subscription_id, user_email, email_h,
             stripe_subscription_id, stripe_customer_id,
             SUBSCRIPTION_ACTIVE, period_start, period_end, now, now),
        )
        conn.commit()
    finally:
        conn.close()


def get_subscription_by_stripe_id(stripe_subscription_id: str) -> dict | None:
    """Look up a subscription by its Stripe subscription ID."""
    conn = _get_db()
    try:
        row = conn.execute(
            "SELECT * FROM subscriptions WHERE stripe_subscription_id = ?",
            (stripe_subscription_id,),
        ).fetchone()
        if row is None:
            return None
        return dict(row)
    finally:
        conn.close()


def update_subscription_status(
    stripe_subscription_id: str,
    status: str,
    period_start: str | None = None,
    period_end: str | None = None,
) -> None:
    """Update subscription status and optionally period dates."""
    conn = _get_db()
    try:
        now = datetime.now(timezone.utc).isoformat()
        if period_start and period_end:
            conn.execute(
                "UPDATE subscriptions SET status = ?, period_start = ?, period_end = ?, "
                "updated_at = ? WHERE stripe_subscription_id = ?",
                (status, period_start, period_end, now, stripe_subscription_id),
            )
        else:
            conn.execute(
                "UPDATE subscriptions SET status = ?, updated_at = ? "
                "WHERE stripe_subscription_id = ?",
                (status, now, stripe_subscription_id),
            )
        conn.commit()
    finally:
        conn.close()


def is_subscription_active(email: str = None, *, email_hash: str = None) -> bool:
    """Check if email has an active (or canceled-but-not-expired) subscription.

    Accepts either email (legacy) or email_hash for consistent indexing.
    """
    if not email and not email_hash:
        return False
    conn = _get_db()
    try:
        if email_hash:
            row = conn.execute(
                "SELECT 1 FROM subscriptions "
                "WHERE email_hash = ? AND status IN (?, ?, ?) "
                "AND period_end > datetime('now') LIMIT 1",
                (email_hash, SUBSCRIPTION_ACTIVE, SUBSCRIPTION_CANCELED,
                 SUBSCRIPTION_PAST_DUE),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT 1 FROM subscriptions "
                "WHERE user_email = ? AND status IN (?, ?, ?) "
                "AND period_end > datetime('now') LIMIT 1",
                (email, SUBSCRIPTION_ACTIVE, SUBSCRIPTION_CANCELED,
                 SUBSCRIPTION_PAST_DUE),
            ).fetchone()
        return row is not None
    finally:
        conn.close()


def get_active_subscription(email: str = None, *, email_hash: str = None) -> dict | None:
    """Return active subscription details for dashboard display, or None.

    Accepts either email (legacy) or email_hash for consistent indexing.
    """
    if not email and not email_hash:
        return None
    conn = _get_db()
    try:
        if email_hash:
            row = conn.execute(
                "SELECT * FROM subscriptions "
                "WHERE email_hash = ? AND status IN (?, ?, ?) "
                "AND period_end > datetime('now') "
                "ORDER BY period_end DESC LIMIT 1",
                (email_hash, SUBSCRIPTION_ACTIVE, SUBSCRIPTION_CANCELED,
                 SUBSCRIPTION_PAST_DUE),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT * FROM subscriptions "
                "WHERE user_email = ? AND status IN (?, ?, ?) "
                "AND period_end > datetime('now') "
                "ORDER BY period_end DESC LIMIT 1",
                (email, SUBSCRIPTION_ACTIVE, SUBSCRIPTION_CANCELED,
                 SUBSCRIPTION_PAST_DUE),
            ).fetchone()
        if row is None:
            return None
        return dict(row)
    finally:
        conn.close()


def update_payment_snapshot_id(snapshot_id: str, job_id: str) -> None:
    """Backfill snapshot_id on payments linked to this job."""
    conn = _get_db()
    try:
        conn.execute(
            "UPDATE payments SET snapshot_id = ? WHERE job_id = ? AND snapshot_id IS NULL",
            (snapshot_id, job_id),
        )
        conn.commit()
    finally:
        conn.close()


def update_payment_snapshot_id_direct(payment_id: str, snapshot_id: str) -> None:
    """Link a payment directly to a snapshot_id (unlock-existing-report flow)."""
    conn = _get_db()
    try:
        conn.execute(
            "UPDATE payments SET snapshot_id = ? WHERE id = ?",
            (snapshot_id, payment_id),
        )
        conn.commit()
    finally:
        conn.close()


