#!/usr/bin/env bash
# ============================================================================
# prepare_fema_bulk.sh — Convert FEMA NFHL GDB downloads to NDJSON for bulk
# ingestion into NestCheck's spatial.db.
#
# NES-404: FEMA REST API fails for dense metros (DMV). This script converts
# state-level GDB files (downloaded manually from FEMA MSC) into gzipped
# NDJSON clipped to the DMV metro bbox.
#
# Prerequisites:
#   - brew install gdal  (provides ogr2ogr)
#   - Download state GDB zips from FEMA MSC:
#     https://hazards.fema.gov/nfhlv2/output/State/NFHL_{FIPS}_{DATE}.zip
#
# Current DMV download URLs (verified 2026-04-03):
#   DC:  https://hazards.fema.gov/nfhlv2/output/State/NFHL_11_20150309.zip  (2 MB)
#   MD:  https://hazards.fema.gov/nfhlv2/output/State/NFHL_24_20220414.zip  (466 MB)
#   VA:  https://hazards.fema.gov/nfhlv2/output/State/NFHL_51_20231201.zip  (1.2 GB)
#
# Usage:
#   1. Download the three zip files into data/fema_nfhl/
#   2. Run this script from the project root:
#      bash scripts/prepare_fema_bulk.sh
#   3. Output: data/fema_nfhl/{dc,md,va}_dmv.ndjson.gz
#
# After conversion, bump FEMA_INGEST_VERSION in scripts/ingest_fema.py to
# trigger re-ingestion on the next deploy.
# ============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
BULK_DIR="$PROJECT_ROOT/data/fema_nfhl"

# DMV metro bounding box (matches METRO_BBOXES["dmv"] in ingest_fema.py)
DMV_BBOX="-77.55 38.55 -76.50 39.50"

# Layer containing flood hazard area polygons
LAYER="S_Fld_Haz_Ar"

# Fields to extract (must match ingest_fema.py metadata keys)
FIELDS="FLD_ZONE,ZONE_SUBTY,SFHA_TF,STATIC_BFE,DEPTH,DFIRM_ID"

# Coordinate precision: 6 decimals = ~11cm accuracy (sufficient for flood zones)
PRECISION=6

# State FIPS → file mapping
declare -A STATES=(
    ["dc"]="11"
    ["md"]="24"
    ["va"]="51"
)

command -v ogr2ogr >/dev/null 2>&1 || {
    echo "ERROR: ogr2ogr not found. Install with: brew install gdal"
    exit 1
}

cd "$BULK_DIR"

for state in dc md va; do
    fips="${STATES[$state]}"

    # Find the zip file for this state (pattern: NFHL_{FIPS}_*.zip)
    zip_file=$(ls NFHL_${fips}_*.zip 2>/dev/null | head -1)
    if [ -z "$zip_file" ]; then
        echo "SKIP: No zip file found for $state (FIPS $fips). Expected NFHL_${fips}_*.zip"
        continue
    fi

    # Derive GDB directory name from zip filename
    gdb_name="${zip_file%.zip}.gdb"
    ndjson_out="${state}_dmv.ndjson"
    gz_out="${ndjson_out}.gz"

    echo "=== Processing $state ($zip_file) ==="

    # Unzip
    echo "  Unzipping..."
    unzip -oq "$zip_file" -d "tmp_${state}"

    # Find the .gdb directory (may be nested)
    gdb_path=$(find "tmp_${state}" -name "*.gdb" -type d | head -1)
    if [ -z "$gdb_path" ]; then
        echo "  ERROR: No .gdb directory found in $zip_file"
        rm -rf "tmp_${state}"
        continue
    fi

    # Convert with spatial clip to DMV bbox
    echo "  Converting $LAYER → $ndjson_out (clipped to DMV bbox)..."
    ogr2ogr -f GeoJSONSeq \
        -t_srs EPSG:4326 \
        -spat $DMV_BBOX \
        -select "$FIELDS" \
        -lco COORDINATE_PRECISION=$PRECISION \
        "$ndjson_out" \
        "$gdb_path" \
        "$LAYER"

    # Compress
    echo "  Compressing → $gz_out..."
    gzip -f "$ndjson_out"

    # Report
    feature_count=$(zcat "$gz_out" | wc -l | tr -d ' ')
    size=$(ls -lh "$gz_out" | awk '{print $5}')
    echo "  Done: $feature_count features, $size compressed"

    # Clean up unzipped GDB
    rm -rf "tmp_${state}"
    echo ""
done

echo "=== Bulk preparation complete ==="
ls -lh *_dmv.ndjson.gz 2>/dev/null || echo "No output files generated."
