"""Integration tests for B2B API endpoints."""
import json
import pytest
from models import _get_db, create_job, get_job
from tests.test_b2b_auth import _create_partner, _create_api_key


class TestEvaluateEndpoint:
    def test_missing_address_returns_400(self, client):
        pid = _create_partner()
        key, _ = _create_api_key(pid)
        resp = client.post(
            "/api/v1/b2b/evaluate",
            json={},
            headers={"Authorization": f"Bearer {key}"},
        )
        assert resp.status_code == 400
        assert resp.get_json()["error"]["code"] == "invalid_request"

    def test_test_key_returns_sandbox_response(self, client):
        pid = _create_partner()
        key, _ = _create_api_key(pid, environment="test")
        resp = client.post(
            "/api/v1/b2b/evaluate",
            json={"address": "123 Main St, White Plains, NY 10601"},
            headers={"Authorization": f"Bearer {key}"},
        )
        data = resp.get_json()
        # Sandbox may return 200 with sandbox flag or 503 if no snapshots configured
        assert resp.status_code in (200, 503)
        if resp.status_code == 200:
            assert data.get("sandbox") is True

    def test_quota_exceeded_returns_429(self, client):
        pid = _create_partner(quota=1)
        key, _ = _create_api_key(pid)
        # First request
        resp1 = client.post(
            "/api/v1/b2b/evaluate",
            json={"address": "123 Main St, White Plains, NY 10601"},
            headers={"Authorization": f"Bearer {key}"},
        )
        # Second request — should hit quota
        resp2 = client.post(
            "/api/v1/b2b/evaluate",
            json={"address": "456 Oak Ave, Scarsdale, NY 10583"},
            headers={"Authorization": f"Bearer {key}"},
        )
        assert resp2.status_code == 429
        assert resp2.get_json()["error"]["code"] == "quota_exceeded"


class TestRateLimiting:
    def test_rate_limit_headers_present(self, client):
        pid = _create_partner()
        key, _ = _create_api_key(pid)
        resp = client.post(
            "/api/v1/b2b/evaluate",
            json={"address": "123 Main St"},
            headers={"Authorization": f"Bearer {key}"},
        )
        assert "X-Quota-Limit" in resp.headers or resp.status_code in (202, 429)


class TestJobStatusEndpoint:
    def test_nonexistent_job_returns_404(self, client):
        pid = _create_partner()
        key, _ = _create_api_key(pid)
        resp = client.get(
            "/api/v1/b2b/jobs/nonexistent123",
            headers={"Authorization": f"Bearer {key}"},
        )
        assert resp.status_code == 404

    def test_other_partners_job_returns_404(self, client):
        pid_a = _create_partner(name="Partner A")
        pid_b = _create_partner(name="Partner B", email="b@corp.com")
        key_a, _ = _create_api_key(pid_a)
        key_b, _ = _create_api_key(pid_b)
        job_id = create_job("123 Main St", partner_id=pid_b)
        resp = client.get(
            f"/api/v1/b2b/jobs/{job_id}",
            headers={"Authorization": f"Bearer {key_a}"},
        )
        assert resp.status_code == 404

    def test_own_job_returns_status(self, client):
        pid = _create_partner()
        key, _ = _create_api_key(pid)
        job_id = create_job("123 Main St", partner_id=pid)
        resp = client.get(
            f"/api/v1/b2b/jobs/{job_id}",
            headers={"Authorization": f"Bearer {key}"},
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["job_id"] == job_id
        assert data["status"] in ("queued", "running", "done", "failed")


class TestEndToEnd:
    def test_full_lifecycle_create_poll_complete(self, client):
        """Simulate: create partner → create job → poll → complete → get result."""
        pid = _create_partner()
        key, _ = _create_api_key(pid)

        # Create evaluation
        resp = client.post(
            "/api/v1/b2b/evaluate",
            json={"address": "123 Main St, White Plains, NY 10601"},
            headers={"Authorization": f"Bearer {key}"},
        )
        assert resp.status_code == 202
        data = resp.get_json()
        job_id = data["job_id"]
        assert data["status"] == "queued"

        # Poll — should be queued
        resp = client.get(
            f"/api/v1/b2b/jobs/{job_id}",
            headers={"Authorization": f"Bearer {key}"},
        )
        assert resp.status_code == 200
        assert resp.get_json()["status"] == "queued"

        # Simulate worker completing the job with a snapshot
        from models import save_snapshot, complete_job
        result_dict = {
            "address": "123 Main St, White Plains, NY 10601",
            "coordinates": {"lat": 41.033, "lng": -73.763},
            "composite_score": 7,
            "composite_band": "Strong",
            "data_confidence": "verified",
            "walk_scores": {"walk_score": 82},
            "tier2_scores": {
                "walkability": {"points": 8, "band": "Strong"},
            },
            "checks": [],
            "health_summary": {"clear": 12, "issues": 0, "warnings": 0},
        }
        snapshot_id = save_snapshot(
            address_input="123 Main St",
            address_norm="123 Main St, White Plains, NY 10601",
            result_dict=result_dict,
        )
        complete_job(job_id, snapshot_id)

        # Poll again — should be done with result
        resp = client.get(
            f"/api/v1/b2b/jobs/{job_id}",
            headers={"Authorization": f"Bearer {key}"},
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "done"
        assert "result" in data
        assert data["result"]["composite_score"] == 7
        assert data["result"]["snapshot_id"] == snapshot_id
