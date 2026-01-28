# NestCheck

**Know before you move.** Evaluate any U.S. address for walkability, green space, transit, schools, and daily-life quality — in one report.

## What It Is

NestCheck is a livability evaluation tool. Enter any U.S. address and get a scored report covering:

- **Health & Safety** — Distance from gas stations, highways, and high-volume roads
- **Green Escape** — Quality parks, trails, and nature within walking distance
- **Urban Access** — Transit options, commute times, and connectivity to major hubs
- **Family & Schooling** — Nearby schools, childcare, and family-friendly infrastructure
- **Daily Essentials** — Walkable groceries, cafes, and fitness
- **Final Score** — 0-100 livability score with full breakdown

## Who It's For

- **Families choosing where to live** — especially remote workers optimizing for daily life, not commute
- **Renters evaluating apartments** — compare addresses objectively before visiting
- **Homebuyers doing due diligence** — environmental and lifestyle checks before making an offer

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

- **$29 per report** — full livability evaluation for any address
- **Coming soon:** 5-packs, subscriptions, PDF export, saved reports
- **Revenue model:** pay-per-report with premium tiers for professionals and frequent movers
- Currently in free preview while payment integration (Stripe) is being built

## Live Demo

Deploy to [Render](https://render.com) to get a public URL. See deployment instructions below.

## Local Development

### Prerequisites

- Python 3.11+
- Google Maps API key (Places, Distance Matrix, Geocoding APIs enabled)
- (Optional) Walk Score API key

### Setup

```bash
# Clone the repo
git clone https://github.com/jbrowning24/NestCheck.git
cd NestCheck

# Install dependencies
pip install -r requirements.txt

# Set environment variables
export GOOGLE_MAPS_API_KEY="your-google-maps-key"
export WALKSCORE_API_KEY="your-walkscore-key"  # optional

# Run locally
python app.py
```

The app will be available at `http://localhost:5001`.

### Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `GOOGLE_MAPS_API_KEY` | Yes | Google Maps Platform API key |
| `WALKSCORE_API_KEY` | No | Walk Score API key (for walk/transit/bike scores) |
| `SECRET_KEY` | No | Flask session secret (auto-generated in production) |
| `PORT` | No | Port to bind (default: 5001) |
| `FLASK_DEBUG` | No | Set to "1" for debug mode |

### API Cost Estimate

~$0.02-0.05 per evaluation (mostly Google Places API calls). At scale, each report costs roughly $0.05 in API fees, supporting a healthy margin at $29/report.

## Deploy to Render

### One-click setup

1. Push this repo to GitHub
2. Go to [Render Dashboard](https://dashboard.render.com)
3. Click **New > Web Service**
4. Connect your GitHub repo
5. Render will auto-detect `render.yaml` and configure:
   - Build: `pip install -r requirements.txt`
   - Start: `gunicorn app:app --bind 0.0.0.0:$PORT --timeout 120 --workers 2`
6. Add environment variables:
   - `GOOGLE_MAPS_API_KEY` (required)
   - `WALKSCORE_API_KEY` (optional)
7. Deploy

### Manual deploy

```bash
# Install gunicorn if not already
pip install -r requirements.txt

# Run in production
gunicorn app:app --bind 0.0.0.0:$PORT --timeout 120 --workers 2
```

### Alternative: Fly.io

```bash
fly launch --name nestcheck
fly secrets set GOOGLE_MAPS_API_KEY="your-key"
fly deploy
```

## Architecture

```
app.py                    Flask web app (routes, template rendering)
property_evaluator.py     Core evaluation engine (scoring, API clients)
templates/
  index.html              Landing page + report template
  pricing.html            Pricing page
render.yaml               Render deployment config
Procfile                  Process file for PaaS platforms
requirements.txt          Python dependencies
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

```
User enters address
  → Geocode via Google Maps
  → Parallel API checks:
      ├─ Health/safety (gas stations, highways, roads)
      ├─ Green spaces (parks, trails, nature)
      ├─ Transit (stations, hubs, commute times)
      ├─ Schools & childcare
      ├─ Daily essentials (grocery, cafe, fitness)
      └─ Walk/Transit/Bike scores
  → Three-tier scoring:
      Tier 1: Pass/fail safety checks
      Tier 2: Quality-of-life scoring (normalized to 100)
      Tier 3: Bonus features (up to +15)
  → Final score: 0-100
```

### Scoring System

| Category | Max Points | What It Measures |
|----------|-----------|-----------------|
| Park & Green Access | 10 | Quality park within walking distance |
| Third Place | 10 | Cafe, bakery, or social space nearby |
| Provisioning | 10 | Grocery/supermarket access |
| Fitness | 10 | Gym or fitness center |
| Affordability | 10 | Monthly cost vs. thresholds |
| Transit Access | 10 | Train/subway proximity and frequency |
| **Subtotal** | **60** | Normalized to 100 |
| Bonus: Parking | +5 | If parking included |
| Bonus: Outdoor | +5 | Yard or balcony |
| Bonus: 3+ BR | +5 | Three or more bedrooms |
| **Final Score** | **0-100** | Capped at 100 |

## Data Sources

- **Google Maps Platform** — Places API, Distance Matrix API, Geocoding API
- **OpenStreetMap** — Road classification via Overpass API
- **Walk Score** — Walk, Transit, and Bike scores (when API key provided)

School and childcare results are from Google Places and may not reflect official district assignments.

## Disclaimer

NestCheck is a decision-support tool, not professional real estate, health, or legal advice. Scores are estimates based on publicly available data. Verify listing details, school assignments, and environmental conditions independently.

## License

Private — All rights reserved.
