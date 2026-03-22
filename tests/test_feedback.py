# tests/test_feedback.py
"""Tests for the feedback survey system (NES-363)."""
import json
import sqlite3
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _fresh_db(tmp_path):
    """Create a fresh test database and patch models to use it."""
    import models
    db_path = str(tmp_path / "test.db")
    original = models.DB_PATH
    models.DB_PATH = db_path
    models.init_db()
    return db_path, original


def test_save_feedback_inserts_row(tmp_path):
    import models
    db_path, original = _fresh_db(tmp_path)
    try:
        response = json.dumps({"overall_accuracy": 4})
        models.save_feedback(
            snapshot_id="abc12345",
            feedback_type="detailed_survey",
            response_json=response,
            address_norm="123 Main St, White Plains, NY",
            visitor_id="visitor123",
        )

        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM feedback WHERE snapshot_id = 'abc12345'").fetchone()
        conn.close()

        assert row is not None
        assert row["feedback_type"] == "detailed_survey"
        assert row["address_norm"] == "123 Main St, White Plains, NY"
        assert row["visitor_id"] == "visitor123"
        assert json.loads(row["response_json"])["overall_accuracy"] == 4
        assert row["created_at"] is not None
    finally:
        models.DB_PATH = original


def test_save_feedback_works_without_optional_fields(tmp_path):
    import models
    db_path, original = _fresh_db(tmp_path)
    try:
        models.save_feedback(
            snapshot_id="def67890",
            feedback_type="detailed_survey",
            response_json="{}",
        )

        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM feedback WHERE snapshot_id = 'def67890'").fetchone()
        conn.close()

        assert row is not None
        assert row["address_norm"] is None
        assert row["visitor_id"] is None
    finally:
        models.DB_PATH = original


def test_post_feedback_success(tmp_path):
    """POST /api/feedback with valid data returns success."""
    import models
    db_path, original = _fresh_db(tmp_path)
    try:
        from app import app
        app.config["TESTING"] = True
        app.config["WTF_CSRF_ENABLED"] = False

        conn = sqlite3.connect(db_path)
        conn.execute(
            "INSERT INTO snapshots (snapshot_id, address_input, result_json, created_at) "
            "VALUES (?, ?, ?, datetime('now'))",
            ("snap1234", "123 Main St", json.dumps({"tier2_scores": []})),
        )
        conn.commit()
        conn.close()

        with app.test_client() as client:
            resp = client.post("/api/feedback", json={
                "snapshot_id": "snap1234",
                "feedback_type": "detailed_survey",
                "response_json": json.dumps({"overall_accuracy": 4}),
            })
            assert resp.status_code == 200
            data = resp.get_json()
            assert data["success"] is True

        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM feedback WHERE snapshot_id = 'snap1234'").fetchone()
        conn.close()
        assert row is not None
    finally:
        models.DB_PATH = original


def test_post_feedback_missing_fields(tmp_path):
    """POST /api/feedback without required fields returns 400."""
    import models
    _, original = _fresh_db(tmp_path)
    try:
        from app import app
        app.config["TESTING"] = True
        app.config["WTF_CSRF_ENABLED"] = False

        with app.test_client() as client:
            resp = client.post("/api/feedback", json={
                "feedback_type": "detailed_survey",
                "response_json": "{}",
            })
            assert resp.status_code == 400

            resp = client.post("/api/feedback", json={
                "snapshot_id": "snap1234",
                "feedback_type": "detailed_survey",
            })
            assert resp.status_code == 400
    finally:
        models.DB_PATH = original


def test_post_feedback_invalid_json(tmp_path):
    """POST /api/feedback with invalid response_json returns 400."""
    import models
    _, original = _fresh_db(tmp_path)
    try:
        from app import app
        app.config["TESTING"] = True
        app.config["WTF_CSRF_ENABLED"] = False

        with app.test_client() as client:
            resp = client.post("/api/feedback", json={
                "snapshot_id": "snap1234",
                "feedback_type": "detailed_survey",
                "response_json": "not valid json{{{",
            })
            assert resp.status_code == 400
    finally:
        models.DB_PATH = original


def test_get_feedback_valid_snapshot(tmp_path):
    """GET /feedback/<snapshot_id> returns 200 for a valid snapshot."""
    import models
    db_path, original = _fresh_db(tmp_path)
    try:
        from app import app
        app.config["TESTING"] = True
        app.config["WTF_CSRF_ENABLED"] = False

        result = {
            "tier1_checks": [],
            "tier2_scores": [],
            "final_score": 76,
            "coordinates": {"lat": 41.0, "lng": -73.7},
            "dimension_summaries": [
                {"name": "Coffee & Social Spots", "score": 8, "max_score": 10,
                 "data_confidence": "verified", "band": {"key": "strong", "label": "Strong"}},
                {"name": "Road Noise", "score": 7, "max_score": 10,
                 "data_confidence": "not_scored", "band": {"key": "not_scored", "label": "Not scored"}},
            ],
        }
        conn = sqlite3.connect(db_path)
        conn.execute(
            "INSERT INTO snapshots (snapshot_id, address_input, address_norm, "
            "result_json, final_score, created_at) "
            "VALUES (?, ?, ?, ?, ?, datetime('now'))",
            ("feedtest", "123 Main St", "123 Main St, White Plains, NY",
             json.dumps(result), 76),
        )
        conn.commit()
        conn.close()

        with app.test_client() as client:
            resp = client.get("/feedback/feedtest")
            assert resp.status_code == 200
            html = resp.data.decode()
            assert "123 Main St" in html
            assert "Coffee" in html
            assert "Road Noise" not in html
    finally:
        models.DB_PATH = original


def test_get_feedback_invalid_snapshot(tmp_path):
    """GET /feedback/<bad_id> returns 404."""
    import models
    _, original = _fresh_db(tmp_path)
    try:
        from app import app
        app.config["TESTING"] = True

        with app.test_client() as client:
            resp = client.get("/feedback/nonexistent")
            assert resp.status_code == 404
    finally:
        models.DB_PATH = original
