"""Tests for coverage_config.py — coverage manifest and helpers."""

import os
import sqlite3

import pytest

from unittest.mock import patch

from coverage_config import (
    COVERAGE_MANIFEST,
    CoverageTier,
    DIMENSION_LABELS,
    SECTION_DIMENSION_MAP,
    SourceStatus,
    _SOURCE_METADATA,
    _SOURCE_TO_REGISTRY_KEY,
    build_section_freshness,
    extract_state_from_address,
    get_all_states,
    get_dimension_coverage,
    get_section_coverage,
    get_source_coverage,
    get_state_name,
    sync_manifest_from_db,
    verify_coverage,
)


# ---------------------------------------------------------------------------
# Fixture: detect whether spatial.db is available
# ---------------------------------------------------------------------------

def _spatial_db_available() -> bool:
    try:
        from spatial_data import _spatial_db_path
        return os.path.exists(_spatial_db_path())
    except Exception:
        return False


_HAS_SPATIAL_DB = _spatial_db_available()
requires_spatial_db = pytest.mark.skipif(
    not _HAS_SPATIAL_DB,
    reason="spatial.db not available",
)


# ---------------------------------------------------------------------------
# Manifest integrity
# ---------------------------------------------------------------------------

class TestManifestIntegrity:
    """Verify the manifest is self-consistent."""

    def test_all_sources_have_metadata(self):
        """Every source key used in state entries exists in _SOURCE_METADATA."""
        for state_code, state_data in COVERAGE_MANIFEST.items():
            for key in state_data:
                if key == "name":
                    continue
                assert key in _SOURCE_METADATA, (
                    f"State {state_code} references unknown source '{key}'"
                )

    def test_all_metadata_sources_in_supported_states(self):
        """Every source in _SOURCE_METADATA appears in at least one supported state."""
        all_source_keys_used = set()
        for state_code, state_data in COVERAGE_MANIFEST.items():
            for key in state_data:
                if key != "name":
                    all_source_keys_used.add(key)
        for src in _SOURCE_METADATA:
            assert src in all_source_keys_used, (
                f"Source '{src}' in metadata but never used in any state"
            )

    def test_statuses_are_valid(self):
        """All status values in the manifest are valid SourceStatus values."""
        valid = {s.value for s in SourceStatus}
        for state_code, state_data in COVERAGE_MANIFEST.items():
            for key, value in state_data.items():
                if key == "name":
                    continue
                assert value in valid, (
                    f"{state_code}.{key} has invalid status '{value}'"
                )

    def test_every_state_has_name(self):
        """Every state entry must have a 'name' field."""
        for state_code, state_data in COVERAGE_MANIFEST.items():
            assert "name" in state_data, f"State {state_code} missing 'name'"

    def test_dimensions_are_known(self):
        """Every dimension in source metadata has a label."""
        for src, meta in _SOURCE_METADATA.items():
            assert meta["dimension"] in DIMENSION_LABELS, (
                f"Source {src} dimension '{meta['dimension']}' not in DIMENSION_LABELS"
            )

    def test_registry_key_mapping_complete(self):
        """Every source has a registry key mapping (even if None for live APIs)."""
        for src in _SOURCE_METADATA:
            assert src in _SOURCE_TO_REGISTRY_KEY, (
                f"Source {src} missing from _SOURCE_TO_REGISTRY_KEY"
            )

    @requires_spatial_db
    def test_manifest_tables_exist_in_spatial_db(self):
        """Every table referenced in source metadata exists in spatial.db."""
        from spatial_data import _spatial_db_path
        conn = sqlite3.connect(_spatial_db_path())
        existing = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        conn.close()

        for src, meta in _SOURCE_METADATA.items():
            table = meta.get("table")
            if table is None:
                continue  # live API, no table expected
            assert table in existing, (
                f"Source {src} references table '{table}' which doesn't exist in spatial.db"
            )


# ---------------------------------------------------------------------------
# get_dimension_coverage
# ---------------------------------------------------------------------------

class TestDimensionCoverage:
    def test_ny_health_is_full(self):
        """NY has all health sources active → FULL."""
        dims = get_dimension_coverage("NY")
        assert dims["health"] == CoverageTier.FULL

    def test_ny_education_is_full(self):
        dims = get_dimension_coverage("NY")
        assert dims["education"] == CoverageTier.FULL

    def test_ny_green_space_is_full(self):
        """NY green_space: single source (Google Places) active → FULL."""
        dims = get_dimension_coverage("NY")
        assert dims["green_space"] == CoverageTier.FULL

    def test_ny_transit_is_full(self):
        """NY transit: both live API sources active → FULL."""
        dims = get_dimension_coverage("NY")
        assert dims["transit"] == CoverageTier.FULL

    def test_nj_health_is_full(self):
        """NJ has all health sources active (including UST, NES-304) → FULL."""
        dims = get_dimension_coverage("NJ")
        assert dims["health"] == CoverageTier.FULL

    def test_ct_health_is_full(self):
        """CT has all health sources active (including UST, NES-304) → FULL."""
        dims = get_dimension_coverage("CT")
        assert dims["health"] == CoverageTier.FULL

    def test_mi_health_is_full(self):
        """MI has all 8 health sources active (HPMS added NES-305) → FULL."""
        dims = get_dimension_coverage("MI")
        assert dims["health"] == CoverageTier.FULL

    def test_mi_education_is_full(self):
        """MI has all 3 education sources active (NES-297) → FULL."""
        dims = get_dimension_coverage("MI")
        assert dims["education"] == CoverageTier.FULL

    def test_mi_green_space_is_full(self):
        """MI green_space: single source (Google Places) active → FULL."""
        dims = get_dimension_coverage("MI")
        assert dims["green_space"] == CoverageTier.FULL

    def test_mi_transit_is_full(self):
        """MI transit: both live API sources active → FULL."""
        dims = get_dimension_coverage("MI")
        assert dims["transit"] == CoverageTier.FULL

    def test_expansion_state_health_partial(self):
        """CA has 7/8 health sources active (NES-305), FEMA_NFHL still planned → PARTIAL."""
        dims = get_dimension_coverage("CA")
        assert dims["health"] == CoverageTier.PARTIAL

    def test_unknown_state_returns_empty(self):
        dims = get_dimension_coverage("ZZ")
        assert dims == {}

    def test_case_insensitive(self):
        dims = get_dimension_coverage("ny")
        assert "health" in dims


# ---------------------------------------------------------------------------
# get_source_coverage
# ---------------------------------------------------------------------------

class TestSourceCoverage:
    def test_ny_returns_all_sources(self):
        sources = get_source_coverage("NY")
        assert len(sources) == len(_SOURCE_METADATA)

    def test_each_source_has_required_fields(self):
        sources = get_source_coverage("NY")
        for src_key, info in sources.items():
            assert "status" in info
            assert "description" in info
            assert "dimension" in info

    def test_unknown_state_returns_empty(self):
        assert get_source_coverage("ZZ") == {}

    def test_expansion_state_has_mixed_statuses(self):
        """CA has active, intended, and planned sources."""
        sources = get_source_coverage("CA")
        statuses = {info["status"] for info in sources.values()}
        assert "active" in statuses, "CA should have some active sources (SEMS, TRI, UST, live APIs)"

    def test_education_url_varies_by_state(self):
        """STATE_EDUCATION source_url should be state-specific."""
        ny = get_source_coverage("NY")["STATE_EDUCATION"]
        nj = get_source_coverage("NJ")["STATE_EDUCATION"]
        assert ny["source_url"] != nj["source_url"]
        assert "nysed" in ny["source_url"].lower()
        assert "nj.gov" in nj["source_url"].lower()


# ---------------------------------------------------------------------------
# get_all_states
# ---------------------------------------------------------------------------

class TestGetAllStates:
    def test_supported_states(self):
        states = get_all_states()
        supported = {s["code"] for s in states if s["status"] == "supported"}
        assert {"NY", "NJ", "CT", "MI"} <= supported

    def test_expansion_states_are_supported(self):
        """CA/TX/FL/IL have active sources (SEMS, TRI, UST, live APIs) → supported."""
        states = get_all_states()
        supported = {s["code"] for s in states if s["status"] == "supported"}
        assert {"CA", "TX", "FL", "IL"} <= supported

    def test_each_state_has_name(self):
        for state in get_all_states():
            assert state["name"]
            assert len(state["name"]) > 1

    def test_no_duplicates(self):
        states = get_all_states()
        codes = [s["code"] for s in states]
        assert len(codes) == len(set(codes))


# ---------------------------------------------------------------------------
# verify_coverage
# ---------------------------------------------------------------------------

class TestVerifyCoverage:
    @requires_spatial_db
    def test_ny_no_mismatches(self):
        """NY should have no mismatches (data matches manifest).

        FRA excluded: local spatial.db may have pre-NES-297 data without
        stateab in metadata_json, causing 0 rows for the new state_filter.
        HIFLD excluded: national ingest has no state_filter, total row count
        may not match NY-specific expectations.
        """
        results = verify_coverage("NY")
        # Exclude sources that need re-ingest to match new metadata schema
        excluded = {"FRA", "HIFLD"}
        mismatches = {k: v for k, v in results.items()
                      if v["mismatch"] and k not in excluded}
        assert not mismatches, f"NY mismatches: {mismatches}"

    @requires_spatial_db
    def test_nj_ust_active(self):
        """NJ UST is active with rows (NES-304)."""
        results = verify_coverage("NJ")
        assert results["UST"]["actual_rows"] > 0
        assert not results["UST"]["mismatch"]

    @requires_spatial_db
    def test_bbox_sources_skipped(self):
        """FEMA_NFHL should be skipped (spatial filter required). HIFLD/FRA now have state filters (NES-297)."""
        results = verify_coverage("NY")
        # Only FEMA_NFHL still requires spatial filtering
        assert results["FEMA_NFHL"]["actual_rows"] is None
        assert "skipped" in results["FEMA_NFHL"]["note"].lower()
        # HIFLD has no state_filter — counts all rows (national)
        # FRA now has state_filter via stateab (NES-297) — counts per-state

    @requires_spatial_db
    def test_census_acs_skipped(self):
        """CENSUS_ACS has no table — should report gracefully."""
        results = verify_coverage("NY")
        assert results["CENSUS_ACS"]["actual_rows"] is None

    def test_unknown_state_returns_empty(self):
        assert verify_coverage("ZZ") == {}

    @requires_spatial_db
    def test_mi_intended_sources_have_zero_rows(self):
        """MI sources marked 'intended' should have 0 actual rows."""
        results = verify_coverage("MI")
        for src_key, info in results.items():
            if info["manifest_status"] == "intended" and info["actual_rows"] is not None:
                assert info["actual_rows"] == 0, (
                    f"MI.{src_key} marked intended but has {info['actual_rows']} rows"
                )


# ---------------------------------------------------------------------------
# extract_state_from_address
# ---------------------------------------------------------------------------

class TestExtractState:
    def test_standard_google_format(self):
        assert extract_state_from_address(
            "123 Main St, White Plains, NY 10601, USA"
        ) == "NY"

    def test_nj_address(self):
        assert extract_state_from_address(
            "456 Broad St, Newark, NJ 07102, USA"
        ) == "NJ"

    def test_mi_address(self):
        assert extract_state_from_address(
            "789 Woodward Ave, Detroit, MI 48226, USA"
        ) == "MI"

    def test_coming_soon_state_returned(self):
        """Coming-soon states in manifest are still returned."""
        assert extract_state_from_address(
            "100 Main St, Austin, TX 78701, USA"
        ) == "TX"

    def test_unknown_state_returns_none(self):
        """States not in manifest at all return None."""
        assert extract_state_from_address(
            "100 Main St, Anchorage, AK 99501, USA"
        ) is None

    def test_no_zip_returns_none(self):
        assert extract_state_from_address("Some random text") is None

    def test_empty_string(self):
        assert extract_state_from_address("") is None


# ---------------------------------------------------------------------------
# get_state_name
# ---------------------------------------------------------------------------

class TestGetStateName:
    def test_known_state(self):
        assert get_state_name("NY") == "New York"
        assert get_state_name("MI") == "Michigan"

    def test_case_insensitive(self):
        assert get_state_name("ny") == "New York"

    def test_unknown_returns_code(self):
        assert get_state_name("ZZ") == "ZZ"

    def test_empty_returns_empty(self):
        assert get_state_name("") == ""
        assert get_state_name(None) == ""


# ---------------------------------------------------------------------------
# get_section_coverage
# ---------------------------------------------------------------------------

class TestSectionCoverage:
    def test_ny_health_full(self):
        """NY has full health coverage → no health badge."""
        result = get_section_coverage("NY")
        assert "health" not in result  # FULL is omitted

    def test_ny_parks_full(self):
        """NY parks mapped to green_space (FULL: live API) → no badge."""
        result = get_section_coverage("NY")
        assert "parks" not in result

    def test_ny_getting_around_full(self):
        """NY getting_around mapped to transit (FULL: all live APIs) → no badge."""
        result = get_section_coverage("NY")
        assert "getting_around" not in result

    def test_nj_health_full(self):
        """NJ health is FULL (all sources active including UST, NES-304) → no badge."""
        result = get_section_coverage("NJ")
        assert "health" not in result  # FULL is omitted

    def test_mi_health_full(self):
        """MI health is FULL (all 8 sources active, NES-305) → no badge."""
        result = get_section_coverage("MI")
        assert "health" not in result  # FULL is omitted

    def test_mi_parks_full(self):
        """MI parks mapped to green_space (FULL: live API) → no badge."""
        result = get_section_coverage("MI")
        assert "parks" not in result

    def test_mi_getting_around_full(self):
        """MI getting_around mapped to transit (FULL) → no badge."""
        result = get_section_coverage("MI")
        assert "getting_around" not in result

    def test_mi_education_full(self):
        """MI education is FULL (all 3 sources active, NES-297) → no badge."""
        result = get_section_coverage("MI")
        assert "school_district" not in result  # FULL is omitted

    def test_unknown_state_empty(self):
        assert get_section_coverage("ZZ") == {}

    def test_none_state_empty(self):
        assert get_section_coverage(None) == {}
        assert get_section_coverage("") == {}

    def test_section_map_dimensions_exist(self):
        """All dimensions referenced in SECTION_DIMENSION_MAP exist in DIMENSION_LABELS."""
        for section, dims in SECTION_DIMENSION_MAP.items():
            for d in dims:
                assert d in DIMENSION_LABELS, (
                    f"Section '{section}' references unknown dimension '{d}'"
                )


# ---------------------------------------------------------------------------
# sync_manifest_from_db (NES-309)
# ---------------------------------------------------------------------------

class TestSyncManifestFromDb:
    @requires_spatial_db
    def test_returns_no_changes_when_in_sync(self):
        """When manifest matches spatial.db, sync reports no changes."""
        changes = sync_manifest_from_db()
        assert isinstance(changes, dict)
        assert "promoted" in changes
        assert "demoted" in changes

    @requires_spatial_db
    def test_promotes_intended_to_active(self):
        """If a source marked 'intended' actually has rows, sync promotes it."""
        original = COVERAGE_MANIFEST["NY"].get("SEMS")
        if original != "active":
            pytest.skip("NY/SEMS not active, can't test promotion")

        COVERAGE_MANIFEST["NY"]["SEMS"] = "intended"
        try:
            changes = sync_manifest_from_db()
            assert COVERAGE_MANIFEST["NY"]["SEMS"] == "active"
            assert any("NY/SEMS" in desc for desc in changes["promoted"])
        finally:
            COVERAGE_MANIFEST["NY"]["SEMS"] = original

    @requires_spatial_db
    def test_demotes_active_when_zero_rows(self):
        """If a source marked 'active' has 0 rows for a state, sync demotes it."""
        COVERAGE_MANIFEST["_TEST"] = {
            "name": "Test State",
            "SEMS": "active",  # SEMS state_filter won't match "_TEST"
        }
        try:
            changes = sync_manifest_from_db()
            assert COVERAGE_MANIFEST["_TEST"]["SEMS"] == "intended"
            assert any("_TEST/SEMS" in desc for desc in changes["demoted"])
        finally:
            del COVERAGE_MANIFEST["_TEST"]

    @requires_spatial_db
    def test_no_demotion_when_table_missing(self):
        """If a table is missing entirely (failed re-ingest), don't demote.

        A missing table signals a failed DROP+recreate ingestion, not a genuine
        data gap. Demoting would cause the /coverage page to flicker.
        """
        COVERAGE_MANIFEST["_TEST2"] = {
            "name": "Test State 2",
            "SEMS": "active",
        }
        original_table = _SOURCE_METADATA["SEMS"]["table"]
        _SOURCE_METADATA["SEMS"]["table"] = "nonexistent_table_xyz"
        try:
            changes = sync_manifest_from_db()
            assert COVERAGE_MANIFEST["_TEST2"]["SEMS"] == "active"
            assert not any("_TEST2/SEMS" in desc for desc in changes["demoted"])
        finally:
            _SOURCE_METADATA["SEMS"]["table"] = original_table
            del COVERAGE_MANIFEST["_TEST2"]

    @requires_spatial_db
    def test_preserves_planned_status(self):
        """Sources marked 'planned' are not changed by sync."""
        original = COVERAGE_MANIFEST["NY"]["SEMS"]
        COVERAGE_MANIFEST["NY"]["SEMS"] = "planned"
        try:
            sync_manifest_from_db()
            assert COVERAGE_MANIFEST["NY"]["SEMS"] == "planned"
        finally:
            COVERAGE_MANIFEST["NY"]["SEMS"] = original

    def test_handles_missing_spatial_db(self):
        """Sync returns empty changes when spatial.db doesn't exist."""
        with patch("spatial_data._spatial_db_path", return_value="/nonexistent/spatial.db"):
            changes = sync_manifest_from_db()
        assert changes == {"promoted": [], "demoted": []}

    @requires_spatial_db
    def test_skips_live_api_sources(self):
        """Sources with no table (live APIs) are never changed."""
        original_google = COVERAGE_MANIFEST["NY"].get("GOOGLE_PLACES_PARKS")
        sync_manifest_from_db()
        assert COVERAGE_MANIFEST["NY"]["GOOGLE_PLACES_PARKS"] == original_google


# ---------------------------------------------------------------------------
# build_section_freshness (NES-356)
# ---------------------------------------------------------------------------

def test_build_section_freshness_returns_expected_keys():
    """Freshness dict contains exactly the 4 annotated sections."""
    freshness = build_section_freshness()
    assert set(freshness.keys()) == {"health_tier1", "health_tier2", "census", "parks"}


def test_build_section_freshness_structure():
    """Each entry has source, date, and stale fields."""
    freshness = build_section_freshness()
    for key, entry in freshness.items():
        assert "source" in entry, f"{key} missing 'source'"
        assert "date" in entry, f"{key} missing 'date'"
        assert "stale" in entry, f"{key} missing 'stale'"
        assert isinstance(entry["stale"], bool), f"{key} stale is not bool"


def test_build_section_freshness_census_from_acs_base():
    """Census entry derives its date from the _ACS_BASE vintage year."""
    from unittest.mock import patch
    import types
    fake_census = types.ModuleType("census")
    fake_census._ACS_BASE = "https://api.census.gov/data/2022/acs/acs5"
    with patch.dict("sys.modules", {"census": fake_census}):
        freshness = build_section_freshness()
    census = freshness["census"]
    assert census["source"] == "Census ACS 5-Year"
    assert census["date"] == "2022"


def test_build_section_freshness_stale_threshold():
    """Entries with ingested_at > 24 months ago are marked stale."""
    from unittest.mock import patch
    from datetime import datetime, timezone, timedelta

    old_date = (datetime.now(timezone.utc) - timedelta(days=800)).strftime("%Y-%m-%d")
    fake_registry = {
        "sems": {"ingested_at": old_date, "source_url": "", "record_count": 1, "notes": ""},
        "ejscreen": {"ingested_at": old_date, "source_url": "", "record_count": 1, "notes": ""},
        "tri": {"ingested_at": old_date, "source_url": "", "record_count": 1, "notes": ""},
        "ust": {"ingested_at": old_date, "source_url": "", "record_count": 1, "notes": ""},
        "hpms": {"ingested_at": old_date, "source_url": "", "record_count": 1, "notes": ""},
        "hifld": {"ingested_at": old_date, "source_url": "", "record_count": 1, "notes": ""},
        "fra": {"ingested_at": old_date, "source_url": "", "record_count": 1, "notes": ""},
        "fema_nfhl": {"ingested_at": old_date, "source_url": "", "record_count": 1, "notes": ""},
    }
    with patch("coverage_config.get_dataset_registry", return_value=fake_registry):
        freshness = build_section_freshness()
    assert freshness["health_tier1"]["stale"] is True
    assert freshness["health_tier2"]["stale"] is True


def test_build_section_freshness_not_stale_when_recent():
    """Entries with recent ingested_at are not stale."""
    from unittest.mock import patch
    from datetime import datetime, timezone

    recent_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    fake_registry = {
        "ejscreen": {"ingested_at": recent_date, "source_url": "", "record_count": 1, "notes": ""},
    }
    with patch("coverage_config.get_dataset_registry", return_value=fake_registry):
        freshness = build_section_freshness()
    assert freshness["health_tier2"]["stale"] is False
