---
name: nestcheck-backlog
description: Pick off one small backlog item from NestCheck's Linear board or codebase. Focus on code quality improvements, small bug fixes, documentation gaps, or minor template fixes. Never touch the evaluation pipeline, API clients, or Stripe integration. Always run /review before finishing.
---

# NestCheck Backlog Pickup

## Constraints
- Only modify files you fully understand after reading them
- Never add new Google Maps API calls or change existing API call patterns
- Never modify property_evaluator.py core logic, green_space.py, or urban_access.py
- Never touch payment/Stripe code
- Changes must be < 50 lines diff
- Run /review when done

## Good targets
- Template HTML/CSS fixes in index.html or snapshot.html
- Dead code removal
- Docstring improvements
- Minor bug fixes in presentation logic (present_checks())
- Builder dashboard improvements
- Error message improvements
- Code comments in complex sections

## Bad targets (skip these)
- Anything requiring new API calls
- Scoring logic changes
- Database schema changes
- New features or endpoints
- Anything in the evaluation pipeline
