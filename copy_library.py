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

COPY_LIBRARY: dict[str, dict[str, CopyEntry]] = {
    # ---------------------------------------------------------------
    # Tier 1 Health Checks (12 keys, 21 entries)
    # ---------------------------------------------------------------
    "flood_zone": {
        "F1": CopyEntry(
            what="Flood zone data is temporarily unavailable.",
            why="FEMA's mapping service isn't responding right now.",
            so_what="This check is not included in your health summary.",
        ),
        "F4": CopyEntry(
            what="FEMA flood maps don't cover this area.",
            why="Coverage is metro-based — addresses outside mapped metro areas fall outside the current dataset.",
            so_what="If you're financing a purchase, your lender may require a separate flood determination.",
        ),
    },
    "ust_proximity": {
        "F1": CopyEntry(
            what="Underground storage tank data could not be queried.",
            why="The environmental dataset encountered an error during lookup.",
            so_what="This check is not included in your health summary.",
        ),
        "F4": CopyEntry(
            what="Underground storage tank data is not available for this area.",
            why="EPA UST records have not been ingested for this state yet.",
            so_what="A Phase I environmental site assessment would cover underground storage tanks if this is a concern.",
        ),
    },
    "high_traffic_road": {
        "F1": CopyEntry(
            what="Traffic volume data could not be queried.",
            why="The federal highway dataset encountered an error during lookup.",
            so_what="This check is not included in your health summary.",
        ),
        "F4": CopyEntry(
            what="Traffic volume data is not available for this area.",
            why="Federal highway monitoring data has not been ingested for this state.",
            so_what="High-traffic roads can be assessed in person during peak commute hours.",
        ),
    },
    "power_lines": {
        "F1": CopyEntry(
            what="Transmission line data is temporarily unavailable.",
            why="The infrastructure dataset used for this check isn't responding right now.",
            so_what="This check is not included in your health summary.",
        ),
        "F4": CopyEntry(
            what="Transmission line data is not available for this area.",
            why="Federal transmission line records have not been loaded for this region.",
            so_what="High-voltage lines are visible on satellite imagery — check the map view.",
        ),
    },
    "electrical_substation": {
        "F1": CopyEntry(
            what="Electrical substation data is temporarily unavailable.",
            why="OpenStreetMap's data service isn't responding right now.",
            so_what="Substations are typically visible on satellite imagery.",
        ),
    },
    "cell_tower": {
        "F1": CopyEntry(
            what="Cell tower data is temporarily unavailable.",
            why="OpenStreetMap's data service isn't responding right now.",
            so_what="Cell towers are typically visible on satellite imagery.",
        ),
    },
    "industrial_zone": {
        "F1": CopyEntry(
            what="Industrial zone data could not be queried.",
            why="The environmental or land-use dataset encountered an error.",
            so_what="This check is not included in your health summary.",
        ),
        "F4": CopyEntry(
            what="Industrial facility data is not available for this area.",
            why="EPA Toxics Release Inventory data has not been ingested for this state.",
            so_what="Nearby industrial activity can be assessed from satellite imagery and local zoning maps.",
        ),
    },
    "tri_proximity": {
        "F1": CopyEntry(
            what="Toxic release facility data could not be queried.",
            why="The EPA TRI spatial dataset encountered an error.",
            so_what="This check is not included in your health summary.",
        ),
        "F4": CopyEntry(
            what="Toxic release facility data is not available for this area.",
            why="EPA TRI records have not been ingested for this state.",
            so_what="For properties near visible industrial sites, a Phase I environmental assessment would cover this.",
        ),
    },
    "superfund": {
        "F1": CopyEntry(
            what="Superfund site data could not be queried.",
            why="The EPA National Priorities List spatial dataset encountered an error.",
            so_what="This check is not included in your health summary.",
        ),
        "F4": CopyEntry(
            what="Superfund site data is not available for this area.",
            why="EPA NPL boundaries have not been ingested for this state.",
            so_what="Active Superfund sites are publicly listed on the EPA website by state.",
        ),
    },
    "rail_proximity": {
        "F1": CopyEntry(
            what="Rail corridor data could not be queried.",
            why="The federal rail dataset encountered an error.",
            so_what="This check is not included in your health summary.",
        ),
        "F4": CopyEntry(
            what="Rail corridor data is not available for this area.",
            why="FRA rail network data has not been ingested for this state.",
            so_what="Rail corridors are visible on satellite imagery and produce audible noise within a few hundred feet.",
        ),
    },
    "gas_station": {
        "F1": CopyEntry(
            what="Gas station proximity could not be verified.",
            why="The mapping service used for this check isn't responding.",
            so_what="Check the satellite view to inspect the immediate surroundings.",
        ),
    },
    "ejscreen": {
        "F1": CopyEntry(
            what="EPA environmental screening data is not available for this area.",
            why="EJScreen block group data has not been ingested for this census tract.",
            so_what="Area-level environmental indicators are not included in this evaluation.",
        ),
        "F2": CopyEntry(
            what="EPA environmental data for this area may be outdated.",
            why="EJScreen is refreshed annually. The current dataset reflects conditions as of {vintage_year}.",
            so_what="Indicator trends are generally stable year-to-year, but specific percentiles may shift.",
        ),
    },
    # ---------------------------------------------------------------
    # Tier 2 Dimensions (6 keys, 16 entries)
    # ---------------------------------------------------------------
    "coffee_social": {
        "F1": CopyEntry(
            what="Coffee and social spot data is temporarily unavailable.",
            why="The places service isn't responding right now.",
            so_what="This dimension is not included in your score.",
        ),
        "F3": CopyEntry(
            what="No coffee shops, cafes, or social spots found in the search area.",
            why="Residential areas outside town centers often lack dedicated third places within walking distance.",
            so_what="Newer or independent venues are sometimes missing from the index — check locally if this seems off.",
        ),
        "F5": CopyEntry(
            what="Not enough venue data to score this dimension.",
            why="Too few venues with sufficient review history were found to produce a reliable score.",
            so_what="This dimension is not included in your score.",
        ),
    },
    "provisioning": {
        "F1": CopyEntry(
            what="Grocery and daily essentials data is temporarily unavailable.",
            why="The places service isn't responding right now.",
            so_what="This dimension is not included in your score.",
        ),
        "F3": CopyEntry(
            what="No grocery stores found within the search radius.",
            why="Grocery stores tend to cluster near commercial corridors and may not be present within walking distance of every address.",
            so_what="Most residents at this distance drive for daily provisioning.",
        ),
        "F5": CopyEntry(
            what="Not enough grocery data to score this dimension.",
            why="Too few stores with sufficient review history were found to produce a reliable score.",
            so_what="This dimension is not included in your score.",
        ),
    },
    "fitness": {
        "F1": CopyEntry(
            what="Fitness facility data is temporarily unavailable.",
            why="The places service isn't responding right now.",
            so_what="This dimension is not included in your score.",
        ),
        "F3": CopyEntry(
            what="No gyms or fitness facilities found in the search area.",
            why="Gyms and fitness centers tend to cluster in commercial areas and may not be present within the search radius.",
            so_what="Home workouts or driving to a facility outside the search area are likely the primary options.",
        ),
        "F5": CopyEntry(
            what="Not enough fitness facility data to score this dimension.",
            why="Too few facilities with sufficient review history were found to produce a reliable score.",
            so_what="This dimension is not included in your score.",
        ),
    },
    "green_space": {
        "F1": CopyEntry(
            what="Park and green space data is temporarily unavailable.",
            why="The data services used for park discovery aren't responding right now.",
            so_what="This dimension is not included in your score.",
        ),
        "F3": CopyEntry(
            what="No parks or green spaces found within the search radius.",
            why="Formal parks may not exist nearby, and informal green spaces or trails are often not indexed.",
            so_what="Satellite imagery can help identify informal green spaces, trails, or preserved land nearby.",
        ),
        "F5": CopyEntry(
            what="Not enough park data to score this dimension.",
            why="Park data was found but lacked sufficient detail (boundaries, reviews) for a reliable score.",
            so_what="This dimension is not included in your score.",
        ),
    },
    "transit": {
        "F1": CopyEntry(
            what="Transit data is temporarily unavailable.",
            why="The transit data service isn't responding right now.",
            so_what="This dimension is not included in your score.",
        ),
        "F5": CopyEntry(
            what="No transit options found within walking distance.",
            why="This area does not appear to have fixed-route public transit coverage.",
            so_what="Driving will likely be the primary way to get around.",
        ),
    },
    "road_noise": {
        "F1": CopyEntry(
            what="Road noise data is temporarily unavailable.",
            why="The traffic data service isn't responding right now.",
            so_what="This dimension is not included in your score.",
        ),
        "F5": CopyEntry(
            what="Road noise could not be estimated for this area.",
            why="Traffic noise modeling requires road segment data that is not available for this state.",
            so_what="Road noise can be assessed in person — visit during weekday rush hours for a representative sample.",
        ),
    },
    # ---------------------------------------------------------------
    # User Input Gaps (5 keys, 5 entries)
    # ---------------------------------------------------------------
    "cost": {
        "input_missing": CopyEntry(
            what="Monthly cost was not provided.",
            why="No monthly housing cost was provided for this evaluation.",
            so_what="Cost is not factored into your overall score.",
        ),
    },
    "washer_dryer": {
        "input_missing": CopyEntry(
            what="Washer/dryer availability was not specified.",
            why="This information was not provided for this evaluation.",
            so_what="Check the listing details or ask the landlord directly.",
        ),
    },
    "central_air": {
        "input_missing": CopyEntry(
            what="Central air availability was not specified.",
            why="This information was not provided for this evaluation.",
            so_what="Check the listing details or ask the landlord directly.",
        ),
    },
    "square_footage": {
        "input_missing": CopyEntry(
            what="Square footage was not specified.",
            why="This information was not provided for this evaluation.",
            so_what="Verify square footage from the listing or during a tour.",
        ),
    },
    "bedrooms": {
        "input_missing": CopyEntry(
            what="Bedroom count was not specified.",
            why="This information was not provided for this evaluation.",
            so_what="Verify bedroom count from the listing or during a tour.",
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
