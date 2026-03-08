# Verify App Agent

Run the full verification suite for NestCheck to confirm the app works end to end.

## Steps

1. **Syntax check**: Run `python -m py_compile app.py` and `python -m py_compile property_evaluator.py` to catch import/syntax errors.
2. **Run tests**: Execute `python -m pytest` if tests exist, or `python smoke_test.py http://localhost:5000` for smoke tests.
3. **Template rendering**: Glob `templates/*.html` and check that all Jinja templates parse without errors by running `python -c "from app import app; app.jinja_env.get_template('filename.html')"` for each discovered template.
4. **Static asset check**: Verify that CSS/JS files referenced in templates exist in `static/`.

## Output

Report pass/fail for each step. If anything fails, provide the exact error and suggest a fix.
