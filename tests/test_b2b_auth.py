"""Tests for B2B partner authentication and key management."""
import hashlib
import secrets
from datetime import datetime, timezone

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


def _create_partner(name="Test Corp", email="test@corp.com", quota=500):
    """Helper to insert a partner and return its id."""
    conn = _get_db()
    cursor = conn.execute(
        "INSERT INTO partners (name, contact_email, monthly_quota) VALUES (?, ?, ?)",
        (name, email, quota),
    )
    partner_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return partner_id


def _create_api_key(partner_id, environment="live"):
    """Helper to insert an API key and return (full_key, key_id)."""
    prefix = "nc_test_" if environment == "test" else "nc_live_"
    raw = prefix + secrets.token_hex(16)
    key_hash = hashlib.sha256(raw.encode()).hexdigest()
    key_prefix = raw[:16]
    conn = _get_db()
    cursor = conn.execute(
        "INSERT INTO partner_api_keys (partner_id, key_hash, key_prefix, environment) "
        "VALUES (?, ?, ?, ?)",
        (partner_id, key_hash, key_prefix, environment),
    )
    key_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return raw, key_id


class TestRequireApiKey:
    def test_missing_auth_header_returns_401(self, client):
        resp = client.post("/api/v1/b2b/evaluate", json={"address": "123 Main St"})
        assert resp.status_code == 401
        data = resp.get_json()
        assert data["error"]["code"] == "unauthorized"

    def test_invalid_key_returns_401(self, client):
        resp = client.post(
            "/api/v1/b2b/evaluate",
            json={"address": "123 Main St"},
            headers={"Authorization": "Bearer nc_live_invalidkey1234567890abcdef"},
        )
        assert resp.status_code == 401

    def test_valid_key_does_not_return_401(self, client):
        pid = _create_partner()
        key, _ = _create_api_key(pid)
        resp = client.post(
            "/api/v1/b2b/evaluate",
            json={"address": "123 Main St"},
            headers={"Authorization": "Bearer " + key},
        )
        assert resp.status_code != 401

    def test_revoked_key_returns_401(self, client):
        pid = _create_partner()
        key, key_id = _create_api_key(pid)
        conn = _get_db()
        conn.execute(
            "UPDATE partner_api_keys SET revoked_at = ? WHERE id = ?",
            (datetime.now(timezone.utc).isoformat(), key_id),
        )
        conn.commit()
        conn.close()
        resp = client.post(
            "/api/v1/b2b/evaluate",
            json={"address": "123 Main St"},
            headers={"Authorization": "Bearer " + key},
        )
        assert resp.status_code == 401

    def test_suspended_partner_returns_403(self, client):
        pid = _create_partner()
        key, _ = _create_api_key(pid)
        conn = _get_db()
        conn.execute("UPDATE partners SET status = 'suspended' WHERE id = ?", (pid,))
        conn.commit()
        conn.close()
        resp = client.post(
            "/api/v1/b2b/evaluate",
            json={"address": "123 Main St"},
            headers={"Authorization": "Bearer " + key},
        )
        assert resp.status_code == 403
        data = resp.get_json()
        assert data["error"]["code"] == "suspended"
