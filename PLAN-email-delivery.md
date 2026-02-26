# Implementation Plan: Wire Up Email Delivery After Evaluation

**Progress:** [==========] 100%
**Status:** Complete
**Created:** 2026-02-25

## TL;DR
The form captures email but the backend ignores it. Resend is in `requirements.txt` but never imported. We need to store the email with each snapshot and send a report-ready link via Resend after evaluation completes. Email failure must never break evaluations.

## Architecture Notes

**Two evaluation paths exist:**
- **Synchronous** (`app.py` POST `/`): Evaluates inline, saves snapshot, returns redirect. Currently working.
- **Async** (`worker.py`): Job queue worker. Already threads `email_raw` through `_run_job()` but `models.py` doesn't accept it yet. Job queue functions (`create_job`, `claim_next_job`, etc.) are referenced in `worker.py` imports but not defined in `models.py` — async path is partially built.

**Email delivery must work for both paths** so it survives when the async path becomes primary.

## Critical Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Email storage | Nullable `email` + `email_sent_at` columns on `snapshots` table | Additive-only, no schema breaks |
| Migration pattern | `PRAGMA table_info` check + conditional `ALTER TABLE` | Matches existing pattern in `models.py:77-84` |
| Email sending | After snapshot save, in try/except | Never blocks or breaks evaluation |
| Sender address | `NestCheck <reports@nestcheck.com>` | Requires Resend domain verification (DNS records) |
| Magic-link form | Disable with "coming soon" | Prevents 404 on `/send-magic-link`; route doesn't exist |

## Pre-flight

- [ ] **Resend domain verification**: Add DNS records for `nestcheck.com` in Resend dashboard. Sends will be rejected until verified. ~5 minutes to set up + propagate.

## Tasks

### Phase 1: Data Layer
- [ ] 🟩 **Task 1.1: Add email columns to snapshots table**
  - File: `models.py`
  - Add `email TEXT` and `email_sent_at TEXT` (both nullable) to `CREATE TABLE IF NOT EXISTS snapshots`
  - Add migration block using existing `PRAGMA table_info` pattern (lines 77-84):
    ```python
    if "email" not in cols:
        conn.execute("ALTER TABLE snapshots ADD COLUMN email TEXT")
    if "email_sent_at" not in cols:
        conn.execute("ALTER TABLE snapshots ADD COLUMN email_sent_at TEXT")
    ```
  - Acceptance: `init_db()` runs without error on both fresh and existing databases. New columns visible in `PRAGMA table_info(snapshots)`.

- [ ] 🟩 **Task 1.2: Update `save_snapshot()` to accept email**
  - File: `models.py`
  - Add optional `email=None` parameter to `save_snapshot()` (line 106)
  - Include `email` in the INSERT statement
  - Acceptance: `save_snapshot(address, norm, result)` still works (backward compat). `save_snapshot(address, norm, result, email="test@example.com")` stores the email.

- [ ] 🟩 **Task 1.3: Update `save_snapshot_for_place()` to accept email**
  - File: `models.py`
  - Add optional `email=None` parameter to `save_snapshot_for_place()` (line 334)
  - Include `email` in both the INSERT and UPDATE branches
  - Acceptance: Both paths store email when provided, `None` when not.

- [ ] 🟩 **Task 1.4: Add `update_snapshot_email_sent()` helper**
  - File: `models.py`
  - New function: `update_snapshot_email_sent(snapshot_id: str) -> None`
  - Sets `email_sent_at` to current UTC ISO timestamp
  - Acceptance: After calling, `get_snapshot(id)["email_sent_at"]` returns a timestamp string.

### Phase 2: Capture Email in Form Submission
- [ ] 🟩 **Task 2.1: Read email in POST `/` route**
  - File: `app.py`
  - After `address = request.form.get("address", "").strip()` (line 475), add:
    `email = request.form.get("email", "").strip() or None`
  - Acceptance: Email value available in the route handler. No change to behavior when email is empty.

- [ ] 🟩 **Task 2.2: Pass email to `save_snapshot()` and `save_snapshot_for_place()`**
  - File: `app.py`
  - Add `email=email` to the `save_snapshot_for_place()` call (line 598) and `save_snapshot()` call (line 615)
  - Acceptance: Evaluations with email store it in the snapshot. Evaluations without email continue to work.

### Phase 3: Email Service
- [ ] 🟩 **Task 3.1: Create `email_service.py`**
  - New file: `email_service.py`
  - `send_report_email(to_email: str, snapshot_id: str, address: str) -> bool`
    - Uses `resend` library (already in requirements.txt)
    - API key from `os.environ.get("RESEND_API_KEY")`
    - From: `NestCheck <reports@nestcheck.com>`
    - Subject: `Your NestCheck Report is Ready`
    - Minimal HTML body: NestCheck branding, evaluated address, prominent link to `/s/{snapshot_id}`, one-line footer
    - Full try/except — logs errors, never raises
    - Returns `True` on success, `False` on failure
  - `send_magic_link_email(...)` stub returning `False` with `# TODO: Phase 3` comment
  - Acceptance: Function callable, returns bool. With valid API key + verified domain, email arrives. Without key, returns `False` and logs warning.

### Phase 4: Wire Sending into Completion Flow
- [ ] 🟩 **Task 4.1: Send email after snapshot save in `app.py` (sync path)**
  - File: `app.py`
  - After snapshot is saved (around line 620), if `email` is not None:
    - Call `send_report_email(email, snapshot_id, address)`
    - On success: call `update_snapshot_email_sent(snapshot_id)`, log event `email_sent`
    - On failure: log event `email_failed`
  - Wrap entire block in try/except — email failure must not affect the response
  - Acceptance: Email sent after successful evaluation. Evaluation still works if Resend is down.

- [ ] 🟩 **Task 4.2: Send email after snapshot save in `worker.py` (async path)**
  - File: `worker.py`
  - After `complete_job(job_id, snapshot_id)` (line 153), if `email_raw` is not None:
    - Import and call `send_report_email(email_raw, snapshot_id, address)`
    - On success: call `update_snapshot_email_sent(snapshot_id)`, log event `email_sent`
    - On failure: log event `email_failed`
  - Wrap in try/except
  - Acceptance: Worker sends email when email_raw is provided. Worker never crashes on email failure.

### Phase 5: Fix My Reports Page
- [ ] 🟩 **Task 5.1: Disable magic-link form in `my_reports.html`**
  - File: `templates/my_reports.html`
  - Replace the magic-link form (lines 77-86) with a "Coming soon" message
  - Keep the template intact — don't delete authenticated section
  - Remove or comment out the JS form handler (lines 131-175) since the form is gone
  - Acceptance: `/my-reports` no longer shows a form that 404s. Shows a friendly message instead.

## Testing Checklist

- [ ] **Schema migration**: Run `init_db()` on existing DB — no errors, columns added
- [ ] **Schema fresh**: Delete DB, run `init_db()` — clean table with email columns
- [ ] **Sync eval with email**: Submit form with email → snapshot has email stored
- [ ] **Sync eval without email**: Submit form without email → works as before
- [ ] **Email delivery**: With valid RESEND_API_KEY + verified domain, email arrives with correct link
- [ ] **Email failure resilience**: Set invalid API key → evaluation completes, email_failed event logged
- [ ] **Snapshot reuse**: Reused snapshot doesn't re-send email (no email send in reuse path)
- [ ] **My Reports page**: Visit `/my-reports` — no form, shows "coming soon" message
- [ ] **Resend domain**: Verify `nestcheck.com` domain in Resend dashboard before live testing

## Files Changed Summary

| File | What Changes |
|------|-------------|
| `models.py` | Add email + email_sent_at columns, migration, update save functions, new update helper |
| `app.py` | Read email from form, pass to save, send email after save |
| `email_service.py` | **New file** — Resend integration, send_report_email, stub for magic link |
| `worker.py` | Send email after snapshot save in async path |
| `templates/my_reports.html` | Disable magic-link form with "coming soon" message |

## What NOT to Touch

- `property_evaluator.py` — evaluation logic unchanged
- `green_space.py` — untouched
- `urban_access.py` — untouched
- Evaluation pipeline — email is metadata only, not an evaluation input
