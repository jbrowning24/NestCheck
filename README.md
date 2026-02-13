# NestCheck

**Know before you move.** Evaluate any U.S. address for walkability, green space, transit, schools, and daily-life quality — in one report.

## What It Is

NestCheck is a livability evaluation tool. Enter any U.S. address and get a scored report covering:

- **Health & Safety** — Distance from gas stations, highways, and high-volume roads
- **Green Escape** — Quality parks, trails, and nature within walking distance (scored 0-10 per space)
- **Urban Access** — Transit options, hub commute times, and reachability (airport, downtown, hospital)
- **Family & Schooling** — Nearby schools by level, childcare, and family-friendly infrastructure
- **Daily Essentials** — Walkable groceries, cafes, and fitness
- **Final Score** — 0-100 livability score with full breakdown and percentile estimate

## Who It's For

- **Families choosing where to live** — especially remote workers optimizing for daily life, not commute
- **Renters evaluating apartments** — compare addresses objectively before visiting
- **Homebuyers doing due diligence** — environmental and lifestyle checks before making an offer

## How It Makes Money

- **$29 per report** — full livability evaluation for any U.S. address
- **API cost per report: ~$0.10-0.15** — healthy margin at scale
- **Coming soon:** 5-report bundles ($99), monthly subscriptions ($49/mo), PDF export, saved reports
- **Revenue model:** Pay-per-report with premium tiers for professionals and frequent movers
- **Current state:** Free preview while payment integration (Stripe) is being built. TODO markers in code for Stripe Checkout, PDF export, saved reports, and subscription management.

## Report Sections

Each report includes:

1. **One-line verdict** — "Strong daily-life match" / "Compromised walkability" / etc.
2. **Final Score: X / 100** — with percentile estimate
3. **Green Escape** — Best daily park with Daily Walk Value score (0-10), subscores for walk time, size, quality, and nature feel. Plus up to 5 other nearby green spaces with PASS/BORDERLINE/FAIL status.
4. **Urban Access** — Nearest transit node, transit frequency, primary hub commute time with Great/OK/Painful verdict, reachability to airport/downtown/hospital. Walk/Transit/Bike scores when available.
5. **Family & Schooling** — Childcare (ages 0-5) and schools by level (Elementary, Middle, High) with walk times and ratings.
6. **Health & Safety Checks** — Pass/fail checks for gas station proximity, highway proximity, and high-volume roads.
7. **What's Missing / Needs Verification** — Automatically detected data gaps and items that need manual verification.
8. **Score Breakdown** — Full tier-2 scoring (6 categories, 0-10 each) plus tier-3 bonuses. Legend explaining how the score is constructed.

## Scoring System

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

Properties that fail health/safety checks (Tier 1) are disqualified before scoring.

## Local Development

### Prerequisites

- Python 3.11+
- Google Maps API key (Places, Distance Matrix, Geocoding APIs enabled)
- (Optional) Walk Score API key

### Setup

```bash
git clone https://github.com/jbrowning24/NestCheck.git
cd NestCheck

pip install -r requirements.txt

export GOOGLE_MAPS_API_KEY="your-google-maps-key"
export WALKSCORE_API_KEY="your-walkscore-key"  # optional

python app.py
```

The app will be available at `http://localhost:5001`.

### Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `GOOGLE_MAPS_API_KEY` | Yes | Google Maps Platform API key |
| `WALKSCORE_API_KEY` | No | Walk Score API key (for walk/transit/bike scores) |
| `SECRET_KEY` | Yes (production) | Flask session secret. Required for production; local dev falls back to default when `FLASK_DEBUG=1` |
| `PORT` | No | Port to bind (default: 5001) |
| `FLASK_DEBUG` | No | Set to "1" for debug mode |

## Deploy to Render

### One-click setup

1. Push this repo to GitHub
2. Go to [Render Dashboard](https://dashboard.render.com)
3. Click **New > Web Service**
4. Connect your GitHub repo
5. Render will auto-detect `render.yaml` and configure:
   - Build: `pip install -r requirements.txt`
   - Start: `gunicorn app:app -c gunicorn_config.py --bind 0.0.0.0:$PORT --timeout 180 --workers 2`
6. Add environment variables:
   - `GOOGLE_MAPS_API_KEY` (required)
   - `WALKSCORE_API_KEY` (optional)
7. Deploy

### Manual production run

```bash
pip install -r requirements.txt
gunicorn app:app -c gunicorn_config.py --bind 0.0.0.0:$PORT --timeout 180 --workers 2
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
green_space.py            Green Escape engine (park quality + scoring)
urban_access.py           Urban Access engine (hub reachability)
templates/
  index.html              Landing page + report template
  pricing.html            Pricing page with Stripe TODO stubs
render.yaml               Render deployment config
Procfile                  Process file for PaaS platforms
requirements.txt          Python dependencies
```

## Data Sources

- **Google Maps Platform** — Places API, Distance Matrix API, Geocoding API
- **OpenStreetMap** — Road classification and green space polygons via Overpass API
- **Walk Score** — Walk, Transit, and Bike scores (when API key provided)

School and childcare results are from Google Places and may not reflect official district assignments.

## API Cost Estimate

~$0.10-0.15 per evaluation. At $29/report, this supports a healthy margin.

## Disclaimer

NestCheck is a decision-support tool, not professional real estate, health, or legal advice. Scores are estimates based on publicly available data. Verify listing details, school assignments, and environmental conditions independently.

## License

Private — All rights reserved.
