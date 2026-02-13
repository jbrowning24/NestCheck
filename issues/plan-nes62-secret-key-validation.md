# NES-62: Crash on Insecure SECRET_KEY in Production

**Overall Progress:** `100%` · **Status:** Complete
**Last updated:** Feb 13, 2025

## TLDR
Add a startup guard that kills the app if `SECRET_KEY` is the hardcoded default (`'nestcheck-dev-key'`) and `FLASK_DEBUG` is not set. Prevents production deployments from running with a trivially guessable session secret.

## Critical Decisions
- **Detection method:** Check if key equals the hardcoded default string — no platform-specific env vars, no new config variables
- **Bypass:** Skip the check when `FLASK_DEBUG` is set — local `python app.py` keeps working as-is
- **Crash mechanism:** `sys.exit(1)` with stderr message — unambiguous, won't be swallowed by gunicorn's worker restart loop

## Tasks

- [ ] 🟩 **Step 1: Add startup guard in app.py**
  - [ ] 🟩 Add `import sys` to imports (line ~6, alongside other stdlib imports)
  - [ ] 🟩 Add guard block after line 57 (`app.config['SECRET_KEY'] = ...`), before the ProxyFix line:
    ```python
    if app.config['SECRET_KEY'] == 'nestcheck-dev-key' and not os.environ.get('FLASK_DEBUG'):
        print("FATAL: SECRET_KEY is not set. Refusing to start with insecure default.", file=sys.stderr)
        print("Set SECRET_KEY in your environment or .env file.", file=sys.stderr)
        sys.exit(1)
    ```

- [ ] 🟩 **Step 2: Update .env.example**
  - [ ] 🟩 Add commented `SECRET_KEY` line: `# SECRET_KEY=your-random-secret-here`

- [ ] 🟩 **Step 3: Update README.md environment variables table**
  - [ ] 🟩 Change `SECRET_KEY` row: mark as required for production, note that local dev falls back to default when `FLASK_DEBUG=1`

- [ ] 🟩 **Step 4: Verify**
  - [ ] 🟩 Confirm: no `SECRET_KEY` + no `FLASK_DEBUG` → `sys.exit(1)` with clear error
  - [ ] 🟩 Confirm: no `SECRET_KEY` + `FLASK_DEBUG=1` → app starts normally
  - [ ] 🟩 Confirm: `SECRET_KEY=something-real` + no `FLASK_DEBUG` → app starts normally
