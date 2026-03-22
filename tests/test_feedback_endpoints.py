# tests/test_feedback_endpoints.py
"""Integration tests for NES-362 inline feedback API endpoints."""
import json
import sqlite3
from datetime import datetime, timezone, timedelta

import pytest

from models import _get_db, init_db


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

VID = "test-visitor-uuid-1234"


def _insert_snapshot(snapshot_id, evaluated_at=None):
    """Insert a minimal snapshot row for endpoint tests."""
    if evaluated_at is None:
        evaluated_at = datetime.now(timezone.utc).isoformat()
    conn = _get_db()
    conn.execute(
        """INSERT INTO snapshots
           (snapshot_id, address_input, address_norm, evaluated_at, created_at,
            result_json)
           VALUES (?, ?, ?, ?, datetime('now'), ?)""",
        (snapshot_id, "123 Main St", "123 Main St, White Plains, NY",
         evaluated_at, json.dumps({"tier2_scores": []})),
    )
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# POST /api/feedback
# ---------------------------------------------------------------------------

class TestSubmitFeedback:
    def test_returns_201_on_success(self, client):
        _insert_snapshot("snap_post_ok")
        client.set_cookie("nestcheck_vid", VID, domain="localhost")
        resp = client.post(
            "/api/feedback",
            json={
                "snapshot_id": "snap_post_ok",
                "told_something_new": 1,
            },
        )
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["status"] == "ok"

    def test_missing_snapshot_id_returns_400(self, client):
        client.set_cookie("nestcheck_vid", VID, domain="localhost")
        resp = client.post(
            "/api/feedback",
            json={"told_something_new": 1},
        )
        assert resp.status_code == 400

    def test_missing_told_something_new_returns_400(self, client):
        _insert_snapshot("snap_missing_told")
        client.set_cookie("nestcheck_vid", VID, domain="localhost")
        resp = client.post(
            "/api/feedback",
            json={"snapshot_id": "snap_missing_told"},
        )
        assert resp.status_code == 400

    def test_invalid_told_something_new_returns_400(self, client):
        _insert_snapshot("snap_bad_told")
        client.set_cookie("nestcheck_vid", VID, domain="localhost")
        resp = client.post(
            "/api/feedback",
            json={"snapshot_id": "snap_bad_told", "told_something_new": 2},
        )
        assert resp.status_code == 400

    def test_snapshot_not_found_returns_404(self, client):
        client.set_cookie("nestcheck_vid", VID, domain="localhost")
        resp = client.post(
            "/api/feedback",
            json={"snapshot_id": "nonexistent", "told_something_new": 0},
        )
        assert resp.status_code == 404

    def test_no_identity_returns_400(self, client):
        _insert_snapshot("snap_no_identity")
        resp = client.post(
            "/api/feedback",
            json={"snapshot_id": "snap_no_identity", "told_something_new": 1},
        )
        assert resp.status_code == 400

    def test_duplicate_returns_200_with_duplicate_status(self, client):
        _insert_snapshot("snap_dup")
        vid_dup = VID + "b"
        client.set_cookie("nestcheck_vid", vid_dup, domain="localhost")
        payload = {"snapshot_id": "snap_dup", "told_something_new": 1}
        client.post("/api/feedback", json=payload)
        resp = client.post("/api/feedback", json=payload)
        assert resp.status_code == 200
        assert resp.get_json()["status"] == "duplicate"

    def test_free_text_too_long_returns_400(self, client):
        _insert_snapshot("snap_long_text")
        client.set_cookie("nestcheck_vid", VID, domain="localhost")
        resp = client.post(
            "/api/feedback",
            json={
                "snapshot_id": "snap_long_text",
                "told_something_new": 1,
                "free_text": "x" * 1001,
            },
        )
        assert resp.status_code == 400

    def test_free_text_1000_chars_accepted(self, client):
        _insert_snapshot("snap_max_text")
        client.set_cookie("nestcheck_vid", VID + "c", domain="localhost")
        resp = client.post(
            "/api/feedback",
            json={
                "snapshot_id": "snap_max_text",
                "told_something_new": 1,
                "free_text": "x" * 1000,
            },
        )
        assert resp.status_code == 201

    def test_told_false_accepted(self, client):
        _insert_snapshot("snap_bool_false")
        client.set_cookie("nestcheck_vid", VID + "d", domain="localhost")
        resp = client.post(
            "/api/feedback",
            json={"snapshot_id": "snap_bool_false", "told_something_new": False},
        )
        assert resp.status_code == 201

    def test_told_true_accepted(self, client):
        _insert_snapshot("snap_bool_true")
        client.set_cookie("nestcheck_vid", VID + "e", domain="localhost")
        resp = client.post(
            "/api/feedback",
            json={"snapshot_id": "snap_bool_true", "told_something_new": True},
        )
        assert resp.status_code == 201


# ---------------------------------------------------------------------------
# GET /api/feedback/<snapshot_id>/status
# ---------------------------------------------------------------------------

class TestFeedbackStatus:
    def test_returns_false_when_no_feedback(self, client):
        _insert_snapshot("snap_status_empty")
        client.set_cookie("nestcheck_vid", VID + "f", domain="localhost")
        resp = client.get("/api/feedback/snap_status_empty/status")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["submitted"] is False

    def test_returns_true_after_feedback_submitted(self, client):
        _insert_snapshot("snap_status_submitted")
        vid = VID + "g"
        client.set_cookie("nestcheck_vid", vid, domain="localhost")
        client.post(
            "/api/feedback",
            json={"snapshot_id": "snap_status_submitted", "told_something_new": 1},
        )
        resp = client.get("/api/feedback/snap_status_submitted/status")
        assert resp.status_code == 200
        assert resp.get_json()["submitted"] is True

    def test_status_false_for_different_visitor(self, client):
        _insert_snapshot("snap_status_diff")
        vid_a = VID + "h"
        client.set_cookie("nestcheck_vid", vid_a, domain="localhost")
        client.post(
            "/api/feedback",
            json={"snapshot_id": "snap_status_diff", "told_something_new": 1},
        )
        # Switch to a different visitor
        client.set_cookie("nestcheck_vid", VID + "i", domain="localhost")
        resp = client.get("/api/feedback/snap_status_diff/status")
        assert resp.get_json()["submitted"] is False

    def test_status_no_identity(self, client):
        _insert_snapshot("snap_status_no_id")
        resp = client.get("/api/feedback/snap_status_no_id/status")
        assert resp.status_code == 200
        assert resp.get_json()["submitted"] is False
