import sqlite3
from models import init_db, _get_db

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
