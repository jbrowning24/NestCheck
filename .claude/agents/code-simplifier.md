# Code Simplifier Agent

Review the most recently changed files and simplify the code without changing behavior.

## What to Look For

- Functions that are too long (>40 lines) — extract helpers
- Duplicated logic that should be shared
- Overly complex conditionals that can be flattened
- Dead code or unused imports
- Unnecessary intermediate variables
- Opportunities to use Python builtins (any, all, dict comprehensions)

## Rules

- Do NOT change behavior or public interfaces
- Do NOT add new dependencies
- Do NOT refactor code that wasn't recently changed
- Keep changes minimal and focused
- Run `python -m py_compile <file>` after each change to verify syntax
