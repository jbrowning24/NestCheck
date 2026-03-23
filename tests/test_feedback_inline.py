# tests/test_feedback_inline.py
"""Unit tests for NES-362 inline feedback model functions."""
import sqlite3
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ---------------------------------------------------------------------------
# has_inline_feedback
# ---------------------------------------------------------------------------

def test_has_inline_feedback_false_when_no_identity(tmp_path):
    import models
    original = models.DB_PATH
    models.DB_PATH = str(tmp_path / "test.db")
    models.init_db()
    try:
        result = models.has_inline_feedback("snap1", user_id=None, visitor_id=None)
        assert result is False
    finally:
        models.DB_PATH = original


def test_has_inline_feedback_false_when_no_matching_row(tmp_path):
    import models
    original = models.DB_PATH
    models.DB_PATH = str(tmp_path / "test.db")
    models.init_db()
    try:
        result = models.has_inline_feedback("snap1", visitor_id="vid-abc")
        assert result is False
    finally:
        models.DB_PATH = original


def test_has_inline_feedback_true_after_save_visitor(tmp_path):
    import models
    original = models.DB_PATH
    models.DB_PATH = str(tmp_path / "test.db")
    models.init_db()
    try:
        saved = models.save_inline_feedback(
            "snap1", None, "vid-abc", "inline_reaction", 1
        )
        assert saved is True
        assert models.has_inline_feedback("snap1", visitor_id="vid-abc") is True
    finally:
        models.DB_PATH = original


def test_has_inline_feedback_true_after_save_user(tmp_path):
    import models
    original = models.DB_PATH
    models.DB_PATH = str(tmp_path / "test.db")
    models.init_db()
    try:
        saved = models.save_inline_feedback(
            "snap1", 42, None, "inline_reaction", 0
        )
        assert saved is True
        assert models.has_inline_feedback("snap1", user_id=42) is True
    finally:
        models.DB_PATH = original


def test_has_inline_feedback_visitor_does_not_cross_contaminate(tmp_path):
    """Feedback for visitor A should not appear for visitor B."""
    import models
    original = models.DB_PATH
    models.DB_PATH = str(tmp_path / "test.db")
    models.init_db()
    try:
        models.save_inline_feedback("snap1", None, "vid-A", "inline_reaction", 1)
        assert models.has_inline_feedback("snap1", visitor_id="vid-B") is False
    finally:
        models.DB_PATH = original


# ---------------------------------------------------------------------------
# save_inline_feedback
# ---------------------------------------------------------------------------

def test_save_inline_feedback_returns_true_on_first_save(tmp_path):
    import models
    original = models.DB_PATH
    models.DB_PATH = str(tmp_path / "test.db")
    models.init_db()
    try:
        result = models.save_inline_feedback(
            "snap1", None, "vid-abc", "inline_reaction", 1, "Great report"
        )
        assert result is True
    finally:
        models.DB_PATH = original


def test_save_inline_feedback_returns_false_on_duplicate(tmp_path):
    import models
    original = models.DB_PATH
    models.DB_PATH = str(tmp_path / "test.db")
    models.init_db()
    try:
        models.save_inline_feedback("snap1", None, "vid-abc", "inline_reaction", 1)
        result = models.save_inline_feedback("snap1", None, "vid-abc", "inline_reaction", 0)
        assert result is False
    finally:
        models.DB_PATH = original


def test_save_inline_feedback_stores_all_fields(tmp_path):
    import models
    db_path = str(tmp_path / "test.db")
    original = models.DB_PATH
    models.DB_PATH = db_path
    models.init_db()
    try:
        models.save_inline_feedback(
            "snap99", 7, "vid-xyz", "inline_reaction", 1, "Very helpful"
        )
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM feedback WHERE snapshot_id = 'snap99'"
        ).fetchone()
        conn.close()
        assert row is not None
        assert row["user_id"] == 7
        assert row["visitor_id"] == "vid-xyz"
        assert row["feedback_type"] == "inline_reaction"
        assert row["told_something_new"] == 1
        assert row["free_text"] == "Very helpful"
        assert row["created_at"] is not None
    finally:
        models.DB_PATH = original


def test_save_inline_feedback_no_free_text(tmp_path):
    import models
    db_path = str(tmp_path / "test.db")
    original = models.DB_PATH
    models.DB_PATH = db_path
    models.init_db()
    try:
        models.save_inline_feedback("snap2", None, "vid-abc", "inline_reaction", 0)
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM feedback WHERE snapshot_id = 'snap2'"
        ).fetchone()
        conn.close()
        assert row["free_text"] is None
    finally:
        models.DB_PATH = original


def test_save_inline_feedback_told_something_new_zero(tmp_path):
    """told_something_new=0 (No) should be stored correctly."""
    import models
    db_path = str(tmp_path / "test.db")
    original = models.DB_PATH
    models.DB_PATH = db_path
    models.init_db()
    try:
        models.save_inline_feedback("snap3", None, "vid-abc", "inline_reaction", 0)
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM feedback WHERE snapshot_id = 'snap3'"
        ).fetchone()
        conn.close()
        assert row["told_something_new"] == 0
    finally:
        models.DB_PATH = original


# ---------------------------------------------------------------------------
# Migration: new columns exist after init_db
# ---------------------------------------------------------------------------

def test_init_db_creates_nes362_columns(tmp_path):
    import models
    db_path = str(tmp_path / "test.db")
    original = models.DB_PATH
    models.DB_PATH = db_path
    models.init_db()
    try:
        conn = sqlite3.connect(db_path)
        cols = {row[1] for row in conn.execute("PRAGMA table_info(feedback)").fetchall()}
        conn.close()
        assert "user_id" in cols
        assert "told_something_new" in cols
        assert "free_text" in cols
    finally:
        models.DB_PATH = original
