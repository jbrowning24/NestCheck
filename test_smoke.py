"""Smoke tests for the NestCheck Flask app.

These tests verify the core routes work without calling external APIs.
They use a mock evaluation result to test the full request cycle:
  POST /evaluate -> redirect to /e/{id} -> 200
  GET /e/{id}.json -> 200 + valid JSON
  GET /e/{id}.csv -> 200 + CSV content
"""

import json
import pytest
from unittest.mock import patch, MagicMock
from app import app, _save_evaluation, _load_evaluation, _make_token, _decode_token


MOCK_RESULT = {
    "address": "123 Main St, Anytown, USA",
    "coordinates": {"lat": 40.0, "lng": -74.0},
    "walk_scores": {"walk_score": 72, "transit_score": 55, "bike_score": 60},
    "child_schooling_snapshot": {"childcare": [], "schools_by_level": {}},
    "urban_access": None,
    "transit_access": None,
    "green_escape": None,
    "transit_score": None,
    "passed_tier1": True,
    "tier1_checks": [
        {"name": "Gas stations", "result": "PASS", "details": "None within 500 ft", "required": True}
    ],
    "tier2_score": 30,
    "tier2_max": 60,
    "tier2_normalized": 50,
    "tier2_scores": [
        {"name": "Park Access", "points": 5, "max": 10, "details": "1 park nearby"}
    ],
    "tier3_bonus": 0,
    "tier3_bonuses": [],
    "tier3_bonus_reasons": [],
    "final_score": 50,
    "percentile_top": 40,
    "percentile_label": "Top 40%",
    "verdict": "Solid foundation with trade-offs",
}


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


class TestLandingPage:
    def test_index_returns_200(self, client):
        resp = client.get("/")
        assert resp.status_code == 200
        assert b"NestCheck" in resp.data

    def test_index_has_evaluate_form(self, client):
        resp = client.get("/")
        assert b"/evaluate" in resp.data
        assert b"Evaluate" in resp.data

    def test_no_report_language_on_landing(self, client):
        resp = client.get("/")
        html = resp.data.decode()
        assert "Generate Report" not in html
        assert "Generate report" not in html


class TestPricingPage:
    def test_pricing_returns_200(self, client):
        resp = client.get("/pricing")
        assert resp.status_code == 200

    def test_no_pdf_language(self, client):
        resp = client.get("/pricing")
        html = resp.data.decode()
        assert "PDF" not in html
        assert "$29" not in html


class TestEvaluateFlow:
    def test_evaluate_empty_address(self, client):
        resp = client.post("/evaluate", data={"address": ""})
        assert resp.status_code == 200
        assert b"Please enter" in resp.data

    def test_evaluate_no_api_key(self, client):
        with patch.dict("os.environ", {}, clear=False):
            import os
            old = os.environ.pop("GOOGLE_MAPS_API_KEY", None)
            try:
                resp = client.post("/evaluate", data={"address": "123 Main St"})
                assert resp.status_code == 200
                assert b"API key" in resp.data or b"configuration" in resp.data.lower()
            finally:
                if old:
                    os.environ["GOOGLE_MAPS_API_KEY"] = old


class TestResultsPersistence:
    def test_save_and_load(self):
        eid = "test123abc"
        _save_evaluation(eid, "Test Address", MOCK_RESULT)
        loaded = _load_evaluation(eid)
        assert loaded is not None
        address, result_dict, created_at = loaded
        assert address == "Test Address"
        assert result_dict["final_score"] == 50

    def test_view_saved_evaluation(self, client):
        eid = "smoke_view1"
        _save_evaluation(eid, "456 Oak Ave", MOCK_RESULT)
        resp = client.get(f"/e/{eid}")
        assert resp.status_code == 200
        assert b"456 Oak Ave" in resp.data or b"123 Main St" in resp.data

    def test_json_export(self, client):
        eid = "smoke_json1"
        _save_evaluation(eid, "789 Elm St", MOCK_RESULT)
        resp = client.get(f"/e/{eid}.json")
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data["evaluation_id"] == eid
        assert data["data"]["final_score"] == 50

    def test_csv_export(self, client):
        eid = "smoke_csv1"
        _save_evaluation(eid, "321 Pine Dr", MOCK_RESULT)
        resp = client.get(f"/e/{eid}.csv")
        assert resp.status_code == 200
        assert resp.content_type == "text/csv; charset=utf-8"
        csv_text = resp.data.decode()
        assert "321 Pine Dr" in csv_text or "123 Main St" in csv_text
        assert "Final Score" in csv_text

    def test_missing_evaluation_404(self, client):
        resp = client.get("/e/nonexistent999")
        assert resp.status_code == 404


class TestStatelessTokens:
    def test_token_roundtrip(self):
        token = _make_token(MOCK_RESULT)
        decoded = _decode_token(token)
        assert decoded is not None
        assert decoded["final_score"] == 50
        assert decoded["address"] == "123 Main St, Anytown, USA"

    def test_tampered_token_rejected(self):
        token = _make_token(MOCK_RESULT)
        # Flip a character in the signature
        tampered = "0" + token[1:]
        decoded = _decode_token(tampered)
        assert decoded is None

    def test_stateless_view(self, client):
        token = _make_token(MOCK_RESULT)
        resp = client.get(f"/e/t?d={token}")
        assert resp.status_code == 200
        assert b"123 Main St" in resp.data

    def test_stateless_json(self, client):
        token = _make_token(MOCK_RESULT)
        resp = client.get(f"/e/t.json?d={token}")
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data["data"]["final_score"] == 50


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
