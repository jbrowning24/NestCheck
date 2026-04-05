"""B2B API Blueprint for partner integrations."""
from flask import Blueprint
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

b2b_bp = Blueprint("b2b", __name__, url_prefix="/api/v1/b2b")

limiter = Limiter(
    key_func=get_remote_address,
    storage_uri="memory://",
    default_limits=[],  # No default — apply per-route
)

# Import routes to register them on the Blueprint.
from b2b import routes as _routes  # noqa: F401, E402
