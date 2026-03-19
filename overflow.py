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

    # Truncation path — implemented in Task 2
    raise NotImplementedError


def _dump_json(
    items: List[Any],
    path: str,
    dump_fn: Optional[Callable[[Any], Any]] = None,
) -> Optional[str]:
    """Write items as JSON to path. Returns path on success, None on failure.

    Uses logging.getLogger(__name__) for warnings on failure.
    """
    raise NotImplementedError
