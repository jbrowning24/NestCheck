# NES-262: CLI Entry Point Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `cli.py` entry point so evaluations can run from the terminal without Flask, with `--verbose` stage timings and structured JSON output via `result_to_dict()`.

**Architecture:** Three changes — (1) add `on_stage_complete` callback to `evaluate_property()` for real-time timing events, (2) create `cli.py` with argparse subcommand pattern, (3) deprecation comment on old CLI. The CLI lazy-imports `result_to_dict` from `app.py` inside the handler to avoid Flask bootstrapping at import time.

**Tech Stack:** Python argparse, existing `property_evaluator.py` + `app.py` (lazy import)

---

### Task 1: Add `on_stage_complete` callback to `_timed_stage` and `evaluate_property`

**Files:**
- Modify: `property_evaluator.py:5752-5805` (`_timed_stage` + `evaluate_property` signature)

The `_timed_stage` function already tracks timing. We need to thread an `on_stage_complete` callback through so the CLI can print stage timings in real-time.

- [ ] **Step 1: Add `on_stage_complete` parameter to `_timed_stage`**

In `property_evaluator.py`, modify `_timed_stage` (line 5752) to accept and call an optional callback:

```python
def _timed_stage(stage_name, fn, *args, on_stage_complete=None, **kwargs):
    """Run *fn* with timing.  Logs duration and re-raises on failure."""
    trace = get_trace()
    if trace:
        trace.start_stage(stage_name)
    t0 = time.time()
    try:
        result = fn(*args, **kwargs)
        t1 = time.time()
        if trace:
            trace.record_stage(stage_name, t0, t1)
        else:
            logger.info("  [stage] %s OK (%.1fs)", stage_name, t1 - t0)
        if on_stage_complete is not None:
            on_stage_complete(stage_name, t1 - t0)
        return result
    except Exception as exc:
        t1 = time.time()
        if trace:
            trace.record_stage(
                stage_name, t0, t1,
                error_class=type(exc).__name__,
                error_message=str(exc)[:200],
            )
        else:
            logger.warning("  [stage] %s FAILED (%.1fs)", stage_name, t1 - t0, exc_info=True)
        if on_stage_complete is not None:
            on_stage_complete(stage_name, t1 - t0)
        raise
```

- [ ] **Step 2: Add `on_stage_complete` parameter to `evaluate_property`**

Modify the `evaluate_property` signature (line 5779) to accept and thread the callback:

```python
def evaluate_property(
    listing: PropertyListing,
    api_key: str,
    pre_geocode: Optional[Dict[str, Any]] = None,
    on_stage: Optional[Callable[[str], None]] = None,
    on_stage_complete: Optional[Callable[[str, float], None]] = None,
    place_id: Optional[str] = None,
) -> EvaluationResult:
```

Update the docstring to document the new param:

```python
        on_stage_complete: Optional callback invoked with (stage_name, elapsed_seconds)
            after each stage completes (or fails). Used by CLI for verbose timing output.
```

- [ ] **Step 3: Thread `on_stage_complete` through `_staged`**

Modify the `_staged` closure inside `evaluate_property` (line 5802):

```python
    def _staged(stage_name, fn, *args, **kwargs):
        """Notify the frontend of the current stage, then run _timed_stage."""
        _notify(stage_name)
        return _timed_stage(stage_name, fn, *args, on_stage_complete=on_stage_complete, **kwargs)
```

- [ ] **Step 4: Verify no existing callers break**

Run: `cd /Users/jeremybrowning/NestCheck && grep -rn "evaluate_property(" worker.py app.py scripts/ tests/ --include="*.py" | head -20`

All existing callers pass `on_stage` by keyword or don't pass it at all. The new `on_stage_complete` defaults to `None`, so zero impact on existing callers.

- [ ] **Step 5: Commit**

```bash
git add property_evaluator.py
git commit -m "feat(NES-262): add on_stage_complete callback to evaluate_property

Threads optional (stage_name, elapsed_seconds) callback through
_timed_stage for real-time timing events. Default None — zero
impact on existing callers (worker.py, app.py)."
```

---

### Task 2: Create `cli.py`

**Files:**
- Create: `cli.py`

- [ ] **Step 1: Create `cli.py` with evaluate subcommand**

```python
#!/usr/bin/env python3
"""NestCheck CLI — run evaluations from the terminal.

Usage:
    python cli.py evaluate "123 Main St, White Plains, NY"
    python cli.py evaluate "123 Main St" --verbose
    python cli.py evaluate "123 Main St" --pretty
    python cli.py evaluate "123 Main St" | jq '.final_score'
"""

import argparse
import json
import os
import sys
import time

from dotenv import load_dotenv

load_dotenv()


def _verbose_callback(stage_name: str, elapsed: float) -> None:
    """Print stage timing to stderr (keeps stdout clean for JSON piping)."""
    print(f"  [{elapsed:5.1f}s] {stage_name}", file=sys.stderr)


def _cmd_evaluate(args: argparse.Namespace) -> None:
    """Run a property evaluation and output results."""
    from property_evaluator import PropertyListing, evaluate_property

    api_key = args.api_key or os.environ.get("GOOGLE_MAPS_API_KEY")
    if not api_key:
        print(
            "Error: Google Maps API key required.\n"
            "Set GOOGLE_MAPS_API_KEY env var or use --api-key",
            file=sys.stderr,
        )
        sys.exit(1)

    listing = PropertyListing(
        address=args.address,
        cost=args.cost,
        sqft=args.sqft,
        bedrooms=args.bedrooms,
        has_washer_dryer_in_unit=args.washer_dryer or None,
        has_central_air=args.central_air or None,
        has_parking=args.parking or None,
        has_outdoor_space=args.outdoor_space or None,
    )

    on_stage_complete = _verbose_callback if args.verbose else None

    if args.verbose:
        print(f"Evaluating: {args.address}", file=sys.stderr)

    t0 = time.time()
    result = evaluate_property(
        listing,
        api_key,
        on_stage_complete=on_stage_complete,
    )
    elapsed = time.time() - t0

    if args.verbose:
        print(f"  [{elapsed:5.1f}s] total", file=sys.stderr)
        print(f"  Score: {result.final_score}/100", file=sys.stderr)

    if args.pretty:
        from property_evaluator import format_result

        print(format_result(result))
    else:
        # Lazy import: result_to_dict lives in app.py which triggers Flask
        # bootstrapping. Importing here (after evaluation) keeps CLI startup
        # fast and avoids Flask dep for --pretty/--help. In dev, SECRET_KEY
        # defaults to 'nestcheck-dev-key' so no env vars are required beyond
        # GOOGLE_MAPS_API_KEY. Future cleanup: extract to serialization.py.
        from app import result_to_dict

        output = result_to_dict(result)
        print(json.dumps(output, indent=2, default=str))


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="nestcheck",
        description="NestCheck — property evaluation from the terminal",
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # --- evaluate ---
    eval_parser = subparsers.add_parser(
        "evaluate",
        help="Evaluate a property address",
        description="Run a full property evaluation and output structured JSON.",
    )
    eval_parser.add_argument(
        "address",
        help="Property address to evaluate",
    )
    eval_parser.add_argument(
        "--cost",
        type=int,
        help="Monthly cost in dollars",
    )
    eval_parser.add_argument(
        "--sqft",
        type=int,
        help="Square footage",
    )
    eval_parser.add_argument(
        "--bedrooms",
        type=int,
        help="Number of bedrooms",
    )
    eval_parser.add_argument(
        "--washer-dryer",
        action="store_true",
        help="Has washer/dryer in unit",
    )
    eval_parser.add_argument(
        "--central-air",
        action="store_true",
        help="Has central air",
    )
    eval_parser.add_argument(
        "--parking",
        action="store_true",
        help="Has parking",
    )
    eval_parser.add_argument(
        "--outdoor-space",
        action="store_true",
        help="Has outdoor space (yard/balcony)",
    )
    eval_parser.add_argument(
        "--api-key",
        help="Google Maps API key (default: GOOGLE_MAPS_API_KEY env var)",
    )
    eval_parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Print stage timings to stderr",
    )
    eval_parser.add_argument(
        "--pretty",
        action="store_true",
        help="Human-readable output instead of JSON",
    )
    eval_parser.set_defaults(func=_cmd_evaluate)

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)

    args.func(args)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Verify the CLI runs with `--help`**

Run: `cd /Users/jeremybrowning/NestCheck && python cli.py --help`

Expected output includes `evaluate` subcommand.

Run: `cd /Users/jeremybrowning/NestCheck && python cli.py evaluate --help`

Expected output lists `address`, `--verbose`, `--pretty`, `--api-key`, etc.

- [ ] **Step 3: Verify JSON output with a real address**

Run: `cd /Users/jeremybrowning/NestCheck && python cli.py evaluate "1 Main St, White Plains, NY" 2>/dev/null | python -m json.tool | head -20`

Expected: valid JSON with `address`, `coordinates`, `tier1_checks`, etc.

- [ ] **Step 4: Verify `--verbose` stage timing output**

Run: `cd /Users/jeremybrowning/NestCheck && python cli.py evaluate "1 Main St, White Plains, NY" --verbose 2>&1 1>/dev/null | head -10`

Expected stderr output like:
```
Evaluating: 1 Main St, White Plains, NY
  [  1.2s] geocode
  [  3.4s] neighborhood
  ...
```

- [ ] **Step 5: Verify `--pretty` human-readable output**

Run: `cd /Users/jeremybrowning/NestCheck && python cli.py evaluate "1 Main St, White Plains, NY" --pretty 2>/dev/null | head -15`

Expected: formatted text report (from `format_result()`).

- [ ] **Step 6: Commit**

```bash
git add cli.py
git commit -m "feat(NES-262): add CLI entry point for terminal evaluations

New cli.py with argparse subcommand pattern:
  python cli.py evaluate '123 Main St, White Plains, NY'
  python cli.py evaluate '...' --verbose  # stage timings to stderr
  python cli.py evaluate '...' --pretty   # human-readable output
  python cli.py evaluate '...' | jq '.final_score'

JSON output (default) uses result_to_dict() from app.py via lazy
import — avoids Flask bootstrapping at CLI startup."
```

---

### Task 3: Add deprecation comment to existing CLI + Makefile target

**Files:**
- Modify: `property_evaluator.py:6333-6337` (deprecation comment)
- Modify: `Makefile` (new target)

- [ ] **Step 1: Add deprecation comment to `main()` in property_evaluator.py**

Add a comment above the `main()` function (line 6337):

```python
# =============================================================================
# CLI (DEPRECATED — use `python cli.py evaluate` instead)
# =============================================================================

def main():
    # Deprecated: prefer `python cli.py evaluate <address>` which uses
    # result_to_dict() for complete JSON serialization. This CLI uses a
    # hand-rolled subset that drifts from the canonical output.
    parser = argparse.ArgumentParser(
```

- [ ] **Step 2: Add Makefile target**

Add to `Makefile`:

```makefile
# CLI evaluation (NES-262)
evaluate:
	python cli.py evaluate "$(ADDR)" $(ARGS)
```

- [ ] **Step 3: Commit**

```bash
git add property_evaluator.py Makefile
git commit -m "chore(NES-262): deprecate old CLI, add Makefile evaluate target

Points property_evaluator.py main() to cli.py evaluate as the
canonical CLI. Adds make evaluate ADDR='...' target."
```
