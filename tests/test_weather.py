"""Unit tests for weather.py — climate normals aggregation and thresholds.

Tests cover: coordinate rounding, daily data aggregation, threshold evaluation,
serialization round-trips, and the public get_weather_summary API.
"""

import json
from unittest.mock import patch, MagicMock

import pytest

from weather import (
    _round_coords,
    _aggregate,
    check_thresholds,
    _serialize,
    _deserialize,
    serialize_for_result,
    get_weather_summary,
    WeatherSummary,
    MonthlyNormals,
    WEATHER_THRESHOLDS,
)


# =========================================================================
# Coordinate rounding
# =========================================================================

class TestRoundCoords:
    def test_rounds_to_2_decimals(self):
        assert _round_coords(41.12345, -73.98765) == "41.12,-73.99"

    def test_negative_coords(self):
        assert _round_coords(-33.8688, 151.2093) == "-33.87,151.21"

    def test_exact_values(self):
        assert _round_coords(41.00, -73.00) == "41.00,-73.00"


# =========================================================================
# Aggregation
# =========================================================================

def _make_daily_data(num_days=365, high=70.0, low=50.0, precip=0.05, snow=0.0):
    """Helper: generate synthetic daily weather data for aggregation tests."""
    dates = []
    highs = []
    lows = []
    precips = []
    snows = []

    # Generate dates for a single year
    for d in range(num_days):
        month = (d // 30) % 12 + 1
        day = (d % 30) + 1
        dates.append(f"2023-{month:02d}-{min(day, 28):02d}")
        highs.append(high)
        lows.append(low)
        precips.append(precip)
        snows.append(snow)

    return {
        "daily": {
            "time": dates,
            "temperature_2m_max": highs,
            "temperature_2m_min": lows,
            "precipitation_sum": precips,
            "snowfall_sum": snows,
        }
    }


class TestAggregate:
    def test_basic_aggregation(self):
        raw = _make_daily_data(num_days=365, high=75.0, low=55.0, precip=0.0, snow=0.0)
        summary = _aggregate(raw)

        assert summary is not None
        assert summary.annual_avg_high_f == pytest.approx(75.0, abs=1)
        assert summary.annual_avg_low_f == pytest.approx(55.0, abs=1)
        assert len(summary.monthly) == 12

    def test_snow_days_counted(self):
        raw = _make_daily_data(num_days=365, high=30.0, low=20.0, precip=0.5, snow=2.0)
        summary = _aggregate(raw)

        assert summary.annual_snow_days > 0
        assert summary.annual_snowfall_in > 0

    def test_extreme_heat_counted(self):
        raw = _make_daily_data(num_days=365, high=95.0, low=75.0)
        summary = _aggregate(raw)

        assert summary.extreme_heat_days > 0

    def test_freezing_days_counted(self):
        raw = _make_daily_data(num_days=365, high=25.0, low=10.0)
        summary = _aggregate(raw)

        assert summary.freezing_days > 0

    def test_missing_daily_returns_none(self):
        assert _aggregate({}) is None
        assert _aggregate({"daily": None}) is None

    def test_empty_dates_returns_none(self):
        assert _aggregate({"daily": {"time": []}}) is None

    def test_mismatched_lengths_returns_none(self):
        raw = {
            "daily": {
                "time": ["2023-01-01"],
                "temperature_2m_max": [],
                "temperature_2m_min": [],
                "precipitation_sum": [],
                "snowfall_sum": [],
            }
        }
        assert _aggregate(raw) is None

    def test_none_values_skipped(self):
        raw = {
            "daily": {
                "time": ["2023-01-01", "2023-01-02", "2023-01-03"],
                "temperature_2m_max": [70.0, None, 72.0],
                "temperature_2m_min": [50.0, None, 52.0],
                "precipitation_sum": [0.0, None, 0.0],
                "snowfall_sum": [0.0, None, 0.0],
            }
        }
        summary = _aggregate(raw)
        assert summary is not None
        # Should still produce results from the non-None days
        assert summary.annual_avg_high_f > 0


# =========================================================================
# Threshold evaluation
# =========================================================================

class TestCheckThresholds:
    def _make_summary(self, **kwargs):
        defaults = {
            "annual_avg_high_f": 60.0,
            "annual_avg_low_f": 40.0,
            "annual_precip_days": 100.0,
            "annual_snow_days": 5.0,
            "annual_snowfall_in": 5.0,
            "extreme_heat_days": 10.0,
            "freezing_days": 10.0,
        }
        defaults.update(kwargs)
        return WeatherSummary(**defaults)

    def test_no_triggers(self):
        s = self._make_summary()
        check_thresholds(s)
        assert s.triggers == []

    def test_snow_by_snowfall(self):
        s = self._make_summary(annual_snowfall_in=20.0)
        check_thresholds(s)
        assert "snow" in s.triggers

    def test_snow_by_snow_days(self):
        s = self._make_summary(annual_snow_days=15.0, annual_snowfall_in=5.0)
        check_thresholds(s)
        assert "snow" in s.triggers

    def test_extreme_heat(self):
        s = self._make_summary(extreme_heat_days=40.0)
        check_thresholds(s)
        assert "extreme_heat" in s.triggers

    def test_freezing(self):
        s = self._make_summary(freezing_days=40.0)
        check_thresholds(s)
        assert "freezing" in s.triggers

    def test_rain(self):
        s = self._make_summary(annual_precip_days=160.0)
        check_thresholds(s)
        assert "rain" in s.triggers

    def test_multiple_triggers(self):
        s = self._make_summary(
            annual_snowfall_in=20.0,
            extreme_heat_days=40.0,
            freezing_days=40.0,
            annual_precip_days=160.0,
        )
        check_thresholds(s)
        assert set(s.triggers) == {"snow", "extreme_heat", "freezing", "rain"}

    def test_returns_same_summary(self):
        s = self._make_summary()
        result = check_thresholds(s)
        assert result is s


# =========================================================================
# Serialization
# =========================================================================

class TestSerialization:
    def _make_full_summary(self):
        monthly = [
            MonthlyNormals(month=m, avg_high_f=60.0, avg_low_f=40.0,
                           avg_precip_days=10.0, avg_snow_days=1.0, avg_snowfall_in=2.0)
            for m in range(1, 13)
        ]
        return WeatherSummary(
            annual_avg_high_f=60.0,
            annual_avg_low_f=40.0,
            annual_precip_days=120.0,
            annual_snow_days=12.0,
            annual_snowfall_in=24.0,
            extreme_heat_days=15.0,
            freezing_days=20.0,
            monthly=monthly,
            triggers=["snow"],
        )

    def test_round_trip(self):
        original = self._make_full_summary()
        serialized = _serialize(original)
        restored = _deserialize(serialized)

        assert restored.annual_avg_high_f == original.annual_avg_high_f
        assert restored.annual_snowfall_in == original.annual_snowfall_in
        assert restored.triggers == ["snow"]
        assert len(restored.monthly) == 12
        assert restored.monthly[0].month == 1

    def test_json_round_trip(self):
        original = self._make_full_summary()
        json_str = json.dumps(_serialize(original))
        restored = _deserialize(json.loads(json_str))
        assert restored.annual_avg_high_f == original.annual_avg_high_f

    def test_serialize_for_result_with_summary(self):
        s = self._make_full_summary()
        result = serialize_for_result(s)
        assert result is not None
        assert "annual_avg_high_f" in result
        assert "monthly" in result

    def test_serialize_for_result_none(self):
        assert serialize_for_result(None) is None


# =========================================================================
# Public API (get_weather_summary)
# =========================================================================

class TestGetWeatherSummary:
    @patch("weather.get_weather_cache", return_value=None)
    @patch("weather.set_weather_cache")
    @patch("weather._fetch_daily_data")
    def test_cache_miss_fetches_and_caches(self, mock_fetch, mock_set_cache, mock_get_cache):
        raw = _make_daily_data(num_days=365, high=70.0, low=50.0)
        mock_fetch.return_value = raw

        result = get_weather_summary(41.0, -73.0)

        assert result is not None
        assert result.annual_avg_high_f > 0
        mock_fetch.assert_called_once()
        mock_set_cache.assert_called_once()

    @patch("weather.get_weather_cache")
    def test_cache_hit_skips_fetch(self, mock_get_cache):
        cached = json.dumps({
            "annual_avg_high_f": 65.0,
            "annual_avg_low_f": 45.0,
            "annual_precip_days": 100.0,
            "annual_snow_days": 5.0,
            "annual_snowfall_in": 10.0,
            "extreme_heat_days": 10.0,
            "freezing_days": 15.0,
            "triggers": ["snow"],
            "monthly": [],
        })
        mock_get_cache.return_value = cached

        result = get_weather_summary(41.0, -73.0)

        assert result is not None
        assert result.annual_avg_high_f == 65.0
        assert result.triggers == ["snow"]

    @patch("weather.get_weather_cache", return_value=None)
    @patch("weather._fetch_daily_data", return_value=None)
    def test_fetch_failure_returns_none(self, mock_fetch, mock_get_cache):
        result = get_weather_summary(41.0, -73.0)
        assert result is None
