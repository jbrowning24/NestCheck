"""Unit tests for og_image.py — OpenGraph image generation.

Tests cover: font loading fallback, image generation with various inputs,
and error handling.
"""

from unittest.mock import patch, MagicMock

import pytest

from og_image import (
    _load_font,
    generate_og_image,
    BAND_COLORS,
    BRAND_PRIMARY,
    WIDTH,
    HEIGHT,
)


# =========================================================================
# Font loading
# =========================================================================

class TestLoadFont:
    def test_fallback_on_missing_font(self):
        """Should return a default font when the TTF file doesn't exist."""
        font = _load_font("/nonexistent/font.ttf", 42)
        assert font is not None

    @patch("og_image.ImageFont.truetype")
    def test_loads_truetype_when_available(self, mock_truetype):
        mock_font = MagicMock()
        mock_truetype.return_value = mock_font

        result = _load_font("/usr/share/fonts/test.ttf", 42)

        assert result == mock_font
        mock_truetype.assert_called_once_with("/usr/share/fonts/test.ttf", 42)


# =========================================================================
# Image generation
# =========================================================================

class TestGenerateOgImage:
    def test_returns_png_bytes(self):
        result = generate_og_image(
            address="123 Main Street, Scarsdale, NY",
            score=78,
            verdict="Strong Fit",
            band_css_class="band-strong",
        )
        assert result is not None
        assert isinstance(result, bytes)
        assert result[:4] == b"\x89PNG"  # PNG magic bytes

    def test_all_band_colors(self):
        """All defined band colors should produce valid images."""
        for band_class in BAND_COLORS:
            result = generate_og_image(
                address="Test Address",
                score=50,
                verdict="Test",
                band_css_class=band_class,
            )
            assert result is not None, f"Failed for {band_class}"

    def test_unknown_band_uses_default(self):
        result = generate_og_image(
            address="Test Address",
            score=50,
            verdict="Test",
            band_css_class="unknown-band",
        )
        assert result is not None

    def test_long_address_truncated(self):
        long_address = "A" * 100
        result = generate_og_image(
            address=long_address,
            score=50,
            verdict="Test",
            band_css_class="band-moderate",
        )
        assert result is not None

    def test_short_address(self):
        result = generate_og_image(
            address="1 Elm",
            score=99,
            verdict="Exceptional",
            band_css_class="band-exceptional",
        )
        assert result is not None

    def test_zero_score(self):
        result = generate_og_image(
            address="Test",
            score=0,
            verdict="Poor Fit",
            band_css_class="band-poor",
        )
        assert result is not None

    def test_100_score(self):
        result = generate_og_image(
            address="Test",
            score=100,
            verdict="Perfect",
            band_css_class="band-exceptional",
        )
        assert result is not None

    @patch("og_image.Image.new", side_effect=Exception("PIL error"))
    def test_failure_returns_none(self, mock_new):
        result = generate_og_image(
            address="Test",
            score=50,
            verdict="Test",
            band_css_class="band-moderate",
        )
        assert result is None
