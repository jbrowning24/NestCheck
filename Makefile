# ---------------------------------------------------------------------------
# NestCheck Makefile
# ---------------------------------------------------------------------------

# Post-deploy smoke test against production
smoke:
	python3 smoke_test.py

# Smoke test against local dev server (assumes running on port 5000)
smoke-local:
	python3 smoke_test.py http://localhost:5000
