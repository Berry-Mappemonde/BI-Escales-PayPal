"""Bornes et terre franche de GET /route. Searoute est simulé."""
from fastapi.testclient import TestClient

import main
from route_engine import endpoint_on_land


def test_start_lat_out_of_range_is_422():
    client = TestClient(main.app)
    response = client.get("/route", params={
        "start_lat": 999,
        "start_lon": -1.15,
        "end_lat": 43.5,
        "end_lon": -5.6,
    })
    assert response.status_code == 422


def test_longitude_out_of_range_is_422():
    # Une longitude dépliée est repliée (voir plus bas) ; au-delà de ±540°, refus.
    client = TestClient(main.app)
    response = client.get("/route", params={
        "start_lat": 46.15,
        "start_lon": 541,
        "end_lat": 43.5,
        "end_lon": -5.6,
    })
    assert response.status_code == 422
    south = client.get("/route", params={
        "start_lat": -91,
        "start_lon": -1,
        "end_lat": 0,
        "end_lon": -1,
    })
    assert south.status_code == 422


def test_inland_endpoint_is_422_on_land(monkeypatch):
    def boom(*_args, **_kwargs):
        raise AssertionError("searoute ne doit pas partir pour un point sur terre")

    monkeypatch.setattr(main, "searoute_with_exact_end", boom)
    client = TestClient(main.app)
    response = client.get("/route", params={
        "start_lat": 48.8566,
        "start_lon": 2.3522,
        "end_lat": 46.2,
        "end_lon": -1.7,
    })
    assert response.status_code == 422
    assert response.json()["detail"] == "on_land"


def test_coastal_ports_are_not_inland():
    assert endpoint_on_land(48.8566, 2.3522) is True
    for lat, lon in ((46.157, -1.151), (43.545, -5.662), (38.722, -9.139)):
        assert endpoint_on_land(lat, lon) is False, (lat, lon)


def test_same_point_at_sea_does_not_call_searoute(monkeypatch):
    def boom(*_args, **_kwargs):
        raise AssertionError("probe même point")

    monkeypatch.setattr(main, "searoute_with_exact_end", boom)
    client = TestClient(main.app)
    response = client.get("/route", params={
        "start_lat": 46.2,
        "start_lon": -2.4,
        "end_lat": 46.2,
        "end_lon": -2.4,
    })
    assert response.status_code == 200
    coords = response.json()["geometry"]["coordinates"]
    assert len(coords) == 2


def test_searoute_timeout_is_a_single_attempt(monkeypatch):
    """Un échec ou un délai dépassé ne relance pas searoute (plus de nouvel essai au large)."""
    import route_engine

    calls = []

    def timed_out(start, end, timeout_s=None):
        calls.append((start, end))
        return None

    monkeypatch.setattr(route_engine, "_invoke_searoute", timed_out)
    start, end = (-1.7, 46.25), (-2.1, 46.05)
    route_engine._route_cache.pop(route_engine._route_cache_key(start, end), None)
    route = route_engine.searoute_with_exact_end(start, end)
    assert route is None
    assert len(calls) == 1
    assert calls[0] == (start, end)


def test_searoute_deadline_is_about_8_s():
    import route_engine

    assert 6.0 <= route_engine.SEAROUTE_TIMEOUT_S <= 10.0


def test_timed_out_call_leaves_no_work_running(monkeypatch):
    """À l'échéance, le process qui calculait est tué : rien ne continue derrière."""
    import time

    import searoute_worker
    from searoute_worker import TIMED_OUT, ProcessRunner

    killed = []
    real_kill = searoute_worker._Worker.kill

    def kill(self):
        killed.append(self)
        real_kill(self)

    monkeypatch.setattr(searoute_worker._Worker, "kill", kill)
    runner = ProcessRunner()
    try:
        assert runner.run("math:hypot", (3, 4), 30) == 5.0
        t0 = time.monotonic()
        assert runner.run("time:sleep", (30,), 0.5) is TIMED_OUT
        assert time.monotonic() - t0 < 5
        assert len(killed) == 1
        assert not killed[0].proc.is_alive()
        assert runner.run("math:hypot", (6, 8), 30) == 10.0
    finally:
        runner.shutdown()


def test_searoute_runs_through_the_process_runner(monkeypatch):
    import route_engine
    import searoute_worker

    seen = []

    def fake_run(target, args, timeout_s):
        seen.append((target, args, timeout_s))
        return searoute_worker.TIMED_OUT

    monkeypatch.setattr(searoute_worker.RUNNER, "run", fake_run)
    assert route_engine._invoke_searoute((-1.7, 46.25), (-2.1, 46.05)) is None
    assert seen == [("searoute:searoute", ([-1.7, 46.25], [-2.1, 46.05]), route_engine.SEAROUTE_TIMEOUT_S)]


def test_unfolded_longitude_is_wrapped_not_refused(monkeypatch):
    seen = []

    def fake_route(start, end):
        seen.append((start, end))
        return {
            "type": "Feature",
            "geometry": {"type": "LineString", "coordinates": [[start[0], start[1]], [end[0], end[1]]]},
            "properties": {"length": 1, "units": "km"},
        }

    monkeypatch.setattr(main, "searoute_with_exact_end", fake_route)
    client = TestClient(main.app)
    for lon, wrapped in ((236.84, -123.16), (181.0, -179.0), (-200.0, 160.0)):
        response = client.get("/route", params={
            "start_lat": 37.0,
            "start_lon": lon,
            "end_lat": 36.0,
            "end_lon": lon - 1,
        })
        assert response.status_code == 200, (lon, response.text)
        start, end = seen[-1]
        assert abs(start[0] - wrapped) < 1e-6
        assert -180.0 <= end[0] <= 180.0
        # La géométrie revient dans le repère déplié de l'appelant.
        assert abs(response.json()["geometry"]["coordinates"][0][0] - lon) < 1e-6


def test_non_finite_or_absurd_longitude_is_422():
    client = TestClient(main.app)
    for bad in ("nan", "inf", "-inf", "540.5", "-541"):
        response = client.get("/route", params={
            "start_lat": 37.0,
            "start_lon": bad,
            "end_lat": 36.0,
            "end_lon": -123.0,
        })
        assert response.status_code == 422, bad


def test_end_longitude_beyond_540_is_422_and_540_is_accepted(monkeypatch):
    seen = []

    def fake_route(start, end):
        seen.append((start, end))
        return {
            "type": "Feature",
            "geometry": {"type": "LineString", "coordinates": [[start[0], start[1]], [end[0], end[1]]]},
            "properties": {"length": 1, "units": "km"},
        }

    monkeypatch.setattr(main, "searoute_with_exact_end", fake_route)
    monkeypatch.setattr(main, "endpoint_on_land", lambda *_a, **_k: False)
    client = TestClient(main.app)
    for bad in (540.01, 541, -540.5, 900):
        response = client.get("/route", params={
            "start_lat": 0.0, "start_lon": 170.0, "end_lat": 1.0, "end_lon": bad,
        })
        assert response.status_code == 422, bad
    assert seen == []
    for edge in (540, -540):
        response = client.get("/route", params={
            "start_lat": 0.0, "start_lon": 170.0, "end_lat": 1.0, "end_lon": edge,
        })
        assert response.status_code == 200, (edge, response.text)
        _start, end = seen[-1]
        assert -180.0 <= end[0] <= 180.0
        assert abs(abs(end[0]) - 180.0) < 1e-6
    response = client.get("/route", params={
        "start_lat": 0.0, "start_lon": 540, "end_lat": 1.0, "end_lon": 179.0,
    })
    assert response.status_code == 200, response.text


def test_runner_caps_concurrent_searoute_processes():
    import threading
    import time as _time

    import searoute_worker

    assert searoute_worker.MAX_BUSY == 4
    runner = searoute_worker.ProcessRunner(max_busy=1)
    try:
        results = {}

        def slow():
            results["slow"] = runner.run("time:sleep", (1.5,), 20.0)

        t = threading.Thread(target=slow)
        t.start()
        _time.sleep(0.3)
        t0 = _time.monotonic()
        # The only slot is busy: this call waits its deadline, then gives up
        # without starting a second process.
        assert runner.run("time:sleep", (0,), 0.3) is searoute_worker.TIMED_OUT
        assert _time.monotonic() - t0 < 1.0
        t.join(30)
        assert results["slow"] is None
        # Slot free again: the next call runs.
        assert runner.run("time:sleep", (0,), 20.0) is None
    finally:
        runner.shutdown()


def test_interrupted_call_kills_its_worker(monkeypatch):
    """Interrompu pendant le calcul (BaseException) : le process est tué, l'exception repart."""
    import pytest

    import searoute_worker
    from searoute_worker import ProcessRunner

    killed = []
    real_kill = searoute_worker._Worker.kill

    def kill(self):
        killed.append(self)
        real_kill(self)

    monkeypatch.setattr(searoute_worker._Worker, "kill", kill)
    runner = ProcessRunner()
    try:
        worker = runner._take()

        class Stop(BaseException):
            pass

        def poll(_timeout):
            raise Stop()

        monkeypatch.setattr(worker.conn, "poll", poll)
        monkeypatch.setattr(runner, "_take", lambda: worker)
        with pytest.raises(Stop):
            runner.run("time:sleep", (30,), 5)
        assert killed == [worker]
        assert not worker.proc.is_alive()
        assert runner._idle == []
    finally:
        runner.shutdown()


def _fresh(route_engine, start, end):
    route_engine._route_cache.pop(route_engine._route_cache_key(start, end), None)


def test_busy_searoute_is_503_not_crosses_land(monkeypatch):
    """Délai dépassé / sémaphore plein : 503 « busy », jamais 422 crosses_land."""
    import route_engine
    import searoute_worker

    monkeypatch.setattr(main, "endpoint_on_land", lambda *_a, **_k: False)
    monkeypatch.setattr(main, "segment_crosses_land", lambda *_a, **_k: True)
    monkeypatch.setattr(searoute_worker.RUNNER, "run", lambda *_a, **_k: searoute_worker.TIMED_OUT)
    _fresh(route_engine, (-1.7, 46.25), (-2.1, 46.05))
    client = TestClient(main.app)
    response = client.get("/route", params={"start_lat": 46.25, "start_lon": -1.7, "end_lat": 46.05, "end_lon": -2.1})
    assert response.status_code == 503
    assert response.json()["detail"] == "busy"


def test_dead_worker_is_503(monkeypatch):
    import route_engine
    import searoute_worker

    def died(*_a, **_k):
        raise searoute_worker.WorkerDied("gone")

    monkeypatch.setattr(main, "endpoint_on_land", lambda *_a, **_k: False)
    monkeypatch.setattr(searoute_worker.RUNNER, "run", died)
    _fresh(route_engine, (-1.7, 46.25), (-2.1, 46.05))
    response = TestClient(main.app).get("/route", params={"start_lat": 46.25, "start_lon": -1.7, "end_lat": 46.05, "end_lon": -2.1})
    assert response.status_code == 503


def test_no_route_from_searoute_still_checks_land(monkeypatch):
    """searoute a vraiment répondu « pas de route » : alors seulement crosses_land."""
    import route_engine

    monkeypatch.setattr(main, "endpoint_on_land", lambda *_a, **_k: False)
    monkeypatch.setattr(main, "segment_crosses_land", lambda *_a, **_k: True)
    monkeypatch.setattr(route_engine, "_invoke_searoute", lambda *_a, **_k: None)
    _fresh(route_engine, (-1.7, 46.25), (-2.1, 46.05))
    response = TestClient(main.app).get("/route", params={"start_lat": 46.25, "start_lon": -1.7, "end_lat": 46.05, "end_lon": -2.1})
    assert response.status_code == 422
    assert response.json()["detail"] == "crosses_land"


def test_on_land_says_which_end(monkeypatch):
    client = TestClient(main.app)
    monkeypatch.setattr(main, "searoute_with_exact_end", lambda *_a, **_k: (_ for _ in ()).throw(AssertionError()))
    monkeypatch.setattr(main, "endpoint_on_land", lambda lat, lon: lat > 48)
    start_land = client.get("/route", params={"start_lat": 48.85, "start_lon": 2.35, "end_lat": 46.2, "end_lon": -1.7})
    assert start_land.status_code == 422
    assert start_land.json() == {"detail": "on_land", "end": "on_land_start"}
    end_land = client.get("/route", params={"start_lat": 46.2, "start_lon": -1.7, "end_lat": 48.85, "end_lon": 2.35})
    assert end_land.json() == {"detail": "on_land", "end": "on_land_end"}


def test_detours_run_in_the_worker_with_the_time_left(monkeypatch):
    """avoid_land : searoute ne tourne jamais dans ce process, et chaque appel
    reçoit le reste du budget global (~12 s pour toute la requête)."""
    import route_engine
    import searoute_worker

    seen = []

    def fake_run(target, args, timeout_s):
        seen.append(timeout_s)
        a, b = args
        return {"type": "Feature", "geometry": {"type": "LineString", "coordinates": [a, [(a[0] + b[0]) / 2, a[1] - 1], b]}, "properties": {"length": 1, "units": "km"}}

    monkeypatch.setattr(searoute_worker.RUNNER, "run", fake_run)
    monkeypatch.setattr(route_engine, "_segment_crosses_land", lambda *a: len(seen) < 2)
    deadline = route_engine.time.monotonic() + 3.0
    route_engine.avoid_land([[0.0, 0.0], [1.0, 0.0]], max_iterations=1, deadline=deadline)
    assert seen and all(0 < t <= 3.0 for t in seen)
    assert route_engine.ROUTE_DEADLINE_S <= 12.0


def test_detour_past_the_deadline_is_busy(monkeypatch):
    import pytest

    import route_engine
    import searoute_worker

    monkeypatch.setattr(searoute_worker.RUNNER, "run", lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("no call once spent")))
    monkeypatch.setattr(route_engine, "_segment_crosses_land", lambda *a: True)
    with pytest.raises(route_engine.RouteBusy):
        route_engine.avoid_land([[0.0, 0.0], [1.0, 0.0]], max_iterations=1, deadline=route_engine.time.monotonic() - 0.1)


def test_whole_request_has_one_deadline(monkeypatch):
    import pytest

    import route_engine
    import searoute_worker

    budgets = []

    def slow(target, args, timeout_s):
        budgets.append(timeout_s)
        return searoute_worker.TIMED_OUT

    monkeypatch.setattr(searoute_worker.RUNNER, "run", slow)
    _fresh(route_engine, (-1.7, 46.25), (-2.1, 46.05))
    with pytest.raises(route_engine.RouteBusy):
        route_engine.searoute_with_exact_end((-1.7, 46.25), (-2.1, 46.05))
    assert budgets and budgets[0] <= route_engine.ROUTE_DEADLINE_S


def test_cached_length_is_the_final_line(monkeypatch):
    """properties.length = longueur géodésique des coordonnées servies, pas celle de searoute."""
    import route_engine

    start, end = (-1.7, 46.25), (-2.6, 46.05)

    def fake(_s, _e, _t=None):
        # searoute snaps to nodes 5 km from both ends and claims 1 km.
        return {"type": "Feature", "geometry": {"type": "LineString", "coordinates": [[-1.77, 46.25], [-2.53, 46.05]]}, "properties": {"length": 1.0, "units": "km"}}

    monkeypatch.setattr(route_engine, "_invoke_searoute", fake)
    monkeypatch.setattr(route_engine, "avoid_land", lambda c, **_k: c)
    _fresh(route_engine, start, end)
    route = route_engine.searoute_with_exact_end(start, end)
    coords = route["geometry"]["coordinates"]
    assert coords[0][:2] == [start[0], start[1]]
    expected = route_engine.route_length_km(coords)
    assert route["properties"]["units"] == "km"
    assert abs(route["properties"]["length"] - expected) < 0.01
    assert route["properties"]["length"] > 60
    cached = route_engine.searoute_with_exact_end(start, end)
    assert abs(cached["properties"]["length"] - expected) < 0.01


def test_same_point_answer_is_unfolded(monkeypatch):
    monkeypatch.setattr(main, "endpoint_on_land", lambda *_a, **_k: False)
    response = TestClient(main.app).get("/route", params={"start_lat": -17.5, "start_lon": 214.02, "end_lat": -17.5, "end_lon": 214.02})
    assert response.status_code == 200
    coords = response.json()["geometry"]["coordinates"]
    assert all(abs(c[0] - 214.02) < 1e-9 for c in coords)


def test_route_deadline_leaves_room_after_one_searoute_call():
    import route_engine

    # One searoute call may use its whole time-out and still leave time for
    # the detours around land before the request answers « busy ».
    assert route_engine.ROUTE_DEADLINE_S >= route_engine.SEAROUTE_TIMEOUT_S + 3.0
    assert route_engine.ROUTE_DEADLINE_S <= 12.0


def _forbid_searoute(monkeypatch, route_engine):
    def boom(*_args, **_kwargs):
        raise AssertionError("searoute ne doit pas partir pour calculer la clé")

    monkeypatch.setattr(route_engine, "_invoke_searoute", boom)
    monkeypatch.setattr(route_engine, "searoute_with_exact_end", boom)


def test_route_cache_key_carries_engine_rev_and_catalog_fingerprint(monkeypatch):
    """Même extrémités, empreintes différentes : deux clés. Aucun appel searoute."""
    import route_engine

    _forbid_searoute(monkeypatch, route_engine)
    assert route_engine.ENGINE_REV == 2

    start, end = (-1.7, 46.25), (-2.1, 46.05)
    empty = route_engine._catalog_id_fingerprint([])
    assert empty != "unavailable"
    with_geom = route_engine._catalog_id_fingerprint([
        {"id": "B", "geom": {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]]}},
        {"id": "A", "geom": {"type": "Polygon", "coordinates": [[[9, 9], [8, 9], [8, 8], [9, 9]]]}},
    ])
    same_ids = route_engine._catalog_id_fingerprint([
        {"id": "A", "geom": "autre"},
        {"id": "B"},
    ])
    other = route_engine._catalog_id_fingerprint([{"id": "A"}, {"id": "C"}])
    named_unavailable = route_engine._catalog_id_fingerprint([{"id": "unavailable"}])

    key_empty = route_engine._route_cache_key(start, end, catalog_fp=empty)
    key_ids = route_engine._route_cache_key(start, end, catalog_fp=with_geom)
    key_same = route_engine._route_cache_key(end, start, catalog_fp=same_ids)
    key_other = route_engine._route_cache_key(start, end, catalog_fp=other)
    key_down = route_engine._route_cache_key(start, end, catalog_fp="unavailable")
    key_word = route_engine._route_cache_key(start, end, catalog_fp=named_unavailable)

    assert key_empty[0] == route_engine.ENGINE_REV
    assert key_ids == key_same
    assert key_ids != key_other
    assert key_empty != key_down
    assert key_down[-1] == "unavailable"
    assert key_empty[-1] != "unavailable"
    assert key_word[-1] != "unavailable"
    assert len(key_empty) == 4


def test_live_catalog_fingerprint_changes_the_cache_key(monkeypatch):
    """Le catalogue chargé (même vide) n'a pas l'empreinte d'une panne."""
    import amp_nogo
    import route_engine

    _forbid_searoute(monkeypatch, route_engine)

    def no_network(*_args, **_kwargs):
        raise AssertionError("pas d'appel réseau pour l'empreinte")

    monkeypatch.setattr("httpx.get", no_network)
    start, end = (0.0, 0.0), (1.0, 1.0)
    ring = [[-2.0, 46.0], [-1.5, 46.0], [-1.5, 46.3], [-2.0, 46.3], [-2.0, 46.0]]
    other = [[-10.0, 40.0], [-9.0, 40.0], [-9.0, 41.0], [-10.0, 41.0], [-10.0, 40.0]]

    def feat(site_id, shell):
        return {
            "type": "Feature",
            "properties": {"site_id": site_id, "entry": 1, "speed": 3},
            "geometry": {"type": "Polygon", "coordinates": [shell]},
        }

    def use(features):
        amp_nogo.reset_nogo_cache()
        monkeypatch.setattr(
            amp_nogo, "_fetch_nogo",
            lambda: {"type": "FeatureCollection", "features": features},
        )
        return route_engine._route_cache_key(start, end)

    try:
        key_ab = use([feat("B", ring), feat("A", other)])
        key_ab_swapped = use([feat("A", ring), feat("B", other)])
        key_ac = use([feat("A", ring), feat("C", other)])
        key_empty = use([])
        amp_nogo.reset_nogo_cache()

        def down():
            raise RuntimeError("catalogue en panne")

        monkeypatch.setattr(amp_nogo, "_fetch_nogo", down)
        key_down = route_engine._route_cache_key(start, end)
        key_down_back = route_engine._route_cache_key(end, start)
    finally:
        amp_nogo.reset_nogo_cache()

    assert key_ab == key_ab_swapped
    assert key_ab != key_ac
    assert key_ab[0] == 2
    assert key_empty[-1] == route_engine._catalog_id_fingerprint([])
    assert key_empty[-1] != "unavailable"
    assert key_down[-1] == "unavailable"
    assert key_empty != key_down
    assert key_down_back == key_down
