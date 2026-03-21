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
