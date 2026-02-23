"""OpenGraph image generator for NestCheck snapshots.

Generates a 1200x630 branded card showing:
  - NestCheck logo text
  - Property address
  - Score number with band color
  - Verdict text
"""

import io
import logging
from typing import Optional

from PIL import Image, ImageDraw, ImageFont

logger = logging.getLogger(__name__)

# Score band colors — mirrors tokens.css
BAND_COLORS = {
    "band-exceptional": "#059669",
    "band-strong": "#16a34a",
    "band-moderate": "#eab308",
    "band-limited": "#f97316",
    "band-poor": "#ef4444",
}

BRAND_PRIMARY = "#0f3460"
SURFACE_WHITE = "#ffffff"
TEXT_MUTED = "#475569"
TEXT_FAINT = "#888888"

WIDTH = 1200
HEIGHT = 630

# Font paths (DejaVu is standard on Linux)
_FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
_FONT_REGULAR = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"


def _load_font(path: str, size: int) -> ImageFont.FreeTypeFont:
    """Load a TrueType font, falling back to Pillow default on error."""
    try:
        return ImageFont.truetype(path, size)
    except (OSError, IOError):
        logger.warning("Font %s not found, using default bitmap font", path)
        return ImageFont.load_default()


def generate_og_image(
    address: str,
    score: int,
    verdict: str,
    band_css_class: str,
) -> Optional[bytes]:
    """Return PNG bytes for the OG image card, or None on failure."""
    try:
        band_color = BAND_COLORS.get(band_css_class, BRAND_PRIMARY)

        img = Image.new("RGB", (WIDTH, HEIGHT), SURFACE_WHITE)
        draw = ImageDraw.Draw(img)

        # Left accent strip
        draw.rectangle([0, 0, 10, HEIGHT], fill=band_color)

        # Fonts
        font_brand = _load_font(_FONT_BOLD, 42)
        font_address = _load_font(_FONT_REGULAR, 28)
        font_score = _load_font(_FONT_BOLD, 140)
        font_verdict = _load_font(_FONT_REGULAR, 32)
        font_footer = _load_font(_FONT_REGULAR, 22)

        # "NestCheck" brand text — top-left
        draw.text((60, 40), "NestCheck", fill=BRAND_PRIMARY, font=font_brand)

        # Address — below brand, truncated if too long
        display_address = address if len(address) <= 60 else address[:57] + "..."
        draw.text((60, 100), display_address, fill=TEXT_MUTED, font=font_address)

        # Score number — centered, large
        score_text = str(score)
        score_bbox = draw.textbbox((0, 0), score_text, font=font_score)
        score_w = score_bbox[2] - score_bbox[0]
        score_x = (WIDTH - score_w) // 2
        score_y = 190
        draw.text((score_x, score_y), score_text, fill=band_color, font=font_score)

        # "/100" label — right of score
        label_font = _load_font(_FONT_REGULAR, 48)
        label_x = score_x + score_w + 8
        label_y = score_y + 90  # baseline-align with score
        draw.text((label_x, label_y), "/100", fill=TEXT_FAINT, font=label_font)

        # Verdict — centered below score
        verdict_bbox = draw.textbbox((0, 0), verdict, font=font_verdict)
        verdict_w = verdict_bbox[2] - verdict_bbox[0]
        verdict_x = (WIDTH - verdict_w) // 2
        draw.text((verdict_x, 400), verdict, fill=TEXT_MUTED, font=font_verdict)

        # Bottom-right: subtle domain
        draw.text((WIDTH - 250, HEIGHT - 50), "nestcheck.app", fill=TEXT_FAINT, font=font_footer)

        # Bottom border accent
        draw.rectangle([0, HEIGHT - 6, WIDTH, HEIGHT], fill=band_color)

        buf = io.BytesIO()
        img.save(buf, format="PNG", optimize=True)
        return buf.getvalue()

    except Exception:
        logger.exception("Failed to generate OG image")
        return None
