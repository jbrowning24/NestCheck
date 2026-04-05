"""Monthly quota tracking for B2B partners."""
import logging
from datetime import datetime, timezone
from typing import Optional, Tuple

from models import _get_db

logger = logging.getLogger(__name__)


def _current_period() -> str:
    """Return the current year-month string, e.g. '2026-04'."""
    return datetime.now(timezone.utc).strftime("%Y-%m")


def increment_quota(partner_id: int, period: Optional[str] = None) -> int:
    """Increment the monthly request counter for a partner.

    Uses a SQLite upsert so the first call creates the row and
    subsequent calls atomically increment it.

    Args:
        partner_id: The partner's database id.
        period: Year-month string (e.g. "2026-04"). Defaults to current month.

    Returns:
        The new request_count after incrementing.
    """
    if period is None:
        period = _current_period()

    conn = _get_db()
    try:
        conn.execute(
            """
            INSERT INTO partner_quota_usage (partner_id, period, request_count)
            VALUES (?, ?, 1)
            ON CONFLICT(partner_id, period) DO UPDATE SET request_count = request_count + 1
            """,
            (partner_id, period),
        )
        conn.commit()
        row = conn.execute(
            "SELECT request_count FROM partner_quota_usage "
            "WHERE partner_id = ? AND period = ?",
            (partner_id, period),
        ).fetchone()
        return row["request_count"]
    finally:
        conn.close()


def check_quota(
    partner_id: int, period: Optional[str] = None
) -> Tuple[bool, int, int]:
    """Check whether a partner has remaining quota for the given period.

    Args:
        partner_id: The partner's database id.
        period: Year-month string (e.g. "2026-04"). Defaults to current month.

    Returns:
        Tuple of (allowed, used, limit) where:
        - allowed: True if used < limit.
        - used: Requests made in the period (0 if no row yet).
        - limit: The partner's monthly_quota setting.
    """
    if period is None:
        period = _current_period()

    conn = _get_db()
    try:
        usage_row = conn.execute(
            "SELECT request_count FROM partner_quota_usage "
            "WHERE partner_id = ? AND period = ?",
            (partner_id, period),
        ).fetchone()
        quota_row = conn.execute(
            "SELECT monthly_quota FROM partners WHERE id = ?",
            (partner_id,),
        ).fetchone()
    finally:
        conn.close()

    used = usage_row["request_count"] if usage_row else 0
    limit = quota_row["monthly_quota"] if quota_row else 0
    allowed = used < limit
    return allowed, used, limit
