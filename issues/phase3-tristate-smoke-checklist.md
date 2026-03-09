# Phase 3: Tri-State Smoke Test Checklist

## Overview

Verify that the tri-state expansion (NY + CT + NJ) works correctly by running
a full evaluation for one address per state and checking results.

**Automated test:** `make smoke-tristate` (or `make smoke-tristate-local`)

---

## Test Addresses

| # | State | Address | Why |
|---|-------|---------|-----|
| 1 | NY (existing) | White Plains, NY 10601 | Regression — must match pre-expansion results |
| 2 | NY (new) | Albany, NY 12207 | Outside Westchester — tests expanded NY spatial data |
| 3 | CT | Stamford, CT 06901 | Metro-North corridor, likely school district match |
| 4 | NJ | Hoboken, NJ 07030 | Dense urban, should hit all spatial datasets |

---

## Per-Address Checklist

### For EVERY address, verify:

- [ ] **HTTP 200** — page loads successfully, no 500 errors
- [ ] **Verdict card** — score ring and verdict text render
- [ ] **Dimension scores** — all scored dimensions appear (Parks, Coffee, etc.)
- [ ] **Health checks render** — gas stations, power lines, flood zones, superfund,
      high-traffic roads, industrial zones all present (or correctly marked clear)
- [ ] **School district identified** — TIGER polygon lookup returns a district name
- [ ] **Nearby schools listed** — NCES school points appear in the section
- [ ] **Environmental checks** — EJScreen, TRI, UST results present for the address
- [ ] **No missing sections** — compare against a known Westchester result; same
      structure, no blank holes where data should be
- [ ] **JSON export works** — `/api/snapshot/{id}/json` returns valid JSON with
      `tier1_checks` and `tier2_scores`

### School performance data:

- [ ] **White Plains** — graduation rate, proficiency, absenteeism MUST display
      (Westchester district is in bundled CSV)
- [ ] **Albany** — performance data likely missing (not in Westchester CSV).
      Confirm graceful degradation: no crash, section omitted or shows fallback
- [ ] **Stamford** — performance data likely missing (NES-219). Same graceful
      degradation check
- [ ] **Hoboken** — performance data likely missing (NES-220). Same graceful
      degradation check

---

## Specific Regression Checks

### White Plains (most important)

- [ ] Results look **identical** to pre-expansion. Same data, same scores.
      If the existing experience degraded, something went wrong.
- [ ] Health check count matches previous runs
- [ ] Dimension scores within expected range (compare to a known snapshot)

### Railway Deployment

- [ ] **spatial.db ingestion logs** — confirm all three states ingested without
      errors. Look for state-specific log lines (e.g., "Ingesting EJScreen for CT...")
- [ ] **spatial.db size** — note the new size. If approaching 4GB, flag it.
      (Railway volume limit is 5GB)

### Cross-State Structural Comparison

- [ ] CT/NJ result pages have the **same section structure** as Westchester results
- [ ] No state-specific sections are blank or erroring
- [ ] Census/demographics section populated for all states

---

## Expected Incomplete Data (NOT bugs)

These are tracked in separate issues and are expected to be missing:

| What | Where | Tracking |
|------|-------|----------|
| School performance data for most CT addresses | Only ~25 districts covered | NES-219 |
| School performance data for most NJ addresses | Only ~35 districts covered | NES-220 |
| School performance data for NY outside Westchester | Only ~40 districts covered | NES-221 |

If an address has no school performance data, the page should either:
1. Omit the performance sub-section entirely, OR
2. Show "data not available" text

It should **never** crash or show a 500 error.

---

## Running the Automated Test

```bash
# Against production
make smoke-tristate

# Against local dev
make smoke-tristate-local

# Direct invocation with custom URL
python3 smoke_test_tristate.py https://your-url.app
```

The automated test (`smoke_test_tristate.py`):
1. Submits each address via POST
2. Polls job status until done/failed (3-minute timeout per address)
3. Fetches the rendered snapshot page
4. Checks for required section markers (verdict, dimensions, health, etc.)
5. Checks for expected section markers (schools, EJScreen — warns if missing)
6. Verifies JSON export endpoint returns valid structured data
7. Reports PASS/FAIL per address with snapshot URLs for manual review

---

## Sign-Off

| Address | Tester | Date | Result | Notes |
|---------|--------|------|--------|-------|
| White Plains, NY | | | | |
| Albany, NY | | | | |
| Stamford, CT | | | | |
| Hoboken, NJ | | | | |
| Railway logs checked | | | | |
| spatial.db size noted | | | | |
