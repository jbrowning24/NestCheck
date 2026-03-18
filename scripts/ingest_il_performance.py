#!/usr/bin/env python3
"""
Load IL school district performance data into the NestCheck spatial database.

Data source: Curated CSV derived from Illinois State Board of Education (ISBE)
Illinois Report Card. Graduation rates, IAR proficiency (ELA + math), chronic
absenteeism, and per-pupil spending sourced from ISBE publications.

GEOIDs follow the NCES LEAID format (state FIPS 17 + 5-digit district code),
which matches Census TIGER unified school district boundaries.

Idempotent: deletes existing IL rows and re-inserts on each run.
Does NOT drop or recreate the table — preserves data from other states.

CSV needs to be populated from ISBE Illinois Report Card:
https://www.isbe.net/ilreportcarddata

Usage:
    python scripts/ingest_il_performance.py
    python scripts/ingest_il_performance.py --verify
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

IL_CSV_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data", "il_district_performance.csv",
)


def ingest(csv_path: str = "", **kwargs):
    """Load IL performance CSV into spatial.db."""
    ingest_state_education(
        state_code="IL",
        csv_path=csv_path or IL_CSV_PATH,
        source_url="isbe.net (ISBE Illinois Report Card, curated CSV)",
        registry_notes=(
            "MANUAL REFRESH — ISBE publishes district-level data at "
            "isbe.net/ilreportcarddata as downloadable reports. IAR "
            "proficiency, graduation rates, chronic absenteeism, and "
            "per-pupil expenditure. Update data/il_district_performance.csv "
            "annually after ISBE releases new data (~fall)."
        ),
    )


def verify():
    """Quick verification: look up IL performance data."""
    verify_state_education("IL")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Load IL performance data")
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
