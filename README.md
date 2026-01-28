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

## How It Makes Money

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

### Evaluation Flow

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
