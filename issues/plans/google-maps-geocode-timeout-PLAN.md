# Feature Implementation Plan: Google Maps / API timeouts

**Overall Progress:** `75%`

## TLDR

Add timeouts to all Google Maps and Overpass API HTTP requests so evaluations fail fast and predictably instead of hanging or relying on external timeouts. Optional: document timeout/quota behavior; later: consider retries with backoff.

## Critical Decisions

- **Single timeout constant (25s)** — One `API_REQUEST_TIMEOUT` for all Maps and Overpass calls for consistency and one place to tune; aligns with Overpass server `[timeout:25]` and existing Walk Score timeouts (10–15s).
- **Include OverpassClient** — Same pattern as Maps (session call with no timeout); avoids the same class of hang and keeps behavior consistent.
- **Timeouts only for now** — No retries yet; existing call-site `try/except` already handles failures and degrades gracefully. Retries can be added later with backoff to avoid rate limits.

## Tasks

- [x] 🟩 **Step 1: Add timeout constant and apply to GoogleMapsClient**
  - [x] 🟩 Define `API_REQUEST_TIMEOUT = 25` in the API clients section of `property_evaluator.py`.
  - [x] 🟩 Pass `timeout=API_REQUEST_TIMEOUT` on all 7 `session.get()` calls: `geocode`, `places_nearby`, `place_details`, `walking_time`, `driving_time`, `transit_time`, `text_search`.

- [x] 🟩 **Step 2: Apply timeout to OverpassClient**
  - [x] 🟩 Pass `timeout=API_REQUEST_TIMEOUT` on `session.post()` in `get_nearby_roads`.

- [x] 🟩 **Step 3: Document timeout and quota behavior**
  - [x] 🟩 Add a short note in README or a comment near `API_REQUEST_TIMEOUT`: that timeouts avoid indefinite hangs, and that repeated timeouts may be quota-related (e.g. Google Maps API limits).

- [ ] 🟥 **Step 4 (Optional / later): Retries with backoff**
  - [ ] 🟥 If transient timeouts remain an issue: add retries (e.g. exponential backoff, max attempts) for Maps/Overpass calls; respect rate limits and document in README.
