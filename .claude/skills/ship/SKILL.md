---
name: NestCheck Shipping Workflows
description: "NestCheck deployment, shipping, and release workflows for Railway. Trigger on: ship, deploy, push, merge, PR, preview, go live, release, what's deployed, check the deploy, Railway status, weekly sweep, branch cleanup, post-deploy, staging, production, or any request about getting code to production."
---

# NestCheck Shipping Workflows

**Repo:** `jbrowning24/NestCheck`
**Host:** Railway (service: `loyal-presence`). NOT Render.
**Volume:** `/app/data` (spatial.db, nestcheck.db)
**Auto-deploy:** Push to `main` triggers Railway deploy automatically.

## Workflow A: Backend / Logic Changes

For scoring changes, data pipeline changes, API client changes, model changes — anything invisible to the user.

```
1. Make changes on main
2. make test-scoring          # CI gate — must pass
3. make validate              # If spatial data touched (needs spatial.db)
4. /pr-learn                  # Code review + extract CLAUDE.md learnings
5. /ship                      # Commit + push to main
6. Railway auto-deploys
7. Run post-deploy checklist
```

Use when: scoring_config.py changes, property_evaluator.py changes, models.py changes, worker.py changes, ingest script changes, census.py changes.

## Workflow B: Visual / Template Changes

For CSS, template, frontend JS changes — anything the user sees.

```
1. Make changes on a branch
2. /pr-learn                  # Code review + CLAUDE.md learnings
3. /preview                   # Create branch + PR, triggers Railway preview environment
4. Visual verification in preview URL
5. /merge                     # Merge PR to main
6. Railway auto-deploys from main
7. Run post-deploy checklist
```

Use when: template changes, CSS changes, static asset changes, layout changes, new UI components. The preview environment lets you verify visual changes before they hit production.

## Workflow C: Complex Multi-Phase Features

For features spanning multiple files, days, or requiring staged rollout.

```
1. Create feature branch from main
2. Implement in phases, committing to feature branch
3. make test-scoring after each scoring-related phase
4. /pr-learn on the full branch diff
5. /preview for visual verification (if UI changes)
6. Create PR: gh pr create --base main
7. Review PR, address feedback
8. Merge PR (squash or merge commit based on complexity)
9. Railway auto-deploys from main
10. Run post-deploy checklist
```

Use when: multi-day features (NES-XXX tickets), features touching both backend and frontend, geographic expansion to new states, new dimension scoring.

## Post-Deploy Checklist

Run after every deploy to production:

```bash
# 1. Verify deployed commit matches main
# Check Railway dashboard or:
git log --oneline -1 main
# Compare SHA against RAILWAY_GIT_COMMIT_SHA in Railway service

# 2. Page load check
curl -s -o /dev/null -w "%{http_code}" https://nestcheck.app/
# Expect: 200

# 3. Evaluate a known address
# Use a Westchester suburb you've verified before
# Check: job completes, snapshot renders, scores display

# 4. Verify health checks render
# Tier 1 cards visible with citations
# Tier 2 collapsible section present
# No missing headlines or blank cards

# 5. Check dimension scores
# All scored dimensions show integer scores with band colors
# Suppressed dimensions show "—" not "0"
# Confidence badges display correctly

# 6. Check Sentry for new errors
# Filter by release (deployed SHA)
# Zero new errors = good deploy

# 7. Automated smoke test (runs daily via Railway cron)
make smoke-test
```

## Weekly Sweep Process

Run weekly to keep the repo and deployment clean.

```bash
# 1. Prune stale remote tracking branches
git fetch --prune

# 2. Clean local branches tracking deleted remotes
git branch -vv | grep ': gone]' | awk '{print $1}'
# Review the list, then:
# git branch -d <branch-name>  (for each)

# 3. Cross-reference remaining branches against Linear tickets
# Open branches should map to open Linear tickets
# Merged/closed tickets → branch should be deleted

# 4. Verify Railway deployment SHA
# Railway dashboard → loyal-presence → latest deployment
# Should match: git log --oneline -1 main

# 5. Check Railway volume health
# Verify spatial.db is being updated by startup_ingest
# Check evaluation_coverage table for recent entries

# 6. Backlog triage
# Review open Linear tickets
# Prioritize: bugs > calibration issues > new features
# Close stale tickets that are no longer relevant
```

## Railway Configuration Details

| Setting | Value |
|---------|-------|
| Service name | `loyal-presence` |
| Config file | `railway.toml` |
| Volume mount | `/app/data` |
| Build system | Railpack (NOT Nixpacks) |
| System deps | `railpack.json` → `deploy.aptPackages` |
| Auto-deploy | On push to `main` |
| Restart policy | `ON_FAILURE` (web service) |
| Workers | Gunicorn with background eval thread per worker |

### Railway Cron Services

| Service | Config File | Schedule | Script |
|---------|------------|----------|--------|
| Smoke test | `railway-cron-smoke-test.toml` | Daily | `scripts/daily_smoke_test.py` |
| Spatial health | `railway-cron-spatial-health.toml` | Weekly | Calls `GET /api/spatial-health` on web service |
| Regression | `railway-cron-regression.toml` | Monthly | `scripts/regression_baseline.py` |

All cron services use `restartPolicyType = "NEVER"`. Cron services cannot share volumes — spatial-health uses an authenticated HTTP endpoint on the web service.

### System Dependencies

Use `railpack.json` for runtime apt packages. `nixpacks.toml` is silently ignored by Railway. If a deploy fails with missing system libraries, check `deploy.aptPackages` in `railpack.json`.

## Git Hygiene

- `fetch.prune` is set globally — `git fetch` automatically prunes stale remote refs
- ~140 legacy branches already cleaned in prior sweep
- Branch naming: `feature/nes-XXX-description` for feature work, direct to `main` for small fixes
- Prefer new commits over amending — amend risks destroying previous work when hooks fail
- Never force-push to `main`

## What NOT to Do

- Do NOT deploy by pushing to any branch other than `main`. Railway auto-deploys from `main` only.
- Do NOT use `nixpacks.toml` for system dependencies — Railway uses Railpack. Use `railpack.json`.
- Do NOT skip the post-deploy checklist. Silent failures (missing template IDs, broken health checks) are invisible without manual verification.
- Do NOT assume Railway preview environments have the production volume. Preview environments start fresh — spatial.db may be empty or stale.
- Do NOT run `make regression-update` unless you intend to accept the current scoring as the new baseline. Baseline updates are intentional, not routine.
- Do NOT delete the `scripts/__init__.py` file — it enables cross-boundary imports from `scripts/` into `app.py`.
- Do NOT create Railway cron services with `restartPolicyType` other than `"NEVER"` — they must exit after task completion.
- Do NOT share secrets between Railway services via volumes. Use environment variables or authenticated HTTP endpoints.
- Do NOT push scoring changes without running `make test-scoring` first. The CI gate catches this, but failed CI on `main` blocks all subsequent merges.
- Do NOT merge a PR without visual verification if it touches templates or CSS. Use Workflow B with `/preview`.
