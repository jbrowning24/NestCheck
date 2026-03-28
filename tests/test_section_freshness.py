"""Tests for get_section_freshness() in coverage_config.py."""

import time
from datetime import datetime, timezone
from unittest.mock import patch

from coverage_config import get_section_freshness, _format_freshness_date


class TestFormatFreshnessDate:
    """Test ISO timestamp → 'Month YYYY' formatting."""

    def test_basic_utc_timestamp(self):
        assert _format_freshness_date("2026-01-15T10:30:00+00:00") == "January 2026"

    def test_different_month(self):
        assert _format_freshness_date("2025-11-03T08:00:00+00:00") == "November 2025"

    def test_none_returns_none(self):
        assert _format_freshness_date(None) is None

    def test_malformed_returns_none(self):
        assert _format_freshness_date("not-a-date") is None


class TestGetSectionFreshness:
    """Test section freshness dict construction."""

    def _make_registry(self, entries: dict) -> dict:
        """Build a fake registry dict. entries: {facility_type: iso_timestamp}."""
        return {
            ft: {"ingested_at": ts, "source_url": "", "record_count": 0, "notes": ""}
            for ft, ts in entries.items()
        }

    @patch("coverage_config.get_dataset_registry")
    def test_health_tier1_returns_oldest_date(self, mock_reg):
        mock_reg.return_value = self._make_registry({
            "tri": "2026-03-01T00:00:00+00:00",
            "fema_nfhl": "2025-12-15T00:00:00+00:00",
            "hifld": "2026-02-01T00:00:00+00:00",
            "hpms": "2026-01-10T00:00:00+00:00",
            "ust": "2026-03-05T00:00:00+00:00",
            "sems": "2026-02-20T00:00:00+00:00",
            "fra": "2026-01-25T00:00:00+00:00",
        })
        get_section_freshness.cache_clear()
        result = get_section_freshness()
        assert result["health_tier1"]["date"] == "December 2025"
        assert "source" in result["health_tier1"]

    @patch("coverage_config.get_dataset_registry")
    def test_health_tier2_returns_ejscreen_date(self, mock_reg):
        mock_reg.return_value = self._make_registry({
            "ejscreen": "2026-02-10T00:00:00+00:00",
        })
        get_section_freshness.cache_clear()
        result = get_section_freshness()
        assert result["health_tier2"]["date"] == "February 2026"

    @patch("coverage_config.get_dataset_registry")
    def test_area_context_uses_acs_vintage(self, mock_reg):
        mock_reg.return_value = self._make_registry({})
        get_section_freshness.cache_clear()
        result = get_section_freshness()
        assert result["area_context"]["date"] == "2022"
        assert "ACS" in result["area_context"]["source"]

    @patch("coverage_config.get_dataset_registry")
    def test_parks_absent_when_no_parkserve(self, mock_reg):
        mock_reg.return_value = self._make_registry({})
        get_section_freshness.cache_clear()
        result = get_section_freshness()
        assert "parks" not in result

    @patch("coverage_config.get_dataset_registry")
    def test_getting_around_absent(self, mock_reg):
        mock_reg.return_value = self._make_registry({
            "tri": "2026-01-01T00:00:00+00:00",
        })
        get_section_freshness.cache_clear()
        result = get_section_freshness()
        assert "getting_around" not in result

    @patch("coverage_config.get_dataset_registry")
    def test_empty_registry_returns_empty_dict(self, mock_reg):
        mock_reg.return_value = {}
        get_section_freshness.cache_clear()
        result = get_section_freshness()
        assert "area_context" in result
        assert "health_tier1" not in result
        assert "health_tier2" not in result

    @patch("coverage_config.get_dataset_registry")
    def test_cache_returns_same_result(self, mock_reg):
        mock_reg.return_value = self._make_registry({
            "ejscreen": "2026-01-01T00:00:00+00:00",
        })
        get_section_freshness.cache_clear()
        r1 = get_section_freshness()
        mock_reg.return_value = self._make_registry({})
        r2 = get_section_freshness()
        assert r1 == r2
        assert mock_reg.call_count == 1

    @patch("coverage_config.get_dataset_registry")
    def test_partial_health_tier1_sources(self, mock_reg):
        mock_reg.return_value = self._make_registry({
            "tri": "2026-03-01T00:00:00+00:00",
            "hifld": "2026-01-15T00:00:00+00:00",
        })
        get_section_freshness.cache_clear()
        result = get_section_freshness()
        assert result["health_tier1"]["date"] == "January 2026"
