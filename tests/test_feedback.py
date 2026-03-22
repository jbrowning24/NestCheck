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
