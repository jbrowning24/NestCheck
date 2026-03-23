"""Tests for widget badge and data API routes (NES-343)."""

import json
import pytest
from app import app
from models import save_snapshot


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


@pytest.fixture
def snapshot_id(client):
    """Save a minimal snapshot and return its ID."""
    result = {
        "address": "123 Main St, White Plains, NY",
        "final_score": 72,
        "tier1_checks": [],
        "tier2_scores": [],
    }
    sid = save_snapshot("123 Main St", "123 Main St, White Plains, NY", result)
    return sid


class TestWidgetDataAPI:
    def test_returns_json(self, client, snapshot_id):
        resp = client.get(f"/api/v1/widget-data/{snapshot_id}")
        assert resp.status_code == 200
        assert resp.content_type == "application/json"
        data = resp.get_json()
        assert data["score"] == 72
        assert data["address"] == "123 Main St, White Plains, NY"
        assert "band" in data
        assert "report_url" in data
        assert "clear_count" in data
        assert "concern_count" in data
        assert "health_summary" in data

    def test_cors_header(self, client, snapshot_id):
        resp = client.get(f"/api/v1/widget-data/{snapshot_id}")
        assert resp.headers.get("Access-Control-Allow-Origin") == "*"

    def test_cache_header(self, client, snapshot_id):
        resp = client.get(f"/api/v1/widget-data/{snapshot_id}")
        assert "max-age=86400" in resp.headers.get("Cache-Control", "")

    def test_404_returns_json(self, client):
        resp = client.get("/api/v1/widget-data/nonexistent")
        assert resp.status_code == 404
        data = resp.get_json()
        assert data["error"] == "Snapshot not found"
        assert resp.headers.get("Access-Control-Allow-Origin") == "*"

    def test_report_url_is_absolute(self, client, snapshot_id):
        resp = client.get(f"/api/v1/widget-data/{snapshot_id}")
        data = resp.get_json()
        assert data["report_url"].startswith("http")
        assert f"/s/{snapshot_id}" in data["report_url"]

    def test_health_summary_no_concerns(self, client, snapshot_id):
        resp = client.get(f"/api/v1/widget-data/{snapshot_id}")
        data = resp.get_json()
        assert "clear" in data["health_summary"]

    def test_health_summary_pluralization(self, client):
        """Snapshot with 1 concern should say 'concern' not 'concerns'."""
        result = {
            "address": "456 Oak Ave, Scarsdale, NY",
            "final_score": 45,
            "tier1_checks": [],
            "tier2_scores": [],
            "presented_checks": [
                {"name": "Gas station", "result_type": "CONFIRMED_ISSUE"},
                {"name": "Power lines", "result_type": "CLEAR"},
            ],
        }
        sid = save_snapshot("456 Oak Ave", "456 Oak Ave, Scarsdale, NY", result)
        resp = client.get(f"/api/v1/widget-data/{sid}")
        data = resp.get_json()
        assert data["concern_count"] == 1
        assert "1 concern" in data["health_summary"]
        assert "concerns" not in data["health_summary"]
