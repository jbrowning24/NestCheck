"""
API health monitoring for NestCheck data sources.

Two monitoring modes:
  1. Active probes (Overpass status endpoint, Open-Meteo) — run by a
     background daemon thread every HEALTH_CHECK_INTERVAL seconds.
  2. Passive tracking (Google Maps, plus Overpass/Open-Meteo from real
     evaluations) — records outcomes from actual API calls made during
     property evaluations.

Active probes target free endpoints only (no Google Maps API cost).
Passive tracking hooks into the existing _traced_get / _do_request /
_fetch_daily_data call paths via record_call().

The background thread follows the same daemon-thread pattern as worker.py
(start_monitor/stop_monitor, threading.Event for shutdown).

Module-level singleton: all callers in this process share one HealthMonitor.
"""

import logging
import os
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import requests

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# How often the background thread runs active probes (seconds).
HEALTH_CHECK_INTERVAL = int(
    os.environ.get("HEALTH_CHECK_INTERVAL", "300")
)

# HTTP timeout for active health probes (seconds).
_PROBE_TIMEOUT = 10

# Rolling window size for passive call tracking per service.
_PASSIVE_WINDOW_SIZE = 50

# Passive health thresholds (success rate).
_HEALTHY_THRESHOLD = 0.95
_DEGRADED_THRESHOLD = 0.70

# Overpass status endpoint (separate from the query interpreter).
_OVERPASS_STATUS_URL = os.environ.get(
    "OVERPASS_STATUS_URL",
    "https://overpass-api.de/api/status",
)

# Open-Meteo archive endpoint for lightweight probe.
_OPEN_METEO_PROBE_URL = "https://archive-api.open-meteo.com/v1/archive"


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class HealthCheckResult:
    """Health status for a single API dependency."""
    service: str
    status: str          # "healthy" | "degraded" | "down" | "unknown"
    latency_ms: int
    last_checked: str    # ISO-8601 timestamp
    error: Optional[str] = None
    details: Optional[Dict[str, Any]] = None


@dataclass
class _CallRecord:
    """A single API call outcome (for passive tracking)."""
    timestamp: float
    success: bool
    latency_ms: int
    error: Optional[str] = None


# ---------------------------------------------------------------------------
# HealthMonitor
# ---------------------------------------------------------------------------

class HealthMonitor:
    """Thread-safe health status tracker for external API dependencies."""

    def __init__(self) -> None:
        self._lock = threading.Lock()

        # Active probe results (Overpass, Open-Meteo).
        self._active_results: Dict[str, HealthCheckResult] = {}

        # Passive call history (all three services).
        self._passive: Dict[str, deque] = {
            "google_maps": deque(maxlen=_PASSIVE_WINDOW_SIZE),
            "overpass": deque(maxlen=_PASSIVE_WINDOW_SIZE),
            "open_meteo": deque(maxlen=_PASSIVE_WINDOW_SIZE),
        }

        # Previous active status per service (for transition logging).
        self._prev_status: Dict[str, str] = {}

        # Background thread plumbing.
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

    # ------------------------------------------------------------------
    # Passive recording (called from API clients)
    # ------------------------------------------------------------------

    def record_call(
        self,
        service: str,
        success: bool,
        latency_ms: int,
        error: Optional[str] = None,
    ) -> None:
        """Record the outcome of an API call for passive health tracking."""
        record = _CallRecord(
            timestamp=time.time(),
            success=success,
            latency_ms=latency_ms,
            error=error,
        )
        with self._lock:
            if service not in self._passive:
                self._passive[service] = deque(maxlen=_PASSIVE_WINDOW_SIZE)
            self._passive[service].append(record)

    # ------------------------------------------------------------------
    # Passive health computation
    # ------------------------------------------------------------------

    def _compute_passive_status(self, service: str) -> HealthCheckResult:
        """Derive health status from the rolling window of real API calls."""
        with self._lock:
            window = list(self._passive.get(service, []))

        if not window:
            return HealthCheckResult(
                service=service,
                status="unknown",
                latency_ms=0,
                last_checked=datetime.now(timezone.utc).isoformat(),
                details={"mode": "passive", "sample_size": 0},
            )

        successes = sum(1 for r in window if r.success)
        total = len(window)
        rate = successes / total
        avg_latency = int(sum(r.latency_ms for r in window) / total)
        last_ts = max(r.timestamp for r in window)
        last_error = None
        for r in reversed(window):
            if not r.success and r.error:
                last_error = r.error
                break

        if rate >= _HEALTHY_THRESHOLD:
            status = "healthy"
        elif rate >= _DEGRADED_THRESHOLD:
            status = "degraded"
        else:
            status = "down"

        return HealthCheckResult(
            service=service,
            status=status,
            latency_ms=avg_latency,
            last_checked=datetime.fromtimestamp(last_ts, tz=timezone.utc).isoformat(),
            error=last_error,
            details={
                "mode": "passive",
                "success_rate": round(rate, 3),
                "sample_size": total,
            },
        )

    # ------------------------------------------------------------------
    # Active health checks
    # ------------------------------------------------------------------

    def _check_overpass(self) -> HealthCheckResult:
        """Probe the Overpass API status endpoint (free, no query cost)."""
        t0 = time.time()
        try:
            resp = requests.get(_OVERPASS_STATUS_URL, timeout=_PROBE_TIMEOUT)
            elapsed_ms = int((time.time() - t0) * 1000)
            if resp.status_code == 200:
                return HealthCheckResult(
                    service="overpass",
                    status="healthy",
                    latency_ms=elapsed_ms,
                    last_checked=datetime.now(timezone.utc).isoformat(),
                    details={"mode": "active"},
                )
            else:
                return HealthCheckResult(
                    service="overpass",
                    status="degraded",
                    latency_ms=elapsed_ms,
                    last_checked=datetime.now(timezone.utc).isoformat(),
                    error=f"HTTP {resp.status_code}",
                    details={"mode": "active"},
                )
        except requests.Timeout:
            elapsed_ms = int((time.time() - t0) * 1000)
            return HealthCheckResult(
                service="overpass",
                status="down",
                latency_ms=elapsed_ms,
                last_checked=datetime.now(timezone.utc).isoformat(),
                error="timeout",
                details={"mode": "active"},
            )
        except Exception as e:
            elapsed_ms = int((time.time() - t0) * 1000)
            return HealthCheckResult(
                service="overpass",
                status="down",
                latency_ms=elapsed_ms,
                last_checked=datetime.now(timezone.utc).isoformat(),
                error=str(e),
                details={"mode": "active"},
            )

    def _check_open_meteo(self) -> HealthCheckResult:
        """Probe the Open-Meteo archive API with a minimal request (free)."""
        t0 = time.time()
        params = {
            "latitude": 0,
            "longitude": 0,
            "start_date": "2024-01-01",
            "end_date": "2024-01-01",
            "daily": "temperature_2m_max",
        }
        try:
            resp = requests.get(
                _OPEN_METEO_PROBE_URL, params=params, timeout=_PROBE_TIMEOUT
            )
            elapsed_ms = int((time.time() - t0) * 1000)
            if resp.status_code == 200:
                return HealthCheckResult(
                    service="open_meteo",
                    status="healthy",
                    latency_ms=elapsed_ms,
                    last_checked=datetime.now(timezone.utc).isoformat(),
                    details={"mode": "active"},
                )
            else:
                return HealthCheckResult(
                    service="open_meteo",
                    status="degraded",
                    latency_ms=elapsed_ms,
                    last_checked=datetime.now(timezone.utc).isoformat(),
                    error=f"HTTP {resp.status_code}",
                    details={"mode": "active"},
                )
        except requests.Timeout:
            elapsed_ms = int((time.time() - t0) * 1000)
            return HealthCheckResult(
                service="open_meteo",
                status="down",
                latency_ms=elapsed_ms,
                last_checked=datetime.now(timezone.utc).isoformat(),
                error="timeout",
                details={"mode": "active"},
            )
        except Exception as e:
            elapsed_ms = int((time.time() - t0) * 1000)
            return HealthCheckResult(
                service="open_meteo",
                status="down",
                latency_ms=elapsed_ms,
                last_checked=datetime.now(timezone.utc).isoformat(),
                error=str(e),
                details={"mode": "active"},
            )

    def run_active_checks(self) -> None:
        """Run all active probes and store results. Called by the bg thread."""
        for name, check_fn in [
            ("overpass", self._check_overpass),
            ("open_meteo", self._check_open_meteo),
        ]:
            result = check_fn()
            with self._lock:
                prev = self._prev_status.get(name)
                self._active_results[name] = result
                self._prev_status[name] = result.status

            # Log result and any state transitions.
            if prev and prev != result.status:
                logger.warning(
                    "[health] %s status changed: %s -> %s (error=%s)",
                    name, prev, result.status, result.error,
                )
            else:
                logger.info(
                    "[health] %s: %s (%dms)",
                    name, result.status, result.latency_ms,
                )

    # ------------------------------------------------------------------
    # Combined status view
    # ------------------------------------------------------------------

    def get_all_status(self) -> Dict[str, Dict[str, Any]]:
        """Return current health for all monitored services.

        For Overpass and Open-Meteo: uses active probe results if available,
        falls back to passive data.
        For Google Maps: always uses passive data (no active probe).
        """
        out: Dict[str, Dict[str, Any]] = {}

        # Google Maps — passive only.
        gm = self._compute_passive_status("google_maps")
        out["google_maps"] = self._result_to_dict(gm)

        # Overpass / Open-Meteo — active preferred, passive fallback.
        for svc in ("overpass", "open_meteo"):
            with self._lock:
                active = self._active_results.get(svc)
            if active:
                out[svc] = self._result_to_dict(active)
            else:
                passive = self._compute_passive_status(svc)
                out[svc] = self._result_to_dict(passive)

        return out

    @staticmethod
    def _result_to_dict(result: HealthCheckResult) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "status": result.status,
            "latency_ms": result.latency_ms,
            "last_checked": result.last_checked,
        }
        if result.error:
            d["error"] = result.error
        if result.details:
            d.update(result.details)
        return d

    # ------------------------------------------------------------------
    # Background thread lifecycle
    # ------------------------------------------------------------------

    def _loop(self) -> None:
        """Background loop: run active checks, sleep, repeat."""
        logger.info("[health] Health monitor thread started (interval=%ds)", HEALTH_CHECK_INTERVAL)
        while not self._stop_event.is_set():
            try:
                self.run_active_checks()
            except Exception:
                logger.exception("[health] Unexpected error in active health checks")
            self._stop_event.wait(timeout=HEALTH_CHECK_INTERVAL)
        logger.info("[health] Health monitor thread stopped")

    def start(self) -> None:
        """Start the background health monitor thread (idempotent)."""
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Signal the health monitor thread to stop."""
        self._stop_event.set()


# ---------------------------------------------------------------------------
# Module-level singleton and public API
# ---------------------------------------------------------------------------

_monitor = HealthMonitor()


def record_call(
    service: str,
    success: bool,
    latency_ms: int,
    error: Optional[str] = None,
) -> None:
    """Record an API call outcome for passive health tracking.

    Called from API clients (GoogleMapsClient, OverpassHTTPClient, weather).
    Failures in health tracking never propagate — callers wrap in try/except.
    """
    _monitor.record_call(service, success, latency_ms, error)


def get_status() -> Dict[str, Dict[str, Any]]:
    """Get current health status for all monitored API services."""
    return _monitor.get_all_status()


def start_monitor() -> None:
    """Start the background health check thread."""
    _monitor.start()


def stop_monitor() -> None:
    """Stop the background health check thread."""
    _monitor.stop()
