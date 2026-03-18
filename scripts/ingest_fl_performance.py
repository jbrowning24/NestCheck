#!/usr/bin/env python3
"""
Load FL school district performance data into the NestCheck spatial database.

Data source: Curated CSV derived from Florida Department of Education (FLDOE).
Graduation rates, FSA proficiency (ELA + math), chronic absenteeism, and
per-pupil spending sourced from FLDOE publications.

GEOIDs follow the NCES LEAID format (state FIPS 12 + 5-digit district code),
which matches Census TIGER unified school district boundaries.

Florida uses a county-based school district system (~67 districts).

Idempotent: deletes existing FL rows and re-inserts on each run.
Does NOT drop or recreate the table — preserves data from other states.

CSV needs to be populated from FLDOE:
https://edudata.fldoe.org

Usage:
    python scripts/ingest_fl_performance.py
    python scripts/ingest_fl_performance.py --verify
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

FL_CSV_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data", "fl_district_performance.csv",
)


def ingest(csv_path: str = "", **kwargs):
    """Load FL performance CSV into spatial.db."""
    ingest_state_education(
        state_code="FL",
        csv_path=csv_path or FL_CSV_PATH,
        source_url="edudata.fldoe.org (FLDOE, curated CSV)",
        registry_notes=(
            "MANUAL REFRESH — FLDOE publishes district-level data at "
            "edudata.fldoe.org as downloadable reports. FSA proficiency, "
            "graduation rates, chronic absenteeism, and per-pupil "
            "expenditure. Update data/fl_district_performance.csv "
            "annually after FLDOE releases new data (~fall)."
        ),
    )


def verify():
    """Quick verification: look up FL performance data."""
    verify_state_education("FL")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Load FL performance data")
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
