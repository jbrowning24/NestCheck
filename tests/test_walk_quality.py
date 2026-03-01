"""Unit tests for walk_quality.py — MAPS-Mini walk quality pipeline.

Tests cover: geometry helpers, image analysis, infrastructure parsing,
scoring functions, confidence classification, and the main assessment flow.
"""

from unittest.mock import patch, MagicMock

import pytest

from walk_quality import (
    _offset_point,
    _generate_sample_points,
    _analyze_image,
    _score_sidewalks,
    _score_greenery,
    _score_lighting,
    _score_crosswalks,
    _score_buffer,
    _score_curb_cuts,
    _score_ped_signals,
    _classify_confidence,
    _walk_quality_rating,
    _walk_score_comparison,
    _build_infra_detail_query,
    _fetch_infrastructure,
    assess_walk_quality,
    GSVSamplePoint,
    InfrastructureFeatures,
    WalkQualityAssessment,
    WalkQualityFeatureScore,
    SAMPLE_DIRECTIONS,
    SAMPLE_DISTANCE_M,
    INFRA_RADIUS_M,
    WEIGHT_SIDEWALK,
    WEIGHT_GREENERY,
    WEIGHT_LIGHTING,
    WEIGHT_CROSSWALKS,
    WEIGHT_BUFFER,
    WEIGHT_CURB_CUTS,
    WEIGHT_PED_SIGNALS,
)


# =========================================================================
# Geometry helpers
# =========================================================================

class TestOffsetPoint:
    def test_north_offset(self):
        """Moving north should increase latitude."""
        lat, lng = _offset_point(40.0, -73.0, 0, 200)
        assert lat > 40.0
        assert abs(lng - (-73.0)) < 0.001

    def test_east_offset(self):
        """Moving east should increase longitude."""
        lat, lng = _offset_point(40.0, -73.0, 90, 200)
        assert abs(lat - 40.0) < 0.001
        assert lng > -73.0

    def test_south_offset(self):
        """Moving south should decrease latitude."""
        lat, lng = _offset_point(40.0, -73.0, 180, 200)
        assert lat < 40.0

    def test_distance_approximately_correct(self):
        """Offset should be approximately the requested distance."""
        import math
        lat1, lng1 = 40.0, -73.0
        lat2, lng2 = _offset_point(lat1, lng1, 0, 200)
        # Approximate distance using Haversine
        R = 6371000
        dlat = math.radians(lat2 - lat1)
        a = math.sin(dlat / 2) ** 2
        c = 2 * math.asin(math.sqrt(a))
        dist = R * c
        assert abs(dist - 200) < 5  # within 5 meters


class TestGenerateSamplePoints:
    def test_returns_8_points(self):
        points = _generate_sample_points(40.0, -73.0)
        assert len(points) == 8

    def test_each_point_has_lat_lng_heading(self):
        points = _generate_sample_points(40.0, -73.0)
        for lat, lng, heading in points:
            assert isinstance(lat, float)
            assert isinstance(lng, float)
            assert isinstance(heading, int)
            assert 0 <= heading < 360

    def test_headings_point_back_to_center(self):
        """Each sample point's heading should face back towards property."""
        points = _generate_sample_points(40.0, -73.0)
        for i, (_, _, heading) in enumerate(points):
            expected = (SAMPLE_DIRECTIONS[i] + 180) % 360
            assert heading == expected


# =========================================================================
# Image analysis
# =========================================================================

class TestAnalyzeImage:
    def test_returns_zero_for_empty_image(self):
        """Should handle cases where Pillow can't decode."""
        result = _analyze_image(b"not an image")
        assert result["greenery_pct"] == 0.0
        assert result["sky_pct"] == 0.0
        assert result["brightness"] == 0.0

    def test_green_image(self):
        """A mostly-green image should report high greenery."""
        try:
            from PIL import Image
        except ImportError:
            pytest.skip("Pillow not installed")

        import io
        # Create a 100x100 green image (RGB)
        img = Image.new("RGB", (100, 100), color=(34, 139, 34))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        buf.seek(0)

        result = _analyze_image(buf.getvalue())
        assert result["greenery_pct"] > 50

    def test_dark_image_low_brightness(self):
        """A dark image should have low brightness."""
        try:
            from PIL import Image
        except ImportError:
            pytest.skip("Pillow not installed")

        import io
        img = Image.new("RGB", (100, 100), color=(10, 10, 10))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        buf.seek(0)

        result = _analyze_image(buf.getvalue())
        assert result["brightness"] < 50

    def test_bright_image_high_brightness(self):
        """A bright white image should have high brightness."""
        try:
            from PIL import Image
        except ImportError:
            pytest.skip("Pillow not installed")

        import io
        img = Image.new("RGB", (100, 100), color=(240, 240, 240))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        buf.seek(0)

        result = _analyze_image(buf.getvalue())
        assert result["brightness"] > 200


# =========================================================================
# Scoring functions
# =========================================================================

class TestScoreSidewalks:
    def test_none_returns_zero(self):
        score = _score_sidewalks(None, None)
        assert score.score == 0
        assert score.feature == "Sidewalk Coverage"

    def test_high_coverage(self):
        score = _score_sidewalks(80.0, "HIGH")
        assert score.score == 100

    def test_medium_coverage(self):
        score = _score_sidewalks(40.0, "MEDIUM")
        assert 40 <= score.score <= 60

    def test_zero_coverage(self):
        score = _score_sidewalks(0.0, "LOW")
        assert score.score == 0

    def test_weight_correct(self):
        score = _score_sidewalks(50.0, "HIGH")
        assert score.weight == WEIGHT_SIDEWALK / 100


class TestScoreGreenery:
    def test_no_gsv(self):
        score = _score_greenery(15.0, False)
        assert score.score == 0
        assert "No Street View" in score.detail

    def test_excellent_canopy(self):
        score = _score_greenery(30.0, True)
        assert score.score == 100

    def test_moderate_canopy(self):
        score = _score_greenery(15.0, True)
        assert 60 <= score.score <= 100

    def test_sparse_canopy(self):
        score = _score_greenery(5.0, True)
        assert 20 <= score.score <= 40

    def test_minimal_canopy(self):
        score = _score_greenery(1.0, True)
        assert score.score < 10


class TestScoreLighting:
    def test_osm_only(self):
        score = _score_lighting(20, 0, False)
        assert score.score == 50  # max from OSM alone

    def test_combined(self):
        score = _score_lighting(20, 150, True)
        assert score.score > 50  # OSM + GSV

    def test_no_data(self):
        score = _score_lighting(0, 0, False)
        assert score.score == 0


class TestScoreCrosswalks:
    def test_zero(self):
        assert _score_crosswalks(0).score == 0

    def test_few(self):
        score = _score_crosswalks(3)
        assert 10 < score.score < 50

    def test_many(self):
        score = _score_crosswalks(15)
        assert score.score == 100


class TestScoreBuffer:
    def test_no_gsv(self):
        score = _score_buffer(50, 20, False)
        assert score.score == 0

    def test_good_enclosure(self):
        """Low sky + high greenery = good buffer."""
        score = _score_buffer(20, 25, True)
        assert score.score >= 70

    def test_exposed(self):
        """High sky + low greenery = poor buffer."""
        score = _score_buffer(80, 2, True)
        assert score.score < 30


class TestScoreCurbCuts:
    def test_zero(self):
        assert _score_curb_cuts(0).score == 0

    def test_many(self):
        assert _score_curb_cuts(10).score == 100


class TestScorePedSignals:
    def test_zero(self):
        assert _score_ped_signals(0).score == 0

    def test_one(self):
        assert _score_ped_signals(1).score == 20

    def test_many(self):
        assert _score_ped_signals(5).score == 100


# =========================================================================
# Confidence classification
# =========================================================================

class TestClassifyConfidence:
    def test_high_confidence(self):
        infra = InfrastructureFeatures(
            crosswalk_count=5, streetlight_count=8, curb_cut_count=3,
            ped_signal_count=2, bench_count=2, total_features=20,
        )
        level, note = _classify_confidence(7, 8, infra)
        assert level == "HIGH"

    def test_medium_confidence_gsv_only(self):
        level, note = _classify_confidence(5, 8, None)
        assert level == "MEDIUM"

    def test_medium_confidence_osm_only(self):
        infra = InfrastructureFeatures(
            crosswalk_count=2, streetlight_count=4, curb_cut_count=1,
            ped_signal_count=1, bench_count=2, total_features=10,
        )
        level, note = _classify_confidence(0, 8, infra)
        assert level in ("MEDIUM", "HIGH")

    def test_low_confidence(self):
        level, note = _classify_confidence(0, 8, None)
        assert level == "LOW"

    def test_low_with_zero_sample_points(self):
        level, note = _classify_confidence(0, 0, None)
        assert level == "LOW"


# =========================================================================
# Rating
# =========================================================================

class TestWalkQualityRating:
    def test_excellent(self):
        assert _walk_quality_rating(85) == "Excellent"

    def test_good(self):
        assert _walk_quality_rating(65) == "Good"

    def test_fair(self):
        assert _walk_quality_rating(45) == "Fair"

    def test_poor(self):
        assert _walk_quality_rating(20) == "Poor"


# =========================================================================
# Walk Score comparison
# =========================================================================

class TestWalkScoreComparison:
    def test_none_walk_score(self):
        assert _walk_score_comparison(70, None) is None

    def test_aligned(self):
        result = _walk_score_comparison(70, 72)
        assert "aligns" in result

    def test_quality_exceeds(self):
        result = _walk_score_comparison(80, 50)
        assert "exceeds" in result

    def test_quality_lower(self):
        result = _walk_score_comparison(40, 70)
        assert "lower" in result


# =========================================================================
# Weights sum to 100
# =========================================================================

class TestWeights:
    def test_weights_sum_to_100(self):
        total = (
            WEIGHT_SIDEWALK + WEIGHT_GREENERY + WEIGHT_LIGHTING +
            WEIGHT_CROSSWALKS + WEIGHT_BUFFER + WEIGHT_CURB_CUTS +
            WEIGHT_PED_SIGNALS
        )
        assert total == 100


# =========================================================================
# Infrastructure query
# =========================================================================

class TestInfrastructureQuery:
    def test_query_contains_tags(self):
        query = _build_infra_detail_query(40.0, -73.0, 500)
        assert "highway" in query
        assert "crossing" in query
        assert "street_lamp" in query
        assert "kerb" in query
        assert "tactile_paving" in query
        assert "traffic_signals" in query
        assert "bench" in query

    @patch("overpass_http.overpass_query")
    def test_fetch_infrastructure_counts(self, mock_overpass):
        mock_overpass.return_value = {
            "elements": [
                {"type": "node", "tags": {"highway": "crossing"}},
                {"type": "node", "tags": {"highway": "crossing"}},
                {"type": "node", "tags": {"highway": "street_lamp"}},
                {"type": "node", "tags": {"kerb": "lowered"}},
                {"type": "node", "tags": {"crossing": "traffic_signals"}},
                {"type": "node", "tags": {"amenity": "bench"}},
            ]
        }
        result = _fetch_infrastructure(40.0, -73.0)
        assert result is not None
        assert result.crosswalk_count == 2
        assert result.streetlight_count == 1
        assert result.curb_cut_count == 1
        assert result.ped_signal_count == 1
        assert result.bench_count == 1
        assert result.total_features == 6

    @patch("overpass_http.overpass_query", side_effect=Exception("network"))
    def test_fetch_infrastructure_failure(self, mock_overpass):
        result = _fetch_infrastructure(40.0, -73.0)
        assert result is None


# =========================================================================
# Main assessment flow
# =========================================================================

class TestAssessWalkQuality:
    @patch("walk_quality._fetch_infrastructure")
    @patch("walk_quality._gsv_image")
    @patch("walk_quality._gsv_metadata")
    def test_full_pipeline_with_gsv(self, mock_meta, mock_image, mock_infra):
        """Full pipeline with GSV imagery available."""
        try:
            from PIL import Image
        except ImportError:
            pytest.skip("Pillow not installed")

        import io

        # Mock GSV metadata — all points have coverage
        mock_meta.return_value = {"status": "OK", "date": "2025-06"}

        # Mock GSV image — a green+bright image
        img = Image.new("RGB", (100, 100), color=(80, 180, 80))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        mock_image.return_value = buf.getvalue()

        # Mock infrastructure
        mock_infra.return_value = InfrastructureFeatures(
            crosswalk_count=10, streetlight_count=15, curb_cut_count=5,
            ped_signal_count=3, bench_count=4, total_features=37,
        )

        result = assess_walk_quality(
            lat=40.9, lng=-73.8, api_key="test-key",
            sidewalk_pct=65.0, sidewalk_confidence="HIGH",
            walk_score=72,
        )

        assert result is not None
        assert isinstance(result, WalkQualityAssessment)
        assert 0 <= result.walk_quality_score <= 100
        assert result.walk_quality_rating in ("Excellent", "Good", "Fair", "Poor")
        assert len(result.feature_scores) == 7
        assert result.sample_points_total == 8
        assert result.sample_points_with_coverage == 8
        assert result.gsv_available is True
        assert result.data_confidence in ("HIGH", "MEDIUM", "LOW")
        assert result.walk_score_comparison is not None

    @patch("walk_quality._fetch_infrastructure")
    @patch("walk_quality._gsv_image")
    @patch("walk_quality._gsv_metadata")
    def test_pipeline_without_gsv(self, mock_meta, mock_image, mock_infra):
        """Pipeline should work with no GSV imagery (OSM only)."""
        mock_meta.return_value = None
        mock_image.return_value = None

        mock_infra.return_value = InfrastructureFeatures(
            crosswalk_count=5, streetlight_count=8, curb_cut_count=2,
            ped_signal_count=1, bench_count=3, total_features=19,
        )

        result = assess_walk_quality(
            lat=40.9, lng=-73.8, api_key="test-key",
            sidewalk_pct=50.0, sidewalk_confidence="MEDIUM",
        )

        assert result is not None
        assert result.gsv_available is False
        assert result.sample_points_with_coverage == 0
        # GSV-dependent features should be 0
        gsv_features = [
            fs for fs in result.feature_scores if fs.source == "GSV"
        ]
        for fs in gsv_features:
            assert fs.score == 0

    @patch("walk_quality._fetch_infrastructure")
    @patch("walk_quality._gsv_image")
    @patch("walk_quality._gsv_metadata")
    def test_pipeline_without_osm(self, mock_meta, mock_image, mock_infra):
        """Pipeline should work with no OSM data (GSV only)."""
        try:
            from PIL import Image
        except ImportError:
            pytest.skip("Pillow not installed")

        import io

        mock_meta.return_value = {"status": "OK", "date": "2025-06"}
        img = Image.new("RGB", (100, 100), color=(80, 180, 80))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        mock_image.return_value = buf.getvalue()
        mock_infra.return_value = None

        result = assess_walk_quality(
            lat=40.9, lng=-73.8, api_key="test-key",
        )

        assert result is not None
        assert result.gsv_available is True
        # OSM features should be 0 scored
        assert result.infrastructure is None

    @patch("walk_quality._fetch_infrastructure")
    @patch("walk_quality._gsv_image")
    @patch("walk_quality._gsv_metadata")
    def test_score_bounded_0_100(self, mock_meta, mock_image, mock_infra):
        """Score should always be between 0 and 100."""
        mock_meta.return_value = None
        mock_image.return_value = None
        mock_infra.return_value = None

        result = assess_walk_quality(
            lat=40.9, lng=-73.8, api_key="test-key",
        )
        assert 0 <= result.walk_quality_score <= 100

    @patch("walk_quality._fetch_infrastructure")
    @patch("walk_quality._gsv_image")
    @patch("walk_quality._gsv_metadata")
    def test_feature_weights_sum_correctly(self, mock_meta, mock_image, mock_infra):
        """Feature weights should sum to 1.0."""
        mock_meta.return_value = None
        mock_image.return_value = None
        mock_infra.return_value = InfrastructureFeatures(
            crosswalk_count=0, streetlight_count=0, curb_cut_count=0,
            ped_signal_count=0, bench_count=0, total_features=0,
        )

        result = assess_walk_quality(
            lat=40.9, lng=-73.8, api_key="test-key",
        )
        total_weight = sum(fs.weight for fs in result.feature_scores)
        assert abs(total_weight - 1.0) < 0.01
