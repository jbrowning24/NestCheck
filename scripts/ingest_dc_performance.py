#!/usr/bin/env python3
"""
Load DC school district performance data into the NestCheck spatial database.

Data source: Curated CSV derived from federal education data APIs
(educationdata.urban.org) via build_dmv_education_csv.py. DC has a single
unified school district (DCPS, GEOID 1100030). Charter LEAs are excluded
(agency_type != 1 in CCD).

GEOIDs follow the NCES LEAID format (state FIPS 11 + 5-digit district code),
which matches Census TIGER unified school district boundaries.

Idempotent: deletes existing DC rows and re-inserts on each run.
Does NOT drop or recreate the table — preserves data from other states.

Usage:
    python scripts/ingest_dc_performance.py
    python scripts/ingest_dc_performance.py --verify
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

DC_CSV_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data", "dc_district_performance.csv",
)


def ingest(csv_path: str = "", **kwargs):
    """Load DC performance CSV into spatial.db."""
    ingest_state_education(
        state_code="DC",
        csv_path=csv_path or DC_CSV_PATH,
        source_url="educationdata.urban.org (CCD + EDFacts)",
        registry_notes=(
            "Federal data via build_dmv_education_csv.py — CCD Directory "
            "(2022-23), EDFacts Graduation Rates (2019), CCD Finance (2020). "
            "DC has one unified district (DCPS). Charter LEAs excluded. "
            "ELA/Math/absenteeism fields empty (state-specific). Update "
            "from OSSE data portal if available."
        ),
    )


def verify():
    """Quick verification: look up DC performance data."""
    verify_state_education("DC")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Load DC performance data")
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
