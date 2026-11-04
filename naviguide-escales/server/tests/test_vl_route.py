"""Route VL : plan sans réseau, ids du sac, cache hors git."""
import asyncio
import json
import os
import socket
import struct
import zlib
from pathlib import Path

import pytest

import llm_budget
import one_shot
import vl_route


@pytest.fixture(autouse=True)
def _reset_vl_hooks():
    vl_route.set_transport(None)
    vl_route.set_bag_provider(None)
    yield
    vl_route.set_transport(None)
    vl_route.set_bag_provider(None)


def _forbid_network(monkeypatch):
    def connect(self, address):
        raise AssertionError("réseau interdit")

    def create_connection(*args, **kwargs):
        raise AssertionError("réseau interdit")

    monkeypatch.setattr(socket.socket, "connect", connect)
    monkeypatch.setattr(socket, "create_connection", create_connection)


def _line(n=61):
    return [
        {"lat": i * 0.1, "lon": 0.0, "cumNm": float(i * 100), "jump": False}
        for i in range(n)
    ]


def _marks(track):
    return [
        {
            "name": "Départ",
            "lat": track[0]["lat"],
            "lon": track[0]["lon"],
            "nm": track[0]["cumNm"],
            "index": 0,
        },
        {
            "name": "Arrivée",
            "lat": track[-1]["lat"],
            "lon": track[-1]["lon"],
            "nm": track[-1]["cumNm"],
            "index": len(track) - 1,
        },
    ]


def test_official_route_is_bounded_and_offline(monkeypatch):
    _forbid_network(monkeypatch)
    points = vl_route.key_points(crossings=[])
    roles = {}
    ids = []
    for point in points:
        roles[point["role"]] = roles.get(point["role"], 0) + 1
        ids.append(point["callId"])
        assert vl_route._CALL_ID.fullmatch(point["callId"])
    assert roles.get("escale") == 17
    assert roles.get("leg") == 11
    assert len(points) == 28
    assert len(points) <= vl_route.MAX_IMAGES
    assert len(ids) == len(set(ids))
    info = vl_route.describe(points)
    assert info["points"] == info["images"] == info["calls"] == 28
    assert info["tilesFetched"] == 0
    assert info["tiles"] == 28 * vl_route.TILE_SPAN * vl_route.TILE_SPAN
    text = vl_route.format_account(points)
    assert "points: 28" in text
    assert "images: 28" in text
    assert "tiles_fetched: 0" in text


def test_estimate_lists_images_without_calling(monkeypatch, tmp_path):
    _forbid_network(monkeypatch)
    monkeypatch.setenv(one_shot.ENV_DIR, str(tmp_path / "one-shot"))
    seen = []

    def execute(call):
        seen.append(call.call_id)
        raise AssertionError("appel")

    monkeypatch.setattr(one_shot.REGISTRY["vl_route_bm"], "execute", execute)
    code = one_shot.main(["--job", "vl_route_bm", "--estimate"])
    assert code == 0
    assert seen == []
    est = one_shot.build_estimate("vl_route_bm")
    assert est["calls"] == 28
    assert est["prompt_tokens"] == 28 * vl_route.PROMPT_TOKENS
    assert est["completion_tokens"] == 28 * vl_route.COMPLETION_TOKENS
    part = llm_budget.estimate_usd("write", vl_route.PROMPT_TOKENS, vl_route.COMPLETION_TOKENS)
    assert est["usd"] == round(28 * part, 8)
    assert est["fingerprint"] == one_shot.fingerprint_for(est)
    assert all(item["tier"] == "write" for item in est["items"])
    job_dir = Path(os.environ[one_shot.ENV_DIR]) / "vl_route_bm"
    assert not (job_dir / ".lock").exists()
    assert not (job_dir / ".done").exists()


def test_run_keeps_the_execution_lock_and_the_done_file(monkeypatch, tmp_path):
    """``.lock`` et ``.done`` restent ceux du socle. Le second passage est refusé."""
    _forbid_network(monkeypatch)
    monkeypatch.setenv(one_shot.ENV_DIR, str(tmp_path / "one-shot"))
    vl_route.set_bag_provider(lambda _point: [])
    called = []
    vl_route.set_transport(lambda *_args: called.append(1) or "{}")
    est = one_shot.build_estimate("vl_route_bm")
    job_dir = Path(os.environ[one_shot.ENV_DIR]) / "vl_route_bm"
    result = one_shot.run("vl_route_bm", est["fingerprint"])
    assert called == []
    assert len(result["completed"]) == est["calls"]
    assert (job_dir / ".lock").is_file()
    assert (job_dir / ".done").is_file()
    with pytest.raises(one_shot.Refused) as refused:
        one_shot.run("vl_route_bm", est["fingerprint"])
    assert refused.value.code == "locked"
    assert (job_dir / ".lock").is_file()
    assert (job_dir / ".done").is_file()


def test_crossings_are_bounded_and_formalites_are_not_zee():
    assert vl_route.crossing_role({
        "kind": "zee-enter", "event": "enter", "title": "Zone économique exclusive française",
    }) == "zee-enter"
    assert vl_route.crossing_role({
        "kind": "zee", "event": "exit", "title": "haute mer",
    }) == "zee-exit"
    assert vl_route.crossing_role({
        "kind": "zee-enter", "title": "Ports d'entrée", "fact": "Formalités",
    }) is None
    assert vl_route.crossing_role({
        "kind": "amp", "title": "Pétoncles", "fact": "zone de pêche",
    }) is None
    assert vl_route.crossing_role({
        "kind": "amp", "title": "Cabrera", "iucn_cat": "II",
    }) == "amp-enter"
    assert vl_route.crossing_role({
        "kind": "alert-off", "title": "Cabrera", "iucn_cat": "II", "fact": "sortie du parc",
    }) == "amp-exit"

    track = _line()
    marks = _marks(track)
    crossings = [
        {"role": "zee-enter", "lat": track[10]["lat"], "lon": 0.0, "name": "ZEE"},
        {"role": "zee-exit", "lat": 80.0, "lon": 0.0, "name": "loin"},
        {"role": "amp-enter", "lat": track[0]["lat"], "lon": 0.0, "name": "sur escale"},
    ]
    for i in range(5, 25):
        crossings.append({
            "role": "zee-enter",
            "lat": track[i]["lat"],
            "lon": 0.0,
            "name": f"z{i}",
        })
    chosen = vl_route.select_key_points(track, marks, crossings)
    zee = [p for p in chosen if p["role"] == "zee-enter"]
    assert len(zee) <= vl_route.MAX_CROSSINGS
    assert all(p["name"] != "loin" for p in chosen)
    assert all(p["name"] != "sur escale" for p in chosen)
    assert len(chosen) <= vl_route.MAX_IMAGES
    jumped = _line()
    jumped[30]["jump"] = True
    assert vl_route._leg_samples(jumped, _marks(jumped)) == []
    assert len(vl_route._leg_samples(track, marks)) == 2


def test_png_is_local_and_tiles_are_not_fetched(monkeypatch):
    _forbid_network(monkeypatch)
    point = vl_route.key_points(crossings=[])[1]
    refs = vl_route.tile_refs(point["lat"], point["lon"])
    assert len(refs) == 4
    assert {ref["z"] for ref in refs} == {vl_route.TILE_ZOOM}
    png = vl_route.render_png(point)
    assert png.startswith(b"\x89PNG\r\n\x1a\n")
    i = 8
    idat = b""
    width = height = None
    while i < len(png):
        size = struct.unpack(">I", png[i:i + 4])[0]
        tag = png[i + 4:i + 8]
        data = png[i + 8:i + 8 + size]
        crc = struct.unpack(">I", png[i + 8 + size:i + 12 + size])[0]
        assert zlib.crc32(tag + data) & 0xFFFFFFFF == crc
        if tag == b"IHDR":
            width, height, bit, color, *_rest = struct.unpack(">IIBBBBB", data)
        elif tag == b"IDAT":
            idat += data
        i += 12 + size
        if tag == b"IEND":
            break
    raw = zlib.decompress(idat)
    assert (width, height, bit, color) == (96, 96, 8, 2)
    assert len(raw) == 96 * (1 + 96 * 3)


def test_parse_rejects_unknown_ids_numbers_and_prose():
    allowed = ["dc:amp", "dc:poe"]
    rows = vl_route.parse_response(json.dumps({
        "ids": ["dc:poe", "invented-id", "dc:poe", {"id": "dc:amp", "reason": "aire marine"}],
        "reasons": {"dc:poe": "formalités"},
        "script": "Berry-Mappemonde quitte La Rochelle sous 99 nœuds.",
    }), allowed)
    assert [row["id"] for row in rows] == ["dc:poe", "dc:amp"]
    assert rows[0]["reason"] == "formalités"
    assert rows[1]["reason"] == "aire marine"
    assert "Berry" not in json.dumps(rows)
    numbered = vl_route.parse_response(json.dumps({
        "ids": ["dc:amp", "12"],
        "reasons": {"dc:amp": "12 milles au vent. Puis Cabrera."},
    }), allowed)
    assert numbered == [{"id": "dc:amp", "reason": "Puis Cabrera."}]
    assert vl_route.parse_response(
        "Berry quitte La Rochelle sous 12 nœuds.", allowed,
    ) == []
    assert vl_route.parse_response(json.dumps({"script": "une phrase"}), allowed) == []


def test_execute_is_simulated_and_cached(monkeypatch):
    _forbid_network(monkeypatch)
    point = vl_route.key_points(crossings=[])[0]
    seen = {}

    def transport(png, ids):
        seen["png"] = png
        seen["ids"] = list(ids)
        return json.dumps({
            "ids": ["not-in-bag", "dc:poe", "dc:amp"],
            "reasons": {
                "dc:poe": "formalités",
                "dc:amp": "99 nœuds",
                "not-in-bag": "hors sac",
            },
            "script": "une phrase inventée",
        })

    vl_route.set_transport(transport)
    vl_route.set_bag_provider(lambda _point: ["dc:amp", "dc:poe"])
    call = one_shot.PlannedCall(point["callId"], "write", 416, 64)
    out = vl_route.execute_call(call)
    assert seen["png"].startswith(b"\x89PNG")
    assert seen["ids"] == ["dc:amp", "dc:poe"]
    assert out["ids"] == ["dc:poe", "dc:amp"]
    doc = vl_route.load()
    assert doc["rev"] == "vb1"
    assert doc["route"] == vl_route.route_stamp()
    assert doc["ids"] == ["dc:poe", "dc:amp"]
    blob = json.dumps(doc, ensure_ascii=False)
    reasons = doc["points"][0].get("reasons") or {}
    assert "not-in-bag" not in blob
    assert "99" not in json.dumps(reasons)
    assert reasons.get("dc:amp", "") == ""
    assert "une phrase inventée" not in blob
    bag = [{"id": "dc:amp", "kind": "amp"}, {"id": "dc:watch", "kind": "watch"}]
    assert vl_route.ids_for_bag(bag) == ["dc:amp"]


def test_empty_bag_does_not_call_and_pytest_blocks_real_call():
    point = vl_route.key_points(crossings=[])[0]
    called = []
    vl_route.set_transport(lambda *_a: called.append(1) or "{}")
    vl_route.set_bag_provider(lambda _point: [])
    call = one_shot.PlannedCall(point["callId"], "write", 416, 64)
    out = vl_route.execute_call(call)
    assert called == []
    assert out["ids"] == []
    vl_route.set_transport(None)
    vl_route.set_bag_provider(lambda _point: ["dc:amp"])
    with pytest.raises(RuntimeError, match="interdit"):
        vl_route.execute_call(call)


def test_stale_or_broken_cache_yields_no_ids():
    bag = [{"id": "dc:amp"}]
    assert vl_route.ids_for_bag(bag) == []
    vl_route.save({
        "rev": "vb1",
        "route": "pas-la-route",
        "job": "vl_route_bm",
        "ids": ["dc:amp"],
        "points": [],
    })
    assert vl_route.ids_for_bag(bag) == []
    path = vl_route.result_path()
    path.write_text("{", encoding="utf-8")
    assert vl_route.load() is None
    assert vl_route.ids_for_bag(bag) == []
    assert "vl-route" in str(path)
    assert "vb1.json" in str(path)


def _vl_payload(content, *, finish="stop", prompt=501, completion=17, reasoning=None):
    message = {"role": "assistant", "content": content}
    if reasoning is not None:
        message["reasoning"] = reasoning
    return {
        "choices": [{"finish_reason": finish, "message": message}],
        "usage": {"prompt_tokens": prompt, "completion_tokens": completion},
    }


def _arm_vl_http(monkeypatch, payload, *, mode="all"):
    """httpx.MockTransport à la place du client réel. Aucune socket."""
    import httpx
    import story_cascade

    _forbid_network(monkeypatch)
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.setenv("NAVIGUIDE_LLM_MODE", mode)
    monkeypatch.setattr(story_cascade, "nebius_key", lambda: "test")
    seen = []

    def handler(request):
        body = json.loads(request.content.decode("utf-8"))
        seen.append({"model": body.get("model"), "url": str(request.url)})
        return httpx.Response(200, json=payload)

    transport = httpx.MockTransport(handler)
    real = httpx.Client

    def factory(*args, **kwargs):
        kwargs = dict(kwargs)
        kwargs["transport"] = transport
        return real(*args, **kwargs)

    monkeypatch.setattr(httpx, "Client", factory)
    vl_route.set_transport(None)
    return seen


def _one_point_call():
    point = vl_route.key_points(crossings=[])[0]
    vl_route.set_bag_provider(lambda _point: ["dc:amp"])
    return one_shot.PlannedCall(
        point["callId"], "write", vl_route.PROMPT_TOKENS, vl_route.COMPLETION_TOKENS,
    )


def _assert_write_usage(prompt, completion, calls=1):
    usage = llm_budget.get_usage("write")
    assert usage["calls"] == calls
    assert usage["prompt_tokens"] == prompt
    assert usage["completion_tokens"] == completion


def test_film_path_ids_for_bag_does_not_call_the_model(monkeypatch):
    """Le film lit le cache. Un appel modèle dans ids_for_bag se voit ici."""
    seen = _arm_vl_http(monkeypatch, _vl_payload('{"ids":["dc:amp"]}'))
    import film_script

    async def boom(*_a, **_k):
        raise AssertionError("appel modèle")

    bag = [{"id": "dc:amp", "kind": "amp", "phrase": "Cabrera"}]
    tour = {"legs": [{"name": "film", "iso": "2026-01-01T00:00:00Z"}]}
    assert vl_route.ids_for_bag(bag) == []
    asyncio.run(film_script.choose_film_ids(
        bag, tour, 150, cascade=boom, allow_llm=False,
    ))
    vl_route.save({
        "rev": vl_route.REV,
        "route": vl_route.route_stamp(),
        "job": vl_route.JOB,
        "ids": ["dc:amp"],
        "points": [],
    })
    assert vl_route.ids_for_bag(bag) == ["dc:amp"]
    ids, src = asyncio.run(film_script.choose_film_ids(
        bag,
        {"legs": [{"name": "film", "iso": "2026-01-02T00:00:00Z"}]},
        150,
        cascade=boom,
        allow_llm=False,
    ))
    assert seen == []
    assert src == "rules"
    assert ids == ["dc:amp"]


def test_execute_calls_the_model_once_and_records_usage(monkeypatch):
    """Un point, un POST. Retirer record ou doubler l'appel fait échouer."""
    import story_cascade

    content = json.dumps({"ids": ["dc:amp"], "reasons": {"dc:amp": "aire"}})
    seen = _arm_vl_http(monkeypatch, _vl_payload(content))
    out = vl_route.execute_call(_one_point_call())
    assert out["ids"] == ["dc:amp"]
    assert len(seen) == 1
    assert seen[0]["model"] == "nvidia/Nemotron-3.5-Super-VL"
    assert seen[0]["model"] == vl_route.vl_model()
    assert seen[0]["url"] == story_cascade._tf_url("write")
    _assert_write_usage(501, 17)


def test_call_vl_refuses_before_http_when_mode_blocks(monkeypatch):
    """Sans llm_allowed_here, le mode off atteint quand même le transport."""
    content = json.dumps({"ids": ["dc:amp"]})
    seen = _arm_vl_http(monkeypatch, _vl_payload(content), mode="off")
    with pytest.raises(RuntimeError, match="refusé"):
        vl_route.execute_call(_one_point_call())
    assert seen == []
    assert llm_budget.get_usage("write")["calls"] == 0


def test_empty_reasoning_response_is_still_counted(monkeypatch):
    """finish_reason=length, contenu vide : facturé, donc compté, puis rejeté."""
    seen = _arm_vl_http(monkeypatch, _vl_payload(
        None, finish="length", reasoning="only thinking",
    ))
    with pytest.raises(RuntimeError, match="réponse vide"):
        vl_route.execute_call(_one_point_call())
    assert len(seen) == 1
    _assert_write_usage(501, 17)


def test_estimate_prints_points_and_images(monkeypatch, capsys, tmp_path):
    """--estimate affiche points et images. L'empreinte ne les contient pas."""
    _forbid_network(monkeypatch)
    monkeypatch.setenv(one_shot.ENV_DIR, str(tmp_path / "one-shot"))
    code = one_shot.main(["--job", "vl_route_bm", "--estimate"])
    out = capsys.readouterr().out
    assert code == 0
    est = one_shot.build_estimate("vl_route_bm")
    assert "points" not in est
    assert "images" not in est
    assert f"calls: {est['calls']}" in out
    assert "points: 28" in out
    assert "images: 28" in out
    assert "tiles_fetched: 0" in out
    assert "escale=17" in out
    assert "leg=11" in out
    assert f"fingerprint: {est['fingerprint']}" in out
    assert not (tmp_path / "one-shot").exists()


def test_ici_bag_offers_a_buoy_and_ignores_other_stations():
    assert vl_route.ids_from_ici_bag({
        "science": {"nearby": [{"name": "Station", "source": "buoy", "kind": "mooring"}]},
    }) == ["dc:buoy"]
    assert vl_route.ids_from_ici_bag({
        "science": {"nearby": [{"name": "Float", "source": "argo", "kind": "argo_float"}]},
    }) == []
    assert "dc:buoy" not in vl_route.ids_from_ici_bag({
        "aton": {"nearby": [{"name": "buoy_lateral"}]},
    })


def test_ici_bag_keeps_present_families_only():
    assert vl_route.ids_from_ici_bag({
        "amp": [
            {"name": "Pétoncles", "designation": "fishery"},
            {"name": "Cabrera", "designation": "Parc"},
        ],
        "poe": [{"name": "Papeete"}],
        "emodnet": {"cables": {"name": "Honotua"}, "bathy": {"depth_m": 18}},
        "satellites": {"caption": "panache"},
    }) == ["dc:amp", "dc:poe", "dc:cable", "dc:depth", "dc:satellite"]
    assert vl_route.ids_from_ici_bag({}) == []
    assert vl_route.ids_from_ici_bag(None) == []
