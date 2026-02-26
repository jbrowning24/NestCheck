"""Tests for the /compare route — side-by-side comparison of 2-4 snapshots."""

import json
import pytest

from models import save_snapshot


def _make_fake_result(address: str, score: int, verdict: str) -> dict:
    """Minimal result dict for snapshot creation."""
    return {
        "address": address,
        "final_score": score,
        "passed_tier1": True,
        "verdict": verdict,
        "tier2_score": 40,
        "tier2_max": 60,
        "tier2_normalized": 67,
        "tier3_bonus": 5,
        "tier2_scores": [
            {"name": "Parks & Green Space", "points": 7, "max": 10, "details": ""},
            {"name": "Getting Around", "points": 6, "max": 10, "details": ""},
        ],
        "tier1_checks": [
            {"name": "Highway buffer", "result": "PASS", "details": "", "required": True},
        ],
        "coordinates": {"lat": 30.0, "lng": -97.0},
        "walk_scores": {"walk_score": 65, "transit_score": 40, "bike_score": 55},
    }


@pytest.fixture
def two_snapshots():
    """Create two snapshots for comparison tests."""
    id1 = save_snapshot(
        address_input="123 First St",
        address_norm="123 First St, Austin, TX",
        result_dict=_make_fake_result("123 First St, Austin, TX", 72, "Strong match"),
    )
    id2 = save_snapshot(
        address_input="456 Second Ave",
        address_norm="456 Second Ave, Austin, TX",
        result_dict=_make_fake_result("456 Second Ave, Austin, TX", 58, "Moderate match"),
    )
    return id1, id2


class TestCompareRoute:
    def test_compare_two_valid_snapshots_renders(self, client, two_snapshots):
        id1, id2 = two_snapshots
        resp = client.get(f"/compare?ids={id1},{id2}")
        assert resp.status_code == 200
        body = resp.data.decode()
        assert "Compare Addresses" in body
        assert "123 First St" in body
        assert "456 Second Ave" in body
        assert "72" in body
        assert "58" in body

    def test_compare_empty_ids_redirects(self, client):
        resp = client.get("/compare?ids=", follow_redirects=True)
        body = resp.data.decode()
        assert "Select at least two addresses" in body

    def test_compare_single_id_redirects(self, client, two_snapshots):
        id1, _ = two_snapshots
        resp = client.get(f"/compare?ids={id1}", follow_redirects=True)
        body = resp.data.decode()
        assert "Select at least two addresses" in body

    def test_compare_five_ids_redirects(self, client, two_snapshots):
        id1, id2 = two_snapshots
        resp = client.get(f"/compare?ids={id1},{id2},a,b,c", follow_redirects=True)
        body = resp.data.decode()
        assert "You can compare up to four" in body

    def test_compare_one_valid_one_invalid_redirects(self, client, two_snapshots):
        id1, _ = two_snapshots
        resp = client.get(f"/compare?ids={id1},nonexistent999", follow_redirects=True)
        # Only one valid — should redirect (need at least 2)
        body = resp.data.decode()
        assert "no longer available" in body

    def test_compare_deduplicates_ids(self, client, two_snapshots):
        id1, id2 = two_snapshots
        resp = client.get(f"/compare?ids={id1},{id2},{id1}")
        assert resp.status_code == 200
        body = resp.data.decode()
        assert "Compare Addresses" in body
        # Should show 2 evaluations (deduped) — both addresses appear once each
        assert "123 First St" in body
        assert "456 Second Ave" in body

    def test_compare_all_stale_ids_shows_helpful_error(self, client):
        """When all IDs in the compare list are stale (DB wiped), show actionable message."""
        resp = client.get("/compare?ids=gone1,gone2", follow_redirects=True)
        body = resp.data.decode()
        assert "no longer available" in body
        assert "re-evaluate" in body

    def test_compare_two_valid_one_stale_still_works(self, client, two_snapshots):
        """If one ID is stale but two are valid, comparison should still render."""
        id1, id2 = two_snapshots
        resp = client.get(f"/compare?ids={id1},{id2},gone999")
        assert resp.status_code == 200
        body = resp.data.decode()
        assert "Compare Addresses" in body
        assert "123 First St" in body
        assert "456 Second Ave" in body


class TestCheckSnapshotsAPI:
    """Tests for /api/snapshots/check — client-side ID validation."""

    def test_check_returns_valid_and_invalid(self, client, two_snapshots):
        id1, id2 = two_snapshots
        resp = client.post(
            "/api/snapshots/check",
            data=json.dumps({"ids": [id1, "nonexistent", id2]}),
            content_type="application/json",
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert set(data["valid"]) == {id1, id2}
        assert data["invalid"] == ["nonexistent"]

    def test_check_all_stale(self, client):
        resp = client.post(
            "/api/snapshots/check",
            data=json.dumps({"ids": ["gone1", "gone2"]}),
            content_type="application/json",
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["valid"] == []
        assert set(data["invalid"]) == {"gone1", "gone2"}

    def test_check_empty_list(self, client):
        resp = client.post(
            "/api/snapshots/check",
            data=json.dumps({"ids": []}),
            content_type="application/json",
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["valid"] == []
        assert data["invalid"] == []

    def test_check_rejects_oversized_list(self, client):
        resp = client.post(
            "/api/snapshots/check",
            data=json.dumps({"ids": [f"id{i}" for i in range(11)]}),
            content_type="application/json",
        )
        assert resp.status_code == 400
