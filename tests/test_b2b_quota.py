"""Tests for B2B quota enforcement."""
import pytest
from models import _get_db, init_db

# Import helpers from auth tests
from tests.test_b2b_auth import _create_partner, _create_api_key


class TestQuotaIncrement:
    def test_first_request_creates_period_row(self):
        from b2b.quota import increment_quota
        pid = _create_partner(quota=100)
        increment_quota(pid, "2026-04")
        conn = _get_db()
        row = conn.execute(
            "SELECT request_count FROM partner_quota_usage "
            "WHERE partner_id = ? AND period = ?",
            (pid, "2026-04"),
        ).fetchone()
        conn.close()
        assert row["request_count"] == 1

    def test_subsequent_requests_increment(self):
        from b2b.quota import increment_quota
        pid = _create_partner(quota=100)
        increment_quota(pid, "2026-04")
        increment_quota(pid, "2026-04")
        increment_quota(pid, "2026-04")
        conn = _get_db()
        row = conn.execute(
            "SELECT request_count FROM partner_quota_usage "
            "WHERE partner_id = ? AND period = ?",
            (pid, "2026-04"),
        ).fetchone()
        conn.close()
        assert row["request_count"] == 3


class TestQuotaCheck:
    def test_under_quota_returns_true(self):
        from b2b.quota import check_quota
        pid = _create_partner(quota=100)
        allowed, used, limit = check_quota(pid)
        assert allowed is True
        assert used == 0
        assert limit == 100

    def test_at_quota_returns_false(self):
        from b2b.quota import increment_quota, check_quota
        pid = _create_partner(quota=2)
        increment_quota(pid, "2026-04")
        increment_quota(pid, "2026-04")
        allowed, used, limit = check_quota(pid, period="2026-04")
        assert allowed is False
        assert used == 2

    def test_different_periods_are_independent(self):
        from b2b.quota import increment_quota, check_quota
        pid = _create_partner(quota=1)
        increment_quota(pid, "2026-03")
        allowed, used, limit = check_quota(pid, period="2026-04")
        assert allowed is True
        assert used == 0
