# Code Review Task

Perform comprehensive code review. Be thorough but concise.

## Check For:

**Logging** - No print() in production, uses logging module with context
**Error Handling** - Try/except for API calls, timeouts set, graceful degradation
**Type Hints** - Function signatures have type hints, no bare dicts where dataclasses fit
**Production Readiness** - No debug statements, no TODOs, no hardcoded secrets or API keys
**API Safety** - All external calls use `timeout=API_REQUEST_TIMEOUT`, quota errors handled
**SQLite** - Connections closed in finally blocks, busy_timeout set, retries for write contention
**Templates** - Smoke test markers match element IDs, no orphaned CSS selectors
**Security** - Inputs validated, CSRF protection, no SQL injection via string formatting
**Architecture** - Follows existing patterns in property_evaluator.py and app.py

## Output Format

### ✅ Looks Good
- [Item 1]
- [Item 2]

### ⚠️ Issues Found
- **[Severity]** [File:line] - [Issue description]
  - Fix: [Suggested fix]

### 📊 Summary
- Files reviewed: X
- Critical issues: X
- Warnings: X

## Severity Levels
- **CRITICAL** - Security, data loss, crashes
- **HIGH** - Bugs, performance issues, bad UX
- **MEDIUM** - Code quality, maintainability
- **LOW** - Style, minor improvements