#!/usr/bin/env python3
"""
Shared utilities for state education performance ingestion scripts.

All state education scripts share the same table schema, CSV column mapping,
and ingestion flow. This module centralises that logic so each per-state
script is a thin wrapper providing only its state-specific config.
"""

import csv
import logging
import os
import sqlite3
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

TABLE_NAME = "state_education_performance"


def safe_float(value):
    """Convert to float, treating empty strings and suppression symbols as None.

    State education data uses various suppression symbols for small populations
    or missing data (e.g., * for suppressed, N/A for not applicable).
    """
    if not value or value.strip() in ("", "*", "**", "N", "†", "s", "N/A", "-"):
        return None
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


def ensure_education_table(conn):
    """Create state_education_performance table if it doesn't exist.

    Safe to call from any per-state script — uses CREATE TABLE IF NOT EXISTS.
    """
    conn.execute(f"""
        CREATE TABLE IF NOT EXISTS {TABLE_NAME} (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            geoid TEXT UNIQUE NOT NULL,
            district_name TEXT,
            county TEXT,
            graduation_rate_pct REAL,
            ela_proficiency_pct REAL,
            math_proficiency_pct REAL,
            chronic_absenteeism_pct REAL,
            pupil_expenditure REAL,
            source_year TEXT,
            state TEXT
        )
    """)
    conn.execute(
        f"CREATE INDEX IF NOT EXISTS idx_{TABLE_NAME}_geoid ON {TABLE_NAME}(geoid)"
    )
    conn.commit()


def ingest_state_education(
    state_code,
    csv_path,
    source_url,
    registry_notes,
    registry_facility_type=None,
):
    """Load a state education performance CSV into spatial.db.

    This is the shared ingestion flow used by all per-state scripts.
    Idempotent: deletes existing rows for the state and re-inserts.

    Args:
        state_code: 2-letter state code (e.g., "NY", "NJ", "CT", "MI").
        csv_path: Absolute path to the curated CSV file.
        source_url: Source URL string for the dataset_registry entry.
        registry_notes: Notes string for the dataset_registry entry.
        registry_facility_type: Override facility_type for dataset_registry.
            Defaults to "state_education_performance_{state_code.lower()}".
    """
    from spatial_data import _connect, init_spatial_db

    if not os.path.exists(csv_path):
        logger.error("%s performance CSV not found at %s", state_code, csv_path)
        return

    facility_type = registry_facility_type or f"state_education_performance_{state_code.lower()}"

    init_spatial_db()
    conn = _connect()

    try:
        ensure_education_table(conn)

        # Delete existing rows for this state (idempotent — preserves other states)
        deleted = conn.execute(
            f"DELETE FROM {TABLE_NAME} WHERE state = ?", (state_code,)
        ).rowcount
        if deleted > 0:
            logger.info("Cleared %d existing %s rows", deleted, state_code)
        conn.commit()

        total = 0
        skipped = 0
        with open(csv_path, "r", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    conn.execute(
                        f"""INSERT INTO {TABLE_NAME}
                            (geoid, district_name, county, graduation_rate_pct,
                             ela_proficiency_pct, math_proficiency_pct,
                             chronic_absenteeism_pct, pupil_expenditure, source_year,
                             state)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (
                            row["geoid"],
                            row["district_name"],
                            row.get("county", ""),
                            safe_float(row.get("graduation_rate_pct")),
                            safe_float(row.get("ela_proficiency_pct")),
                            safe_float(row.get("math_proficiency_pct")),
                            safe_float(row.get("chronic_absenteeism_pct")),
                            safe_float(row.get("pupil_expenditure")),
                            row.get("source_year", ""),
                            state_code,
                        ),
                    )
                    total += 1
                except (ValueError, KeyError, sqlite3.IntegrityError) as e:
                    logger.warning("Skipping row %s: %s", row.get("geoid", "?"), e)
                    skipped += 1

        conn.execute(
            """INSERT OR REPLACE INTO dataset_registry
               (facility_type, source_url, ingested_at, record_count, notes)
               VALUES (?, ?, ?, ?, ?)""",
            (
                facility_type,
                source_url,
                datetime.now(timezone.utc).isoformat(),
                total,
                f"Source: {os.path.basename(csv_path)}; {registry_notes}",
            ),
        )
        conn.commit()
        logger.info(
            "%s performance data loaded: %d districts, %d skipped",
            state_code, total, skipped,
        )

    finally:
        conn.close()


def verify_state_education(state_code, sample_query=None):
    """Quick verification: print sample rows and count for a state.

    Args:
        state_code: 2-letter state code.
        sample_query: Optional WHERE clause override for sample lookup.
            Defaults to "state = '{state_code}' ORDER BY district_name LIMIT 5".
    """
    from spatial_data import _spatial_db_path

    db_path = _spatial_db_path()
    if not os.path.exists(db_path):
        logger.error("Spatial DB not found")
        return

    conn = sqlite3.connect(db_path)
    try:
        if sample_query:
            cursor = conn.execute(
                f"SELECT * FROM {TABLE_NAME} WHERE {sample_query}"
            )
        else:
            cursor = conn.execute(
                f"SELECT * FROM {TABLE_NAME} WHERE state = ? ORDER BY district_name LIMIT 5",
                (state_code,),
            )
        cols = [d[0] for d in cursor.description]
        rows = cursor.fetchall()
        if rows:
            for row in rows:
                data = dict(zip(cols, row))
                logger.info(
                    "  %s (GEOID %s): grad=%s, ela=%s, math=%s",
                    data.get("district_name"), data.get("geoid"),
                    data.get("graduation_rate_pct"),
                    data.get("ela_proficiency_pct"),
                    data.get("math_proficiency_pct"),
                )
        else:
            logger.warning("No %s data found in %s", state_code, TABLE_NAME)

        count = conn.execute(
            f"SELECT COUNT(*) FROM {TABLE_NAME} WHERE state = ?", (state_code,)
        ).fetchone()[0]
        logger.info("Total %s districts: %d", state_code, count)
    finally:
        conn.close()
