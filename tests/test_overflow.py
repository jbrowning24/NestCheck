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
