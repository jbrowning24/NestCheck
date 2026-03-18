#!/usr/bin/env python3
"""
Load TX school district performance data into the NestCheck spatial database.

Data source: Curated CSV derived from Texas Education Agency (TEA) Texas
Academic Performance Reports (TAPR). Graduation rates, STAAR proficiency
(ELA + math), chronic absenteeism, and per-pupil spending sourced from
TEA publications.

GEOIDs follow the NCES LEAID format (state FIPS 48 + 5-digit district code),
which matches Census TIGER unified school district boundaries.

Idempotent: deletes existing TX rows and re-inserts on each run.
Does NOT drop or recreate the table — preserves data from other states.

CSV needs to be populated from TEA TAPR:
https://tea.texas.gov/reports-and-data

Usage:
    python scripts/ingest_tx_performance.py
    python scripts/ingest_tx_performance.py --verify
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

TX_CSV_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data", "tx_district_performance.csv",
)


def ingest(csv_path: str = "", **kwargs):
    """Load TX performance CSV into spatial.db."""
    ingest_state_education(
        state_code="TX",
        csv_path=csv_path or TX_CSV_PATH,
        source_url="tea.texas.gov (TEA TAPR, curated CSV)",
        registry_notes=(
            "MANUAL REFRESH — TEA publishes district-level data at "
            "tea.texas.gov/reports-and-data as downloadable reports. "
            "STAAR proficiency, graduation rates, chronic absenteeism, "
            "and per-pupil expenditure. Update data/tx_district_performance.csv "
            "annually after TEA releases new data (~fall)."
        ),
    )


def verify():
    """Quick verification: look up TX performance data."""
    verify_state_education("TX")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Load TX performance data")
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
