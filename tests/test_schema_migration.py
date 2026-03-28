"""NES-379: Verify init_db() succeeds against the oldest known production schema.

The 2026-03-23 outage was caused by init_db() running CREATE INDEX on a column
that didn't exist in the production database. CREATE TABLE IF NOT EXISTS is a
no-op on existing tables, so columns added to the code's CREATE TABLE after the
table was first created are invisible to production — unless there's a matching
ALTER TABLE migration.

This test creates a fixture DB with the original table schemas (before any ALTER
TABLE migrations), then runs init_db() against it and asserts no
OperationalError.

When a new CREATE INDEX is added without its ALTER TABLE migration, this test
fails.
"""

import os
import sqlite3
import tempfile


# ---------------------------------------------------------------------------
# Oldest known production schema — CREATE TABLE as they existed when the
# production DB was first created, BEFORE any ALTER TABLE migrations.
#
# To update: when a NEW table is added to init_db() via CREATE TABLE IF NOT
# EXISTS, copy it here verbatim. When a NEW column is added to an existing
# CREATE TABLE and a corresponding ALTER TABLE migration is added, do NOT
# update the table here — the whole point is that this fixture lacks those
# columns so the migration is exercised.
# ---------------------------------------------------------------------------

_OLDEST_SCHEMA = """
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
"""


def test_init_db_against_oldest_schema():
    """init_db() must succeed against the oldest known production schema.

    This catches the class of bug where a CREATE INDEX is added for a column
    that only exists in the code's CREATE TABLE (which is a no-op on existing
    tables) but has no ALTER TABLE migration.
    """
    import models

    # Create a temporary DB with the oldest schema
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)

    try:
        conn = sqlite3.connect(db_path)
        conn.executescript(_OLDEST_SCHEMA)
        conn.close()

        # Point models at our fixture DB
        original_db_path = models.DB_PATH
        models.DB_PATH = db_path

        try:
            # This is the line that would have caught the 2026-03-23 outage.
            # If init_db() tries to CREATE INDEX on a column that doesn't
            # exist and has no ALTER TABLE migration, it raises
            # OperationalError here.
            models.init_db()
        finally:
            models.DB_PATH = original_db_path

        # Verify all migration-added columns exist after init_db()
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row

        snap_cols = {row["name"] for row in conn.execute("PRAGMA table_info(snapshots)").fetchall()}
        for col in ("place_id", "evaluated_at", "email", "email_sent_at",
                     "user_id", "is_preview", "og_image", "city", "state_abbr"):
            assert col in snap_cols, f"snapshots.{col} missing after init_db() migration"

        job_cols = {row["name"] for row in conn.execute("PRAGMA table_info(evaluation_jobs)").fetchall()}
        for col in ("user_id", "snapshot_id"):
            assert col in job_cols, f"evaluation_jobs.{col} missing after init_db() migration"

        user_cols = {row["name"] for row in conn.execute("PRAGMA table_info(users)").fetchall()}
        assert "stripe_customer_id" in user_cols, "users.stripe_customer_id missing after init_db() migration"

        ft_cols = {row["name"] for row in conn.execute("PRAGMA table_info(free_tier_usage)").fetchall()}
        for col in ("eval_count", "window_start"):
            assert col in ft_cols, f"free_tier_usage.{col} missing after init_db() migration"

        sub_cols = {row["name"] for row in conn.execute("PRAGMA table_info(subscriptions)").fetchall()}
        assert "updated_at" in sub_cols, "subscriptions.updated_at missing after init_db() migration"

        conn.close()

    finally:
        if os.path.exists(db_path):
            os.unlink(db_path)
