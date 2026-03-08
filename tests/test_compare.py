"""Tests for the /compare route — side-by-side comparison of 2-4 snapshots."""

import json
import pytest

from app import _build_comparative_verdict, _short_address
from models import save_snapshot


def _make_fake_result(address: str, score: int, verdict: str) -> dict:
    """Minimal result dict for snapshot creation."""
    return {
        "address": address,
        "final_score": score,
        "passed_tier1": True,
        "verdict": verdict,
        "tier2_score": 40,
        "tier2_max": 60,
        "tier2_normalized": 67,
        "tier3_bonus": 5,
        "tier2_scores": [
            {"name": "Parks & Green Space", "points": 7, "max": 10, "details": ""},
            {"name": "Getting Around", "points": 6, "max": 10, "details": ""},
        ],
        "tier1_checks": [
            {"name": "Highway buffer", "result": "PASS", "details": "", "required": True},
        ],
        "coordinates": {"lat": 30.0, "lng": -97.0},
        "walk_scores": {"walk_score": 65, "transit_score": 40, "bike_score": 55},
    }


@pytest.fixture
def two_snapshots():
    """Create two snapshots for comparison tests."""
    id1 = save_snapshot(
        address_input="123 First St",
        address_norm="123 First St, Austin, TX",
        result_dict=_make_fake_result("123 First St, Austin, TX", 72, "Strong match"),
    )
    id2 = save_snapshot(
        address_input="456 Second Ave",
        address_norm="456 Second Ave, Austin, TX",
        result_dict=_make_fake_result("456 Second Ave, Austin, TX", 58, "Moderate match"),
    )
    return id1, id2


class TestCompareRoute:
    def test_compare_two_valid_snapshots_renders(self, client, two_snapshots):
        id1, id2 = two_snapshots
        resp = client.get(f"/compare?ids={id1},{id2}")
        assert resp.status_code == 200
        body = resp.data.decode()
        assert "Compare Addresses" in body
        assert "123 First St" in body
        assert "456 Second Ave" in body
        assert "72" in body
        assert "58" in body

    def test_compare_renders_verdict_card(self, client, two_snapshots):
        """Verdict card appears in the rendered compare page."""
        id1, id2 = two_snapshots
        resp = client.get(f"/compare?ids={id1},{id2}")
        assert resp.status_code == 200
        body = resp.data.decode()
        assert "compare-verdict" in body
        assert "compare-verdict__headline" in body

    def test_compare_empty_ids_redirects(self, client):
        resp = client.get("/compare?ids=", follow_redirects=True)
        body = resp.data.decode()
        assert "Select at least two addresses" in body

    def test_compare_single_id_redirects(self, client, two_snapshots):
        id1, _ = two_snapshots
        resp = client.get(f"/compare?ids={id1}", follow_redirects=True)
        body = resp.data.decode()
        assert "Select at least two addresses" in body

    def test_compare_five_ids_redirects(self, client, two_snapshots):
        id1, id2 = two_snapshots
        resp = client.get(f"/compare?ids={id1},{id2},a,b,c", follow_redirects=True)
        body = resp.data.decode()
        assert "You can compare up to four" in body

    def test_compare_one_valid_one_invalid_redirects(self, client, two_snapshots):
        id1, _ = two_snapshots
        resp = client.get(f"/compare?ids={id1},nonexistent999", follow_redirects=True)
        # Only one valid — should redirect (need at least 2)
        body = resp.data.decode()
        assert "no longer available" in body

    def test_compare_deduplicates_ids(self, client, two_snapshots):
        id1, id2 = two_snapshots
        resp = client.get(f"/compare?ids={id1},{id2},{id1}")
        assert resp.status_code == 200
        body = resp.data.decode()
        assert "Compare Addresses" in body
        # Should show 2 evaluations (deduped) — both addresses appear once each
        assert "123 First St" in body
        assert "456 Second Ave" in body

    def test_compare_all_stale_ids_shows_helpful_error(self, client):
        """When all IDs in the compare list are stale (DB wiped), show actionable message."""
        resp = client.get("/compare?ids=gone1,gone2", follow_redirects=True)
        body = resp.data.decode()
        assert "no longer available" in body
        assert "re-evaluate" in body

    def test_compare_two_valid_one_stale_still_works(self, client, two_snapshots):
        """If one ID is stale but two are valid, comparison should still render."""
        id1, id2 = two_snapshots
        resp = client.get(f"/compare?ids={id1},{id2},gone999")
        assert resp.status_code == 200
        body = resp.data.decode()
        assert "Compare Addresses" in body
        assert "123 First St" in body
        assert "456 Second Ave" in body


class TestCheckSnapshotsAPI:
    """Tests for /api/snapshots/check — client-side ID validation."""

    def test_check_returns_valid_and_invalid(self, client, two_snapshots):
        id1, id2 = two_snapshots
        resp = client.post(
            "/api/snapshots/check",
            data=json.dumps({"ids": [id1, "nonexistent", id2]}),
            content_type="application/json",
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert set(data["valid"]) == {id1, id2}
        assert data["invalid"] == ["nonexistent"]

    def test_check_all_stale(self, client):
        resp = client.post(
            "/api/snapshots/check",
            data=json.dumps({"ids": ["gone1", "gone2"]}),
            content_type="application/json",
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["valid"] == []
        assert set(data["invalid"]) == {"gone1", "gone2"}

    def test_check_empty_list(self, client):
        resp = client.post(
            "/api/snapshots/check",
            data=json.dumps({"ids": []}),
            content_type="application/json",
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["valid"] == []
        assert data["invalid"] == []

    def test_check_rejects_oversized_list(self, client):
        resp = client.post(
            "/api/snapshots/check",
            data=json.dumps({"ids": [f"id{i}" for i in range(11)]}),
            content_type="application/json",
        )
        assert resp.status_code == 400


# ── Helpers for verdict unit tests ──────────────────────────────────


def _make_eval(
    address: str,
    score: int,
    passed_tier1: bool = True,
    tier1_checks: list = None,
    tier2_scores: list = None,
) -> dict:
    """Build a minimal evaluation dict for _build_comparative_verdict."""
    if tier1_checks is None:
        tier1_checks = [
            {"name": "Highway buffer", "result": "PASS", "details": "", "required": True},
        ]
    if tier2_scores is None:
        tier2_scores = []
    return {
        "address": address,
        "final_score": score,
        "result": {
            "passed_tier1": passed_tier1,
            "tier1_checks": tier1_checks,
            "tier2_scores": tier2_scores,
        },
    }


def _empty_health_grid() -> dict:
    return {"rows": [], "has_any_issues": False}


def _health_grid_with_rows(rows: list) -> dict:
    has_issues = any(
        c in ("FAIL", "WARNING")
        for row in rows
        for c in row.get("cells", [])
        if c is not None
    )
    return {"rows": rows, "has_any_issues": has_issues}


class TestShortAddress:
    def test_extracts_street(self):
        assert _short_address("123 Main St, Scarsdale, NY 10583") == "123 Main St"

    def test_no_comma(self):
        assert _short_address("123 Main St") == "123 Main St"

    def test_empty(self):
        assert _short_address("") == "Address"


class TestComparativeVerdict:
    """Unit tests for _build_comparative_verdict — all 6 branches + edge cases."""

    def test_single_eval_returns_none(self):
        ev = _make_eval("123 Main St, Town, NY", 72)
        result = _build_comparative_verdict([ev], _empty_health_grid(), [], [])
        assert result is None

    def test_tier1_failure_split(self):
        """Branch 1: One address failed tier1, the other passed."""
        ev_pass = _make_eval("123 Main St, Town, NY", 72)
        ev_fail = _make_eval(
            "456 Oak Ave, Town, NY",
            40,
            passed_tier1=False,
            tier1_checks=[
                {"name": "Flood zone", "result": "FAIL", "details": "", "required": True},
                {"name": "Highway buffer", "result": "PASS", "details": "", "required": True},
            ],
        )
        grid = _empty_health_grid()
        result = _build_comparative_verdict([ev_pass, ev_fail], grid, [], [])
        assert result is not None
        assert "did not pass" in result["headline"]
        assert "456 Oak Ave" in result["headline"]
        assert "Flood zone" in result["body"]
        assert "123 Main St" in result["body"]

    def test_all_tier1_failed(self):
        """Branch 1 sub-case: All addresses failed tier1."""
        ev1 = _make_eval("123 Main St, Town, NY", 30, passed_tier1=False)
        ev2 = _make_eval("456 Oak Ave, Town, NY", 25, passed_tier1=False)
        grid = _empty_health_grid()
        result = _build_comparative_verdict([ev1, ev2], grid, [], [])
        assert result is not None
        assert "None of these" in result["headline"]

    def test_health_disparity(self):
        """Branch 2: Both pass tier1, but one has many more health flags."""
        ev1 = _make_eval("123 Main St, Town, NY", 70)
        ev2 = _make_eval("456 Oak Ave, Town, NY", 68)
        grid = _health_grid_with_rows([
            {"label": "Flood zone", "cells": ["PASS", "FAIL"]},
            {"label": "Power lines", "cells": ["PASS", "WARNING"]},
            {"label": "Gas station", "cells": ["PASS", "FAIL"]},
        ])
        result = _build_comparative_verdict([ev1, ev2], grid, [], [])
        assert result is not None
        assert "cleanest health profile" in result["headline"]
        assert "123 Main St" in result["headline"]
        assert "456 Oak Ave" in result["body"]

    def test_clear_winner(self):
        """Branch 3: Spread >= 10, no health disparity."""
        ev1 = _make_eval("123 Main St, Town, NY", 85)
        ev2 = _make_eval("456 Oak Ave, Town, NY", 60)
        grid = _empty_health_grid()
        diffs = [
            {
                "dimension": "Parks & Green Space",
                "high": 9, "high_address": "123 Main St, Town, NY",
                "low": 4, "low_address": "456 Oak Ave, Town, NY",
                "gap": 5,
            },
        ]
        result = _build_comparative_verdict([ev1, ev2], grid, diffs, [])
        assert result is not None
        assert "stronger choice" in result["headline"]
        assert "123 Main St" in result["headline"]
        assert "Parks" in result["body"]

    def test_clear_winner_no_key_diffs(self):
        """Branch 3 without key_differences falls back to generic body."""
        ev1 = _make_eval("123 Main St, Town, NY", 85)
        ev2 = _make_eval("456 Oak Ave, Town, NY", 60)
        result = _build_comparative_verdict(
            [ev1, ev2], _empty_health_grid(), [], [],
        )
        assert result is not None
        assert "stronger choice" in result["headline"]
        assert "85" in result["body"]
        assert "60" in result["body"]

    def test_all_similar(self):
        """Branch 6: Spread <= 3."""
        ev1 = _make_eval("123 Main St, Town, NY", 72)
        ev2 = _make_eval("456 Oak Ave, Town, NY", 71)
        grid = _empty_health_grid()
        result = _build_comparative_verdict([ev1, ev2], grid, [], [])
        assert result is not None
        assert "essentially equivalent" in result["headline"]

    def test_close_race(self):
        """Branch 4: Spread 4-5 points."""
        ev1 = _make_eval("123 Main St, Town, NY", 74)
        ev2 = _make_eval("456 Oak Ave, Town, NY", 70)
        grid = _empty_health_grid()
        dim_rows = [
            {"name": "Parks & Green Space", "scores": [8, 6], "max_score": 10, "best_index": 0, "all_tied": False},
            {"name": "Getting Around", "scores": [5, 7], "max_score": 10, "best_index": 1, "all_tied": False},
        ]
        result = _build_comparative_verdict([ev1, ev2], grid, [], dim_rows)
        assert result is not None
        assert "closely matched" in result["headline"]
        assert "Parks" in result["body"] or "Getting Around" in result["body"]

    def test_middle_ground(self):
        """Branch 5: Spread 6-9 points."""
        ev1 = _make_eval("123 Main St, Town, NY", 77)
        ev2 = _make_eval("456 Oak Ave, Town, NY", 68)
        grid = _empty_health_grid()
        diffs = [
            {
                "dimension": "Daily Essentials",
                "high": 8, "high_address": "123 Main St, Town, NY",
                "low": 4, "low_address": "456 Oak Ave, Town, NY",
                "gap": 4,
            },
        ]
        result = _build_comparative_verdict([ev1, ev2], grid, diffs, [])
        assert result is not None
        assert "has an edge" in result["headline"]
        assert "123 Main St" in result["headline"]
        assert "Daily Essentials" in result["body"]

    def test_three_evals_one_failed_tier1(self):
        """Multi-address: one failed, two passed."""
        ev1 = _make_eval("123 Main St, Town, NY", 75)
        ev2 = _make_eval("456 Oak Ave, Town, NY", 70)
        ev3 = _make_eval(
            "789 Elm Dr, Town, NY",
            30,
            passed_tier1=False,
            tier1_checks=[
                {"name": "Flood zone", "result": "FAIL", "details": "", "required": True},
            ],
        )
        grid = _empty_health_grid()
        result = _build_comparative_verdict([ev1, ev2, ev3], grid, [], [])
        assert result is not None
        assert "did not pass" in result["headline"]
        assert "789 Elm Dr" in result["headline"]
        assert "123 Main St" in result["body"]
        assert "456 Oak Ave" in result["body"]

    def test_three_evals_multiple_failed_tier1(self):
        """Multi-address: two failed, one passed."""
        ev1 = _make_eval("123 Main St, Town, NY", 75)
        ev2 = _make_eval("456 Oak Ave, Town, NY", 30, passed_tier1=False)
        ev3 = _make_eval("789 Elm Dr, Town, NY", 25, passed_tier1=False)
        grid = _empty_health_grid()
        result = _build_comparative_verdict([ev1, ev2, ev3], grid, [], [])
        assert result is not None
        assert "Multiple addresses" in result["headline"]
        assert "123 Main St" in result["body"]

    def test_close_race_no_dimension_leaders(self):
        """Close race with all dimensions tied falls back to generic body."""
        ev1 = _make_eval("123 Main St, Town, NY", 74)
        ev2 = _make_eval("456 Oak Ave, Town, NY", 70)
        dim_rows = [
            {"name": "Parks", "scores": [7, 7], "max_score": 10, "best_index": None, "all_tied": True},
        ]
        result = _build_comparative_verdict(
            [ev1, ev2], _empty_health_grid(), [], dim_rows,
        )
        assert result is not None
        assert "closely matched" in result["headline"]
        assert "personal priorities" in result["body"]
