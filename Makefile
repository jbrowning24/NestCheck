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

# ---------------------------------------------------------------------------
# CI gates (NES-278)
# ---------------------------------------------------------------------------

# Scoring regression tests (fast, no external deps)
test-scoring:
	python3 -m pytest tests/test_scoring_regression.py tests/test_scoring_config.py -v --tb=short

# Ground truth validation (requires spatial.db + SpatiaLite)
validate:
	python3 scripts/validate_all_ground_truth.py

# Full CI gate — both scoring tests and ground truth validation
ci: test-scoring validate
