# NES-263: Overflow Mode for Large Evaluation Stage Outputs

**Date:** 2026-03-18
**Status:** Approved
**Linear:** NES-263

## Problem

NestCheck's evaluation pipeline produces lists of varying size: TRI facilities (up to 50), parks (up to 10), neighborhood venues (up to 5 per category), EJScreen indicators, spatial query results. The pipeline already applies data-fetching limits (`[:5]`, `LIMIT 50`) to control API costs and query scope, but there is no presentation-layer utility for display truncation.

Future consumers — CLI (NES-262), batch evaluation, agent layer, debug/audit workflows — need a way to receive large result sets without flooding their output surface. The utility should truncate to a configurable limit, provide a summary of what was omitted, and optionally write the full dataset to a file for exploration.

## Design

### API Surface

One function, one dataclass. The module lives at `overflow.py` in the project root (alongside `property_evaluator.py`, `scoring_config.py`).

```python
from dataclasses import dataclass
from typing import Any, Callable, List, Optional

@dataclass
class OverflowResult:
    items: List[Any]          # Truncated list (or full list if under limit)
    total: int                # Original item count
    truncated: bool           # Whether truncation occurred
    summary: Optional[str]    # Human-readable footer; None when not truncated
    dump_path: Optional[str]  # Path to full JSON dump; None when not dumped

def overflow(
    items: List[Any],
    limit: int,
    *,
    label: str = "items",
    label_fn: Optional[Callable[[List[Any]], str]] = None,
    dump_path: Optional[str] = None,
    dump_fn: Optional[Callable[[Any], Any]] = None,
) -> OverflowResult:
    ...
```

### Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `items` | `List[Any]` | Yes | The full list to potentially truncate. |
| `limit` | `int` | Yes | Maximum items to keep. Must be >= 1. |
| `label` | `str` | No | Noun for the summary footer. Default: `"items"`. Used when `label_fn` is not provided. |
| `label_fn` | `Callable[[List[Any]], str]` | No | If provided, called with the **full** `items` list. Its return value **replaces `label` entirely** in the summary string — it is not combined with `label`. This allows callers to produce context-dependent labels (e.g., `lambda items: f"TRI facilities within 5km"`). |
| `dump_path` | `str` | No | File path to write full JSON dump. Dump only occurs when truncation happens AND `dump_path` is provided. Parent directories are created automatically. |
| `dump_fn` | `Callable[[Any], Any]` | No | Per-item serialization function for JSON dump. Applied to each item before `json.dumps`. Default: items are dumped as-is (must be JSON-serializable). Useful for dataclass instances or objects with custom serialization. |

### Behavior

**No truncation (len(items) <= limit):**
Returns `OverflowResult` with full `items` list, `truncated=False`, `summary=None`, `dump_path=None`.

**Truncation (len(items) > limit):**
Returns `OverflowResult` with `items[:limit]`, `truncated=True`, and a summary string.

Summary format: `"Showing {limit} of {total} {resolved_label}."` where `resolved_label` is `label_fn(items)` if provided, otherwise `label`.

If `dump_path` is provided, the full list is written as JSON to that path (creating parent directories as needed), and `dump_path` is set on the result. If the write fails, `dump_path` is `None` and a warning is logged — dump failure never raises.

**Edge cases:**
- Empty list: returns empty `items`, `total=0`, `truncated=False`.
- `limit >= len(items)`: no truncation.
- `limit < 1`: raises `ValueError`.
- `dump_fn` raises on an item: logs warning, skips dump, `dump_path=None`.

### label_fn Contract

`label_fn` and `label` are mutually exclusive in effect. When `label_fn` is provided:
- `label_fn(items)` is called with the full (pre-truncation) list
- Its return value is used as the complete label text in the summary
- The `label` parameter is ignored entirely

This avoids ambiguity about how `label_fn` and `label` interact. The caller owns the full label string when using `label_fn`.

### File Dump

The dump helper (`_dump_json`) is an internal function, separately testable:

```python
def _dump_json(
    items: List[Any],
    path: str,
    dump_fn: Optional[Callable[[Any], Any]] = None,
) -> Optional[str]:
    """Write items as JSON to path. Returns path on success, None on failure.

    Uses logging.getLogger(__name__) for warnings on failure.
    """
```

- Creates parent directories via `os.makedirs(exist_ok=True)`
- Writes with `json.dump(..., indent=2)` for human readability
- Wrapped in try/except — logs `logger.warning` on failure, returns `None`
- If `dump_fn` is provided, applies it to each item: `[dump_fn(i) for i in items]`

Default dump directory convention for future consumers: `/tmp/nestcheck/<stage>_<timestamp>.json`. The overflow utility itself does not enforce this — it writes to whatever `dump_path` the caller provides. The convention is documented here for consistency across consumers.

## What This Is Not

- **Not a replacement for pipeline-level limits.** The `[:5]` slices and `LIMIT 50` in the evaluator control data fetching. This utility controls display.
- **Not format-aware.** It returns a dataclass. Rendering to terminal, markdown, JSON, or HTML is the caller's responsibility.
- **Not wired into any existing consumer.** This is a standalone module. Integration with CLI (NES-262), batch mode, and agent layer happens in those tickets.

## Testing

Unit tests in `tests/test_overflow.py`:

1. **No truncation:** list under limit returns full list, `truncated=False`, `summary=None`
2. **Truncation:** list over limit returns truncated list, correct `total`, summary string
3. **Custom label:** summary uses provided `label`
4. **label_fn override:** summary uses `label_fn` return value, ignores `label`
5. **Dump on truncation:** file written, `dump_path` set on result
6. **No dump when not truncated:** even if `dump_path` provided, no file written
7. **Dump failure graceful:** invalid path logs warning, `dump_path=None`, no raise
8. **dump_fn applied:** custom serializer transforms items in dump file
9. **Empty list:** returns empty result, no truncation
10. **limit < 1:** raises `ValueError`
11. **Exact boundary:** `len(items) == limit` returns full list, not truncated
12. **dump_fn raises:** logs warning, `dump_path=None`, no raise

## File Layout

```
NestCheck/
  overflow.py                    # Module: overflow(), OverflowResult, _dump_json()
  tests/test_overflow.py         # Unit tests
```
