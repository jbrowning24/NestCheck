# Overflow Mode Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a presentation-layer utility that truncates large lists with a summary footer and optional file dump.

**Architecture:** Single function `overflow()` returning an `OverflowResult` dataclass. Internal `_dump_json()` helper for file writes. No dependencies beyond stdlib. No integration with existing consumers — standalone module tested in isolation.

**Tech Stack:** Python 3.x stdlib only (`dataclasses`, `json`, `os`, `logging`)

**Spec:** `docs/superpowers/specs/2026-03-18-overflow-mode-design.md`

---

## File Structure

| File | Responsibility |
|------|---------------|
| `overflow.py` (create) | `OverflowResult` dataclass, `overflow()` function, `_dump_json()` helper |
| `tests/test_overflow.py` (create) | 14 unit tests covering all 12 spec contract behaviors (spec case #10 split into 2 tests) |

---

### Task 1: OverflowResult dataclass + overflow() no-truncation path

**Files:**
- Create: `tests/test_overflow.py`
- Create: `overflow.py`

- [ ] **Step 1: Write failing tests for no-truncation cases**

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/jeremybrowning/NestCheck && python -m pytest tests/test_overflow.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'overflow'` (or an import error from `tests/conftest.py` if `SECRET_KEY`/`GOOGLE_MAPS_API_KEY` env vars are not set — the conftest loads the full Flask app for all tests under `tests/`. CI already sets these vars.)

- [ ] **Step 3: Write OverflowResult and overflow() with no-truncation path**

```python
"""Overflow mode for large evaluation stage outputs.

Presentation-layer utility that truncates large lists for display,
returning metadata about what was omitted and optionally writing
full data to a file for exploration.
"""

import json
import logging
import os
from dataclasses import dataclass
from typing import Any, Callable, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class OverflowResult:
    """Result of applying overflow truncation to a list.

    Attributes:
        items: Truncated list (or full list if under limit).
        total: Original item count.
        truncated: Whether truncation occurred.
        summary: Human-readable footer, e.g.
            "Showing 20 of 147 TRI facilities." None when not truncated.
        dump_path: Path to full JSON dump. None when not dumped.
    """

    items: List[Any]
    total: int
    truncated: bool
    summary: Optional[str]
    dump_path: Optional[str]


def overflow(
    items: List[Any],
    limit: int,
    *,
    label: str = "items",
    label_fn: Optional[Callable[[List[Any]], str]] = None,
    dump_path: Optional[str] = None,
    dump_fn: Optional[Callable[[Any], Any]] = None,
) -> OverflowResult:
    """Apply overflow truncation to a list.

    Args:
        items: The full list to potentially truncate.
        limit: Maximum items to keep. Must be >= 1.
        label: Noun for the summary footer. Default: "items".
            Ignored when label_fn is provided.
        label_fn: If provided, called with the full items list. Its return
            value replaces label entirely in the summary string — it is not
            combined with label.
        dump_path: File path to write full JSON dump. Dump only occurs when
            truncation happens AND dump_path is provided.
        dump_fn: Per-item serialization function for JSON dump. Applied to
            each item before json.dumps. Default: items dumped as-is.

    Returns:
        OverflowResult with truncated items and metadata.

    Raises:
        ValueError: If limit < 1.
    """
    if limit < 1:
        raise ValueError(f"limit must be >= 1, got {limit}")

    total = len(items)

    if total <= limit:
        return OverflowResult(
            items=items,
            total=total,
            truncated=False,
            summary=None,
            dump_path=None,
        )

    # Truncation path — implemented in next task
    raise NotImplementedError
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/jeremybrowning/NestCheck && python -m pytest tests/test_overflow.py::TestNoTruncation -v`
Expected: All 4 tests PASS

- [ ] **Step 5: Commit**

```bash
cd /Users/jeremybrowning/NestCheck
git add overflow.py tests/test_overflow.py
git commit -m "feat(NES-263): add OverflowResult dataclass and no-truncation path"
```

---

### Task 2: Truncation path with label and label_fn

**Files:**
- Modify: `tests/test_overflow.py`
- Modify: `overflow.py`

- [ ] **Step 1: Write failing tests for truncation + labels**

Append to `tests/test_overflow.py`:

```python
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
            label_fn=lambda xs: f"TRI facilities within 5km",
        )
        assert result.summary == "Showing 10 of 50 TRI facilities within 5km."
        assert "should be ignored" not in result.summary
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/jeremybrowning/NestCheck && python -m pytest tests/test_overflow.py::TestTruncation -v`
Expected: FAIL — `NotImplementedError`

- [ ] **Step 3: Implement truncation path in overflow()**

Replace the `raise NotImplementedError` block in `overflow()` with the truncation path, and add a `_dump_json` stub (implemented in Task 3):

```python
    resolved_label = label_fn(items) if label_fn is not None else label
    summary = f"Showing {limit} of {total} {resolved_label}."

    written_path = None
    if dump_path is not None:
        written_path = _dump_json(items, dump_path, dump_fn)

    return OverflowResult(
        items=items[:limit],
        total=total,
        truncated=True,
        summary=summary,
        dump_path=written_path,
    )
```

Also add the `_dump_json` stub at the bottom of `overflow.py` (no tests call it yet since none pass `dump_path` with truncation):

```python
def _dump_json(
    items: List[Any],
    path: str,
    dump_fn: Optional[Callable[[Any], Any]] = None,
) -> Optional[str]:
    """Write items as JSON to path. Returns path on success, None on failure.

    Uses logging.getLogger(__name__) for warnings on failure.
    """
    raise NotImplementedError
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/jeremybrowning/NestCheck && python -m pytest tests/test_overflow.py -v`
Expected: All 7 tests PASS (4 no-truncation + 3 truncation; no test provides `dump_path` with truncation so the stub is not hit)

- [ ] **Step 5: Commit**

```bash
cd /Users/jeremybrowning/NestCheck
git add overflow.py tests/test_overflow.py
git commit -m "feat(NES-263): add truncation path with label and label_fn"
```

---

### Task 3: File dump via _dump_json()

**Files:**
- Modify: `tests/test_overflow.py`
- Modify: `overflow.py`

- [ ] **Step 1: Write failing tests for dump behavior**

Append to `tests/test_overflow.py`:

```python
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
        # Use an invalid path (directory as filename on Unix)
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/jeremybrowning/NestCheck && python -m pytest tests/test_overflow.py::TestDump -v`
Expected: FAIL — `NotImplementedError` from `_dump_json`

- [ ] **Step 3: Implement _dump_json()**

Replace the `_dump_json` stub in `overflow.py`:

```python
def _dump_json(
    items: List[Any],
    path: str,
    dump_fn: Optional[Callable[[Any], Any]] = None,
) -> Optional[str]:
    """Write items as JSON to path. Returns path on success, None on failure.

    Uses logging.getLogger(__name__) for warnings on failure.
    Creates parent directories automatically.
    """
    try:
        data = [dump_fn(item) for item in items] if dump_fn is not None else items
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(path, "w") as f:
            json.dump(data, f, indent=2)
        return path
    except Exception:
        logger.warning("Failed to write overflow dump to %s", path, exc_info=True)
        return None
```

- [ ] **Step 4: Run all tests to verify they pass**

Run: `cd /Users/jeremybrowning/NestCheck && python -m pytest tests/test_overflow.py -v`
Expected: All 12 tests PASS

- [ ] **Step 5: Commit**

```bash
cd /Users/jeremybrowning/NestCheck
git add overflow.py tests/test_overflow.py
git commit -m "feat(NES-263): add _dump_json with graceful failure handling"
```

---

### Task 4: Validation edge case + final test

**Files:**
- Modify: `tests/test_overflow.py`

- [ ] **Step 1: Write test for limit < 1 validation**

Append to `tests/test_overflow.py`:

```python
class TestValidation:
    """Input validation edge cases."""

    def test_limit_zero_raises(self):
        with pytest.raises(ValueError, match="limit must be >= 1"):
            overflow([1, 2, 3], limit=0)

    def test_limit_negative_raises(self):
        with pytest.raises(ValueError, match="limit must be >= 1"):
            overflow([1], limit=-1)
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `cd /Users/jeremybrowning/NestCheck && python -m pytest tests/test_overflow.py -v`
Expected: All 14 tests PASS (validation was already implemented in Task 1)

- [ ] **Step 3: Commit**

```bash
cd /Users/jeremybrowning/NestCheck
git add tests/test_overflow.py
git commit -m "test(NES-263): add validation edge case tests for overflow()"
```

---

### Task 5: Wire into CI + final verification

**Files:**
- Modify: `.github/workflows/ci.yml`
- Modify: `Makefile`

- [ ] **Step 1: Check current CI config for test patterns**

Read: `.github/workflows/ci.yml` — find the `pytest` command in `scoring-tests` job.
Read: `Makefile` — find `test-scoring` target.

- [ ] **Step 2: Add overflow tests to CI gate**

In `.github/workflows/ci.yml`, add `tests/test_overflow.py` to the pytest command in the `scoring-tests` job (alongside existing `tests/test_scoring_regression.py tests/test_scoring_config.py`).

In `Makefile`, add `tests/test_overflow.py` to the `test-scoring` target command.

- [ ] **Step 3: Run full test suite locally**

Run: `cd /Users/jeremybrowning/NestCheck && python -m pytest tests/test_overflow.py -v`
Expected: All 14 tests PASS

- [ ] **Step 4: Commit**

```bash
cd /Users/jeremybrowning/NestCheck
git add .github/workflows/ci.yml Makefile
git commit -m "ci(NES-263): add overflow tests to scoring-tests gate"
```
