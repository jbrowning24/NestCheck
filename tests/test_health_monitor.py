"""
Tests for the API health monitoring system (NES-155).

Covers:
  - HealthMonitor passive tracking (record_call → status computation)
  - Active probe functions (Overpass status, Open-Meteo) with mocked HTTP
  - Combined get_all_status() output
  - /healthz endpoint integration with health data
"""

import time
from unittest.mock import patch, MagicMock

import pytest
import requests

from health_monitor import HealthMonitor, HealthCheckResult


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def monitor():
    """Fresh HealthMonitor instance (no background thread)."""
    return HealthMonitor()


# ---------------------------------------------------------------------------
# Passive tracking — record_call + status computation
# ---------------------------------------------------------------------------

class TestPassiveTracking:

    def test_record_call_tracks_outcomes(self, monitor):
        """Recorded calls accumulate in the passive window."""
        monitor.record_call("google_maps", True, 100)
        monitor.record_call("google_maps", False, 200, "timeout")
        monitor.record_call("google_maps", True, 150)

        window = list(monitor._passive["google_maps"])
        assert len(window) == 3
        assert window[0].success is True
        assert window[1].success is False
        assert window[1].error == "timeout"

    def test_passive_status_unknown_when_empty(self, monitor):
        """No data → status is 'unknown'."""
        result = monitor._compute_passive_status("google_maps")
        assert result.status == "unknown"
        assert result.details["sample_size"] == 0
        assert result.details["mode"] == "passive"

    def test_passive_status_healthy(self, monitor):
        """All successes → 'healthy'."""
        for _ in range(20):
            monitor.record_call("google_maps", True, 100)

        result = monitor._compute_passive_status("google_maps")
        assert result.status == "healthy"
        assert result.details["success_rate"] == 1.0
        assert result.details["sample_size"] == 20

    def test_passive_status_degraded(self, monitor):
        """80% success rate → 'degraded' (below 95%, above 70%)."""
        for _ in range(16):
            monitor.record_call("google_maps", True, 100)
        for _ in range(4):
            monitor.record_call("google_maps", False, 200, "error")

        result = monitor._compute_passive_status("google_maps")
        assert result.status == "degraded"
        assert result.details["success_rate"] == 0.8

    def test_passive_status_down(self, monitor):
        """50% success rate → 'down' (below 70%)."""
        for _ in range(10):
            monitor.record_call("google_maps", True, 100)
        for _ in range(10):
            monitor.record_call("google_maps", False, 200, "error")

        result = monitor._compute_passive_status("google_maps")
        assert result.status == "down"
        assert result.details["success_rate"] == 0.5

    def test_passive_status_at_threshold_boundary(self, monitor):
        """Exactly 95% success → 'healthy' (>= threshold)."""
        for _ in range(19):
            monitor.record_call("google_maps", True, 100)
        monitor.record_call("google_maps", False, 200, "error")

        result = monitor._compute_passive_status("google_maps")
        assert result.status == "healthy"
        assert result.details["success_rate"] == 0.95

    def test_passive_latency_average(self, monitor):
        """Latency is averaged across all calls in the window."""
        monitor.record_call("google_maps", True, 100)
        monitor.record_call("google_maps", True, 300)

        result = monitor._compute_passive_status("google_maps")
        assert result.latency_ms == 200

    def test_passive_last_error_reported(self, monitor):
        """The most recent error is surfaced in the result."""
        monitor.record_call("google_maps", False, 100, "first error")
        monitor.record_call("google_maps", True, 100)
        monitor.record_call("google_maps", False, 100, "latest error")

        result = monitor._compute_passive_status("google_maps")
        assert result.error == "latest error"

    def test_passive_unknown_service(self, monitor):
        """Recording a call for an unregistered service creates the window."""
        monitor.record_call("new_service", True, 50)
        result = monitor._compute_passive_status("new_service")
        assert result.status == "healthy"
        assert result.details["sample_size"] == 1


# ---------------------------------------------------------------------------
# Active health checks — mocked HTTP
# ---------------------------------------------------------------------------

class TestActiveChecks:

    @patch("health_monitor.requests.get")
    def test_check_overpass_healthy(self, mock_get, monitor):
        """Overpass status endpoint returns 200 → healthy."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_get.return_value = mock_resp

        result = monitor._check_overpass()
        assert result.status == "healthy"
        assert result.service == "overpass"
        assert result.details["mode"] == "active"

    @patch("health_monitor.requests.get")
    def test_check_overpass_degraded(self, mock_get, monitor):
        """Overpass returns non-200 → degraded."""
        mock_resp = MagicMock()
        mock_resp.status_code = 503
        mock_get.return_value = mock_resp

        result = monitor._check_overpass()
        assert result.status == "degraded"
        assert "503" in result.error

    @patch("health_monitor.requests.get")
    def test_check_overpass_timeout(self, mock_get, monitor):
        """Overpass times out → down."""
        mock_get.side_effect = requests.Timeout("connection timed out")

        result = monitor._check_overpass()
        assert result.status == "down"
        assert result.error == "timeout"

    @patch("health_monitor.requests.get")
    def test_check_overpass_connection_error(self, mock_get, monitor):
        """Overpass connection error → down."""
        mock_get.side_effect = requests.ConnectionError("DNS resolution failed")

        result = monitor._check_overpass()
        assert result.status == "down"
        assert "DNS" in result.error

    @patch("health_monitor.requests.get")
    def test_check_open_meteo_healthy(self, mock_get, monitor):
        """Open-Meteo returns 200 → healthy."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_get.return_value = mock_resp

        result = monitor._check_open_meteo()
        assert result.status == "healthy"
        assert result.service == "open_meteo"
        assert result.details["mode"] == "active"

    @patch("health_monitor.requests.get")
    def test_check_open_meteo_server_error(self, mock_get, monitor):
        """Open-Meteo returns 500 → degraded."""
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_get.return_value = mock_resp

        result = monitor._check_open_meteo()
        assert result.status == "degraded"
        assert "500" in result.error

    @patch("health_monitor.requests.get")
    def test_check_open_meteo_timeout(self, mock_get, monitor):
        """Open-Meteo times out → down."""
        mock_get.side_effect = requests.Timeout("timed out")

        result = monitor._check_open_meteo()
        assert result.status == "down"
        assert result.error == "timeout"


# ---------------------------------------------------------------------------
# run_active_checks — state transitions
# ---------------------------------------------------------------------------

class TestActiveCheckRunner:

    @patch("health_monitor.requests.get")
    def test_run_active_checks_stores_results(self, mock_get, monitor):
        """Active check results are stored and retrievable."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_get.return_value = mock_resp

        monitor.run_active_checks()

        assert "overpass" in monitor._active_results
        assert "open_meteo" in monitor._active_results
        assert monitor._active_results["overpass"].status == "healthy"
        assert monitor._active_results["open_meteo"].status == "healthy"

    @patch("health_monitor.requests.get")
    def test_state_transition_logged(self, mock_get, monitor):
        """Status transitions are detected (prev_status tracking)."""
        # First run: healthy
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_get.return_value = mock_resp
        monitor.run_active_checks()

        assert monitor._prev_status["overpass"] == "healthy"

        # Second run: down
        mock_get.side_effect = requests.Timeout("timeout")
        monitor.run_active_checks()

        assert monitor._prev_status["overpass"] == "down"


# ---------------------------------------------------------------------------
# get_all_status — combined view
# ---------------------------------------------------------------------------

class TestGetAllStatus:

    @patch("health_monitor.requests.get")
    def test_combines_active_and_passive(self, mock_get, monitor):
        """Status dict includes all three services with correct modes."""
        # Set up active results
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_get.return_value = mock_resp
        monitor.run_active_checks()

        # Set up passive Google Maps data
        for _ in range(10):
            monitor.record_call("google_maps", True, 150)

        status = monitor.get_all_status()

        assert "google_maps" in status
        assert "overpass" in status
        assert "open_meteo" in status

        assert status["google_maps"]["mode"] == "passive"
        assert status["google_maps"]["status"] == "healthy"
        assert status["overpass"]["mode"] == "active"
        assert status["overpass"]["status"] == "healthy"
        assert status["open_meteo"]["mode"] == "active"
        assert status["open_meteo"]["status"] == "healthy"

    def test_all_unknown_when_no_data(self, monitor):
        """With no active checks and no passive data, everything is unknown."""
        status = monitor.get_all_status()

        assert status["google_maps"]["status"] == "unknown"
        assert status["overpass"]["status"] == "unknown"
        assert status["open_meteo"]["status"] == "unknown"

    @patch("health_monitor.requests.get")
    def test_active_preferred_over_passive(self, mock_get, monitor):
        """For Overpass/Open-Meteo, active results take precedence over passive data."""
        # Passive data says healthy
        for _ in range(10):
            monitor.record_call("overpass", True, 50)

        # Active probe says down
        mock_get.side_effect = requests.Timeout("timeout")
        monitor.run_active_checks()

        status = monitor.get_all_status()
        assert status["overpass"]["status"] == "down"
        assert status["overpass"]["mode"] == "active"

    def test_passive_fallback_when_no_active(self, monitor):
        """Overpass/Open-Meteo fall back to passive data when no active probe has run."""
        for _ in range(10):
            monitor.record_call("overpass", True, 50)

        status = monitor.get_all_status()
        assert status["overpass"]["status"] == "healthy"
        assert status["overpass"]["mode"] == "passive"


# ---------------------------------------------------------------------------
# /healthz integration
# ---------------------------------------------------------------------------

class TestHealthzEndpoint:

    @pytest.fixture
    def app_client(self, monkeypatch, tmp_path):
        """Flask test client with isolated DB."""
        db_path = str(tmp_path / "test.db")
        monkeypatch.setenv("NESTCHECK_DB_PATH", db_path)
        monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "test-key")
        monkeypatch.setenv("BUILDER_MODE", "false")

        import importlib
        import models
        importlib.reload(models)
        import app as app_module
        importlib.reload(app_module)

        app_module.app.config["TESTING"] = True
        with app_module.app.test_client() as client:
            yield client

    def test_healthz_includes_api_health(self, app_client):
        """Response includes api_health section with all three services."""
        resp = app_client.get("/healthz")
        data = resp.get_json()

        assert "api_health" in data
        assert "google_maps" in data["api_health"]
        assert "overpass" in data["api_health"]
        assert "open_meteo" in data["api_health"]

        # All should be unknown (no evaluations, no active checks in test)
        for svc in ("google_maps", "overpass", "open_meteo"):
            assert "status" in data["api_health"][svc]

    def test_healthz_ok_when_config_present(self, app_client):
        """With API key set and no APIs down, status is 'ok'."""
        resp = app_client.get("/healthz")
        data = resp.get_json()

        # All services are 'unknown' (no data), which is not 'down'
        assert data["status"] == "ok"
        assert resp.status_code == 200

    @patch("health_monitor._monitor")
    def test_healthz_degraded_when_api_down(self, mock_monitor, app_client):
        """Status becomes 'degraded' when any API reports 'down'."""
        mock_monitor.get_all_status.return_value = {
            "google_maps": {"status": "healthy", "mode": "passive"},
            "overpass": {"status": "down", "mode": "active", "error": "timeout"},
            "open_meteo": {"status": "healthy", "mode": "active"},
        }

        resp = app_client.get("/healthz")
        data = resp.get_json()

        assert data["status"] == "degraded"
        assert resp.status_code == 503


# ---------------------------------------------------------------------------
# Thread lifecycle (smoke test — no actual sleeping)
# ---------------------------------------------------------------------------

class TestThreadLifecycle:

    def test_start_stop(self, monitor):
        """Monitor thread starts and stops without error."""
        # Override interval to be very short for test
        monitor._stop_event.clear()
        monitor.start()
        assert monitor._thread is not None
        assert monitor._thread.is_alive()

        monitor.stop()
        monitor._thread.join(timeout=2)
        assert not monitor._thread.is_alive()

    def test_start_idempotent(self, monitor):
        """Calling start twice doesn't create a second thread."""
        monitor.start()
        thread1 = monitor._thread

        monitor.start()
        thread2 = monitor._thread

        assert thread1 is thread2
        monitor.stop()
        monitor._thread.join(timeout=2)
