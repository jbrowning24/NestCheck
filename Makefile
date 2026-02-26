# ---------------------------------------------------------------------------
# NestCheck Makefile
# ---------------------------------------------------------------------------

.PHONY: help run test test-quick lint coverage clean smoke smoke-local

help: ## Show available commands
	@grep -E '^[a-zA-Z_-]+:.*##' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*## "}; {printf "  make %-14s %s\n", $$1, $$2}'

run: ## Start Flask dev server (port 5001)
	python3 app.py

test: ## Run full test suite
	pytest tests/ -v

test-quick: ## Run tests, stop on first failure
	pytest tests/ -v -x

lint: ## Run ruff linter
	ruff check .

coverage: ## Run tests with coverage report
	pytest tests/ --cov=. --cov-report=term-missing

clean: ## Remove caches and compiled files
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null; \
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null; \
	find . -name '*.pyc' -delete 2>/dev/null; \
	true

smoke: ## Post-deploy smoke test against production
	python3 smoke_test.py

smoke-local: ## Smoke test against local dev server (port 5000)
	python3 smoke_test.py http://localhost:5000
