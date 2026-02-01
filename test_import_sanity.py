"""Import sanity tests.

These lightweight tests verify that the WSGI entrypoint and core modules
can be imported without errors — the minimum bar for Railway deploys.
"""

import pytest


def test_app_module_imports():
    """The Flask app module must import without errors."""
    import app  # noqa: F401


def test_wsgi_app_object():
    """Gunicorn's 'app:app' entrypoint must resolve to a Flask instance."""
    from app import app as flask_app
    assert flask_app is not None
    assert hasattr(flask_app, "route"), "app object is not a Flask instance"


def test_property_evaluator_imports():
    """Core symbols used by app.py must be importable."""
    from property_evaluator import PropertyListing, evaluate_property, CheckResult
    assert PropertyListing is not None
    assert evaluate_property is not None
    assert CheckResult is not None


def test_green_space_imports():
    """GreenEscapeEvaluation must be importable (was the deploy crash)."""
    from green_space import GreenEscapeEvaluation, evaluate_green_escape
    assert GreenEscapeEvaluation is not None
    assert evaluate_green_escape is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
