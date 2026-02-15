# NES-32: Weather Context for Transit & Walkability Insights

**Overall Progress:** `100%`

## TLDR

Add weather context to the Getting Around insight so transit/walkability narratives acknowledge climate realities. Fetch 10 years of historical daily weather from Open-Meteo (free, no key), aggregate into monthly normals, and append 1-2 conditional sentences to the existing insight when snow, extreme heat, extreme cold, or frequent rain materially changes the walkability story. Informational only — no score impact.

## Critical Decisions

- **Informational, not scored:** Weather context is a qualifier on existing transit/walkability insights, not a new Tier 2 dimension. No score impact, no scoring model version bump.
- **Open-Meteo Historical Weather API:** Free, no key, accepts lat/lng, returns daily observed data back to 1940. One call per evaluation (before cache).
- **Inline in Getting Around insight:** Weather sentences append to the existing `parts` array in `_insight_getting_around()`. Same `<p>`, not a separate element.
- **Infrastructure-first:** Uses lat/lng coordinates so it works for any geography from day one, not hard-coded to Westchester.
- **Aggressive caching:** 90-day TTL on computed summaries. Cache key rounded to 2 decimal places (~1km) so nearby addresses share cache entries. Climate normals don't change.
- **Thresholds in config dict:** Reasonable defaults, easy to tune. Only surface weather when it materially changes the story.

## Tasks

- [x] 🟩 **Step 1: Create `weather.py` module**
  - [x] 🟩 Define `WeatherSummary` dataclass (monthly temp highs/lows, precipitation days, snow days, annual aggregates)
  - [x] 🟩 Define threshold config dict at module top (`SNOW_DAYS_THRESHOLD = 10`, `EXTREME_HEAT_DAYS = 30`, `FREEZING_DAYS = 30`, `RAINY_DAYS = 150`, `ANNUAL_SNOWFALL_IN = 12`)
  - [x] 🟩 Implement `fetch_weather_data(lat, lng)` — calls Open-Meteo Historical API for 10 years of daily data (temperature_2m_max, temperature_2m_min, precipitation_sum, snowfall_sum), aggregates into `WeatherSummary`
  - [x] 🟩 Implement coordinate rounding helper for cache key generation (2 decimal places)
  - [x] 🟩 Add timeout handling, logging, and graceful `None` return on failure

- [x] 🟩 **Step 2: Add weather cache table to `models.py`**
  - [x] 🟩 Add `weather_cache` table to schema init (`cache_key TEXT PRIMARY KEY, summary_json TEXT NOT NULL, created_at TIMESTAMP`)
  - [x] 🟩 Implement `get_weather_cache(cache_key)` and `set_weather_cache(cache_key, summary_json)` with 90-day TTL
  - [x] 🟩 Follow Overpass cache pattern: swallow errors, never break an evaluation

- [x] 🟩 **Step 3: Integrate into evaluation pipeline (`property_evaluator.py`)**
  - [x] 🟩 Add `weather_summary: Optional[WeatherSummary]` field to `EvaluationResult` dataclass
  - [x] 🟩 Add weather as a parallel stage in `evaluate_property()` via the existing `ThreadPoolExecutor`
  - [x] 🟩 Assign result to `result.weather_summary` (graceful `None` on failure)

- [x] 🟩 **Step 4: Serialize and pass to insights (`app.py`)**
  - [x] 🟩 Add `_serialize_weather(summary)` helper — returns dict with annual/monthly stats or `None`
  - [x] 🟩 Add `"weather": _serialize_weather(...)` to `result_to_dict()`
  - [x] 🟩 Pass weather dict into `_insight_getting_around()` as new parameter
  - [x] 🟩 Update `generate_insights()` to thread weather data through

- [x] 🟩 **Step 5: Generate conditional weather sentences in `_insight_getting_around()`**
  - [x] 🟩 Add weather threshold evaluation logic — check snow, heat, cold, rain against config thresholds
  - [x] 🟩 Generate 1-2 natural-language sentences when thresholds are met (e.g., "Expect significant snow in winter — plan for that commute to feel longer from December through March")
  - [x] 🟩 Append to existing `parts` array; no output for mild climates
  - [x] 🟩 Handle multiple triggers gracefully (e.g., cold + snow → single combined sentence, not two redundant ones)

- [x] 🟩 **Step 6: Test with diverse locations**
  - [x] 🟩 Verify no weather sentence for mild climate (e.g., San Diego)
  - [x] 🟩 Verify snow/cold sentence for a snowy location (e.g., Buffalo, NY)
  - [x] 🟩 Verify heat sentence for hot climate (e.g., Phoenix, AZ)
  - [x] 🟩 Verify rain sentence for rainy climate (e.g., Seattle, WA)
  - [x] 🟩 Verify Westchester County address produces appropriate output
  - [x] 🟩 Verify cache hit on second evaluation for nearby address
  - [x] 🟩 Verify graceful degradation when Open-Meteo is unreachable
