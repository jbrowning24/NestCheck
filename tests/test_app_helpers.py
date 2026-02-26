"""Tests for app.py presentation helpers and route coverage gaps.

Covers generate_verdict, present_checks, _serialize_green_escape,
_serialize_urban_access, and builder route access control.
"""

import os
from unittest.mock import patch

import pytest

from property_evaluator import (
    CheckResult,
    EvaluationResult,
    MajorHubAccess,
    PrimaryTransitOption,
    PropertyListing,
    Tier1Check,
    Tier2Score,
    Tier3Bonus,
    TransitAccessResult,
    UrbanAccessProfile,
)
from app import (
    app,
    generate_verdict,
    present_checks,
    _serialize_urban_access,
    result_to_dict,
)


# ============================================================================
# generate_verdict
# ============================================================================

class TestGenerateVerdict:
    def test_failed_tier1(self):
        result = generate_verdict({"passed_tier1": False, "final_score": 90})
        assert result == "Does not meet baseline requirements"

    def test_exceptional(self):
        result = generate_verdict({"passed_tier1": True, "final_score": 85})
        assert result == "Exceptional daily-life match"

    def test_strong(self):
        result = generate_verdict({"passed_tier1": True, "final_score": 70})
        assert result == "Strong daily-life match"

    def test_solid(self):
        result = generate_verdict({"passed_tier1": True, "final_score": 55})
        assert result == "Solid foundation with trade-offs"

    def test_compromised(self):
        result = generate_verdict({"passed_tier1": True, "final_score": 40})
        assert result == "Compromised walkability — car likely needed"

    def test_significant_gaps(self):
        result = generate_verdict({"passed_tier1": True, "final_score": 30})
        assert result == "Significant daily-life gaps"

    def test_zero_score_passed(self):
        result = generate_verdict({"passed_tier1": True, "final_score": 0})
        assert result == "Significant daily-life gaps"

    def test_boundary_84(self):
        result = generate_verdict({"passed_tier1": True, "final_score": 84})
        assert result == "Strong daily-life match"

    def test_boundary_54(self):
        result = generate_verdict({"passed_tier1": True, "final_score": 54})
        assert result == "Compromised walkability — car likely needed"

    def test_boundary_39(self):
        result = generate_verdict({"passed_tier1": True, "final_score": 39})
        assert result == "Significant daily-life gaps"


# ============================================================================
# present_checks
# ============================================================================

class TestPresentChecks:
    def _check(self, name, result, details="test"):
        return {"name": name, "result": result, "details": details}

    def test_pass_safety_check(self):
        checks = [self._check("Gas station", "PASS")]
        presented = present_checks(checks)
        assert len(presented) == 1
        p = presented[0]
        assert p["category"] == "SAFETY"
        assert p["result_type"] == "CLEAR"
        assert p["proximity_band"] == "NEUTRAL"
        assert p["explanation"] is None

    def test_fail_safety_check(self):
        checks = [self._check("Highway", "FAIL", "TOO CLOSE to: I-95")]
        presented = present_checks(checks)
        p = presented[0]
        assert p["result_type"] == "CONFIRMED_ISSUE"
        assert p["proximity_band"] == "VERY_CLOSE"
        assert "Highway or major parkway nearby" in p["headline"]
        assert p["explanation"] == "TOO CLOSE to: I-95"

    def test_warning_check(self):
        checks = [self._check("Power lines", "WARNING", "detected within 150 ft")]
        presented = present_checks(checks)
        p = presented[0]
        assert p["result_type"] == "WARNING_DETECTED"
        assert p["proximity_band"] == "NOTABLE"

    def test_unknown_check(self):
        checks = [self._check("Cell tower", "UNKNOWN", "Unable to query")]
        presented = present_checks(checks)
        p = presented[0]
        assert p["result_type"] == "VERIFICATION_NEEDED"
        assert "Unable to verify" in p["headline"]

    def test_lifestyle_category(self):
        checks = [self._check("W/D in unit", "PASS")]
        presented = present_checks(checks)
        assert presented[0]["category"] == "LIFESTYLE"

    def test_all_safety_check_names(self):
        safety_names = [
            "Gas station", "Highway", "High-volume road",
            "Power lines", "Electrical substation", "Cell tower", "Industrial zone",
        ]
        for name in safety_names:
            checks = [self._check(name, "PASS")]
            presented = present_checks(checks)
            assert presented[0]["category"] == "SAFETY", f"{name} should be SAFETY"


# ============================================================================
# _serialize_urban_access
# ============================================================================

class TestSerializeUrbanAccess:
    def test_none_returns_none(self):
        assert _serialize_urban_access(None) is None

    def test_empty_profile(self):
        profile = UrbanAccessProfile()
        result = _serialize_urban_access(profile)
        assert result["primary_transit"] is None
        assert result["major_hub"] is None

    def test_full_profile(self):
        profile = UrbanAccessProfile(
            primary_transit=PrimaryTransitOption(
                name="Scarsdale Station",
                mode="Commuter Rail",
                lat=40.99,
                lng=-73.78,
                walk_time_min=12,
                drive_time_min=5,
                parking_available=True,
                frequency_class="High frequency",
            ),
            major_hub=MajorHubAccess(
                name="Grand Central",
                travel_time_min=40,
                transit_mode="Metro-North",
                route_summary="12 min walk + 28 min train",
            ),
        )
        result = _serialize_urban_access(profile)
        assert result["primary_transit"]["name"] == "Scarsdale Station"
        assert result["primary_transit"]["walk_time_min"] == 12
        assert result["major_hub"]["travel_time_min"] == 40


# ============================================================================
# result_to_dict
# ============================================================================

class TestResultToDict:
    def _minimal_result(self):
        return EvaluationResult(
            listing=PropertyListing(address="123 Test St"),
            lat=40.0,
            lng=-74.0,
            tier1_checks=[
                Tier1Check("Gas station", CheckResult.PASS, "Clear"),
            ],
            tier2_scores=[
                Tier2Score("Cost", 6, 10, "In range"),
            ],
            tier3_bonuses=[],
            passed_tier1=True,
            final_score=60,
        )

    def test_basic_structure(self):
        result = self._minimal_result()
        d = result_to_dict(result)
        assert d["address"] == "123 Test St"
        assert d["coordinates"]["lat"] == 40.0
        assert d["passed_tier1"] is True
        assert d["final_score"] == 60

    def test_tier1_checks_serialized(self):
        result = self._minimal_result()
        d = result_to_dict(result)
        assert len(d["tier1_checks"]) == 1
        assert d["tier1_checks"][0]["result"] == "PASS"

    def test_tier2_scores_serialized(self):
        result = self._minimal_result()
        d = result_to_dict(result)
        assert len(d["tier2_scores"]) == 1
        assert d["tier2_scores"][0]["name"] == "Cost"
        assert d["tier2_scores"][0]["points"] == 6

    def test_presented_checks_generated(self):
        result = self._minimal_result()
        d = result_to_dict(result)
        assert "presented_checks" in d
        assert len(d["presented_checks"]) == 1

    def test_verdict_generated(self):
        result = self._minimal_result()
        d = result_to_dict(result)
        assert "verdict" in d
        assert isinstance(d["verdict"], str)

    def test_transit_access_none(self):
        result = self._minimal_result()
        d = result_to_dict(result)
        assert d["transit_access"] is None

    def test_transit_access_serialized(self):
        result = self._minimal_result()
        result.transit_access = TransitAccessResult(
            primary_stop="Scarsdale",
            walk_minutes=12,
            mode="Commuter Rail",
            frequency_bucket="High",
            score_0_10=8,
        )
        d = result_to_dict(result)
        assert d["transit_access"]["primary_stop"] == "Scarsdale"
        assert d["transit_access"]["score_0_10"] == 8

    def test_neighborhood_places_none(self):
        result = self._minimal_result()
        d = result_to_dict(result)
        assert d["neighborhood_places"] is None


# ============================================================================
# Route tests
# ============================================================================

@pytest.fixture()
def client():
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    with app.test_client() as c:
        yield c


class TestHealthzRoute:
    def test_healthz_ok(self, client):
        with patch.dict(os.environ, {"GOOGLE_MAPS_API_KEY": "fake-key"}):
            resp = client.get("/healthz")
            assert resp.status_code == 200

    def test_healthz_missing_key(self, client):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("GOOGLE_MAPS_API_KEY", None)
            resp = client.get("/healthz")
            assert resp.status_code == 503


class TestPricingRoute:
    def test_pricing_200(self, client):
        resp = client.get("/pricing")
        assert resp.status_code == 200


class TestEventRoute:
    def test_valid_event(self, client):
        resp = client.post(
            "/api/event",
            json={"event_type": "snapshot_shared", "snapshot_id": "test123"},
        )
        assert resp.status_code in (200, 204)

    def test_missing_event_type(self, client):
        resp = client.post("/api/event", json={"snapshot_id": "test123"})
        assert resp.status_code == 400


class TestBuilderRoutes:
    def test_dashboard_non_builder_404(self, client):
        with patch.dict(os.environ, {"BUILDER_MODE": "false", "BUILDER_SECRET": "secret123"}):
            resp = client.get("/builder/dashboard")
            assert resp.status_code == 404

    def test_debug_trace_non_builder_404(self, client):
        with patch.dict(os.environ, {"BUILDER_MODE": "false", "BUILDER_SECRET": "secret123"}):
            resp = client.get("/debug/trace/fake-id")
            assert resp.status_code == 404
