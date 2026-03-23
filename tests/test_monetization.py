import sqlite3
import uuid
from datetime import datetime, timedelta

from models import (
    init_db, _get_db,
    create_subscription, get_subscription_by_stripe_id,
    update_subscription_status, is_subscription_active,
)

def test_subscriptions_table_exists():
    """Subscriptions table should be created by init_db()."""
    conn = _get_db()
    cursor = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='subscriptions'"
    )
    assert cursor.fetchone() is not None
    conn.close()

def test_free_tier_usage_has_counter_columns():
    """free_tier_usage should have eval_count and window_start columns."""
    conn = _get_db()
    cursor = conn.execute("PRAGMA table_info(free_tier_usage)")
    columns = {row[1] for row in cursor.fetchall()}
    conn.close()
    assert "eval_count" in columns
    assert "window_start" in columns


def test_create_and_retrieve_subscription():
    sub_id = uuid.uuid4().hex
    create_subscription(
        subscription_id=sub_id,
        user_email="test@example.com",
        stripe_subscription_id="sub_test123",
        stripe_customer_id="cus_test123",
        period_start="2026-03-01T00:00:00",
        period_end="2026-04-01T00:00:00",
    )
    sub = get_subscription_by_stripe_id("sub_test123")
    assert sub is not None
    assert sub["user_email"] == "test@example.com"
    assert sub["status"] == "active"


def test_is_subscription_active_true():
    sub_id = uuid.uuid4().hex
    future = (datetime.utcnow() + timedelta(days=30)).isoformat()
    create_subscription(
        subscription_id=sub_id,
        user_email="active@example.com",
        stripe_subscription_id="sub_active",
        stripe_customer_id="cus_active",
        period_start="2026-03-01T00:00:00",
        period_end=future,
    )
    assert is_subscription_active("active@example.com") is True


def test_is_subscription_active_expired():
    sub_id = uuid.uuid4().hex
    create_subscription(
        subscription_id=sub_id,
        user_email="expired@example.com",
        stripe_subscription_id="sub_expired",
        stripe_customer_id="cus_expired",
        period_start="2025-01-01T00:00:00",
        period_end="2025-02-01T00:00:00",
    )
    assert is_subscription_active("expired@example.com") is False


def test_update_subscription_status():
    sub_id = uuid.uuid4().hex
    future = (datetime.utcnow() + timedelta(days=30)).isoformat()
    create_subscription(
        subscription_id=sub_id,
        user_email="cancel@example.com",
        stripe_subscription_id="sub_cancel",
        stripe_customer_id="cus_cancel",
        period_start="2026-03-01T00:00:00",
        period_end=future,
    )
    update_subscription_status("sub_cancel", "canceled")
    sub = get_subscription_by_stripe_id("sub_cancel")
    assert sub["status"] == "canceled"
    # canceled still counts as active until period_end
    assert is_subscription_active("cancel@example.com") is True
