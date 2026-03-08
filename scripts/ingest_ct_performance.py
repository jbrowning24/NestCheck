#!/usr/bin/env python3
"""
Load CT school district performance data into the NestCheck spatial database.

Data source: Curated CSV derived from CT EdSight (edsight.ct.gov) and
CTData.org data. CT publishes education data across multiple portals;
this script loads a pre-processed CSV with key metrics per district.

GEOIDs follow the NCES LEAID format (state FIPS 09 + 5-digit district code),
which matches Census TIGER unified school district boundaries.

Idempotent: deletes existing CT rows and re-inserts on each run.
Does NOT drop or recreate the table — preserves data from other states.

Usage:
    python scripts/ingest_ct_performance.py
    python scripts/ingest_ct_performance.py --verify
"""

import argparse
import csv
import logging
import os
import sqlite3
import sys
from datetime import datetime, timezone

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from spatial_data import _spatial_db_path, _connect, init_spatial_db

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

CT_CSV_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data", "ct_district_performance.csv",
)

TABLE_NAME = "state_education_performance"


def _ensure_table(conn):
    """Create state_education_performance table if it doesn't exist.

    This allows the CT script to run independently of the NYSED script.
    If the table already exists (created by ingest_nysed.py), this is a no-op.
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


def _safe_float(value):
    """Convert to float, treating empty strings and suppression symbols as None.

    CT suppresses data for populations < 20 students. Symbols include *, **, N/A.
    """
    if not value or value.strip() in ("", "*", "**", "N", "†", "s", "N/A", "-"):
        return None
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


def ingest(csv_path: str = "", **kwargs):
    """Load CT performance CSV into spatial.db.

    Args:
        csv_path: Override path to CSV file (default: data/ct_district_performance.csv).
    """
    csv_file = csv_path or CT_CSV_PATH
    if not os.path.exists(csv_file):
        logger.error("CT performance CSV not found at %s", csv_file)
        return

    init_spatial_db()
    conn = _connect()

    try:
        _ensure_table(conn)

        # Delete existing CT rows (idempotent — preserves NY/NJ data)
        deleted = conn.execute(
            f"DELETE FROM {TABLE_NAME} WHERE state = 'CT'"
        ).rowcount
        if deleted > 0:
            logger.info("Cleared %d existing CT rows", deleted)
        conn.commit()

        total = 0
        skipped = 0
        with open(csv_file, "r", newline="") as f:
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
                            _safe_float(row.get("graduation_rate_pct")),
                            _safe_float(row.get("ela_proficiency_pct")),
                            _safe_float(row.get("math_proficiency_pct")),
                            _safe_float(row.get("chronic_absenteeism_pct")),
                            _safe_float(row.get("pupil_expenditure")),
                            row.get("source_year", ""),
                            "CT",
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
                "state_education_performance_ct",
                "edsight.ct.gov / data.ctdata.org (curated CSV)",
                datetime.now(timezone.utc).isoformat(),
                total,
                f"Source: {os.path.basename(csv_file)}; "
                "MANUAL REFRESH — CT publishes education data across EdSight "
                "(edsight.ct.gov) and CTData.org. Download district-level "
                "graduation, SBAC, chronic absenteeism, and expenditure data, "
                "then update data/ct_district_performance.csv.",
            ),
        )
        conn.commit()
        logger.info("CT performance data loaded: %d districts, %d skipped", total, skipped)

    finally:
        conn.close()


def verify():
    """Quick verification: look up Hartford performance data."""
    db_path = _spatial_db_path()
    if not os.path.exists(db_path):
        logger.error("Spatial DB not found")
        return

    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.execute(
            f"SELECT * FROM {TABLE_NAME} WHERE state = 'CT' ORDER BY district_name LIMIT 5"
        )
        cols = [d[0] for d in cursor.description]
        rows = cursor.fetchall()
        if rows:
            for row in rows:
                data = dict(zip(cols, row))
                logger.info("  %s (GEOID %s): grad=%s, ela=%s, math=%s",
                            data.get("district_name"), data.get("geoid"),
                            data.get("graduation_rate_pct"), data.get("ela_proficiency_pct"),
                            data.get("math_proficiency_pct"))
        else:
            logger.warning("No CT data found in %s", TABLE_NAME)

        # Count
        count = conn.execute(
            f"SELECT COUNT(*) FROM {TABLE_NAME} WHERE state = 'CT'"
        ).fetchone()[0]
        logger.info("Total CT districts: %d", count)
    finally:
        conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Load CT performance data")
    parser.add_argument(
        "--csv", type=str, default="",
        help="Override CSV file path.",
    )
    parser.add_argument(
        "--verify", action="store_true",
        help="Run verification after loading.",
    )
    args = parser.parse_args()

    ingest(csv_path=args.csv)
    if args.verify:
        verify()
