"""Tests for curated list pages and supporting helpers."""

import json
import pytest
from app import _prepare_snapshot_for_display


def _make_minimal_result():
    """Build a minimal result dict matching snapshot structure."""
    return {
        "address": "123 Test St, Testville, NY 10000",
        "coordinates": {"lat": 41.0, "lng": -73.7},
        "tier1_checks": [],
        "tier2_scores": [],
        "dimension_summaries": [],
        "neighborhood_places": {
            "coffee": [{"name": "Bean Co", "walk_time_min": 5, "rating": 4.5}],
            "grocery": [],
            "fitness": [],
        },
        "final_score": 72,
        "passed_tier1": True,
        "score_band": {"label": "Strong", "css_class": "band-strong"},
        "verdict": "Strong",
    }


class TestPrepareSnapshotForDisplay:
    def test_adds_presented_checks_when_missing(self):
        result = _make_minimal_result()
        assert "presented_checks" not in result
        _prepare_snapshot_for_display(result)
        assert "presented_checks" in result

    def test_idempotent(self):
        """Running the pipeline twice produces identical output."""
        result = _make_minimal_result()
        _prepare_snapshot_for_display(result)
        first_pass = json.dumps(result, sort_keys=True, default=str)

        _prepare_snapshot_for_display(result)
        second_pass = json.dumps(result, sort_keys=True, default=str)

        assert first_pass == second_pass

    def test_adds_neighborhood_summary(self):
        result = _make_minimal_result()
        _prepare_snapshot_for_display(result)
        assert "neighborhood_summary" in result
        assert result["neighborhood_summary"]["coffee_count"] == 1

    def test_adds_show_numeric_score(self):
        result = _make_minimal_result()
        _prepare_snapshot_for_display(result)
        assert "show_numeric_score" in result
