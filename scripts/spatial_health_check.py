#!/usr/bin/env python3
"""
Weekly spatial data health check.

Queries spatial.db to verify that all bulk datasets are present, have expected
row counts (within tolerance of baseline), and haven't gone stale past their
refresh thresholds. Sends a digest email via Resend.

Usage:
    # Check and print report to stdout (dry run):
    python scripts/spatial_health_check.py

    # Check and send digest email:
    python scripts/spatial_health_check.py --email ops@nestcheck.com

    # Record current row counts as the new baseline:
    python scripts/spatial_health_check.py --record-baseline

    # Custom tolerance (default 5%):
    python scripts/spatial_health_check.py --tolerance 0.10
"""

import argparse
import html
import json
import logging
import os
import sqlite3
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

BASELINE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data",
    "spatial_baseline.json",
)

# All tables we expect in spatial.db, grouped by naming convention.
# facilities_* tables use the _VALID_FACILITY_TYPES whitelist.
# Other tables (state_education_performance) are checked directly.
EXPECTED_FACILITY_TABLES = [
    "facilities_sems",
    "facilities_fema_nfhl",
    "facilities_hpms",
    "facilities_ejscreen",
    "facilities_tri",
    "facilities_ust",
    "facilities_hifld",
    "facilities_fra",
    "facilities_school_districts",
    "facilities_nces_schools",
]

EXPECTED_OTHER_TABLES = [
    "state_education_performance",
]

ALL_EXPECTED_TABLES = EXPECTED_FACILITY_TABLES + EXPECTED_OTHER_TABLES

# Maximum age in days before a dataset is considered stale.
# Keyed by facility_type (dataset_registry PK) or table name for non-facility tables.
STALENESS_THRESHOLDS_DAYS: Dict[str, int] = {
    "sems": 180,  # EPA Superfund — slow-changing
    "fema_nfhl": 365,  # FEMA flood zones — annual
    "hpms": 180,  # FHWA traffic counts — semi-annual
    "ejscreen": 365,  # EPA EJScreen — annual release
    "tri": 365,  # EPA TRI — annual release
    "ust": 180,  # EPA UST — moderate churn
    "hifld": 365,  # Power lines — slow-changing
    "fra": 365,  # Rail network — slow-changing
    "school_districts": 365,  # TIGER boundaries — annual
    "nces_schools": 365,  # NCES schools — annual
}

DEFAULT_STALENESS_DAYS = 180

# Row count tolerance — flag if current count deviates by more than this fraction.
DEFAULT_TOLERANCE = 0.05

FROM_ADDRESS = "NestCheck <reports@nestcheck.com>"


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class TableStatus:
    table_name: str
    exists: bool
    row_count: int
    baseline_count: Optional[int]
    ingested_at: Optional[str]  # ISO timestamp from dataset_registry
    staleness_threshold_days: Optional[int]
    age_days: Optional[float]
    issues: List[str]

    @property
    def healthy(self) -> bool:
        return len(self.issues) == 0


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------


def _spatial_db_path() -> str:
    """Resolve spatial database path — mirrors spatial_data.py."""
    if os.environ.get("RAILWAY_VOLUME_MOUNT_PATH"):
        return os.path.join(os.environ["RAILWAY_VOLUME_MOUNT_PATH"], "spatial.db")
    return os.environ.get("NESTCHECK_SPATIAL_DB_PATH", "data/spatial.db")


def _connect_plain(db_path: str) -> sqlite3.Connection:
    """Plain SQLite connection (no SpatiaLite needed for row counts)."""
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name=?",
        (table_name,),
    ).fetchone()
    return row[0] > 0


def _row_count(conn: sqlite3.Connection, table_name: str) -> int:
    # table_name is from our hardcoded list, not user input — safe to interpolate
    row = conn.execute(f"SELECT COUNT(*) FROM [{table_name}]").fetchone()
    return row[0]


def _get_registry_entry(
    conn: sqlite3.Connection, facility_type: str
) -> Optional[dict]:
    """Read dataset_registry row for a facility type."""
    if not _table_exists(conn, "dataset_registry"):
        return None
    row = conn.execute(
        "SELECT facility_type, source_url, ingested_at, record_count, notes "
        "FROM dataset_registry WHERE facility_type = ?",
        (facility_type,),
    ).fetchone()
    if not row:
        return None
    return {
        "facility_type": row[0],
        "source_url": row[1],
        "ingested_at": row[2],
        "record_count": row[3],
        "notes": row[4],
    }


# ---------------------------------------------------------------------------
# Baseline management
# ---------------------------------------------------------------------------


def load_baseline() -> Dict[str, int]:
    """Load baseline row counts from JSON file."""
    if not os.path.exists(BASELINE_PATH):
        return {}
    with open(BASELINE_PATH) as f:
        data = json.load(f)
    return data.get("row_counts", {})


def record_baseline(db_path: str) -> Dict[str, int]:
    """Snapshot current row counts and save as the new baseline."""
    conn = _connect_plain(db_path)
    try:
        counts = {}
        for table in ALL_EXPECTED_TABLES:
            if _table_exists(conn, table):
                counts[table] = _row_count(conn, table)
    finally:
        conn.close()

    os.makedirs(os.path.dirname(BASELINE_PATH), exist_ok=True)
    payload = {
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "row_counts": counts,
    }
    with open(BASELINE_PATH, "w") as f:
        json.dump(payload, f, indent=2)
    return counts


# ---------------------------------------------------------------------------
# Health check logic
# ---------------------------------------------------------------------------


def _facility_type_for_table(table_name: str) -> Optional[str]:
    """Extract the facility_type key from a table name for registry lookup."""
    if table_name.startswith("facilities_"):
        return table_name[len("facilities_"):]
    return None


def check_health(db_path: str, tolerance: float = DEFAULT_TOLERANCE) -> List[TableStatus]:
    """Run all health checks and return a status for each expected table."""
    baseline = load_baseline()
    results: List[TableStatus] = []

    if not os.path.exists(db_path):
        for table in ALL_EXPECTED_TABLES:
            results.append(
                TableStatus(
                    table_name=table,
                    exists=False,
                    row_count=0,
                    baseline_count=baseline.get(table),
                    ingested_at=None,
                    staleness_threshold_days=None,
                    age_days=None,
                    issues=["spatial.db not found"],
                )
            )
        return results

    conn = _connect_plain(db_path)
    now = datetime.now(timezone.utc)

    try:
        for table in ALL_EXPECTED_TABLES:
            issues: List[str] = []
            exists = _table_exists(conn, table)
            count = 0
            ingested_at = None
            age_days = None
            baseline_count = baseline.get(table)

            # Staleness threshold — look up by facility_type
            ft = _facility_type_for_table(table)
            staleness_days = STALENESS_THRESHOLDS_DAYS.get(
                ft or table, DEFAULT_STALENESS_DAYS
            )

            if not exists:
                issues.append("Table missing")
            else:
                count = _row_count(conn, table)

                # Zero rows — catastrophic
                if count == 0:
                    issues.append("Zero rows (data dropped or never ingested)")

                # Baseline deviation
                if baseline_count is not None and baseline_count > 0 and count > 0:
                    deviation = abs(count - baseline_count) / baseline_count
                    if deviation > tolerance:
                        direction = "increase" if count > baseline_count else "decrease"
                        issues.append(
                            f"Row count {direction}: {baseline_count:,} -> {count:,} "
                            f"({deviation:.0%} deviation, threshold {tolerance:.0%})"
                        )

                # Staleness — check dataset_registry
                if ft:
                    entry = _get_registry_entry(conn, ft)
                    if entry and entry.get("ingested_at"):
                        ingested_at = entry["ingested_at"]
                        try:
                            ts = datetime.fromisoformat(
                                ingested_at.replace("Z", "+00:00")
                            )
                            if ts.tzinfo is None:
                                ts = ts.replace(tzinfo=timezone.utc)
                            age_days = (now - ts).total_seconds() / 86400
                            if age_days > staleness_days:
                                issues.append(
                                    f"Stale: {age_days:.0f} days old "
                                    f"(threshold {staleness_days} days)"
                                )
                        except (ValueError, TypeError):
                            issues.append(
                                f"Unparseable ingested_at: {ingested_at!r}"
                            )
                    elif entry:
                        issues.append("No ingested_at timestamp in registry")
                    else:
                        issues.append("No dataset_registry entry")

            results.append(
                TableStatus(
                    table_name=table,
                    exists=exists,
                    row_count=count,
                    baseline_count=baseline_count,
                    ingested_at=ingested_at,
                    staleness_threshold_days=staleness_days,
                    age_days=age_days,
                    issues=issues,
                )
            )
    finally:
        conn.close()

    return results


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def format_text_report(statuses: List[TableStatus]) -> str:
    """Plain-text digest suitable for stdout or log."""
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    healthy = [s for s in statuses if s.healthy]
    unhealthy = [s for s in statuses if not s.healthy]

    lines = [
        f"NestCheck Spatial Data Health Check — {now_str}",
        "=" * 56,
        "",
    ]

    if not unhealthy:
        lines.append("All datasets healthy.")
        lines.append("")

    if unhealthy:
        lines.append(f"NEEDS ATTENTION ({len(unhealthy)}):")
        lines.append("-" * 40)
        for s in unhealthy:
            lines.append(f"  {s.table_name}")
            lines.append(f"    Rows: {s.row_count:,}" + (
                f"  (baseline: {s.baseline_count:,})" if s.baseline_count else ""
            ))
            if s.age_days is not None:
                lines.append(f"    Age: {s.age_days:.0f} days")
            for issue in s.issues:
                lines.append(f"    ! {issue}")
            lines.append("")

    if healthy:
        lines.append(f"HEALTHY ({len(healthy)}):")
        lines.append("-" * 40)
        for s in healthy:
            age_str = f", {s.age_days:.0f}d old" if s.age_days is not None else ""
            lines.append(f"  {s.table_name}: {s.row_count:,} rows{age_str}")
        lines.append("")

    return "\n".join(lines)


def format_html_report(statuses: List[TableStatus]) -> str:
    """HTML digest email body."""
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    healthy = [s for s in statuses if s.healthy]
    unhealthy = [s for s in statuses if not s.healthy]

    if unhealthy:
        status_color = "#dc2626"
        status_text = f"{len(unhealthy)} dataset{'s' if len(unhealthy) != 1 else ''} need attention"
    else:
        status_color = "#16a34a"
        status_text = "All datasets healthy"

    rows_html = ""
    for s in sorted(statuses, key=lambda x: (x.healthy, x.table_name)):
        dot = "&#9679;"
        color = "#16a34a" if s.healthy else "#dc2626"
        name = html.escape(s.table_name)
        detail_parts = [f"{s.row_count:,} rows"]
        if s.baseline_count is not None:
            detail_parts.append(f"baseline {s.baseline_count:,}")
        if s.age_days is not None:
            detail_parts.append(f"{s.age_days:.0f}d old")
        detail = html.escape(" | ".join(detail_parts))

        issue_html = ""
        if s.issues:
            escaped = [html.escape(i) for i in s.issues]
            issue_html = (
                '<div style="color: #dc2626; font-size: 0.8rem; margin-top: 2px;">'
                + "<br>".join(escaped)
                + "</div>"
            )

        rows_html += f"""
        <tr>
          <td style="padding: 8px 12px; border-bottom: 1px solid #e5e7eb;">
            <span style="color: {color};">{dot}</span>&nbsp;
            <strong>{name}</strong>
            <div style="font-size: 0.85rem; color: #6b7280;">{detail}</div>
            {issue_html}
          </td>
        </tr>"""

    return f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family: system-ui, sans-serif; line-height: 1.5; color: #1f2937;">
  <div style="max-width: 560px; margin: 0 auto; padding: 1.5rem;">
    <p style="font-size: 1.25rem; font-weight: 600; color: #0f3460;">NestCheck</p>
    <p style="font-size: 0.85rem; color: #6b7280;">{html.escape(now_str)}</p>

    <div style="margin: 1rem 0; padding: 12px 16px; border-radius: 8px; background: {status_color}10; border-left: 4px solid {status_color};">
      <span style="font-weight: 600; color: {status_color};">{html.escape(status_text)}</span>
    </div>

    <table style="width: 100%; border-collapse: collapse; font-size: 0.9rem;">
      {rows_html}
    </table>

    <p style="font-size: 0.8rem; color: #9ca3af; margin-top: 1.5rem;">
      Spatial data health check &mdash; {len(healthy)} healthy, {len(unhealthy)} issues
    </p>
  </div>
</body>
</html>"""


def send_digest_email(to_email: str, statuses: List[TableStatus]) -> bool:
    """Send HTML digest via Resend. Returns True on success. Never raises."""
    api_key = os.environ.get("RESEND_API_KEY")
    if not api_key:
        logger.warning("RESEND_API_KEY not set; cannot send digest email")
        return False

    unhealthy = [s for s in statuses if not s.healthy]
    if unhealthy:
        subject = f"NestCheck: {len(unhealthy)} spatial dataset{'s' if len(unhealthy) != 1 else ''} need attention"
    else:
        subject = "NestCheck: All spatial datasets healthy"

    try:
        import resend

        resend.api_key = api_key
        params = {
            "from": FROM_ADDRESS,
            "to": [to_email],
            "subject": subject,
            "html": format_html_report(statuses),
        }
        resend.Emails.send(params)
        logger.info("Digest email sent to %s***", to_email[:3])
        return True
    except Exception as e:
        logger.warning("Failed to send digest email: %s", e, exc_info=True)
        return False


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(
        description="Spatial data health check for NestCheck"
    )
    parser.add_argument(
        "--email",
        help="Send digest email to this address",
    )
    parser.add_argument(
        "--record-baseline",
        action="store_true",
        help="Record current row counts as the new baseline and exit",
    )
    parser.add_argument(
        "--tolerance",
        type=float,
        default=DEFAULT_TOLERANCE,
        help=f"Row count deviation tolerance as fraction (default {DEFAULT_TOLERANCE})",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output results as JSON instead of text",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    db_path = _spatial_db_path()

    if args.record_baseline:
        counts = record_baseline(db_path)
        print(f"Baseline recorded to {BASELINE_PATH}")
        for table, count in sorted(counts.items()):
            print(f"  {table}: {count:,}")
        return

    statuses = check_health(db_path, tolerance=args.tolerance)
    unhealthy = [s for s in statuses if not s.healthy]

    if args.json:
        output = {
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "db_path": db_path,
            "healthy": len(unhealthy) == 0,
            "tables": [
                {
                    "table_name": s.table_name,
                    "exists": s.exists,
                    "row_count": s.row_count,
                    "baseline_count": s.baseline_count,
                    "ingested_at": s.ingested_at,
                    "age_days": round(s.age_days, 1) if s.age_days is not None else None,
                    "staleness_threshold_days": s.staleness_threshold_days,
                    "healthy": s.healthy,
                    "issues": s.issues,
                }
                for s in statuses
            ],
        }
        print(json.dumps(output, indent=2))
    else:
        print(format_text_report(statuses))

    if args.email:
        sent = send_digest_email(args.email, statuses)
        if sent:
            print(f"Digest email sent to {args.email}")
        else:
            print("Failed to send digest email (check logs)")

    # Exit 1 if any datasets unhealthy (useful for CI/cron alerting)
    if unhealthy:
        sys.exit(1)


if __name__ == "__main__":
    main()
