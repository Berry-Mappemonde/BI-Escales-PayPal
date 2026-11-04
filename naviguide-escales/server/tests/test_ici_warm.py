"""Pré-génération des perles along (ici_warm) : échantillonnage, cache disque, chauffeur."""
import asyncio
import json

import httpx

import ici_engine
import ici_warm
from ici_engine import fill_dossier, reset_caches, thin_cache_key
from tests.test_ici_engine import _handler  # mock BI + MarineRegions


def _route():
    pts = []
    # 200 nm of sea eastward along 46.15°N (1° lon ≈ 41.6 nm), then a hop.
    for i in range(0, 25):
        pts.append({"lat": 46.15, "lon": -1.16 - i * 0.2, "cumNm": i * 8.3, "filmCum": i * 8.3})
    pts.append({"lat": 44.0, "lon": -63.0, "cumNm": 3000, "filmCum": 3100, "jump": True})
    pts.append({"lat": 46.8, "lon": 1.6, "cumNm": 0, "filmCum": 0, "nonMaritime": True})
    return pts


def test_sample_route_every_12_nm_skips_hops_and_land():
    pearls = ici_warm.sample_route(_route())
    assert 15 <= len(pearls) <= 19, len(pearls)
    assert pearls[0][0] == 46.15 and abs(pearls[0][1] + 1.16) < 1e-9
    for (la1, lo1), (la2, lo2) in zip(pearls, pearls[1:]):
        d = ici_warm._haversine_nm(la1, lo1, la2, lo2)
        assert 11.5 <= d <= 13.0, d
    assert all(abs(lo) <= 180 for _, lo in pearls)
    assert ici_warm.sample_route([]) == []


def test_store_round_trips_between_restarts():
    reset_caches()
    ici_engine.thin_cache_put(thin_cache_key(46.15, -1.16, 30, None), {"zee": {"mrgid": 5677}, "sources": {"bi": "ok"}}, "rich", 46.15, -1.16)
    reset_caches()  # a restart forgets memory, not the store
    assert ici_engine.thin_cache_get(thin_cache_key(46.15, -1.16, 30, None))["zee"]["mrgid"] == 5677
    assert ici_warm.status()["store"]["rich"] == 1


def _polygon_or_handler(request: httpx.Request) -> httpx.Response:
    """Tuile /amp en vrai polygone, pour que le chauffeur puisse stocker une perle riche."""
    url = str(request.url)
    if "/amp?" in url and "bbox=" in url:
        ring = [[-8.0, 44.0], [3.0, 44.0], [3.0, 48.0], [-8.0, 48.0], [-8.0, 44.0]]
        feat = {
            "type": "Feature",
            "geometry": {"type": "Polygon", "coordinates": [ring]},
            "properties": {
                "name": "Pertuis charentais",
                "lat": 46.16,
                "lon": -1.20,
                "site_id": "PS-1",
            },
        }
        return httpx.Response(200, json={"type": "FeatureCollection", "features": [feat]})
    return _handler(request)


def test_warmer_fills_rich_pearls_once_and_reports(tmp_path, monkeypatch):
    import voyage_store
    reset_caches()
    voyage_store.save_voyage({"voyageId": "berry-mappemonde-2026-officiel", "points": _route()[:6], "marks": [], "t0": "2026-05-15T08:00:00Z"})

    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return _polygon_or_handler(request)

    transport = httpx.MockTransport(handler)
    real_fill = ici_engine.fill_dossier

    async def patched(lat, lon, radius_nm=30.0, client=None, **kw):
        async with httpx.AsyncClient(transport=transport) as c:
            return await real_fill(lat, lon, radius_nm, client=c, **kw)

    monkeypatch.setattr(ici_engine, "fill_dossier", patched)
    out = asyncio.run(ici_warm.warm_official_route(pause_s=0))
    assert out["status"] == "done" and out["kind"] == "rich"
    assert out["total"] >= 3
    assert out["done"] == out["total"]
    assert out["cached"] == 0
    n_calls = len(calls)
    assert n_calls > 0
    assert out["store"]["rich"] == out["total"], "every pearl is rich in the store"
    # A rich pearl carries the timeless layers a thin one skips.
    la, lo = ici_warm.sample_route(_route()[:6])[0]
    bag = ici_engine.thin_cache_get(thin_cache_key(la, lo, 30))
    assert bag["pearl"] == "rich"
    assert "science" in bag and "aton" in bag and "emodnet" in bag
    assert bag["weather"]["reason"] == "not_in_along_pearl", "weather stays live"
    assert bag["satellites"]["reason"] == "not_in_along_pearl"
    # Second pass: everything is already in the store, no upstream call.
    out2 = asyncio.run(ici_warm.warm_official_route(pause_s=0))
    assert out2["cached"] == out2["total"]
    assert len(calls) == n_calls
    # A thin request is served by the rich pearl (superset), without any call.
    async def thin_req():
        async with httpx.AsyncClient(transport=transport) as c:
            return await real_fill(la, lo, 30.0, client=c, thin=True)
    served = asyncio.run(thin_req())
    assert served["cached"] is True and served["pearl"] == "rich"
    assert len(calls) == n_calls


def test_warmer_redoes_a_centroid_pearl_then_skips_it(tmp_path, monkeypatch):
    """Une perle riche encore en centroïde est refaite ; l'ancienne clé disparaît."""
    import pearl_store
    import voyage_store
    reset_caches()
    voyage_store.save_voyage({
        "voyageId": "berry-mappemonde-2026-officiel",
        "points": _route()[:4],
        "marks": [],
        "t0": "2026-05-15T08:00:00Z",
    })
    la, lo = ici_warm.sample_route(_route()[:4])[0]
    old_key = "legacy-centroid"
    assert pearl_store.put_pearl(
        old_key,
        {"pearl": "rich", "amp": [{"name": "Vieux point", "lat": la, "lon": lo}], "sources": {"bi": "ok"}},
        "rich", la, lo,
    )
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return _polygon_or_handler(request)

    transport = httpx.MockTransport(handler)
    real_fill = ici_engine.fill_dossier

    async def patched(lat, lon, radius_nm=30.0, client=None, **kw):
        async with httpx.AsyncClient(transport=transport) as c:
            return await real_fill(lat, lon, radius_nm, client=c, **kw)

    monkeypatch.setattr(ici_engine, "fill_dossier", patched)
    out = asyncio.run(ici_warm.warm_official_route(pause_s=0))
    assert out["ampRedo"] >= 1
    assert pearl_store.get_pearl(old_key) is None
    bag = ici_engine.thin_cache_get(thin_cache_key(la, lo, 30))
    assert bag["amp"][0]["source"] == "polygon"
    n_calls = len(calls)
    out2 = asyncio.run(ici_warm.warm_official_route(pause_s=0))
    assert out2["cached"] == out2["total"]
    assert len(calls) == n_calls


def test_warmer_keeps_the_centroid_pearl_when_polygons_fail(tmp_path, monkeypatch):
    import pearl_store
    import voyage_store
    reset_caches()
    voyage_store.save_voyage({
        "voyageId": "berry-mappemonde-2026-officiel",
        "points": _route()[:4],
        "marks": [],
        "t0": "2026-05-15T08:00:00Z",
    })
    la, lo = ici_warm.sample_route(_route()[:4])[0]
    old_key = "legacy-centroid"
    pearl_store.put_pearl(
        old_key,
        {"pearl": "rich", "amp": [{"name": "Vieux point", "lat": la, "lon": lo}], "sources": {"bi": "ok"}},
        "rich", la, lo,
    )

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "/amp?" in url and "bbox=" in url:
            return httpx.Response(503, json={"detail": "amp down"})
        return _handler(request)

    transport = httpx.MockTransport(handler)
    real_fill = ici_engine.fill_dossier

    async def patched(lat, lon, radius_nm=30.0, client=None, **kw):
        async with httpx.AsyncClient(transport=transport) as c:
            return await real_fill(lat, lon, radius_nm, client=c, **kw)

    monkeypatch.setattr(ici_engine, "fill_dossier", patched)
    out = asyncio.run(ici_warm.warm_official_route(pause_s=0))
    assert out["errors"] >= 1
    assert pearl_store.get_pearl(old_key) is not None
    assert ici_engine.thin_cache_get(thin_cache_key(la, lo, 30)) is None


def test_official_pearls_endpoint_lists_canonical_positions(tmp_path, monkeypatch):
    import voyage_store
    ici_warm._pearls_cache["pearls"] = None
    voyage_store.save_voyage({"voyageId": "berry-mappemonde-2026-officiel", "points": _route(), "marks": [], "t0": "2026-05-15T08:00:00Z", "routeRev": 0})
    out = ici_warm.official_pearls()
    assert out["stepNm"] == 12.0
    assert out["count"] == len(out["pearls"]) >= 15
    assert all(len(p) == 2 for p in out["pearls"])
    assert out["warm"]["status"] in ("idle", "disabled", "running", "done")
    # Same cell as the warmer → the thin cache key ignores the month.
    from ici_engine import thin_cache_key
    la, lo = out["pearls"][0]
    assert thin_cache_key(la, lo, 30, 9) == thin_cache_key(la, lo, 30, None)


def test_status_exposes_llm_budget_counters():
    st = ici_warm.status()
    assert "llm" in st
    for tier in ("fast", "write", "judge"):
        assert set(st["llm"][tier]) >= {"tokens", "calls", "usd"}
        assert st["llm"][tier]["tokens"] == 0
        assert st["llm"][tier]["calls"] == 0
    assert st["stories"]["skipped"] == "on-demand"


def test_warm_skips_stories_and_does_not_call_llm(tmp_path, monkeypatch):
    """Un warm complet n'appelle pas cascade_text ; le compteur write ne bouge pas."""
    import llm_budget
    import story_cascade
    import voyage_store
    reset_caches()
    voyage_store.save_voyage({
        "voyageId": "berry-mappemonde-2026-officiel",
        "points": _route()[:6],
        "marks": [],
        "t0": "2026-05-15T08:00:00Z",
    })
    calls = []

    async def boom(*_a, **_k):
        calls.append(1)
        raise RuntimeError("cascade_text forbidden during warm")

    monkeypatch.setattr(story_cascade, "cascade_text", boom)

    def handler(request: httpx.Request) -> httpx.Response:
        return _polygon_or_handler(request)

    transport = httpx.MockTransport(handler)
    real_fill = ici_engine.fill_dossier

    async def patched(lat, lon, radius_nm=30.0, client=None, **kw):
        async with httpx.AsyncClient(transport=transport) as c:
            return await real_fill(lat, lon, radius_nm, client=c, **kw)

    monkeypatch.setattr(ici_engine, "fill_dossier", patched)
    before = llm_budget.get_usage("write")["tokens"]
    out = asyncio.run(ici_warm.warm_official_route(pause_s=0))
    assert out["stories"]["skipped"] == "on-demand"
    assert calls == []
    assert llm_budget.get_usage("write")["tokens"] == before
    assert ici_warm.stories_enabled() is False


def test_warmer_is_disabled_by_env(monkeypatch):
    monkeypatch.setenv("NAVIGUIDE_ICI_WARM", "0")
    assert ici_warm.warm_enabled() is False
    assert ici_warm.start_background() is False
    assert ici_warm.status()["status"] == "disabled"
    monkeypatch.setenv("NAVIGUIDE_ICI_WARM", "1")
    assert ici_warm.warm_enabled() is True


def test_pearls_carry_the_clocks_sail_scale_including_the_land_leg():
    """La perle porte le cumNm de la route — l'échelle de
    l'horloge — et non des milles comptés depuis le premier point de mer.
    Sans ça, chaque ligne du journal issue des perles était datée ~16 h trop tôt."""
    pts = [
        {"lat": 46.8, "lon": 1.6, "cumNm": 0, "filmCum": 0, "nonMaritime": True},        # Saint-Maur
        {"lat": 46.15, "lon": -1.16, "cumNm": 122.3, "filmCum": 122.3, "nonMaritime": True},  # La Rochelle (land end)
        {"lat": 46.24, "lon": -1.26, "cumNm": 128.8, "filmCum": 128.8},                    # first sea point
        {"lat": 46.1, "lon": -1.7, "cumNm": 156.0, "filmCum": 156.0},
        {"lat": 45.86, "lon": -2.45, "cumNm": 190.5, "filmCum": 190.5},
    ]
    pearls = ici_warm.sample_route_nm(pts)
    assert pearls[0]["sailNm"] == 128.8, pearls[0]
    assert all(b["sailNm"] > a["sailNm"] for a, b in zip(pearls, pearls[1:]))
    assert pearls[-1]["sailNm"] <= 190.5 + 0.01
    # Without cumNm the old accumulation still works (0 at the first sea point).
    bare = ici_warm.sample_route_nm([{k: v for k, v in p.items() if k != "cumNm"} for p in pts])
    assert bare[0]["sailNm"] == 0


def _put_amp_pearls(pearls, bags):
    import ici_engine
    from ici_engine import thin_cache_key

    ici_engine.reset_caches()
    for p, bag in zip(pearls, bags):
        ici_engine.thin_cache_put(
            thin_cache_key(p["lat"], p["lon"], 30.0),
            bag,
            "rich",
            p["lat"],
            p["lon"],
        )


def test_am1b_amp_enter_exit_and_nearby(monkeypatch):
    """Trois perles, la 2e dedans → enter puis exit ; 10 nm du bord → nearby."""
    pearls = [
        {"lat": 41.00, "lon": 9.00, "sailNm": 0},
        {"lat": 41.20, "lon": 9.20, "sailNm": 12},
        {"lat": 41.40, "lon": 9.40, "sailNm": 24},
    ]
    park = "Réserve des Bouches de Bonifacio"
    bags = [
        {"amp": [{"name": park, "siteId": "AIFRA7", "inside": False, "nm": 22.0, "source": "polygon"}], "sources": {"bi": "ok"}},
        {"amp": [{"name": park, "siteId": "AIFRA7", "inside": True, "nm": 0.0, "source": "polygon"}], "sources": {"bi": "ok"}},
        {"amp": [{"name": park, "siteId": "AIFRA7", "inside": False, "nm": 18.0, "source": "polygon"}], "sources": {"bi": "ok"}},
    ]
    monkeypatch.setattr(ici_warm, "sample_route_nm", lambda points, step_nm=12.0: pearls)
    _put_amp_pearls(pearls, bags)
    events = ici_warm.route_events_from_pearls([{"lat": p["lat"], "lon": p["lon"], "cumNm": p["sailNm"]} for p in pearls])
    amps = [e for e in events if e["kind"] == "amp"]
    assert [(e["event"], e["idx"]) for e in amps] == [("enter", 1), ("exit", 2)]
    assert amps[0]["name"] == park and amps[0]["inside"] is True

    near_pearls = [{"lat": 39.10, "lon": 3.00, "sailNm": 0}]
    near_bags = [{"amp": [{"name": "Parc de Cabrera", "siteId": "ES-CAB", "inside": False, "nm": 10.0, "source": "polygon"}], "sources": {"bi": "ok"}}]
    monkeypatch.setattr(ici_warm, "sample_route_nm", lambda points, step_nm=12.0: near_pearls)
    _put_amp_pearls(near_pearls, near_bags)
    near = [e for e in ici_warm.route_events_from_pearls(near_pearls) if e["kind"] == "amp"]
    assert len(near) == 1 and near[0]["event"] == "nearby" and near[0]["nm"] == 10.0


def test_am1b_amp_dedup_prefix_and_export_fallback(monkeypatch):
    """Lilleau ×2 = un événement ; sac export sans inside = nearby d'avant, jamais rouge."""
    pearls = [{"lat": 46.15, "lon": -1.40, "sailNm": 0}]
    monkeypatch.setattr(ici_warm, "sample_route_nm", lambda points, step_nm=12.0: pearls)
    bags = [{
        "amp": [
            {"name": "Lilleau-des-Niges", "siteId": "a1", "inside": False, "nm": 4.9, "source": "polygon"},
            {"name": "Lilleau-des-Niges - Zone de Protection", "siteId": "a2", "inside": False, "nm": 4.9, "source": "polygon"},
        ],
        "sources": {"bi": "ok"},
    }]
    _put_amp_pearls(pearls, bags)
    amps = [e for e in ici_warm.route_events_from_pearls(pearls) if e["kind"] == "amp"]
    assert len(amps) == 1 and amps[0]["event"] == "nearby"

    export_bags = [{
        "amp": [{"name": "Pertuis charentais - Rochebonne", "site_id": "rb-1", "nm": 8.0, "source": "export", "iucn_cat": "II"}],
        "sources": {"bi": "ok"},
    }]
    _put_amp_pearls(pearls, export_bags)
    exp = [e for e in ici_warm.route_events_from_pearls(pearls) if e["kind"] == "amp"]
    assert len(exp) == 1 and exp[0]["event"] == "nearby" and "inside" in exp[0]
    assert exp[0]["inside"] is False
    assert exp[0].get("source") == "export"


def test_watch_loop_starts_when_warmer_is_off(monkeypatch):
    """Chauffage coupé, veille ouverte : la boucle part, sans enrichir les perles."""
    import escale_watch

    monkeypatch.setenv("NAVIGUIDE_ICI_WARM", "0")
    monkeypatch.setenv("NAVIGUIDE_TAVILY_WATCH", "1")
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    saved = dict(ici_warm._state)
    scheduled: list = []

    class _Loop:
        def create_task(self, coro):
            scheduled.append(coro)
            return coro

    enrich_calls: list = []
    daily_calls: list = []
    real_daily = escale_watch.run_daily

    async def spy_enrich(*_a, **_k):
        enrich_calls.append(1)
        return {"skipped": True}

    async def spy_daily(*args, **kwargs):
        daily_calls.append(dict(kwargs))
        return await real_daily(*args, **kwargs)

    sleeps: list = []

    async def fake_sleep(delay, result=None):
        sleeps.append(delay)
        if len(sleeps) >= 2:
            raise asyncio.CancelledError()
        return result

    monkeypatch.setattr(escale_watch, "run_daily_enrich", spy_enrich)
    monkeypatch.setattr(escale_watch, "run_daily", spy_daily)
    monkeypatch.setattr(ici_warm.asyncio, "sleep", fake_sleep)
    try:
        assert ici_warm.warm_enabled() is False
        assert ici_warm.watch_enabled() is True
        assert ici_warm.start_background(_Loop()) is False
        assert ici_warm.status()["status"] == "disabled"
        assert ici_warm.status()["watch"]["status"] == "scheduled"
        assert len(scheduled) == 1
        assert scheduled[0].cr_code.co_name == "_watch_loop"
        try:
            asyncio.run(scheduled[0])
        except asyncio.CancelledError:
            pass
        assert enrich_calls == []
        assert daily_calls and daily_calls[0].get("enrich") is False
        assert sleeps[0] == 120.0
        assert sleeps[1] == ici_warm._watch_period_s()
        assert "watch" in ici_warm.status()
    finally:
        ici_warm._state.clear()
        ici_warm._state.update(saved)
        for coro in scheduled:
            if getattr(coro, "cr_frame", None) is not None:
                coro.close()
