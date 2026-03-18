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

NYSED_CSV_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data", "nysed_district_performance.csv",
)


def ingest(csv_path: str = "", **kwargs):
    """Load NYSED performance CSV into spatial.db."""
    ingest_state_education(
        state_code="NY",
        csv_path=csv_path or NYSED_CSV_PATH,
        source_url="data.nysed.gov (curated CSV)",
        registry_notes=(
            "MANUAL REFRESH — NYSED publishes bulk data as Access DBs "
            "(data.nysed.gov/downloads.php), no stable API. "
            "Update CSV annually after Report Card release (~Dec)."
        ),
        # Legacy: NY was registered without state suffix
        registry_facility_type="state_education_performance",
    )


def verify():
    """Quick verification: look up White Plains performance data."""
    verify_state_education("NY", sample_query="district_name LIKE '%White Plains%'")


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
