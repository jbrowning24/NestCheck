"""
Regression tests for the "Service configuration error" bug.

These tests ensure:
1. The opaque "Service configuration error. Please contact support." message
   can never appear in user-facing responses.
2. Missing config produces a clear, actionable error with a request_id.
3. Builder mode shows diagnostic details on errors.
4. JSON and CSV export endpoints work for existing snapshots.
5. The old error string is not present anywhere in the codebase.
"""

import json
import os
import subprocess
import tempfile

import pytest

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def app_client(monkeypatch, tmp_path):
    """Flask test client with isolated DB and NO Google Maps key."""
    db_path = str(tmp_path / "test.db")
    monkeypatch.setenv("NESTCHECK_DB_PATH", db_path)
    # Explicitly REMOVE the API key to test the missing-config path
    monkeypatch.delenv("GOOGLE_MAPS_API_KEY", raising=False)
    monkeypatch.setenv("BUILDER_MODE", "false")

    # Re-import to pick up new env
    import importlib
    import models
    importlib.reload(models)
    import app as app_module
    importlib.reload(app_module)

    app_module.app.config["TESTING"] = True
    with app_module.app.test_client() as client:
        yield client


@pytest.fixture
def builder_client(monkeypatch, tmp_path):
    """Flask test client in builder mode with NO Google Maps key."""
    db_path = str(tmp_path / "test.db")
    monkeypatch.setenv("NESTCHECK_DB_PATH", db_path)
    monkeypatch.delenv("GOOGLE_MAPS_API_KEY", raising=False)
    monkeypatch.setenv("BUILDER_MODE", "true")

    import importlib
    import models
    importlib.reload(models)
    import app as app_module
    importlib.reload(app_module)

    app_module.app.config["TESTING"] = True
    with app_module.app.test_client() as client:
        yield client


@pytest.fixture
def client_with_snapshot(monkeypatch, tmp_path):
    """Flask test client with a pre-populated snapshot for export tests."""
    db_path = str(tmp_path / "test.db")
    monkeypatch.setenv("NESTCHECK_DB_PATH", db_path)
    monkeypatch.delenv("GOOGLE_MAPS_API_KEY", raising=False)

    import importlib
    import models
    importlib.reload(models)
    import app as app_module
    importlib.reload(app_module)

    app_module.app.config["TESTING"] = True

    # Create a fake snapshot directly via the models layer
    fake_result = {
        "address": "123 Test St, Testville, TX 12345",
        "final_score": 72,
        "passed_tier1": True,
        "verdict": "Strong daily-life match",
        "tier2_score": 40,
        "tier2_max": 60,
        "tier2_normalized": 67,
        "tier3_bonus": 5,
        "tier2_scores": [
            {"name": "Park & Green Access", "points": 7, "max": 10, "details": "Good park nearby"},
            {"name": "Transit Access", "points": 6, "max": 10, "details": "Bus stop 5 min walk"},
        ],
        "tier1_checks": [
            {"name": "Highway buffer", "result": "PASS", "details": ">300m from highway", "required": True},
        ],
        "coordinates": {"lat": 30.0, "lng": -97.0},
        "walk_scores": {"walk_score": 65, "transit_score": 40, "bike_score": 55},
    }
    snapshot_id = models.save_snapshot(
        address_input="123 Test St",
        address_norm="123 Test St, Testville, TX 12345",
        result_dict=fake_result,
    )

    with app_module.app.test_client() as client:
        yield client, snapshot_id


# ---------------------------------------------------------------------------
# 1. The opaque error message must NEVER appear
# ---------------------------------------------------------------------------

class TestOpaqueErrorEliminated:
    """The old 'Service configuration error' message must not appear."""

    def test_missing_api_key_does_not_show_opaque_error(self, app_client):
        """POST / with missing GOOGLE_MAPS_API_KEY must NOT return the old message."""
        resp = app_client.post("/", data={"address": "123 Main St"})
        body = resp.data.decode()
        assert "Service configuration error" not in body
        assert "Please contact support" not in body

    def test_missing_api_key_shows_actionable_message(self, app_client):
        """POST / with missing key must name the specific missing variable."""
        resp = app_client.post("/", data={"address": "123 Main St"})
        body = resp.data.decode()
        assert "GOOGLE_MAPS_API_KEY" in body
        assert "required API keys are not configured" in body

    def test_missing_api_key_includes_request_id(self, app_client):
        """Error responses must include a request reference ID."""
        resp = app_client.post("/", data={"address": "123 Main St"})
        body = resp.data.decode()
        assert "ref:" in body

    def test_builder_mode_shows_diagnostic(self, builder_client):
        """In builder mode, error should include diagnostic detail block."""
        resp = builder_client.post("/", data={"address": "123 Main St"})
        body = resp.data.decode()
        assert "Builder diagnostic" in body
        assert "missing_keys" in body
        assert "GOOGLE_MAPS_API_KEY" in body

    def test_get_homepage_returns_200(self, app_client):
        """GET / should always return 200 (landing page)."""
        resp = app_client.get("/")
        assert resp.status_code == 200

    def test_empty_address_returns_validation_error(self, app_client):
        """POST / with empty address returns a validation message, not a config error."""
        resp = app_client.post("/", data={"address": ""})
        body = resp.data.decode()
        assert "Please enter a property address" in body
        assert "Service configuration error" not in body


# ---------------------------------------------------------------------------
# 2. JSON and CSV export endpoints
# ---------------------------------------------------------------------------

class TestExportEndpoints:
    """Verify JSON and CSV snapshot exports work."""

    def test_json_export_returns_valid_json(self, client_with_snapshot):
        client, snapshot_id = client_with_snapshot
        resp = client.get(f"/api/snapshot/{snapshot_id}/json")
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data["snapshot_id"] == snapshot_id
        assert data["final_score"] == 72
        assert data["verdict"] == "Strong daily-life match"
        assert "result" in data

    def test_csv_export_returns_csv(self, client_with_snapshot):
        client, snapshot_id = client_with_snapshot
        resp = client.get(f"/api/snapshot/{snapshot_id}/csv")
        assert resp.status_code == 200
        assert resp.mimetype == "text/csv"
        body = resp.data.decode()
        assert "snapshot_id" in body
        assert snapshot_id in body
        assert "123 Test St" in body

    def test_json_export_404_for_missing_snapshot(self, client_with_snapshot):
        client, _ = client_with_snapshot
        resp = client.get("/api/snapshot/nonexistent/json")
        assert resp.status_code == 404

    def test_csv_export_404_for_missing_snapshot(self, client_with_snapshot):
        client, _ = client_with_snapshot
        resp = client.get("/api/snapshot/nonexistent/csv")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# 3. Snapshot view works
# ---------------------------------------------------------------------------

class TestSnapshotView:
    """Verify the snapshot page renders for existing snapshots."""

    def test_snapshot_page_renders(self, client_with_snapshot):
        client, snapshot_id = client_with_snapshot
        resp = client.get(f"/s/{snapshot_id}")
        assert resp.status_code == 200
        body = resp.data.decode()
        assert "123 Test St" in body
        assert "Copy share link" in body

    def test_snapshot_page_has_export_links(self, client_with_snapshot):
        client, snapshot_id = client_with_snapshot
        resp = client.get(f"/s/{snapshot_id}")
        body = resp.data.decode()
        assert f"/api/snapshot/{snapshot_id}/json" in body
        assert f"/api/snapshot/{snapshot_id}/csv" in body

    def test_missing_snapshot_returns_404(self, client_with_snapshot):
        client, _ = client_with_snapshot
        resp = client.get("/s/doesnotexist")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# 4. "Never again" codebase grep guard
# ---------------------------------------------------------------------------

class TestCodebaseGuard:
    """Ensure the banned error strings are not in the codebase."""

    BANNED_STRINGS = [
        "Service configuration error",
        "Please contact support",
        "Could not generate report",
        "generate_report",
    ]

    @pytest.mark.parametrize("banned", BANNED_STRINGS)
    def test_banned_string_not_in_python_code(self, banned):
        """The banned string must not appear in any .py file (except this test)."""
        result = subprocess.run(
            ["grep", "-r", "--include=*.py", "-l", banned, "."],
            capture_output=True, text=True, cwd="/home/user/NestCheck",
        )
        matching_files = [
            f for f in result.stdout.strip().split("\n")
            if f and "test_service_errors.py" not in f
        ]
        assert matching_files == [], (
            f"Banned string {banned!r} found in: {matching_files}"
        )

    @pytest.mark.parametrize("banned", BANNED_STRINGS)
    def test_banned_string_not_in_templates(self, banned):
        """The banned string must not appear in any template."""
        result = subprocess.run(
            ["grep", "-r", "--include=*.html", "-l", banned, "templates/"],
            capture_output=True, text=True, cwd="/home/user/NestCheck",
        )
        matching_files = [f for f in result.stdout.strip().split("\n") if f]
        assert matching_files == [], (
            f"Banned string {banned!r} found in templates: {matching_files}"
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
