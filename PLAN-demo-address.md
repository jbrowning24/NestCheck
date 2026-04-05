# Implementation Plan: NES-320 — Demo Address on Landing Page

**Progress:** [##########] 100%
**Created:** 2026-04-04

## TL;DR
Wire 282 Bruce Park Ave, Greenwich CT as a permanent demo snapshot and add a "See a sample report" CTA on the landing page between the hero and "How It Works" sections. The address FAILs Tier 1 (I-95 at 137,700 AADT, 279 ft away) — a non-obvious finding on a Greenwich address that sells the product instantly.

## Critical Decisions
| Decision | Choice | Rationale |
|----------|--------|-----------|
| Snapshot creation | Save CLI result via `save_snapshot()` script | Avoids re-running the full evaluation; we already have the JSON |
| Snapshot permanence | `is_demo=1` column flag, skip TTL expiration | Simpler than a config file; queryable, one-row change |
| CTA placement | Between hero section and "How It Works" | Maximum visibility without cluttering the search form |
| CTA design | Single sentence + link, not a card/preview | Minimal — let the report sell itself |
| Demo snapshot ID | Pass as `jinja_env.globals` | Same pattern as other static config; available on all pages |

## Tasks

### Phase 1: Create the demo snapshot
- [x] 🟩 **Task 1.1: Save Greenwich evaluation as a snapshot** → `85ab0a18`
  - Write a one-off script (or inline in Flask shell) that loads the CLI JSON output, calls `save_snapshot()`, and prints the snapshot_id
  - Files: run in Flask shell using `models.save_snapshot()`
  - Input: the JSON from `/private/tmp/.../tasks/bscedcxtx.output` (line 6+)
  - Acceptance: `get_snapshot(snapshot_id)` returns the Greenwich result with `passed_tier1=False`

- [x] 🟩 **Task 1.2: Mark snapshot as permanent (skip TTL)**
  - Add `is_demo INTEGER DEFAULT 0` column to `snapshots` table in `models.py` `init_db()`
  - Update `is_snapshot_fresh()` to return `True` when `is_demo=1` (demo snapshots never expire)
  - Set `is_demo=1` on the Greenwich snapshot
  - Files: `models.py`
  - Acceptance: `is_snapshot_fresh(demo_snapshot_id)` returns True regardless of age

### Phase 2: Wire into landing page
- [x] 🟩 **Task 2.1: Expose demo snapshot ID as a template global**
  - Add `DEMO_SNAPSHOT_ID` to `jinja_env.globals` in `app.py` (same pattern as other globals)
  - Source from env var `DEMO_SNAPSHOT_ID` with hardcoded fallback to the Greenwich snapshot ID
  - Files: `app.py` (near other `jinja_env.globals` assignments)
  - Acceptance: `{{ demo_snapshot_id }}` renders the snapshot ID in any template

- [x] 🟩 **Task 2.2: Add demo CTA section to landing page**
  - Insert a new section between the hero (`</section>` line ~120) and the auth callout/How It Works
  - Content: one-liner CTA linking to `/s/{{ demo_snapshot_id }}`
  - Copy: "See what NestCheck found at a Greenwich address →" (links to the snapshot)
  - Minimal styling — uses existing design tokens, no new CSS classes needed beyond one `.hp-demo-cta`
  - Files: `templates/index.html`, `static/css/landing.css` (or inline in template)
  - Acceptance: Landing page shows the CTA; clicking it opens the full Greenwich report

### Phase 3: Verify
- [x] 🟩 **Task 3.1: Manual QA**
  - Load landing page — CTA visible between hero and How It Works
  - Click CTA — opens `/s/{snapshot_id}` with Greenwich report
  - Report shows FAIL badge for high-traffic road, WARNING for rail and hazardous waste
  - Mobile: CTA renders cleanly on 375px viewport
  - Acceptance: All four checks pass

## Testing Checklist
- [ ] `make test-scoring` passes (no regression)
- [ ] Demo snapshot loads at `/s/{snapshot_id}`
- [ ] Landing page CTA links to correct snapshot
- [ ] Schema migration: fresh DB + existing DB both work (`is_demo` column)
- [ ] Mobile viewport: CTA doesn't break layout
