#!/usr/bin/env python3
"""
Ground Truth Audit — Run 4 real evaluations and produce a structured audit report.

READ + RUN task. Uses direct evaluate_property() with trace for full API call counts.
Output: ground_truth_audit_YYYYMMDD.md in project root.
"""

import os
import sys
import json
import time
from datetime import datetime

# Ensure project root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

ADDRESSES = [
    "620 W 143rd Street, New York, NY 10031",
    "152 W 128TH ST, NEW YORK, NY 10027",
    "315 W 91st Street, New York, NY 10024",
    "35565 Vicksburg, Farmington Hills, MI 48331",
]


def run_audit():
    from nc_trace import TraceContext, set_trace, clear_trace, get_trace
    from property_evaluator import PropertyListing, evaluate_property

    api_key = os.environ.get("GOOGLE_MAPS_API_KEY")
    if not api_key:
        print("Error: GOOGLE_MAPS_API_KEY not set. Set in .env or environment.")
        sys.exit(1)

    reports = []
    for i, addr in enumerate(ADDRESSES):
        print(f"\n[{i+1}/4] Evaluating: {addr}", flush=True)
        trace_ctx = TraceContext(trace_id=f"audit-{i+1}")
        set_trace(trace_ctx)
        t0 = time.time()
        err_msg = None
        raw_result = None
        result_dict = None
        try:
            listing = PropertyListing(address=addr)
            raw_result = evaluate_property(listing, api_key)
            # Build template dict (matches worker path)
            from app import result_to_dict
            result_dict = result_to_dict(raw_result)
        except Exception as e:
            err_msg = str(e)
            import traceback
            err_msg += "\n" + traceback.format_exc()
        finally:
            elapsed = time.time() - t0
            trace_summary = trace_ctx.full_trace_dict() if trace_ctx else {}
            trace_ctx.log_summary()
            clear_trace()

        report = {
            "address": addr,
            "geocode": {"lat": raw_result.lat, "lng": raw_result.lng} if raw_result else None,
            "elapsed_sec": round(elapsed, 2),
            "error": err_msg,
            "result_dict": result_dict,
            "trace": trace_summary,
            "raw_tier1": [{"name": c.name, "result": c.result.value, "details": c.details, "value": c.value}
                          for c in raw_result.tier1_checks] if raw_result else [],
        }
        reports.append(report)
        print(f"  -> {report['elapsed_sec']}s, tier1_pass={raw_result.passed_tier1 if raw_result else 'N/A'}", flush=True)

    return reports


def format_report(reports):
    lines = []
    lines.append("# NestCheck Ground Truth Audit")
    lines.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append("")
    lines.append("## Files Read (Pipeline Understanding)")
    lines.append("- property_evaluator.py — evaluate_property(), present_checks(), Tier 1 checks")
    lines.append("- green_space.py — Green Escape scoring engine")
    lines.append("- urban_access.py — Urban Access / transit scoring")
    lines.append("- app.py — /evaluate flow, result_to_dict, debug_eval")
    lines.append("- models.py — snapshot structure")
    lines.append("")
    lines.append("## Method Used")
    lines.append("Direct function call: evaluate_property() + result_to_dict() with TraceContext")
    lines.append("")

    completed = sum(1 for r in reports if not r.get("error"))
    failed = [r["address"] for r in reports if r.get("error")]

    lines.append("## Evaluations Summary")
    lines.append(f"- Completed: {completed}/4")
    lines.append(f"- Failed: {failed if failed else 'None'}")
    lines.append("")

    for r in reports:
        lines.append("---")
        lines.append(f"## Address: {r['address']}")
        lines.append("")
        if r.get("geocode"):
            lines.append(f"**Geocode result:** [{r['geocode']['lat']}, {r['geocode']['lng']}]")
        lines.append(f"**Evaluation time:** {r['elapsed_sec']} seconds")
        if r.get("error"):
            lines.append(f"**Errors/exceptions:** {r['error']}")
        else:
            lines.append("**Any errors or exceptions:** None")
        lines.append("")

        rd = r.get("result_dict") or {}
        trace = r.get("trace") or {}

        # Tier 1
        lines.append("### Tier 1 Safety Checks")
        tier1 = rd.get("tier1_checks", r.get("raw_tier1", []))
        for c in tier1:
            name = c.get("name", "?")
            res = c.get("result", "?")
            details = c.get("details", "")
            value = c.get("value")
            lines.append(f"- **{name}:** {res}")
            if details:
                lines.append(f"  - Details: {details}")
            if value is not None:
                lines.append(f"  - Raw value: {value}")
        lines.append("")

        # Tier 2
        lines.append("### Tier 2 Scores")
        for s in rd.get("tier2_scores", []):
            n = s.get("name", "?")
            pts = s.get("points", s.get("score", "?"))
            mx = s.get("max", s.get("max_points", "?"))
            det = s.get("details", "")
            lines.append(f"- **{n}:** {pts}/{mx} — {det}")
        if not rd.get("tier2_scores"):
            lines.append("- (No tier 2 — tier 1 failed or skipped)")
        lines.append("")

        # Tier 3
        lines.append("### Tier 3 Bonuses")
        for b in rd.get("tier3_bonuses", []):
            lines.append(f"- **{b.get('name', '?')}:** +{b.get('points', 0)} — {b.get('details', '')}")
        if not rd.get("tier3_bonuses"):
            lines.append("- (None)")
        lines.append("")

        # Insights
        lines.append("### Insight Layer")
        insights = rd.get("insights") or {}
        for k, v in insights.items():
            if v:
                lines.append(f"- **{k}:** {v}")
        if not insights or not any(insights.values()):
            lines.append("- (Insights not populated in result_dict)")
        lines.append("")

        # API summary
        lines.append("### API Call Summary")
        api_calls = trace.get("api_calls", [])
        if isinstance(api_calls, list) and api_calls:
            by_svc = {}
            for ac in api_calls:
                svc = ac.get("service", "unknown")
                by_svc[svc] = by_svc.get(svc, 0) + 1
            for svc, cnt in sorted(by_svc.items()):
                lines.append(f"- {svc}: {cnt}")
        else:
            lines.append("- Trace not available in expected format")
        total = trace.get("total_api_calls", len(api_calls) if isinstance(api_calls, list) else 0)
        lines.append(f"- Total API calls: {total}")
        lines.append("")
        lines.append("")

    # Summary table
    lines.append("---")
    lines.append("## Summary Table")
    lines.append("")
    lines.append("| Check / Dimension | 620 W 143rd | 152 W 128th | 315 W 91st | 35565 Vicksburg |")
    lines.append("|-------------------|-------------|-------------|------------|------------------|")

    # Collect all check names
    all_checks = set()
    for r in reports:
        for c in r.get("result_dict", {}).get("tier1_checks", []) or r.get("raw_tier1", []):
            all_checks.add(c.get("name", ""))
    all_checks = sorted(all_checks)

    for check in all_checks:
        row = [check]
        for r in reports:
            tier1 = r.get("result_dict", {}).get("tier1_checks", []) or r.get("raw_tier1", [])
            found = next((c for c in tier1 if c.get("name") == check), None)
            row.append(found.get("result", "—") if found else "—")
        lines.append("| " + " | ".join(row) + " |")

    # Tier 2 dimensions
    all_dims = set()
    for r in reports:
        for s in r.get("result_dict", {}).get("tier2_scores", []):
            all_dims.add(s.get("name", ""))
    all_dims = sorted(all_dims)
    for dim in all_dims:
        row = [dim]
        for r in reports:
            scores = r.get("result_dict", {}).get("tier2_scores", [])
            found = next((s for s in scores if s.get("name") == dim), None)
            val = f"{found.get('points', '—')}/{found.get('max', '—')}" if found else "—"
            row.append(val)
        lines.append("| " + " | ".join(row) + " |")

    # Totals
    row = ["Total API Calls"]
    for r in reports:
        row.append(str(r.get("trace", {}).get("total_api_calls", "—")))
    lines.append("| " + " | ".join(row) + " |")

    row = ["Eval Time (sec)"]
    for r in reports:
        row.append(str(r.get("elapsed_sec", "—")))
    lines.append("| " + " | ".join(row) + " |")
    lines.append("")

    # Suspicious flags
    lines.append("---")
    lines.append("## Suspicious Items / Flags")
    lines.append("")
    lines.append("(Manual review recommended for:)")
    lines.append("- Gas station flags in residential areas with no visible gas station")
    lines.append("- Missing highway/high-traffic flags near known major roads")
    lines.append("- Manhattan addresses scoring low on transit")
    lines.append("- Suburban addresses scoring high on walkability")
    lines.append("- Dimensions returning None or empty data")
    lines.append("- Redundant or excessive API calls")
    lines.append("")

    return "\n".join(lines)


def main():
    reports = run_audit()
    report_md = format_report(reports)
    date_str = datetime.now().strftime("%Y%m%d")
    out_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), f"ground_truth_audit_{date_str}.md")
    with open(out_path, "w") as f:
        f.write(report_md)
    print(f"\nOutput saved to: {out_path}")
    print(f"Evaluations completed: {sum(1 for r in reports if not r.get('error'))}/4")
    if any(r.get("error") for r in reports):
        print("Failed:", [r["address"] for r in reports if r.get("error")])


if __name__ == "__main__":
    main()
