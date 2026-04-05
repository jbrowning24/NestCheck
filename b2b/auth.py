"""API key authentication decorator for B2B partner routes."""
import hashlib
import logging
from functools import wraps
from typing import Callable

from flask import g, jsonify, request

from models import _get_db

logger = logging.getLogger(__name__)


def _auth_error(code: str, message: str, status: int):
    """Return a structured auth error response."""
    return jsonify({"error": {"code": code, "message": message, "type": "auth"}}), status


def require_api_key(f: Callable) -> Callable:
    """Decorator that validates a Bearer API key on B2B routes.

    Extracts the ``Authorization: Bearer <token>`` header, SHA-256 hashes
    the token, and looks it up in ``partner_api_keys`` joined to ``partners``.

    On success sets:
    - ``g.partner``: dict with id, name, status, monthly_quota
    - ``g.api_key``: dict with id, environment

    On failure returns a JSON error response with the appropriate HTTP status.
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return _auth_error("unauthorized", "Missing or malformed Authorization header.", 401)

        token = auth_header[len("Bearer "):]
        if not token:
            return _auth_error("unauthorized", "Missing API key.", 401)

        key_hash = hashlib.sha256(token.encode()).hexdigest()

        conn = _get_db()
        try:
            row = conn.execute(
                """
                SELECT
                    k.id        AS key_id,
                    k.environment,
                    k.revoked_at,
                    p.id        AS partner_id,
                    p.name      AS partner_name,
                    p.status    AS partner_status,
                    p.monthly_quota
                FROM partner_api_keys k
                JOIN partners p ON p.id = k.partner_id
                WHERE k.key_hash = ?
                """,
                (key_hash,),
            ).fetchone()
        finally:
            conn.close()

        if row is None:
            return _auth_error("unauthorized", "Invalid API key.", 401)

        if row["revoked_at"] is not None:
            return _auth_error("unauthorized", "API key has been revoked.", 401)

        partner_status = row["partner_status"]
        if partner_status == "suspended":
            return _auth_error("suspended", "Partner account is suspended.", 403)

        if partner_status == "revoked":
            return _auth_error("unauthorized", "Partner account has been revoked.", 401)

        if partner_status != "active":
            return _auth_error("unauthorized", "Partner account is not active.", 401)

        g.partner = {
            "id": row["partner_id"],
            "name": row["partner_name"],
            "status": partner_status,
            "monthly_quota": row["monthly_quota"],
        }
        g.api_key = {
            "id": row["key_id"],
            "environment": row["environment"],
        }

        return f(*args, **kwargs)

    return decorated
