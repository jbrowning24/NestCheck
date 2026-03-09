# ---------------------------------------------------------------------------
# NestCheck Makefile
# ---------------------------------------------------------------------------

# Post-deploy smoke test against production
smoke:
	python3 smoke_test.py

# Smoke test against local dev server (assumes running on port 5000)
smoke-local:
	python3 smoke_test.py http://localhost:5000

# Tri-state smoke test — submits evaluations for NY/CT/NJ and verifies results
smoke-tristate:
	python3 smoke_test_tristate.py

# Tri-state smoke test against local dev server
smoke-tristate-local:
	python3 smoke_test_tristate.py http://localhost:5000
