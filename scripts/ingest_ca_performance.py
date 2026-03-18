#!/usr/bin/env python3
"""
Load CA school district performance data into the NestCheck spatial database.

Data source: Curated CSV derived from California Department of Education (CDE)
DataQuest. Graduation rates, CAASPP proficiency (ELA + math), chronic
absenteeism, and per-pupil spending sourced from CDE publications.

GEOIDs follow the NCES LEAID format (state FIPS 06 + 5-digit district code),
which matches Census TIGER unified school district boundaries.

Idempotent: deletes existing CA rows and re-inserts on each run.
Does NOT drop or recreate the table — preserves data from other states.

CSV needs to be populated from CDE DataQuest:
https://www.cde.ca.gov/ds/ad/fileslsafl.asp

Usage:
    python scripts/ingest_ca_performance.py
    python scripts/ingest_ca_performance.py --verify
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

CA_CSV_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data", "ca_district_performance.csv",
)


def ingest(csv_path: str = "", **kwargs):
    """Load CA performance CSV into spatial.db."""
    ingest_state_education(
        state_code="CA",
        csv_path=csv_path or CA_CSV_PATH,
        source_url="cde.ca.gov (CDE DataQuest, curated CSV)",
        registry_notes=(
            "MANUAL REFRESH — CDE publishes district-level data at "
            "cde.ca.gov/ds/ad/fileslsafl.asp as downloadable files. "
            "CAASPP proficiency, graduation rates, chronic absenteeism, "
            "and per-pupil expenditure. Update data/ca_district_performance.csv "
            "annually after CDE releases new data (~fall)."
        ),
    )


def verify():
    """Quick verification: look up CA performance data."""
    verify_state_education("CA")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Load CA performance data")
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
