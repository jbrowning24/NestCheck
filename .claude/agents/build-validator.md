# Build Validator Agent

Validate that the NestCheck application can start and serve requests without errors.

## Steps

1. **Import check**: `python -c "import app"` — catches missing dependencies, circular imports, syntax errors.
2. **Model check**: `python -c "import models; print('models OK')"` — validates DB schema code loads.
3. **Worker check**: `python -c "import worker; print('worker OK')"` — validates background worker loads.
4. **Dependency audit**: Compare `requirements.txt` imports against actual imports in `*.py` files. Flag any missing packages.
5. **Smoke test markers**: Verify that IDs in `smoke_test.py` markers (`LANDING_REQUIRED_MARKERS`, `SNAPSHOT_REQUIRED_MARKERS`) match the actual template HTML.

## Output

Report pass/fail for each step with exact error messages if anything fails.
