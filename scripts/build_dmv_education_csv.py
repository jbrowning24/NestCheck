#!/usr/bin/env python3
"""
Build MD, DC, VA school district performance CSVs from federal data sources.

Combines three federal datasets per state via the Urban Institute Education
Data API (educationdata.urban.org):

1. NCES CCD Directory (2022-23): District names, counties, enrollment
   - Provides LEAID (= Census TIGER GEOID) for spatial joins
2. EDFacts Graduation Rates (2019): 4-year adjusted cohort graduation rates
3. CCD Finance (2020): Total expenditures -> per-pupil expenditure

ELA/Math proficiency and chronic absenteeism are state-specific metrics not
available from these federal sources. Fields are left empty for now; they can
be filled from MSDE, OSSE, or VDOE data portals in a future pass.

State notes:
  - MD (FIPS 24): ~24 unified school districts (county-based)
  - DC (FIPS 11): 1 unified school district (DCPS, GEOID 1100030)
  - VA (FIPS 51): ~130+ school divisions; independent cities have their own
    divisions and use the city name in the county field

Output: data/{md,dc,va}_district_performance.csv

Usage:
    python scripts/build_dmv_education_csv.py
    python scripts/build_dmv_education_csv.py --dry-run
    python scripts/build_dmv_education_csv.py --states MD DC
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
URBAN_API_BASE = "https://educationdata.urban.org/api/v1"
AGENCY_TYPE_REGULAR = 1  # Regular local school district

REQUEST_TIMEOUT = 60
MAX_RETRIES = 3
RETRY_BACKOFF = 5

# States to build CSVs for, keyed by 2-letter code
DMV_STATES = {
    "MD": {"fips": 24, "csv": "md_district_performance.csv"},
    "DC": {"fips": 11, "csv": "dc_district_performance.csv"},
    "VA": {"fips": 51, "csv": "va_district_performance.csv"},
}

CSV_FIELDNAMES = [
    "geoid", "district_name", "county",
    "graduation_rate_pct", "ela_proficiency_pct", "math_proficiency_pct",
    "chronic_absenteeism_pct", "pupil_expenditure", "source_year",
]


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
    result = name.title()
    # Fix common acronyms and short words
    replacements = {
        " Of ": " of ",
        " The ": " the ",
        " And ": " and ",
        " For ": " for ",
        " In ": " in ",
        " Co ": " Co ",
    }
    for old, new in replacements.items():
        result = result.replace(old, new)
    # Ensure first character stays capitalized
    if result:
        result = result[0].upper() + result[1:]
    return result


def fetch_ccd_directory(fips: int) -> dict:
    """Fetch regular school districts from CCD directory for a state.

    Returns dict keyed by LEAID (str) with district info.
    """
    url = f"{URBAN_API_BASE}/school-districts/ccd/directory/2022/"
    params = {"fips": fips, "limit": 2000}
    data = _api_get(url, params)
    results = data.get("results", [])
    logger.info("  CCD directory: %d total records fetched", len(results))

    districts = {}
    for r in results:
        if r.get("agency_type") != AGENCY_TYPE_REGULAR:
            continue

        leaid = str(r.get("leaid", ""))
        if not leaid:
            continue

        county = r.get("county_name", "")
        if county and county.endswith(" County"):
            county = county[:-7]

        districts[leaid] = {
            "geoid": leaid,
            "district_name": _title_case_district(r.get("lea_name", "")),
            "county": county,
            "enrollment": r.get("enrollment"),
        }

    logger.info("  CCD directory: %d regular school districts", len(districts))
    return districts


def fetch_grad_rates(fips: int) -> dict:
    """Fetch district graduation rates from EDFacts.

    Returns dict keyed by LEAID with grad_rate_midpt.
    Filters select the 'all students' aggregate (race=99, etc.).
    """
    url = f"{URBAN_API_BASE}/school-districts/edfacts/grad-rates/2019/"
    params = {
        "fips": fips,
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
    logger.info("  EDFacts grad rates: %d records", len(results))

    rates = {}
    for r in results:
        leaid = str(r.get("leaid", ""))
        rate = r.get("grad_rate_midpt")
        if leaid and rate is not None and rate >= 0:
            rates[leaid] = rate

    logger.info("  EDFacts grad rates: %d districts with valid rates", len(rates))
    return rates


def fetch_finance_data(fips: int, districts: dict) -> dict:
    """Fetch district finance data and compute per-pupil expenditure.

    Returns dict keyed by LEAID with pupil_expenditure.
    """
    url = f"{URBAN_API_BASE}/school-districts/ccd/finance/2020/"
    params = {"fips": fips, "limit": 2000}
    data = _api_get(url, params)
    results = data.get("results", [])
    logger.info("  CCD finance: %d records", len(results))

    expenditures = {}
    for r in results:
        leaid = str(r.get("leaid", ""))
        if not leaid:
            continue

        exp_total = r.get("exp_current_elsec_total")
        if exp_total is None or exp_total <= 0:
            continue

        enrollment = None
        if leaid in districts:
            enrollment = districts[leaid].get("enrollment")

        if enrollment and enrollment > 0:
            expenditures[leaid] = round(exp_total / enrollment)

    logger.info("  CCD finance: %d districts with per-pupil expenditure", len(expenditures))
    return expenditures


def build_state_csv(
    state_code: str,
    fips: int,
    output_path: str,
    dry_run: bool = False,
) -> list[dict]:
    """Build a single state's education performance CSV.

    Returns the list of row dicts written (or that would be written).
    """
    logger.info("Building %s (FIPS %d)...", state_code, fips)

    districts = fetch_ccd_directory(fips)
    grad_rates = fetch_grad_rates(fips)
    expenditures = fetch_finance_data(fips, districts)

    rows = []
    for leaid, info in sorted(districts.items()):
        grad_rate = grad_rates.get(leaid)
        expenditure = expenditures.get(leaid)

        rows.append({
            "geoid": info["geoid"],
            "district_name": info["district_name"],
            "county": info["county"],
            "graduation_rate_pct": str(grad_rate) if grad_rate is not None else "",
            "ela_proficiency_pct": "",      # State-specific, not in federal data
            "math_proficiency_pct": "",      # State-specific, not in federal data
            "chronic_absenteeism_pct": "",   # State-specific, not in federal data
            "pupil_expenditure": str(expenditure) if expenditure is not None else "",
            "source_year": "2019-20",
        })

    # Coverage stats
    with_grad = sum(1 for r in rows if r["graduation_rate_pct"])
    with_exp = sum(1 for r in rows if r["pupil_expenditure"])
    logger.info(
        "  %s: %d districts, grad_rate=%d, expenditure=%d",
        state_code, len(rows), with_grad, with_exp,
    )

    if dry_run:
        logger.info("  DRY RUN — not writing %s. Sample rows:", output_path)
        for r in rows[:3]:
            logger.info(
                "    %s: %s (%s) — grad=%s, exp=%s",
                r["geoid"], r["district_name"], r["county"],
                r["graduation_rate_pct"] or "—",
                r["pupil_expenditure"] or "—",
            )
        return rows

    with open(output_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)

    logger.info("  Wrote %d districts to %s", len(rows), output_path)
    return rows


def main():
    parser = argparse.ArgumentParser(
        description="Build MD/DC/VA district performance CSVs from federal APIs",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Fetch data and show stats without writing CSVs.",
    )
    parser.add_argument(
        "--states", nargs="+", default=list(DMV_STATES.keys()),
        help="Which states to build (default: all). E.g., --states MD DC",
    )
    args = parser.parse_args()

    for state_code in args.states:
        state_code = state_code.upper()
        if state_code not in DMV_STATES:
            logger.error("Unknown state: %s (valid: %s)", state_code, list(DMV_STATES.keys()))
            continue

        cfg = DMV_STATES[state_code]
        output_path = os.path.join(PROJECT_ROOT, "data", cfg["csv"])
        build_state_csv(state_code, cfg["fips"], output_path, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
