# Implementation Plan: Add robots.txt, sitemap.xml, and SEO metadata

**Progress:** 100% · **Status:** Done
**Last updated:** 2026-02-13

## TLDR

Add `robots.txt` and `sitemap.xml` as Flask routes, block crawlers from internal endpoints, and add baseline SEO meta tags (`description`, `og:title`, `og:description`, `og:type`, `og:url`) to all public pages via `_base.html` with per-page overrides.

## Scope

**In scope:**
- `robots.txt` route with disallow rules and dynamic `Sitemap:` directive
- `sitemap.xml` route with static pages + all snapshot URLs from SQLite
- Default SEO meta tags in `_base.html`
- Per-page `description` and OG overrides for `index.html`, `snapshot.html`, `pricing.html`, `privacy.html`, `terms.html`

**Out of scope:**
- `og:image` (no asset ready — fast follow)
- Twitter Card meta tags
- JSON-LD structured data
- Sitemap pagination / sitemap index (not needed at current volume)
- Canonical URLs (straightforward follow-up but not in the ticket)

## Key Decisions

| # | Decision | Rationale |
|---|----------|-----------|
| 1 | Serve `robots.txt` and `sitemap.xml` as Flask routes, not static files | `sitemap.xml` must query snapshots from SQLite; `robots.txt` needs dynamic `Sitemap:` URL built from `request.host_url` |
| 2 | Include all snapshots in sitemap | Snapshots are the most linkable pages; addresses aren't sensitive since users chose to evaluate them |
| 3 | Skip `og:image` | No asset available; shipping the rest now, image is a fast follow |
| 4 | Build `Sitemap:` URL dynamically from `request.host_url` | App is still on a Render subdomain; hardcoding a domain would break |
| 5 | Put default meta tags in `_base.html`, override via `head_extra` block | Existing pattern — child templates already use `head_extra` for OG tags |

## Assumptions

- Snapshot volume is low enough that a single `sitemap.xml` with all entries will be fine (no index needed)
- `get_recent_snapshots()` in `models.py` can be adapted or a new query written to fetch all snapshot IDs + `created_at` for the sitemap without loading full `result_json`

## Tasks

- [x] 🟩 **1. Add `robots.txt` route** · _S_
  New route in `app.py` that returns a plain-text response with crawler rules.
  - [x] 🟩 1.1 Add `@app.route("/robots.txt")` returning `text/plain` response
  - [x] 🟩 1.2 Disallow: `/checkout/`, `/webhook/`, `/job/`, `/api/`, `/debug/`, `/builder/`, `/healthz`
  - [x] 🟩 1.3 Include `Sitemap:` directive using `request.host_url` (strip trailing slash, append `/sitemap.xml`)
  - [x] 🟩 1.4 Exempt route from rate limiter if default limits apply to all routes

- [x] 🟩 **2. Add sitemap query to `models.py`** · _S_
  The sitemap needs all snapshot IDs and their `created_at` timestamps without pulling full result JSON.
  - [x] 🟩 2.1 Add `get_all_snapshot_ids()` function that returns `[{snapshot_id, created_at}, ...]` ordered by `created_at DESC`
  - [x] 🟩 2.2 Query only `snapshot_id` and `created_at` columns for efficiency

- [x] 🟩 **3. Add `sitemap.xml` route** · _S_
  New route in `app.py` that returns a valid XML sitemap.
  - [x] 🟩 3.1 Add `@app.route("/sitemap.xml")` returning `application/xml` response
  - [x] 🟩 3.2 Include static pages: `/`, `/pricing`, `/privacy`, `/terms`
  - [x] 🟩 3.3 Include all snapshot URLs as `{host}/s/{snapshot_id}` with `<lastmod>` from `created_at`
  - [x] 🟩 3.4 Build all URLs dynamically from `request.host_url`
  - [x] 🟩 3.5 Exempt route from rate limiter

- [x] 🟩 **4. Add default SEO meta tags to `_base.html`** · _M_
  Establish baseline metadata that every page inherits, using Jinja2 variables so child templates can override.
  - [x] 🟩 4.1 Add `<meta name="description">` with a default NestCheck description inside `<head>`, controllable via a block or template variable
  - [x] 🟩 4.2 Add `og:title` defaulting to the page `<title>`
  - [x] 🟩 4.3 Add `og:description` defaulting to the same description
  - [x] 🟩 4.4 Add `og:type` defaulting to `"website"`
  - [x] 🟩 4.5 Add `og:url` using `request.url`

- [x] 🟩 **5. Add per-page meta overrides** · _S_
  Fill in richer descriptions for pages that currently have none.
  - [x] 🟩 5.1 `index.html` — add a default description for the landing page (no-result state); keep existing conditional OG tags for the result state
  - [x] 🟩 5.2 `snapshot.html` — already has OG tags; ensure they integrate cleanly with new base defaults (no duplicate tags)
  - [x] 🟩 5.3 `pricing.html` — add description and og_tags: pricing ($9 for 3 evaluations) and value prop
  - [x] 🟩 5.4 `privacy.html` — add description and og_tags: privacy policy summary
  - [x] 🟩 5.5 `terms.html` — add description and og_tags: terms of service summary

## Verification

- [x] `curl localhost:5001/robots.txt` returns valid plain-text with all disallow rules and a `Sitemap:` line
- [x] `curl localhost:5001/sitemap.xml` returns valid XML containing static pages and at least one snapshot URL (if any exist in DB)
- [x] View page source on `/`, `/pricing`, `/privacy`, `/terms`, `/s/<id>` — each has `description`, `og:title`, `og:description`, `og:type`, `og:url` meta tags with page-appropriate content
- [x] No duplicate meta tags on `snapshot.html` or `index.html` (where child templates override base defaults)
