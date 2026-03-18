"""Tests for coverage_config.py — coverage manifest and helpers."""

import os
import sqlite3

import pytest

from coverage_config import (
    COVERAGE_MANIFEST,
    CoverageTier,
    DIMENSION_LABELS,
    SECTION_DIMENSION_MAP,
    SourceStatus,
    _SOURCE_METADATA,
    _SOURCE_TO_REGISTRY_KEY,
    extract_state_from_address,
    get_all_states,
    get_dimension_coverage,
    get_section_coverage,
    get_source_coverage,
    get_state_name,
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

    def test_nj_health_is_partial(self):
        """NJ has UST intended → not all active → PARTIAL."""
        dims = get_dimension_coverage("NJ")
        assert dims["health"] == CoverageTier.PARTIAL

    def test_ct_health_is_partial(self):
        """CT has UST intended → PARTIAL."""
        dims = get_dimension_coverage("CT")
        assert dims["health"] == CoverageTier.PARTIAL

    def test_mi_health_is_minimal(self):
        """MI has only SEMS active for health → MINIMAL."""
        dims = get_dimension_coverage("MI")
        assert dims["health"] == CoverageTier.MINIMAL

    def test_mi_education_is_minimal(self):
        """MI has STATE_EDUCATION active but SCHOOL_DISTRICTS and NCES intended → MINIMAL."""
        dims = get_dimension_coverage("MI")
        assert dims["education"] == CoverageTier.MINIMAL

    def test_mi_green_space_is_full(self):
        """MI green_space: single source (Google Places) active → FULL."""
        dims = get_dimension_coverage("MI")
        assert dims["green_space"] == CoverageTier.FULL

    def test_mi_transit_is_full(self):
        """MI transit: both live API sources active → FULL."""
        dims = get_dimension_coverage("MI")
        assert dims["transit"] == CoverageTier.FULL

    def test_coming_soon_state_all_none(self):
        """CA (coming soon) has no active sources → all NONE."""
        dims = get_dimension_coverage("CA")
        for dim, tier in dims.items():
            assert tier == CoverageTier.NONE, (
                f"CA dimension '{dim}' should be NONE, got {tier}"
            )

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

    def test_coming_soon_state_all_planned(self):
        """CA only has a name, so all sources default to 'planned'."""
        sources = get_source_coverage("CA")
        for src_key, info in sources.items():
            assert info["status"] == "planned", (
                f"CA.{src_key} should be 'planned', got '{info['status']}'"
            )

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

    def test_coming_soon_states(self):
        states = get_all_states()
        coming = {s["code"] for s in states if s["status"] == "coming_soon"}
        assert {"CA", "TX", "FL", "IL"} <= coming

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
        """NY should have no mismatches (data matches manifest)."""
        results = verify_coverage("NY")
        mismatches = {k: v for k, v in results.items() if v["mismatch"]}
        assert not mismatches, f"NY mismatches: {mismatches}"

    @requires_spatial_db
    def test_nj_ust_intended(self):
        """NJ UST is intended (0 rows) — should not be a mismatch."""
        results = verify_coverage("NJ")
        assert results["UST"]["actual_rows"] == 0
        assert not results["UST"]["mismatch"]

    @requires_spatial_db
    def test_bbox_sources_skipped(self):
        """HIFLD/FRA/FEMA should be skipped (spatial filter required)."""
        results = verify_coverage("NY")
        for src in ("HIFLD", "FRA", "FEMA_NFHL"):
            assert results[src]["actual_rows"] is None
            assert "skipped" in results[src]["note"].lower()

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

    def test_nj_health_partial(self):
        """NJ health is PARTIAL (UST intended) → badge appears."""
        result = get_section_coverage("NJ")
        assert result.get("health") == "partial"

    def test_mi_health_minimal(self):
        """MI health is MINIMAL → badge appears as 'minimal'."""
        result = get_section_coverage("MI")
        assert result.get("health") == "minimal"

    def test_mi_parks_full(self):
        """MI parks mapped to green_space (FULL: live API) → no badge."""
        result = get_section_coverage("MI")
        assert "parks" not in result

    def test_mi_getting_around_full(self):
        """MI getting_around mapped to transit (FULL) → no badge."""
        result = get_section_coverage("MI")
        assert "getting_around" not in result

    def test_mi_education_minimal(self):
        result = get_section_coverage("MI")
        assert result.get("school_district") == "minimal"

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
