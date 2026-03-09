# NES-209: Evaluate Notte Anything API for Multi-State Education Data Scraping

## Status: EVALUATED — Not recommended

## Summary

Notte is an AI-powered browser automation platform that turns websites into callable APIs.
The "Anything API" lets you describe a workflow in natural language, and Notte generates a
production-ready API endpoint backed by managed Chromium sessions. This evaluation assesses
whether Notte is suitable for replacing or augmenting NestCheck's current education data
pipeline as we consider multi-state expansion.

**Verdict:** Notte does not solve a problem we actually have. Our education data sources
already provide structured APIs or downloadable data. Notte would add cost, non-determinism,
and a new dependency without meaningful benefit.

---

## Current Education Data Architecture

NestCheck uses three data sources for school/education data, all NY-scoped:

| Source | Script | Data Type | Access Method | Scope |
|--------|--------|-----------|---------------|-------|
| **NCES EDGE** | `ingest_nces_schools.py` | School point locations, enrollment, FRL%, grade range | ArcGIS REST API (paginated JSON) | NY state (STABR='NY'), bbox-filtered to Westchester |
| **Census TIGER** | `ingest_school_districts.py` | School district polygon boundaries | ArcGIS REST API (paginated JSON) | NY state (FIPS='36') |
| **NYSED Report Card** | `ingest_nysed.py` | District performance (grad rate, proficiency, absenteeism, expenditure) | Bundled CSV (`data/nysed_district_performance.csv`) | ~40 Westchester districts |

The NCES and TIGER sources use standard ArcGIS REST endpoints that support nationwide queries
by changing filter parameters (state code, bbox). The NYSED data is the only source that
requires manual curation — NYSED publishes bulk data as Access databases with no API.

### Multi-State Expansion Bottlenecks

If NestCheck expands beyond NY, here's what each source requires:

1. **NCES EDGE** — Already nationwide. Change `STABR='NY'` to target state. **No bottleneck.**
2. **Census TIGER** — Already nationwide. Change `STATE='36'` to target FIPS. **No bottleneck.**
3. **State performance data** — This is the real bottleneck. Each state publishes education
   performance data differently:
   - Some states have APIs (CA, TX, FL have reasonably structured data portals)
   - Some publish CSVs/Excel downloads (common)
   - Some publish only as Access DBs or HTML reports (NYSED pattern)
   - Data fields vary: not every state reports the same metrics

---

## Notte Anything API Assessment

### What Notte Is

- **Platform:** Managed Chromium browser infrastructure with anti-detection, CAPTCHA solving,
  residential proxies
- **Core idea:** Transform websites into "agent-friendly environments" using LLM-powered
  navigation
- **Anything API:** Describe a browser workflow → Notte generates a callable REST endpoint
- **SDK:** `pip install notte`, Python client with `client.scrape()` and `client.Agent()`

### Pricing

| Plan | Cost | Browser Hours | Concurrent Sessions |
|------|------|---------------|---------------------|
| Free | $0 | 100 total (forever) | 5 |
| Developer | $20/mo + usage | 100/mo | 25 |
| Startup | $100/mo + usage | 500/mo | 100 |

Usage: $0.05/hr browser time + $10/GB proxy + LLM token pass-through.

### Strengths (Theoretical)

- Could scrape state education portals that lack APIs (HTML-only sites)
- Structured output via Pydantic models — define schema, get typed data
- Handles JS-rendered pages, CAPTCHAs, authentication flows
- No per-site scraper maintenance — AI agent adapts to layout changes

### Weaknesses (Practical, for Our Use Case)

| Concern | Detail |
|---------|--------|
| **Solves the wrong problem** | 2 of 3 education sources already have ArcGIS APIs. Only NYSED lacks an API, and a bundled CSV is simpler. |
| **Non-deterministic** | AI agent "figures out" navigation each time. Claimed >90% success rate = ~1 in 10 runs fails. Unacceptable for a data pipeline. |
| **Expensive at scale** | Scraping 50 states × performance data = many browser-hours. Direct API calls or CSV downloads cost $0. |
| **Fragile for tabular data** | Government sites change layouts. AI agents adapt, but with unpredictable failure modes. A CSV download or API call either works or doesn't — debuggable. |
| **New dependency** | Young platform (~1.9K GitHub stars), no published SLAs below Enterprise tier. Adding a dependency on a startup's API for our core data pipeline is risky. |
| **Latency** | Browser sessions are orders of magnitude slower than HTTP API calls. Our ArcGIS ingestion takes seconds; browser-based scraping would take minutes. |

---

## Alternative Approaches for Multi-State Expansion

### Option A: State-Specific API Adapters (Recommended)

For each target state, write a focused ingestion script that uses the best available source:

| State | Source | Access |
|-------|--------|--------|
| NY | NYSED Report Card | Bundled CSV (current approach) |
| CA | CA Dept of Education DataQuest | Downloadable CSV files (ed-data.org) |
| TX | TEA TAPR | API + downloadable CSV |
| CT | CT EdSight | Downloadable CSV |
| NJ | NJ School Performance Reports | Downloadable CSV/API |

**Pattern:** One `ingest_<state>_performance.py` per state, loading into the same
`<state>_performance` table schema. Most states publish CSVs — the NYSED CSV approach
generalizes cleanly.

**Cost:** ~1 day per state to map fields. No runtime cost. Deterministic. Debuggable.

### Option B: Common Core of Data (CCD) — Federal

The NCES Common Core of Data (https://nces.ed.gov/ccd/) publishes nationwide school-level
data including some performance proxies (Title I status, student counts, demographics).
This is already available via ArcGIS REST (same pattern as our NCES schools ingestion).

**Limitation:** CCD doesn't include state-specific metrics like proficiency rates or grad
rates. But it provides a nationwide baseline without any scraping.

### Option C: Notte for HTML-Only Outliers

If we encounter a state that publishes education data *only* as HTML tables with no CSV
download and no API, Notte could be evaluated as a last resort. But even then, a targeted
Playwright script would be more reliable and cheaper.

---

## Recommendation

**Do not adopt Notte for education data scraping.** The problem it solves (no structured
access to data) doesn't apply to our primary sources. For the one source that lacks an API
(NYSED), a bundled CSV is simpler, cheaper, and more reliable.

For multi-state expansion, pursue **Option A** (state-specific CSV/API adapters) as the
primary approach, supplemented by **Option B** (federal CCD data) for a nationwide baseline.

### If Notte Becomes Relevant Later

Revisit if:
- NestCheck expands to 10+ states and several have truly no downloadable data
- Notte matures (higher success rates, published SLAs, larger community)
- A non-education data source requires browser-based extraction with no API alternative

---

## References

- Notte Platform: https://www.notte.cc
- Anything API: https://anything.notte.cc/
- Notte GitHub: https://github.com/nottelabs/notte (1.9K stars)
- Notte Docs: https://docs.notte.cc
- NCES EDGE: https://nces.ed.gov/opengis/rest/services/K12_School_Locations
- NCES CCD: https://nces.ed.gov/ccd/
