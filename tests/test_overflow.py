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
