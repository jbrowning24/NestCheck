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
