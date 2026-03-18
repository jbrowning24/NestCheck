# Railway Cron Services Setup

NestCheck uses three scheduled automation scripts. Railway supports cron jobs
as separate services, but **volumes cannot be shared across services**. This
constraint shapes the setup.

## Architecture

```
Railway Project: NestCheck
├── web (existing)        — gunicorn, owns volume at /app/data
├── smoke-test (cron)     — daily, no volume needed
├── spatial-health (cron) — weekly, no volume needed (queries web service via HTTP)
└── regression (cron)     — monthly, no volume needed
```

### Volume Constraint

Railway volumes are attached to a single service and cannot be mounted by
multiple services. The web service owns the volume at `/app/data` containing
`spatial.db`. For cron services that need spatial data, the workaround is an
authenticated HTTP endpoint on the web service — the cron calls the endpoint
instead of reading the DB directly.

| Service | Needs Volume? | Why |
|---------|--------------|-----|
| `smoke-test` | No | Runs evaluation via API calls, no direct DB reads |
| `spatial-health` | No | Queries web service's `/api/spatial-health` endpoint via HTTP |
| `regression` | No | Evaluations use live APIs; baselines are in git |

## Prerequisites

- The web service is already deployed and running
- Railway Shared Variables configured (see below)

## Step 1: Configure Shared Variables

To avoid duplicating env vars across services:

1. Go to **Project Settings** → **Shared Variables**
2. Add these variables and share to all services:

| Variable | Purpose |
|----------|---------|
| `GOOGLE_MAPS_API_KEY` | Google Maps API access |
| `RESEND_API_KEY` | Email delivery via Resend |
| `SECRET_KEY` | Flask session secret |

## Step 2: Create Each Cron Service

### smoke-test (daily)

Runs `evaluate_property()` for a test address, validates the result dict
structure, and emails on failure or warnings.

1. **+ New** → **GitHub Repo** → select NestCheck repo → name it `smoke-test`
2. **Settings** → **Build & Deploy**:
   - **Config File Path**: `railway-cron-smoke-test.toml`
3. **Variables** (service-specific):
   - `SMOKE_TEST_NOTIFY_EMAIL` = your alert email
4. **No volume needed**

Schedule: `0 12 * * *` — daily at 12:00 UTC (7am EST / 8am EDT)

### spatial-health (weekly)

Queries the production web service's `spatial.db` via an authenticated HTTP
endpoint to verify all 11 expected tables are present, have row counts within
baseline tolerance, and haven't gone stale.

1. **+ New** → **GitHub Repo** → select NestCheck repo → name it `spatial-health`
2. **Settings** → **Build & Deploy**:
   - **Config File Path**: `railway-cron-spatial-health.toml`
3. **Variables** (service-specific):
   - `SPATIAL_HEALTH_NOTIFY_EMAIL` = your alert email
   - `NESTCHECK_WEB_URL` = production web service URL (e.g. `https://nestcheck.up.railway.app`)
4. **Variables** (shared with web service):
   - `SPATIAL_HEALTH_TOKEN` = shared secret token (set on BOTH web and spatial-health services)

Schedule: `0 14 * * 1` — Mondays at 14:00 UTC (9am EST / 10am EDT)

**No volume needed**: The cron service calls the web service's
`GET /api/spatial-health` endpoint, which checks the production volume's
`spatial.db` directly. This ensures the health check validates the actual
production data, not a separate copy. Runs are fast (~5s).

### regression (monthly)

Evaluates 7 test addresses, compares scores and health checks against saved
baselines, and emails a diff when regressions exceed thresholds.

1. **+ New** → **GitHub Repo** → select NestCheck repo → name it `regression`
2. **Settings** → **Build & Deploy**:
   - **Config File Path**: `railway-cron-regression.toml`
3. **Variables** (service-specific):
   - `REGRESSION_NOTIFY_EMAIL` = your alert email
4. **No volume needed** — baselines are JSON files in git, evaluations use live APIs

Schedule: `0 13 1 * *` — 1st of month at 13:00 UTC (8am EST / 9am EDT)

## Step 3: Deploy Config Files

The three `railway-cron-*.toml` files in the repo root define the start
command and cron schedule for each service. Railway reads these automatically
when the config file path is set in the service settings.

These files are already created in the repo. Verify them after setup:

```bash
cat railway-cron-smoke-test.toml
cat railway-cron-spatial-health.toml
cat railway-cron-regression.toml
```

## Step 4: Verify

After deployment, check each service's **Deployments** tab. Railway shows
the next scheduled run time. Verify it matches:

| Service | Schedule | Next Run |
|---------|----------|----------|
| `smoke-test` | `0 12 * * *` | Tomorrow at 12:00 UTC |
| `spatial-health` | `0 14 * * 1` | Next Monday at 14:00 UTC |
| `regression` | `0 13 1 * *` | 1st of next month at 13:00 UTC |

## Cron Service Requirements

Railway cron services **must exit** after completing their task. If the
process doesn't terminate, subsequent runs are skipped. All three scripts
exit with:

- Exit 0: success (pass / healthy / no regressions)
- Exit 1: failure (check failed / issues found / regressions detected)

## Baseline Management

### Spatial health baseline

Record the current row counts as baseline (run after spatial data changes):

```bash
make spatial-baseline
```

The baseline file (`data/spatial_baseline.json`) should be committed to git.

### Regression baselines

After an intentional scoring change, update baselines locally:

```bash
make regression-update
# Review the JSON diffs
git add data/regression_baselines/
git commit -m "Update regression baselines after scoring change"
```

## Troubleshooting

**Cron not firing**: Check the service's deployment logs for "Cron triggered"
entries. Railway's minimum interval is 5 minutes. All schedules are UTC.

**Process doesn't exit**: If a script hangs (e.g., API timeout without the
timeout parameter), Railway keeps the deployment running and skips subsequent
executions. All scripts use timeouts on network calls.

**spatial-health 401/404 errors**: Verify `SPATIAL_HEALTH_TOKEN` is set to
the same value on both the web service and the spatial-health cron service.
A 404 means the token is not set on the web service (endpoint disabled).
A 401 means the tokens don't match.

**Email not sending**: Verify `RESEND_API_KEY` is set on the cron service.
Each service has its own env var scope unless Shared Variables are used.
Check that the notify email variable is set on the specific service.

## Cost Estimate

Cron services are billed per execution (not always-on):

| Service | Runs/month | Time/run | Compute cost |
|---------|-----------|----------|--------------|
| `smoke-test` | ~30 | ~60s | ~$0.50 |
| `spatial-health` | ~4 | ~5s | ~$0.05 |
| `regression` | 1 | ~15 min | ~$0.50 |
| **Total** | | | **~$1.05/month** |
