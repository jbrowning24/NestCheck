"""Tests for the scoring key context builder."""
from app import _build_score_bands_context


def test_build_score_bands_context_returns_five_bands():
    bands = _build_score_bands_context()
    assert len(bands) == 5


def test_build_score_bands_context_band_structure():
    bands = _build_score_bands_context()
    for band in bands:
        assert "threshold" in band
        assert "upper_bound" in band
        assert "label" in band
        assert "css_class" in band
        assert "description" in band


def test_build_score_bands_context_upper_bounds():
    bands = _build_score_bands_context()
    assert bands[0]["upper_bound"] == 100
    assert bands[0]["threshold"] == 85
    for i in range(1, len(bands)):
        assert bands[i]["upper_bound"] == bands[i - 1]["threshold"] - 1


def test_build_score_bands_context_ranges_no_gaps_no_overlaps():
    bands = _build_score_bands_context()
    for i in range(len(bands) - 1):
        assert bands[i]["threshold"] == bands[i + 1]["upper_bound"] + 1


def test_build_score_bands_context_last_band_starts_at_zero():
    bands = _build_score_bands_context()
    assert bands[-1]["threshold"] == 0


def test_build_score_bands_context_descriptions_not_empty():
    bands = _build_score_bands_context()
    for band in bands:
        assert len(band["description"]) > 0


def test_build_score_bands_context_exact_thresholds():
    bands = _build_score_bands_context()
    thresholds = [b["threshold"] for b in bands]
    assert thresholds == [85, 70, 55, 40, 0]
