"""Tests for curated list pages and supporting helpers."""

import json
import os
import tempfile

import pytest
from app import _prepare_snapshot_for_display, _load_list_config, _get_all_list_slugs
from models import save_snapshot


def _make_minimal_result():
    """Build a minimal result dict matching snapshot structure."""
    return {
        "address": "123 Test St, Testville, NY 10000",
        "coordinates": {"lat": 41.0, "lng": -73.7},
        "tier1_checks": [],
        "tier2_scores": [],
        "dimension_summaries": [],
        "neighborhood_places": {
            "coffee": [{"name": "Bean Co", "walk_time_min": 5, "rating": 4.5}],
            "grocery": [],
            "fitness": [],
        },
        "final_score": 72,
        "passed_tier1": True,
        "score_band": {"label": "Strong", "css_class": "band-strong"},
        "verdict": "Strong",
    }


class TestPrepareSnapshotForDisplay:
    def test_adds_presented_checks_when_missing(self):
        result = _make_minimal_result()
        assert "presented_checks" not in result
        _prepare_snapshot_for_display(result)
        assert "presented_checks" in result

    def test_idempotent(self):
        """Running the pipeline twice produces identical output."""
        result = _make_minimal_result()
        _prepare_snapshot_for_display(result)
        first_pass = json.dumps(result, sort_keys=True, default=str)

        _prepare_snapshot_for_display(result)
        second_pass = json.dumps(result, sort_keys=True, default=str)

        assert first_pass == second_pass

    def test_adds_neighborhood_summary(self):
        result = _make_minimal_result()
        _prepare_snapshot_for_display(result)
        assert "neighborhood_summary" in result
        assert result["neighborhood_summary"]["coffee_count"] == 1

    def test_adds_show_numeric_score(self):
        result = _make_minimal_result()
        _prepare_snapshot_for_display(result)
        assert "show_numeric_score" in result


def _create_test_snapshot():
    """Insert a minimal snapshot into the DB and return its auto-generated ID."""
    result = _make_minimal_result()
    snapshot_id = save_snapshot(
        address_input=result["address"],
        address_norm=result["address"],
        result_dict=result,
    )
    return snapshot_id


class TestLoadListConfig:
    def test_returns_none_for_missing_slug(self):
        assert _load_list_config("nonexistent-slug-xyz") is None

    def test_loads_valid_config(self, tmp_path):
        config = {
            "slug": "test-list",
            "title": "Test List",
            "meta_description": "A test list.",
            "intro": "This is a test.",
            "entries": [
                {"snapshot_id": "abc123", "narrative": "Great spot."}
            ],
        }
        (tmp_path / "test-list.json").write_text(json.dumps(config))
        result = _load_list_config("test-list", config_dir=str(tmp_path))
        assert result is not None
        assert result["title"] == "Test List"
        assert len(result["entries"]) == 1

    def test_returns_none_for_invalid_json(self, tmp_path):
        (tmp_path / "bad.json").write_text("{not valid json")
        assert _load_list_config("bad", config_dir=str(tmp_path)) is None

    def test_slug_rejects_path_traversal(self):
        assert _load_list_config("../etc/passwd") is None
        assert _load_list_config("foo/../../bar") is None


class TestGetAllListSlugs:
    def test_returns_slugs_from_json_files(self, tmp_path):
        (tmp_path / "alpha.json").write_text('{"slug": "alpha", "title": "A"}')
        (tmp_path / "beta.json").write_text('{"slug": "beta", "title": "B"}')
        (tmp_path / "_example.json").write_text('{"slug": "_example"}')
        slugs = _get_all_list_slugs(config_dir=str(tmp_path))
        assert "alpha" in slugs
        assert "beta" in slugs

    def test_skips_underscore_prefixed_files(self, tmp_path):
        (tmp_path / "_example.json").write_text('{"slug": "_example"}')
        slugs = _get_all_list_slugs(config_dir=str(tmp_path))
        assert "_example" not in slugs


class TestListRoute:
    def test_404_for_missing_slug(self, client):
        resp = client.get("/lists/nonexistent-slug")
        assert resp.status_code == 404

    def test_200_for_valid_list(self, client, tmp_path, monkeypatch):
        sid = _create_test_snapshot()
        config = {
            "slug": "test-walkable",
            "title": "Test Walkable List",
            "meta_description": "Test description.",
            "intro": "An intro paragraph.",
            "entries": [{"snapshot_id": sid, "narrative": "A nice place."}],
        }
        (tmp_path / "test-walkable.json").write_text(json.dumps(config))
        monkeypatch.setattr("app._LISTS_DIR", str(tmp_path))
        resp = client.get("/lists/test-walkable")
        assert resp.status_code == 200
        assert b"Test Walkable List" in resp.data

    def test_json_ld_item_list(self, client, tmp_path, monkeypatch):
        sid = _create_test_snapshot()
        config = {
            "slug": "ld-test",
            "title": "JSON-LD Test",
            "meta_description": "Test desc.",
            "intro": "Intro.",
            "entries": [{"snapshot_id": sid, "narrative": "Note."}],
        }
        (tmp_path / "ld-test.json").write_text(json.dumps(config))
        monkeypatch.setattr("app._LISTS_DIR", str(tmp_path))
        resp = client.get("/lists/ld-test")
        assert b'"@type": "ItemList"' in resp.data
        assert b'"numberOfItems": 1' in resp.data
        assert bytes(f'/s/{sid}', "utf-8") in resp.data

    def test_og_tags_from_config(self, client, tmp_path, monkeypatch):
        sid = _create_test_snapshot()
        config = {
            "slug": "og-test",
            "title": "OG Test Title",
            "meta_description": "OG test desc.",
            "intro": "Intro.",
            "entries": [{"snapshot_id": sid, "narrative": "N."}],
        }
        (tmp_path / "og-test.json").write_text(json.dumps(config))
        monkeypatch.setattr("app._LISTS_DIR", str(tmp_path))
        resp = client.get("/lists/og-test")
        assert b'og:title" content="OG Test Title"' in resp.data
        assert b'og:description" content="OG test desc."' in resp.data

    def test_related_lists_rendered(self, client, tmp_path, monkeypatch):
        sid = _create_test_snapshot()
        main_config = {
            "slug": "main-list",
            "title": "Main List",
            "meta_description": "Main.",
            "intro": "Intro.",
            "entries": [{"snapshot_id": sid, "narrative": "N."}],
            "related_lists": ["related-list"],
        }
        related_config = {
            "slug": "related-list",
            "title": "The Related List",
            "meta_description": "Related.",
            "intro": "Intro.",
            "entries": [],
        }
        (tmp_path / "main-list.json").write_text(json.dumps(main_config))
        (tmp_path / "related-list.json").write_text(json.dumps(related_config))
        monkeypatch.setattr("app._LISTS_DIR", str(tmp_path))
        resp = client.get("/lists/main-list")
        assert b"The Related List" in resp.data
        assert b"/lists/related-list" in resp.data

    def test_skips_missing_snapshots(self, client, tmp_path, monkeypatch):
        config = {
            "slug": "sparse-list",
            "title": "Sparse List",
            "meta_description": "Some missing.",
            "intro": "Intro.",
            "entries": [{"snapshot_id": "does-not-exist", "narrative": "Gone."}],
        }
        (tmp_path / "sparse-list.json").write_text(json.dumps(config))
        monkeypatch.setattr("app._LISTS_DIR", str(tmp_path))
        resp = client.get("/lists/sparse-list")
        assert resp.status_code == 200
        assert b"does-not-exist" not in resp.data

    def test_empty_list_renders(self, client, tmp_path, monkeypatch):
        """A list with zero valid entries should still render 200 with header/CTA."""
        config = {
            "slug": "empty-list",
            "title": "Empty List",
            "meta_description": "Empty.",
            "intro": "Nothing here yet.",
            "entries": [],
        }
        (tmp_path / "empty-list.json").write_text(json.dumps(config))
        monkeypatch.setattr("app._LISTS_DIR", str(tmp_path))
        resp = client.get("/lists/empty-list")
        assert resp.status_code == 200
        assert b"Empty List" in resp.data
        assert b"Evaluate your own address" in resp.data


class TestSitemap:
    def test_list_pages_in_sitemap(self, client, tmp_path, monkeypatch):
        config = {
            "slug": "sitemap-test",
            "title": "Sitemap Test List",
            "meta_description": "For sitemap test.",
            "intro": "Intro.",
            "entries": [],
        }
        (tmp_path / "sitemap-test.json").write_text(json.dumps(config))
        monkeypatch.setattr("app._LISTS_DIR", str(tmp_path))

        resp = client.get("/sitemap.xml")
        assert resp.status_code == 200
        assert b"/lists/sitemap-test" in resp.data
        assert b"<priority>0.7</priority>" in resp.data
        assert b"<changefreq>monthly</changefreq>" in resp.data
