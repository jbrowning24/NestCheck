"""Server-side neighborhood map generation using staticmap + OSM tiles."""

import io
import base64
import logging
from typing import Optional, Dict, List

from staticmap import StaticMap, CircleMarker

logger = logging.getLogger(__name__)

USER_AGENT = "NestCheck/1.0 (address evaluation tool; contact@nestcheck.com)"

CATEGORY_COLORS = {
    "coffee": "#92400e",   # brown
    "grocery": "#15803d",  # green
    "fitness": "#7c3aed",  # purple
    "parks": "#166534",    # dark green
}

TRANSIT_COLOR = "#ea580c"  # orange


def generate_neighborhood_map(
    property_lat: float,
    property_lng: float,
    neighborhood_places: dict,
    transit_lat: Optional[float] = None,
    transit_lng: Optional[float] = None,
    width: int = 640,
    height: int = 400,
) -> Optional[str]:
    """Generate a static neighborhood map as a base64-encoded PNG string.

    Returns a base64 string (no data URI prefix) or None if generation
    fails for any reason.
    """
    try:
        m = StaticMap(
            width,
            height,
            url_template="http://a.tile.openstreetmap.org/{z}/{x}/{y}.png",
            tile_request_timeout=10,
            headers={"User-Agent": USER_AGENT},
        )

        # Property pin — blue, prominent (note: staticmap uses lng, lat order)
        m.add_marker(CircleMarker((property_lng, property_lat), "#2563eb", 14))
        m.add_marker(CircleMarker((property_lng, property_lat), "white", 10))

        # POI markers by category
        if neighborhood_places:
            for category, places in neighborhood_places.items():
                color = CATEGORY_COLORS.get(category, "#6b7280")
                for place in (places or []):
                    lat = place.get("lat")
                    lng = place.get("lng")
                    if lat is None or lng is None:
                        continue
                    m.add_marker(CircleMarker((lng, lat), color, 8))

        # Transit stop marker
        if transit_lat is not None and transit_lng is not None:
            m.add_marker(CircleMarker((transit_lng, transit_lat), TRANSIT_COLOR, 10))

        image = m.render()
        buffer = io.BytesIO()
        image.save(buffer, format="PNG", optimize=True)
        buffer.seek(0)
        return base64.b64encode(buffer.read()).decode("utf-8")

    except Exception:
        logger.exception("Failed to generate neighborhood map")
        return None
