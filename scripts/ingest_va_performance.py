#!/usr/bin/env python3
"""
Load VA school district performance data into the NestCheck spatial database.

Data source: Curated CSV derived from federal education data APIs
(educationdata.urban.org) via build_dmv_education_csv.py. Virginia has ~132
school divisions. Independent cities (e.g., Alexandria, Richmond) have their
own divisions and use the city name in the county field.

GEOIDs follow the NCES LEAID format (state FIPS 51 + 5-digit district code),
which matches Census TIGER unified school district boundaries.

Idempotent: deletes existing VA rows and re-inserts on each run.
Does NOT drop or recreate the table — preserves data from other states.

Usage:
    python scripts/ingest_va_performance.py
    python scripts/ingest_va_performance.py --verify
"""

import argparse
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.ingest_utils import ingest_state_education, verify_state_education

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)

VA_CSV_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data", "va_district_performance.csv",
)


def ingest(csv_path: str = "", **kwargs):
    """Load VA performance CSV into spatial.db."""
    ingest_state_education(
        state_code="VA",
        csv_path=csv_path or VA_CSV_PATH,
        source_url="educationdata.urban.org (CCD + EDFacts)",
        registry_notes=(
            "Federal data via build_dmv_education_csv.py — CCD Directory "
            "(2022-23), EDFacts Graduation Rates (2019), CCD Finance (2020). "
            "VA independent cities use city name in county field. "
            "ELA/Math/absenteeism fields empty (state-specific). Update "
            "from VDOE data portal if available."
        ),
    )


def verify():
    """Quick verification: look up VA performance data."""
    verify_state_education("VA")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Load VA performance data")
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
