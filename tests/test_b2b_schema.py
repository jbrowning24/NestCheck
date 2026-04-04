"""Tests for B2B curated response schema builder."""
import pytest


def _make_snapshot_result():
    """Minimal snapshot result dict that mirrors result_to_dict() output."""
    return {
        "address": "123 Main St, White Plains, NY 10601",
        "coordinates": {"lat": 41.033, "lng": -73.763},
        "walk_scores": {"walk_score": 82, "transit_score": 55, "bike_score": 60},
        "composite_score": 7,
        "composite_band": "Strong",
        "data_confidence": "verified",
        "tier2_scores": {
            "walkability": {"points": 8, "band": "Strong"},
            "green_space": {"points": 7, "band": "Strong"},
            "transit": {"points": 6, "band": "Moderate"},
            "third_place": {"points": 8, "band": "Strong"},
            "fitness": {"points": 5, "band": "Moderate"},
            "provisioning": {"points": 7, "band": "Strong"},
        },
        "checks": [
            {
                "name": "Gas Station Proximity",
                "status": "pass",
                "distance_ft": 2150,
                "description": "No gas stations within 1,500 ft",
                "icon": "gas-station",
                "css_class": "check-pass",
            },
        ],
        "health_summary": {"clear": 12, "issues": 1, "warnings": 0},
        "_trace": {"api_calls": 15, "total_ms": 12000},
        "quality_ceiling_inputs": {"sub_types": 3},
    }


class TestBuildB2bResponse:
    def test_includes_composite_score(self):
        from b2b.schema import build_b2b_response
        resp = build_b2b_response(_make_snapshot_result(), "snap123")
        assert resp["composite_score"] == 7
        assert resp["composite_band"] == "Strong"

    def test_includes_dimensions(self):
        from b2b.schema import build_b2b_response
        resp = build_b2b_response(_make_snapshot_result(), "snap123")
        assert "walkability" in resp["dimensions"]
        assert resp["dimensions"]["walkability"]["score"] == 8
        assert resp["dimensions"]["walkability"]["band"] == "Strong"

    def test_includes_health_checks(self):
        from b2b.schema import build_b2b_response
        resp = build_b2b_response(_make_snapshot_result(), "snap123")
        assert len(resp["health"]["checks"]) == 1
        check = resp["health"]["checks"][0]
        assert check["name"] == "Gas Station Proximity"
        assert check["status"] == "pass"

    def test_excludes_internal_fields(self):
        from b2b.schema import build_b2b_response
        resp = build_b2b_response(_make_snapshot_result(), "snap123")
        assert "_trace" not in resp
        assert "quality_ceiling_inputs" not in resp

    def test_health_checks_exclude_presentation_fields(self):
        from b2b.schema import build_b2b_response
        resp = build_b2b_response(_make_snapshot_result(), "snap123")
        check = resp["health"]["checks"][0]
        assert "icon" not in check
        assert "css_class" not in check

    def test_includes_snapshot_metadata(self):
        from b2b.schema import build_b2b_response
        resp = build_b2b_response(_make_snapshot_result(), "snap123")
        assert resp["snapshot_id"] == "snap123"
        assert "evaluated_at" in resp

    def test_includes_walk_scores(self):
        from b2b.schema import build_b2b_response
        resp = build_b2b_response(_make_snapshot_result(), "snap123")
        assert resp["dimensions"]["walkability"]["walk_score"] == 82


class TestSandboxLookup:
    def test_exact_match_returns_snapshot_id(self):
        from b2b.sandbox import get_sandbox_snapshot_id, SANDBOX_ADDRESSES
        if not SANDBOX_ADDRESSES:
            pytest.skip("No sandbox addresses configured")
        first_addr = next(iter(SANDBOX_ADDRESSES))
        result = get_sandbox_snapshot_id(first_addr)
        assert result is not None

    def test_no_match_returns_default(self):
        from b2b.sandbox import get_sandbox_snapshot_id, DEFAULT_SANDBOX_SNAPSHOT
        result = get_sandbox_snapshot_id("999 Nonexistent Blvd, Nowhere, XX 00000")
        assert result == DEFAULT_SANDBOX_SNAPSHOT

    def test_case_insensitive_match(self):
        from b2b.sandbox import get_sandbox_snapshot_id, SANDBOX_ADDRESSES
        if not SANDBOX_ADDRESSES:
            pytest.skip("No sandbox addresses configured")
        first_addr = next(iter(SANDBOX_ADDRESSES))
        result = get_sandbox_snapshot_id(first_addr.upper())
        assert result is not None
