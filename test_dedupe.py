import importlib
import sqlite3
from datetime import datetime, timedelta, timezone


def _load_app(monkeypatch, tmp_path, *, builder=False, ttl_days="90"):
    db_path = str(tmp_path / "test.db")
    monkeypatch.setenv("NESTCHECK_DB_PATH", db_path)
    monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "test-key")
    monkeypatch.setenv("SNAPSHOT_TTL_DAYS", ttl_days)
    monkeypatch.setenv("BUILDER_MODE", "true" if builder else "false")

    import models
    import app as app_module

    importlib.reload(models)
    importlib.reload(app_module)

    app_module.app.config["TESTING"] = True
    return app_module, models


def _result(final_score=72, verdict="Strong daily-life match", passed_tier1=True):
    return {
        "address": "123 Test St, Testville, TX 12345",
        "final_score": final_score,
        "passed_tier1": passed_tier1,
        "verdict": verdict,
        "tier2_score": 40,
        "tier2_max": 60,
        "tier2_normalized": 67,
        "tier3_bonus": 5,
        "tier2_scores": [],
        "tier1_checks": [],
        "coordinates": {"lat": 30.0, "lng": -97.0},
        "walk_scores": {},
    }


def test_fresh_duplicate_reuses_existing_snapshot(monkeypatch, tmp_path):
    app_module, models = _load_app(monkeypatch, tmp_path, ttl_days="90")
    now = datetime.now(timezone.utc).isoformat()
    snapshot_id = models.save_snapshot_for_place(
        place_id="place-123",
        address_input="123 Main St",
        address_norm="123 Main St, Testville, TX",
        evaluated_at=now,
        result_dict=_result(),
    )

    class FakeGeo:
        def __init__(self, api_key):
            self.api_key = api_key

        def geocode_details(self, address):
            return {
                "lat": 30.0,
                "lng": -97.0,
                "place_id": "place-123",
                "formatted_address": "123 Main St, Testville, TX",
            }

    monkeypatch.setattr(app_module, "GoogleMapsClient", FakeGeo)

    def should_not_run(*args, **kwargs):
        raise AssertionError("evaluate_property should not run on fresh dedupe hit")

    monkeypatch.setattr(app_module, "evaluate_property", should_not_run)

    with app_module.app.test_client() as client:
        resp = client.post("/", data={"address": "123 Main St"}, headers={"Accept": "application/json"})

    data = resp.get_json()
    assert resp.status_code == 200
    assert data["snapshot_id"] == snapshot_id
    assert data["redirect_url"] == f"/s/{snapshot_id}"

    events = models.get_recent_events(limit=20)
    reused = [e for e in events if e["event_type"] == "snapshot_reused"]
    assert reused


def test_stale_snapshot_refreshes_in_place(monkeypatch, tmp_path):
    app_module, models = _load_app(monkeypatch, tmp_path, ttl_days="30")
    stale_time = (datetime.now(timezone.utc) - timedelta(days=120)).isoformat()
    snapshot_id = models.save_snapshot_for_place(
        place_id="place-abc",
        address_input="100 Old St",
        address_norm="100 Old St, Testville, TX",
        evaluated_at=stale_time,
        result_dict=_result(final_score=40, verdict="Old"),
    )

    class FakeGeo:
        def __init__(self, api_key):
            self.api_key = api_key

        def geocode_details(self, address):
            return {
                "lat": 30.1,
                "lng": -97.1,
                "place_id": "place-abc",
                "formatted_address": "100 Old St, Testville, TX",
            }

    monkeypatch.setattr(app_module, "GoogleMapsClient", FakeGeo)

    calls = []

    def fake_eval(listing, api_key, pre_geocode=None):
        calls.append({"listing": listing.address, "pre_geocode": pre_geocode})
        return object()

    monkeypatch.setattr(app_module, "evaluate_property", fake_eval)
    monkeypatch.setattr(app_module, "result_to_dict", lambda _: _result(final_score=95, verdict="Refreshed"))

    with app_module.app.test_client() as client:
        resp = client.post("/", data={"address": "100 Old St"}, headers={"Accept": "application/json"})

    assert resp.status_code == 200
    data = resp.get_json()
    assert data["snapshot_id"] == snapshot_id
    assert len(calls) == 1
    assert calls[0]["pre_geocode"]["place_id"] == "place-abc"

    snapshot = models.get_snapshot(snapshot_id)
    assert snapshot["final_score"] == 95
    assert snapshot["verdict"] == "Refreshed"
    assert snapshot["evaluated_at"] != stale_time


def test_new_place_id_creates_snapshot_with_place_id(monkeypatch, tmp_path):
    app_module, models = _load_app(monkeypatch, tmp_path)

    class FakeGeo:
        def __init__(self, api_key):
            self.api_key = api_key

        def geocode_details(self, address):
            return {
                "lat": 29.9,
                "lng": -97.2,
                "place_id": "place-new",
                "formatted_address": "500 New St, Testville, TX",
            }

    monkeypatch.setattr(app_module, "GoogleMapsClient", FakeGeo)
    monkeypatch.setattr(app_module, "evaluate_property", lambda *args, **kwargs: object())
    monkeypatch.setattr(app_module, "result_to_dict", lambda _: _result(final_score=80))

    with app_module.app.test_client() as client:
        resp = client.post("/", data={"address": "500 New St"}, headers={"Accept": "application/json"})

    assert resp.status_code == 200
    snapshot_id = resp.get_json()["snapshot_id"]
    snapshot = models.get_snapshot(snapshot_id)
    assert snapshot["place_id"] == "place-new"
    assert snapshot["evaluated_at"]


def test_integrity_error_race_falls_back_to_winner(monkeypatch, tmp_path):
    app_module, models = _load_app(monkeypatch, tmp_path)
    winner_id = models.save_snapshot_for_place(
        place_id="place-race",
        address_input="1 Race St",
        address_norm="1 Race St, Testville, TX",
        evaluated_at=datetime.now(timezone.utc).isoformat(),
        result_dict=_result(),
    )
    winner = models.get_snapshot(winner_id)

    class FakeGeo:
        def __init__(self, api_key):
            self.api_key = api_key

        def geocode_details(self, address):
            return {
                "lat": 30.0,
                "lng": -97.0,
                "place_id": "place-race",
                "formatted_address": "1 Race St, Testville, TX",
            }

    monkeypatch.setattr(app_module, "GoogleMapsClient", FakeGeo)
    monkeypatch.setattr(app_module, "evaluate_property", lambda *args, **kwargs: object())
    monkeypatch.setattr(app_module, "result_to_dict", lambda _: _result())

    call_count = {"n": 0}

    def fake_lookup(place_id):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return None
        return winner

    monkeypatch.setattr(app_module, "get_snapshot_by_place_id", fake_lookup)

    def raise_integrity(*args, **kwargs):
        raise sqlite3.IntegrityError("UNIQUE constraint failed: snapshots.place_id")

    monkeypatch.setattr(app_module, "save_snapshot_for_place", raise_integrity)

    with app_module.app.test_client() as client:
        resp = client.post("/", data={"address": "1 Race St"}, headers={"Accept": "application/json"})

    assert resp.status_code == 200
    data = resp.get_json()
    assert data["snapshot_id"] == winner_id
    assert data["redirect_url"] == f"/s/{winner_id}"


def test_missing_place_id_runs_evaluation_and_saves_legacy_snapshot(monkeypatch, tmp_path):
    app_module, models = _load_app(monkeypatch, tmp_path)

    class FakeGeo:
        def __init__(self, api_key):
            self.api_key = api_key

        def geocode_details(self, address):
            return {
                "lat": 31.0,
                "lng": -98.0,
                "formatted_address": "No Place ID St, Testville, TX",
            }

    monkeypatch.setattr(app_module, "GoogleMapsClient", FakeGeo)
    calls = []

    def fake_eval(listing, api_key, pre_geocode=None):
        calls.append(pre_geocode)
        return object()

    monkeypatch.setattr(app_module, "evaluate_property", fake_eval)
    monkeypatch.setattr(app_module, "result_to_dict", lambda _: _result())

    with app_module.app.test_client() as client:
        resp = client.post("/", data={"address": "No Place ID St"}, headers={"Accept": "application/json"})

    assert resp.status_code == 200
    assert len(calls) == 1
    assert "place_id" not in calls[0]

    snapshot_id = resp.get_json()["snapshot_id"]
    snapshot = models.get_snapshot(snapshot_id)
    assert snapshot["place_id"] is None


def test_debug_eval_bypasses_dedupe(monkeypatch, tmp_path):
    app_module, _ = _load_app(monkeypatch, tmp_path, builder=True)

    called = {"eval": 0}

    def fake_eval(*args, **kwargs):
        called["eval"] += 1

        class FakeEvalResult:
            final_score = 88
            passed_tier1 = True

        return FakeEvalResult()

    monkeypatch.setattr(app_module, "evaluate_property", fake_eval)

    def should_not_lookup(*args, **kwargs):
        raise AssertionError("debug/eval should not call dedupe lookup")

    monkeypatch.setattr(app_module, "get_snapshot_by_place_id", should_not_lookup)

    with app_module.app.test_client() as client:
        resp = client.post("/debug/eval", json={"address": "Debug Address"})

    assert resp.status_code == 200
    assert called["eval"] == 1
