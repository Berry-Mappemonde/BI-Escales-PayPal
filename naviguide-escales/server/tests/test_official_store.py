"""Stock officiel : une interface, deux dos, aucun calcul sur la requête."""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import official_store
from official_store import (
    DiskBackend,
    FAMILIES,
    FILM_SCRIPT_REV,
    ICI_REV,
    MOMENTS_REV,
    PLAN_REVIEW_REV,
    MongoBackend,
    OfficialStore,
    PREPARING,
    READY,
    UNAVAILABLE,
    film_snapshot_stale,
    make_key,
    parse_key,
    preparing_payload,
)

T0 = "2026-05-15T08:00:00Z"
NOW = datetime(2026, 9, 26, 12, tzinfo=timezone.utc)


class _FakeColl:
    def __init__(self):
        self.docs = {}

    def find_one(self, filt):
        return self.docs.get((filt or {}).get("_id"))

    def find(self, filt=None):
        filt = filt or {}
        for doc in self.docs.values():
            if all(doc.get(k) == v for k, v in filt.items()):
                yield dict(doc)

    def replace_one(self, filt, doc, upsert=True):
        self.docs[doc["_id"]] = dict(doc)
        return type("R", (), {"upserted_id": doc["_id"], "modified_count": 1})()


class _FakeDB:
    def __init__(self):
        self.cols = {}

    def __getitem__(self, name):
        return self.cols.setdefault(name, _FakeColl())


class FakeMongoClient:
    """Client in-process, même contrat que mongomock pour notre dos. Pas de réseau."""

    def __init__(self):
        self.dbs = {}

    def __getitem__(self, name):
        return self.dbs.setdefault(name, _FakeDB())


def _mongo_client():
    try:
        import mongomock
        return mongomock.MongoClient()
    except ImportError:
        return FakeMongoClient()


def _stores(tmp_path):
    disk = OfficialStore(DiskBackend(tmp_path / "disk"), now=lambda: NOW)
    mongo = OfficialStore(MongoBackend(_mongo_client()), now=lambda: NOW)
    return [("disk", disk), ("mongo", mongo)]


def _payload(family, tag="A"):
    if family == "film":
        return {
            "fr": {
                "chapters": [{"id": "c1", "text": f"Saint-Maur {tag} 15 mai 2026", "tA": T0, "tB": T0}],
                "source": "rules", "chars": 20, "targetSeconds": 0,
            },
            "default": {
                "chapters": [{"id": "c1", "text": f"Saint-Maur {tag} 15 mai 2026", "tA": T0, "tB": T0}],
                "source": "rules", "chars": 20, "targetSeconds": 0,
            },
        }
    if family == "eta":
        return {"stops": {"Dzaoudzi (Mayotte)": {
            "members": 12, "p10": "2026-10-11T00:00:00Z", "p90": "2026-10-13T00:00:00Z",
        }}}
    if family == "climo":
        return {"clock": {"t0": T0, "vertices": [{"lat": 46.15, "lon": -1.16, "iso": T0}]}, "regimes": [], "fiches": []}
    if family == "ici":
        return {"points": [{"lat": 46.15, "lon": -1.16, "nm": 0, "bag": {
            "zee": {"name": "FR"},
            "amp": [{"name": "Pertuis charentais", "source": "polygon", "inside": False, "nm": 8.0, "siteId": "PS-1"}],
            "at": {"lat": 46.15, "lon": -1.16},
            "sources": {"bi": "ok"},
        }}]}
    if family == "plan_review":
        return {"legs": [{"from": "La Rochelle", "to": "Fort-de-France (Martinique)"}]}
    return {"moments": [{"t": T0, "signature": tag}], "journal": {"count": 2, "latest": [{"t": T0, "kind": "stop", "name": "La Rochelle"}], "events": [], "days": []}}


@pytest.mark.parametrize("backend_name", ["disk", "mongo"])
def test_same_key_no_recompute(tmp_path, backend_name):
    store = dict(_stores(tmp_path))[backend_name]
    key = make_key("routeA", T0, "2026-09-26")
    calls = {"n": 0}

    def compute(voy, now):
        calls["n"] += 1
        return _payload("film", "once")

    voy = {"t0": T0, "points": [{"lat": 1, "lon": 2}], "marks": []}
    first = official_store.refresh_family(
        "film", compute=compute, now=NOW, store=store, voy=voy, force=True,
    )
    assert first == READY
    key = store.family_key("film", voy, NOW)
    stored_at = store.get("film", key)["storedAt"]
    again = official_store.refresh_family(
        "film", compute=compute, now=NOW, store=store, voy=voy, force=False,
    )
    assert again == "unchanged"
    assert calls["n"] == 1
    assert store.get("film", key)["storedAt"] == stored_at


@pytest.mark.parametrize("backend_name", ["disk", "mongo"])
def test_missing_is_preparing(tmp_path, backend_name):
    store = dict(_stores(tmp_path))[backend_name]
    assert store.get("film") is None
    body = preparing_payload("film", {"chapters": []})
    assert body["status"] == PREPARING
    assert body["reason"] == "en préparation"


@pytest.mark.parametrize("backend_name", ["disk", "mongo"])
def test_restart_rereads_same_payload(tmp_path, backend_name):
    if backend_name == "disk":
        root = tmp_path / "persist"
        a = OfficialStore(DiskBackend(root), now=lambda: NOW)
        key = make_key("r", T0, "2026-09-26")
        a.put("moments", _payload("moments"), key)
        b = OfficialStore(DiskBackend(root), now=lambda: NOW)
        hit = b.get("moments", key)
        assert hit["payload"]["journal"]["count"] == 2
        assert hit["storedAt"]
    else:
        client = _mongo_client()
        a = OfficialStore(MongoBackend(client), now=lambda: NOW)
        key = make_key("r", T0, "2026-09-26")
        a.put("eta", _payload("eta"), key)
        b = OfficialStore(MongoBackend(client), now=lambda: NOW)
        hit = b.get("eta", key)
        assert hit["payload"]["stops"]["Dzaoudzi (Mayotte)"]["members"] == 12


@pytest.mark.parametrize("backend_name", ["disk", "mongo"])
def test_atomic_replace_and_all_families(tmp_path, backend_name):
    store = dict(_stores(tmp_path))[backend_name]
    key = make_key("r", T0, "2026-09-26")
    for name in FAMILIES:
        store.put(name, _payload(name, "v1"), key)
        store.put(name, _payload(name, "v2"), key)
        hit = store.get(name, key)
        assert hit["payload"] is not None
        assert hit["storedAt"]
    st = store.status(key)
    assert all(st["families"][n]["status"] == READY for n in FAMILIES)


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("NAVIGUIDE_FORECAST_BACKEND", "synthetic")
    monkeypatch.setenv("NAVIGUIDE_VOYAGE_DIR", str(tmp_path / "voyages"))
    import voyage_store
    voyage_store._DIR = tmp_path / "voyages"
    official_store.reset_store()
    from fastapi.testclient import TestClient
    from main import app
    return TestClient(app)


def test_http_missing_is_preparing_not_500(client):
    r = client.get("/voyage/official/journal")
    assert r.status_code == 200
    assert r.json()["status"] == PREPARING
    assert r.json()["latest"] == []

    film = client.get("/voyage/official/film?lang=fr&seconds=0")
    assert film.status_code == 200
    assert film.json()["status"] == PREPARING
    assert film.json()["chapters"] == []

    eta = client.get("/voyage/official/eta", params={"stop": "Dzaoudzi (Mayotte)"})
    assert eta.status_code == 200
    assert eta.json().get("members") == 0
    assert eta.json()["status"] == PREPARING

    review = client.get("/voyage/official/plan-review")
    assert review.status_code == 200
    assert review.json()["status"] == PREPARING
    assert review.json()["legs"] == []

    clock = client.get("/voyage/official/clock")
    assert clock.status_code == 200
    assert clock.json()["status"] == PREPARING


def test_http_serves_store_when_externals_would_fail(client, monkeypatch):
    import ensemble_eta
    import film_script
    import plan_review
    import voyage_api

    def boom(*_a, **_k):
        raise AssertionError("fournisseur appelé sur la requête")

    monkeypatch.setattr(film_script, "official_film", boom)
    monkeypatch.setattr(plan_review, "review_official", boom)
    monkeypatch.setattr(ensemble_eta, "peek_official_eta", boom)
    monkeypatch.setattr(ensemble_eta, "preheat_official_eta", boom)
    monkeypatch.setattr(voyage_api, "_climo_clock", boom)
    monkeypatch.setattr(voyage_api, "_kick_official_eta", boom)
    monkeypatch.setattr(voyage_api, "_kick_official_moments", boom)

    official_store.put("film", _payload("film"))
    official_store.put("plan_review", _payload("plan_review"))
    official_store.put("eta", _payload("eta"))
    official_store.put("climo", _payload("climo"))
    official_store.put("moments", _payload("moments"))

    film = client.get("/voyage/official/film?lang=fr&seconds=0")
    assert film.status_code == 200
    assert "Saint-Maur" in film.json()["chapters"][0]["text"]
    assert film.json()["status"] == READY

    review = client.get("/voyage/official/plan-review")
    assert review.status_code == 200
    assert review.json()["legs"][0]["to"] == "Fort-de-France (Martinique)"

    eta = client.get("/voyage/official/eta", params={"stop": "Dzaoudzi (Mayotte)"})
    assert eta.status_code == 200
    assert eta.json()["members"] == 12

    clock = client.get("/voyage/official/clock")
    assert clock.status_code == 200
    assert clock.json()["t0"].startswith("2026-05-15")

    journal = client.get("/voyage/official/journal")
    assert journal.status_code == 200
    assert journal.json()["status"] == READY
    assert journal.json()["latest"][0]["kind"] == "stop"


def test_http_ici_official_point_from_store_not_fill(client, monkeypatch):
    import main
    import voyage_api

    def boom(*_a, **_k):
        raise AssertionError("fill_dossier sur la requête officielle")

    monkeypatch.setattr(main, "fill_dossier", boom)
    voy = voyage_api.seed_official_voyage()
    assert voy and voy.get("points")
    official_store.put("ici", _payload("ici"))

    r = client.get("/ici", params={"lat": 46.15, "lon": -1.16})
    assert r.status_code == 200
    body = r.json()
    assert body.get("cached") is True or (body.get("zee") or {}).get("name") == "FR"
    assert body["amp"][0]["source"] == "polygon"


def test_ici_bag_near_rejects_amp_without_source():
    official_store.put("ici", {"points": [{
        "lat": 41.31,
        "lon": 9.19,
        "nm": 0,
        "bag": {
            "amp": [{"name": "Strait of Bonifacio", "nm": 2.0}],
            "sources": {"bi": "ok"},
            "pearl": "rich",
        },
    }]})
    assert official_store.ici_bag_near(41.31, 9.19) is None


def test_ici_bag_near_accepts_amp_with_source():
    bag = {
        "amp": [{"name": "Strait of Bonifacio", "source": "polygon", "inside": True, "nm": 0.0, "siteId": "AIFRA7"}],
        "sources": {"bi": "ok"},
    }
    official_store.put("ici", {"points": [{"lat": 41.31, "lon": 9.19, "nm": 0, "bag": bag}]})
    got = official_store.ici_bag_near(41.31, 9.19)
    assert got is not None
    assert got["amp"][0]["source"] == "polygon"
    assert got["amp"][0]["inside"] is True


def test_ici_bag_near_accepts_empty_amp_list():
    official_store.put("ici", {"points": [{
        "lat": 0.0,
        "lon": -30.0,
        "nm": 1000,
        "bag": {"amp": [], "sources": {"bi": "ok"}, "zee": None},
    }]})
    got = official_store.ici_bag_near(0.0, -30.0)
    assert got is not None
    assert got["amp"] == []


def test_http_ici_pre_am1a_snapshot_is_not_served_cached(client, monkeypatch):
    import voyage_api

    voy = voyage_api.seed_official_voyage()
    assert voy and voy.get("points")
    official_store.put("ici", {"points": [{
        "lat": 46.15,
        "lon": -1.16,
        "nm": 0,
        "bag": {
            "amp": [{"name": "Old park", "nm": 3.0}],
            "sources": {"bi": "ok"},
            "pearl": "rich",
        },
    }]})
    assert official_store.ici_bag_near(46.15, -1.16) is None
    r = client.get("/ici", params={"lat": 46.15, "lon": -1.16})
    assert r.status_code == 200
    body = r.json()
    amps = body.get("amp") or []
    has_source = any(isinstance(x, dict) and "source" in x for x in amps)
    assert body.get("status") == PREPARING or has_source
    if not has_source:
        assert body.get("cached") is not True


AIR_MARKS = [
    {"name": "Saint-Maur (Berry, Indre)", "nm": 0, "filmNm": 0, "lat": 46.8, "lon": 1.6},
    {"name": "Cayenne (Guyane)", "nm": 4000, "filmNm": 4000, "lat": 4.9, "lon": -52.3},
    {"name": "Halifax (Nouvelle-Écosse)", "nm": 4100, "filmNm": 4100, "lat": 44.6, "lon": -63.6},
    {"name": "Nouméa (Nouvelle-Calédonie)", "nm": 19000, "filmNm": 19000, "lat": -22.2, "lon": 166.4},
]


def _air_voy():
    return {
        "t0": T0,
        "points": [{"lat": 46.8, "lon": 1.6}, {"lat": 4.9, "lon": -52.3}],
        "marks": AIR_MARKS,
        "clock": {"t0": T0, "marks": AIR_MARKS, "vertices": []},
    }


def _stale_film_payload():
    chapter = {
        "id": "c1",
        "text": "Le 1er juillet, départ vers Saint-Pierre.",
        "tA": T0,
        "tB": T0,
    }
    plan = {"chapters": [chapter], "source": "rules", "chars": 40, "targetSeconds": 0}
    return {"fr": plan, "default": plan}


def _rf5_from_marks(marks, lang="fr"):
    import film_script
    outbound, back = film_script._air_pair_sentences(marks, lang)
    text = f"{outbound} {back}".strip()
    return {
        "chapters": [{"id": "c1", "text": text, "tA": T0, "tB": T0}],
        "source": "rules",
        "chars": len(text),
        "targetSeconds": 0,
        "hasWritten": False,
    }


def test_serve_film_plays_previous_revision_until_the_new_one_is_stored(tmp_path, monkeypatch):
    """La révision du checkout peut manquer (remplisseur encore dessus). Revoir joue le dernier script."""
    voy = {
        "t0": T0,
        "points": [{"lat": 46.8, "lon": 1.6}],
        "marks": [{"name": "La Rochelle", "nm": 0}],
        "clock": {"t0": T0, "vertices": [], "marks": []},
    }
    monkeypatch.setattr(official_store, "_load_official", lambda: voy)
    monkeypatch.setenv("NAVIGUIDE_OFFICIAL_WORKER", "1")
    store = OfficialStore(DiskBackend(tmp_path / "disk"), now=lambda: NOW)
    plan = {
        "chapters": [{
            "id": "c1",
            "text": "The Berry-Mappemonde expedition left Saint-Maur on 15 May 2026.",
        }],
        "source": "rules",
        "chars": 64,
        "targetSeconds": 150,
    }
    payload = {"en": plan, "default": plan, "variants": {"en": {"150": plan}}}
    store.put("film", payload, f"{store.current_key(voy, NOW)}:rc55")
    assert store.get("film", store.family_key("film", voy, NOW)) is None
    official_store._INSTANCE = store
    try:
        played = official_store.serve_film("en", 150)
        assert played["status"] == READY
        assert played["chapters"][0]["text"].startswith("The Berry-Mappemonde")
        official_store._INSTANCE = OfficialStore(DiskBackend(tmp_path / "empty"), now=lambda: NOW)
        assert official_store.serve_film("en", 150)["status"] == PREPARING
    finally:
        official_store.reset_store()


def test_film_key_includes_script_rev(tmp_path):
    store = OfficialStore(DiskBackend(tmp_path / "disk"), now=lambda: NOW)
    voy = {"t0": T0, "points": [{"lat": 1, "lon": 2}], "marks": []}
    film_key = store.family_key("film", voy, NOW)
    base = store.current_key(voy, NOW)
    assert FILM_SCRIPT_REV == "vs1-ed2"
    assert film_key == f"{base}:{FILM_SCRIPT_REV}"
    assert store.family_key("moments", voy, NOW) == f"{base}:{MOMENTS_REV}"
    assert store.family_key("ici", voy, NOW) == f"{base}:{ICI_REV}"
    assert store.family_key("plan_review", voy, NOW) == f"{base}:{PLAN_REVIEW_REV}"
    assert store.family_key("eta", voy, NOW) == base


def test_plan_review_key_changes_with_rev(tmp_path, monkeypatch):
    """Bumper PLAN_REVIEW_REV change la clé."""
    store = OfficialStore(DiskBackend(tmp_path / "disk"), now=lambda: NOW)
    voy = {"t0": T0, "points": [{"lat": 1, "lon": 2}], "marks": []}
    base = store.current_key(voy, NOW)
    before = store.family_key("plan_review", voy, NOW)
    assert before == f"{base}:{PLAN_REVIEW_REV}"
    monkeypatch.setattr(official_store, "PLAN_REVIEW_REV", "rc50-test")
    after = store.family_key("plan_review", voy, NOW)
    assert after == f"{base}:rc50-test"
    assert after != before


def test_plan_review_pre_rev_snapshot_is_preparing_even_when_worker_off(tmp_path, monkeypatch):
    """Snapshot Halifax → Papeete à la clé sans rev n'est jamais ready.

    Contrairement à film/moments/ici, plan_review n'a pas de repli WORKER=0 :
    GET sans entrée à `…:PLAN_REVIEW_REV` reste en préparation.
    """
    monkeypatch.setenv("NAVIGUIDE_OFFICIAL_WORKER", "0")
    store = OfficialStore(DiskBackend(tmp_path / "disk"), now=lambda: NOW)
    voy = {"t0": T0, "points": [{"lat": 1, "lon": 2}], "marks": []}
    monkeypatch.setattr(official_store, "_load_official", lambda: voy)
    monkeypatch.setattr(official_store, "_INSTANCE", store)
    stale = {
        "legs": [{
            "from": "Halifax (Nouvelle-Écosse)",
            "to": "Papeete (Polynésie française)",
        }],
        "generatedAt": "2026-10-16T00:28:46Z",
    }
    old_key = store.current_key(voy, NOW)
    store.put("plan_review", stale, old_key)
    new_key = store.family_key("plan_review", voy, NOW)
    assert new_key == f"{old_key}:{PLAN_REVIEW_REV}"
    assert store.get("plan_review", new_key) is None
    served = official_store.serve_plan_review()
    assert served["status"] == PREPARING
    assert served["legs"] == []
    blob = str(served)
    assert "Halifax" not in blob
    assert "Papeete" not in blob


def test_plan_review_refresh_misses_old_key(tmp_path, monkeypatch):
    """Refresh_family ne rend pas unchanged sur l'ancien snapshot."""
    store = OfficialStore(DiskBackend(tmp_path / "disk"), now=lambda: NOW)
    voy = {"t0": T0, "points": [{"lat": 1, "lon": 2}], "marks": []}
    stale = {
        "legs": [{
            "from": "Halifax (Nouvelle-Écosse)",
            "to": "Papeete (Polynésie française)",
        }],
    }
    store.put("plan_review", stale, store.current_key(voy, NOW))
    calls = {"n": 0}

    def compute(_voy, _now):
        calls["n"] += 1
        return {"legs": [{"from": "computed", "to": "computed"}]}

    status = official_store.refresh_family(
        "plan_review", compute=compute, now=NOW, store=store, voy=voy, force=False,
    )
    assert status == READY
    assert calls["n"] == 1
    hit = store.get("plan_review", store.family_key("plan_review", voy, NOW))
    assert hit["payload"]["legs"][0]["from"] == "computed"
    again = official_store.refresh_family(
        "plan_review", compute=compute, now=NOW, store=store, voy=voy, force=False,
    )
    assert again == "unchanged"
    assert calls["n"] == 1


def test_plan_review_http_old_key_is_preparing_and_kicks(client, monkeypatch):
    """GET /plan-review sans snapshot à la nouvelle clé : preparing + kick."""
    kicks = {"n": 0}
    monkeypatch.setattr(official_store, "kick_worker", lambda: kicks.__setitem__("n", kicks["n"] + 1))
    voy = {"t0": T0, "points": [{"lat": 1, "lon": 2}], "marks": []}
    monkeypatch.setattr(official_store, "_load_official", lambda: voy)
    store = official_store.get_store()
    store.put("plan_review", {
        "legs": [{
            "from": "Halifax (Nouvelle-Écosse)",
            "to": "Papeete (Polynésie française)",
        }],
        "generatedAt": "2026-10-16T00:28:46Z",
    }, store.current_key(voy))
    r = client.get("/voyage/official/plan-review")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == PREPARING
    assert body["legs"] == []
    assert "Halifax" not in str(body)
    assert kicks["n"] >= 1


def test_film_get_falls_back_to_previous_rev_when_worker_off(tmp_path, monkeypatch):
    monkeypatch.setenv("NAVIGUIDE_OFFICIAL_WORKER", "0")
    store = OfficialStore(DiskBackend(tmp_path / "disk"), now=lambda: NOW)
    voy = {"t0": T0, "points": [{"lat": 1, "lon": 2}], "marks": []}
    monkeypatch.setattr(official_store, "_load_official", lambda: voy)
    payload = {"fr": {"chapters": [{"text": "ancien rf5"}]}}
    store.put("film", payload, f"{store.current_key(voy, NOW)}:rf5")
    hit = store.get("film")
    assert hit is not None
    assert hit["payload"]["fr"]["chapters"][0]["text"] == "ancien rf5"


def test_film_get_prefers_current_rev_when_both_exist(tmp_path, monkeypatch):
    monkeypatch.setenv("NAVIGUIDE_OFFICIAL_WORKER", "0")
    store = OfficialStore(DiskBackend(tmp_path / "disk"), now=lambda: NOW)
    voy = {"t0": T0, "points": [{"lat": 1, "lon": 2}], "marks": []}
    monkeypatch.setattr(official_store, "_load_official", lambda: voy)
    base = store.current_key(voy, NOW)
    store.put("film", {"fr": {"chapters": [{"text": "vieux"}]}}, f"{base}:rf5")
    store.put("film", {"fr": {"chapters": [{"text": "rg1"}]}}, f"{base}:{FILM_SCRIPT_REV}")
    hit = store.get("film")
    assert hit["payload"]["fr"]["chapters"][0]["text"] == "rg1"


def test_film_get_skips_previous_rev_when_worker_on(tmp_path, monkeypatch):
    monkeypatch.setenv("NAVIGUIDE_OFFICIAL_WORKER", "1")
    store = OfficialStore(DiskBackend(tmp_path / "disk"), now=lambda: NOW)
    voy = {"t0": T0, "points": [{"lat": 1, "lon": 2}], "marks": []}
    monkeypatch.setattr(official_store, "_load_official", lambda: voy)
    store.put("film", {"fr": {"chapters": [{"text": "rf5"}]}}, f"{store.current_key(voy, NOW)}:rf5")
    assert store.get("film") is None


def test_frozen_archive_serves_film_under_new_rev_when_worker_off(tmp_path, monkeypatch):
    import tarfile

    monkeypatch.setenv("NAVIGUIDE_OFFICIAL_WORKER", "0")
    dest = tmp_path / "store"
    dest.mkdir()
    archive = Path(__file__).resolve().parent / "fixtures" / "official_store.tar.gz"
    with tarfile.open(archive, "r:gz") as tf:
        tf.extractall(dest, filter="data")
    store = OfficialStore(DiskBackend(dest), now=lambda: datetime(2026, 9, 27, tzinfo=timezone.utc))
    current = "c4a0d2dc06cea61b:2026-05-15T08:00:00Z:2026-09-27:rg1"
    monkeypatch.setattr(
        store, "family_key",
        lambda family, voy=None, now=None: current if family == "film" else current.rsplit(":", 1)[0],
    )
    hit = store.get("film")
    assert hit is not None
    chapters = ((hit.get("payload") or {}).get("fr") or {}).get("chapters") or []
    if not chapters:
        variants = ((hit.get("payload") or {}).get("variants") or {}).get("fr") or {}
        first = next(iter(variants.values()), {}) if isinstance(variants, dict) else {}
        chapters = (first or {}).get("chapters") or []
    assert len(chapters) > 0


def test_frozen_archive_is_paired_with_its_route(monkeypatch):
    """La recette hors ligne sert official_store.route.geojson : chaque clé de l'archive
    doit porter l'empreinte de cette route, sinon l'API ne sert rien (bateau, horloge, film)."""
    import json
    import tarfile

    import voyage_api

    fixtures = Path(__file__).resolve().parent / "fixtures"
    monkeypatch.setattr(voyage_api, "_ROUTE_GEOJSON", fixtures / "official_store.route.geojson")
    monkeypatch.setattr(voyage_api, "_OFFICIAL_BODY_CACHE", None)
    body = voyage_api.official_itinerary_body()
    fp = voyage_api._route_fp(body.points, body.marks, voyage_api.OFFICIAL_T0)
    with tarfile.open(fixtures / "official_store.tar.gz", "r:gz") as tf:
        keys = {
            json.load(tf.extractfile(m))["key"]
            for m in tf.getmembers()
            if m.isfile() and m.name.endswith(".json")
        }
    assert keys
    assert all(k.startswith(f"{fp}:") for k in keys), (fp, sorted(keys))


def test_route_override_only_when_offline(monkeypatch):
    import voyage_api

    monkeypatch.setenv("NAVIGUIDE_OFFICIAL_ROUTE_FILE", "/tmp/route-du-gel.geojson")
    monkeypatch.delenv("NAVIGUIDE_OFFLINE", raising=False)
    assert voyage_api._route_geojson_path() == voyage_api._PUBLIC_ROUTE_GEOJSON
    monkeypatch.setenv("NAVIGUIDE_OFFLINE", "1")
    assert voyage_api._route_geojson_path() == Path("/tmp/route-du-gel.geojson")


def test_stale_film_refreshed_when_marks_have_air_pair(tmp_path):
    store = OfficialStore(DiskBackend(tmp_path / "disk"), now=lambda: NOW)
    voy = _air_voy()
    calls = {"n": 0}

    def compute(_voy, _now):
        calls["n"] += 1
        plan = _rf5_from_marks(_voy.get("marks") or [])
        return {"fr": plan, "default": plan}

    key = store.family_key("film", voy, NOW)
    store.put("film", _stale_film_payload(), key)
    assert film_snapshot_stale(store.get("film", key)["payload"], voy)
    status = official_store.refresh_family(
        "film", compute=compute, now=NOW, store=store, voy=voy, force=False,
    )
    assert status == READY
    assert calls["n"] == 1
    blob = " ".join(
        c.get("text") or ""
        for c in store.get("film", key)["payload"]["fr"]["chapters"]
    )
    low = blob.lower()
    assert "s'envole" in low
    assert "bateau attend" in low or "catamaran attend" in low

    again = official_store.refresh_family(
        "film", compute=compute, now=NOW, store=store, voy=voy, force=False,
    )
    assert again == "unchanged"
    assert calls["n"] == 1


def test_ajaccio_refresh_does_not_invent_air(tmp_path):
    store = OfficialStore(DiskBackend(tmp_path / "disk"), now=lambda: NOW)
    voy = {
        "t0": T0,
        "points": [{"lat": 46.15, "lon": -1.16}],
        "marks": [
            {"name": "La Rochelle", "nm": 0, "lat": 46.15, "lon": -1.16},
            {"name": "Ajaccio (Corse)", "nm": 1820, "lat": 41.9, "lon": 8.7},
        ],
        "clock": {"t0": T0, "marks": [], "vertices": []},
    }
    plan = {
        "chapters": [{"id": "c1", "text": "Le 15 mai, départ vers Ajaccio.", "tA": T0, "tB": T0}],
        "source": "rules", "chars": 30, "targetSeconds": 0,
    }

    def compute(_voy, _now):
        return {"fr": plan, "default": plan}

    assert film_snapshot_stale({"fr": plan}, voy) is False
    status = official_store.refresh_family(
        "film", compute=compute, now=NOW, store=store, voy=voy, force=True,
    )
    assert status == READY
    blob = store.get("film", store.family_key("film", voy, NOW))["payload"]["fr"]["chapters"][0]["text"]
    assert "prend l'avion" not in blob
    assert "s'envole" not in blob
    assert "retour en avion" not in blob


def test_cayenne_voyage_uses_itinerary_halifax_for_air(tmp_path):
    """Voyage stocké sans Halifax : l'itinéraire Berry (route.geojson) porte la paire."""
    from film_script import _route_has_air_pair

    if not _route_has_air_pair(official_store._itinerary_marks()):
        return
    store = OfficialStore(DiskBackend(tmp_path / "disk"), now=lambda: NOW)
    voy = {
        "t0": T0,
        "points": [{"lat": 4.9, "lon": -52.3}],
        "marks": [{"name": "Cayenne (Guyane)", "nm": 4000, "lat": 4.9, "lon": -52.3}],
        "clock": {"t0": T0, "marks": [], "vertices": []},
    }
    plan = {
        "chapters": [{
            "id": "c1",
            "text": "Le 18 août, départ vers Saint-Pierre.",
            "fromName": "Cayenne (Guyane)",
            "toName": "Saint-Pierre (Saint-Pierre-et-Miquelon)",
        }],
        "source": "rules", "chars": 40, "targetSeconds": 0,
    }
    stale = {"fr": plan, "default": plan}
    assert film_snapshot_stale(stale, voy)

    def compute(v, _now):
        raw = {
            "chapters": [dict(plan["chapters"][0])],
            "source": "rules", "chars": 40, "targetSeconds": 0,
        }
        done = official_store._apply_air_sentences(raw, "fr", v)
        return {"fr": done, "default": done}

    status = official_store.refresh_family(
        "film", compute=compute, now=NOW, store=store, voy=voy, force=True,
    )
    assert status == READY
    blob = store.get("film", store.family_key("film", voy, NOW))["payload"]["fr"]["chapters"][0]["text"]
    low = blob.lower()
    assert "s'envole" in low
    assert "bateau attend" in low or "catamaran attend" in low


def test_http_force_refresh_film_serves_air_when_marks_have_pair(client, monkeypatch):
    import film_script
    import voyage_store
    from tests.test_voyage_journal import PUBLIC
    from voyage_clock import OFFICIAL_VOYAGE_ID

    body = {
        "t0": T0,
        "expedition_id": "berry-mappemonde-2026",
        "routeKind": "berry",
        "follow": True,
        "forecast": False,
        "official": True,
        "points": [
            {"lat": 46.8, "lon": 1.6, "cumNm": 0},
            {"lat": 4.9, "lon": -52.3, "cumNm": 4000},
            {"lat": 44.6, "lon": -63.6, "cumNm": 4100},
            {"lat": -22.2, "lon": 166.4, "cumNm": 19000},
        ],
        "marks": AIR_MARKS,
    }
    put = client.put("/voyage/official", json=body, headers=PUBLIC)
    assert put.status_code == 200
    voy = voyage_store.load_voyage(OFFICIAL_VOYAGE_ID)
    assert voy and voy.get("marks")
    names = " ".join(m.get("name") or "" for m in voy["marks"])
    assert "Cayenne" in names and "Halifax" in names

    async def from_marks(*, lang="fr", **_k):
        return _rf5_from_marks(voy.get("marks") or [], lang)

    monkeypatch.setattr(film_script, "official_film", from_marks)
    official_store.put("film", _stale_film_payload())
    stale = client.get("/voyage/official/film?lang=fr&seconds=0")
    assert stale.status_code == 200
    # Le script déjà rangé se joue tout de suite, même s'il ne dit pas encore l'avion.
    # Consigne : compléter les phrases manquantes, ne pas bloquer le film périmé.
    played = stale.json()
    assert played["status"] == READY
    assert played["chapters"]
    assert "Saint-Pierre" in played["chapters"][0]["text"]

    assert official_store.refresh_family("film", force=True) == READY
    film = client.get("/voyage/official/film?lang=fr&seconds=0")
    assert film.status_code == 200
    blob = " ".join(c.get("text") or "" for c in film.json().get("chapters") or [])
    low = blob.lower()
    assert "s'envole" in low
    assert "bateau attend" in low or "catamaran attend" in low


YESTERDAY = datetime(2026, 9, 26, 12, tzinfo=timezone.utc)
TODAY = datetime(2026, 9, 27, 12, tzinfo=timezone.utc)


@pytest.mark.parametrize("backend_name", ["disk", "mongo"])
def test_missing_today_serves_latest_with_data_date(tmp_path, monkeypatch, backend_name):
    voy = {"t0": T0, "points": [{"lat": 1.0, "lon": 2.0}], "marks": []}
    monkeypatch.setattr(official_store, "_load_official", lambda: voy)
    store = dict(_stores(tmp_path))[backend_name]
    store._now = lambda: TODAY
    old_key = store.family_key("moments", voy, YESTERDAY)
    store.put("moments", _payload("moments"), old_key)
    today_key = store.family_key("moments", voy, TODAY)
    assert today_key != old_key
    assert store.get("moments", today_key) is None
    hit = store.get("moments")
    assert hit is not None
    assert hit["payload"]["journal"]["count"] == 2
    assert hit["dataDate"] == "2026-09-26"
    assert hit["storedAt"]
    route, t0, date, _suf = parse_key(hit["key"])
    assert t0 == T0
    assert date == "2026-09-26"
    assert route == official_store.route_fingerprint(voy)
    official_store._INSTANCE = store
    try:
        served = official_store.serve_journal(50)
        assert served["status"] == READY
        assert served["dataDate"] == "2026-09-26"
        assert served["storedAt"]
    finally:
        official_store.reset_store()


def test_http_yesterday_key_is_served_with_data_date(client):
    voy = official_store._load_official()
    key = official_store.make_key(
        official_store.route_fingerprint(voy),
        (voy or {}).get("t0") or "",
        "2026-09-26",
    )
    official_store.put("moments", _payload("moments"), key)
    journal = client.get("/voyage/official/journal")
    assert journal.status_code == 200
    body = journal.json()
    assert body["status"] == READY
    assert body["dataDate"] == "2026-09-26"
    assert body["storedAt"]
    assert body["latest"][0]["kind"] == "stop"


def test_freeze_then_unpack_same_payloads(tmp_path):
    import importlib.util

    src = tmp_path / "src"
    store = OfficialStore(DiskBackend(src), now=lambda: NOW)
    key = make_key("routeA", T0, "2026-09-26")
    expected = {}
    for name in FAMILIES:
        payload = _payload(name, "freeze")
        store.put(name, payload, key)
        expected[name] = payload

    spec = importlib.util.spec_from_file_location(
        "freeze_official_store",
        Path(__file__).resolve().parents[2] / "scripts" / "freeze_official_store.py",
    )
    freeze = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(freeze)

    archive = tmp_path / "official_store.tar.gz"
    info = freeze.freeze(src, archive)
    assert info["docs"] == len(FAMILIES)
    assert archive.stat().st_size > 0
    dest = tmp_path / "unpacked"
    freeze.unpack(archive, dest)
    again = OfficialStore(DiskBackend(dest), now=lambda: NOW)
    for name in FAMILIES:
        hit = again.get(name, key)
        assert hit is not None
        assert hit["payload"] == expected[name]


# ── RC18 : le remplisseur est un processus séparé, l'API relit le stock quand il change ──────────────────

@pytest.mark.parametrize("backend_name", ["disk", "mongo"])
def test_get_rereads_when_another_process_rewrote(tmp_path, backend_name):
    """L'API garde une copie mémoire ; si le remplisseur (autre processus) a réécrit l'entrée, elle la relit."""
    import os
    import time

    key = make_key("r", T0, "2026-09-26")
    if backend_name == "disk":
        root = tmp_path / "shared"
        api = OfficialStore(DiskBackend(root), now=lambda: NOW)
        filler = OfficialStore(DiskBackend(root), now=lambda: datetime(2026, 9, 26, 13, tzinfo=timezone.utc))
    else:
        client = _mongo_client()
        api = OfficialStore(MongoBackend(client), now=lambda: NOW)
        filler = OfficialStore(MongoBackend(client), now=lambda: datetime(2026, 9, 26, 13, tzinfo=timezone.utc))
    api.put("eta", _payload("eta"), key)
    assert api.get("eta", key)["storedAt"] == "2026-09-26T12:00:00Z"
    time.sleep(0.02)
    filler.put("eta", {"stops": {"Papeete": {"members": 99}}}, key)
    if backend_name == "disk":   # mtime à la seconde sur certains systèmes : on force un horodatage plus récent
        f = next((root).rglob("eta.json"))
        os.utime(f, (time.time() + 5, time.time() + 5))
    hit = api.get("eta", key)
    assert hit["storedAt"] == "2026-09-26T13:00:00Z"
    assert hit["payload"]["stops"]["Papeete"]["members"] == 99


def test_process_mode_spawns_filler_once_and_never_computes_in_api(tmp_path, monkeypatch):
    """Mode process (défaut) : kick_worker lance scripts/prepare_official_store.py --loop UNE fois, le réveille
    par le fichier nudge, et ne calcule jamais dans le processus de l'API."""
    import subprocess

    monkeypatch.setenv("NAVIGUIDE_OFFICIAL_WORKER", "force")      # pytest coupe le worker sinon
    monkeypatch.setenv("NAVIGUIDE_OFFICIAL_STORE_DIR", str(tmp_path / "store"))
    monkeypatch.setenv("NAVIGUIDE_FILL_NUDGE_MIN_S", "0")         # ce test compte les lancements, pas le plafond
    monkeypatch.setattr(official_store, "_LAST_NUDGE_AT", None)
    monkeypatch.setattr(official_store, "WORKER_MODE", "process")
    calls: list[list[str]] = []

    class _Proc:
        pid = 424242

    def fake_popen(cmd, **kwargs):
        calls.append(list(cmd))
        return _Proc()

    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    monkeypatch.setattr(official_store, "_process_command", lambda pid: f"python {official_store.FILL_SCRIPT} --loop" if pid == 424242 else "")
    monkeypatch.setattr(official_store.os, "kill", lambda pid, sig: None if pid == 424242 else (_ for _ in ()).throw(OSError()))

    def boom(*a, **k):
        raise AssertionError("refresh_missing appelé dans le processus de l'API")

    monkeypatch.setattr(official_store, "refresh_missing", boom)

    official_store.kick_worker()
    official_store.kick_worker()
    official_store.start_worker()
    assert len(calls) == 1, calls
    assert calls[0][1] == str(official_store.FILL_SCRIPT) and "--loop" in calls[0]
    assert official_store.fill_pidfile().read_text(encoding="utf-8").splitlines()[0] == "424242"
    assert official_store.fill_nudgefile().exists()
    assert official_store.fill_process_alive() == 424242


def test_process_mode_wakes_the_filler_once_per_window(tmp_path, monkeypatch):
    """Trois kicks rapprochés ne relancent pas `ps -ax` ni le remplisseur."""
    monkeypatch.setenv("NAVIGUIDE_OFFICIAL_WORKER", "force")
    monkeypatch.setenv("NAVIGUIDE_OFFICIAL_STORE_DIR", str(tmp_path / "store"))
    monkeypatch.setenv("NAVIGUIDE_FILL_NUDGE_MIN_S", "180")
    monkeypatch.setattr(official_store, "WORKER_MODE", "process")
    monkeypatch.setattr(official_store, "_LAST_NUDGE_AT", None)
    wakes = {"n": 0}

    def count():
        wakes["n"] += 1
        return 1

    monkeypatch.setattr(official_store, "ensure_fill_process", count)
    monkeypatch.setattr(official_store, "nudge_fill_process", count)
    official_store.kick_worker()
    official_store.kick_worker()
    official_store.kick_worker()
    assert wakes["n"] == 2


def test_filler_from_another_checkout_is_replaced(tmp_path, monkeypatch):
    """Un remplisseur d'un ancien worktree (autre chemin de script) écrirait un stock d'un autre format : remplacé."""
    monkeypatch.setenv("NAVIGUIDE_OFFICIAL_STORE_DIR", str(tmp_path / "store"))
    official_store.fill_pidfile().parent.mkdir(parents=True, exist_ok=True)
    official_store.fill_pidfile().write_text("31337\n/ailleurs/scripts/prepare_official_store.py\n", encoding="utf-8")
    killed: list[tuple[int, int]] = []
    monkeypatch.setattr(official_store.os, "kill", lambda pid, sig: killed.append((pid, sig)))
    monkeypatch.setattr(official_store, "_process_command", lambda pid: "python /ailleurs/scripts/prepare_official_store.py --loop")
    assert official_store.fill_process_alive() is None
    assert (31337, 15) in killed


def test_rg8_three_variants_stored_and_served(tmp_path, monkeypatch):
    import film_script

    store = OfficialStore(DiskBackend(tmp_path / "disk"), now=lambda: NOW)
    monkeypatch.setattr(official_store, "_INSTANCE", store)
    monkeypatch.setattr(official_store, "_load_official", lambda: {
        "t0": T0, "clock": {"t0": T0, "vertices": [{"lat": 1, "lon": 2, "iso": T0}]}, "marks": [],
    })

    async def fake_film(*, lang="fr", seconds=150, **_k):
        n = {0: 40, 150: 10, 180: 20}.get(int(seconds or 0), 10)
        text = ("Berry-Mappemonde quitte La Rochelle. " * n).strip()
        return {
            "chapters": [{"id": "c0", "text": text}],
            "chars": len(text),
            "source": "rules",
            "targetSeconds": int(seconds or 0),
        }

    monkeypatch.setattr(film_script, "official_film", fake_film)
    voy = {"t0": T0, "clock": {"t0": T0, "vertices": [{"lat": 1, "lon": 2, "iso": T0}]}, "marks": []}
    payload = official_store.compute_film(voy, NOW)
    assert payload is not None
    fr = (payload.get("variants") or {}).get("fr") or {}
    assert set(fr) >= {"150", "180", "0"}
    assert fr["150"]["chars"] < fr["180"]["chars"] < fr["0"]["chars"]
    assert fr["150"]["estimatedSeconds"] < fr["180"]["estimatedSeconds"]
    key = store.family_key("film", voy, NOW)
    store.put("film", payload, key)
    short = official_store.serve_film("fr", 150)
    mid = official_store.serve_film("fr", 180)
    full = official_store.serve_film("fr", 0)
    assert short["status"] == READY
    assert short["chars"] < mid["chars"] < full["chars"]
    assert short["estimatedSeconds"] == fr["150"]["estimatedSeconds"]
    assert "150" in (full.get("estimates") or {})
    assert full["estimates"]["0"]["chars"] == fr["0"]["chars"]


def _film_voy():
    return {
        "t0": T0,
        "clock": {"t0": T0, "vertices": [{"lat": 1, "lon": 2, "iso": T0}]},
        "marks": [],
    }


def _film_plan(lang, seconds):
    return {
        "chapters": [{"id": "c0", "text": f"{lang}-{int(seconds)} Berry-Mappemonde"}],
        "chars": 20 + int(seconds or 0),
        "source": "rules",
        "targetSeconds": int(seconds or 0),
    }


def test_compute_film_runs_outside_a_live_loop(tmp_path, monkeypatch):
    """Une boucle déjà ouverte ne fait plus renvoyer None sans calculer."""
    import asyncio
    import film_script

    store = OfficialStore(DiskBackend(tmp_path / "disk"), now=lambda: NOW)
    monkeypatch.setattr(official_store, "_INSTANCE", store)
    voy = _film_voy()
    monkeypatch.setattr(official_store, "_load_official", lambda: voy)

    async def fake(*, lang="fr", seconds=150, **_k):
        return _film_plan(lang, seconds)

    monkeypatch.setattr(film_script, "official_film", fake)

    async def inside():
        assert asyncio.get_running_loop() is not None
        return official_store.compute_film(voy, NOW)

    payload = asyncio.run(inside())
    assert payload is not None
    assert payload["variants"]["fr"]["150"]["chapters"]
    assert payload["variants"]["en"]["0"]["chapters"]


def test_compute_film_one_variant_at_a_time_with_timeout(tmp_path, monkeypatch):
    """La variante qui dépasse le délai est sautée ; la 2:30 déjà faite reste."""
    import asyncio
    import time
    import film_script

    store = OfficialStore(DiskBackend(tmp_path / "disk"), now=lambda: NOW)
    monkeypatch.setattr(official_store, "_INSTANCE", store)
    voy = _film_voy()
    monkeypatch.setattr(official_store, "_load_official", lambda: voy)
    monkeypatch.setenv("NAVIGUIDE_FILM_VARIANT_TIMEOUT_S", "0.25")
    monkeypatch.setenv("NAVIGUIDE_FILM_PROGRESS_PUT", "1")
    order = []
    state = {"n": 0, "max": 0}

    async def fake(*, lang="fr", seconds=150, **_k):
        state["n"] += 1
        state["max"] = max(state["max"], state["n"])
        order.append((lang, int(seconds or 0)))
        try:
            if lang == "fr" and int(seconds or 0) == 0:
                await asyncio.sleep(30)
            return _film_plan(lang, seconds)
        finally:
            state["n"] -= 1

    monkeypatch.setattr(film_script, "official_film", fake)
    t0 = time.monotonic()
    payload = official_store.compute_film(voy, NOW)
    elapsed = time.monotonic() - t0
    assert elapsed < 5, elapsed
    assert state["max"] == 1
    assert order[0] == ("fr", 150)
    assert order.index(("fr", 0)) > order.index(("fr", 150))
    assert payload is not None
    assert "150" in payload["variants"]["fr"]
    assert "0" not in payload["variants"]["fr"]
    assert "0" in payload["variants"]["en"]
    hit = store.get("film", store.family_key("film", voy, NOW))
    stored = (hit or {}).get("payload") or {}
    assert "150" in (stored.get("variants") or {}).get("fr", {})
    assert "0" not in (stored.get("variants") or {}).get("fr", {})


def test_compute_film_keeps_stored_variant_when_the_only_one_times_out(tmp_path, monkeypatch):
    import asyncio
    import film_script

    store = OfficialStore(DiskBackend(tmp_path / "disk"), now=lambda: NOW)
    monkeypatch.setattr(official_store, "_INSTANCE", store)
    voy = _film_voy()
    monkeypatch.setattr(official_store, "_load_official", lambda: voy)
    monkeypatch.setenv("NAVIGUIDE_FILM_ONLY", "fr:0")
    monkeypatch.setenv("NAVIGUIDE_FILM_VARIANT_TIMEOUT_S", "0.2")
    kept = _film_plan("fr", 150)
    variants = {"fr": {"150": kept, "180": _film_plan("fr", 180)}}
    payload = official_store._film_payload_from_variants(variants)
    store.put("film", payload, store.family_key("film", voy, NOW))

    async def hang(*, lang="fr", seconds=0, **_k):
        await asyncio.sleep(30)
        return _film_plan(lang, seconds)

    monkeypatch.setattr(film_script, "official_film", hang)
    out = official_store.compute_film(voy, NOW)
    assert out is not None
    assert out["variants"]["fr"]["150"]["chapters"]
    assert out["variants"]["fr"]["180"]["chapters"]
    hit = store.get("film", store.family_key("film", voy, NOW))
    assert (hit or {}).get("payload", {}).get("variants", {}).get("fr", {}).get("150")


def test_compute_one_variant_uses_a_process_outside_pytest(monkeypatch):
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    seen = {}

    def fake_run(target, args, timeout_s):
        seen["target"] = target
        seen["args"] = args
        seen["timeout"] = timeout_s
        return True, ("ok", _film_plan("fr", 150))

    monkeypatch.setattr(official_store, "run_bounded_process", fake_run)
    plan = official_store._compute_one_variant("fr", 150, 12)
    assert seen["target"] is official_store._film_variant_worker
    assert seen["args"][0] == "fr"
    assert seen["args"][1] == 150
    assert seen["timeout"] == 17
    assert plan["chapters"]


def test_run_bounded_process_stops_a_hung_variant():
    import time

    t0 = time.monotonic()
    finished, value = official_store.run_bounded_process(
        official_store._bounded_sleep_worker, (30,), 0.6,
    )
    assert finished is False
    assert value is None
    assert time.monotonic() - t0 < 8


def test_run_bounded_process_returns_a_plan_bigger_than_the_pipe():
    """Un plan déjà calculé, plus gros que le tampon du tube, doit être lu.

    L'ancienne attente du fils avant la file tuait ce plan au délai
    (un 150 s du stock dépasse déjà ~70 Ko une fois sérialisé).
    """
    import time

    t0 = time.monotonic()
    finished, value = official_store.run_bounded_process(
        official_store._bounded_blob_worker, (80_000,), 3.0,
    )
    assert finished is True
    assert time.monotonic() - t0 < 3
    assert isinstance(value, tuple) and value[0] == "ok"
    assert len(value[1]["chapters"][0]["text"]) == 80_000


def test_prepare_forces_film_once_and_accepts_one_variant(tmp_path, monkeypatch):
    import importlib.util
    import sys

    monkeypatch.setenv("NAVIGUIDE_OFFICIAL_STORE_DIR", str(tmp_path / "store"))
    monkeypatch.delenv("NAVIGUIDE_FILM_ONLY", raising=False)
    worker_before = os.environ.get("NAVIGUIDE_OFFICIAL_WORKER")
    path = Path(__file__).resolve().parents[2] / "scripts" / "prepare_official_store.py"
    spec = importlib.util.spec_from_file_location("prepare_official_store_film", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    if worker_before is None:
        os.environ.pop("NAVIGUIDE_OFFICIAL_WORKER", None)
    else:
        os.environ["NAVIGUIDE_OFFICIAL_WORKER"] = worker_before
    calls = []

    def refresh_missing(**kwargs):
        calls.append(("missing", kwargs.get("skip")))
        return {"families": {}}

    def refresh_family(*_a, **kwargs):
        calls.append(("film", kwargs.get("force")))
        return official_store.READY

    monkeypatch.setattr(official_store, "refresh_missing", refresh_missing)
    monkeypatch.setattr(official_store, "refresh_family", refresh_family)
    monkeypatch.setattr(official_store, "family_status", lambda: {"families": {}})
    monkeypatch.setattr(
        "ici_engine.ensure_pearl_amp_layer_sig", lambda *_a, **_k: "x",
    )
    mod.one_pass(force_film=True)
    assert calls[0] == ("missing", ("film",))
    assert ("film", True) in calls

    monkeypatch.setattr(mod.signal, "signal", lambda *_a, **_k: None)
    monkeypatch.setattr(mod, "_arm_parent_watch", lambda: None)
    monkeypatch.setattr(mod, "one_pass", lambda **_k: 0)
    monkeypatch.setattr(official_store, "reset_store", lambda: None)
    monkeypatch.setattr(sys, "argv", ["prepare_official_store.py", "--film-only", "en:150", "--nice", "0"])
    try:
        assert mod.main() == 0
        assert os.environ["NAVIGUIDE_FILM_ONLY"] == "en:150"
    finally:
        os.environ.pop("NAVIGUIDE_FILM_ONLY", None)
    monkeypatch.setattr(sys, "argv", ["prepare_official_store.py", "--film-only", "de:10", "--nice", "0"])
    with pytest.raises(SystemExit):
        mod.main()


def _load_prepare_script(monkeypatch, tmp_path, name: str):
    import importlib.util

    monkeypatch.setenv("NAVIGUIDE_OFFICIAL_STORE_DIR", str(tmp_path / "store"))
    monkeypatch.delenv("SIMULATOR_MONGO_URL", raising=False)
    monkeypatch.delenv("NAVIGUIDE_FILM_ONLY", raising=False)
    worker_before = os.environ.get("NAVIGUIDE_OFFICIAL_WORKER")
    path = Path(__file__).resolve().parents[2] / "scripts" / "prepare_official_store.py"
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    if worker_before is None:
        os.environ.pop("NAVIGUIDE_OFFICIAL_WORKER", None)
    else:
        os.environ["NAVIGUIDE_OFFICIAL_WORKER"] = worker_before
    monkeypatch.setattr(mod.signal, "signal", lambda *_a, **_k: None)
    monkeypatch.setattr(mod, "_arm_parent_watch", lambda: None)
    monkeypatch.setattr(
        "ici_engine.ensure_pearl_amp_layer_sig", lambda *_a, **_k: "3769",
    )
    return mod


def test_rebuild_film_journal_shows_variant_nemotron_and_store(tmp_path, monkeypatch):
    """Une variante : le journal dit la variante, l'appel Nemotron, l'écriture. Pas d'appel réseau."""
    import sys
    import film_script

    mod = _load_prepare_script(monkeypatch, tmp_path, "prepare_rebuild_journal")
    official_store.reset_film_journal()
    official_store.reset_store()
    monkeypatch.setenv("NAVIGUIDE_FILM_PROGRESS_PUT", "1")
    monkeypatch.setenv("NAVIGUIDE_FILM_VARIANT_TIMEOUT_S", "2")
    monkeypatch.setattr(official_store, "_load_official", lambda: _film_voy())
    paid = {"n": 0}
    seen = []

    async def no_network(*_a, **_k):
        paid["n"] += 1
        raise AssertionError("appel Nemotron réel")

    def compute(lang, seconds, timeout_s):
        seen.append((lang, int(seconds)))
        return _film_plan(lang, seconds)

    monkeypatch.setattr(film_script, "write_with_llm", no_network)
    monkeypatch.setattr(official_store, "_compute_one_variant", compute)
    monkeypatch.setattr(sys, "argv", [
        "prepare_official_store.py", "--rebuild-film", "fr:150", "--nice", "0",
    ])
    try:
        assert mod.main() == 0
    finally:
        os.environ.pop("NAVIGUIDE_FILM_ONLY", None)
    assert seen == [("fr", 150)]
    assert paid["n"] == 0
    blob = "\n".join(official_store.film_journal())
    variant_at = blob.index("variante fr 150s")
    nemotron_at = blob.index("appel Nemotron fr 150s")
    stored_at = blob.index("écriture stock fr 150s chapitres=1")
    assert variant_at < nemotron_at < stored_at
    assert "arrêt" not in blob
    assert "non rangée" not in blob
    hit = official_store.get("film")
    chapters = (((hit or {}).get("payload") or {}).get("variants") or {}).get("fr", {}).get("150", {}).get("chapters")
    assert chapters and "Berry-Mappemonde" in chapters[0]["text"]


def test_rebuild_film_stall_fails_the_command(tmp_path, monkeypatch):
    """Sans ligne de progrès avant le délai, la commande s'arrête avec une erreur lisible."""
    import sys
    import time

    mod = _load_prepare_script(monkeypatch, tmp_path, "prepare_rebuild_stall")
    official_store.reset_film_journal()
    monkeypatch.setenv("NAVIGUIDE_FILM_VARIANT_TIMEOUT_S", "0.25")
    monkeypatch.setattr(official_store, "_load_official", lambda: _film_voy())
    called = {"nemotron": 0}

    def hang(lang, seconds, timeout_s):
        official_store._STEP_CANCEL.wait(2)
        return _film_plan(lang, seconds)

    def nemotron(*_a, **_k):
        called["nemotron"] += 1
        return None

    monkeypatch.setattr(official_store, "_compute_one_variant", hang)
    monkeypatch.setattr(official_store, "_nemotron_for_variant", nemotron)
    monkeypatch.setattr(sys, "argv", [
        "prepare_official_store.py", "--rebuild-film", "en:180", "--nice", "0",
    ])
    t0 = time.monotonic()
    try:
        code = mod.main()
    finally:
        os.environ.pop("NAVIGUIDE_FILM_ONLY", None)
    elapsed = time.monotonic() - t0
    assert code == 1
    assert elapsed < 3, elapsed
    blob = "\n".join(official_store.film_journal())
    assert "variante en 180s" in blob
    assert "aucun progrès avant le délai maximum" in blob
    assert "arrêt" in blob
    assert "écriture stock" not in blob
    assert "appel Nemotron" not in blob
    assert called["nemotron"] == 0


def test_rebuild_film_rejects_anything_but_one_variant(tmp_path, monkeypatch):
    import sys

    mod = _load_prepare_script(monkeypatch, tmp_path, "prepare_rebuild_reject")
    monkeypatch.setattr(mod, "one_pass", lambda **_k: (_ for _ in ()).throw(AssertionError("passe entière")))
    monkeypatch.setattr(sys, "argv", [
        "prepare_official_store.py", "--rebuild-film", "de:10", "--nice", "0",
    ])
    with pytest.raises(SystemExit):
        mod.main()
    monkeypatch.setattr(sys, "argv", [
        "prepare_official_store.py", "--rebuild-film", "fr:150,en:180", "--nice", "0",
    ])
    with pytest.raises(SystemExit):
        mod.main()
    monkeypatch.setattr(sys, "argv", [
        "prepare_official_store.py", "--rebuild-film", "fr:150", "--film-only", "en:180", "--nice", "0",
    ])
    with pytest.raises(SystemExit):
        mod.main()


def test_film_progress_line_resets_the_silence_deadline(tmp_path, monkeypatch):
    """Une ligne au milieu remet le délai : deux silences courts ne sont pas un blocage."""
    import time

    store = OfficialStore(DiskBackend(tmp_path / "disk"), now=lambda: NOW)
    monkeypatch.setattr(official_store, "_INSTANCE", store)
    monkeypatch.setenv("NAVIGUIDE_FILM_VARIANT_TIMEOUT_S", "1.5")
    monkeypatch.setenv("NAVIGUIDE_FILM_PROGRESS_PUT", "1")
    official_store.reset_film_journal()

    def slow(lang, seconds, _timeout_s):
        time.sleep(1.0)
        official_store._film_say(f"calcul {lang} {int(seconds)}s")
        time.sleep(1.0)
        return _film_plan(lang, seconds)

    monkeypatch.setattr(official_store, "_compute_one_variant", slow)
    t0 = time.monotonic()
    payload = official_store.rebuild_film_variant("fr", 150, voy=_film_voy(), now=NOW)
    assert time.monotonic() - t0 < 4
    assert payload["variants"]["fr"]["150"]["chapters"]
    blob = "\n".join(official_store.film_journal())
    assert "calcul fr 150s" in blob
    assert "appel Nemotron fr 150s" in blob
    assert "écriture stock fr 150s" in blob
    assert "arrêt" not in blob


def test_child_progress_line_extends_only_the_rebuild_deadline():
    """Une ligne du fils remet le délai de la fabrication. Le délai dur de la boucle, non."""
    import time

    official_store.reset_film_journal()
    t0 = time.monotonic()
    finished, value = official_store.run_bounded_process(
        official_store._bounded_progress_worker,
        (4, 0.8),
        2.5,
        follow_progress=True,
    )
    assert time.monotonic() - t0 < 8
    assert finished is True
    assert isinstance(value, tuple) and value[0] == "ok"
    assert value[1]["chapters"][0]["text"] == "Berry-Mappemonde"
    followed = "\n".join(official_store.film_journal())
    assert "calcul 0" in followed and "calcul 3" in followed

    official_store.reset_film_journal()
    t1 = time.monotonic()
    cut, empty = official_store.run_bounded_process(
        official_store._bounded_progress_worker,
        (4, 0.8),
        2.5,
        follow_progress=False,
    )
    assert time.monotonic() - t1 < 6
    assert cut is False and empty is None
    hard = "\n".join(official_store.film_journal())
    assert "calcul 0" in hard
    assert "calcul 3" not in hard


def test_rebuild_sees_a_progress_line_written_in_the_child(tmp_path, monkeypatch):
    """La fabrication ne s'arrête pas si le fils a écrit avant le délai."""
    import time

    store = OfficialStore(DiskBackend(tmp_path / "disk"), now=lambda: NOW)
    monkeypatch.setattr(official_store, "_INSTANCE", store)
    monkeypatch.setenv("NAVIGUIDE_OFFICIAL_STORE_DIR", str(tmp_path / "store"))
    monkeypatch.setenv("NAVIGUIDE_FILM_VARIANT_TIMEOUT_S", "2.5")
    monkeypatch.setenv("NAVIGUIDE_FILM_PROGRESS_PUT", "1")
    monkeypatch.delenv("SIMULATOR_MONGO_URL", raising=False)
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    official_store.reset_film_journal()
    official_store.reset_store()
    monkeypatch.setattr(official_store, "_INSTANCE", store)
    seen = {}
    real_run = official_store.run_bounded_process

    def run_progress(target, args, timeout_s, follow_progress=False):
        seen["follow"] = follow_progress
        return real_run(
            official_store._bounded_progress_worker,
            (4, 0.8),
            timeout_s,
            follow_progress=follow_progress,
        )

    monkeypatch.setattr(official_store, "run_bounded_process", run_progress)
    monkeypatch.setattr(official_store, "_nemotron_for_variant", lambda *_a, **_k: None)
    t0 = time.monotonic()
    payload = official_store.rebuild_film_variant("fr", 150, voy=_film_voy(), now=NOW)
    assert time.monotonic() - t0 < 8
    assert seen["follow"] is True
    assert payload["variants"]["fr"]["150"]["chapters"]
    blob = "\n".join(official_store.film_journal())
    assert "variante fr 150s" in blob
    assert "calcul 0" in blob and "calcul 3" in blob
    assert "appel Nemotron fr 150s" in blob
    assert "écriture stock fr 150s" in blob
    assert "arrêt" not in blob
    assert official_store._FOLLOW_FILM_PROGRESS is False


def _rg17_voy():
    return {
        "t0": T0,
        "points": [{"lat": -22.27, "lon": 166.44}],
        "marks": [{"name": "Nouméa", "iso": "2026-10-12T00:00:00Z"}],
        "clock": {
            "t0": T0,
            "marks": [{"name": "Nouméa", "iso": "2026-10-12T00:00:00Z"}],
        },
    }


def test_rg17_compute_eta_writes_unavailable_and_skips_retry(tmp_path, monkeypatch):
    import ensemble_eta

    store = OfficialStore(DiskBackend(tmp_path / "disk"), now=lambda: NOW)
    official_store.reset_store()
    monkeypatch.setattr(official_store, "_INSTANCE", store)
    voy = _rg17_voy()
    monkeypatch.setattr(official_store, "_load_official", lambda: voy)
    future = "2026-09-27T00:15:00Z"
    preheats = {"n": 0}

    def fake_preheat(*_a, **_k):
        preheats["n"] += 1
        return {
            "members": 0, "p10": None, "p50": None, "p90": None,
            "reason": "quota", "nextRetry": future,
            "detail": "Daily API request limit exceeded",
            "computedAt": "2026-09-26T12:00:00Z",
        }

    def fake_peek(*_a, **_k):
        return {
            "members": 0, "p10": None, "p50": None, "p90": None,
            "reason": "quota", "nextRetry": future,
            "detail": "Daily API request limit exceeded",
            "computedAt": "2026-09-26T12:00:00Z",
        }

    monkeypatch.setattr(ensemble_eta, "preheat_official_eta", fake_preheat)
    monkeypatch.setattr(ensemble_eta, "peek_official_eta", fake_peek)
    monkeypatch.setattr(ensemble_eta, "next_official_stop", lambda *_a, **_k: "Nouméa")

    payload = official_store.compute_eta(voy, NOW)
    assert payload is not None
    stop = payload["stops"]["Nouméa"]
    assert stop["members"] == 0
    assert stop["status"] == UNAVAILABLE
    assert stop["p10"] is None and stop["p90"] is None
    assert stop["reason"] == "quota Open-Meteo atteint"
    assert stop["nextRetry"] == future
    assert preheats["n"] == 0

    key = store.family_key("eta", voy, NOW)
    store.put("eta", payload, key)
    again = official_store.refresh_family(
        "eta", compute=official_store.compute_eta, now=NOW, store=store, voy=voy,
    )
    assert again == "unchanged"
    assert preheats["n"] == 0

    served = official_store.serve_eta("Nouméa")
    assert served["status"] == UNAVAILABLE
    assert served["members"] == 0
    assert served.get("p10") is None
    assert served["reason"] == "quota Open-Meteo atteint"
    assert served["nextRetry"] == future
    assert served["status"] != PREPARING


def test_rg17_compute_eta_ready_when_members(tmp_path, monkeypatch):
    import ensemble_eta

    store = OfficialStore(DiskBackend(tmp_path / "disk"), now=lambda: NOW)
    official_store.reset_store()
    monkeypatch.setattr(official_store, "_INSTANCE", store)
    voy = _rg17_voy()
    monkeypatch.setattr(official_store, "_load_official", lambda: voy)

    def fake_peek(*_a, **_k):
        return {
            "members": 24,
            "p10": "2026-10-11T00:00:00Z",
            "p50": "2026-10-12T12:00:00Z",
            "p90": "2026-10-14T00:00:00Z",
            "source": "open-meteo-ensemble",
            "computedAt": "2026-09-26T12:00:00Z",
            "memberKnots": [8.0, 8.1],
        }

    monkeypatch.setattr(ensemble_eta, "preheat_official_eta", lambda *_a, **_k: fake_peek())
    monkeypatch.setattr(ensemble_eta, "peek_official_eta", fake_peek)
    monkeypatch.setattr(ensemble_eta, "next_official_stop", lambda *_a, **_k: "Nouméa")

    payload = official_store.compute_eta(voy, NOW)
    stop = payload["stops"]["Nouméa"]
    assert stop["status"] == READY
    assert stop["members"] == 24
    assert stop["p10"] and stop["p90"]
    assert stop["reason"] is None
    key = store.family_key("eta", voy, NOW)
    store.put("eta", payload, key)
    served = official_store.serve_eta("Nouméa")
    assert served["status"] == READY
    assert served["members"] == 24
    assert served["p10"].startswith("2026-10-11")


# ── un seul remplisseur par machine (29 sept. : quatre écrivaient le même stock) ─────────────────────────────

def test_other_fill_processes_lists_every_loop_worker_but_us(monkeypatch):
    import subprocess
    import official_store as os_

    fake = (
        f"  111 python3 /Users/x/bim-lots/rg16/naviguide-simulator/scripts/{os_.FILL_SCRIPT.name} --loop --period 21600 --store /S\n"
        f"  222 python3 /Users/x/bim-lots/rc28/naviguide-simulator/scripts/{os_.FILL_SCRIPT.name} --loop --period 21600 --store /S\n"
        f"  333 python3 /Users/x/bim-lots/dc3/naviguide-simulator/scripts/{os_.FILL_SCRIPT.name} --store /S\n"
        f"  555 python3 /Users/x/bim-lots/dm3/naviguide-simulator/scripts/{os_.FILL_SCRIPT.name} --loop --period 21600 --store /agent\n"
        f"  666 .venv/bin/python scripts/{os_.FILL_SCRIPT.name}\n"
        "  444 /usr/bin/uvicorn server.main:app\n"
    )

    class _Out:
        stdout = fake

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _Out())
    assert os_.other_fill_processes(store=Path("/S")) == [111, 222, 333]
    assert os_.other_fill_processes(keep=222, store=Path("/S")) == [111, 333]
    assert os_.other_fill_processes(store=Path("/autre")) == [], "un autre stock : pas touché"
    home = Path.home() / ".cache" / "naviguide" / "voyage-store"
    assert os_.other_fill_processes(store=home) == [666]


def test_stop_other_fill_processes_terms_then_kills(monkeypatch):
    import signal
    import official_store as os_

    sent: list[tuple[int, int]] = []
    alive = {111: True}

    def fake_kill(pid, sig):
        sent.append((pid, sig))
        if sig == signal.SIGKILL:
            alive[pid] = False

    monkeypatch.setattr(os_, "other_fill_processes", lambda keep=None, store=None: [111])
    monkeypatch.setattr(os_, "_alive", lambda pid: alive.get(pid, False))
    monkeypatch.setattr(os_.os, "kill", fake_kill)
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)   # le garde-fou pytest est testé à part
    monkeypatch.delenv("CI", raising=False)
    assert os_.stop_other_fill_processes(keep=999, grace_s=0.2) == [111]
    assert sent[0] == (111, signal.SIGTERM) and sent[-1] == (111, signal.SIGKILL)


def test_stop_other_fill_processes_is_a_noop_under_pytest(monkeypatch):
    import official_store as os_
    monkeypatch.setattr(os_, "other_fill_processes", lambda keep=None, store=None: (_ for _ in ()).throw(AssertionError("ps appelé sous pytest")))
    assert os_.stop_other_fill_processes() == []


# ── HC1 — passé réel figé + avenir déterministe dans la famille climo ───


def _hc1_bind_om(published_until: str, era5_kn: float = 20.0):
    import httpx
    from hindcast import bind_http

    def _hours(start, end):
        from datetime import datetime as _dt, timedelta as _td
        d = _dt.fromisoformat(start).date()
        last = _dt.fromisoformat(end).date()
        out = []
        while d <= last:
            out.extend(f"{d.isoformat()}T{h:02d}:00" for h in range(24))
            d += _td(days=1)
        return out

    def handler(request: httpx.Request) -> httpx.Response:
        params = dict(request.url.params)
        times = _hours(params.get("start_date"), params.get("end_date") or params.get("start_date"))
        speeds = [era5_kn if iso[:10] <= published_until else None for iso in times]
        return httpx.Response(200, json={"hourly": {
            "time": times,
            "wind_speed_10m": speeds,
            "wind_direction_10m": [0.0] * len(times),
            "wind_gusts_10m": [None if s is None else s + 3 for s in speeds],
        }})

    bind_http(lambda: httpx.Client(transport=httpx.MockTransport(handler)))


def _hc1_official_voy():
    from voyage_clock import OFFICIAL_VOYAGE_ID
    return {
        "voyageId": OFFICIAL_VOYAGE_ID,
        "t0": T0,
        "points": [
            {"lat": 46.15, "lon": -1.16, "cumNm": 0, "filmCum": 0, "jump": False},
            {"lat": 46.15, "lon": -13.5, "cumNm": 500, "filmCum": 500, "jump": False},
            {"lat": 46.15, "lon": -38.0, "cumNm": 1520, "filmCum": 1520, "jump": False},
        ],
        # La boucle FINIT à La Rochelle : l'horloge « avenir » ne doit pas
        # pivoter dessus (régression attrapée sur la vraie route).
        "marks": [{"name": "La Rochelle", "nm": 1520, "lat": 46.15, "lon": -38.0}],
        "startAt": "saint-maur",
        "expedition_id": "berry-mappemonde-2026",
        "official": True,
        "routeRev": 0,
    }


def test_hc1_compute_climo_real_past_then_climatology_future(monkeypatch):
    from datetime import timedelta
    from hindcast import reset_hooks
    from voyage_clock import parse_iso

    monkeypatch.setenv("NAVIGUIDE_HINDCAST", "1")
    reset_hooks()
    now = parse_iso(T0) + timedelta(days=10)
    frontier = (now - timedelta(days=6)).strftime("%Y-%m-%d")
    _hc1_bind_om(frontier)
    voy = _hc1_official_voy()

    payload = official_store.compute_climo(dict(voy), now)
    assert payload is not None
    clock = payload["clock"]
    assert clock["realUntil"] == frontier
    assert payload["realUntil"] == frontier
    assert payload["hindcastStatus"] == "ready"      # 5/5 jours publiés intégrés
    assert payload["hindcastCoverage"] == "5/5"
    assert payload["hindcastReason"] is None
    assert clock["hindcastCoverage"] == "5/5"
    regimes = [v.get("regime") for v in clock["vertices"] if (v.get("speedKnots") or 0) > 0]
    assert "hindcast" in regimes and "climatology" in regimes
    # Le réel d'abord, la climatologie ensuite — jamais mélangés.
    first_climo = regimes.index("climatology")
    assert all(r == "climatology" for r in regimes[first_climo:])
    # La frontière réel/climatologie tombe au dernier jour publié.
    real_verts = [v for v in clock["vertices"] if v.get("regime") == "hindcast"]
    assert real_verts[-1]["iso"][:10] >= frontier
    # tHours et sailNm restent monotones à la couture.
    ts = [v["tHours"] for v in clock["vertices"]]
    assert ts == sorted(ts)
    # L'avenir va jusqu'au BOUT de la route : la marque d'arrivée
    # « La Rochelle » ne doit pas faire pivoter l'horloge climatologique.
    assert abs(clock["vertices"][-1]["lon"] - (-38.0)) < 0.1
    assert clock["arrivalIso"][:10] > frontier
    # Statut honnête rangé sur le voyage (GET /voyage/official).
    from voyage_store import load_voyage
    from voyage_clock import OFFICIAL_VOYAGE_ID
    saved = load_voyage(OFFICIAL_VOYAGE_ID)
    assert saved["hindcastStatus"] == "ready"
    assert saved["hindcastCoverage"] == "5/5"

    # Deux calculs successifs : la MÊME horloge (position du jour identique).
    second = official_store.compute_climo(dict(voy), now)
    assert second["clock"]["vertices"] == clock["vertices"]
    assert second["clock"]["arrivalIso"] == clock["arrivalIso"]
    reset_hooks()


def test_hc1_atlas_degraded_serves_yesterday_clock(monkeypatch):
    from datetime import timedelta
    from hindcast import reset_hooks
    from voyage_clock import OFFICIAL_VOYAGE_ID, parse_iso
    from voyage_store import load_voyage, save_voyage
    import real_track

    monkeypatch.setenv("NAVIGUIDE_HINDCAST", "1")
    reset_hooks()
    now = parse_iso(T0) + timedelta(days=10)
    frontier = (now - timedelta(days=6)).strftime("%Y-%m-%d")
    _hc1_bind_om(frontier)
    voy = _hc1_official_voy()
    save_voyage(dict(voy))

    # « La veille » : une horloge calculée avec un atlas complet (ratio 1.0).
    official_store.put("climo", {"clock": {"t0": T0, "vertices": [
        {"lat": 46.15, "lon": -1.16, "iso": T0, "tHours": 0, "sailNm": 0},
    ]}, "regimes": [], "fiches": [], "atlasRatio": 1.0})

    # Aujourd'hui l'atlas est mort (port 9) : tout l'avenir partirait en zones
    # → on NE recalcule PAS, on garde l'horloge de la veille, le statut le dit.
    out = official_store.compute_climo(dict(voy), now)
    assert out is None
    saved = load_voyage(OFFICIAL_VOYAGE_ID)
    assert "horloge de la veille" in (saved.get("hindcastReason") or "")
    assert official_store.stored_clock() is not None  # la veille reste servie

    # Atlas complet à nouveau → recalcul accepté.
    monkeypatch.setattr(real_track, "atlas_ratio", lambda f: 1.0)
    again = official_store.compute_climo(dict(voy), now)
    assert again is not None
    assert again["clock"]["realUntil"] == frontier
    reset_hooks()


def test_rc34_stale_climo_without_real_until_is_recomputed(tmp_path, monkeypatch):
    """Un climo du jour sans realUntil n'est pas `unchanged` —
    compute_climo tourne (faux ERA5 HC1), le payload rangé a realUntil ;
    un second refresh avec realUntil → unchanged. L'ancienne horloge reste
    servie tant que put n'a pas eu lieu."""
    from datetime import timedelta
    from hindcast import reset_hooks
    from voyage_clock import parse_iso
    from voyage_store import save_voyage

    monkeypatch.setenv("NAVIGUIDE_HINDCAST", "1")
    reset_hooks()
    now = parse_iso(T0) + timedelta(days=10)
    frontier = (now - timedelta(days=6)).strftime("%Y-%m-%d")
    _hc1_bind_om(frontier)
    voy = _hc1_official_voy()
    save_voyage(dict(voy))

    store = OfficialStore(DiskBackend(tmp_path / "climo-rc34"), now=lambda: now)
    key = store.family_key("climo", voy, now)
    stale = {
        "clock": {
            "t0": T0,
            "kind": "climatology",
            "vertices": [
                {"lat": 46.15, "lon": -1.16, "iso": T0, "regime": "climatology"},
            ],
        },
        "regimes": [],
        "fiches": [],
    }
    store.put("climo", stale, key)
    before = store.get("climo", key)
    assert "realUntil" not in (before["payload"].get("clock") or {})
    assert "realUntil" not in before["payload"]
    stale_n = len((before["payload"].get("clock") or {}).get("vertices") or [])

    status = official_store.refresh_family(
        "climo", now=now, store=store, voy=voy, force=False,
    )
    assert status != "unchanged"
    assert status == READY
    hit = store.get("climo", key)
    payload = hit["payload"]
    assert payload["clock"]["realUntil"] == frontier
    assert payload["realUntil"] == frontier
    assert len(payload["clock"]["vertices"]) > stale_n

    again = official_store.refresh_family(
        "climo", now=now, store=store, voy=voy, force=False,
    )
    assert again == "unchanged"
    reset_hooks()


def test_rc34_clock_get_nudges_when_climo_lacks_real_until(client, monkeypatch):
    """GET /voyage/official/clock sert l'horloge déjà rangée et nudge le
    remplisseur si realUntil manque (hindcast actif) — jamais de recalcul HTTP."""
    kicks = {"n": 0}
    monkeypatch.setenv("NAVIGUIDE_HINDCAST", "1")
    monkeypatch.delenv("NAVIGUIDE_FORECAST_BACKEND", raising=False)
    monkeypatch.setattr(official_store, "kick_worker", lambda: kicks.__setitem__("n", kicks["n"] + 1))

    official_store.put("climo", _payload("climo"))
    r = client.get("/voyage/official/clock")
    assert r.status_code == 200
    body = r.json()
    assert body["t0"].startswith("2026-05-15")
    assert "realUntil" not in body
    assert kicks["n"] >= 1

    kicks["n"] = 0
    official_store.put("climo", {
        "clock": {
            "t0": T0,
            "vertices": [{"lat": 46.15, "lon": -1.16, "iso": T0}],
            "realUntil": "2026-10-09",
        },
        "regimes": [],
        "fiches": [],
        "realUntil": "2026-10-09",
    })
    r2 = client.get("/voyage/official/clock")
    assert r2.status_code == 200
    assert r2.json().get("realUntil") == "2026-10-09"
    assert kicks["n"] == 0


def test_rc34_ensure_track_none_keeps_climatology_empty(monkeypatch):
    """Pas de vent réel → horloge climatologique + statut empty, jamais ready à vide."""
    from datetime import timedelta
    from hindcast import reset_hooks
    from voyage_clock import parse_iso
    import real_track

    monkeypatch.setenv("NAVIGUIDE_HINDCAST", "1")
    reset_hooks()
    monkeypatch.setattr(real_track, "ensure_track", lambda *a, **k: None)
    now = parse_iso(T0) + timedelta(days=10)
    voy = _hc1_official_voy()
    payload = official_store.compute_climo(dict(voy), now)
    assert payload is not None
    clock = payload["clock"]
    regimes = {(v.get("regime") or v.get("kind")) for v in clock.get("vertices") or []}
    assert "hindcast" not in regimes
    assert payload["hindcastStatus"] == "empty"
    assert payload["hindcastStatus"] != "ready"
    assert payload.get("realUntil") is None
    assert "realUntil" in payload
    assert "realUntil" in clock
    cov = str(payload.get("hindcastCoverage") or "")
    assert cov.startswith("0/")
    reset_hooks()


def _rg11a_raw_plan(text=None):
    body = text or (
        "Le 15 mai, Berry-Mappemonde quitte La Rochelle, cap au sud-ouest. "
        "Arrivée à Ajaccio le 26 mai."
    )
    return {
        "chapters": [{
            "id": "c0",
            "text": body,
            "tA": T0,
            "tB": T0,
            "fromName": "La Rochelle",
            "toName": "Ajaccio (Corse)",
            "anchors": [{"charIdx": 0, "t": T0}, {"charIdx": 60, "t": T0}],
        }],
        "source": "rules",
        "chars": len(body),
        "targetSeconds": 150,
        "hasWritten": False,
    }


def _rg11a_payload(plan=None):
    plan = plan or _rg11a_raw_plan()
    return {
        "fr": plan, "default": plan,
        "variants": {"fr": {"150": plan, "180": plan, "0": plan}},
        "estimates": {"fr": {"150": {"chars": plan["chars"], "estimatedSeconds": 10}}},
    }


async def _rg11a_honest_cascade(system, user, **kw):
    import json
    import re
    if "real stops" in (system or ""):
        return '{"ok": true, "faults": []}', "nemotron-super"
    match = re.search(r"sentences=(\[.*\])", user or "", re.S)
    sents = json.loads(match.group(1)) if match else ["ok."]
    return " ".join(
        s.replace("quitte", "laisse", 1) if "quitte" in s else s for s in sents
    ), "nemotron-super"


def _rg11a_voy():
    return {
        "t0": T0, "clock": {"t0": T0, "vertices": [{"lat": 1, "lon": 2, "iso": T0}]}, "marks": [],
        "points": [{"lat": 1, "lon": 2}],
    }


def test_ed2_reservice_keeps_source_reviewed_by_and_model(tmp_path, monkeypatch):
    store = OfficialStore(DiskBackend(tmp_path / "disk-ed2"), now=lambda: NOW)
    voy = _rg11a_voy()
    monkeypatch.setattr(official_store, "_INSTANCE", store)
    monkeypatch.setattr(official_store, "_load_official", lambda: voy)
    plan = _rg11a_raw_plan()
    written = {
        **plan,
        "hasWritten": True,
        "source": "nemotron-super",
        "reviewedBy": "nemotron-ultra",
        "model": "nvidia/Nemotron-3.5-Super-VL",
        "generated_at": "2026-10-17T10:00:00Z",
    }
    payload = _rg11a_payload()
    payload["written"] = {"fr": {"150": written}}
    store.put("film", payload, store.family_key("film", voy, NOW))
    out = official_store.serve_film("fr", 150, style="written")
    assert out["status"] == READY
    assert out["hasWritten"] is True
    assert out["source"] == "nemotron-super"
    assert out["reviewedBy"] == "nemotron-ultra"
    assert out["model"] == "nvidia/Nemotron-3.5-Super-VL"
    assert out["generated_at"] == "2026-10-17T10:00:00Z"
    again = official_store.serve_film("fr", 150, style="written")
    assert again["source"] == out["source"]
    assert again["reviewedBy"] == out["reviewedBy"]
    assert again["model"] == out["model"]
    assert again["generated_at"] == out["generated_at"]

    fallback = {
        **plan,
        "hasWritten": True,
        "source": "nvidia-gpt-oss-20b",
        "model": "openai/gpt-oss-20b",
    }
    payload["written"] = {"fr": {"150": fallback}}
    store.put("film", payload, store.family_key("film", voy, NOW))
    nim = official_store.serve_film("fr", 150, style="written")
    assert nim["source"] == "nvidia-gpt-oss-20b"
    assert "Token Factory" not in nim["source"]
    assert not nim.get("reviewedBy")
    assert nim["model"] == "openai/gpt-oss-20b"

    legacy = {
        **plan,
        "hasWritten": True,
        "source": "nemotron-super-reviewed-ultra",
        "model": "nvidia/Nemotron-3.5-Super-VL",
        "generated_at": "2026-10-17T10:00:00Z",
    }
    payload["written"] = {"fr": {"150": legacy}}
    store.put("film", payload, store.family_key("film", voy, NOW))
    old = official_store.serve_film("fr", 150, style="written")
    assert old["source"] == "nemotron-super"
    assert old["reviewedBy"] == "nemotron-ultra"
    assert old["model"] == legacy["model"]
    assert old["generated_at"] == legacy["generated_at"]


def test_rg11a_serve_written_when_present(tmp_path, monkeypatch):
    import asyncio

    store = OfficialStore(DiskBackend(tmp_path / "disk"), now=lambda: NOW)
    voy = _rg11a_voy()
    monkeypatch.setattr(official_store, "_INSTANCE", store)
    monkeypatch.setattr(official_store, "_load_official", lambda: voy)
    payload = _rg11a_payload()
    key = store.family_key("film", voy, NOW)
    store.put("film", payload, key)
    asyncio.run(official_store.write_film_on_click("fr", 150, cascade=_rg11a_honest_cascade, now=NOW))
    written = official_store.serve_film("fr", 150, style="written")
    assert written["status"] == READY
    assert written["hasWritten"] is True
    assert written["source"] == official_store.WRITTEN_SOURCE
    assert written.get("writtenAt")
    assert "laisse" in (written["chapters"][0]["text"] or "")
    raw = official_store.serve_film("fr", 150, style="raw")
    assert raw["hasWritten"] is False
    assert raw["source"] == "rules"
    assert "quitte" in (raw["chapters"][0]["text"] or "")


def test_rg11a_missing_written_is_raw_not_preparing(tmp_path, monkeypatch):
    store = OfficialStore(DiskBackend(tmp_path / "disk"), now=lambda: NOW)
    voy = _rg11a_voy()
    monkeypatch.setattr(official_store, "_INSTANCE", store)
    monkeypatch.setattr(official_store, "_load_official", lambda: voy)
    payload = _rg11a_payload()
    key = store.family_key("film", voy, NOW)
    store.put("film", payload, key)
    out = official_store.serve_film("fr", 150, style="written")
    assert out["status"] == READY
    assert out["hasWritten"] is False
    assert out["source"] == "rules"
    assert out["chapters"]
    missing_variant = official_store.serve_film("en", 180, style="written")
    assert missing_variant["status"] == READY
    assert missing_variant["hasWritten"] is False


def test_rg11a_mode_off_does_not_call_llm(tmp_path, monkeypatch):
    store = OfficialStore(DiskBackend(tmp_path / "disk"), now=lambda: NOW)
    voy = _rg11a_voy()
    monkeypatch.setattr(official_store, "_INSTANCE", store)
    monkeypatch.setattr(official_store, "_load_official", lambda: voy)
    monkeypatch.setenv("NAVIGUIDE_LLM_MODE", "off")
    payload = _rg11a_payload()
    key = store.family_key("film", voy, NOW)
    store.put("film", payload, key)
    calls = {"n": 0}

    async def boom(*_a, **_k):
        calls["n"] += 1
        raise AssertionError("LLM en mode off")

    out = official_store.fill_written_film(force=True, cascade=boom, now=NOW)
    assert out["status"] == "click-only"
    assert calls["n"] == 0
    import asyncio
    served_click = asyncio.run(official_store.write_film_on_click("fr", 150, cascade=boom, now=NOW))
    assert served_click["hasWritten"] is False
    served = official_store.serve_film("fr", 150, style="written")
    assert served["hasWritten"] is False
    assert served["status"] == READY


def test_rg11a_write_cap_serves_raw(tmp_path, monkeypatch):
    store = OfficialStore(DiskBackend(tmp_path / "disk"), now=lambda: NOW)
    voy = _rg11a_voy()
    monkeypatch.setattr(official_store, "_INSTANCE", store)
    monkeypatch.setattr(official_store, "_load_official", lambda: voy)
    monkeypatch.delenv("NAVIGUIDE_LLM_MODE", raising=False)
    monkeypatch.setenv("NAVIGUIDE_LLM_DAILY_TOKENS_WRITE", "50")
    import llm_budget
    llm_budget.record("write", 50, 0)
    payload = _rg11a_payload()
    key = store.family_key("film", voy, NOW)
    store.put("film", payload, key)
    calls = {"n": 0}

    async def boom(*_a, **_k):
        calls["n"] += 1
        raise AssertionError("LLM au plafond")

    out = official_store.fill_written_film(force=True, cascade=boom, now=NOW)
    assert out["status"] == "click-only"
    assert calls["n"] == 0
    import asyncio
    served_click = asyncio.run(official_store.write_film_on_click("fr", 150, cascade=boom, now=NOW))
    assert served_click["hasWritten"] is False
    served = official_store.serve_film("fr", 150, style="written")
    assert served["hasWritten"] is False
    assert served["status"] == READY


def test_rg11a_http_style_written(client, tmp_path, monkeypatch):
    store = OfficialStore(DiskBackend(tmp_path / "http-film"), now=lambda: NOW)
    voy = _rg11a_voy()
    official_store.reset_store()
    monkeypatch.setattr(official_store, "_INSTANCE", store)
    monkeypatch.setattr(official_store, "_load_official", lambda: voy)
    payload = _rg11a_payload()
    store.put("film", payload, store.family_key("film", voy, NOW))
    import asyncio
    asyncio.run(official_store.write_film_on_click("fr", 150, cascade=_rg11a_honest_cascade, now=NOW))
    written = client.get("/voyage/official/film?lang=fr&seconds=150&style=written")
    assert written.status_code == 200
    data = written.json()
    assert data["hasWritten"] is True
    assert data["source"] == official_store.WRITTEN_SOURCE
    assert data.get("writtenAt")
    raw = client.get("/voyage/official/film?lang=fr&seconds=150&style=raw")
    assert raw.json()["hasWritten"] is False


def test_ed1_get_does_not_write(client, tmp_path, monkeypatch):
    store = OfficialStore(DiskBackend(tmp_path / "http-ed1"), now=lambda: NOW)
    voy = _rg11a_voy()
    official_store.reset_store()
    monkeypatch.setattr(official_store, "_INSTANCE", store)
    monkeypatch.setattr(official_store, "_load_official", lambda: voy)
    store.put("film", _rg11a_payload(), store.family_key("film", voy, NOW))
    calls = {"n": 0}

    async def boom(*_a, **_k):
        calls["n"] += 1
        raise AssertionError("GET a lancé la chaîne")

    monkeypatch.setattr(official_store, "write_film_on_click", boom)
    out = client.get("/voyage/official/film?lang=fr&seconds=150&style=written")
    assert out.status_code == 200
    assert out.json()["hasWritten"] is False
    assert calls["n"] == 0


def test_ed1_write_query_runs_once_then_cache(client, tmp_path, monkeypatch):
    import film_script

    store = OfficialStore(DiskBackend(tmp_path / "http-ed1-write"), now=lambda: NOW)
    voy = _rg11a_voy()
    official_store.reset_store()
    monkeypatch.setattr(official_store, "_INSTANCE", store)
    monkeypatch.setattr(official_store, "_load_official", lambda: voy)
    monkeypatch.setenv("NAVIGUIDE_LLM_MODE", "on-demand")
    monkeypatch.setenv("NAVIGUIDE_LLM_DAILY_TOKENS_JUDGE", "0")  # Ultra fermé : chemin Super seul
    store.put("film", _rg11a_payload(), store.family_key("film", voy, NOW))
    calls = {"n": 0}

    async def fake_chain(plan, *, seconds=150, cascade=None, **kwargs):
        calls["n"] += 1
        written = {
            "chapters": list(plan.get("chapters") or []),
            "source": official_store.WRITTEN_SOURCE,
            "hasWritten": True,
            "chars": 40,
            "targetSeconds": seconds,
        }
        english = {**written, "chapters": list((kwargs.get("en_raw") or {}).get("chapters") or [])}
        return written, english, {
            "super": 1, "ultra_edit": 0, "ultra_judge": 0, "lightning": 0,
            "source": official_store.WRITTEN_SOURCE, "reviewed": False,
        }

    monkeypatch.setattr(film_script, "write_film_chain", fake_chain)

    async def _noop_attach(**_kw):
        return None

    monkeypatch.setattr(official_store, "attach_film_web_context", _noop_attach)

    first = client.post("/voyage/official/film?lang=fr&seconds=150")
    assert first.status_code == 200
    body = first.json()
    # R22: first POST returns writing=True, hasWritten=False
    assert body["writing"] is True
    assert body["hasWritten"] is False

    # Second POST: task done (sync in test), cached written film served
    # Wait for background task to complete (sync in test)
    import asyncio
    asyncio.run(asyncio.sleep(0))

    # Second POST: task done (sync in test), cached written film served
    second = client.post("/voyage/official/film?lang=fr&seconds=150")
    assert second.status_code == 200
    second_body = second.json()
    assert second_body["hasWritten"] is True
    assert second_body["source"] == official_store.WRITTEN_SOURCE
    assert calls["n"] == 1

    # GET: serves cached written film
    get_only = client.get("/voyage/official/film?lang=fr&seconds=150&style=written")
    assert get_only.status_code == 200
    assert get_only.json()["hasWritten"] is True
    assert get_only.json()["source"] == official_store.WRITTEN_SOURCE
    get_en = client.get("/voyage/official/film?lang=en&seconds=150&style=written")
    assert get_en.json()["hasWritten"] is True
    assert get_only.json()["receipt"] == get_en.json()["receipt"]
    assert calls["n"] == 1


def test_film_async_write_failed_then_retry(client, tmp_path, monkeypatch):
    import asyncio
    import film_script

    store = OfficialStore(DiskBackend(tmp_path / "film-failed-retry"), now=lambda: NOW)
    voy = _rg11a_voy()
    official_store.reset_store()
    official_store._FILM_WRITE_FAILED.clear()
    monkeypatch.setattr(official_store, "_INSTANCE", store)
    monkeypatch.setattr(official_store, "_load_official", lambda: voy)
    monkeypatch.setenv("NAVIGUIDE_LLM_MODE", "on-demand")
    monkeypatch.setenv("NAVIGUIDE_LLM_DAILY_TOKENS_JUDGE", "0")
    store.put("film", _rg11a_payload(), store.family_key("film", voy, NOW))
    calls = {"n": 0}

    async def fake_chain(plan, *, seconds=150, cascade=None, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            return None, None, {"source": "rules", "super": 0}
        written = {
            "chapters": list(plan.get("chapters") or []),
            "source": official_store.WRITTEN_SOURCE,
            "hasWritten": True,
            "chars": 40,
            "targetSeconds": seconds,
        }
        return written, None, {
            "super": 1,
            "ultra_edit": 0,
            "ultra_judge": 0,
            "lightning": 0,
            "source": official_store.WRITTEN_SOURCE,
            "reviewed": False,
        }

    monkeypatch.setattr(film_script, "write_film_chain", fake_chain)

    first = client.post("/voyage/official/film?lang=fr&seconds=150")
    assert first.status_code == 200
    asyncio.run(asyncio.sleep(0))

    failed_get = client.get("/voyage/official/film?lang=fr&seconds=150&style=written")
    assert failed_get.status_code == 200
    assert failed_get.json()["status"] == "failed"
    raw_after_failure = client.get("/voyage/official/film?lang=fr&seconds=150&style=raw")
    assert raw_after_failure.json()["status"] == "ready"
    assert raw_after_failure.json()["chapters"]

    retry = client.post("/voyage/official/film?lang=fr&seconds=150")
    assert retry.status_code == 200
    assert retry.json()["status"] == "writing"
    asyncio.run(asyncio.sleep(0))

    ready = client.get("/voyage/official/film?lang=fr&seconds=150&style=written")
    assert ready.json()["status"] == "ready"
    assert ready.json()["hasWritten"] is True
    assert calls["n"] == 2


def test_film_async_fr_en_posts_share_atomic_bilingual_reservation(tmp_path, monkeypatch):
    import asyncio
    import film_script
    from film_front import post_official_film

    store = OfficialStore(DiskBackend(tmp_path / "film-bilingual-atomic"), now=lambda: NOW)
    voy = _rg11a_voy()
    official_store.reset_store()
    official_store._FILM_WRITE_TASKS.clear()
    monkeypatch.setattr(official_store, "_INSTANCE", store)
    monkeypatch.setattr(official_store, "_load_official", lambda: voy)
    monkeypatch.setenv("NAVIGUIDE_LLM_MODE", "on-demand")
    monkeypatch.setenv("NAVIGUIDE_LLM_DAILY_TOKENS_JUDGE", "0")
    store.put("film", _rg11a_payload(), store.family_key("film", voy, NOW))
    calls = {"n": 0}
    started, release = asyncio.Event(), asyncio.Event()

    async def fake_chain(plan, *, seconds=150, cascade=None, **kwargs):
        calls["n"] += 1
        started.set()
        await release.wait()
        written = {"chapters": list(plan.get("chapters") or []), "source": official_store.WRITTEN_SOURCE,
                   "hasWritten": True, "chars": 40, "targetSeconds": seconds}
        en = {**written, "chapters": list((kwargs.get("en_raw") or {}).get("chapters") or [])}
        return written, en, {"super": 1, "ultra_edit": 0, "ultra_judge": 0, "lightning": 0,
                             "source": official_store.WRITTEN_SOURCE, "reviewed": False}

    async def noop_attach(**_kw):
        return None

    monkeypatch.setattr(film_script, "write_film_chain", fake_chain)
    monkeypatch.setattr(official_store, "attach_film_web_context", noop_attach)

    async def scenario():
        fr, en = await asyncio.gather(post_official_film(lang="fr", seconds=150),
                                      post_official_film(lang="en", seconds=150))
        assert fr["status"] == en["status"] == "writing"
        await started.wait()
        # A separate worker has its own task registry but reads the shared DB.
        official_store._FILM_WRITE_TASKS.clear()
        other_worker = OfficialStore(DiskBackend(tmp_path / "film-bilingual-atomic"), now=lambda: NOW)
        monkeypatch.setattr(official_store, "_INSTANCE", other_worker)
        assert official_store.serve_film("en", 150, "written")["status"] == "writing"
        assert calls["n"] == 1
        monkeypatch.setattr(official_store, "_INSTANCE", store)
        release.set()
        for _ in range(20):
            await asyncio.sleep(0)
            if not official_store.film_write_running("fr", 150):
                break
        assert official_store.serve_film("en", 150, "written")["status"] == "ready"
        assert calls["n"] == 1

    asyncio.run(scenario())


def test_film_async_interrupted_owner_becomes_terminal_failure(tmp_path, monkeypatch):
    import sqlite3

    store = OfficialStore(DiskBackend(tmp_path / "film-state-restart"), now=lambda: NOW)
    official_store.reset_store()
    monkeypatch.setattr(official_store, "_INSTANCE", store)
    official_store._set_film_write_state(180, "writing")
    with sqlite3.connect(official_store._film_write_db()) as db:
        db.execute("UPDATE film_write_tasks SET owner_pid=? WHERE seconds=180", (999999999,))
    assert official_store.serve_film("fr", 180, "written")["status"] == "failed"
    official_store._FILM_WRITE_TASKS.clear()
    assert official_store.serve_film("en", 180, "written")["status"] == "failed"


def test_film_async_writing_state_expires_only_after_age_limit(tmp_path, monkeypatch):
    import sqlite3

    store = OfficialStore(DiskBackend(tmp_path / "film-state-age"), now=lambda: NOW)
    official_store.reset_store()
    monkeypatch.setattr(official_store, "_INSTANCE", store)
    stale_at = NOW - official_store.FILM_WRITE_STALE_AFTER - timedelta(seconds=1)
    fresh_at = NOW - official_store.FILM_WRITE_STALE_AFTER + timedelta(seconds=1)
    for seconds, timestamp in ((150, stale_at), (180, fresh_at)):
        official_store._set_film_write_state(seconds, "writing")
        with sqlite3.connect(official_store._film_write_db()) as db:
            db.execute(
                "UPDATE film_write_tasks SET owner_pid=?, updated_at=? WHERE seconds=?",
                (os.getpid(), official_store._iso(timestamp), seconds),
            )

    assert official_store._film_write_state(150, now=NOW) == "failed"
    assert official_store._film_write_state(180, now=NOW) == "writing"


def test_film_async_tavily_runs_in_background_task(client, tmp_path, monkeypatch):
    import asyncio
    import film_script

    store = OfficialStore(DiskBackend(tmp_path / "film-tavily-bg"), now=lambda: NOW)
    voy = _rg11a_voy()
    official_store.reset_store()
    official_store._FILM_WRITE_FAILED.clear()
    monkeypatch.setattr(official_store, "_INSTANCE", store)
    monkeypatch.setattr(official_store, "_load_official", lambda: voy)
    monkeypatch.setenv("NAVIGUIDE_LLM_MODE", "on-demand")
    monkeypatch.setenv("NAVIGUIDE_LLM_DAILY_TOKENS_JUDGE", "0")
    store.put("film", _rg11a_payload(), store.family_key("film", voy, NOW))
    order: list[str] = []
    proceed_attach = asyncio.Event()

    async def slow_attach(**_kw):
        order.append("attach_start")
        await proceed_attach.wait()
        order.append("attach_done")

    async def fake_chain(plan, *, seconds=150, cascade=None, **kwargs):
        order.append("chain")
        written = {
            "chapters": list(plan.get("chapters") or []),
            "source": official_store.WRITTEN_SOURCE,
            "hasWritten": True,
            "chars": 40,
            "targetSeconds": seconds,
        }
        return written, None, {
            "super": 1,
            "ultra_edit": 0,
            "ultra_judge": 0,
            "lightning": 0,
            "source": official_store.WRITTEN_SOURCE,
            "reviewed": False,
        }

    monkeypatch.setattr(official_store, "attach_film_web_context", slow_attach)
    monkeypatch.setattr(film_script, "write_film_chain", fake_chain)

    first = client.post("/voyage/official/film?lang=fr&seconds=150")
    assert first.status_code == 200
    body = first.json()
    assert body["status"] == "writing"
    assert body["writing"] is True
    # Tavily a démarré dans la tâche de fond : le POST a répondu avant attach_done/chain.
    assert order == ["attach_start"]
    proceed_attach.set()


def test_replay_local_without_token_factory_serves_raw_and_labels_written_failure(tmp_path, monkeypatch):
    """FR/EN Replay uses the frozen store; unavailable writing stays a clean API state."""
    import asyncio
    import json
    import main
    import story_cascade

    store = OfficialStore(DiskBackend(tmp_path / "replay-local-no-tf"), now=lambda: NOW)
    voy = _rg11a_voy()
    official_store.reset_store()
    monkeypatch.setattr(official_store, "_INSTANCE", store)
    monkeypatch.setattr(official_store, "_load_official", lambda: voy)
    monkeypatch.setenv("NAVIGUIDE_LLM_MODE", "on-demand")
    monkeypatch.delenv("NAVIGUIDE_LLM_PROVIDERS", raising=False)
    monkeypatch.delenv("NAVIGUIDE_ALLOW_TF", raising=False)
    monkeypatch.delenv("NEBIUS_API_KEY", raising=False)
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
    monkeypatch.delenv("NVIDIA_API_KEY_2", raising=False)
    async def no_web(*_a, **_k):
        return None

    monkeypatch.setattr(official_store, "attach_film_web_context", no_web)
    payload = _rg11a_payload()
    store.put("film", payload, store.family_key("film", voy, NOW))

    calls = {"tf": 0}

    async def forbidden_tf(*_args, **_kwargs):
        calls["tf"] += 1
        raise AssertionError("Token Factory path must not be called")

    monkeypatch.setattr(story_cascade, "_call_tokenfactory", forbidden_tf)

    async def replay_both_languages():
        for lang in ("fr", "en"):
            raw = await main.get_official_film(lang=lang, seconds=150, style="raw")
            assert raw["status"] == READY
            assert raw["chapters"]

        # The async POST acknowledges the job. Await that same job in this
        # direct-call test so asyncio.run does not cancel it while closing its loop.
        started = await main.post_official_film_write(lang="fr", seconds=150)
        assert started["status"] == "writing"
        task = official_store._FILM_WRITE_TASKS[("pair", 150)]
        await task

        for lang in ("fr", "en"):
            raw = await main.get_official_film(lang=lang, seconds=150, style="raw")
            assert raw["status"] == READY
            assert raw["chapters"]
            # The completed job records the written failure for both languages;
            # raw remains playable and the client maps this state to its failure label.
            written = await main.get_official_film(lang=lang, seconds=150, style="written")
            assert written["status"] == "failed"
            assert written["hasWritten"] is False
            assert "NEBIUS_API_KEY" not in json.dumps(written)
            assert "RuntimeError" not in json.dumps(written)

    asyncio.run(replay_both_languages())

    assert calls["tf"] == 0


# Visiteur public (nginx pose X-Real-IP). Sans ces en-têtes, l'appel local
# est admin et le limiteur ne s'applique pas — comme pour POST /ici/story.
_PUBLIC_FILM = {"X-Real-IP": "203.0.113.40", "X-Forwarded-For": "203.0.113.40"}
_PUBLIC_FILM_OTHER = {"X-Real-IP": "203.0.113.41", "X-Forwarded-For": "203.0.113.41"}


def test_film_write_rate_limit_and_offered_durations(client, tmp_path, monkeypatch):
    """POST Rédigé : 429 au-delà du budget, 422 hors 0/150/180, 200 et cache inchangés."""
    import admin_guard
    import film_script
    from official_store import FILM_VARIANT_SECONDS

    admin_guard.reset_limiters()
    store = OfficialStore(DiskBackend(tmp_path / "http-film-write-limit"), now=lambda: NOW)
    voy = _rg11a_voy()
    official_store.reset_store()
    monkeypatch.setattr(official_store, "_INSTANCE", store)
    monkeypatch.setattr(official_store, "_load_official", lambda: voy)
    monkeypatch.setenv("NAVIGUIDE_LLM_MODE", "off")
    monkeypatch.setenv("NAVIGUIDE_LLM_DAILY_TOKENS_JUDGE", "0")  # Ultra fermé : chemin Super seul
    store.put("film", _rg11a_payload(), store.family_key("film", voy, NOW))
    calls = {"n": 0}

    async def fake_chain(plan, *, seconds=150, cascade=None, en_raw=None):
        calls["n"] += 1
        written = {
            "chapters": list(plan.get("chapters") or []),
            "source": official_store.WRITTEN_SOURCE,
            "hasWritten": True,
            "chars": 40,
            "targetSeconds": seconds,
        }
        return written, None, {
            "super": 1, "ultra_edit": 0, "ultra_judge": 0, "lightning": 0,
            "source": official_store.WRITTEN_SOURCE, "reviewed": False,
        }

    monkeypatch.setattr(film_script, "write_film_chain", fake_chain)

    # Mode off : aucune écriture LLM, forme identique au GET rédigé.
    for secs in FILM_VARIANT_SECONDS:
        posted = client.post(
            f"/voyage/official/film?lang=fr&seconds={secs}",
            headers=_PUBLIC_FILM,
        )
        assert posted.status_code == 200, secs
        got = client.get(
            f"/voyage/official/film?lang=fr&seconds={secs}&style=written",
            headers=_PUBLIC_FILM,
        )
        assert posted.json() == got.json()
        assert "chapters" in posted.json()
        assert isinstance(posted.json()["hasWritten"], bool)
    assert calls["n"] == 0

    for secs in (101, 115, 108, 200, 300):
        denied = client.post(
            f"/voyage/official/film?lang=fr&seconds={secs}",
            headers=_PUBLIC_FILM,
        )
        assert denied.status_code == 422, secs
        assert denied.json()["detail"] == "unsupported film duration"
    assert client.post("/voyage/official/film?lang=fr&seconds=301", headers=_PUBLIC_FILM).status_code == 422
    assert calls["n"] == 0
    # La lecture n'est pas bornée : seul le clic qui lance la chaîne l'est.
    assert client.get("/voyage/official/film?lang=fr&seconds=115").status_code == 200

    # Chaîne mockée : un écrit, le suivant relit le cache.
    monkeypatch.setenv("NAVIGUIDE_LLM_MODE", "on-demand")
    admin_guard.reset_limiters()
    first = client.post("/voyage/official/film?lang=fr&seconds=150", headers=_PUBLIC_FILM)
    assert first.status_code == 200
    body = first.json()
    # R22: first POST returns writing=True, hasWritten=False
    assert body["hasWritten"] is False
    assert body["status"] == "writing"
    # Second POST (simulated poll): after first successful poll, write ready
    second = client.post("/voyage/official/film?lang=fr&seconds=150", headers=_PUBLIC_FILM)
    assert second.status_code == 200
    second_body = second.json()
    assert second_body["hasWritten"] is True
    assert second_body["status"] == "ready"
    assert calls["n"] == 1

    # 12 / min / IP, comme POST /ici/story. Les deux appels ci-dessus comptent.
    for _ in range(10):
        again = client.post("/voyage/official/film?lang=fr&seconds=150", headers=_PUBLIC_FILM)
        assert again.status_code == 200
        assert again.json()["hasWritten"] is True
    assert calls["n"] == 1
    blocked = client.post("/voyage/official/film?lang=fr&seconds=150", headers=_PUBLIC_FILM)
    assert blocked.status_code == 429
    assert blocked.headers.get("retry-after")
    other = client.post("/voyage/official/film?lang=fr&seconds=150", headers=_PUBLIC_FILM_OTHER)
    assert other.status_code == 200
    assert calls["n"] == 1
    # Sans en-tête proxy, l'appel local reste accepté : pas de clé admin exigée.
    local = client.post("/voyage/official/film?lang=fr&seconds=180")
    assert local.status_code == 200
    admin_guard.reset_limiters()


def test_official_meta_route_fingerprints_on_fake_stock(client, monkeypatch):
    """Mêmes coordonnées → même empreinte. Stock fictif : les deux champs,
    égaux si les points recopient les LineString, différents sinon.
    Sans points, routeVoyageFp est null. routeRev reste. Aucun semis."""
    import json

    from route_contract import line_strings
    from voyage_clock import OFFICIAL_T0, OFFICIAL_VOYAGE_ID
    from voyage_store import load_voyage, save_voyage
    import voyage_api

    def _forbid_seed():
        raise AssertionError("seed_official_voyage")

    monkeypatch.setattr(voyage_api, "seed_official_voyage", _forbid_seed)

    same = voyage_api.route_points_fingerprint([
        {"lon": 1, "lat": -46.2, "cumNm": 12},
        {"lat": 10.5, "lon": -79.5, "jump": False},
    ])
    again = voyage_api.route_points_fingerprint([
        {"lat": -46.2, "lon": 1.0},
        {"lon": -79.5, "lat": 10.5, "name": "ignore"},
    ])
    assert same and same == again
    assert same != voyage_api.route_points_fingerprint([
        {"lon": -79.5, "lat": 10.5},
        {"lon": 1.0, "lat": -46.2},
    ])
    assert voyage_api.route_points_fingerprint(None) is None
    assert voyage_api.route_points_fingerprint([]) is None

    collection = json.loads(voyage_api._ROUTE_GEOJSON.read_text(encoding="utf-8"))
    file_points = []
    for line in line_strings(collection):
        for coord in line["coordinates"]:
            file_points.append({
                "lon": coord[0],
                "lat": coord[1],
                "cumNm": len(file_points),
                "filmCum": len(file_points),
                "jump": False,
            })
    assert file_points
    file_fp = voyage_api.route_file_fingerprint()
    assert isinstance(file_fp, str) and len(file_fp) == 64
    assert voyage_api.route_file_fingerprint() == file_fp
    assert voyage_api.route_points_fingerprint(file_points) == file_fp

    save_voyage({
        "voyageId": OFFICIAL_VOYAGE_ID,
        "t0": OFFICIAL_T0,
        "official": True,
        "routeRev": 4,
        "points": file_points,
        "marks": [],
        "follow": True,
    })
    got = client.get("/voyage/official")
    assert got.status_code == 200
    body = got.json()
    assert body["routeRev"] == 4
    assert body["routeFileFp"] == file_fp
    assert body["routeVoyageFp"] == file_fp

    shifted = [dict(point) for point in file_points]
    shifted[0]["lon"] = float(shifted[0]["lon"]) + 0.05
    save_voyage({
        "voyageId": OFFICIAL_VOYAGE_ID,
        "t0": OFFICIAL_T0,
        "official": True,
        "routeRev": 4,
        "points": shifted,
        "marks": [],
        "follow": True,
    })
    body_shifted = client.get("/voyage/official").json()
    assert body_shifted["routeFileFp"] == file_fp
    assert body_shifted["routeVoyageFp"] != file_fp
    assert isinstance(body_shifted["routeVoyageFp"], str)
    assert body_shifted["routeRev"] == 4
    stored = load_voyage(OFFICIAL_VOYAGE_ID)
    assert stored["points"][0]["lon"] == pytest.approx(float(file_points[0]["lon"]) + 0.05)
    assert stored["routeRev"] == 4

    bare = voyage_api._public_meta({
        "voyageId": OFFICIAL_VOYAGE_ID,
        "t0": OFFICIAL_T0,
        "official": True,
        "routeRev": 0,
    })
    assert bare["routeFileFp"] == file_fp
    assert bare["routeVoyageFp"] is None
    assert bare["routeRev"] == 0
    assert load_voyage(OFFICIAL_VOYAGE_ID)["routeRev"] == 4

    draft = voyage_api._public_meta({
        "voyageId": "brouillon",
        "t0": OFFICIAL_T0,
        "official": False,
        "points": file_points[:2],
    })
    assert "routeFileFp" not in draft
    assert "routeVoyageFp" not in draft
    assert draft["routeRev"] == 0


@pytest.mark.parametrize("today_present,expect_nudge", [(False, 1), (True, 0)])
def test_repair_worker_restarts_dead_filler_and_nudges_only_on_new_day(tmp_path, monkeypatch, today_present, expect_nudge):
    """PUT visiteur : remplisseur mort relancé ; réveil seulement si le climo du jour manque (revue #121, 1)."""
    voy = {"t0": T0, "points": [{"lat": 1.0, "lon": 2.0}], "marks": []}
    monkeypatch.setenv("NAVIGUIDE_OFFICIAL_WORKER", "force")
    monkeypatch.setenv("NAVIGUIDE_OFFICIAL_STORE_DIR", str(tmp_path / "store"))
    monkeypatch.setenv("NAVIGUIDE_FILL_NUDGE_MIN_S", "180")
    monkeypatch.setattr(official_store, "WORKER_MODE", "process")
    monkeypatch.setattr(official_store, "_LAST_REPAIR_AT", None)
    monkeypatch.setattr(official_store, "_load_official", lambda: voy)
    store = dict(_stores(tmp_path))["disk"]
    store._now = lambda: TODAY
    monkeypatch.setattr(official_store, "get_store", lambda **_: store)
    store.put("climo", {"clock": {"t0": T0}}, store.family_key("climo", voy, YESTERDAY))
    if today_present:
        store.put("climo", {"clock": {"t0": T0}}, store.family_key("climo", voy, TODAY))
    calls = {"ensure": 0, "nudge": 0}
    monkeypatch.setattr(official_store, "ensure_fill_process", lambda: calls.__setitem__("ensure", calls["ensure"] + 1))
    monkeypatch.setattr(official_store, "nudge_fill_process", lambda: calls.__setitem__("nudge", calls["nudge"] + 1))
    official_store.repair_worker()
    official_store.repair_worker()  # même fenêtre : plafonné
    assert calls == {"ensure": 1, "nudge": expect_nudge}
