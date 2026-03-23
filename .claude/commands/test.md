---
description: Run the test suite to verify changes before shipping
---

Determine what changed by examining the current diff (`git diff HEAD` or `git diff --cached`).

**Always run:**
```bash
python -m pytest tests/ -x -q --ignore=tests/playwright/ 2>&1 | tail -30
```

**If any of these paths appear in the diff, also run Playwright browser tests:**
- `templates/`
- `static/css/`
- `_macros.html`
- `_result_sections.html`
- `_report_rail.html`
- `app.py` (only if `result_to_dict`, `save_snapshot`, `_prepare_snapshot_for_display`, or `view_snapshot` were modified)
```bash
python -m pytest tests/playwright/ -x -v 2>&1 | tail -50
```

**Report format:**

Unit tests: ✅ X passed / ❌ X failed (list failures)
Browser tests: ✅ X passed / ❌ X failed / ⏭️ Skipped (no template changes)

If any test fails, stop and report the failure. Do NOT proceed to commit or ship.
Do NOT commit or push.
