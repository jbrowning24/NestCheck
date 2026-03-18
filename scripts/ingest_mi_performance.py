#!/usr/bin/env python3
"""
Load MI school district performance data into the NestCheck spatial database.

Data source: Curated CSV derived from MI School Data (mischooldata.org),
published by the Center for Educational Performance and Information (CEPI).
Graduation rates, M-STEP proficiency (ELA + math), and per-pupil expenditure
sourced from EdFacts federal data files; chronic absenteeism from CEPI when
available.

GEOIDs follow the NCES LEAID format (state FIPS 26 + 5-digit district code),
which matches Census TIGER unified school district boundaries.

Idempotent: deletes existing MI rows and re-inserts on each run.
Does NOT drop or recreate the table — preserves data from other states.

Usage:
    python scripts/ingest_mi_performance.py
    python scripts/ingest_mi_performance.py --verify
"""

import argparse
import logging
import os
import sys

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.ingest_utils import ingest_state_education, verify_state_education

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)

MI_CSV_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data", "mi_district_performance.csv",
)


def ingest(csv_path: str = "", **kwargs):
    """Load MI performance CSV into spatial.db."""
    ingest_state_education(
        state_code="MI",
        csv_path=csv_path or MI_CSV_PATH,
        source_url="mischooldata.org (CEPI, curated CSV)",
        registry_notes=(
            "MANUAL REFRESH — CEPI publishes district-level data at "
            "mischooldata.org as downloadable reports. Graduation rates "
            "and assessment proficiency also available via EdFacts federal "
            "data files. Update data/mi_district_performance.csv annually "
            "after CEPI releases new data (~fall)."
        ),
    )


def verify():
    """Quick verification: look up MI performance data."""
    verify_state_education("MI")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Load MI performance data")
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
