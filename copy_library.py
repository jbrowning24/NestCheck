"""Empty state copy library for NestCheck evaluation reports (NES-319).

Provides what/why/so_what copy for every failure mode in the evaluation
pipeline. Organized by check name → failure type → CopyEntry. Zero
dependencies beyond stdlib.

See: docs/superpowers/specs/2026-03-21-empty-state-copy-library-design.md
"""

import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CopyEntry:
    """A single empty state message with three fields."""
    what: str
    why: str
    so_what: str

    @property
    def combined(self) -> str:
        """Joins fields into a single string for compact display contexts."""
        return f"{self.what} {self.why} {self.so_what}"


# --- Alias mapping: evaluator check names → copy library keys ---

CHECK_NAME_ALIASES: dict[str, str] = {
    # Legacy display names
    "Flood zone": "flood_zone",
    "Power lines": "power_lines",
    "Gas station": "gas_station",
    "Superfund (NPL)": "superfund",
    "High-traffic road": "high_traffic_road",
    "TRI facility": "tri_proximity",
    "Industrial zone": "industrial_zone",
    "Electrical substation": "electrical_substation",
    "Cell tower": "cell_tower",
    "Road Noise": "road_noise",
    # Phase 1B spatial names
    "hifld_power_lines": "power_lines",
    # Listing amenity display names
    "W/D in unit": "washer_dryer",
    "Central air": "central_air",
    "Size": "square_footage",
    "Bedrooms": "bedrooms",
    # EJScreen per-indicator names → block-group-level copy
    "EJScreen PM2.5": "ejscreen",
    "EJScreen cancer risk": "ejscreen",
    "EJScreen diesel PM": "ejscreen",
    "EJScreen lead paint": "ejscreen",
    "EJScreen Superfund": "ejscreen",
    "EJScreen hazardous waste": "ejscreen",
}


# --- Copy library: check_name → failure_type → CopyEntry ---
# Populated in Task 2. Scaffold with flood_zone for initial test pass.

COPY_LIBRARY: dict[str, dict[str, CopyEntry]] = {
    "flood_zone": {
        "F1": CopyEntry(
            what="Flood zone data is temporarily unavailable.",
            why="FEMA's mapping service isn't responding right now.",
            so_what="This check is not included in your health summary.",
        ),
    },
}


# --- F6: Complete evaluation failure (standalone, no check context) ---

EVALUATION_FAILURE_COPY = CopyEntry(
    what="We couldn't evaluate this address.",
    why="This may be due to a temporary issue, an unrecognizable address format, or an area we don't cover yet.",
    so_what="Try again in a few minutes. If the problem persists, report it so we can investigate.",
)


def get_copy(check_name: str, failure_type: str) -> Optional[CopyEntry]:
    """Look up empty state copy for a check and failure type.

    Resolves CHECK_NAME_ALIASES first, then looks up COPY_LIBRARY.
    Returns None on miss so the caller can fall back to generic text.
    """
    key = CHECK_NAME_ALIASES.get(check_name, check_name)
    check_entries = COPY_LIBRARY.get(key)
    if check_entries is None:
        logger.debug("copy_library miss: check_name=%r (key=%r) not found", check_name, key)
        return None
    entry = check_entries.get(failure_type)
    if entry is None:
        logger.debug(
            "copy_library miss: check_name=%r (key=%r) has no %r entry",
            check_name, key, failure_type,
        )
    return entry
