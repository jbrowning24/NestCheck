# NES-225: User Accounts + Authentication (Flask-Login + Google OAuth)

## Overview

Add Google OAuth sign-in to NestCheck using Flask-Login for session management and Authlib for the OAuth flow. All existing routes stay public. Auth only gates `/my-reports`. Auto-claim snapshots matching the user's Google email.

## Design Decisions

- **Google OAuth only** — no password-based auth, keeps UX simple
- **Flask-Login** — lightweight session management, integrates with Flask's `g` and `request` context
- **Authlib** — battle-tested OAuth library, cleaner than hand-rolling
- **Raw sqlite3** — match existing `_get_db()` pattern, no ORM
- **Auto-detect OAuth redirect URI** from `request.host_url` (works for localhost + production)
- **All routes stay public** — auth only required for `/my-reports`
- **Auto-claim** snapshots by email match on first sign-in

---

## Step 1: Dependencies

**File: `requirements.txt`**

Add:
```
Flask-Login==0.6.3
Authlib==1.4.1
```

---

## Step 2: SQLite Schema — Users Table

**File: `models.py`**

Add `users` table + `user_id` column on `snapshots`:

```sql
CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,           -- uuid hex
    email TEXT UNIQUE NOT NULL,
    name TEXT,
    picture_url TEXT,
    google_sub TEXT UNIQUE,        -- Google subject ID (stable identifier)
    created_at TEXT DEFAULT (datetime('now')),
    last_login_at TEXT
);

-- Nullable FK on snapshots for backward compat
ALTER TABLE snapshots ADD COLUMN user_id TEXT REFERENCES users(id);
CREATE INDEX IF NOT EXISTS idx_snapshots_user_id ON snapshots(user_id);
```

Functions to add:
- `init_users_table()` — CREATE TABLE IF NOT EXISTS + ALTER TABLE (idempotent)
- `get_user_by_id(user_id)` → dict or None
- `get_user_by_email(email)` → dict or None
- `get_user_by_google_sub(google_sub)` → dict or None
- `create_user(email, name, picture_url, google_sub)` → user dict
- `update_user_last_login(user_id)` → None
- `claim_snapshots_for_user(user_id, email)` → int (count claimed)
- `get_user_snapshots(user_id, limit=50)` → list of snapshot dicts

---

## Step 3: Flask-Login Integration

**File: `app.py`**

### 3a: User class for Flask-Login

```python
class User:
    """Minimal user class for Flask-Login (not a db model)."""
    def __init__(self, user_dict):
        self.id = user_dict["id"]
        self.email = user_dict["email"]
        self.name = user_dict.get("name")
        self.picture_url = user_dict.get("picture_url")
        self.is_authenticated = True
        self.is_active = True
        self.is_anonymous = False

    def get_id(self):
        return self.id
```

### 3b: Login manager setup

```python
from flask_login import LoginManager, login_user, logout_user, current_user, login_required

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "auth_login"

@login_manager.user_loader
def load_user(user_id):
    user_dict = models.get_user_by_id(user_id)
    if user_dict:
        return User(user_dict)
    return None
```

### 3c: Update `_set_request_context`

Add after existing `g.visitor_id` setup:
```python
g.user_email = current_user.email if current_user.is_authenticated else None
g.user_name = current_user.name if current_user.is_authenticated else None
```

---

## Step 4: Google OAuth Routes

**File: `app.py`**

### 4a: Authlib OAuth setup

```python
from authlib.integrations.flask_client import OAuth

oauth = OAuth(app)
oauth.register(
    name="google",
    client_id=os.environ.get("GOOGLE_CLIENT_ID"),
    client_secret=os.environ.get("GOOGLE_CLIENT_SECRET"),
    server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
    client_kwargs={"scope": "openid email profile"},
)
```

### 4b: Routes

```
GET  /auth/login          — Redirect to Google OAuth
GET  /auth/callback       — Handle OAuth callback, create/find user, login
GET  /auth/logout         — Logout + redirect to /
```

**Login flow:**
1. User clicks "Sign in with Google"
2. `/auth/login` stores `next` URL in session, redirects to Google
3. Google redirects back to `/auth/callback`
4. Callback: verify token, extract email/name/sub
5. Find or create user by `google_sub` (or email for first-time linking)
6. On first login: `claim_snapshots_for_user(user_id, email)`
7. `login_user(user)` + redirect to `next` or `/my-reports`

---

## Step 5: My Reports Route

**File: `app.py`**

```python
@app.route("/my-reports")
@login_required
def my_reports():
    snapshots = models.get_user_snapshots(current_user.id)
    return render_template("my_reports.html",
        authenticated=True,
        email=current_user.email,
        snapshots=snapshots,
    )
```

---

## Step 6: Link New Evaluations to User

**File: `app.py`** — in the POST `/` handler

When creating a job, if `current_user.is_authenticated`, pass `user_id` to the job. When the worker saves the snapshot, propagate `user_id` to the snapshot row.

**File: `models.py`** — update `save_snapshot()` to accept optional `user_id`
**File: `worker.py`** — pass `user_id` from job to `save_snapshot()`

---

## Step 7: Template Updates

### 7a: `_base.html` — Nav auth buttons

Replace line 36 area:
```html
{% if current_user.is_authenticated %}
  <a href="/my-reports" class="nav-link">My Reports</a>
  <a href="/auth/logout" class="nav-link">Sign Out</a>
{% else %}
  <a href="/auth/login" class="nav-link">Sign In</a>
{% endif %}
```

### 7b: `my_reports.html` — Wire up authenticated state

Already has template structure for `authenticated`, `email`, `snapshots`. Minimal updates needed to show real data.

---

## Step 8: Env Vars

**File: `.env.example`**

```
# Google OAuth (required for sign-in)
GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=
```

---

## Step 9: Schema Migration on Startup

**File: `app.py`** or `gunicorn_config.py`

Call `models.init_users_table()` on app startup (idempotent CREATE TABLE IF NOT EXISTS + safe ALTER TABLE).

---

## File Change Summary

| File | Change |
|------|--------|
| `requirements.txt` | Add Flask-Login, Authlib |
| `models.py` | Users table, user CRUD, snapshot claiming, user_id on snapshots |
| `app.py` | Flask-Login setup, OAuth routes, User class, /my-reports, before_request update |
| `worker.py` | Pass user_id from job to snapshot |
| `templates/_base.html` | Auth nav buttons (sign in / sign out / my reports) |
| `templates/my_reports.html` | Minor updates for real snapshot data |
| `.env.example` | Google OAuth env vars |
| `static/css/base.css` | Minimal nav button styles for auth links |

---

## Status

- [ ] Step 1: Dependencies
- [ ] Step 2: Schema + models.py
- [ ] Step 3: Flask-Login integration in app.py
- [ ] Step 4: Google OAuth routes
- [ ] Step 5: My Reports route
- [ ] Step 6: Link evaluations to user
- [ ] Step 7: Template updates
- [ ] Step 8: Env vars
- [ ] Step 9: Startup migration
