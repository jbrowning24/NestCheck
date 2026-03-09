#!/usr/bin/env python3
"""
One-time crosswalk script: fix GEOIDs in all three state education CSVs.

Problem: The original CSVs used fabricated GEOIDs that don't match Census
TIGER unified school district boundaries. This script:

1. Fetches real TIGER GEOIDs + district names for NY, NJ, CT
2. Matches each CSV district name to its TIGER district by normalized name
3. Rewrites each CSV with the correct TIGER GEOID

Special cases:
- "Tarrytown Union Free School District" → "Union Free School District of the Tarrytowns"
- "Mount Vernon City School District" → "Mount Vernon School District"
- "Montclair Township School District" → "Montclair Town School District"
- "West Orange Township School District" → "West Orange Town School District"
- Dropped: Hawthorne-Cedar Knolls (special-purpose facility, no TIGER boundary)
- Dropped: Mansfield CT (part of a regional district, no unified boundary in TIGER)

Usage:
    python scripts/crosswalk_geoids.py              # dry-run (print changes)
    python scripts/crosswalk_geoids.py --write       # overwrite CSVs
"""

import argparse
import csv
import logging
import os
import re
import sys

import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")

TIGER_SD_ENDPOINT = (
    "https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb"
    "/tigerWMS_Current/MapServer/14/query"
)

# Hard-coded name overrides for districts whose CSV name doesn't normalize
# to match the TIGER name.  Format: (state, csv_district_name) → tiger_name_key
_NAME_OVERRIDES: dict[tuple[str, str], str] = {
    ("NY", "Tarrytown Union Free School District"): "union free school district of the tarrytowns",
    ("NY", "Mount Vernon City School District"): "mount vernon",
    ("NJ", "Montclair Township School District"): "montclair town",
    ("NJ", "West Orange Township School District"): "west orange town",
}

# Districts to drop — no TIGER unified school district boundary exists
_DROP_DISTRICTS: set[tuple[str, str]] = {
    ("NY", "Hawthorne-Cedar Knolls Union Free School District"),
    ("CT", "Mansfield School District"),
}

CSV_FILES: list[tuple[str, str, str]] = [
    ("nysed_district_performance.csv", "NY", "36"),
    ("nj_district_performance.csv", "NJ", "34"),
    ("ct_district_performance.csv", "CT", "09"),
]


def _normalize(name: str) -> str:
    """Normalize a district name for fuzzy matching."""
    n = name.lower().strip()
    for suffix in [
        " school district",
        " city school district",
        " central school district",
        " union free school district",
        " township school district",
        " borough school district",
        " village school district",
        " regional school district",
        " public schools",
        " town school district",
    ]:
        if n.endswith(suffix):
            n = n[: -len(suffix)]
            break
    return re.sub(r"\s+", " ", n).strip()


def _fetch_tiger_districts(fips: str) -> dict[str, tuple[str, str]]:
    """Fetch TIGER districts for a state → {normalized_name: (geoid, full_name)}."""
    resp = requests.get(
        TIGER_SD_ENDPOINT,
        params={
            "where": f"STATE='{fips}'",
            "outFields": "GEOID,NAME,BASENAME",
            "returnGeometry": "false",
            "f": "json",
            "resultRecordCount": 1000,
        },
        timeout=60,
    )
    resp.raise_for_status()
    data = resp.json()
    if "error" in data:
        raise RuntimeError(f"ArcGIS error: {data['error']}")

    features = data.get("features", [])
    logger.info("TIGER returned %d districts for FIPS %s", len(features), fips)

    result: dict[str, tuple[str, str]] = {}
    for feat in features:
        attrs = feat["attributes"]
        geoid = attrs["GEOID"]
        name = attrs["NAME"]
        basename = attrs.get("BASENAME", "")

        nkey = _normalize(name)
        result[nkey] = (geoid, name)

        bkey = _normalize(basename)
        if bkey and bkey != nkey:
            result[bkey] = (geoid, name)

    return result


def crosswalk(write: bool = False) -> dict[str, list[str]]:
    """Run the crosswalk. Returns {state: [list of changes made]}."""
    all_changes: dict[str, list[str]] = {}

    for csv_name, state, fips in CSV_FILES:
        csv_path = os.path.join(DATA_DIR, csv_name)
        logger.info("Processing %s (%s, FIPS %s)", csv_name, state, fips)

        tiger = _fetch_tiger_districts(fips)

        with open(csv_path, newline="") as f:
            reader = csv.DictReader(f)
            fieldnames = reader.fieldnames
            rows = list(reader)

        changes: list[str] = []
        output_rows: list[dict[str, str]] = []

        for row in rows:
            district = row["district_name"]

            # Check if this district should be dropped
            if (state, district) in _DROP_DISTRICTS:
                changes.append(f"DROPPED: {district} (no TIGER boundary)")
                continue

            # Try override first, then normalize
            override_key = _NAME_OVERRIDES.get((state, district))
            if override_key:
                nkey = override_key
            else:
                nkey = _normalize(district)

            if nkey in tiger:
                new_geoid, tiger_name = tiger[nkey]
                old_geoid = row["geoid"]
                if old_geoid != new_geoid:
                    changes.append(
                        f"FIXED: {district}: {old_geoid} → {new_geoid} "
                        f"(TIGER: {tiger_name})"
                    )
                row["geoid"] = new_geoid
                output_rows.append(row)
            else:
                # Try substring match
                found = False
                for tkey, (geoid, tname) in tiger.items():
                    if nkey in tkey or tkey in nkey:
                        old_geoid = row["geoid"]
                        if old_geoid != geoid:
                            changes.append(
                                f"FIXED (partial): {district}: {old_geoid} → {geoid} "
                                f"(TIGER: {tname})"
                            )
                        row["geoid"] = geoid
                        output_rows.append(row)
                        found = True
                        break
                if not found:
                    changes.append(f"UNMATCHED: {district} — kept with original GEOID")
                    output_rows.append(row)

        if write:
            with open(csv_path, "w", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(output_rows)
            logger.info("Wrote %d rows to %s", len(output_rows), csv_path)

        for c in changes:
            logger.info("  %s", c)

        logger.info(
            "%s summary: %d input → %d output, %d changes",
            state, len(rows), len(output_rows), len(changes),
        )
        all_changes[state] = changes

    return all_changes


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fix school district GEOIDs in CSVs")
    parser.add_argument(
        "--write", action="store_true",
        help="Actually overwrite CSV files (default: dry-run)",
    )
    args = parser.parse_args()

    if not args.write:
        logger.info("DRY RUN — pass --write to overwrite CSVs")

    changes = crosswalk(write=args.write)

    total = sum(len(c) for c in changes.values())
    logger.info("Total changes across all states: %d", total)
