#!/usr/bin/env python3
"""
Load NJ school district performance data into the NestCheck spatial database.

Data source: Curated CSV derived from NJDOE School Performance Report data
(https://www.nj.gov/education/spr/download/). NJDOE publishes databases as
Excel/Access files; this script loads a pre-processed CSV with key metrics
per district.

GEOIDs follow the NCES LEAID format (state FIPS 34 + 5-digit district code),
which matches Census TIGER unified school district boundaries.

Idempotent: deletes existing NJ rows and re-inserts on each run.
Does NOT drop or recreate the table — preserves data from other states.

Usage:
    python scripts/ingest_nj_performance.py
    python scripts/ingest_nj_performance.py --verify
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

NJ_CSV_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data", "nj_district_performance.csv",
)


def ingest(csv_path: str = "", **kwargs):
    """Load NJ performance CSV into spatial.db."""
    ingest_state_education(
        state_code="NJ",
        csv_path=csv_path or NJ_CSV_PATH,
        source_url="nj.gov/education/spr/download (curated CSV)",
        registry_notes=(
            "MANUAL REFRESH — NJDOE publishes School Performance Reports "
            "(nj.gov/education/spr/download/) as Excel/Access databases. "
            "Download 2023-2024 district data, extract metrics, and "
            "update data/nj_district_performance.csv."
        ),
    )


def verify():
    """Quick verification: look up NJ performance data."""
    verify_state_education("NJ")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Load NJ performance data")
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
