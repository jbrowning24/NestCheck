# B2B API Licensing Spec

> Planning document for NestCheck partner API access.
> Status: Draft | NES-327

---

## 1. API Contract

### Endpoint

```
POST /api/v1/evaluate
```

### Authorization

```
Authorization: Bearer nc_live_<32 hex chars>
```

### Request Body

```json
{
  "address": "123 Main St, White Plains, NY 10601",
  "place_id": "ChIJ..."
}
```

- `address` (required) — Full street address including zip code.
- `place_id` (optional) — Google Place ID. When provided, bypasses geocoding for faster + more accurate lookups.

### Response

Returns the same JSON shape produced by `result_to_dict()` in `app.py` (line 2244). Refer to that function as the canonical schema definition — do not maintain a duplicate schema here.

### Rate Limits

| Tier       | Limit                  |
|------------|------------------------|
| Default    | 100 requests/hour      |
| Enterprise | Negotiated per partner |

Rate limit headers included in every response:

```
X-RateLimit-Limit: 100
X-RateLimit-Remaining: 87
X-RateLimit-Reset: 1711234567
```

HTTP 429 returned when exceeded.

---

## 2. Authentication Model

### Key Format

```
nc_live_<32 hex chars>
```

The `nc_live_` prefix allows quick identification in logs and support tickets without exposing the full key.

### Storage

- Keys are stored as **SHA-256 hashes** in the `partner_api_keys` table — never plaintext.
- The raw key is shown exactly once at provisioning time.

### Scoping & Revocation

- Each key is scoped to a single partner account.
- Keys can be revoked independently without affecting other partners.
- Multiple keys per partner are supported (e.g., separate keys for staging vs. production).

### Table Schema (conceptual)

| Column         | Type      | Notes                        |
|----------------|-----------|------------------------------|
| id             | UUID      | PK                           |
| partner_id     | UUID      | FK to partners table         |
| key_hash       | TEXT      | SHA-256 of the full API key  |
| key_prefix     | TEXT      | First 12 chars for lookup    |
| label          | TEXT      | e.g., "production", "staging"|
| created_at     | TIMESTAMP |                              |
| revoked_at     | TIMESTAMP | NULL if active               |

---

## 3. Partner Categories

### Relocation Companies

Companies like Cartus, SIRVA, and Graebel that evaluate destination cities for transferees. Primary use: neighborhood safety, school quality, and environmental risk data for relocation packages.

### Corporate HR

Internal HR teams managing employee relocation. Similar data needs to relocation companies but consumed via internal tools rather than customer-facing reports.

### Home Insurers

Underwriting enrichment — particularly health hazard proximity data (EPA Superfund sites, industrial facilities, flood zones). Supplements existing risk models with hyperlocal environmental signals.

### Home Inspection Firms

Pre-inspection environmental screening. Inspectors use NestCheck data to flag potential concerns (nearby contamination, noise sources, flood risk) before arriving on-site.

---

## 4. Onboarding Flow

1. **Inquiry** — Partner contacts via email or website form.
2. **Agreement** — NDA + data licensing agreement executed.
3. **Provisioning** — API key generated manually by NestCheck team. Key shown once; partner stores it securely.
4. **Sandbox** — Partner integrates against sandbox environment with a fixed set of test addresses (deterministic responses, no external API calls).
5. **Production** — After successful sandbox integration, production key issued with usage dashboard access.

### Initial Simplicity

V1 onboarding is entirely manual. No self-service portal. This is intentional — at low partner volumes, manual onboarding allows us to learn what partners actually need before automating.

---

## 5. Future Considerations (not for V1)

These are scoped out of the initial release but captured here for planning:

- **Batch endpoint** — `POST /api/v1/evaluate/batch` accepting an array of addresses. Returns a job ID; results retrieved via polling or webhook.
- **Webhook notifications** — Partner-configured URL called when async evaluations complete.
- **Usage analytics dashboard** — Self-service view of API call volume, error rates, and latency percentiles.
- **Custom report templates** — Per-partner response shaping (e.g., insurer gets environmental fields only, relocation company gets schools + safety).
- **Self-service key management** — Partner portal for rotating keys, viewing usage, managing team access.

---

## Open Questions

- Pricing model: per-call vs. monthly tier vs. annual license?
- SLA commitments for response time and uptime?
- Data freshness guarantees (how often underlying sources update)?
- Geographic coverage limitations to communicate upfront?
