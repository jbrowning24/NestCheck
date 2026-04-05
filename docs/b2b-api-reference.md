# NestCheck B2B API Reference

Partner-facing API reference for integrating with NestCheck's property evaluation service.

---

## Overview

NestCheck evaluates residential addresses across health, environmental, walkability, green space, transit, and amenity dimensions. It returns a composite score (0–10) alongside individual dimension scores and a set of health/hazard checks.

**Current coverage:**
- Westchester County, NY (Metro-North corridor)
- DC / Maryland / Virginia metro area

Evaluations are asynchronous. You submit an address, receive a job ID, and poll until the result is ready — typically under 30 seconds.

---

## Authentication

API keys come in two forms:

| Type | Prefix | Use |
|------|--------|-----|
| Sandbox | `nc_test_` | Development and testing |
| Production | `nc_live_` | Live integration |

Both follow the format `nc_<env>_<32 hex chars>`. Keys are provisioned by the NestCheck team — there is no self-service portal.

Send your key as a Bearer token on every request:

```
Authorization: Bearer nc_live_a1b2c3d4e5f6...
```

Keys are shown exactly once at provisioning time. Store them securely (environment variables, a secrets manager). If a key is lost or compromised, contact NestCheck to revoke and reissue.

---

## Quick Start

### 1. Submit an address for evaluation

```bash
curl -X POST https://api.nestcheck.com/api/v1/b2b/evaluate \
  -H "Authorization: Bearer nc_live_a1b2c3d4e5f6..." \
  -H "Content-Type: application/json" \
  -d '{"address": "123 Main St, White Plains, NY 10601"}'
```

Response:

```json
{
  "job_id": "a8f3c2e1-4b5d-4f6a-9c1e-2d3f4a5b6c7d",
  "status": "queued"
}
```

### 2. Poll for the result

```bash
curl https://api.nestcheck.com/api/v1/b2b/jobs/a8f3c2e1-4b5d-4f6a-9c1e-2d3f4a5b6c7d \
  -H "Authorization: Bearer nc_live_a1b2c3d4e5f6..."
```

Poll every 2 seconds until `status` is `done` or `failed`.

### 3. Test with a sandbox key

Replace `nc_live_` with `nc_test_` in the Authorization header. Sandbox keys return pre-computed results for a fixed set of test addresses without making external API calls. Contact NestCheck for the current sandbox address list.

---

## POST /api/v1/b2b/evaluate

Submit an address for evaluation.

### Request body

```json
{
  "address": "123 Main St, White Plains, NY 10601",
  "place_id": "ChIJ..."
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `address` | string | Yes | Full street address including city, state, and zip code |
| `place_id` | string | No | Google Place ID. When provided, bypasses geocoding for faster and more accurate results |

### Responses

**202 Queued**

```json
{
  "job_id": "a8f3c2e1-4b5d-4f6a-9c1e-2d3f4a5b6c7d",
  "status": "queued"
}
```

**400 Invalid request**

```json
{
  "error": "invalid_request",
  "message": "address is required"
}
```

**401 Unauthorized**

```json
{
  "error": "unauthorized",
  "message": "Invalid or missing API key"
}
```

**403 Suspended**

```json
{
  "error": "suspended",
  "message": "This API key has been suspended. Contact support."
}
```

**422 Address not in coverage area**

```json
{
  "error": "address_not_in_coverage",
  "message": "Address is outside supported coverage areas"
}
```

**429 Rate limit or quota exceeded**

```json
{
  "error": "rate_limit_exceeded",
  "message": "Rate limit exceeded. Retry after 3600 seconds.",
  "retry_after": 3600
}
```

Rate limit headers are included on every response:

```
X-RateLimit-Limit: 100
X-RateLimit-Remaining: 87
X-RateLimit-Reset: 1711234567
```

**503 Sandbox not configured**

```json
{
  "error": "internal_error",
  "message": "Sandbox environment is not available"
}
```

---

## GET /api/v1/b2b/jobs/{job_id}

Retrieve the status and result of an evaluation job.

### Path parameters

| Parameter | Description |
|-----------|-------------|
| `job_id` | The job ID returned by POST /evaluate |

### Responses

**Queued**

```json
{
  "job_id": "a8f3c2e1-...",
  "status": "queued"
}
```

**Running**

```json
{
  "job_id": "a8f3c2e1-...",
  "status": "running",
  "stage": "Analyzing transit access"
}
```

**Done**

```json
{
  "job_id": "a8f3c2e1-...",
  "status": "done",
  "result": { ... }
}
```

See [Response Schema](#response-schema) for the full `result` structure.

**Failed**

```json
{
  "job_id": "a8f3c2e1-...",
  "status": "failed",
  "error_message": "Unable to geocode address"
}
```

**404 Not found**

```json
{
  "error": "not_found",
  "message": "Job not found"
}
```

---

## Response Schema

The `result` object returned in a completed job:

### Top-level fields

| Field | Type | Description |
|-------|------|-------------|
| `composite_score` | integer (0–10) | Overall property score, equally weighted across all scored dimensions |
| `composite_band` | string | Score band label (see [Dimension Scores](#dimension-scores)) |
| `snapshot_id` | string | Unique identifier for this evaluation result |
| `snapshot_url` | string | Public URL to the full NestCheck report for this address |
| `evaluated_at` | string (ISO 8601) | Timestamp when the evaluation completed |
| `data_confidence` | string | `verified`, `estimated`, or `limited` |

### health

```json
{
  "health": {
    "clear_count": 6,
    "warning_count": 1,
    "issue_count": 1,
    "checks": [
      {
        "name": "Flood Zone",
        "status": "fail",
        "distance_ft": null,
        "description": "Property is in a FEMA Special Flood Hazard Area (Zone AE)"
      },
      {
        "name": "Gas Station Proximity",
        "status": "pass",
        "distance_ft": 2640,
        "description": "Nearest gas station is 0.5 miles away"
      }
    ]
  }
}
```

| Field | Type | Description |
|-------|------|-------------|
| `clear_count` | integer | Number of checks with status `pass` |
| `warning_count` | integer | Number of checks with status `warning` |
| `issue_count` | integer | Number of checks with status `fail` |
| `checks[].name` | string | Check name (see [Health Checks Reference](#health-checks-reference)) |
| `checks[].status` | string | `pass`, `warning`, or `fail` |
| `checks[].distance_ft` | integer or null | Distance to the nearest relevant feature, in feet. Null for area-based checks (e.g., flood zone) |
| `checks[].description` | string | Human-readable summary of the finding |

### dimensions

Each dimension has a `score` and `band`. Some dimensions include additional detail fields.

```json
{
  "dimensions": {
    "walkability": {
      "score": 8,
      "band": "Strong",
      "walk_score": 74
    },
    "green_space": {
      "score": 6,
      "band": "Moderate"
    },
    "transit": {
      "score": 9,
      "band": "Exceptional",
      "transit_score": 88
    },
    "third_place": {
      "score": 7,
      "band": "Strong"
    },
    "fitness": {
      "score": 5,
      "band": "Moderate"
    },
    "provisioning": {
      "score": 8,
      "band": "Strong"
    }
  }
}
```

| Dimension | Description | Extra fields |
|-----------|-------------|--------------|
| `walkability` | Access to daily destinations on foot | `walk_score` (0–100 Walk Score) |
| `green_space` | Proximity to parks, trails, and natural areas | — |
| `transit` | Rail and bus access, commute viability | `transit_score` (0–100 Transit Score) |
| `third_place` | Coffee shops, restaurants, social venues | — |
| `fitness` | Gyms, yoga, fitness studios | — |
| `provisioning` | Grocery stores and essential retail | — |

A dimension score of `null` means no eligible venues were found to score it. Null dimensions are excluded from the composite score.

---

## Health Checks Reference

| Check name | What it detects |
|------------|-----------------|
| Gas Station Proximity | Proximity to gas stations, which may indicate air quality concerns from vehicle exhaust and fuel vapors |
| Highway Proximity | Distance to limited-access highways; close proximity is associated with elevated particulate matter and noise |
| High-Traffic Road | Presence of high-volume arterial roads within a health-relevant distance |
| Power Lines | High-voltage transmission lines overhead or nearby |
| Flood Zone | FEMA-designated Special Flood Hazard Areas (Zones A, AE, AO, etc.) |
| Superfund Site | EPA National Priorities List sites within proximity |
| TRI Facility | Toxic Release Inventory industrial facilities within proximity |
| Underground Storage Tanks | Known underground storage tank sites (gas stations, former industrial uses) that may indicate soil or groundwater contamination risk |

Checks marked `fail` indicate the property is within a health-relevant threshold distance. Checks marked `warning` indicate borderline proximity worth noting. `pass` means no concern was found.

---

## Dimension Scores

All dimension scores use a 0–10 integer scale with the following bands:

| Band | Score range |
|------|-------------|
| Exceptional | 9–10 |
| Strong | 7–8 |
| Moderate | 5–6 |
| Limited | 3–4 |
| Poor | 0–2 |

The `composite_score` applies the same scale and bands. It is an equal-weight average of all non-null dimension scores. Suppressed dimensions (no eligible venues) are excluded from both the numerator and denominator.

---

## Error Handling

All error responses follow this shape:

```json
{
  "error": "<error_code>",
  "message": "<human-readable description>"
}
```

| Error code | HTTP status | Description |
|------------|-------------|-------------|
| `unauthorized` | 401 | Missing or invalid API key |
| `suspended` | 403 | API key has been suspended; contact support |
| `invalid_request` | 400 | Missing required field or malformed input |
| `address_not_in_coverage` | 422 | Address is outside supported coverage areas |
| `rate_limit_exceeded` | 429 | Exceeded 100 requests per hour |
| `quota_exceeded` | 429 | Exceeded the monthly quota for your account |
| `not_found` | 404 | Job ID does not exist |
| `evaluation_failed` | 200 | Job completed but evaluation encountered an error (check `error_message` in job response) |
| `internal_error` | 500 | Unexpected server error; safe to retry with backoff |

**Rate limits:** 100 requests per hour by default. Enterprise partners have negotiated limits. Rate limit headers (`X-RateLimit-Limit`, `X-RateLimit-Remaining`, `X-RateLimit-Reset`) are included on every response.

**Quota:** Per your partner agreement. Contact NestCheck if you need a higher allocation.

---

## Sandbox Testing

Sandbox keys (`nc_test_...`) return pre-computed, deterministic results for a fixed set of test addresses. No external API calls are made in sandbox mode.

To get started with sandbox testing:
1. Request sandbox credentials from the NestCheck team.
2. Ask for the current sandbox address list — a set of addresses with known, stable results covering the full range of scores and health check outcomes.
3. Integrate against sandbox until you're confident in your integration, then request production credentials.

You can identify sandbox responses by the `sandbox: true` field in the job result.

---

## Best Practices

**Polling cadence:** Poll GET /jobs/{job_id} every 2 seconds. Most evaluations complete within 15–30 seconds. Do not poll faster than once per second.

**Caching:** Results are stable for a given `snapshot_id`. Cache by `snapshot_id` to avoid redundant API calls for the same evaluation. If you need a fresh evaluation for an address you've seen before, submit a new POST /evaluate request.

**Attribution:** When displaying NestCheck scores or health checks in your product, include attribution to NestCheck. The `snapshot_url` field links to the full NestCheck report, which you may surface to end users.

**Error handling:** Implement exponential backoff on `internal_error` (500) responses. Do not retry `address_not_in_coverage` (422) or `unauthorized` (401) — these require action before retrying.

**Coverage check:** Before submitting a batch of addresses, consider filtering for coverage area (Westchester County NY or DC/MD/VA metro) to avoid 422 errors.

---

## Support

For key provisioning, quota increases, sandbox access, or integration questions, contact the NestCheck team at the address provided during onboarding.
