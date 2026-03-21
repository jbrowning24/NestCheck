"""Tests for the empty state copy library (NES-319)."""

import pytest
from copy_library import CopyEntry, COPY_LIBRARY, CHECK_NAME_ALIASES, EVALUATION_FAILURE_COPY, get_copy


class TestCopyEntry:
    def test_frozen(self):
        entry = CopyEntry(what="a", why="b", so_what="c")
        with pytest.raises(AttributeError):
            entry.what = "changed"

    def test_combined(self):
        entry = CopyEntry(what="A.", why="B.", so_what="C.")
        assert entry.combined == "A. B. C."

    def test_fields_required(self):
        with pytest.raises(TypeError):
            CopyEntry(what="a", why="b")  # missing so_what


class TestGetCopy:
    def test_direct_key_hit(self):
        result = get_copy("flood_zone", "F1")
        assert result is not None
        assert isinstance(result, CopyEntry)
        assert result.what  # non-empty string

    def test_alias_resolution(self):
        result = get_copy("Flood zone", "F1")
        direct = get_copy("flood_zone", "F1")
        assert result == direct

    def test_miss_returns_none(self):
        assert get_copy("nonexistent_check", "F1") is None

    def test_wrong_failure_type_returns_none(self):
        assert get_copy("flood_zone", "F99") is None

    def test_ejscreen_alias_all_six(self):
        indicators = [
            "EJScreen PM2.5", "EJScreen cancer risk", "EJScreen diesel PM",
            "EJScreen lead paint", "EJScreen Superfund", "EJScreen hazardous waste",
        ]
        for name in indicators:
            result = get_copy(name, "F1")
            assert result is not None, f"Missing alias for {name}"
            assert result == get_copy("ejscreen", "F1")

    def test_hifld_alias(self):
        assert get_copy("hifld_power_lines", "F1") == get_copy("power_lines", "F1")

    def test_listing_amenity_aliases(self):
        assert get_copy("W/D in unit", "input_missing") is not None
        assert get_copy("Central air", "input_missing") is not None
        assert get_copy("Size", "input_missing") is not None
        assert get_copy("Bedrooms", "input_missing") is not None


class TestInventory:
    def test_total_entry_count(self):
        """42 entries in COPY_LIBRARY + 1 standalone F6 = 43 total per spec."""
        count = sum(len(variants) for variants in COPY_LIBRARY.values())
        assert count == 42

    def test_tier1_check_keys(self):
        tier1_keys = {
            "flood_zone", "ust_proximity", "high_traffic_road", "power_lines",
            "electrical_substation", "cell_tower", "industrial_zone",
            "tri_proximity", "superfund", "rail_proximity", "gas_station", "ejscreen",
        }
        for key in tier1_keys:
            assert key in COPY_LIBRARY, f"Missing Tier 1 key: {key}"
            assert "F1" in COPY_LIBRARY[key], f"{key} missing F1 entry"

    def test_tier2_dimension_keys(self):
        tier2_keys = {
            "coffee_social", "provisioning", "fitness",
            "green_space", "transit", "road_noise",
        }
        for key in tier2_keys:
            assert key in COPY_LIBRARY, f"Missing Tier 2 key: {key}"
            assert "F1" in COPY_LIBRARY[key], f"{key} missing F1 entry"

    def test_input_missing_keys(self):
        input_keys = {"cost", "washer_dryer", "central_air", "square_footage", "bedrooms"}
        for key in input_keys:
            assert key in COPY_LIBRARY, f"Missing input_missing key: {key}"
            assert "input_missing" in COPY_LIBRARY[key], f"{key} missing input_missing entry"

    def test_f6_standalone(self):
        assert EVALUATION_FAILURE_COPY.what
        assert EVALUATION_FAILURE_COPY.why
        assert EVALUATION_FAILURE_COPY.so_what

    def test_all_entries_have_nonempty_fields(self):
        for check_name, variants in COPY_LIBRARY.items():
            for f_type, entry in variants.items():
                assert entry.what, f"{check_name}/{f_type} has empty 'what'"
                assert entry.why, f"{check_name}/{f_type} has empty 'why'"
                assert entry.so_what, f"{check_name}/{f_type} has empty 'so_what'"

    def test_no_alias_targets_missing_key(self):
        """Every alias target must exist in COPY_LIBRARY."""
        for evaluator_name, copy_key in CHECK_NAME_ALIASES.items():
            assert copy_key in COPY_LIBRARY, (
                f"Alias {evaluator_name!r} → {copy_key!r} but {copy_key!r} not in COPY_LIBRARY"
            )

    def test_ejscreen_vintage_placeholder(self):
        """The ejscreen F2 entry must contain the {vintage_year} placeholder."""
        entry = COPY_LIBRARY["ejscreen"]["F2"]
        assert "{vintage_year}" in entry.why
