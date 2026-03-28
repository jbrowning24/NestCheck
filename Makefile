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
	python3 -m pytest tests/test_scoring_regression.py tests/test_scoring_config.py tests/test_overflow.py tests/test_schema_migration.py tests/test_scoring_key.py tests/test_section_freshness.py -v --tb=short

# Schema migration test — verifies init_db() against oldest known schema (NES-379)
test-schema:
	python3 -m pytest tests/test_schema_migration.py -v --tb=short

# Ground truth validation (requires spatial.db + SpatiaLite)
validate:
	python3 scripts/validate_all_ground_truth.py

# Playwright browser tests (NES-378)
test-browser:
	python3 -m pytest tests/playwright/ -v --tb=short

# Full CI gate — scoring tests, browser tests, and ground truth validation
ci: test-scoring test-browser validate

# ---------------------------------------------------------------------------
# Regression baselines (monthly)
# ---------------------------------------------------------------------------

# Compare current evaluations against saved baselines
regression:
	python3 scripts/regression_baseline.py

# Compare without sending email
regression-dry:
	python3 scripts/regression_baseline.py --dry-run

# Save new baselines after intentional scoring changes
regression-update:
	python3 scripts/regression_baseline.py --update-baselines

# ---------------------------------------------------------------------------
# Spatial data health check (weekly)
# ---------------------------------------------------------------------------

# Check spatial.db health and print report
spatial-health:
	python3 scripts/spatial_health_check.py

# Record current row counts as the new baseline
spatial-baseline:
	python3 scripts/spatial_health_check.py --record-baseline

# Check and send digest email (set SPATIAL_HEALTH_EMAIL or pass EMAIL=)
spatial-health-email:
	python3 scripts/spatial_health_check.py --email $(or $(EMAIL),$(SPATIAL_HEALTH_EMAIL))

# ---------------------------------------------------------------------------
# CLI evaluation (NES-262)
# ---------------------------------------------------------------------------

# Usage: make evaluate ADDR="123 Main St, White Plains, NY"
#        make evaluate ADDR="123 Main St" ARGS="--verbose --pretty"
evaluate:
	python3 cli.py evaluate "$(ADDR)" $(ARGS)

feedback-digest:
	python3 cli.py feedback-digest

# ---------------------------------------------------------------------------
# Daily smoke test (evaluation pipeline)
# ---------------------------------------------------------------------------

# Run smoke test, print results to terminal
smoke-test:
	python3 scripts/daily_smoke_test.py

# Run and send email on failure/warning
smoke-test-email:
	python3 scripts/daily_smoke_test.py --email $(or $(EMAIL),$(SMOKE_TEST_NOTIFY_EMAIL))

# ---------------------------------------------------------------------------
# Seed evaluation sprint (content strategy)
# ---------------------------------------------------------------------------

# Run pending evaluations against production
seed-sprint:
	python3 scripts/seed_evaluation_sprint.py

# Retry failed evaluations
seed-sprint-retry:
	python3 scripts/seed_evaluation_sprint.py --retry-failures

# Show sprint progress
seed-sprint-status:
	python3 scripts/seed_evaluation_sprint.py --status

# Export results to CSV for content planning
seed-sprint-export:
	python3 scripts/seed_evaluation_sprint.py --export-csv

# ---------------------------------------------------------------------------
# Test B validation (tester-provided addresses)
# ---------------------------------------------------------------------------

# Run Test B evaluations and send report/survey emails to testers
validation-test-b:
	python3 scripts/run_validation_test_b.py

# Run evaluations without sending emails
validation-test-b-dry:
	python3 scripts/run_validation_test_b.py --dry-run

# Show Test B progress
validation-test-b-status:
	python3 scripts/run_validation_test_b.py --status

# Send follow-up survey emails to testers who already have reports
validation-followup:
	python3 scripts/send_validation_followup.py

# Preview follow-up emails without sending
validation-followup-dry:
	python3 scripts/send_validation_followup.py --dry-run
