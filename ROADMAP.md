# NestCheck Product Roadmap

**Author:** Jeremy Browning
**Date:** March 1, 2026
**Status:** Active
**Goal:** Shortest path from current state to 5-user validation, then paying customers.

---

## Where You Are (Honest Assessment)

NestCheck is further along than it feels. Here's the inventory:

| Area | Status | Notes |
|------|--------|-------|
| Evaluation pipeline | **Working** | 6 Tier 2 dimensions scoring 0-100, piecewise curves, persona weights |
| Health checks (Tier 1) | **Working** | 8+ hazard types: gas stations, HPMS roads, Superfund, flood zones, TRI, power lines, EJScreen |
| Async job queue | **Production-ready** | SQLite WAL, atomic claiming, stage callbacks, requeue on stale |
| Payments (Stripe) | **Code complete, not wired** | State machine tested, atomic redemption, reissue on failure. Routes not in app.py |
| Email delivery (Resend) | **Working** | Report-ready email sends after evaluation. Magic links stubbed |
| Persona scoring | **Working** | 4 presets (Balanced, Active, Commuter, Quiet) |
| Comparison mode | **Working** | 2-4 addresses side-by-side |
| Spatial data (13+ datasets) | **Ingested** | EJScreen, SEMS, HPMS, HIFLD, TRI, UST, FEMA, ParkServe |
| Walk quality (MAPS-Mini) | **Working** | GSV computer vision for sidewalk features |
| Road noise scoring | **Working** | FHWA/WHO-calibrated dBA model |
| Census demographics | **Working** | ACS block group data wired in |
| Test suite | **Solid** | 400+ tests, regression suite, payment state machine |
| Landing page | **Functional** | Form + async polling + redirect to report |
| Report page | **Functional** | All sections render, but density and hierarchy need work |

**What's not done:**
- Stripe checkout routes (POST `/api/checkout`, webhook handler)
- Magic link flow for "My Reports"
- Landing page copy finalization
- Report page design polish (hierarchy, density, mobile)
- Data confidence badges visible to users (backend done, frontend partial)
- Fair Housing attorney review (PRD prerequisite)

---

## The Milestone That Matters

**5-User Validation Test** with Yaffe, Graham, Paul, Tanner + 1 more.

This is not a launch. It's a test of two questions:
1. Did this tell you something you didn't already know?
2. Would you have paid $10-15 for this?

If 3/5 say yes to #1 and 2/5 say yes to #2, you have a product. If not, you have invaluable signal on what to fix.

Everything below is sequenced to reach that milestone first, then layer revenue and growth after.

---

## Phase 0: Validation-Ready (Target: 2 weeks)

**Goal:** A report that 5 real people can evaluate for 5 real addresses and give honest feedback. No payment gate. No account system. Just "here's the URL, tell me what you think."

### 0.1 — Fix Check Accuracy (Days 1-3)

Before showing the report to anyone, the checks need to be trustworthy. Run the pipeline against 10 known addresses (5 where someone lives and knows ground truth, 5 that the test users are considering) and fix what breaks.

| Task | What to look for | Files |
|------|-----------------|-------|
| Run 10 real evaluations | Which checks produce surprising results? | `property_evaluator.py` |
| Audit gas station check | Are 300ft/500ft thresholds producing false positives in dense areas? | `property_evaluator.py:996` |
| Audit high-traffic road check | Is HPMS AADT data present for all roads near test addresses? | `property_evaluator.py:1104`, `spatial_data.py` |
| Audit green escape scoring | Does "Primary Green Escape" pick the right park? Are walk times plausible? | `green_space.py` |
| Audit transit check | Does Metro-North/subway detection work for Westchester + NYC addresses? | `property_evaluator.py:2858` |
| Fix false positives | Remove or downgrade checks that flag things that aren't real hazards | Per check |
| Fix false negatives | Add coverage for hazards the pipeline misses at test addresses | Per check |
| Verify EJScreen integration | Do block group percentiles render correctly in reports? | `property_evaluator.py`, `app.py:728` |

**Exit criteria:** 10 reports reviewed by you (Jeremy). Each check result is defensible. No "wait, that's wrong" moments when a test user sees their own neighborhood.

### 0.2 — Report Clarity (Days 3-7)

The report is the product. It needs to be scannable in 60 seconds and deep-readable in 5 minutes.

| Task | Why it matters | Files |
|------|---------------|-------|
| Simplify the verdict section | First thing users see. Must be a clear sentence, not jargon | `app.py:158` (generate_verdict) |
| Fix score breakdown hierarchy | 6 dimensions + bonuses + health checks = too flat. Group into "The Good / The Concerns / The Details" | `templates/_result_sections.html` |
| Add visual score bar | A number alone means nothing. A bar chart with labeled bands gives instant context | `templates/snapshot.html`, `static/css/snapshot.css` |
| Improve health check presentation | PASS/WARNING/FAIL badges are there but lack context. Add one-sentence "why this matters" per check type | `app.py:728` (present_checks) |
| Surface data confidence | Backend has HIGH/MEDIUM/LOW. Show it. Users trust you more when you say "we don't have great data here" | `templates/_result_sections.html` |
| Mobile readability pass | Test users will open the link on their phone. Cards need to not overlap | `static/css/snapshot.css` |
| Add "How We Scored This" section | Link to methodology. Transparency is the product | `templates/snapshot.html` |

**Exit criteria:** You (Jeremy) can hand someone a report URL on their phone and they understand the verdict in under 60 seconds without you explaining anything.

### 0.3 — Landing Page (Days 5-8)

The landing page only needs to do one thing: get the test user to enter an address.

| Task | Why it matters | Files |
|------|---------------|-------|
| Write final copy | "Know before you go" + 3-sentence value prop + address input. That's it | `templates/index.html` |
| Remove pricing references | No payment gate for validation. Free for test users | `templates/index.html` |
| Add "What you'll get" preview | Show a blurred/sample report screenshot below the fold | `templates/index.html`, `static/images/` |
| Fix progress indicator | The 60-90 second wait needs clear stage labels users understand | `templates/_eval_snippet.html` |
| Test the flow end-to-end | Submit address → poll → redirect → report renders correctly | Manual QA |

**Exit criteria:** A non-technical person can go to the URL, enter an address, wait for the evaluation, and land on a readable report without getting confused.

### 0.4 — Pre-Validation Prep (Days 8-10)

| Task | Why it matters |
|------|---------------|
| Prepare 5 test scripts | Standardized questions for each tester (prospective + ground-truth) |
| Set up analytics tracking | Know which sections users scroll to, how long they spend | `app.py` event tracking |
| Create feedback form | Google Form: "What surprised you? What was wrong? Would you pay?" |
| Run final smoke test | 5 addresses, all complete without errors, all reports reviewed |
| Brief each test user | 5 min context: "I built a neighborhood evaluation tool. Try it on an address you know well and one you're considering. Then fill out this form." |

**Exit criteria:** 5 URLs sent to 5 people with clear instructions and a feedback form.

---

## Phase 1: Monetization Foundation (Weeks 3-4)

**Only start this if Phase 0 validation signals are positive (3/5 "told me something new").**

### 1.1 — Wire Stripe Checkout

The payment model code is complete and tested. What's missing is the route handlers.

| Task | Files | Complexity |
|------|-------|------------|
| Implement POST `/api/checkout` — create Stripe session | `app.py` | Medium |
| Implement POST `/api/webhook/stripe` — handle session.completed event | `app.py` | Medium |
| Implement GET `/api/payment/<id>` — status check | `app.py` | Low |
| Wire pricing.html "Buy Report" button to checkout flow | `templates/pricing.html` | Low |
| Set up Stripe webhook in dashboard | Stripe Dashboard | Config |
| Flip `REQUIRE_PAYMENT=true` on staging, test end-to-end | Railway env | Config |
| Free tier: 1 report per email per month (already modeled) | `models.py` | Already built |

**Pricing for validation:** $9.99 single report. Keep it simple. One price, one product.

### 1.2 — Preview → Unlock Flow

When `REQUIRE_PAYMENT=true`, free tier users get a preview snapshot. The unlock flow:

| Task | Files |
|------|-------|
| Design preview report (show verdict + health checks, blur Tier 2 details) | `templates/snapshot.html` |
| Add "Unlock Full Report" CTA on preview snapshot | `templates/snapshot.html` |
| Wire CTA to Stripe checkout with return URL back to snapshot | `app.py`, `templates/snapshot.html` |
| Handle webhook: update snapshot from preview → full | `worker.py`, `models.py` |

### 1.3 — My Reports (Magic Link)

Users need to find their reports again without creating an account.

| Task | Files |
|------|-------|
| Implement `send_magic_link_email()` with JWT token | `email_service.py` |
| Add GET `/auth/magic/<token>` route | `app.py` |
| Wire `/my-reports` page to show snapshots by email | `templates/my_reports.html` |

---

## Phase 2: Report Quality & Trust (Weeks 5-8)

Based on validation feedback, fix what users flagged. Likely areas:

### 2.1 — Check Accuracy Iteration

| What testers might flag | Fix |
|------------------------|-----|
| "The gas station warning seems wrong — I don't see one nearby" | Verify Google Places results match reality. Add "last verified" date |
| "It says flood zone but my block has never flooded" | Show FEMA zone designation explicitly, not just PASS/FAIL |
| "The park it picked isn't the one I actually use" | Improve park ranking to weight user-reported usage patterns |
| "Transit score seems off — the train is right there" | Verify walk time calculation. Check if station is on wrong side of tracks |

### 2.2 — Data Confidence Visibility

| Task | Why |
|------|-----|
| Show confidence badges on every dimension | Users in data-rich areas should know their report is more reliable |
| Add "Data Sources" footer to each section | Attribution builds trust and is legally required for some datasets |
| Handle "no data" gracefully | "We couldn't evaluate road noise for this address" > showing a misleading score |

### 2.3 — Design Polish

| Task | Why |
|------|-----|
| Typography hierarchy (H1/H2/H3 consistent) | Report currently too flat |
| Color system for scores (not correlated with race/income per PRD) | Avoid green=good/red=bad on demographic-correlated metrics |
| Print stylesheet | Users will want to save/share reports |
| PDF export | "Send this to my partner" use case |

---

## Phase 3: Growth Mechanics (Weeks 9-16)

### 3.1 — SEO Foundation

The PRD correctly identifies SEO as the sustainable growth channel.

| Task | Why |
|------|-----|
| Generate neighborhood pages (programmatic SEO) | Target "[neighborhood] review" long-tail queries |
| Add schema.org structured data to reports | Rich snippets in search results |
| Create 5-10 "neighborhood evaluation" content pages | Build topical authority for YMYL content |
| Submit sitemap to Google Search Console | Index programmatic pages |

### 3.2 — Shareability

| Task | Why |
|------|-----|
| OG image per report (map + score badge) | WhatsApp/iMessage previews drive shares |
| "Share this report" button with copy-link | Frictionless sharing |
| "Compare with another address" CTA on report | Increases engagement per user |

### 3.3 — Embeddable Widget

Walk Score's original growth playbook: free widgets on real estate blogs.

| Task | Why |
|------|-----|
| Build `<iframe>` widget (score badge + link to full report) | Distribution through partner sites |
| Create widget landing page with embed code | Self-serve for bloggers |
| Reach out to 10 Westchester real estate blogs | Initial distribution |

---

## Phase 4: Platform Expansion (Months 4-6)

### 4.1 — Geographic Expansion

| Metro | Why | Data readiness |
|-------|-----|---------------|
| NYC (all boroughs) | Adjacent to Westchester. Test users already here | HIGH — MTA, NYC Open Data, dense OSM |
| Jersey City / Hoboken | Metro-North adjacent. Young professional rental market | MEDIUM — NJ Transit data needed |
| Connecticut (Fairfield County) | Metro-North corridor. Natural expansion | MEDIUM — CT-specific data sources |
| San Francisco | Strong open data. High willingness to pay for neighborhood info | MEDIUM — BART data needed |

### 4.2 — User Steering (PRD Layer 3)

Let users adjust dimension weights beyond preset personas.

| Task | Why |
|------|-----|
| Custom weight sliders on report page | "I don't care about fitness, I care about quiet" |
| Save preferences per email | Returning users get personalized defaults |
| "Re-score with my priorities" button | Instant re-evaluation without new API calls |

### 4.3 — B2B Pipeline

Per PRD: aligned B2B only (no MLS/brokerage).

| Partner type | Value prop | Approach |
|-------------|-----------|----------|
| Relocation companies | "Give relocating employees honest neighborhood data" | Direct outreach |
| Corporate HR | "Add to your relocation benefits package" | Pilot with 1-2 companies |
| Home inspectors | "Neighborhood inspection alongside home inspection" | Partnership widget |
| Home insurers | "Neighborhood risk data for underwriting" | API licensing |

---

## Decision Points (Don't Skip These)

| After Phase | Decision | If yes | If no |
|-------------|----------|--------|-------|
| 0 (Validation) | Did 3/5 users learn something new? | Proceed to Phase 1 | Rethink which dimensions actually surprise people |
| 0 (Validation) | Did 2/5 users say they'd pay? | Build payment flow | Pivot to free + B2B licensing |
| 1 (Payments) | Are people actually paying $9.99? | Double down on DTC | Accelerate B2B pipeline |
| 2 (Polish) | Is retention happening (return visits)? | Invest in SEO + growth | Fix the report — they're not coming back for a reason |
| 3 (Growth) | Is organic traffic growing? | Scale content, expand metros | Reconsider distribution strategy |

---

## What NOT to Build Right Now

These are real features in the PRD that should wait:

| Feature | Why wait |
|---------|----------|
| Account system / login | Magic links are enough for validation. Full auth is a distraction |
| Crime data integration | Highest FHA risk. Needs attorney review first. Not required for validation |
| School district boundaries | Google Places schools are adequate for validation. Official boundaries are a separate data pipeline |
| AI-generated neighborhood narratives | Adds cost and hallucination risk. Structured data is more trustworthy |
| Mobile app | The web works. A native app is a distraction at this stage |
| Multi-language support | English-only until proven demand |
| PostGIS migration | SQLite + SpatiaLite handles validation load. Migrate when you hit concurrency limits |

---

## Weekly Cadence

| Day | What |
|-----|------|
| Monday | Pick the 3 most important tasks for the week. No more than 3 |
| Tuesday-Thursday | Build. Ship small PRs. Test against real addresses |
| Friday | Run 2 evaluations against new addresses. Review results. Note what's wrong |
| Weekend | Think about the product, not the code. Talk to potential users |

---

## The Honest Summary

You have a working product. The gap is not technical — it's validation. The fastest path from here to "I know if this works" is:

1. **Fix the checks that are wrong** (3 days)
2. **Make the report readable** (4 days)
3. **Send 5 URLs to 5 people** (1 day)
4. **Listen** (1 week)

Everything after that depends on what they tell you. Don't build the payment flow until you know the free report earns trust. Don't build SEO pages until you know the report is worth sharing. Don't expand to new metros until you nail the one you're in.

The messy middle ends when you ship to real users and get real feedback. That's 2 weeks away, not 2 months.
