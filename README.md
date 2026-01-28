# Westchester Property Evaluator

A command-line tool to evaluate rental properties in Westchester County against health, lifestyle, and budget criteria.

## What It Does

Given a property address, this tool automatically checks:

### Tier 1: Hard Disqualifiers (any fail = reject)
- **Gas station proximity**: Must be >500 feet from any gas station (benzene exposure research)
- **Highway proximity**: Must be >500 feet from I-95, Saw Mill, Hutch, etc.
- **High-volume roads**: Must be >500 feet from 4+ lane roads or numbered routes (US-1, NY-9, etc.)
- **Washer/dryer**: Must be IN the unit (not building laundry, not garage)
- **Central air**: Required (no window units)
- **Size**: Must be ≥1,700 sq ft
- **Bedrooms**: Must be ≥2
- **Rent**: Must be ≤$7,000/month

### Tier 2: Scored Preferences (0-60 points)
- **Park access** (0-20 pts): Quality park within 20 min walk = 20 pts, 30 min = 10 pts
- **Third Place** (0-15 pts): Quality third place within 20 min walk = 15 pts, 30 min = 8 pts
- **Budget** (0-15 pts): ≤$6,000 = 15 pts, ≤$6,500 = 10 pts
- **Metro North** (0-10 pts): Station within 20 min walk = 10 pts, 30 min = 5 pts

### Tier 3: Bonus Points
- Parking included: +5 pts
- Outdoor space (yard/balcony): +5 pts  
- 3+ bedrooms: +5 pts

## Urban Access Engine

The Urban Access Engine replaces the simple "transit station within 20 minutes" check with a multi-hub reachability analysis. It evaluates how well-connected a property is to the places that matter for daily life.

### What It Outputs

1. **Primary Transit Node** — nearest rail/subway/light-rail station with walk time, drive time (if far), frequency class, and parking info.

2. **Commute to Primary Hub** — travel time to a configurable primary hub (default: Grand Central Terminal) via transit or driving, whichever is faster. Shows a verdict: Great / OK / Painful.

3. **Reachability** — travel time to three additional hub categories:
   - **Major Airport** — nearest of JFK, LaGuardia, or Newark (configurable).
   - **Downtown** — nearest major commercial area (default: Downtown Manhattan).
   - **Major Hospital** — nearest large hospital (default: NewYork-Presbyterian).

   Each hub shows: best mode (transit vs. driving), total time, and a verdict bucket.

### Verdict Thresholds

| Category     | Great    | OK        | Painful   |
|-------------|----------|-----------|-----------|
| Primary Hub | <= 45 min | <= 75 min | > 75 min  |
| Airport     | <= 60 min | <= 90 min | > 90 min  |
| Downtown    | <= 40 min | <= 70 min | > 70 min  |
| Hospital    | <= 30 min | <= 60 min | > 60 min  |

### Configuration

Set these environment variables to customise destinations:

| Variable              | Default                                        | Description                        |
|-----------------------|------------------------------------------------|------------------------------------|
| `PRIMARY_HUB_ADDRESS` | `Grand Central Terminal, New York, NY`         | The main commute destination       |
| `AIRPORT_HUBS`        | JSON list of JFK / LGA / EWR                  | Airports to evaluate (nearest wins)|
| `DOWNTOWN_HUB`        | `Downtown Manhattan, New York, NY`             | Downtown cluster proxy             |
| `HOSPITAL_HUB`        | `NewYork-Presbyterian Hospital, New York, NY`  | Major hospital                     |

Example — override the primary hub:

```bash
export PRIMARY_HUB_ADDRESS="Penn Station, New York, NY"
```

Example — custom airports (JSON):

```bash
export AIRPORT_HUBS='[{"name": "JFK", "address": "JFK Airport, Queens, NY"}, {"name": "BOS", "address": "Boston Logan Airport, Boston, MA"}]'
```

### Caching

The engine caches all geocode and directions API results in-memory (keyed by origin/destination/mode). This avoids redundant API calls when multiple hubs share the same origin coordinates. The cache lives for the duration of the process.

### Cost Implications

The Urban Access Engine adds the following API calls per evaluation:

- **Geocoding**: 1 call per unique hub address (~4-5 hubs), cached after first use.
- **Distance Matrix**: Up to 2 calls per hub (transit + driving), cached.
- **Total additional cost**: ~$0.03-0.06 per property evaluation (on top of the base ~$0.02-0.05).

### Running Tests

```bash
python -m unittest test_urban_access -v
```

The test suite covers:
- Fallback behaviour when transit is unavailable (driving used, `fallback` flag set)
- Verdict classification stability at all boundary values
- Mode selection (transit vs. driving, whichever is faster)
- Full evaluation structure validation
- Cache hit verification

## Setup

### 1. Get a Google Maps API Key

You'll need a Google Cloud account with the following APIs enabled:
- Geocoding API
- Places API
- Distance Matrix API

Get your API key from: https://console.cloud.google.com/google/maps-apis

**Cost estimate**: ~$0.02-0.05 per property evaluated (mostly Places API calls)

### 2. Install Dependencies

```bash
pip install -r requirements.txt
```

### 3. Set Your API Key

```bash
export GOOGLE_MAPS_API_KEY="your-key-here"
```

Or pass it via `--api-key` flag.

### 4. (Optional) Add Walk Score

Create a `.env` file (or export the env var) with your Walk Score API key:

```bash
WALKSCORE_API_KEY="your-walkscore-key"
```

## Usage

### Basic Usage

```bash
python property_evaluator.py "123 Main St, Scarsdale, NY 10583"
```

### With Property Details

```bash
python property_evaluator.py "123 Main St, Scarsdale, NY 10583" \
    --rent 6200 \
    --sqft 1850 \
    --bedrooms 3 \
    --washer-dryer \
    --central-air \
    --parking
```

### JSON Output (for scripting)

```bash
python property_evaluator.py "123 Main St, Scarsdale, NY" --json
```

### Example Output

```
======================================================================
PROPERTY: 123 Main St, Scarsdale, NY 10583
RENT: $6,200/month
COORDINATES: 40.988765, -73.784532
======================================================================

TIER 1 CHECKS:
  ✓ Gas station: PASS — Nearest: Shell (1,245 ft)
  ✓ Highway: PASS — No highways within 500 feet
  ✓ High-volume road: PASS — No high-volume roads within 500 feet
  ✓ W/D in unit: PASS — Washer/dryer in unit confirmed
  ✓ Central air: PASS — Central air confirmed
  ✓ Size: PASS — 1,850 sq ft
  ✓ Bedrooms: PASS — 3 BR
  ✓ Rent: PASS — $6,200/month

✅ PASSED TIER 1

TIER 2 SCORE: 52/60
  - Park access: 20 pts — Scarsdale Village Park (4.5★, 234 reviews) — 12 min walk
  - Third Place access: 15 pts — Local: Lange's Deli — 8 min walk
  - Budget: 10 pts — $6,200 — within target range
  - Metro North access: 7 pts — Scarsdale Station — 18 min walk

TIER 3 BONUS: +10 pts
  - Parking: +5 — Parking included
  - Extra bedroom: +5 — 3 bedrooms

======================================================================
TOTAL SCORE: 62
======================================================================
```

## Green Escape (Daily Outdoor Life)

The **Green Escape** engine (`green_space.py`) evaluates parks and green spaces
for daily outdoor routines with a stroller/toddler. It replaces the old single
park-access line item with a richer model.

### What it does

1. **Finds real parks/green spaces** near the address using Google Places
   (type-based + keyword-based searches) and filters out stores, hotels, and
   generic POIs.
2. **Computes a "Daily Walk Value" score (0–10)** for each space, based on four
   subscores:
   - Walk time (0–3): ≤10 min best, 11–20 good, 21–30 marginal, >30 poor.
   - Size & loop potential (0–3): OSM polygon area + footway/path density when
     available; falls back to review count + name keywords as a weak proxy
     (labeled "estimate").
   - Quality proxy (0–2): Google rating + review count with thresholds.
   - Nature feel (0–2): OSM tags (forest, water, nature reserve) + name keywords.
3. **Displays comprehensive results**:
   - "Best Daily Park" — highest-scoring space, with full subscore breakdown and
     "Why this park?" reasons.
   - "Other Nearby Green Spaces" — top 8, shown regardless of pass/fail, each
     marked PASS / BORDERLINE / FAIL with a reason.
4. **Avoids false positives**: hard-filters out stores, hotels, restaurants, and
   name patterns like "Sam's Club" or "Holiday Inn."

### Data sources

| Source | Used for |
|--------|----------|
| Google Places Nearby Search | Find parks, campgrounds, national parks |
| Google Places Text Search | Find trails, greenways, preserves by keyword |
| Google Distance Matrix | Walking time from address to each space |
| OpenStreetMap Overpass API | Polygon area, footway/path count, nature tags |

### Limitations

- **Acreage is estimated** from OSM bounding-box polygons when available.
  Coverage varies by area. When no OSM polygon exists, review count + name
  keywords are used as a weak proxy (marked "estimate" in the UI).
- **Walk times** come from Google Distance Matrix and assume sidewalk availability.
- **Trail detection** depends on OSM data quality; some trails may not have
  `highway=footway` tags.
- **Overpass API** may be slow or rate-limited under heavy load. Results are
  cached for 10 minutes.

### Tuning guide

Thresholds are defined at the top of `green_space.py`. Key values to adjust:

| Parameter | Default | Effect |
|-----------|---------|--------|
| `WALK_TIME_EXCELLENT` | 10 min | Full walk-time score (3/3) |
| `WALK_TIME_GOOD` | 20 min | Good walk-time score (~2/3) |
| `WALK_TIME_MARGINAL` | 30 min | Hard cutoff for inclusion |
| `QUALITY_HIGH_RATING` | 4.3 | Full quality-rating score |
| `QUALITY_MID_RATING` | 3.8 | Moderate quality-rating score |
| `QUALITY_HIGH_REVIEWS` | 200 | Full review-volume score |
| `QUALITY_MID_REVIEWS` | 50 | Moderate review-volume score |
| `SIZE_LARGE_SQM` | 40,000 (~10 ac) | Full size score from OSM |
| `SIZE_MEDIUM_SQM` | 12,000 (~3 ac) | Moderate size score from OSM |
| `PATH_NETWORK_DENSE` | 5 segments | Full loop-potential score |
| `PATH_NETWORK_MODERATE` | 2 segments | Moderate loop-potential score |
| `DAILY_PARK_MIN_TOTAL` | 5/10 | Minimum Daily Value to PASS |
| `DEFAULT_RADIUS_M` | 2,000m | Initial search radius |
| `EXPANDED_RADIUS_M` | 5,000m | Expanded if <3 results |
| `NEARBY_LIST_SIZE` | 8 | How many spaces in the nearby list |

### Caching

API results are cached in-memory with a 10-minute TTL. Cache keys are based on
`(lat, lng, radius)` for Places/Distance Matrix and query text for Overpass.
This prevents redundant calls when the same address is evaluated multiple times
in a session.

### Tests

Run with:

```bash
pip install pytest
python -m pytest test_green_space.py -v
```

Tests verify:
1. Non-park POIs are excluded (Sam's Club, Walmart, hotels)
2. Trail/greenway entities are included via keyword search
3. Results always include a nearby list even when nothing passes strict criteria

## Criteria Definitions

### What counts as a "quality park"?
- Must have ≥4.0 stars on Google with ≥50 reviews, OR
- Must be ≥5 acres (if acreage data available)
- Small playgrounds are excluded
- The goal: a 20-30 min walking loop with nature vibes, stroller-friendly

### What counts as a third place?
**Included examples:**
- Cafes, bakeries, coffee shops, wine bars, bookstores with cafes

**Required traits:**
- Serves drinks or food
- Allows seating
- Not fast food
- Not a convenience store

### What counts as a "high-volume road"?
- Any highway/freeway (I-95, I-87, Saw Mill, Hutch, etc.)
- Numbered state/US routes (US-1, NY-9, NY-9A, NY-22, etc.)
- Roads with 4+ lanes
- Central Avenue, Boston Post Road, etc.

## Extending This Tool

### Adding a Zillow/Redfin scraper

The tool accepts listing data via command-line flags, but you could add a scraper module to auto-populate from URLs. See `property_evaluator.py` — the `PropertyListing` dataclass is designed to be populated from any source.

### Adding a monitoring/notification system

To get alerts when new listings match your criteria:
1. Set up a cron job or GitHub Action to poll Zillow/Redfin RSS feeds
2. Run each new listing through this evaluator
3. Send notifications (email, Slack, text) for properties that pass Tier 1 and score above a threshold

### Adding more data sources

The tool uses:
- **Google Places API** for gas stations, parks, cafes, transit
- **OpenStreetMap Overpass API** for road classification

You could enhance with:
- County tax records for more accurate square footage
- Walk Score API for additional walkability data
- School district boundaries (for future planning)

## Troubleshooting

### "Geocoding failed" error
- Check that the address is complete and valid
- Ensure your Google Maps API key has Geocoding API enabled

### "UNKNOWN" results for listing criteria
- These come from missing data — add the flags (--washer-dryer, --central-air, etc.)
- The tool will note what needs manual verification

### Rate limiting
- The free tier of Google Maps APIs should handle ~100 properties/day
- Overpass API has no key requirement but may rate limit heavy usage
