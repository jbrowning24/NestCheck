"""Tests for overflow module."""

import json
import os
import tempfile

import pytest

from overflow import OverflowResult, overflow


class TestNoTruncation:
    """Cases where len(items) <= limit — no truncation occurs."""

    def test_under_limit(self):
        result = overflow([1, 2, 3], limit=5)
        assert result.items == [1, 2, 3]
        assert result.total == 3
        assert result.truncated is False
        assert result.summary is None
        assert result.dump_path is None

    def test_empty_list(self):
        result = overflow([], limit=10)
        assert result.items == []
        assert result.total == 0
        assert result.truncated is False
        assert result.summary is None

    def test_exact_boundary(self):
        items = list(range(5))
        result = overflow(items, limit=5)
        assert result.items == items
        assert result.total == 5
        assert result.truncated is False
        assert result.summary is None

    def test_no_dump_when_not_truncated(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "dump.json")
            result = overflow([1, 2], limit=5, dump_path=path)
            assert result.dump_path is None
            assert not os.path.exists(path)


class TestTruncation:
    """Cases where len(items) > limit — truncation occurs."""

    def test_basic_truncation(self):
        items = list(range(10))
        result = overflow(items, limit=3)
        assert result.items == [0, 1, 2]
        assert result.total == 10
        assert result.truncated is True
        assert result.summary == "Showing 3 of 10 items."

    def test_custom_label(self):
        items = [{"name": f"park_{i}"} for i in range(20)]
        result = overflow(items, limit=5, label="parks")
        assert result.summary == "Showing 5 of 20 parks."

    def test_label_fn_overrides_label(self):
        items = [{"name": f"fac_{i}"} for i in range(50)]
        result = overflow(
            items,
            limit=10,
            label="should be ignored",
            label_fn=lambda xs: "TRI facilities within 5km",
        )
        assert result.summary == "Showing 10 of 50 TRI facilities within 5km."
        assert "should be ignored" not in result.summary


class TestDump:
    """File dump behavior — only on truncation with dump_path provided."""

    def test_dump_on_truncation(self):
        items = list(range(10))
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "results.json")
            result = overflow(items, limit=3, dump_path=path)
            assert result.dump_path == path
            assert os.path.exists(path)
            with open(path) as f:
                dumped = json.load(f)
            assert dumped == items

    def test_dump_creates_parent_dirs(self):
        items = list(range(10))
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "nested", "deep", "results.json")
            result = overflow(items, limit=3, dump_path=path)
            assert result.dump_path == path
            assert os.path.exists(path)

    def test_dump_fn_applied(self):
        items = [{"name": "Park A", "internal_id": 99}, {"name": "Park B", "internal_id": 100}]
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "parks.json")
            result = overflow(
                items,
                limit=1,
                dump_path=path,
                dump_fn=lambda x: {"name": x["name"]},
            )
            assert result.dump_path == path
            with open(path) as f:
                dumped = json.load(f)
            assert dumped == [{"name": "Park A"}, {"name": "Park B"}]

    def test_dump_failure_graceful(self):
        items = list(range(10))
        result = overflow(items, limit=3, dump_path="/dev/null/impossible/file.json")
        assert result.dump_path is None
        assert result.truncated is True
        assert result.summary is not None

    def test_dump_fn_raises_graceful(self):
        items = [1, 2, 3, 4, 5]

        def bad_fn(x):
            raise TypeError("can't serialize this")

        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "results.json")
            result = overflow(items, limit=2, dump_path=path, dump_fn=bad_fn)
            assert result.dump_path is None
            assert result.truncated is True


class TestValidation:
    """Input validation edge cases."""

    def test_limit_zero_raises(self):
        with pytest.raises(ValueError, match="limit must be >= 1"):
            overflow([1, 2, 3], limit=0)

    def test_limit_negative_raises(self):
        with pytest.raises(ValueError, match="limit must be >= 1"):
            overflow([1], limit=-1)
