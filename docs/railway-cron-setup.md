# Railway Cron Services Setup

NestCheck uses three scheduled automation scripts. Railway supports cron jobs
as separate services, but **volumes cannot be shared across services**. This
constraint shapes the setup.

## Architecture

```
Railway Project: NestCheck
├── web (existing)        — gunicorn, owns volume at /app/data
├── smoke-test (cron)     — daily, no volume needed
├── spatial-health (cron) — weekly, needs its own volume
└── regression (cron)     — monthly, no volume needed
```

### Volume Constraint

Railway volumes are attached to a single service and cannot be mounted by
multiple services. The web service owns the volume at `/app/data` containing
`spatial.db`. Cron services that need spatial data must have their own volume
and run `startup_ingest.py` on first boot to populate it.

| Service | Needs Volume? | Why |
|---------|--------------|-----|
| `smoke-test` | No | Runs evaluation via API calls, no direct DB reads |
| `spatial-health` | Yes (own volume) | Queries `spatial.db` row counts and staleness |
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

Queries `spatial.db` to verify all 11 expected tables are present, have row
counts within baseline tolerance, and haven't gone stale.

1. **+ New** → **GitHub Repo** → select NestCheck repo → name it `spatial-health`
2. **Settings** → **Build & Deploy**:
   - **Config File Path**: `railway-cron-spatial-health.toml`
3. **Volumes** → **Add Volume**:
   - Mount path: `/app/data`
   - Size: 5 GB
4. **Variables** (service-specific):
   - `SPATIAL_HEALTH_NOTIFY_EMAIL` = your alert email
   - `RAILWAY_VOLUME_MOUNT_PATH` = `/app/data`

Schedule: `0 14 * * 1` — Mondays at 14:00 UTC (9am EST / 10am EDT)

**First run**: The start command runs `startup_ingest.py` before the health
check to populate `spatial.db` on this service's volume. The first execution
takes longer (~5-10 min for ingestion). Subsequent runs are fast (~5s) since
data persists on the volume between cron executions and `startup_ingest.py`
skips tables that already have data.

**Data freshness**: This volume is independent of the web service's volume.
The spatial data will match the web service's data in content (same ingest
scripts, same sources) but may differ in ingestion timestamps. For health
checking purposes — verifying tables exist, row counts are stable, data
isn't stale — this is fine.

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

**spatial.db not found (spatial-health)**: Verify the volume mount path
matches `RAILWAY_VOLUME_MOUNT_PATH`. The first run must complete
`startup_ingest.py` to populate the DB. Check the deployment logs for
ingestion progress.

**Email not sending**: Verify `RESEND_API_KEY` is set on the cron service.
Each service has its own env var scope unless Shared Variables are used.
Check that the notify email variable is set on the specific service.

## Cost Estimate

Cron services are billed per execution (not always-on):

| Service | Runs/month | Time/run | Compute cost |
|---------|-----------|----------|--------------|
| `smoke-test` | ~30 | ~60s | ~$0.50 |
| `spatial-health` | ~4 | ~5s (after first) | ~$0.05 |
| `regression` | 1 | ~15 min | ~$0.50 |
| Extra volume (spatial-health) | — | — | ~$1.25 |
| **Total** | | | **~$2.30/month** |
