"""
Urban Access Engine

Models reachable hubs and daily utility from a given property location.
Replaces the simple "transit station within 20 minutes" approach with a
multi-hub reachability analysis that accounts for transit and driving modes,
caches API results, and outputs verdict buckets (Great / OK / Painful).

Configuration (env vars):
    PRIMARY_HUB_ADDRESS  – default: "Grand Central Terminal, New York, NY"
    AIRPORT_HUBS         – JSON list; default: JFK, LGA, EWR
    DOWNTOWN_HUB         – default: "Downtown Manhattan, New York, NY"
    HOSPITAL_HUB         – default: "NewYork-Presbyterian Hospital, New York, NY"
"""

import os
import hashlib
from dataclasses import dataclass, field
from typing import Optional, List, Tuple, Dict, Any

# ---------------------------------------------------------------------------
# Verdict thresholds (minutes) – Great / OK / Painful
# ---------------------------------------------------------------------------
VERDICT_THRESHOLDS = {
    "primary_hub":  (45, 75),    # <=45 Great, <=75 OK, >75 Painful
    "airport":      (60, 90),
    "downtown":     (40, 70),
    "hospital":     (30, 60),
}


def _verdict(minutes: int, category: str) -> str:
    """Return Great / OK / Painful for *minutes* in *category*."""
    great, ok = VERDICT_THRESHOLDS.get(category, (45, 75))
    if minutes <= great:
        return "Great"
    if minutes <= ok:
        return "OK"
    return "Painful"


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class HubReachability:
    """Reachability result for a single destination hub."""
    hub_name: str
    category: str            # "airport" | "downtown" | "hospital"
    best_mode: str           # "transit" | "driving"
    total_time_min: int
    verdict: str             # "Great" | "OK" | "Painful"
    fallback: bool = False   # True when transit unavailable, fell back to driving


@dataclass
class PrimaryHubCommute:
    """Commute result to the primary hub (e.g. Grand Central Terminal)."""
    hub_name: str
    hub_address: str
    mode: str                # "transit" | "driving"
    time_min: int
    verdict: str
    fallback: bool = False


@dataclass
class UrbanAccessResult:
    """Full output of the Urban Access Engine."""
    primary_transit: Optional[Dict[str, Any]] = None
    primary_hub_commute: Optional[PrimaryHubCommute] = None
    reachability_hubs: List[HubReachability] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

class UrbanAccessEngine:
    """
    Evaluates urban access from a property location.

    Parameters
    ----------
    maps : GoogleMapsClient
        An initialised Google Maps client (from property_evaluator).
    lat, lng : float
        Property coordinates.
    """

    # Class-level cache shared across instances within the same process.
    # Key: md5(origin_str + "|" + dest_str + "|" + mode)
    # Value: travel time in minutes (int) or None
    _cache: Dict[str, Optional[int]] = {}

    def __init__(self, maps, lat: float, lng: float):
        self.maps = maps
        self.lat = lat
        self.lng = lng

        # Configurable destinations via env vars
        self.primary_hub_address = os.environ.get(
            "PRIMARY_HUB_ADDRESS",
            "Grand Central Terminal, New York, NY",
        )

        self.airport_hubs: List[Dict[str, str]] = _load_airport_hubs()
        self.downtown_hub_address = os.environ.get(
            "DOWNTOWN_HUB",
            "Downtown Manhattan, New York, NY",
        )
        self.hospital_hub_address = os.environ.get(
            "HOSPITAL_HUB",
            "NewYork-Presbyterian Hospital, New York, NY",
        )

    # ------------------------------------------------------------------
    # Caching helpers
    # ------------------------------------------------------------------

    @classmethod
    def clear_cache(cls):
        """Clear the directions / geocode cache (useful in tests)."""
        cls._cache.clear()

    def _cache_key(self, origin: str, dest: str, mode: str) -> str:
        raw = f"{origin}|{dest}|{mode}"
        return hashlib.md5(raw.encode()).hexdigest()

    def _geocode_cached(self, address: str) -> Tuple[float, float]:
        """Geocode with caching."""
        key = self._cache_key("geocode", address, "")
        if key in self._cache:
            return self._cache[key]
        result = self.maps.geocode(address)
        self._cache[key] = result
        return result

    def _travel_time(
        self,
        origin: Tuple[float, float],
        dest: Tuple[float, float],
        mode: str,
    ) -> Optional[int]:
        """
        Return travel time in minutes between *origin* and *dest* using
        *mode* ("transit" or "driving").  Returns None when the route is
        unreachable.  Results are cached.
        """
        origin_str = f"{origin[0]:.6f},{origin[1]:.6f}"
        dest_str = f"{dest[0]:.6f},{dest[1]:.6f}"
        key = self._cache_key(origin_str, dest_str, mode)

        if key in self._cache:
            return self._cache[key]

        try:
            if mode == "transit":
                minutes = self.maps.transit_time(origin, dest)
            else:
                minutes = self.maps.driving_time(origin, dest)

            if minutes == 9999:
                result = None
            else:
                result = minutes
        except Exception:
            result = None

        self._cache[key] = result
        return result

    def _best_travel(
        self,
        dest: Tuple[float, float],
    ) -> Tuple[Optional[int], str, bool]:
        """
        Try transit first; fall back to driving.

        Returns (time_min, mode_label, is_fallback).
        """
        origin = (self.lat, self.lng)
        transit_time = self._travel_time(origin, dest, "transit")
        driving_time = self._travel_time(origin, dest, "driving")

        if transit_time is not None and driving_time is not None:
            if transit_time <= driving_time:
                return transit_time, "transit", False
            else:
                return driving_time, "driving", False
        if transit_time is not None:
            return transit_time, "transit", False
        if driving_time is not None:
            return driving_time, "driving", True  # fallback
        return None, "unknown", True

    # ------------------------------------------------------------------
    # Primary hub commute
    # ------------------------------------------------------------------

    def get_primary_hub_commute(self) -> Optional[PrimaryHubCommute]:
        """Commute time from the property to the primary hub."""
        try:
            hub_coords = self._geocode_cached(self.primary_hub_address)
        except Exception:
            return None

        time_min, mode, fallback = self._best_travel(hub_coords)
        if time_min is None:
            return None

        # Derive a short display name from the address
        hub_name = self.primary_hub_address.split(",")[0].strip()

        return PrimaryHubCommute(
            hub_name=hub_name,
            hub_address=self.primary_hub_address,
            mode=mode,
            time_min=time_min,
            verdict=_verdict(time_min, "primary_hub"),
            fallback=fallback,
        )

    # ------------------------------------------------------------------
    # Reachability hubs
    # ------------------------------------------------------------------

    def _nearest_airport(self) -> Optional[HubReachability]:
        """Find the nearest airport from the configured list."""
        best: Optional[HubReachability] = None
        best_time = float("inf")

        for airport in self.airport_hubs:
            addr = airport["address"]
            name = airport["name"]
            try:
                coords = self._geocode_cached(addr)
            except Exception:
                continue

            time_min, mode, fallback = self._best_travel(coords)
            if time_min is None:
                continue

            if time_min < best_time:
                best_time = time_min
                best = HubReachability(
                    hub_name=name,
                    category="airport",
                    best_mode=mode,
                    total_time_min=time_min,
                    verdict=_verdict(time_min, "airport"),
                    fallback=fallback,
                )
        return best

    def _nearest_downtown(self) -> Optional[HubReachability]:
        """Reachability to the downtown cluster."""
        try:
            coords = self._geocode_cached(self.downtown_hub_address)
        except Exception:
            return None

        time_min, mode, fallback = self._best_travel(coords)
        if time_min is None:
            return None

        hub_name = self.downtown_hub_address.split(",")[0].strip()
        return HubReachability(
            hub_name=hub_name,
            category="downtown",
            best_mode=mode,
            total_time_min=time_min,
            verdict=_verdict(time_min, "downtown"),
            fallback=fallback,
        )

    def _nearest_hospital(self) -> Optional[HubReachability]:
        """Reachability to the nearest major hospital."""
        try:
            coords = self._geocode_cached(self.hospital_hub_address)
        except Exception:
            return None

        time_min, mode, fallback = self._best_travel(coords)
        if time_min is None:
            return None

        hub_name = self.hospital_hub_address.split(",")[0].strip()
        return HubReachability(
            hub_name=hub_name,
            category="hospital",
            best_mode=mode,
            total_time_min=time_min,
            verdict=_verdict(time_min, "hospital"),
            fallback=fallback,
        )

    def get_reachability_hubs(self) -> List[HubReachability]:
        """Return reachability data for airport, downtown, and hospital."""
        hubs: List[HubReachability] = []
        for fn in (self._nearest_airport, self._nearest_downtown, self._nearest_hospital):
            result = fn()
            if result is not None:
                hubs.append(result)
        return hubs

    # ------------------------------------------------------------------
    # Full evaluation
    # ------------------------------------------------------------------

    def evaluate(
        self,
        primary_transit_data: Optional[Dict[str, Any]] = None,
    ) -> UrbanAccessResult:
        """
        Run the full Urban Access Engine evaluation.

        Parameters
        ----------
        primary_transit_data :
            Pre-computed primary transit node dict (from find_primary_transit
            in property_evaluator).  Passed through as-is.
        """
        return UrbanAccessResult(
            primary_transit=primary_transit_data,
            primary_hub_commute=self.get_primary_hub_commute(),
            reachability_hubs=self.get_reachability_hubs(),
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_airport_hubs() -> List[Dict[str, str]]:
    """Load airport hub list from env or use defaults."""
    import json as _json
    raw = os.environ.get("AIRPORT_HUBS")
    if raw:
        try:
            return _json.loads(raw)
        except Exception:
            pass

    return [
        {"name": "JFK International Airport", "address": "JFK Airport, Queens, NY"},
        {"name": "LaGuardia Airport", "address": "LaGuardia Airport, Queens, NY"},
        {"name": "Newark Liberty Airport", "address": "Newark Liberty International Airport, Newark, NJ"},
    ]


# ---------------------------------------------------------------------------
# Serialisation helpers (for JSON output)
# ---------------------------------------------------------------------------

def hub_reachability_to_dict(hub: HubReachability) -> Dict[str, Any]:
    return {
        "hub_name": hub.hub_name,
        "category": hub.category,
        "best_mode": hub.best_mode,
        "total_time_min": hub.total_time_min,
        "verdict": hub.verdict,
        "fallback": hub.fallback,
    }


def primary_hub_commute_to_dict(commute: PrimaryHubCommute) -> Dict[str, Any]:
    return {
        "hub_name": commute.hub_name,
        "hub_address": commute.hub_address,
        "mode": commute.mode,
        "time_min": commute.time_min,
        "verdict": commute.verdict,
        "fallback": commute.fallback,
    }


def urban_access_result_to_dict(result: UrbanAccessResult) -> Dict[str, Any]:
    return {
        "primary_transit": result.primary_transit,
        "primary_hub_commute": (
            primary_hub_commute_to_dict(result.primary_hub_commute)
            if result.primary_hub_commute else None
        ),
        "reachability_hubs": [
            hub_reachability_to_dict(h) for h in result.reachability_hubs
        ],
    }
