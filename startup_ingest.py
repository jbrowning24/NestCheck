"""
Startup spatial data ingestion for NestCheck.

Called during gunicorn post_fork to ensure spatial datasets (SEMS, FEMA, HPMS,
EJScreen, TRI, UST, HIFLD, FRA, School Districts, NYSED, NCES) are populated before
the evaluation worker starts processing jobs. Uses a
file-based lock (fcntl) to prevent concurrent ingestion from multiple workers.

Datasets are checked in order and ingested independently — a failure in one
never blocks the others or crashes the worker.

Geographic scope: controlled by TARGET_STATES config below. State-filtered
datasets derive their filter lists from this dict. HIFLD ingests nationally
(no state field available). Only FEMA NFHL uses bbox filtering.
"""

import fcntl
import logging
import os
import sqlite3
import threading
import time

from spatial_data import _spatial_db_path

import re

# ── Geographic scope ────────────────────────────────────────────────────
# Single source of truth for all state-filtered ingestion. Adding a new
# state is a single dict entry; every ingest call below derives its filter
# from this config.
#
# Keys: 2-letter postal code (used by HPMS, EJScreen, TRI, NCES STABR, FRA STATEAB)
# Values:
#   fips      — 2-digit FIPS code (used by TIGER school districts)
#   full_name — full state name (used by UST)
#
# HIFLD ingests nationally (no state attribute field). FEMA NFHL uses
# per-metro bboxes with automatic 0.5-degree grid chunking (NES-286).
TARGET_STATES = {
    "NY": {"fips": "36", "full_name": "New York"},
    "NJ": {"fips": "34", "full_name": "New Jersey"},
    "CT": {"fips": "09", "full_name": "Connecticut"},
    "MI": {"fips": "26", "full_name": "Michigan"},
    "CA": {"fips": "06", "full_name": "California"},
    "TX": {"fips": "48", "full_name": "Texas"},
    "FL": {"fips": "12", "full_name": "Florida"},
    "IL": {"fips": "17", "full_name": "Illinois"},
}


# Per-state education performance ingest functions are registered at the
# bottom of the file (after function definitions) in _STATE_EDUCATION_INGEST.

logger = logging.getLogger("nestcheck.startup_ingest")

# Regex for valid table names: lowercase letters, digits, underscores only
_SAFE_TABLE_NAME = re.compile(r"^[a-z][a-z0-9_]*$")


def _validate_table_name(table_name: str) -> None:
    """Ensure table_name is safe for SQL interpolation."""
    if not _SAFE_TABLE_NAME.match(table_name):
        raise ValueError(f"Unsafe table name: {table_name!r}")


# Event signalling that spatial data is ready (or ingestion was attempted).
# The evaluation worker waits on this before processing its first job so that
# spatial health checks don't return UNKNOWN due to a race with ingestion.
spatial_ready = threading.Event()

# Warn (but don't kill) if a single ingest exceeds this threshold
_INGEST_WARN_SECONDS = 300  # 5 minutes


def _table_has_state_data(
    db_path: str, table_name: str, state: str,
) -> tuple[bool, int]:
    """Check if a table has rows for a specific state.

    Used for state_education_performance where NY, NJ, CT data are
    loaded independently and should be checked individually.
    """
    try:
        _validate_table_name(table_name)
        conn = sqlite3.connect(db_path)
        try:
            cursor = conn.execute(
                f"SELECT COUNT(*) FROM {table_name} WHERE state = ?", (state,)
            )
            count = cursor.fetchone()[0]
            return (count > 0, count)
        finally:
            conn.close()
    except Exception:
        return (False, 0)


def _table_has_data(db_path: str, table_name: str) -> tuple[bool, int]:
    """
    Check if a table exists in the spatial DB and has rows.

    Returns (has_data, row_count). On any error (DB missing, table missing,
    SpatiaLite not loaded), returns (False, 0) — never raises.
    """
    try:
        _validate_table_name(table_name)
        conn = sqlite3.connect(db_path)
        try:
            cursor = conn.execute(f"SELECT COUNT(*) FROM {table_name}")
            count = cursor.fetchone()[0]
            return (count > 0, count)
        finally:
            conn.close()
    except Exception:
        return (False, 0)


def _missing_states(
    db_path: str,
    table_name: str,
    state_expr: str,
    expected: dict[str, str],
) -> list[str]:
    """Return TARGET_STATES codes that have 0 rows in the given table.

    Args:
        db_path: Path to spatial.db.
        table_name: Table to check (e.g., "facilities_tri").
        state_expr: SQL expression that extracts the state identifier from a row.
            Examples:
            - "json_extract(metadata_json, '$.state')"  (returns 2-letter code)
            - "SUBSTR(json_extract(metadata_json, '$.geoid'), 1, 2)"  (returns FIPS)
            SAFETY: This is interpolated into SQL. Only pass hardcoded expressions
            from _missing_states_abbr/_missing_states_fips — never user input.
        expected: Mapping of TARGET_STATES code -> value that state_expr produces.
            e.g., {"NY": "NY", "MI": "MI"} for 2-letter, or {"NY": "36", "MI": "26"} for FIPS.

    Returns list of TARGET_STATES codes (e.g., ["MI", "CA"]) that are missing.
    On any error, returns all codes from expected (safe: triggers full re-ingest).
    """
    try:
        _validate_table_name(table_name)
        conn = sqlite3.connect(db_path)
        try:
            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                (table_name,),
            )
            if not cursor.fetchone():
                return list(expected.keys())

            cursor = conn.execute(
                f"SELECT DISTINCT {state_expr} FROM {table_name}"
            )
            present = {row[0] for row in cursor.fetchall()}
            return [
                code for code, val in expected.items()
                if val not in present
            ]
        finally:
            conn.close()
    except Exception:
        return list(expected.keys())


def _missing_states_abbr(db_path: str, table_name: str) -> list[str]:
    """Missing states for tables where metadata $.state is 2-letter code."""
    return _missing_states(
        db_path, table_name,
        "json_extract(metadata_json, '$.state')",
        {code: code for code in TARGET_STATES},
    )


def _missing_states_fips(db_path: str, table_name: str, json_field: str) -> list[str]:
    """Missing states for tables where a metadata field has FIPS prefix."""
    if not _SAFE_TABLE_NAME.match(json_field):
        raise ValueError(f"json_field must match [a-z][a-z0-9_]*, got {json_field!r}")
    return _missing_states(
        db_path, table_name,
        f"SUBSTR(json_extract(metadata_json, '$.{json_field}'), 1, 2)",
        {code: info["fips"] for code, info in TARGET_STATES.items()},
    )


def _ust_missing_states(db_path: str) -> list[str]:
    """Return target state codes that have 0 UST rows in spatial.db.

    UST stores state as full name in json_extract(metadata_json, '$.state').
    Returns e.g. ['NJ', 'CT', 'MI'] for states without data.
    On any error (table missing, DB missing), returns all target states.
    """
    return _missing_states(
        db_path,
        "facilities_ust",
        "json_extract(metadata_json, '$.state')",
        {code: info["full_name"] for code, info in TARGET_STATES.items()},
    )


def ensure_spatial_data() -> None:
    """
    Check each spatial dataset and run ingestion for any that are missing.

    Acquires an exclusive file lock so only one gunicorn worker performs
    ingestion. Other workers block on a shared lock until ingestion finishes,
    then signal spatial_ready so their evaluation worker can proceed.
    """
    logger.info("Checking spatial data availability...")

    db_path = _spatial_db_path()

    # Ensure parent directory is writable (ingestion will create the DB)
    parent = os.path.dirname(db_path)
    if parent:
        os.makedirs(parent, exist_ok=True)

    # File-based lock: prevent concurrent ingestion from multiple workers
    lock_path = os.path.join(
        os.path.dirname(db_path) or ".", ".ingest.lock"
    )
    lock_fd = open(lock_path, "w")
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        # Another worker holds the lock — wait for it to finish so that the
        # spatial DB exists before we signal readiness to our own worker thread.
        logger.info("Another worker is running ingestion, waiting for it to finish...")
        lock_fd.close()
        # Re-open read-only for shared lock; file may be empty but that's fine
        # on Linux (fcntl locks work on any valid fd regardless of content).
        lock_fd = open(lock_path, "r")
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_SH)  # blocks until exclusive lock is released
            logger.info("Other worker's ingestion finished, spatial data should be ready")
        except OSError:
            logger.warning("Failed to wait for ingestion lock, proceeding anyway")
        finally:
            lock_fd.close()
        spatial_ready.set()
        return

    try:
        _check_and_ingest_all(db_path)
        _sync_coverage_manifest()
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        lock_fd.close()
        spatial_ready.set()

    logger.info("Spatial data check complete")


# Dataset definitions: (name, table_name, ingest_callable)
# Ingest callables are imported lazily inside _check_and_ingest_all to avoid
# import errors if script dependencies are missing.

def _check_and_ingest_all(db_path: str) -> None:
    """Run the check-and-ingest loop for each dataset in order."""

    # --- SEMS (EPA Superfund boundaries) ---
    has_data, count = _table_has_data(db_path, "facilities_sems")
    if has_data:
        logger.info("Dataset sems: present (%d records), skipping", count)
    else:
        logger.info("Dataset sems: missing or empty, starting ingestion...")
        _run_ingest("sems", _ingest_sems)

    # --- FEMA NFHL (flood zones, per-metro with grid chunking) ---
    has_data, count = _table_has_data(db_path, "facilities_fema_nfhl")
    if has_data:
        logger.info("Dataset fema_nfhl: present (%d records), skipping", count)
    else:
        logger.info("Dataset fema_nfhl: missing or empty, starting ingestion...")
        _run_ingest("fema_nfhl", _ingest_fema)

    # --- HPMS (high-traffic roads, per-state incremental) ---
    hpms_missing = _missing_states_abbr(db_path, "facilities_hpms")
    if hpms_missing:
        has_data, count = _table_has_data(db_path, "facilities_hpms")
        logger.info(
            "Dataset hpms: missing states %s (%d existing records), ingesting missing states...",
            hpms_missing, count,
        )
        _run_ingest("hpms", lambda: _ingest_hpms_states(hpms_missing))
    else:
        has_data, count = _table_has_data(db_path, "facilities_hpms")
        logger.info("Dataset hpms: present for all %d states (%d records), skipping",
                     len(TARGET_STATES), count)

    # --- EJScreen (EPA environmental justice block groups) ---
    ejscreen_missing = _missing_states_abbr(db_path, "facilities_ejscreen")
    if ejscreen_missing:
        has_data, count = _table_has_data(db_path, "facilities_ejscreen")
        logger.info(
            "Dataset ejscreen: missing states %s (%d existing records), re-ingesting all states...",
            ejscreen_missing, count,
        )
        _run_ingest("ejscreen", _ingest_ejscreen)
    else:
        has_data, count = _table_has_data(db_path, "facilities_ejscreen")
        logger.info("Dataset ejscreen: present for all %d states (%d records), skipping",
                     len(TARGET_STATES), count)

    # --- TRI (EPA Toxic Release Inventory) ---
    tri_missing = _missing_states_abbr(db_path, "facilities_tri")
    if tri_missing:
        has_data, count = _table_has_data(db_path, "facilities_tri")
        logger.info(
            "Dataset tri: missing states %s (%d existing records), re-ingesting all states...",
            tri_missing, count,
        )
        _run_ingest("tri", _ingest_tri)
    else:
        has_data, count = _table_has_data(db_path, "facilities_tri")
        logger.info("Dataset tri: present for all %d states (%d records), skipping",
                     len(TARGET_STATES), count)

    # --- UST (EPA Underground Storage Tanks, all TARGET_STATES) ---
    # UST uses json_extract(metadata_json, '$.state') with full state names.
    # Must check per-state since existing NY-only data causes _table_has_data
    # to skip ingestion for the other 7 states (NES-304).
    ust_missing = _ust_missing_states(db_path)
    if ust_missing:
        has_data, count = _table_has_data(db_path, "facilities_ust")
        logger.info(
            "Dataset ust: missing states %s (%d existing records), starting full ingestion...",
            ust_missing, count,
        )
        _run_ingest("ust", _ingest_ust)
    else:
        has_data, count = _table_has_data(db_path, "facilities_ust")
        logger.info("Dataset ust: present for all %d states (%d records), skipping",
                     len(TARGET_STATES), count)

    # --- HIFLD (electric power transmission lines, national) ---
    has_data, count = _table_has_data(db_path, "facilities_hifld")
    if has_data:
        logger.info("Dataset hifld: present (%d records), skipping", count)
    else:
        logger.info("Dataset hifld: missing or empty, starting ingestion...")
        _run_ingest("hifld", _ingest_hifld)

    # --- FRA (rail network lines, state-filtered via STATEAB) ---
    fra_missing = _missing_states(
        db_path, "facilities_fra",
        "json_extract(metadata_json, '$.stateab')",
        {code: code for code in TARGET_STATES},
    )
    if fra_missing:
        has_data, count = _table_has_data(db_path, "facilities_fra")
        logger.info(
            "Dataset fra: missing states %s (%d existing records), re-ingesting all states...",
            fra_missing, count,
        )
        _run_ingest("fra", _ingest_fra)
    else:
        has_data, count = _table_has_data(db_path, "facilities_fra")
        logger.info("Dataset fra: present for all %d states (%d records), skipping",
                     len(TARGET_STATES), count)

    # --- School Districts (TIGER unified school district boundaries) ---
    sd_missing = _missing_states_fips(db_path, "facilities_school_districts", "geoid")
    if sd_missing:
        has_data, count = _table_has_data(db_path, "facilities_school_districts")
        logger.info(
            "Dataset school_districts: missing states %s (%d existing records), re-ingesting all states...",
            sd_missing, count,
        )
        _run_ingest("school_districts", _ingest_school_districts)
    else:
        has_data, count = _table_has_data(db_path, "facilities_school_districts")
        logger.info("Dataset school_districts: present for all %d states (%d records), skipping",
                     len(TARGET_STATES), count)

    # --- State Education Performance (school district performance metrics, multi-state) ---
    # Each state's education data is checked and ingested independently.
    # Ingest order follows TARGET_STATES; first state creates the table.
    for state_code, ingest_fn in _STATE_EDUCATION_INGEST.items():
        has_data, count = _table_has_state_data(
            db_path, "state_education_performance", state_code,
        )
        if has_data:
            logger.info(
                "Dataset state_education_performance %s: present (%d records), skipping",
                state_code, count,
            )
        else:
            logger.info(
                "Dataset state_education_performance %s: missing, starting ingestion...",
                state_code,
            )
            _run_ingest(f"state_education_performance_{state_code.lower()}", ingest_fn)

    # --- NCES Public Schools (2022-23) ---
    nces_missing = _missing_states_fips(db_path, "facilities_nces_schools", "leaid")
    if nces_missing:
        has_data, count = _table_has_data(db_path, "facilities_nces_schools")
        logger.info(
            "Dataset nces_schools: missing states %s (%d existing records), re-ingesting all states...",
            nces_missing, count,
        )
        _run_ingest("nces_schools", _ingest_nces_schools)
    else:
        has_data, count = _table_has_data(db_path, "facilities_nces_schools")
        logger.info("Dataset nces_schools: present for all %d states (%d records), skipping",
                     len(TARGET_STATES), count)


def _sync_coverage_manifest() -> None:
    """Sync COVERAGE_MANIFEST with actual spatial.db contents (NES-309).

    Called after all ingestion completes. Updates manifest statuses in-place
    so the /coverage page reflects reality without manual edits.
    """
    try:
        from coverage_config import sync_manifest_from_db
        changes = sync_manifest_from_db()
        promoted = changes.get("promoted", [])
        demoted = changes.get("demoted", [])
        if promoted or demoted:
            for desc in promoted:
                logger.info("Coverage manifest promoted: %s", desc)
            for desc in demoted:
                logger.info("Coverage manifest demoted: %s", desc)
            logger.info(
                "Coverage manifest synced: %d promoted, %d demoted",
                len(promoted), len(demoted),
            )
        else:
            logger.info("Coverage manifest: already in sync with spatial.db")
    except Exception:
        logger.warning("Coverage manifest sync failed", exc_info=True)


def _run_ingest(name: str, fn) -> None:
    """Execute an ingestion function with timing and error handling."""
    t0 = time.time()
    try:
        fn()
        elapsed = time.time() - t0
        if elapsed > _INGEST_WARN_SECONDS:
            logger.warning(
                "Dataset %s: ingestion took %.0fs (exceeded %ds threshold)",
                name, elapsed, _INGEST_WARN_SECONDS,
            )
        logger.info("Dataset %s: ingestion complete (%.0fs)", name, elapsed)
    except Exception as e:
        elapsed = time.time() - t0
        logger.error("Dataset %s: ingestion failed (%.0fs): %s", name, elapsed, e)


# Lazy-import wrappers — keep script imports inside the function body so
# a missing dependency in one script doesn't prevent the others from running.

def _ingest_sems():
    from scripts.ingest_sems import ingest as do_ingest
    do_ingest()


def _ingest_fema():
    from scripts.ingest_fema import ingest_metros
    ingest_metros(target_states=list(TARGET_STATES.keys()))


def _ingest_hpms():
    from scripts.ingest_hpms import ingest as do_ingest
    do_ingest(states_filter=list(TARGET_STATES.keys()))


def _ingest_hpms_states(states: list[str]):
    """Ingest HPMS for specific states only (incremental — HPMS supports per-state DELETE+INSERT)."""
    from scripts.ingest_hpms import ingest as do_ingest
    do_ingest(states_filter=states)


def _ingest_ejscreen():
    from scripts.ingest_ejscreen import ingest as do_ingest
    do_ingest(states=list(TARGET_STATES.keys()))


def _ingest_tri():
    from scripts.ingest_tri import ingest as do_ingest
    do_ingest(states=list(TARGET_STATES.keys()))


def _ingest_ust():
    from scripts.ingest_ust import ingest as do_ingest
    do_ingest(states=[v["full_name"] for v in TARGET_STATES.values()])


def _ingest_hifld():
    from scripts.ingest_hifld import ingest as do_ingest
    do_ingest()  # National ingest — no state field available (NES-285)


def _ingest_fra():
    from scripts.ingest_fra import ingest as do_ingest
    do_ingest(states=list(TARGET_STATES.keys()))  # State filter via STATEAB (NES-285)


def _ingest_school_districts():
    from scripts.ingest_school_districts import ingest as do_ingest
    do_ingest(states=[v["fips"] for v in TARGET_STATES.values()])


def _ingest_nysed():
    from scripts.ingest_nysed import ingest as do_ingest
    do_ingest()


def _ingest_nj_performance():
    from scripts.ingest_nj_performance import ingest as do_ingest
    do_ingest()


def _ingest_ct_performance():
    from scripts.ingest_ct_performance import ingest as do_ingest
    do_ingest()


def _ingest_mi_performance():
    from scripts.ingest_mi_performance import ingest as do_ingest
    do_ingest()


def _ingest_ca_performance():
    from scripts.ingest_ca_performance import ingest as do_ingest
    do_ingest()


def _ingest_tx_performance():
    from scripts.ingest_tx_performance import ingest as do_ingest
    do_ingest()


def _ingest_fl_performance():
    from scripts.ingest_fl_performance import ingest as do_ingest
    do_ingest()


def _ingest_il_performance():
    from scripts.ingest_il_performance import ingest as do_ingest
    do_ingest()


def _ingest_nces_schools():
    from scripts.ingest_nces_schools import ingest as do_ingest
    from spatial_data import init_spatial_db, create_facility_table
    init_spatial_db()
    create_facility_table("nces_schools")
    logger.info("Created facilities_nces_schools table")
    for stabr in TARGET_STATES:
        logger.info("Ingesting NCES schools for STABR=%s...", stabr)
        do_ingest(stabr=stabr, _skip_table_create=True)


# Per-state education performance ingest functions. Each entry maps a
# 2-letter state code to its lazy-import wrapper. When adding a new state's
# education data, add an entry here and the corresponding _ingest_* wrapper.
_STATE_EDUCATION_INGEST = {
    "NY": _ingest_nysed,
    "NJ": _ingest_nj_performance,
    "CT": _ingest_ct_performance,
    "MI": _ingest_mi_performance,
    "CA": _ingest_ca_performance,
    "TX": _ingest_tx_performance,
    "FL": _ingest_fl_performance,
    "IL": _ingest_il_performance,
}
