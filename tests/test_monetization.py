import sqlite3
import uuid
from datetime import datetime, timedelta

from models import (
    init_db, _get_db,
    create_subscription, get_subscription_by_stripe_id,
    update_subscription_status, is_subscription_active,
    check_free_tier_available, record_free_tier_usage, decrement_free_tier_usage,
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


# =========================================================================
# Free tier counter model
# =========================================================================

def test_check_free_tier_available_no_record():
    assert check_free_tier_available("hash_new_user") is True

def test_free_tier_counter_increments():
    email_hash = "hash_counter_test"
    for i in range(10):
        record_free_tier_usage(email_hash, "counter@test.com")
    assert check_free_tier_available(email_hash) is False

def test_free_tier_counter_nine_is_available():
    email_hash = "hash_nine_test"
    for i in range(9):
        record_free_tier_usage(email_hash, "nine@test.com")
    assert check_free_tier_available(email_hash) is True

def test_decrement_free_tier_usage():
    email_hash = "hash_decrement_test"
    for i in range(10):
        record_free_tier_usage(email_hash, "decrement@test.com")
    assert check_free_tier_available(email_hash) is False
    decrement_free_tier_usage(email_hash)
    assert check_free_tier_available(email_hash) is True

def test_free_tier_window_reset():
    email_hash = "hash_window_reset"
    conn = _get_db()
    try:
        conn.execute(
            "INSERT INTO free_tier_usage (email_hash, email_raw, created_at, "
            "eval_count, window_start) VALUES (?, ?, datetime('now'), 10, "
            "datetime('now', '-40 days'))",
            (email_hash, "window@test.com"),
        )
        conn.commit()
    finally:
        conn.close()
    assert check_free_tier_available(email_hash) is True
    record_free_tier_usage(email_hash, "window@test.com")
    conn = _get_db()
    try:
        row = conn.execute(
            "SELECT eval_count FROM free_tier_usage WHERE email_hash = ?",
            (email_hash,),
        ).fetchone()
        assert row[0] == 1
    finally:
        conn.close()
