"""B2B curated response schema builder.

Transforms the internal result_to_dict() output into a clean, stable API
response suitable for external partners. Internal fields and presentation
artifacts are excluded.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

_SNAPSHOT_BASE_URL = "https://nestcheck.com/s/"

# Walk Scores fields to embed in specific dimensions.
_DIMENSION_WALK_SCORE_MAP: dict[str, str] = {
    "walkability": "walk_score",
    "transit": "transit_score",
}


def build_b2b_response(snapshot_result: dict[str, Any], snapshot_id: str) -> dict[str, Any]:
    """Build a curated B2B API response from a serialized snapshot result.

    Args:
        snapshot_result: Output of result_to_dict() — a fully serialized dict.
        snapshot_id: The snapshot identifier used to build the canonical URL.

    Returns:
        A curated dict safe for external API consumers. Internal fields
        (_trace, quality_ceiling_inputs) and presentation fields (icon,
        css_class) are excluded.
    """
    walk_scores: dict[str, Any] = snapshot_result.get("walk_scores") or {}
    tier2_scores: dict[str, Any] = snapshot_result.get("tier2_scores") or {}
    health_summary: dict[str, Any] = snapshot_result.get("health_summary") or {}

    dimensions = _build_dimensions(tier2_scores, walk_scores)
    health = _build_health(snapshot_result.get("checks") or [], health_summary)

    return {
        "address": snapshot_result.get("address"),
        "coordinates": snapshot_result.get("coordinates"),
        "composite_score": snapshot_result.get("composite_score"),
        "composite_band": snapshot_result.get("composite_band"),
        "health": health,
        "dimensions": dimensions,
        "data_confidence": snapshot_result.get("data_confidence"),
        "snapshot_id": snapshot_id,
        "snapshot_url": f"{_SNAPSHOT_BASE_URL}{snapshot_id}",
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
    }


def _build_dimensions(
    tier2_scores: dict[str, Any],
    walk_scores: dict[str, Any],
) -> dict[str, Any]:
    """Map tier2_scores into the B2B dimensions shape, embedding Walk Score fields."""
    dimensions: dict[str, Any] = {}
    for name, data in tier2_scores.items():
        dim: dict[str, Any] = {
            "score": data.get("points"),
            "band": data.get("band"),
        }
        walk_score_field = _DIMENSION_WALK_SCORE_MAP.get(name)
        if walk_score_field and walk_score_field in walk_scores:
            dim[walk_score_field] = walk_scores[walk_score_field]
        dimensions[name] = dim
    return dimensions


def _build_health(
    checks: list[dict[str, Any]],
    health_summary: dict[str, Any],
) -> dict[str, Any]:
    """Strip presentation fields from checks and attach summary counts."""
    curated_checks = [
        {
            "name": c.get("name"),
            "status": c.get("status"),
            "distance_ft": c.get("distance_ft"),
            "description": c.get("description"),
        }
        for c in checks
    ]
    return {
        "checks": curated_checks,
        "clear_count": health_summary.get("clear", 0),
        "issue_count": health_summary.get("issues", 0),
        "warning_count": health_summary.get("warnings", 0),
    }
