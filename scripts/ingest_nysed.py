#!/usr/bin/env python3
"""
Load NY school district performance data into the NestCheck spatial database.

Data source: Curated CSV at data/nysed_district_performance.csv, covering all
691 regular school districts in New York State. Built from three sources:

1. NCES CCD Directory (2022-23): District names, GEOIDs, counties
   - GEOIDs match Census TIGER unified school district boundaries
   - Urban Institute Education Data API (educationdata.urban.org)

2. EDFacts Graduation Rates (2019): 4-year adjusted cohort graduation rates
   - Federal data via Urban Institute API; most recent available year

3. CCD Finance (2020): Per-pupil expenditure (exp_current_elsec_total / enrollment)

4. NYSED Report Card (2023-24): ELA/Math proficiency, chronic absenteeism
   - Currently available for ~40 Westchester County districts only
   - Full statewide data requires NYSED Access DB extraction (see below)

The CSV maps TIGER GEOID → performance metrics, enabling joins with
the school district polygon table (facilities_school_districts).

Idempotent: deletes existing NY rows and re-inserts on each run.
Does NOT drop or recreate the table — preserves data from other states.

Rebuilding the statewide CSV:
    python scripts/build_nysed_statewide_csv.py

Expanding NYSED-specific data (ELA, Math, absenteeism) statewide:
    NYSED publishes full data as Access .mdb databases:
    - Graduation rates: https://data.nysed.gov/files/gradrate/24-25/gradrate.zip
    - Report Card (ELA/Math): https://data.nysed.gov/files/essa/24-25/SRC2025.zip
    To extract:
    1. Install mdbtools: apt install mdbtools
    2. List tables: mdb-tables <file>.mdb
    3. Export: mdb-export <file>.mdb <table> > output.csv
    4. Map NYSED BEDS codes to TIGER GEOIDs (NCES LEAID = GEOID)
    5. Merge into data/nysed_district_performance.csv

Note: NYC DOE (GEOID 3620580) exists in TIGER as a unified district but
is agency_type=3 (supervisory union) in CCD, not type 1 (regular). NYC's
32 geographic sub-districts are type 2. The CSV excludes NYC since it
doesn't have district-level metrics comparable to other districts.

Usage:
    python scripts/ingest_nysed.py
    python scripts/ingest_nysed.py --verify
"""

import argparse
import csv
import json
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

NYSED_CSV_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data", "nysed_district_performance.csv",
)

TABLE_NAME = "state_education_performance"


def ingest(csv_path: str = "", **kwargs):
    """Load NYSED performance CSV into spatial.db.

    Args:
        csv_path: Override path to CSV file (default: data/nysed_district_performance.csv).
    """
    csv_file = csv_path or NYSED_CSV_PATH
    if not os.path.exists(csv_file):
        logger.error("NYSED CSV not found at %s", csv_file)
        return

    init_spatial_db()
    conn = _connect()

    try:
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
        conn.execute(f"CREATE INDEX IF NOT EXISTS idx_{TABLE_NAME}_geoid ON {TABLE_NAME}(geoid)")

        # Delete existing NY rows (idempotent — preserves CT/NJ data)
        deleted = conn.execute(
            f"DELETE FROM {TABLE_NAME} WHERE state = 'NY'"
        ).rowcount
        if deleted > 0:
            logger.info("Cleared %d existing NY rows", deleted)
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
                            row["county"],
                            float(row["graduation_rate_pct"]) if row.get("graduation_rate_pct") else None,
                            float(row["ela_proficiency_pct"]) if row.get("ela_proficiency_pct") else None,
                            float(row["math_proficiency_pct"]) if row.get("math_proficiency_pct") else None,
                            float(row["chronic_absenteeism_pct"]) if row.get("chronic_absenteeism_pct") else None,
                            float(row["pupil_expenditure"]) if row.get("pupil_expenditure") else None,
                            row.get("source_year", ""),
                            "NY",
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
                "state_education_performance",
                "data.nysed.gov (curated CSV)",
                datetime.now(timezone.utc).isoformat(),
                total,
                f"Source: {os.path.basename(csv_file)}; "
                "MANUAL REFRESH — NYSED publishes bulk data as Access DBs "
                "(data.nysed.gov/downloads.php), no stable API. "
                "Update CSV annually after Report Card release (~Dec).",
            ),
        )
        conn.commit()
        logger.info("NYSED performance data loaded: %d districts", total)

    finally:
        conn.close()


def verify():
    """Quick verification: look up White Plains performance data."""
    db_path = _spatial_db_path()
    if not os.path.exists(db_path):
        logger.error("Spatial DB not found")
        return

    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.execute(
            f"SELECT * FROM {TABLE_NAME} WHERE district_name LIKE '%White Plains%'"
        )
        row = cursor.fetchone()
        if row:
            cols = [d[0] for d in cursor.description]
            data = dict(zip(cols, row))
            logger.info("White Plains: %s", json.dumps(data, indent=2))
        else:
            logger.warning("No data found for White Plains")
    finally:
        conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Load NYSED performance data")
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
