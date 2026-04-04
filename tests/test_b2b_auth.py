"""Tests for B2B partner authentication and key management."""
import pytest
from models import _get_db, init_db


def test_partners_table_exists():
    """init_db() creates the partners table."""
    conn = _get_db()
    tables = {
        row["name"]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    conn.close()
    assert "partners" in tables


def test_partner_api_keys_table_exists():
    conn = _get_db()
    tables = {
        row["name"]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    conn.close()
    assert "partner_api_keys" in tables


def test_partner_quota_usage_table_exists():
    conn = _get_db()
    tables = {
        row["name"]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    conn.close()
    assert "partner_quota_usage" in tables


def test_partner_usage_log_table_exists():
    conn = _get_db()
    tables = {
        row["name"]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    conn.close()
    assert "partner_usage_log" in tables


def test_evaluation_jobs_has_partner_id_column():
    conn = _get_db()
    cols = {
        row["name"]
        for row in conn.execute("PRAGMA table_info(evaluation_jobs)").fetchall()
    }
    conn.close()
    assert "partner_id" in cols
