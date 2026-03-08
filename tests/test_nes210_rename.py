"""Tests for NES-210: Third Place rename + category gap analysis.

Covers _classify_coffee_sub_type() and _migrate_dimension_names().
"""

import pytest

from property_evaluator import _classify_coffee_sub_type
from app import _migrate_dimension_names


# ============================================================================
# _classify_coffee_sub_type
# ============================================================================

class TestClassifyCoffeeSubType:
    """Priority: bakery > cafe > coffee_shop."""

    def test_bakery_only(self):
        assert _classify_coffee_sub_type(["bakery"]) == "bakery"

    def test_cafe_only(self):
        assert _classify_coffee_sub_type(["cafe"]) == "cafe"

    def test_bakery_beats_cafe(self):
        """Google often tags bakeries with 'cafe' too — bakery should win."""
        assert _classify_coffee_sub_type(["cafe", "bakery", "food"]) == "bakery"

    def test_cafe_beats_coffee_shop(self):
        assert _classify_coffee_sub_type(["coffee_shop", "cafe"]) == "cafe"

    def test_coffee_shop_fallback(self):
        assert _classify_coffee_sub_type(["coffee_shop"]) == "coffee_shop"

    def test_empty_types(self):
        """No recognized type defaults to coffee_shop."""
        assert _classify_coffee_sub_type([]) == "coffee_shop"

    def test_unrelated_types(self):
        """Types with no cafe/bakery/coffee_shop default to coffee_shop."""
        assert _classify_coffee_sub_type(["restaurant", "food"]) == "coffee_shop"


# ============================================================================
# _migrate_dimension_names
# ============================================================================

class TestMigrateDimensionNames:
    """Remap legacy 'Third Place' to 'Coffee & Social Spots' in snapshot dicts."""

    def test_migrates_tier2_scores(self):
        result = {
            "tier2_scores": [
                {"name": "Third Place", "points": 7, "max": 10},
                {"name": "Road Noise", "points": 5, "max": 10},
            ]
        }
        _migrate_dimension_names(result)
        assert result["tier2_scores"][0]["name"] == "Coffee & Social Spots"
        assert result["tier2_scores"][1]["name"] == "Road Noise"  # unchanged

    def test_migrates_dimension_summaries(self):
        result = {
            "dimension_summaries": [
                {"name": "Third Place", "score": 7},
            ]
        }
        _migrate_dimension_names(result)
        assert result["dimension_summaries"][0]["name"] == "Coffee & Social Spots"

    def test_no_op_for_current_name(self):
        result = {
            "tier2_scores": [
                {"name": "Coffee & Social Spots", "points": 7, "max": 10},
            ]
        }
        _migrate_dimension_names(result)
        assert result["tier2_scores"][0]["name"] == "Coffee & Social Spots"

    def test_handles_empty_result(self):
        """Gracefully handles missing keys."""
        result = {}
        _migrate_dimension_names(result)
        assert result == {}

    def test_handles_missing_name(self):
        result = {"tier2_scores": [{"points": 5}]}
        _migrate_dimension_names(result)
        assert result["tier2_scores"][0] == {"points": 5}
