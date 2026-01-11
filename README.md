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
- **Coffee shop** (0-15 pts): Local/approved chain within 20 min walk = 15 pts, 30 min = 8 pts
- **Budget** (0-15 pts): ≤$6,000 = 15 pts, ≤$6,500 = 10 pts
- **Metro North** (0-10 pts): Station within 20 min walk = 10 pts, 30 min = 5 pts

### Tier 3: Bonus Points
- Parking included: +5 pts
- Outdoor space (yard/balcony): +5 pts  
- 3+ bedrooms: +5 pts

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
  - Coffee shop access: 15 pts — Local: Lange's Deli — 8 min walk
  - Budget: 10 pts — $6,200 — within target range
  - Metro North access: 7 pts — Scarsdale Station — 18 min walk

TIER 3 BONUS: +10 pts
  - Parking: +5 — Parking included
  - Extra bedroom: +5 — 3 bedrooms

======================================================================
TOTAL SCORE: 62
======================================================================
```

## Criteria Definitions

### What counts as a "quality park"?
- Must have ≥4.0 stars on Google with ≥50 reviews, OR
- Must be ≥5 acres (if acreage data available)
- Small playgrounds are excluded
- The goal: somewhere Theodore can run around and you can do a 15-30 min walking loop

### What counts as an acceptable coffee shop?
**Excluded chains:**
- Starbucks, Dunkin' Donuts, Tim Hortons, McDonald's, fast food

**Approved chains:**
- Blue Bottle, Bluestone Lane, La Colombe, Birch Coffee, Joe Coffee, Think Coffee, Gregorys, Black Fox, Variety

**Default:** Any local/independent cafe is included

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
