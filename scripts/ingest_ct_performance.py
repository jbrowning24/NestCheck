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

CT_CSV_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data", "ct_district_performance.csv",
)


def ingest(csv_path: str = "", **kwargs):
    """Load CT performance CSV into spatial.db."""
    ingest_state_education(
        state_code="CT",
        csv_path=csv_path or CT_CSV_PATH,
        source_url="edsight.ct.gov / data.ctdata.org (curated CSV)",
        registry_notes=(
            "MANUAL REFRESH — CT publishes education data across EdSight "
            "(edsight.ct.gov) and CTData.org. Download district-level "
            "graduation, SBAC, chronic absenteeism, and expenditure data, "
            "then update data/ct_district_performance.csv."
        ),
    )


def verify():
    """Quick verification: look up CT performance data."""
    verify_state_education("CT")


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
