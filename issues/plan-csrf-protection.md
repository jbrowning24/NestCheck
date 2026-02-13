# NES-59: Add CSRF Protection via Flask-WTF

**Overall Progress:** `100%`

## TLDR
Add CSRF protection to all browser-facing POST endpoints using Flask-WTF's `CSRFProtect`. Render token via `<meta>` tag, send via `X-CSRFToken` header on all `fetch()` calls. Exempt only the Stripe webhook (server-to-server with its own signature verification).

## Critical Decisions
- **Meta tag + header only** — no hidden `<input>` fields. All forms submit via JS `fetch()`, so hidden fields would be dead code.
- **Protect all 4 browser-facing POSTs** — including `/api/event` and `/debug/eval`. No "low-risk" exemptions.
- **Exempt `/webhook/stripe` only** — it has Stripe signature verification and CSRF would break it.
- **Global `CSRFProtect`** — use Flask-WTF's app-wide CSRF rather than per-route decorators. Simpler, safer default.

## Tasks

- [x] 🟩 **Step 1: Install Flask-WTF**
  - [x] 🟩 `pip install Flask-WTF` and add to `requirements.txt`

- [x] 🟩 **Step 2: Initialize CSRFProtect in app.py**
  - [x] 🟩 Import `CSRFProtect` from `flask_wtf.csrf` (line 14)
  - [x] 🟩 Call `csrf = CSRFProtect(app)` after app creation (line 56)
  - [x] 🟩 Add `@csrf.exempt` decorator to `stripe_webhook()` (line 1373)

- [x] 🟩 **Step 3: Add CSRF meta tag to base template**
  - [x] 🟩 Add `<meta name="csrf-token" content="{{ csrf_token() }}">` before `</head>` in `_base.html` (line 10) — inherited by all pages

- [x] 🟩 **Step 4: Add X-CSRFToken header to all fetch() POST calls**
  - [x] 🟩 Add `csrfToken()` helper + `X-CSRFToken` header on `fetch('/')` in `index.html` (lines 128-131, 236)
  - [x] 🟩 Add `X-CSRFToken` header on `fetch('/checkout/create')` in `index.html` (line 280)
  - [x] 🟩 Add `X-CSRFToken` header on `fetch('/api/event')` in `index.html` (line 363)
  - [x] 🟩 Add `csrfToken()` helper + `X-CSRFToken` header on `fetch('/api/event')` in `snapshot.html` (lines 47-50, 67)

- [x] 🟩 **Step 5: Smoke test**
  - [x] 🟩 POST without token → 400 (CSRF rejected)
  - [x] 🟩 POST /webhook/stripe without token → passes (exempt, fails on Stripe signature instead)
  - [x] 🟩 POST with valid X-CSRFToken header → 200 (evaluation job created)

## Files Changed
| File | Change |
|------|--------|
| `requirements.txt` | Add `Flask-WTF==1.2.2`, `WTForms==3.2.1` |
| `app.py` | Import + init `CSRFProtect`, exempt webhook |
| `templates/_base.html` | CSRF meta tag (inherited by all pages) |
| `templates/index.html` | `csrfToken()` helper + `X-CSRFToken` header on 3 fetch calls |
| `templates/snapshot.html` | `csrfToken()` helper + `X-CSRFToken` header on 1 fetch call |
