# Technical Plan: PRD Alignment & Validation Readiness

**Author:** Jeremy Browning + Claude
**Date:** March 21, 2026
**Status:** Active
**Linear project:** NES-323 through NES-366

---

## Purpose

This document bridges the gap between the PRDs (`prd-nestcheck-v1.md`, `prd-report-design-system.md`) and the implementation backlog. It captures:

1. A systematic audit of where the codebase diverges from the PRD specs
2. Prioritization rationale for what to build and what to defer
3. CTO review decisions that override or refine PRD specifications
4. Sequencing: what blocks what, and what comes after validation

The PRDs define *what* NestCheck should be. The design system spec defines *how it should look*. This document defines *what's missing, what to do about it, and in what order*.

---

## Methodology

Both PRDs were read in full and compared against the current codebase via targeted exploration of templates, CSS, Python modules, and database schemas. Gaps were ranked by business impact — not spec compliance for its own sake. The CTO expert perspective was consulted on the validation infrastructure plan.

---

## Gap Inventory

### Tier 1 — High-Leverage, High-Priority (Ticketed)

| # | Gap | Linear | Priority | Project |
|---|-----|--------|----------|---------|
| 1 | Mobile sticky tab bar (no in-page nav on mobile) | NES-323 | High | Visual Restyle |
| 2 | User steering / configurable dimension weights | NES-324 | Medium | — |
| 3 | Venue cards: vertical grid instead of horizontal scroll | NES-325 | High | Visual Restyle |
| 4 | Scoring key card missing from verdict area | NES-326 | Medium | Visual Restyle |
| 5 | Single-tier monetization ($9 flat) vs. PRD's 4-tier model | NES-327 | High | — |

### Tier 2 — Important, Secondary Priority (Ticketed)

| # | Gap | Linear | Priority | Project |
|---|-----|--------|----------|---------|
| 6 | No embeddable widget / badge API for distribution | NES-343 | High | — |
| 7 | No hyper-local SEO area pages (city/state) | NES-344 | High | — |
| 8 | No data freshness indicators on report sections | NES-345 | Medium | Visual Restyle |
| 9 | Verdict score badge CSS not implemented | NES-346 | High | Visual Restyle |
| 10 | No NDVI / satellite vegetation analysis | NES-347 | Medium | PRD Alignment |

### Tier 0 — Validation Blocker (Ticketed, Urgent)

| # | Gap | Linear | Priority |
|---|-----|--------|----------|
| 11 | No feedback collection mechanism (Test A + Test B) | NES-360 | **Urgent** |

### Acknowledged but Not Ticketed

| Gap | Rationale for deferral |
|-----|----------------------|
| `empty_state` reusable macro (§4.12) | Works via inline conditionals; maintainability issue, not feature gap |
| Print header missing address + date | Small fix, low leverage; `@media print` block exists and is functional |
| `prefers-reduced-motion` only in 2 CSS files | Should be global; fix as part of next accessibility pass |
| "N Clear · 1 Unverified" health count string | Icon exists; count string distinction is cosmetic |
| Pedestrian crash data (PRD Phase 3) | Intentionally deferred; requires state DOT pipelines |
| Crime data (PRD Phase 3) | Intentionally deferred; requires FHA legal counsel first |
| ParkServe loop trail geometry analysis | Data scarcity: OSM doesn't tag loop geometry consistently |
| Park maintenance quality scoring | Only ~20-30 cities publish inspection data nationally |

---

## Sequencing & Dependencies

### Phase 0: Validation (must complete before all other work)

```
NES-360  Validation test infrastructure
├── NES-361  validation_feedback table + API endpoint
├── NES-362  Inline feedback prompt on report
├── NES-363  Detailed survey page
├── NES-364  Builder dashboard validation results
├── NES-365  Test B address collection + script
└── NES-366  Follow-up email script
```

**Outcome gates:**
- If ≥ 3/5 say "told me something new" → core value prop validated, proceed to Phase 1
- If ≥ 2/5 say "would pay" → consumer monetization viable, proceed with NES-327
- If < 2/5 would pay → pivot to B2B-primary (NES-341 becomes urgent)
- If any dimension averages < 3.0 accuracy → fix that dimension's methodology before launch

### Phase 1: Report Experience (post-validation, parallel tracks)

**Track A — Mobile & Layout (Visual Restyle project)**
```
NES-330  Verify section IDs (prerequisite)
  ↓
NES-323  Mobile sticky tab bar
├── NES-328  section-nav.js dual consumers
├── NES-329  Tab bar HTML + CSS
└── NES-330  Section ID audit

NES-325  Venue cards horizontal scroll
├── NES-334  Convert to scroll containers
├── NES-335  Walk/drive time pill logic
└── NES-336  Accessibility

NES-346  Verdict score badge CSS
└── NES-357  Wire macro + verify band classes
```

**Track B — Trust & Transparency**
```
NES-326  Scoring key card
├── NES-337  Jinja macro + CSS
└── NES-338  Expose ScoreBand thresholds

NES-345  Data freshness indicators
├── NES-355  Query dataset_registry
└── NES-356  Render in templates
```

### Phase 2: Distribution (post-Phase 1, high leverage)

```
NES-343  Embeddable widget API
├── NES-348  SVG badge endpoint
├── NES-349  iframe card widget
├── NES-350  API key model + data endpoint
└── NES-351  Embed code generator modal

NES-344  SEO area pages
├── NES-352  City page route + template
├── NES-353  State page route + template
└── NES-354  Sitemap + internal linking
```

### Phase 3: Monetization (post-validation, conditional on WTP signal)

```
NES-327  Multi-tier monetization
├── NES-339  Content-gated free tier (DEPRIORITIZED per CTO — post-validation only)
├── NES-340  Stripe subscription model
├── NES-341  B2B API spec (design only — escalates to urgent if WTP < 2/5)
└── NES-342  Pricing page redesign
```

### Phase 4: Personalization + Data Depth (longer term)

```
NES-324  User steering / dimension weights
├── NES-331  UserWeights data model
├── NES-332  Weight adjustment UI
└── NES-333  Client-side recalculation

NES-347  NDVI vegetation analysis
├── NES-358  Ingest NLCD tree canopy
└── NES-359  Canopy subscore in green space
```

---

## CTO Review: Key Decisions

The following decisions were made during CTO consultation on the validation infrastructure (March 21, 2026). They override or refine PRD specifications where noted.

### 1. Scope discipline for 5-user test
> "You're overbuilding for 5 users. A `validation_feedback` table, follow-up email cron, and results dashboard is the right architecture for 50+ testers. For 5 Columbia MBA peers, build the lightweight version."

**Decision:** Build the inline feedback prompt + survey page + builder dashboard section (real infrastructure that scales). Skip PDF export, follow-up email cron, content-gated free tier, and A/B testing for now.

### 2. PDF export is not a validation blocker
> "The report is already a shareable public URL. The existing `@media print` block means Cmd+P produces a reasonable printout. WeasyPrint is a dependency headache on Railway."

**Decision:** Skip PDF generation. Testers get links. Cmd+P for printing. Revisit post-validation if users specifically request PDF.

### 3. Content gate should NOT precede validation
> "If you ask 'would you pay for this?' after giving it away for free, the answer is always 'no' because they already have it."

**Decision:** Reframe WTP question as hypothetical: "If you hadn't seen the full report, would you have paid $10-15 to unlock it?" NES-339 (content gate) deprioritized from High to Medium. Build after validation passes.

### 4. Follow-up emails: script, not cron
> "A Railway cron service for 5 emails is over-engineering."

**Decision:** `scripts/send_validation_followup.py` with manual execution via `make validation-followup`. No Railway cron service.

### 5. Test B requires user-provided addresses
> "The 86 seed addresses are Westchester-only and chosen for content diversity. Test B requires addresses where the test user already lives."

**Decision:** Separate data collection step. Each tester provides 1-2 addresses they know intimately. New `data/validation_test_b_addresses.json` file. Evaluations run via existing tooling.

### 6. Dimension list must be frozen before test
> "If you're still adding/renaming dimensions between now and the test, the survey results won't be comparable."

**Decision:** Freeze `scoring_config.py` dimension definitions before sending any validation surveys. Add to pre-test checklist.

---

## What's Working Well (No Action Needed)

These PRD-specified capabilities are fully implemented and production-ready:

- **Health-first rubric hierarchy** — Tier 0 health disqualifiers with evidence-based thresholds
- **MAPS-Mini walk quality** — Full GSV + OSM computer vision pipeline
- **ParkServe integration** — Trust for Public Land park polygons, amenity enrichment
- **All Tier 2 health checks** — Cell towers, substations, industrial zones, EJScreen
- **Three-tier confidence system** — verified/estimated/not_scored with caps
- **Data confidence badges** — Per-dimension badges on all scorecard
- **Inter typeface** — Loaded at 400/500/600 with font-display: swap
- **Scroll-aware sidebar nav** — IntersectionObserver + aria-current (desktop)
- **Semantic HTML landmarks** — `<main>`, `<nav>`, `<aside>`, `<footer>`
- **aria-expanded on collapsibles** — All 6 toggle sections
- **Inline annotations** — Macro exists, 120ch max, actively used
- **Drill-down affordance** — 12px SVG icon macro
- **JSON-LD structured data** — WebPage + Residence + PropertyValue + BreadcrumbList
- **Drive-Only badge colors** — Neutral gray, correctly not using health-fail red
- **Builder mode payment bypass** — Cookie-based, fully functional
- **Seed evaluation sprint** — 86 addresses, resumable, content suitability rating
- **Email delivery** — Resend integration, graceful degradation
- **Shareable report links** — Public `/s/<id>`, no auth required

---

## Metrics & Falsification

Per the PRD, the validation test has hard falsification criteria:

| Metric | Threshold | Consequence if failed |
|--------|-----------|----------------------|
| "Told something new" | ≥ 3 of 5 | Core value proposition needs rethinking |
| "Would pay $10-15" | ≥ 2 of 5 | Consumer monetization hypothesis needs revision → B2B primary |
| Dimension accuracy | All dimensions ≥ 3.0 avg | Failing dimension needs methodology revision before launch |

These thresholds are displayed as traffic-light indicators on the builder dashboard (NES-364). They are the single most important output of the validation sprint.

---

## Document Maintenance

This document should be updated when:
- A ticketed gap is completed (move from "Gap Inventory" to "What's Working Well")
- Validation test results change the sequencing (e.g., WTP failure triggers B2B pivot)
- New PRD revisions introduce additional specifications
- CTO review decisions are revisited based on new evidence

Linear remains the source of truth for ticket status. This document is the source of truth for *why* those tickets exist and how they relate to each other.
