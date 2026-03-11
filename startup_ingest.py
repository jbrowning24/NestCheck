"""
Startup spatial data ingestion for NestCheck.

Called during gunicorn post_fork to ensure spatial datasets (SEMS, FEMA, HPMS,
EJScreen, TRI, UST, HIFLD, FRA, School Districts, NYSED, NCES) are populated before
the evaluation worker starts processing jobs. Uses a
file-based lock (fcntl) to prevent concurrent ingestion from multiple workers.

Datasets are checked in order and ingested independently — a failure in one
never blocks the others or crashes the worker.

Geographic scope: NY + CT + NJ (tri-state). State-filtered datasets use
multi-state IN clauses; bbox-filtered datasets use (-75.6, 38.9, -71.8, 42.1).
"""

import fcntl
import logging
import os
import sqlite3
import threading
import time

from spatial_data import _spatial_db_path

import re

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

    # --- FEMA NFHL (flood zones, tri-state) ---
    has_data, count = _table_has_data(db_path, "facilities_fema_nfhl")
    if has_data:
        logger.info("Dataset fema_nfhl: present (%d records), skipping", count)
    else:
        logger.info("Dataset fema_nfhl: missing or empty, starting ingestion...")
        _run_ingest("fema_nfhl", _ingest_fema)

    # --- HPMS (high-traffic roads, tri-state) ---
    has_data, count = _table_has_data(db_path, "facilities_hpms")
    if has_data:
        logger.info("Dataset hpms: present (%d records), skipping", count)
    else:
        logger.info("Dataset hpms: missing or empty, starting ingestion...")
        _run_ingest("hpms", _ingest_hpms)

    # --- EJScreen (EPA environmental justice block groups, NY+CT+NJ) ---
    has_data, count = _table_has_data(db_path, "facilities_ejscreen")
    if has_data:
        logger.info("Dataset ejscreen: present (%d records), skipping", count)
    else:
        logger.info("Dataset ejscreen: missing or empty, starting ingestion...")
        _run_ingest("ejscreen", _ingest_ejscreen)

    # --- TRI (EPA Toxic Release Inventory, NY+CT+NJ) ---
    has_data, count = _table_has_data(db_path, "facilities_tri")
    if has_data:
        logger.info("Dataset tri: present (%d records), skipping", count)
    else:
        logger.info("Dataset tri: missing or empty, starting ingestion...")
        _run_ingest("tri", _ingest_tri)

    # --- UST (EPA Underground Storage Tanks, NY+CT+NJ) ---
    has_data, count = _table_has_data(db_path, "facilities_ust")
    if has_data:
        logger.info("Dataset ust: present (%d records), skipping", count)
    else:
        logger.info("Dataset ust: missing or empty, starting ingestion...")
        _run_ingest("ust", _ingest_ust)

    # --- HIFLD (electric power transmission lines, tri-state bbox) ---
    has_data, count = _table_has_data(db_path, "facilities_hifld")
    if has_data:
        logger.info("Dataset hifld: present (%d records), skipping", count)
    else:
        logger.info("Dataset hifld: missing or empty, starting ingestion...")
        _run_ingest("hifld", _ingest_hifld)

    # --- FRA (rail network lines, tri-state bbox) ---
    has_data, count = _table_has_data(db_path, "facilities_fra")
    if has_data:
        logger.info("Dataset fra: present (%d records), skipping", count)
    else:
        logger.info("Dataset fra: missing or empty, starting ingestion...")
        _run_ingest("fra", _ingest_fra)

    # --- School Districts (TIGER unified school district boundaries, NY+CT+NJ) ---
    has_data, count = _table_has_data(db_path, "facilities_school_districts")
    if has_data:
        logger.info("Dataset school_districts: present (%d records), skipping", count)
    else:
        logger.info("Dataset school_districts: missing or empty, starting ingestion...")
        _run_ingest("school_districts", _ingest_school_districts)

    # --- State Education Performance (school district performance metrics, multi-state) ---
    # NY (NYSED) — creates the table and loads NY data
    has_ny, ny_count = _table_has_state_data(db_path, "state_education_performance", "NY")
    if has_ny:
        logger.info("Dataset state_education_performance NY: present (%d records), skipping", ny_count)
    else:
        logger.info("Dataset state_education_performance NY: missing, starting ingestion...")
        _run_ingest("state_education_performance_ny", _ingest_nysed)

    # NJ — appends NJ data (table must exist from NYSED step or NJ creates it)
    has_nj, nj_count = _table_has_state_data(db_path, "state_education_performance", "NJ")
    if has_nj:
        logger.info("Dataset state_education_performance NJ: present (%d records), skipping", nj_count)
    else:
        logger.info("Dataset state_education_performance NJ: missing, starting ingestion...")
        _run_ingest("state_education_performance_nj", _ingest_nj_performance)

    # CT — appends CT data
    has_ct, ct_count = _table_has_state_data(db_path, "state_education_performance", "CT")
    if has_ct:
        logger.info("Dataset state_education_performance CT: present (%d records), skipping", ct_count)
    else:
        logger.info("Dataset state_education_performance CT: missing, starting ingestion...")
        _run_ingest("state_education_performance_ct", _ingest_ct_performance)

    # --- NCES Public Schools (2022-23, tri-state) ---
    has_data, count = _table_has_data(db_path, "facilities_nces_schools")
    if has_data:
        logger.info("Dataset nces_schools: present (%d records), skipping", count)
    else:
        logger.info("Dataset nces_schools: missing or empty, starting ingestion...")
        _run_ingest("nces_schools", _ingest_nces_schools)


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
    from scripts.ingest_fema import ingest as do_ingest
    do_ingest(bbox=(-75.6, 38.9, -71.8, 42.1))


def _ingest_hpms():
    from scripts.ingest_hpms import ingest as do_ingest
    do_ingest(states_filter=["NY", "NJ", "CT"])


def _ingest_ejscreen():
    from scripts.ingest_ejscreen import ingest as do_ingest
    do_ingest(states=["NY", "CT", "NJ"])


def _ingest_tri():
    from scripts.ingest_tri import ingest as do_ingest
    do_ingest(states=["NY", "CT", "NJ"])


def _ingest_ust():
    from scripts.ingest_ust import ingest as do_ingest
    do_ingest(states=["New York", "Connecticut", "New Jersey"])


def _ingest_hifld():
    from scripts.ingest_hifld import ingest as do_ingest
    do_ingest(bbox="-75.6,38.9,-71.8,42.1")


def _ingest_fra():
    from scripts.ingest_fra import ingest as do_ingest
    do_ingest(bbox="-75.6,38.9,-71.8,42.1", us_only=True)


def _ingest_school_districts():
    from scripts.ingest_school_districts import ingest as do_ingest
    do_ingest(states=["36", "09", "34"])


def _ingest_nysed():
    from scripts.ingest_nysed import ingest as do_ingest
    do_ingest()


def _ingest_nj_performance():
    from scripts.ingest_nj_performance import ingest as do_ingest
    do_ingest()


def _ingest_ct_performance():
    from scripts.ingest_ct_performance import ingest as do_ingest
    do_ingest()


def _ingest_nces_schools():
    from scripts.ingest_nces_schools import ingest as do_ingest
    _TRI_STATE_BBOX = "-75.6,38.9,-71.8,42.1"
    _STABR_CODES = ["NY", "CT", "NJ"]
    from spatial_data import init_spatial_db, create_facility_table
    init_spatial_db()
    create_facility_table("nces_schools")
    logger.info("Created facilities_nces_schools table")
    for stabr in _STABR_CODES:
        logger.info("Ingesting NCES schools for STABR=%s...", stabr)
        do_ingest(bbox=_TRI_STATE_BBOX, stabr=stabr, _skip_table_create=True)
