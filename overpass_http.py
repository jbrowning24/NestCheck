"""
Coordinated Overpass API HTTP layer.

All Overpass HTTP requests in the application MUST go through this module.
It provides:
- SQLite cache check before any HTTP request (7-day TTL via models.py)
- Process-local rate limiting: 1 request/second minimum spacing
- Thread-safe request execution (no shared requests.Session)
- Retry with exponential backoff on 429/5xx (2 attempts, 2s/4s)
- nc_trace integration for observability

Rate limiting is per-process. With 2 gunicorn workers, worst case is
2 req/s to the public Overpass endpoint. When self-hosting Overpass,
set OVERPASS_BASE_URL env var and increase/remove the rate limit.

Cache: Uses models.overpass_cache_key() / get_overpass_cache() /
set_overpass_cache() with 7-day TTL. Cache hits bypass the rate limiter
entirely.
"""

import json
import logging
import os
import threading
import time
from typing import Any, Dict, Optional

import requests

from models import (
    get_overpass_cache,
    get_overpass_cache_stale,
    overpass_cache_key,
    set_overpass_cache,
)
from nc_trace import get_trace

logger = logging.getLogger(__name__)


class OverpassRateLimitError(Exception):
    """Raised when Overpass returns 429 or rate-limit indicators after all retries are exhausted."""

    pass


class OverpassQueryError(Exception):
    """Raised when Overpass returns a non-retryable error after all retries are exhausted."""

    pass


class OverpassHTTPClient:
    DEFAULT_TIMEOUT = 30  # seconds
    MIN_SPACING = 1.0  # seconds between HTTP requests
    MAX_RETRIES = 2
    RETRY_BACKOFF = [2, 4]  # seconds

    def __init__(self):
        self._lock = threading.Lock()
        self._last_request_time = 0.0
        self.base_url = os.environ.get(
            "OVERPASS_BASE_URL",
            "https://overpass-api.de/api/interpreter",
        )

    def query(
        self,
        overpass_ql: str,
        caller: str = "unknown",
        timeout: Optional[int] = None,
        ttl_days: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Execute an Overpass QL query with cache-first, rate-limited HTTP.

        Args:
            overpass_ql: The Overpass QL query string.
            caller: Identifier for trace attribution (e.g., "green_escape",
                    "road_noise", "overpass_client.get_nearby_roads").
            timeout: HTTP timeout in seconds. Defaults to DEFAULT_TIMEOUT.
            ttl_days: Cache TTL in days for this lookup; None uses default (7 days).

        Returns:
            Parsed JSON response dict from Overpass.

        Raises:
            OverpassRateLimitError: If Overpass returns 429 or rate-limit
                indicators after MAX_RETRIES attempts.
            OverpassQueryError: If Overpass returns a non-retryable error
                after MAX_RETRIES attempts.
        """
        if timeout is None:
            timeout = self.DEFAULT_TIMEOUT

        # --- Cache check (no lock needed, no rate limiter engagement) ---
        cache_key = overpass_cache_key(overpass_ql)
        try:
            cached = get_overpass_cache(cache_key, ttl_days=ttl_days)
        except Exception:
            logger.warning(
                "Overpass cache read failed for key, falling through to HTTP",
                exc_info=True,
            )
            cached = None
        if cached is not None:
            trace = get_trace()
            if trace:
                trace.record_api_call(
                    service="overpass",
                    endpoint=caller,
                    elapsed_ms=0,
                    status_code=200,
                    provider_status="cache_hit",
                )
            try:
                return json.loads(cached)
            except (json.JSONDecodeError, TypeError):
                # Corrupted cache entry — fall through to HTTP
                logger.warning(
                    "Corrupted Overpass cache entry for key %s, falling through to HTTP",
                    cache_key,
                )

        # --- Rate-limited HTTP ---
        try:
            last_exception = None
            for attempt in range(1 + self.MAX_RETRIES):
                try:
                    result = self._do_request(overpass_ql, caller, timeout)
                    # Cache on success
                    try:
                        set_overpass_cache(cache_key, json.dumps(result))
                    except Exception:
                        logger.warning(
                            "Failed to write Overpass cache for key %s",
                            cache_key,
                            exc_info=True,
                        )
                    return result
                except OverpassRateLimitError as e:
                    last_exception = e
                    if attempt < self.MAX_RETRIES:
                        sleep_time = self.RETRY_BACKOFF[attempt]
                        logger.info(
                            "Overpass rate limited (attempt %d/%d), sleeping %ds before retry [caller=%s]",
                            attempt + 1,
                            1 + self.MAX_RETRIES,
                            sleep_time,
                            caller,
                        )
                        time.sleep(sleep_time)
                        continue
                    raise
                except OverpassQueryError as e:
                    last_exception = e
                    if attempt < self.MAX_RETRIES and self._is_retryable_error(e):
                        sleep_time = self.RETRY_BACKOFF[attempt]
                        logger.info(
                            "Overpass query error (attempt %d/%d), sleeping %ds before retry [caller=%s]",
                            attempt + 1,
                            1 + self.MAX_RETRIES,
                            sleep_time,
                            caller,
                        )
                        time.sleep(sleep_time)
                        continue
                    raise

            # Should not reach here, but safety net
            raise last_exception or OverpassQueryError(
                "Overpass query failed after all retries"
            )
        except OverpassQueryError as e:
            if not self._is_retryable_error(e):
                raise
            return self._try_stale_fallback(cache_key, caller, e)
        except (
            OverpassRateLimitError,
            requests.exceptions.RequestException,
            json.JSONDecodeError,
        ) as e:
            return self._try_stale_fallback(cache_key, caller, e)

    def _do_request(
        self, overpass_ql: str, caller: str, timeout: int
    ) -> Dict[str, Any]:
        """Make a single rate-limited HTTP request to Overpass."""
        # Enforce minimum spacing
        with self._lock:
            now = time.monotonic()
            elapsed_since_last = now - self._last_request_time
            if elapsed_since_last < self.MIN_SPACING:
                wait = self.MIN_SPACING - elapsed_since_last
                time.sleep(wait)
            self._last_request_time = time.monotonic()

        # Fresh session per request (thread-safe, no shared state)
        start = time.monotonic()
        trace = get_trace()
        try:
            session = requests.Session()
            session.trust_env = False
            resp = session.post(
                self.base_url,
                data={"data": overpass_ql},
                timeout=timeout,
            )
            elapsed_ms = int((time.monotonic() - start) * 1000)
            status_code = resp.status_code

            # Handle HTTP errors (trace each branch with provider_status)
            if status_code == 429:
                if trace:
                    trace.record_api_call(
                        service="overpass",
                        endpoint=caller,
                        elapsed_ms=elapsed_ms,
                        status_code=429,
                        provider_status="rate_limit",
                    )
                raise OverpassRateLimitError(
                    f"Overpass 429 Too Many Requests [caller={caller}]"
                )
            if status_code == 504:
                if trace:
                    trace.record_api_call(
                        service="overpass",
                        endpoint=caller,
                        elapsed_ms=elapsed_ms,
                        status_code=504,
                        provider_status="timeout",
                    )
                raise OverpassQueryError(
                    f"Overpass 504 Gateway Timeout [caller={caller}]"
                )
            if status_code >= 400:
                if trace:
                    trace.record_api_call(
                        service="overpass",
                        endpoint=caller,
                        elapsed_ms=elapsed_ms,
                        status_code=status_code,
                        provider_status="http_error",
                    )
                raise OverpassQueryError(
                    f"Overpass HTTP {status_code} [caller={caller}]"
                )

            # Parse JSON body
            try:
                data = resp.json()
            except ValueError:
                if trace:
                    trace.record_api_call(
                        service="overpass",
                        endpoint=caller,
                        elapsed_ms=elapsed_ms,
                        status_code=status_code,
                        provider_status="parse_error",
                    )
                raise OverpassQueryError(
                    f"Overpass returned non-JSON response (HTTP {status_code}) [caller={caller}]"
                )

            # Check for rate-limit indicators in response body
            # Overpass may put errors in osm3s.remark or top-level remark
            remark = ""
            if isinstance(data, dict):
                osm3s = data.get("osm3s", {}) or {}
                remark = str(
                    osm3s.get("remark") or data.get("remark") or ""
                )

            remark_lower = remark.lower()
            if "too many requests" in remark_lower:
                if trace:
                    trace.record_api_call(
                        service="overpass",
                        endpoint=caller,
                        elapsed_ms=elapsed_ms,
                        status_code=status_code,
                        provider_status="rate_limit",
                    )
                raise OverpassRateLimitError(
                    f"Overpass rate limit in response body [caller={caller}]"
                )
            if any(
                indicator in remark_lower
                for indicator in [
                    "runtime error",
                    "timed out",
                    "out of memory",
                ]
            ):
                if trace:
                    trace.record_api_call(
                        service="overpass",
                        endpoint=caller,
                        elapsed_ms=elapsed_ms,
                        status_code=status_code,
                        provider_status="body_error",
                    )
                raise OverpassQueryError(
                    f"Overpass server error in response body: {remark[:100]} [caller={caller}]"
                )

            # Success — record trace after all validation passed
            if trace:
                trace.record_api_call(
                    service="overpass",
                    endpoint=caller,
                    elapsed_ms=elapsed_ms,
                    status_code=status_code,
                )

            try:
                from health_monitor import record_call
                record_call("overpass", True, elapsed_ms)
            except Exception:
                pass

            return data

        except (OverpassRateLimitError, OverpassQueryError):
            _elapsed = int((time.monotonic() - start) * 1000)
            try:
                from health_monitor import record_call
                record_call("overpass", False, _elapsed)
            except Exception:
                pass
            raise
        except requests.exceptions.Timeout:
            elapsed_ms = int((time.monotonic() - start) * 1000)
            if trace:
                trace.record_api_call(
                    service="overpass",
                    endpoint=caller,
                    elapsed_ms=elapsed_ms,
                    status_code=0,
                    provider_status="timeout",
                )
            try:
                from health_monitor import record_call
                record_call("overpass", False, elapsed_ms, "timeout")
            except Exception:
                pass
            raise OverpassQueryError(
                f"Overpass request timeout after {timeout}s [caller={caller}]"
            )
        except Exception as e:
            elapsed_ms = int((time.monotonic() - start) * 1000)
            if trace:
                trace.record_api_call(
                    service="overpass",
                    endpoint=caller,
                    elapsed_ms=elapsed_ms,
                    status_code=0,
                    provider_status="exception",
                )
            try:
                from health_monitor import record_call
                record_call("overpass", False, elapsed_ms, str(e))
            except Exception:
                pass
            raise OverpassQueryError(
                f"Overpass request failed: {e} [caller={caller}]"
            ) from e

    @staticmethod
    def _try_stale_fallback(
        cache_key: str, caller: str, original_exc: Exception
    ) -> Dict[str, Any]:
        """Attempt to serve stale cache after an availability failure.

        Raises the original exception if no usable stale entry exists.
        """
        stale = get_overpass_cache_stale(cache_key)
        if stale is not None:
            json_text, created_at = stale
            try:
                logger.warning(
                    "Overpass unavailable for %s; serving stale cache from %s",
                    caller,
                    created_at,
                )
                result = json.loads(json_text)
                result["_stale"] = True
                result["_stale_created_at"] = created_at
                trace = get_trace()
                if trace:
                    trace.record_api_call(
                        service="overpass",
                        endpoint=caller,
                        elapsed_ms=0,
                        status_code=0,
                        provider_status="stale_cache",
                    )
                return result
            except (json.JSONDecodeError, TypeError):
                # Corrupted stale cache — fall through to raise original
                pass
        raise original_exc

    @staticmethod
    def _is_retryable_error(e: OverpassQueryError) -> bool:
        """5xx errors, timeouts, and server body errors are retryable. 4xx are not."""
        msg = str(e).lower()
        if "timeout" in msg or "server error" in msg:
            return True
        # Match "HTTP 5xx" patterns (500, 502, 503, 504, etc.)
        for code in ("500", "502", "503", "504"):
            if code in msg:
                return True
        return False


# Module-level singleton — all callers in this process share one instance
_client = OverpassHTTPClient()


def overpass_query(
    overpass_ql: str,
    caller: str = "unknown",
    timeout: Optional[int] = None,
    ttl_days: Optional[int] = None,
) -> Dict[str, Any]:
    """Module-level convenience function. All Overpass calls should use this."""
    return _client.query(overpass_ql, caller=caller, timeout=timeout, ttl_days=ttl_days)
