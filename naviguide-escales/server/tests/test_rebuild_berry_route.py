"""Outil de recalcul : moteur simulé, aucun appel searoute, rien dans le fichier public.

Le FeatureCollection de test n'est pas le fichier publié. Il ne va ni dans
public/route.geojson, ni dans un stock du poste.
"""
import json
from pathlib import Path

import pytest

from rebuild_berry_route import (
    build_manifest,
    dest_targets_public_route,
    land_hit_counts,
    main,
    manifest_path_for,
    public_route_file,
    rebuild_collection,
)

PANAMA = [-79.9, 9.1]
SUEZ = [32.2, 30.2]
CAYENNE = [-52.33, 4.94]
PAPEETE = [-149.57, -17.54]
HALIFAX = [-63.57, 44.65]
SPM = [-56.17, 46.78]
CAPE_A = [18.5, -34.4]
CAPE_B = [20.0, -35.0]
SAINT_MAUR = [2.47, 48.79]
LA_ROCHELLE = [-1.15, 46.16]


def _line(src: str, dst: str, kind: str, coords: list, name: str | None = None) -> dict:
    props = {"from": src, "to": dst, "type": kind}
    if name:
        props["name"] = name
    return {
        "type": "Feature",
        "properties": props,
        "geometry": {"type": "LineString", "coordinates": coords},
    }


def sample_collection() -> dict:
    return {
        "type": "FeatureCollection",
        "features": [
            _line("Cayenne", "Papeete", "maritime", [CAYENNE, [-70.0, 12.0], PAPEETE]),
            _line("Halifax", "Saint-Pierre", "maritime", [HALIFAX, SPM]),
            _line("Saint-Pierre", "Halifax", "maritime", [SPM, HALIFAX]),
            _line(
                "Le Cap",
                "Melbourne",
                "maritime",
                [CAPE_A, CAPE_B],
                name="Cap de Bonne Espérance",
            ),
            _line("Saint-Maur-des-Fossés", "La Rochelle", "overland", [SAINT_MAUR, LA_ROCHELLE]),
            {
                "type": "Feature",
                "properties": {"name": "Papeete"},
                "geometry": {"type": "Point", "coordinates": PAPEETE},
            },
        ],
    }


def _key(point) -> tuple[float, float]:
    return (round(float(point[0]), 2), round(float(point[1]), 2))


def _feature(coords, *, open_status: bool = False) -> dict:
    props = {"length": 1.0, "units": "km"}
    if open_status:
        props["constraintStatus"] = "open"
    return {
        "type": "Feature",
        "properties": props,
        "geometry": {"type": "LineString", "coordinates": coords},
    }


def _engine(
    calls: list,
    *,
    suez: bool = False,
    drop_halifax: bool = False,
    open_leg: bool = False,
    drop_panama: bool = False,
    horn: bool = False,
):
    def route_fn(start, end, deadline=None):
        calls.append((_key(start), _key(end)))
        pair = (_key(start), _key(end))
        if pair == (_key(SAINT_MAUR), _key(LA_ROCHELLE)):
            raise AssertionError("l'overland ne se recalcule pas")
        if pair == (_key(CAYENNE), _key(PAPEETE)):
            if drop_panama:
                return _feature([CAYENNE, [-70.0, 12.0], PAPEETE])
            if horn:
                return _feature([CAYENNE, PANAMA, [-67.0, -55.0], PAPEETE])
            return _feature([CAYENNE, PANAMA, PAPEETE])
        if pair == (_key(HALIFAX), _key(SPM)):
            return _feature([HALIFAX, SPM], open_status=open_leg)
        if pair == (_key(SPM), _key(HALIFAX)):
            if drop_halifax:
                return None
            return _feature([SPM, HALIFAX])
        if pair == (_key(CAPE_A), _key(CAPE_B)):
            coords = [CAPE_A, SUEZ, CAPE_B] if suez else [CAPE_A, CAPE_B]
            return _feature(coords)
        raise AssertionError(f"jambe inattendue {pair}")

    return route_fn


def _write_src(tmp_path: Path) -> Path:
    src = tmp_path / "collection.geojson"
    src.write_text(json.dumps(sample_collection()), encoding="utf-8")
    return src


def _public_digest() -> bytes:
    return public_route_file().read_bytes()


def test_collection_argument_does_not_touch_the_public_file(tmp_path, monkeypatch):
    def boom(*_args, **_kwargs):
        raise AssertionError("moteur réel")

    monkeypatch.setattr("rebuild_berry_route._default_route_fn", boom)
    before = _public_digest()
    calls: list = []
    source = sample_collection()
    candidate, violations, manifest = rebuild_collection(source, _engine(calls))
    assert violations == []
    assert [row["from"] for row in manifest] == [
        "Cayenne",
        "Halifax",
        "Saint-Pierre",
        "Le Cap",
        "Saint-Maur-des-Fossés",
    ]
    assert len(calls) == 4
    assert not list(tmp_path.iterdir())
    assert _public_digest() == before
    cayenne = next(
        feature
        for feature in candidate["features"]
        if (feature.get("properties") or {}).get("from") == "Cayenne"
    )
    assert PANAMA in cayenne["geometry"]["coordinates"]
    assert [feature for feature in candidate["features"] if (feature.get("properties") or {}).get("type") == "overland"] == [
        feature for feature in source["features"] if (feature.get("properties") or {}).get("type") == "overland"
    ]


def test_dry_run_report_is_compliant_and_writes_nothing(tmp_path, monkeypatch, capsys):
    def boom(*_args, **_kwargs):
        raise AssertionError("moteur réel")

    monkeypatch.setattr("rebuild_berry_route._default_route_fn", boom)
    src = _write_src(tmp_path)
    raw = src.read_text(encoding="utf-8")
    before = _public_digest()
    calls: list = []
    code = main(["--src", str(src)], route_fn=_engine(calls))
    out = capsys.readouterr().out
    assert code == 0
    assert len(calls) == 4
    assert "Cayenne → Papeete : Panama présent" in out
    assert "Suez : aucun sommet" in out
    assert "Bonne Espérance : nommé" in out
    assert "Halifax ↔ Saint-Pierre : 2 jambes maritimes" in out
    assert "overland : 1" in out
    assert "Cayenne ↔ Halifax : aucune" in out
    assert "contraintes ouvertes : aucune" in out
    assert "écriture : non" in out
    assert "manifeste : non" in out
    assert "verdict : conforme" in out
    assert src.read_text(encoding="utf-8") == raw
    assert _public_digest() == before
    assert list(tmp_path.glob("*.geojson")) == [src]
    assert list(tmp_path.glob("*.manifest.json")) == []
    assert list(tmp_path.glob("*.tmp")) == []


def _assert_compliant_manifest(rows: list, written: dict) -> None:
    from route_engine import route_length_km

    lines = [
        feature
        for feature in written["features"]
        if (feature.get("geometry") or {}).get("type") == "LineString"
    ]
    assert len(rows) == len(lines) == 5
    for row, feature in zip(rows, lines):
        props = feature.get("properties") or {}
        coords = feature["geometry"]["coordinates"]
        assert row["from"] == props.get("from")
        assert row["to"] == props.get("to")
        assert row["longueur"] == round(route_length_km(coords), 3)
        assert row["longueur"] > 0
        assert row["hitsTerre"] == land_hit_counts(coords)
        assert isinstance(row["hitsTerre"]["echantillonneur"], int)
        assert row["hitsTerre"]["oracle"] is None or isinstance(row["hitsTerre"]["oracle"], int)
        assert row["hitsAires"] == 0
        assert row["constraintStatus"] is None
    by_leg = {(row["from"], row["to"]): row for row in rows}
    assert by_leg[("Cayenne", "Papeete")]["passageNomme"] == "Panama"
    assert by_leg[("Cayenne", "Papeete")]["jambeHalifax"] is False
    assert by_leg[("Le Cap", "Melbourne")]["passageNomme"] == "Bonne Espérance"
    halifax = [row for row in rows if row["jambeHalifax"]]
    assert {(row["from"], row["to"]) for row in halifax} == {
        ("Halifax", "Saint-Pierre"),
        ("Saint-Pierre", "Halifax"),
    }
    assert all(row["passageNomme"] is None and row["overlandSaintMaur"] is False for row in halifax)
    overland = [row for row in rows if row["overlandSaintMaur"]]
    assert len(overland) == 1
    assert overland[0]["from"] == "Saint-Maur-des-Fossés"
    assert overland[0]["to"] == "La Rochelle"
    assert overland[0]["passageNomme"] is None
    assert overland[0]["jambeHalifax"] is False
    assert overland[0]["hitsTerre"]["oracle"] >= 1


def test_write_outside_public_keeps_contract(tmp_path, capsys):
    src = _write_src(tmp_path)
    source = json.loads(src.read_text(encoding="utf-8"))
    before = _public_digest()
    dest = tmp_path / "candidat.geojson"
    calls: list = []
    code = main(
        ["--src", str(src), "--write", "--dest", str(dest)],
        route_fn=_engine(calls),
    )
    out = capsys.readouterr().out
    manifest_path = manifest_path_for(dest)
    assert code == 0
    assert dest.is_file()
    assert manifest_path.is_file()
    assert f"manifeste : {manifest_path.name}" in out
    written = json.loads(dest.read_text(encoding="utf-8"))
    assert len(written["features"]) == len(source["features"])
    assert [f for f in written["features"] if (f.get("properties") or {}).get("type") == "overland"] == [
        f for f in source["features"] if (f.get("properties") or {}).get("type") == "overland"
    ]
    papeete = next(
        f
        for f in written["features"]
        if (f.get("properties") or {}).get("from") == "Cayenne"
    )
    assert PANAMA in papeete["geometry"]["coordinates"]
    halifax = [
        feature
        for feature in written["features"]
        if (feature.get("properties") or {}).get("type") == "maritime"
        and "Halifax" in ((feature.get("properties") or {}).get("from") or "")
        and "Saint-Pierre" in ((feature.get("properties") or {}).get("to") or "")
    ]
    spm = [
        feature
        for feature in written["features"]
        if (feature.get("properties") or {}).get("type") == "maritime"
        and "Saint-Pierre" in ((feature.get("properties") or {}).get("from") or "")
        and "Halifax" in ((feature.get("properties") or {}).get("to") or "")
    ]
    assert len(halifax) == 1 and len(spm) == 1
    assert halifax[0] is not spm[0]
    assert dest_targets_public_route(dest) is False
    assert _public_digest() == before
    assert "hitsTerre" not in dest.read_text(encoding="utf-8")
    rows = json.loads(manifest_path.read_text(encoding="utf-8"))
    _assert_compliant_manifest(rows, written)


@pytest.mark.parametrize(
    ("flag", "needle"),
    [
        ("suez", "sommet dans la boîte Suez"),
        ("halifax", "deux jambes maritimes"),
        ("panama", "boîte Panama"),
        ("horn", "40° S"),
    ],
)
def test_suez_or_lost_halifax_exits_nonzero_and_writes_nothing(tmp_path, capsys, flag, needle):
    src = _write_src(tmp_path)
    before = _public_digest()
    dest = tmp_path / "candidat.geojson"
    calls: list = []
    code = main(
        ["--src", str(src), "--write", "--dest", str(dest)],
        route_fn=_engine(
            calls,
            suez=flag == "suez",
            drop_halifax=flag == "halifax",
            drop_panama=flag == "panama",
            horn=flag == "horn",
        ),
    )
    out = capsys.readouterr().out
    assert code != 0
    assert needle in out
    assert "verdict : refusé" in out
    assert "écriture : non" in out
    assert not dest.exists()
    assert not manifest_path_for(dest).exists()
    assert list(tmp_path.glob("*.manifest.json")) == []
    assert list(tmp_path.glob("*.tmp")) == []
    assert _public_digest() == before
    assert calls


def test_dry_run_refusal_writes_nothing(tmp_path, capsys):
    src = _write_src(tmp_path)
    before = _public_digest()
    code = main(["--src", str(src)], route_fn=_engine([], suez=True))
    out = capsys.readouterr().out
    assert code != 0
    assert "sommet dans la boîte Suez" in out
    assert "écriture : non" in out
    assert "manifeste : non" in out
    assert _public_digest() == before
    assert list(tmp_path.glob("*.geojson")) == [src]
    assert list(tmp_path.glob("*.manifest.json")) == []


def test_server_startup_and_ci_do_not_launch_the_tool():
    server = Path(__file__).resolve().parents[1]
    root = server.parents[1]
    main_py = (server / "main.py").read_text(encoding="utf-8")
    voyage = (server / "voyage_api.py").read_text(encoding="utf-8")
    assert "rebuild_berry_route" not in main_py
    assert ".manifest.json" not in main_py
    assert "hitsTerre" not in main_py
    assert ".manifest.json" not in voyage
    assert "hitsTerre" not in voyage
    workflow = root / ".github" / "workflows" / "ci.yml"
    assert "rebuild_berry_route" not in workflow.read_text(encoding="utf-8")
    for path in (server.parent / "src").rglob("*"):
        if path.suffix not in {".js", ".jsx"}:
            continue
        text = path.read_text(encoding="utf-8")
        assert ".manifest.json" not in text, path
        assert "hitsTerre" not in text, path


def test_open_constraint_is_not_written(tmp_path, capsys):
    src = _write_src(tmp_path)
    before = _public_digest()
    dest = tmp_path / "candidat.geojson"
    code = main(
        ["--src", str(src), "--write", "--dest", str(dest)],
        route_fn=_engine([], open_leg=True),
    )
    out = capsys.readouterr().out
    assert code != 0
    assert "constraintStatus open" in out
    assert "verdict : refusé" in out
    assert not dest.exists()
    assert not manifest_path_for(dest).exists()
    assert list(tmp_path.glob("*.tmp")) == []
    assert _public_digest() == before


def test_write_without_dest_is_refused_before_compute(tmp_path, capsys):
    calls: list = []
    code = main(
        ["--write", "--src", str(tmp_path / "absent.geojson")],
        route_fn=_engine(calls),
    )
    err = capsys.readouterr().err
    assert code != 0
    assert calls == []
    assert "--dest" in err
    assert "source illisible" not in err


def test_write_public_route_is_refused_before_compute(tmp_path, monkeypatch, capsys):
    public = public_route_file()
    before = public.read_bytes()
    calls: list = []
    simulator = public.parent.parent
    monkeypatch.chdir(simulator)
    targets = [
        str(public),
        "public/route.geojson",
        str(public.parent / ".." / "public" / "route.geojson"),
    ]
    link = tmp_path / "lien.geojson"
    link.symlink_to(public)
    targets.append(str(link))
    linked_dir = tmp_path / "pub"
    linked_dir.symlink_to(public.parent, target_is_directory=True)
    targets.append(str(linked_dir / "route.geojson"))
    for dest in targets:
        calls.clear()
        code = main(
            ["--src", str(tmp_path / "absent.geojson"), "--write", "--dest", dest],
            route_fn=_engine(calls),
        )
        captured = capsys.readouterr()
        assert code != 0, dest
        assert calls == [], dest
        assert "public/route.geojson" in captured.err, dest
        assert "source illisible" not in captured.err
        assert "verdict" not in captured.out
        assert public.read_bytes() == before
    assert dest_targets_public_route(link)
    assert dest_targets_public_route(linked_dir / "route.geojson")


# Trait qui traverse North Chesterfield dans l'extrait figé : les bouts sont
# dehors, un point du segment est dedans.
_NC = [[158.084, -19.82437], [159.189, -19.82437]]


def test_land_oracle_sees_iberia_when_shapely_is_present():
    counts = land_hit_counts([[-9.0, 40.0], [-1.0, 40.0]])
    assert counts["oracle"] is not None
    assert counts["oracle"] >= 1
    assert counts["echantillonneur"] >= 1


def test_dateline_jump_is_not_a_north_chesterfield_hit():
    feature = _line("Est", "Ouest", "maritime", [[170.0, -19.3], [-170.0, -19.3]])
    rows = build_manifest([feature], [None])
    assert rows[0]["hitsAires"] == 0


def test_frozen_pin_counts_north_chesterfield_and_ignores_the_ocean():
    nc = _line("Nouméa", "Lifou", "maritime", _NC)
    hit = build_manifest([nc], [None])
    assert hit[0]["hitsAires"] >= 1
    assert hit[0]["passageNomme"] is None
    ocean = _line("Cayenne", "Papeete", "maritime", [CAYENNE, PANAMA, PAPEETE])
    clear = build_manifest([ocean], [None])
    assert clear[0]["hitsAires"] == 0
    assert clear[0]["passageNomme"] == "Panama"


def test_area_hit_is_written_beside_a_compliant_candidate(tmp_path, capsys):
    collection = sample_collection()
    collection["features"].append(_line("Nouméa", "Lifou", "maritime", _NC))
    src = tmp_path / "collection.geojson"
    src.write_text(json.dumps(collection), encoding="utf-8")
    dest = tmp_path / "candidat.geojson"
    base = _engine([])

    def route_fn(start, end, deadline=None):
        if _key(start) == _key(_NC[0]) and _key(end) == _key(_NC[1]):
            return _feature(_NC)
        return base(start, end, deadline=deadline)

    before = _public_digest()
    code = main(
        ["--src", str(src), "--write", "--dest", str(dest)],
        route_fn=route_fn,
    )
    capsys.readouterr()
    assert code == 0
    rows = json.loads(manifest_path_for(dest).read_text(encoding="utf-8"))
    nc = next(row for row in rows if row["from"] == "Nouméa" and row["to"] == "Lifou")
    assert nc["hitsAires"] >= 1
    assert nc["jambeHalifax"] is False
    assert nc["overlandSaintMaur"] is False
    others = [row for row in rows if row is not nc]
    assert others
    assert all(row["hitsAires"] == 0 for row in others)
    assert _public_digest() == before


def test_constraint_status_from_the_engine_is_kept_when_not_open(tmp_path, capsys):
    src = _write_src(tmp_path)
    dest = tmp_path / "candidat.geojson"
    base = _engine([])

    def route_fn(start, end, deadline=None):
        route = base(start, end, deadline=deadline)
        if _key(start) == _key(HALIFAX) and _key(end) == _key(SPM):
            route = json.loads(json.dumps(route))
            route["properties"]["constraintStatus"] = "tenue"
        return route

    code = main(
        ["--src", str(src), "--write", "--dest", str(dest)],
        route_fn=route_fn,
    )
    capsys.readouterr()
    assert code == 0
    rows = json.loads(manifest_path_for(dest).read_text(encoding="utf-8"))
    halifax = next(row for row in rows if row["from"] == "Halifax")
    assert halifax["constraintStatus"] == "tenue"
    assert all(row["constraintStatus"] is None for row in rows if row["from"] != "Halifax")
    written = json.loads(dest.read_text(encoding="utf-8"))
    stored = next(
        feature
        for feature in written["features"]
        if (feature.get("properties") or {}).get("from") == "Halifax"
    )
    assert "constraintStatus" not in (stored.get("properties") or {})


def test_missing_pin_writes_neither_file(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr("rebuild_berry_route.PIN_PATH", tmp_path / "absent.geojson")
    src = _write_src(tmp_path)
    dest = tmp_path / "candidat.geojson"
    before = _public_digest()
    code = main(
        ["--src", str(src), "--write", "--dest", str(dest)],
        route_fn=_engine([]),
    )
    out = capsys.readouterr().out
    assert code != 0
    assert "extrait d'aires illisible" in out
    assert "écriture : non" in out
    assert "manifeste : non" in out
    assert not dest.exists()
    assert not manifest_path_for(dest).exists()
    assert _public_digest() == before


def test_write_does_not_call_searoute(tmp_path, monkeypatch, capsys):
    def boom(*_args, **_kwargs):
        raise AssertionError("searoute")

    monkeypatch.setattr("route_engine.searoute_with_exact_end", boom)
    src = _write_src(tmp_path)
    dest = tmp_path / "candidat.geojson"
    code = main(
        ["--src", str(src), "--write", "--dest", str(dest)],
        route_fn=_engine([]),
    )
    capsys.readouterr()
    assert code == 0
    assert manifest_path_for(dest).is_file()
