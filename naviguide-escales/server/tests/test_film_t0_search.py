"""Dichotomie : une date dont la lecture du film dure entre 2:30 et 3:00.

Route courte fictive, dans le test seulement. Rien n'est écrit dans un stock.
"""
import importlib.util
import math
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "film_t0_search.py"


def _load():
    spec = importlib.util.spec_from_file_location("film_t0_search", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def search():
    return _load()


def _route():
    """Quatre chapitres. Le texte restant entre dans la fenêtre au 10 janvier."""
    chapters = [
        {"text": "a" * 6000, "tA": "2026-01-01T00:00:00Z", "tB": "2026-01-05T00:00:00Z",
         "fromName": "Alpha", "toName": "Bravo"},
        {"text": "b" * 600, "tA": "2026-01-05T00:00:00Z", "tB": "2026-01-10T00:00:00Z",
         "fromName": "Bravo", "toName": "Charlie"},
        {"text": "c" * 2100, "tA": "2026-01-10T00:00:00Z", "tB": "2026-01-20T00:00:00Z",
         "fromName": "Charlie", "toName": "Delta"},
        {"text": "d" * 300, "tA": "2026-01-20T00:00:00Z", "tB": "2026-01-30T00:00:00Z",
         "fromName": "Delta", "toName": "Echo"},
    ]
    stops = [
        {"name": "Alpha", "iso": "2026-01-01T00:00:00Z"},
        {"name": "Bravo", "iso": "2026-01-05T00:00:00Z"},
        {"name": "Charlie", "iso": "2026-01-10T00:00:00Z"},
        {"name": "Delta", "iso": "2026-01-20T00:00:00Z"},
        {"name": "Echo", "iso": "2026-01-30T00:00:00Z"},
    ]
    return chapters, stops


def test_dichotomy_finds_a_date_inside_two_and_a_half_to_three_minutes(search):
    chapters, stops = _route()
    found = search.search_reading_t0(chapters, stops)
    assert found is not None
    assert found["t0"] == "2026-01-10T00:00:00Z"
    assert found["seconds"] == pytest.approx(160.0)
    assert found["clock"] == "2:40"
    assert found["chars"] == 2400
    assert 150.0 <= found["seconds"] <= 180.0
    assert [s["name"] for s in found["passed"]] == ["Alpha", "Bravo", "Charlie"]
    assert [s["name"] for s in found["upcoming"]] == ["Delta", "Echo"]
    assert found["until"] == "2026-01-19T23:59:59.999Z"
    # Le 10 janvier est une frontière de chapitre, pas une coupe dans le texte.
    kept = [ch for ch in chapters if search.parse_ms(ch["tB"]) > found["t0Ms"]]
    assert [k["chars"] for k in found["kept"]] == [len(ch["text"]) for ch in kept]
    assert found["chars"] == sum(len(ch["text"]) for ch in kept)
    span = search.parse_ms("2026-01-30T00:00:00Z") - search.parse_ms("2026-01-01T00:00:00Z")
    assert found["probes"] <= 4 * (math.log2(span) + 2)
    assert found["probes"] < 100


def test_bounds_150_and_180_are_accepted(search):
    base = {"fromName": "Alpha", "toName": "Bravo"}
    stops = [
        {"name": "Alpha", "iso": "2026-03-01T00:00:00Z"},
        {"name": "Bravo", "iso": "2026-03-10T00:00:00Z"},
    ]
    for chars, expect in ((2250, 150.0), (2700, 180.0)):
        chapters = [
            {"text": "x" * 3000, "tA": "2026-03-01T00:00:00Z", "tB": "2026-03-05T00:00:00Z", **base},
            {"text": "y" * chars, "tA": "2026-03-05T00:00:00Z", "tB": "2026-03-10T00:00:00Z", **base},
        ]
        found = search.search_reading_t0(chapters, stops)
        assert found is not None
        assert found["t0"] == "2026-03-05T00:00:00Z"
        assert found["seconds"] == pytest.approx(expect)
        assert found["chars"] == chars


def test_a_jump_over_the_window_finds_nothing(search):
    chapters = [
        {"text": "x" * 6000, "tA": "2026-02-01T00:00:00Z", "tB": "2026-02-05T00:00:00Z"},
        {"text": "y" * 100, "tA": "2026-02-05T00:00:00Z", "tB": "2026-02-10T00:00:00Z"},
    ]
    stops = [
        {"name": "Alpha", "iso": "2026-02-01T00:00:00Z"},
        {"name": "Bravo", "iso": "2026-02-10T00:00:00Z"},
    ]
    assert search.search_reading_t0(chapters, stops) is None


def test_a_text_already_inside_the_window_keeps_its_start(search):
    chapters = [
        {"text": "z" * 2400, "tA": "2026-04-01T00:00:00Z", "tB": "2026-04-08T00:00:00Z",
         "fromName": "Alpha", "toName": "Bravo"},
    ]
    stops = [
        {"name": "Alpha", "iso": "2026-04-01T00:00:00Z"},
        {"name": "Bravo", "iso": "2026-04-08T00:00:00Z"},
    ]
    found = search.search_reading_t0(chapters, stops)
    assert found["t0"] == "2026-04-01T00:00:00Z"
    assert found["seconds"] == pytest.approx(160.0)
    assert [s["name"] for s in found["passed"]] == ["Alpha"]
    assert [s["name"] for s in found["upcoming"]] == ["Bravo"]
    assert found["kept"][0]["chars"] == 2400


def test_return_call_is_kept_and_a_scrambled_clock_date_is_not(search):
    base = [
        {"name": "La Rochelle", "iso": "2026-05-15T08:00:00Z"},
        {"name": "Halifax (Nouvelle-Écosse)", "iso": "2026-08-12T03:59:04Z"},
        {"name": "Mata-Utu (Wallis-et-Futuna)", "iso": "2026-10-15T08:00:24Z"},
    ]
    clock = [
        {"name": "La Rochelle", "iso": "2027-05-31T08:28:10Z", "filmNm": 39585.8},
        {"name": "Halifax (Nouvelle-Écosse)", "iso": "2026-08-25T16:00:15Z", "filmNm": 9774.2},
        {"name": "Mata-Utu (Wallis-et-Futuna)", "iso": "2027-05-02T14:29:32Z", "filmNm": 38364.2},
    ]
    route = [
        {"name": "La Rochelle", "filmNm": 122.3},
        {"name": "La Rochelle", "filmNm": 39585.8},
        {"name": "Mata-Utu (Wallis-et-Futuna)", "filmNm": 18007.1},
    ]

    def same(a, b):
        def fold(value):
            return value.split("(")[0].strip().casefold()
        return fold(a) == fold(b)

    rows = search.merge_clock_visits(base, clock, route, same)
    isos = {(row["name"].split("(")[0].strip(), row["iso"]) for row in rows}
    assert ("La Rochelle", "2027-05-31T08:28:10Z") in isos
    assert ("Halifax", "2026-08-25T16:00:15Z") in isos
    assert ("Mata-Utu", "2026-10-15T08:00:24Z") in isos
    assert ("Mata-Utu", "2027-05-02T14:29:32Z") not in isos


def test_official_departure_constant_is_untouched():
    root = Path(__file__).resolve().parents[2]
    clock = (root / "server" / "voyage_clock.py").read_text(encoding="utf-8")
    assert 'OFFICIAL_T0 = "2026-05-15T08:00:00Z"' in clock.splitlines()
    script = _SCRIPT.read_text(encoding="utf-8")
    assert not any(line.startswith("OFFICIAL_T0") for line in script.splitlines())
    assert "save_voyage" not in script
    assert "want_write" not in script
    assert "put_film_cached" not in script
    film = (root / "server" / "film_script.py").read_text(encoding="utf-8")
    assert any(line.startswith("FILM_ESTIMATE_CPS = 15") for line in film.splitlines())
