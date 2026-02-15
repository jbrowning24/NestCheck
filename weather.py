"""
Weather Context — historical climate normals for transit/walkability insights.

Fetches 10 years of daily observed weather from the Open-Meteo Historical
Weather API (free, no key required) and aggregates into monthly normals.
Used to add contextual sentences to the Getting Around insight when climate
materially affects the walkability story (e.g., heavy snow, extreme heat).

Data source:
  - Open-Meteo Historical Weather API (archive-api.open-meteo.com)
  - ERA5 reanalysis data, ~0.25° grid resolution

Limitations:
  - Reanalysis data smooths local microclimates; actual conditions at a
    specific address may differ from the grid cell average.
  - Snowfall is modeled from precipitation + temperature; true accumulation
    depends on ground temperature, wind, and melt cycles.
  - 10-year averages may not capture long-term trends (warming, shifting
    precipitation patterns).
"""

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Optional, List

import requests
from models import get_weather_cache, set_weather_cache
from nc_trace import get_trace

logger = logging.getLogger(__name__)


# =============================================================================
# CONFIGURATION — thresholds for "material" weather context
# =============================================================================
# Only surface weather when it materially changes the walkability story.
# These are reasonable defaults; tune after seeing real output across climates.

WEATHER_THRESHOLDS = {
    "annual_snowfall_in": 12,       # inches/year — triggers snow context
    "snow_days": 10,                # days/year with >0.1" snowfall
    "extreme_heat_days": 30,        # days/year above 90°F (32.2°C)
    "freezing_days": 30,            # days/year with high temp below 32°F (0°C)
    "rainy_days": 150,              # days/year with >0.01" (0.25mm) precipitation
}

# Open-Meteo API configuration
_API_BASE = "https://archive-api.open-meteo.com/v1/archive"
_API_TIMEOUT = 15  # seconds — generous; Open-Meteo is generally fast
_REFERENCE_YEARS = 10  # years of daily data to average


# =============================================================================
# DATA CLASSES
# =============================================================================

@dataclass
class MonthlyNormals:
    """Climate normals for a single calendar month."""
    month: int                      # 1-12
    avg_high_f: float               # average daily high (°F)
    avg_low_f: float                # average daily low (°F)
    avg_precip_days: float          # days with precipitation > 0.25mm
    avg_snow_days: float            # days with snowfall > 0.1" (2.5mm)
    avg_snowfall_in: float          # total snowfall in inches


@dataclass
class WeatherSummary:
    """Aggregated climate summary for a location.

    Computed from 10 years of daily observed data. Used to generate
    contextual weather sentences in transit/walkability insights.
    """
    # Annual aggregates
    annual_avg_high_f: float
    annual_avg_low_f: float
    annual_precip_days: float       # total rainy/snowy days per year
    annual_snow_days: float         # days with measurable snowfall
    annual_snowfall_in: float       # total snowfall in inches
    extreme_heat_days: float        # days/year with high > 90°F
    freezing_days: float            # days/year with high < 32°F

    # Monthly breakdown (12 entries, Jan–Dec)
    monthly: List[MonthlyNormals] = field(default_factory=list)

    # Which thresholds were triggered (populated by check_thresholds)
    triggers: List[str] = field(default_factory=list)


# =============================================================================
# CACHE KEY GENERATION
# =============================================================================

def _round_coords(lat: float, lng: float) -> str:
    """Round coordinates to 2 decimal places (~1km) for cache key.

    Nearby addresses share the same climate normals — no reason to re-fetch
    for addresses 500 feet apart.
    """
    return f"{lat:.2f},{lng:.2f}"


# =============================================================================
# OPEN-METEO API CLIENT
# =============================================================================

def _fetch_daily_data(lat: float, lng: float) -> Optional[dict]:
    """Fetch 10 years of daily weather data from Open-Meteo.

    Returns the raw JSON response dict, or None on failure.
    """
    trace = get_trace()
    t0 = time.time()

    # Date range: 10 full calendar years ending last year
    import datetime as dt
    end_year = dt.date.today().year - 1
    start_year = end_year - _REFERENCE_YEARS + 1
    start_date = f"{start_year}-01-01"
    end_date = f"{end_year}-12-31"

    params = {
        "latitude": lat,
        "longitude": lng,
        "start_date": start_date,
        "end_date": end_date,
        "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum,snowfall_sum",
        "temperature_unit": "fahrenheit",
        "precipitation_unit": "inch",
        "timezone": "auto",
    }

    try:
        resp = requests.get(_API_BASE, params=params, timeout=_API_TIMEOUT)
        elapsed_ms = (time.time() - t0) * 1000

        if trace:
            trace.record_api_call(
                service="open_meteo",
                endpoint="archive",
                elapsed_ms=elapsed_ms,
                status_code=resp.status_code,
                provider_status="OK" if resp.ok else "ERROR",
            )

        if not resp.ok:
            logger.warning(
                "Open-Meteo API returned %d for (%.2f, %.2f)",
                resp.status_code, lat, lng,
            )
            return None

        return resp.json()

    except requests.Timeout:
        logger.warning("Open-Meteo API timed out for (%.2f, %.2f)", lat, lng)
        if trace:
            trace.record_api_call(
                service="open_meteo",
                endpoint="archive",
                elapsed_ms=(time.time() - t0) * 1000,
                status_code=0,
                provider_status="TIMEOUT",
            )
        return None
    except Exception:
        logger.warning(
            "Open-Meteo API request failed for (%.2f, %.2f)",
            lat, lng, exc_info=True,
        )
        return None


# =============================================================================
# AGGREGATION — daily data → monthly normals → annual summary
# =============================================================================

def _aggregate(raw: dict) -> Optional[WeatherSummary]:
    """Aggregate raw daily data into a WeatherSummary.

    Expects the Open-Meteo response dict with daily arrays for
    temperature_2m_max, temperature_2m_min, precipitation_sum, snowfall_sum.
    Returns None if the data is missing or malformed.
    """
    daily = raw.get("daily")
    if not daily:
        return None

    dates = daily.get("time", [])
    highs = daily.get("temperature_2m_max", [])
    lows = daily.get("temperature_2m_min", [])
    precip = daily.get("precipitation_sum", [])
    snow = daily.get("snowfall_sum", [])

    if not dates or len(dates) != len(highs):
        return None

    # Accumulate per-month totals across all years
    # month_data[month] = { highs: [], lows: [], precip_days: int,
    #                        snow_days: int, snowfall_in: float }
    month_data = {m: {"highs": [], "lows": [], "precip_days": 0,
                       "snow_days": 0, "snowfall_in": 0.0}
                  for m in range(1, 13)}

    total_extreme_heat = 0
    total_freezing = 0
    year_count = _REFERENCE_YEARS

    for i, date_str in enumerate(dates):
        if i >= len(highs) or highs[i] is None:
            continue

        month = int(date_str[5:7])  # "2020-01-15" → 1
        md = month_data[month]

        high = highs[i]
        low = lows[i] if i < len(lows) and lows[i] is not None else None

        md["highs"].append(high)
        if low is not None:
            md["lows"].append(low)

        # Precipitation day: > 0.01 inches (0.25mm)
        if i < len(precip) and precip[i] is not None and precip[i] > 0.01:
            md["precip_days"] += 1

        # Snowfall: Open-Meteo returns cm when using inch unit for precip,
        # but with precipitation_unit=inch, snowfall_sum is in inches.
        if i < len(snow) and snow[i] is not None and snow[i] > 0.1:
            md["snow_days"] += 1
        if i < len(snow) and snow[i] is not None:
            md["snowfall_in"] += snow[i]

        # Extreme heat: high > 90°F
        if high > 90:
            total_extreme_heat += 1

        # Freezing day: high < 32°F
        if high < 32:
            total_freezing += 1

    # Build monthly normals (averaged over reference years)
    monthly = []
    total_precip_days = 0
    total_snow_days = 0
    total_snowfall_in = 0.0

    for m in range(1, 13):
        md = month_data[m]
        avg_high = sum(md["highs"]) / len(md["highs"]) if md["highs"] else 0
        avg_low = sum(md["lows"]) / len(md["lows"]) if md["lows"] else 0
        precip_days = md["precip_days"] / year_count
        snow_days = md["snow_days"] / year_count
        snowfall_in = md["snowfall_in"] / year_count

        total_precip_days += precip_days
        total_snow_days += snow_days
        total_snowfall_in += snowfall_in

        monthly.append(MonthlyNormals(
            month=m,
            avg_high_f=round(avg_high, 1),
            avg_low_f=round(avg_low, 1),
            avg_precip_days=round(precip_days, 1),
            avg_snow_days=round(snow_days, 1),
            avg_snowfall_in=round(snowfall_in, 1),
        ))

    all_highs = [h for md in month_data.values() for h in md["highs"]]
    all_lows = [l for md in month_data.values() for l in md["lows"]]

    return WeatherSummary(
        annual_avg_high_f=round(sum(all_highs) / len(all_highs), 1) if all_highs else 0,
        annual_avg_low_f=round(sum(all_lows) / len(all_lows), 1) if all_lows else 0,
        annual_precip_days=round(total_precip_days, 1),
        annual_snow_days=round(total_snow_days, 1),
        annual_snowfall_in=round(total_snowfall_in, 1),
        extreme_heat_days=round(total_extreme_heat / year_count, 1),
        freezing_days=round(total_freezing / year_count, 1),
        monthly=monthly,
    )


# =============================================================================
# THRESHOLD EVALUATION
# =============================================================================

def check_thresholds(summary: WeatherSummary) -> WeatherSummary:
    """Evaluate which weather thresholds are triggered.

    Populates summary.triggers with string keys matching triggered
    conditions. Returns the same summary for chaining.
    """
    triggers = []

    if summary.annual_snowfall_in >= WEATHER_THRESHOLDS["annual_snowfall_in"]:
        triggers.append("snow")
    elif summary.annual_snow_days >= WEATHER_THRESHOLDS["snow_days"]:
        # Snow days alone can trigger even if total accumulation is borderline
        triggers.append("snow")

    if summary.extreme_heat_days >= WEATHER_THRESHOLDS["extreme_heat_days"]:
        triggers.append("extreme_heat")

    if summary.freezing_days >= WEATHER_THRESHOLDS["freezing_days"]:
        triggers.append("freezing")

    if summary.annual_precip_days >= WEATHER_THRESHOLDS["rainy_days"]:
        triggers.append("rain")

    summary.triggers = triggers
    return summary


# =============================================================================
# PUBLIC API
# =============================================================================

def get_weather_summary(lat: float, lng: float) -> Optional[WeatherSummary]:
    """Fetch and aggregate weather data for a location.

    Checks the SQLite cache first (90-day TTL, keyed by rounded coordinates).
    On cache miss, calls Open-Meteo, aggregates, caches, and returns.
    Returns None on any failure — weather is optional context.
    """
    cache_key = _round_coords(lat, lng)

    # Check cache
    cached = get_weather_cache(cache_key)
    if cached is not None:
        try:
            return _deserialize(json.loads(cached))
        except Exception:
            logger.warning("Failed to deserialize cached weather data", exc_info=True)

    # Fetch from Open-Meteo
    raw = _fetch_daily_data(lat, lng)
    if raw is None:
        return None

    summary = _aggregate(raw)
    if summary is None:
        return None

    check_thresholds(summary)

    # Cache the computed summary (not the raw daily data)
    try:
        set_weather_cache(cache_key, json.dumps(_serialize(summary)))
    except Exception:
        logger.warning("Failed to cache weather summary", exc_info=True)

    return summary


# =============================================================================
# SERIALIZATION — for cache storage and result_to_dict
# =============================================================================

def _serialize(summary: WeatherSummary) -> dict:
    """Convert WeatherSummary to a plain dict for JSON storage."""
    return {
        "annual_avg_high_f": summary.annual_avg_high_f,
        "annual_avg_low_f": summary.annual_avg_low_f,
        "annual_precip_days": summary.annual_precip_days,
        "annual_snow_days": summary.annual_snow_days,
        "annual_snowfall_in": summary.annual_snowfall_in,
        "extreme_heat_days": summary.extreme_heat_days,
        "freezing_days": summary.freezing_days,
        "triggers": summary.triggers,
        "monthly": [
            {
                "month": m.month,
                "avg_high_f": m.avg_high_f,
                "avg_low_f": m.avg_low_f,
                "avg_precip_days": m.avg_precip_days,
                "avg_snow_days": m.avg_snow_days,
                "avg_snowfall_in": m.avg_snowfall_in,
            }
            for m in summary.monthly
        ],
    }


def _deserialize(data: dict) -> WeatherSummary:
    """Reconstruct WeatherSummary from a plain dict (cache hit)."""
    monthly = [
        MonthlyNormals(**m)
        for m in data.get("monthly", [])
    ]
    return WeatherSummary(
        annual_avg_high_f=data["annual_avg_high_f"],
        annual_avg_low_f=data["annual_avg_low_f"],
        annual_precip_days=data["annual_precip_days"],
        annual_snow_days=data["annual_snow_days"],
        annual_snowfall_in=data["annual_snowfall_in"],
        extreme_heat_days=data["extreme_heat_days"],
        freezing_days=data["freezing_days"],
        monthly=monthly,
        triggers=data.get("triggers", []),
    )


def serialize_for_result(summary: Optional[WeatherSummary]) -> Optional[dict]:
    """Serialize WeatherSummary for result_to_dict output.

    Public helper called from app.py. Returns None when summary is absent
    (API failure / old snapshots), which the insight generator uses to skip
    weather context.
    """
    if not summary:
        return None
    return _serialize(summary)
