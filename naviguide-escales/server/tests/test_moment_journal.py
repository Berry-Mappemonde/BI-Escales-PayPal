"""Journal des moments : diff, remplissage idempotent, until."""
from __future__ import annotations

import copy

from fastapi.testclient import TestClient

from moment import build_moment, load_official_mini
from moment_journal import (
    COAST_NEAR_NM,
    PROJECT_NEAR_NM,
    SCORE_ALERT_OFF,
    SCORE_ALERT_ON,
    SCORE_AMP,
    SCORE_APPROCHE,
    SCORE_ESCALE,
    SCORE_PROJECT,
    SCORE_REGIME,
    SCORE_STATION,
    SCORE_ZEE,
    _new_places_nearby,
    _new_projects_nearby,
    diff_moments,
    named_title,
    read_moments,
    rows_from_voyage,
    warm_moments,
)
from voyage_clock import OFFICIAL_VOYAGE_ID
from voyage_store import save_voyage


def _fixture_voyage(voyage_id=None):
    voy = load_official_mini()
    voy["voyageId"] = voyage_id or voy["voyageId"]
    save_voyage(voy)
    return voy


def _moment(voy, pearl_idx, extra_pearl=None, extra_clock=None, extra_leg=None):
    pearl = copy.deepcopy(voy["pearls"][pearl_idx])
    if extra_pearl:
        pearl.update(extra_pearl)
    sail = float(pearl.get("sailNm") or 0)
    clock = copy.deepcopy(min(
        voy["clock"]["vertices"],
        key=lambda v: abs(float(v.get("sailNm") or 0) - sail),
    ))
    if extra_clock:
        clock.update(extra_clock)
    leg = copy.deepcopy(voy["legs"][0 if sail <= 3350 else 1])
    if extra_leg:
        leg.update(extra_leg)
    return build_moment(pearl, clock, leg, voy["skipper_thresholds"], lang="fr")


def test_diff_moments_scores_match_plan():
    voy = load_official_mini()
    base = _moment(voy, 0)
    escale = _moment(voy, 0, extra_leg={"to": "Fort-de-France (Martinique)", "from": "La Rochelle"})
    # Même perle, destination changée.
    other_leg = copy.deepcopy(escale)
    other_leg["leg"] = {**escale["leg"], "to": "Pointe-à-Pitre (Guadeloupe)"}
    kinds = {c["kind"]: c for c in diff_moments(escale, other_leg)}
    assert kinds["escale"]["score"] == SCORE_ESCALE

    alert_on = copy.deepcopy(base)
    alert_on["alerts"] = list(base.get("alerts") or []) + [{
        "id": "wind-test", "kind": "wind", "title": "Coup de vent", "fact": "Vent 36 kn ≥ 34 kn.",
    }]
    kinds = {c["kind"]: c for c in diff_moments(base, alert_on)}
    assert kinds["alert-on"]["score"] == SCORE_ALERT_ON

    kinds = {c["kind"]: c for c in diff_moments(alert_on, base)}
    assert kinds["alert-off"]["score"] == SCORE_ALERT_OFF

    zee = copy.deepcopy(base)
    zee["here"] = copy.deepcopy(base["here"])
    zee["here"]["zee"] = {"name": "Spanish EEZ", "mrgid": 5693, "entry": {"known": False, "ports": []}}
    kinds = {c["kind"]: c for c in diff_moments(base, zee)}
    assert kinds["zee-enter"]["score"] == SCORE_ZEE
    assert not kinds["zee-enter"]["title"].lower().startswith("entrée dans")

    station = copy.deepcopy(base)
    station["around"] = list(base.get("around") or []) + [{
        "kind": "science", "title": "Station croisée", "fact": "Station PIRATA (8 nm)",
    }]
    kinds = {c["kind"]: c for c in diff_moments(base, station)}
    assert kinds["station"]["score"] == SCORE_STATION
    assert kinds["station"]["title"] == "PIRATA"

    regime = copy.deepcopy(base)
    regime["leg"] = {**base["leg"], "regime": "forecast"}
    kinds = {c["kind"]: c for c in diff_moments(base, regime)}
    assert kinds["regime"]["score"] == SCORE_REGIME

    amp = copy.deepcopy(base)
    amp["here"] = copy.deepcopy(base["here"])
    amp["here"]["mpa"] = list(base["here"].get("mpa") or []) + [{
        "name": "Grand Cul-de-Sac Marin", "nm": 4.0, "site_id": "fr-amp-gcsm",
    }]
    kinds = {c["kind"]: c for c in diff_moments(base, amp)}
    assert kinds["amp"]["score"] == SCORE_AMP

    assert diff_moments(None, base) == []
    assert diff_moments({}, base) == []


def test_fixture_pearls_collapse_to_fewer_moments():
    voy = _fixture_voyage()
    n = len(voy["pearls"])
    assert n == 12
    first = warm_moments(voy["voyageId"])
    rows = read_moments(voy["voyageId"])
    m = first["count"]
    assert m == len(rows)
    assert 1 <= m < n
    seqs = [row["seq"] for row in rows]
    assert seqs == list(range(m))
    # Première ligne : pas de différence avec un moment précédent — seulement, le cas échéant, les marinas et
    # ports croisés dès la première perle (27 sept. : chaque marina/port à moins de 15 nm, cité une fois).
    assert all(c["kind"] in {"marina", "port", "coast"} for c in rows[0]["changes"])
    for row in rows[1:]:
        assert row["changes"], f"seq {row['seq']} sans changes"
        for change in row["changes"]:
            assert change["kind"] and change["title"] and change["fact"]
            assert change["score"] in (1, 2, 3)
    replay = warm_moments(voy["voyageId"])
    again = read_moments(voy["voyageId"])
    assert replay["count"] == m == len(again)
    assert [row["signature"] for row in again] == [row["signature"] for row in rows]


def _moment_row(seq: int, t: str, sig: str, fact: str = "f") -> dict:
    return {
        "seq": seq,
        "t": t,
        "signature": sig,
        "changes": [{"kind": "note", "title": "t", "fact": fact}],
        "moment": {"note": fact},
        "pos": {},
    }


def test_append_only_ignores_rebuild_inside_covered_period():
    from moment_journal import merge_append_only_moment_rows

    existing = [
        _moment_row(i, f"2026-05-{15 + (i % 28):02d}T14:32:51Z", f"sig-{i}", f"body-{i}")
        for i in range(1142)
    ]
    existing[-1] = _moment_row(1141, "2027-11-15T08:00:00Z", "sig-last", "end")
    rebuilt = [
        _moment_row(i, f"2026-06-{1 + (i % 28):02d}T10:00:00Z", f"rebuild-{i}", f"r{i}")
        for i in range(844)
    ]
    merged, added = merge_append_only_moment_rows(existing, rebuilt)
    assert added == []
    assert len(merged) == 1142
    assert merged == existing


def test_append_only_adds_row_strictly_after_last_t():
    from moment_journal import merge_append_only_moment_rows

    existing = [_moment_row(i, f"2026-05-{10 + i}T08:00:00Z", f"k{i}") for i in range(5)]
    existing[-1] = _moment_row(4, "2027-11-15T08:00:00Z", "last", "end")
    same_instant = _moment_row(0, "2027-11-15T08:00:00Z", "other-sig", "nope")
    future = _moment_row(0, "2027-11-16T09:00:00Z", "future", "new")
    merged, added = merge_append_only_moment_rows(existing, [same_instant, future])
    assert len(merged) == 6
    assert len(added) == 1
    assert added[0]["t"] == "2027-11-16T09:00:00Z"
    assert merged[-1]["t"] == "2027-11-16T09:00:00Z"
    assert merged[-1]["seq"] == 5
    assert [row["seq"] for row in merged[:-1]] == [0, 1, 2, 3, 4]
    again, added_again = merge_append_only_moment_rows(merged, [same_instant, future])
    assert added_again == []
    assert again == merged


def test_enrich_same_key_keeps_moment_t_and_signature():
    from moment_journal import merge_append_only_moment_rows

    existing = [_moment_row(0, "2026-05-15T08:00:00Z", "same", "keep")]
    existing[0]["pos"] = {"lat": None, "lon": None}
    patch = _moment_row(9, "2026-05-15T08:00:00Z", "same", "replaced")
    patch["pos"] = {"lat": 46.1, "lon": -1.1}
    patch["legIdx"] = 2
    patch["changes"] = existing[0]["changes"] + [
        {"kind": "coast", "id": "c-new", "title": "Côte", "fact": "vue"},
    ]
    patch["moment"] = {"note": "replaced", "extra": "no"}
    merged, added = merge_append_only_moment_rows(existing, [patch])
    assert added == []
    assert len(merged) == 1
    row = merged[0]
    assert row["t"] == "2026-05-15T08:00:00Z"
    assert row["signature"] == "same"
    assert row["seq"] == 0
    assert row["moment"] == {"note": "keep"}
    assert row["pos"]["lat"] == 46.1
    assert row["legIdx"] == 2
    assert any(c.get("id") == "c-new" for c in row["changes"])
    twice, added_twice = merge_append_only_moment_rows(merged, [patch])
    assert added_twice == []
    assert twice == merged


def test_warm_append_only_ignores_partial_rebuild_in_past(monkeypatch):
    import pearl_store
    from moment_journal import moment_row_key, warm_moments

    voy = _fixture_voyage()
    existing = [
        _moment_row(i, f"2026-05-{15 + (i % 28):02d}T14:32:51Z", f"sig-{i}", f"body-{i}")
        for i in range(1142)
    ]
    existing[-1] = _moment_row(1141, "2027-11-15T08:00:00Z", "sig-last", "end")
    pearl_store.replace_moments(voy["voyageId"], existing)
    before = read_moments(voy["voyageId"])
    rebuild = [_moment_row(0, "2026-05-17T23:20:55Z", "sig-new", "partial")]
    monkeypatch.setattr("moment_journal._build_rows", lambda _vid, _voy: rebuild)

    out = warm_moments(voy["voyageId"], voy)
    after = read_moments(voy["voyageId"])
    assert out["count"] == 1142
    assert len(after) == 1142
    assert not added_rows(before, after)
    for left, right in zip(before, after):
        assert moment_row_key(left) == moment_row_key(right)
        assert left["moment"] == right["moment"]
        assert left["t"] == right["t"]
        assert left["signature"] == right["signature"]

    again = warm_moments(voy["voyageId"], voy)
    assert again["count"] == 1142
    assert read_moments(voy["voyageId"]) == after


def added_rows(before: list[dict], after: list[dict]) -> list[dict]:
    from moment_journal import moment_row_key

    known = {moment_row_key(row) for row in before}
    return [row for row in after if moment_row_key(row) not in known]


def test_warm_appends_only_a_row_after_last_t(monkeypatch):
    import pearl_store
    from moment_journal import warm_moments

    voy = _fixture_voyage()
    existing = [_moment_row(i, f"2026-05-{10 + i}T08:00:00Z", f"k{i}") for i in range(4)]
    existing[-1] = _moment_row(3, "2027-11-15T08:00:00Z", "last", "end")
    pearl_store.replace_moments(voy["voyageId"], existing)
    future = _moment_row(0, "2027-11-16T09:00:00Z", "future", "new")
    monkeypatch.setattr("moment_journal._build_rows", lambda _vid, _voy: [future])
    out = warm_moments(voy["voyageId"], voy)
    rows = read_moments(voy["voyageId"])
    assert out["count"] == 5
    assert rows[-1]["t"] == "2027-11-16T09:00:00Z"
    assert rows[-1]["signature"] == "future"
    assert [row["t"] for row in rows[:-1]] == [row["t"] for row in existing]
    again = warm_moments(voy["voyageId"], voy)
    assert again["count"] == 5
    assert read_moments(voy["voyageId"]) == rows


def test_warm_merge_empty_rebuild_preserves_journal(monkeypatch):
    import pearl_store
    from moment_journal import warm_moments

    voy = _fixture_voyage()
    rows = [_moment_row(i, f"2026-05-{10 + i}T08:00:00Z", f"s{i}") for i in range(12)]
    pearl_store.replace_moments(voy["voyageId"], rows)
    before = read_moments(voy["voyageId"])
    monkeypatch.setattr("moment_journal._build_rows", lambda _vid, _voy: [])
    out = warm_moments(voy["voyageId"], voy)
    assert out["status"] == "preserved"
    assert out["count"] == 12
    assert pearl_store.count_moments(voy["voyageId"]) == 12
    assert read_moments(voy["voyageId"]) == before


def test_warm_moments_never_drops_existing_sqlite_rows(monkeypatch):
    """Régression : un recalcul plus court ne doit pas effacer le journal (oct. 2026 prod)."""
    import pearl_store
    from moment_journal import warm_moments

    voy = _fixture_voyage()
    rows = [
        {
            "seq": i,
            "t": f"2026-05-{10 + i}T08:00:00Z",
            "signature": f"s{i}",
            "changes": [{"kind": "note", "title": "t", "fact": "f"}],
            "moment": {},
            "pos": {},
        }
        for i in range(8)
    ]
    pearl_store.replace_moments(voy["voyageId"], rows)
    thin = [rows[0]]

    monkeypatch.setattr("moment_journal._build_rows", lambda _vid, _voy: thin)
    out = warm_moments(voy["voyageId"], voy)
    assert out["count"] == 8
    assert pearl_store.count_moments(voy["voyageId"]) == 8


def test_replace_moments_refuses_silent_shrink(tmp_path, monkeypatch):
    import pearl_store

    monkeypatch.setenv("NAVIGUIDE_VOYAGE_DIR", str(tmp_path / "voyage"))
    pearl_store.reset()
    voy = _fixture_voyage()
    full = [
        {"seq": i, "t": f"2026-05-{10 + i}T08:00:00Z", "signature": f"s{i}",
         "changes": [], "moment": {}, "pos": {}}
        for i in range(4)
    ]
    pearl_store.replace_moments(voy["voyageId"], full)
    monkeypatch.delenv("NAVIGUIDE_TEST_ALLOW_MOMENT_DECREASE", raising=False)
    n = pearl_store.replace_moments(voy["voyageId"], full[:1])
    assert n == 4
    assert pearl_store.count_moments(voy["voyageId"]) == 4
    monkeypatch.setenv("NAVIGUIDE_TEST_ALLOW_MOMENT_DECREASE", "1")
    pearl_store.replace_moments(voy["voyageId"], full[:1])
    assert pearl_store.count_moments(voy["voyageId"]) == 1


def test_changed_signature_updates_the_line():
    from moment_journal import moment_row_key

    voy = _fixture_voyage()
    warm_moments(voy["voyageId"])
    before_rows = read_moments(voy["voyageId"])
    before = {row["seq"]: row["signature"] for row in before_rows}
    voy["pearls"][0]["zee"] = {
        "name": "Spanish Exclusive Economic Zone",
        "mrgid": 5693,
        "gold": False,
    }
    voy["pearls"][0]["poe"] = []
    save_voyage(voy)
    warm_moments(voy["voyageId"])
    after = read_moments(voy["voyageId"])
    assert before[0] in {row["signature"] for row in after}
    # Un recalcul dans la période déjà couverte ne change pas les lignes existantes.
    after_by_key = {moment_row_key(row): row for row in after}
    for row in before_rows:
        kept = after_by_key.get(moment_row_key(row))
        assert kept is not None
        assert kept["moment"] == row["moment"]
    assert len(after) == len(before_rows)
    assert [row["seq"] for row in after] == list(range(len(after)))
    assert [row["t"] for row in after] == sorted(row["t"] for row in after)


def test_warm_emits_approche_per_stop():
    voy = _fixture_voyage()
    warm_moments(voy["voyageId"])
    rows = read_moments(voy["voyageId"])
    approaches = [c for row in rows for c in row["changes"] if c.get("kind") == "approche"]
    titles = {c["title"] for c in approaches}
    assert approaches, "le journal doit fournir une approche d'escale"
    assert any(c.get("score") == SCORE_APPROCHE for c in approaches)
    assert any("Fort-de-France" in t for t in titles)
    assert any("Pointe-à-Pitre" in t for t in titles)
    for change in approaches:
        assert not change["title"].lower().startswith("approche")
        assert change["title"]
        assert "milles nautiques" in change["fact"]


def test_read_moments_until_cuts():
    voy = _fixture_voyage()
    warm_moments(voy["voyageId"])
    all_rows = read_moments(voy["voyageId"])
    assert len(all_rows) >= 2
    cut = all_rows[len(all_rows) // 2]["t"]
    sliced = read_moments(voy["voyageId"], until=cut)
    assert 1 <= len(sliced) < len(all_rows)
    assert all(row["t"] <= cut or row["t"][:10] <= cut[:10] for row in sliced)
    assert sliced[-1]["seq"] < all_rows[-1]["seq"]
    day = all_rows[0]["t"][:10]
    by_day = read_moments(voy["voyageId"], until=day)
    assert by_day
    assert all(row["t"].startswith(day) or row["t"][:10] <= day for row in by_day)


def test_status_and_get_expose_moments():
    voy = _fixture_voyage(OFFICIAL_VOYAGE_ID)
    n = warm_moments(OFFICIAL_VOYAGE_ID)["count"]
    assert n >= 1
    import ici_warm
    st = ici_warm.status()
    assert st["moments"] == n
    assert st["store"]["moments"] == n

    import official_store
    from moment_journal import read_moments
    official_store.put("moments", {"moments": read_moments(OFFICIAL_VOYAGE_ID), "journal": {"count": n, "latest": [], "events": [], "days": []}})

    from main import app
    client = TestClient(app)
    res = client.get("/voyage/official/moments")
    assert res.status_code == 200
    body = res.json()
    assert body["voyageId"] == OFFICIAL_VOYAGE_ID
    assert body["count"] == n
    assert len(body["moments"]) == n
    until = body["moments"][0]["t"]
    cut = client.get("/voyage/official/moments", params={"until": until})
    assert cut.status_code == 200
    assert 1 <= cut.json()["count"] <= n
    status = client.get("/ici/warm/status")
    assert status.status_code == 200
    assert status.json()["moments"] == n


def test_startup_does_not_block_on_moments(monkeypatch):
    calls = []
    monkeypatch.setenv("NAVIGUIDE_ICI_WARM", "0")
    import ici_warm
    monkeypatch.setattr("moment_journal.warm_moments", lambda *_a, **_k: calls.append(1) or {"count": 0})
    assert ici_warm.start_background() is False
    assert calls == []
    assert ici_warm.status()["status"] == "disabled"


def test_kick_official_moments_returns_without_waiting(monkeypatch):
    import voyage_api
    _fixture_voyage(OFFICIAL_VOYAGE_ID)
    started = []

    def fake_kick(*_a, **_k):
        started.append(True)
        return True

    monkeypatch.setattr(voyage_api.get_pipeline(), "kick", fake_kick)
    assert voyage_api._kick_official_moments() is True
    assert started == [True]


def test_diff_moments_silence_without_name():
    assert named_title("Station croisée", "Station croisée", "station") == ""
    assert named_title("Station croisée", "Station PIRATA (8 nm)", "station") == "PIRATA"
    voy = load_official_mini()
    base = _moment(voy, 0)
    empty = copy.deepcopy(base)
    empty["here"] = copy.deepcopy(base["here"])
    empty["here"]["entry"] = {"known": False, "ports": []}
    if isinstance(empty["here"].get("zee"), dict):
        empty["here"]["zee"] = {**empty["here"]["zee"], "entry": {"known": False, "ports": []}}
    no_port = copy.deepcopy(empty)
    no_port["here"]["entry"] = {"known": False, "ports": []}
    silent = diff_moments(empty, no_port)
    assert not any("Aucun port" in (c.get("fact") or "") for c in silent)
    assert not any("Ports d'entrée" in (c.get("title") or "") for c in silent)
    with_port = copy.deepcopy(empty)
    with_port["here"]["entry"] = {"known": True, "ports": ["Les Sables-d'Olonne"]}
    kinds = {c["kind"]: c for c in diff_moments(empty, with_port)}
    assert kinds["port"]["title"] == "Les Sables-d'Olonne"
    nameless = copy.deepcopy(base)
    nameless["around"] = list(base.get("around") or []) + [{
        "kind": "science", "title": "Station croisée", "fact": "Station croisée",
    }]
    assert not any(c.get("kind") == "station" for c in diff_moments(base, nameless))


def test_wpi_within_25nm_becomes_coast():
    seen: set[tuple[str, str]] = set()
    pearl = {
        "nearby": {
            "wpi": [
                {"name": "Camariñas", "nm": 20.0},
                {"name": "Trop loin", "nm": 30.0},
            ],
            "capitaineries": [],
            "marinas": [],
        },
    }
    out = _new_places_nearby(pearl, seen)
    kinds = {c["kind"] for c in out}
    titles = {c["title"] for c in out}
    assert "coast" in kinds
    assert "Camariñas" in titles
    assert "Trop loin" not in titles
    assert COAST_NEAR_NM == 25.0


def test_chaluts_never_becomes_amp_change():
    voy = load_official_mini()
    base = _moment(voy, 0)
    fishing = copy.deepcopy(base)
    fishing["here"] = copy.deepcopy(base["here"])
    fishing["here"]["mpa"] = list(base["here"].get("mpa") or []) + [{
        "name": "Pertuis Charentais - Chaluts", "nm": 2.0, "site_id": "fish-1",
    }]
    kinds = {c["kind"] for c in diff_moments(base, fishing)}
    assert "amp" not in kinds
    alert = copy.deepcopy(base)
    alert["alerts"] = list(base.get("alerts") or []) + [{
        "id": "mpa-chaluts", "kind": "mpa",
        "title": "Aire marine protégée",
        "fact": "Pertuis Charentais - Chaluts (2 nm): IUCN Unassigned.",
    }]
    kinds = {c["kind"] for c in diff_moments(base, alert)}
    assert "alert-on" not in kinds


def test_project_at_10nm_emits_at_60nm_silent():
    seen: set[tuple[str, str]] = set()
    near = _new_projects_nearby({
        "projects": [
            {"name": "Récif sentinelle", "nm": 10.0, "gold_on": True},
            {"name": "Trop loin", "nm": 60.0, "gold_on": True},
        ],
    }, seen)
    titles = {c["title"] for c in near}
    assert any(c["kind"] == "project" and c["score"] == SCORE_PROJECT for c in near)
    assert "Récif sentinelle" in titles
    assert "Trop loin" not in titles
    assert PROJECT_NEAR_NM == 30.0
    gold_first = _new_projects_nearby({
        "projects": [
            {"name": "Argent", "nm": 5.0, "gold_on": False},
            {"name": "Or", "nm": 12.0, "gold_on": True},
        ],
    }, set())
    assert [c["title"] for c in gold_first] == ["Or", "Argent"]


_RC44_MARKS = [
    {"name": "Cayenne (Guyane)", "lat": 4.93, "lon": -52.35, "iso": "2026-07-19T08:00:00Z"},
    {"name": "Halifax (Nouvelle-Écosse)", "lat": 44.65, "lon": -63.57, "iso": "2026-07-22T08:00:00Z"},
    {"name": "Saint-Pierre (Saint-Pierre-et-Miquelon)", "lat": 46.78, "lon": -56.16,
     "iso": "2026-07-25T08:00:00Z"},
]


def test_diff_moments_halifax_pearl_is_not_cayenne():
    """Perle 44,65/−63,57 → titre Halifax, pas Arrivée à Cayenne."""
    prev = {"leg": {"to": "Cayenne (Guyane)"}, "pos": {"lat": 4.93, "lon": -52.35}}
    cur = {
        "leg": {"to": "Saint-Pierre (Saint-Pierre-et-Miquelon)"},
        "pos": {"lat": 44.65, "lon": -63.57},
    }
    kinds = {c["kind"]: c for c in diff_moments(prev, cur, marks=_RC44_MARKS)}
    assert kinds["escale"]["score"] == SCORE_ESCALE
    assert "Halifax" in kinds["escale"]["title"]
    assert "Cayenne" not in kinds["escale"]["title"]


def test_rows_from_voyage_halifax_line_uses_mark_date():
    voy = {
        "legs": [
            {"from": "Fort-de-France", "to": "Cayenne (Guyane)", "fromNm": 0, "toNm": 1000},
            {"from": "Cayenne (Guyane)", "to": "Saint-Pierre (Saint-Pierre-et-Miquelon)",
             "fromNm": 1000, "toNm": 1400},
        ],
        "marks": _RC44_MARKS,
        "clock": {
            "t0": "2026-07-19T08:00:00Z",
            "marks": [
                {**_RC44_MARKS[0], "tHours": 0},
                {**_RC44_MARKS[1], "tHours": 72},
            ],
            "vertices": [
                {"sailNm": 999, "lat": 4.93, "lon": -52.35, "iso": "2026-07-19T08:00:00Z",
                 "tHours": 0, "vehicle": "quay"},
                {"sailNm": 1000, "lat": 44.65, "lon": -63.57, "iso": "2026-07-22T17:25:00Z",
                 "tHours": 81.4, "vehicle": "side"},
            ],
        },
        "pearls": [
            {"lat": 4.93, "lon": -52.35, "sailNm": 500, "here": {}, "alerts": [], "around": []},
            {"lat": 44.65, "lon": -63.57, "sailNm": 1000, "here": {}, "alerts": [], "around": []},
        ],
        "skipper_thresholds": {"galeKt": 34.0, "hsAlertM": 3.0},
    }
    rows = rows_from_voyage("rc44", voy)
    escale_at_hfx = [
        row for row in rows
        if abs(float((row.get("pos") or {}).get("lat") or 0) - 44.65) < 1
        and any(c.get("kind") == "escale" for c in (row.get("changes") or []))
    ]
    assert escale_at_hfx, [r.get("changes") for r in rows]
    titles = " ".join(
        c.get("title") or ""
        for row in escale_at_hfx
        for c in (row.get("changes") or [])
        if c.get("kind") == "escale"
    )
    assert "Halifax" in titles
    assert "Cayenne" not in titles
    assert escale_at_hfx[0]["t"].startswith("2026-07-22")


def test_rows_from_voyage_localizes_english_station_name_and_distance_without_changing_french():
    voy = load_official_mini()
    fr_rows = rows_from_voyage(voy["voyageId"], voy, lang="fr")
    en_rows = rows_from_voyage(voy["voyageId"], voy, lang="en")

    fr_station = next(
        c for row in fr_rows for c in row["changes"]
        if c.get("kind") == "station" and "CORIOLIS" in c.get("fact", "")
    )
    en_station = next(
        c for row in en_rows for c in row["changes"]
        if c.get("kind") == "station" and "CORIOLIS" in c.get("fact", "")
    )

    assert fr_station["title"] == "CORIOLIS-Guadeloupe"
    assert "7,5 nm" in fr_station["fact"]
    assert en_station["title"] == "CORIOLIS-Guadeloupe"
    assert "7.5 nm" in en_station["fact"]
    assert any(
        item.get("title") == "Station croisée"
        for row in fr_rows for item in (row.get("moment", {}).get("around") or [])
    )
    assert any(
        item.get("title") == "Station passed"
        for row in en_rows for item in (row.get("moment", {}).get("around") or [])
    )
