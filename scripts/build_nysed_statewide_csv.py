#!/usr/bin/env python3
"""
Build statewide NY school district performance CSV from federal data sources.

Combines three federal datasets to create a comprehensive CSV covering all
regular school districts in New York State:

1. NCES CCD Directory (2022-23): District names, counties, enrollment
   - API: educationdata.urban.org
   - Provides LEAID (= Census TIGER GEOID) for spatial joins

2. EDFacts Graduation Rates (2019): 4-year adjusted cohort graduation rates
   - API: educationdata.urban.org
   - Most recent available year with complete data

3. CCD Finance (2020): Total expenditures → per-pupil expenditure
   - API: educationdata.urban.org
   - Computed as exp_current_elsec_total / enrollment

For ELA/Math proficiency and chronic absenteeism, these metrics are
state-specific (NYSED Report Card data) and not available from federal
sources. The script preserves existing Westchester data for these fields
and leaves them NULL for non-Westchester districts.

To fill in statewide ELA/Math/absenteeism data, extract from NYSED
Access databases (see ingest_nysed.py docstring for instructions).

Output: data/nysed_district_performance.csv

Usage:
    python scripts/build_nysed_statewide_csv.py
    python scripts/build_nysed_statewide_csv.py --dry-run
"""

import argparse
import csv
import logging
import os
import sys
import time

import requests

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT_CSV = os.path.join(PROJECT_ROOT, "data", "nysed_district_performance.csv")
EXISTING_CSV = OUTPUT_CSV  # We merge existing Westchester data back in

URBAN_API_BASE = "https://educationdata.urban.org/api/v1"
NY_FIPS = 36
AGENCY_TYPE_REGULAR = 1  # Regular local school district

# County FIPS → county name mapping for NY (from Census)
# The CCD API returns "X County" format; we strip " County" for the CSV.

REQUEST_TIMEOUT = 60
MAX_RETRIES = 3
RETRY_BACKOFF = 5


def _api_get(url: str, params: dict) -> dict:
    """Fetch JSON from Urban Institute API with retries."""
    for attempt in range(MAX_RETRIES):
        try:
            resp = requests.get(url, params=params, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            if attempt < MAX_RETRIES - 1:
                wait = RETRY_BACKOFF * (attempt + 1)
                logger.warning(
                    "API request failed (attempt %d): %s — retrying in %ds",
                    attempt + 1, e, wait,
                )
                time.sleep(wait)
            else:
                raise


def _title_case_district(name: str) -> str:
    """Convert ALL CAPS district name to title case, preserving acronyms."""
    if not name:
        return name
    # Title-case the name
    result = name.title()
    # Fix common acronyms and short words
    replacements = {
        " Csd": " CSD",
        " Ufsd": " UFSD",
        " Boces": " BOCES",
        " Of ": " of ",
        " The ": " the ",
        " And ": " and ",
    }
    for old, new in replacements.items():
        result = result.replace(old, new)
    # Ensure first character is capitalized
    if result:
        result = result[0].upper() + result[1:]
    return result


def fetch_ccd_directory() -> dict:
    """Fetch all NY regular school districts from CCD directory.

    Returns dict keyed by LEAID (str) with district info.
    """
    url = f"{URBAN_API_BASE}/school-districts/ccd/directory/2022/"
    params = {"fips": NY_FIPS, "limit": 2000}
    data = _api_get(url, params)
    results = data.get("results", [])
    logger.info("CCD directory: %d total districts fetched", len(results))

    districts = {}
    for r in results:
        # Only include regular local school districts (agency_type=1)
        if r.get("agency_type") != AGENCY_TYPE_REGULAR:
            continue

        leaid = str(r.get("leaid", ""))
        if not leaid:
            continue

        county = r.get("county_name", "")
        if county and county.endswith(" County"):
            county = county[:-7]  # Strip " County" suffix

        districts[leaid] = {
            "geoid": leaid,
            "district_name": _title_case_district(r.get("lea_name", "")),
            "county": county,
            "enrollment": r.get("enrollment"),
        }

    logger.info("CCD directory: %d regular school districts", len(districts))
    return districts


def fetch_grad_rates() -> dict:
    """Fetch NY district graduation rates from EDFacts.

    Returns dict keyed by LEAID with grad_rate_midpt.
    The filters select the "all students" aggregate (race=99, etc.).
    """
    url = f"{URBAN_API_BASE}/school-districts/edfacts/grad-rates/2019/"
    params = {
        "fips": NY_FIPS,
        "race": 99,
        "disability": 99,
        "lep": 99,
        "homeless": 99,
        "econ_disadvantaged": 99,
        "foster_care": 99,
        "limit": 2000,
    }
    data = _api_get(url, params)
    results = data.get("results", [])
    logger.info("EDFacts grad rates: %d records", len(results))

    rates = {}
    for r in results:
        leaid = str(r.get("leaid", ""))
        rate = r.get("grad_rate_midpt")
        if leaid and rate is not None and rate >= 0:
            rates[leaid] = rate

    logger.info("EDFacts grad rates: %d districts with valid rates", len(rates))
    return rates


def fetch_finance_data(districts: dict) -> dict:
    """Fetch NY district finance data and compute per-pupil expenditure.

    Returns dict keyed by LEAID with pupil_expenditure.
    """
    url = f"{URBAN_API_BASE}/school-districts/ccd/finance/2020/"
    params = {"fips": NY_FIPS, "limit": 2000}
    data = _api_get(url, params)
    results = data.get("results", [])
    logger.info("CCD finance: %d records", len(results))

    expenditures = {}
    for r in results:
        leaid = str(r.get("leaid", ""))
        if not leaid:
            continue

        exp_total = r.get("exp_current_elsec_total")
        if exp_total is None or exp_total <= 0:
            continue

        # Get enrollment from the district directory data
        enrollment = None
        if leaid in districts:
            enrollment = districts[leaid].get("enrollment")

        if enrollment and enrollment > 0:
            per_pupil = round(exp_total / enrollment)
            expenditures[leaid] = per_pupil

    logger.info("CCD finance: %d districts with per-pupil expenditure", len(expenditures))
    return expenditures


def load_existing_westchester(fallback_path: str = "") -> dict:
    """Load existing Westchester performance data to preserve ELA/Math/absenteeism.

    The existing CSV may use legacy GEOIDs that don't match CCD/TIGER LEAIDs,
    so we key by normalized district name for matching.

    Returns dict keyed by uppercase district name with full row data.
    """
    csv_path = fallback_path or EXISTING_CSV
    if not os.path.exists(csv_path):
        logger.info("No existing CSV found at %s", csv_path)
        return {}

    existing = {}
    with open(csv_path, "r", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            name = row.get("district_name", "").upper().strip()
            if name:
                existing[name] = row

    logger.info("Loaded %d existing districts (keyed by name)", len(existing))
    return existing


def _normalize_name(name: str) -> str:
    """Normalize a district name for fuzzy matching."""
    return name.upper().strip()


# Known name differences between legacy CSV and CCD/TIGER
_NAME_ALIASES = {
    "MOUNT VERNON CITY SCHOOL DISTRICT": "MOUNT VERNON SCHOOL DISTRICT",
    "TARRYTOWN UNION FREE SCHOOL DISTRICT": "UNION FREE SCHOOL DISTRICT OF THE TARRYTOWNS",
}


def _find_existing_match(ccd_name: str, existing: dict) -> dict | None:
    """Find existing Westchester data by name, handling known aliases."""
    norm = _normalize_name(ccd_name)
    if norm in existing:
        return existing[norm]

    # Check known aliases
    for alias, canonical in _NAME_ALIASES.items():
        if norm == canonical and alias in existing:
            return existing[alias]
        if norm == alias and canonical in existing:
            return existing[canonical]

    return None


def build_statewide_csv(
    dry_run: bool = False,
    existing_csv: str = "",
) -> None:
    """Build the statewide CSV by merging federal and existing data."""

    # Step 1: Load existing Westchester data (before we overwrite the file)
    existing = load_existing_westchester(fallback_path=existing_csv)

    # Step 2: Fetch federal data
    logger.info("Fetching CCD directory...")
    districts = fetch_ccd_directory()

    logger.info("Fetching EDFacts graduation rates...")
    grad_rates = fetch_grad_rates()

    logger.info("Fetching CCD finance data...")
    expenditures = fetch_finance_data(districts)

    # Step 3: Merge all data sources
    rows = []
    westchester_preserved = 0
    federal_only = 0

    for leaid, info in sorted(districts.items()):
        geoid = info["geoid"]

        # Match by name (legacy CSV GEOIDs differ from CCD/TIGER LEAIDs)
        match = _find_existing_match(info["district_name"], existing)

        if match:
            # Preserve existing performance data (has ELA, math, absenteeism)
            # Use the correct CCD/TIGER GEOID, not the legacy one
            row = {
                "geoid": geoid,
                "district_name": info["district_name"],
                "county": info["county"],
                "graduation_rate_pct": match.get("graduation_rate_pct", ""),
                "ela_proficiency_pct": match.get("ela_proficiency_pct", ""),
                "math_proficiency_pct": match.get("math_proficiency_pct", ""),
                "chronic_absenteeism_pct": match.get("chronic_absenteeism_pct", ""),
                "pupil_expenditure": match.get("pupil_expenditure", ""),
                "source_year": match.get("source_year", "2023-24"),
            }
            westchester_preserved += 1
        else:
            # New district from federal data
            grad_rate = grad_rates.get(leaid)
            expenditure = expenditures.get(leaid)

            row = {
                "geoid": geoid,
                "district_name": info["district_name"],
                "county": info["county"],
                "graduation_rate_pct": str(grad_rate) if grad_rate is not None else "",
                "ela_proficiency_pct": "",  # NYSED-only, requires Access DB extraction
                "math_proficiency_pct": "",  # NYSED-only, requires Access DB extraction
                "chronic_absenteeism_pct": "",  # NYSED-only, requires Access DB extraction
                "pupil_expenditure": str(expenditure) if expenditure is not None else "",
                "source_year": "2019-20",  # Federal data years
            }
            federal_only += 1

        rows.append(row)

    logger.info(
        "Merged: %d total districts (%d Westchester preserved, %d federal-only)",
        len(rows), westchester_preserved, federal_only,
    )

    # Stats
    with_grad = sum(1 for r in rows if r["graduation_rate_pct"])
    with_ela = sum(1 for r in rows if r["ela_proficiency_pct"])
    with_exp = sum(1 for r in rows if r["pupil_expenditure"])
    logger.info("Coverage: grad_rate=%d, ela=%d, expenditure=%d", with_grad, with_ela, with_exp)

    if dry_run:
        logger.info("DRY RUN — not writing CSV. Sample rows:")
        for r in rows[:5]:
            logger.info("  %s: %s (%s) — grad=%s, ela=%s, exp=%s",
                        r["geoid"], r["district_name"], r["county"],
                        r["graduation_rate_pct"] or "—",
                        r["ela_proficiency_pct"] or "—",
                        r["pupil_expenditure"] or "—")
        return

    # Step 4: Write CSV
    fieldnames = [
        "geoid", "district_name", "county",
        "graduation_rate_pct", "ela_proficiency_pct", "math_proficiency_pct",
        "chronic_absenteeism_pct", "pupil_expenditure", "source_year",
    ]

    with open(OUTPUT_CSV, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    logger.info("Wrote %d districts to %s", len(rows), OUTPUT_CSV)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Build statewide NY district performance CSV from federal APIs",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Fetch data and show stats without writing CSV.",
    )
    parser.add_argument(
        "--existing-csv", type=str, default="",
        help="Path to existing CSV with Westchester data to merge.",
    )
    args = parser.parse_args()

    build_statewide_csv(dry_run=args.dry_run, existing_csv=args.existing_csv)
