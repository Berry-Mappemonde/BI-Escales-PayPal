"""Changements de climatologie lus sur l'horloge."""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from climo_events import (
    LONG_LIMIT,
    SHORT_CROSSING_MS,
    climo_sentence,
    dose_climo_changes,
    notable_climo_changes,
    spoken_knots,
)


def _iso(when: datetime) -> str:
    return when.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _clock(rows: list[dict]) -> dict:
    return {"t0": rows[0]["iso"], "vertices": rows}


def _vtx(when: datetime, lat: float, lon: float, kn: float, direc: float, source: str = "atlas", **extra):
    return {
        "iso": _iso(when),
        "lat": lat,
        "lon": lon,
        "windKnots": kn,
        "dirFromDeg": direc,
        "source": source,
        "kind": "hindcast" if source == "hindcast" else "climatology",
        "regime": "hindcast" if source == "hindcast" else "climatology",
        "vehicle": "main",
        "sailNm": extra.pop("sailNm", 4000.0),
        "month": when.month,
        **extra,
    }


def _series(start: datetime, hours: int, step_h: int, **kwargs) -> list[dict]:
    out = []
    t = start
    end = start + timedelta(hours=hours)
    sail = float(kwargs.pop("sail0", 3000.0))
    while t < end:
        out.append(_vtx(t, sailNm=sail, **kwargs))
        t += timedelta(hours=step_h)
        sail += 40.0
    return out


def test_regime_jump_one_event():
    t0 = datetime(2026, 6, 10, tzinfo=timezone.utc)
    west = _series(t0, 48, 6, lat=38.0, lon=-10.0, kn=14.0, direc=260.0, source="atlas")
    trades = _series(
        t0 + timedelta(hours=48), 72, 6,
        lat=13.0, lon=-24.0, kn=15.0, direc=50.0, source="atlas",
    )
    events = notable_climo_changes(_clock(west + trades))
    named = [e for e in events if e.get("regimeId") == "ne_trades"]
    assert len(named) == 1
    ev = named[0]
    assert ev["source"] == "atlas"
    assert ev["nature"] == "season"
    assert ev["windKnots"] == 15.0
    assert ev["t"].startswith("2026-06-12")


def test_noise_no_event():
    t0 = datetime(2026, 6, 1, tzinfo=timezone.utc)
    rows = []
    sail = 2000.0
    for i in range(20):
        direc = 50.0 if i % 2 == 0 else 140.0
        rows.append(_vtx(
            t0 + timedelta(hours=6 * i), 16.0, -24.0, 15.0, direc,
            source="atlas", sailNm=sail,
        ))
        sail += 30.0
    assert notable_climo_changes(_clock(rows)) == []


def test_zone_fallback_never_speaks_a_figure():
    t0 = datetime(2026, 6, 10, tzinfo=timezone.utc)
    west = _series(t0, 48, 6, lat=38.0, lon=-10.0, kn=14.0, direc=260.0, source="zone_fallback")
    trades = _series(
        t0 + timedelta(hours=48), 72, 6,
        lat=13.0, lon=-24.0, kn=15.0, direc=50.0, source="zone_fallback",
    )
    events = notable_climo_changes(_clock(west + trades))
    assert events
    for ev in events:
        assert ev["source"] == "zone_fallback"
        assert ev["windKnots"] is None
        assert ev["dirFromDeg"] is None
        fr = climo_sentence(ev, "fr")
        en = climo_sentence(ev, "en")
        assert fr
        assert "vents moyens de saison" in fr
        assert "seasonal average winds" in en
        assert ev["windKnots"] is None
        assert not re.search(r"\b(15|14|50|260|quinze|quatorze)\b", fr)
        assert not re.search(r"n[œo]uds", fr)
        assert not re.search(r"\b(fifteen|fourteen|knots)\b", en)


def test_sentence_fr_en_atlas():
    ev = {
        "kind": "climo",
        "event": "ne_trades",
        "regimeId": "ne_trades",
        "t": "2026-06-14T12:00:00Z",
        "source": "atlas",
        "nature": "season",
        "windKnots": 15.0,
        "placeFr": "au sud du Cap-Vert",
        "placeEn": "south of Cape Verde",
        "title": "alizés de nord-est",
    }
    fr = climo_sentence(ev, "fr")
    en = climo_sentence(ev, "en")
    assert fr.startswith("Le 14 juin")
    assert "au sud du Cap-Vert" in fr
    assert "alizés de nord-est" in fr
    assert "quinze nœuds, la moyenne de saison" in fr
    assert en.startswith("On 14 June")
    assert "south of Cape Verde" in en
    assert "northeasterly trade winds" in en
    assert "fifteen knots, the seasonal average" in en
    assert spoken_knots(15, "fr") == "quinze"


def test_sentence_hindcast_says_measured():
    ev = {
        "kind": "climo",
        "event": "force",
        "t": "2026-06-14T12:00:00Z",
        "source": "hindcast",
        "nature": "measured",
        "windKnots": 22.0,
        "prevKnots": 12.0,
    }
    fr = climo_sentence(ev, "fr")
    en = climo_sentence(ev, "en")
    assert "vingt-deux nœuds mesurés" in fr
    assert "de saison" not in fr
    assert "twenty-two measured knots" in en
    assert "seasonal" not in en


def test_rc30_place_is_boat_position_galice_not_gibraltar():
    """Le lieu d'une phrase climato est la position du bateau à cet
    instant — au large de la Galice, le bateau n'est pas « au nord de
    Gibraltar » (445 nm) ; un jalon trop loin ne se dit pas."""
    from climo_events import _place_phrase

    galice = _place_phrase(43.2, -9.3, "fr")
    assert "Gibraltar" not in galice
    assert galice == ""
    assert _place_phrase(43.2, -9.3, "en") == ""
    # à portée, le jalon se dit toujours
    assert _place_phrase(36.5, -5.5, "fr") == "au large de Gibraltar"
    assert _place_phrase(13.0, -24.0, "fr") == "au sud du Cap-Vert"


def test_rc30_no_mistral_outside_mediterranean():
    """Le mistral / la tramontane : Méditerranée vraie seulement — un vent de
    nord au large de la Galice n'est pas le mistral (transcription du 14 oct.)."""
    from climo_events import named_belt

    assert named_belt(43.2, -9.3, 0.0, 16.0, "atlas") is None
    assert named_belt(42.0, 5.0, 350.0, 16.0, "atlas") == "mistral"
    assert named_belt(42.5, 3.5, 320.0, 15.0, "atlas") == "tramontane"
    # l'atlas qui NOMME le régime garde la main, où que soit le bateau
    assert named_belt(43.2, -9.3, 0.0, 16.0, "atlas", {"atlasName": "mistral"}) == "mistral"


def test_rc30_event_place_empty_when_landmark_far():
    """_make_event au large de la Galice : placeFr / placeEn vides — la phrase
    se dit sans lieu plutôt qu'avec un lieu faux."""
    t0 = datetime(2026, 5, 17, tzinfo=timezone.utc)
    calm = _series(t0, 48, 6, lat=43.4, lon=-9.2, kn=6.0, direc=20.0, source="atlas")
    windy = _series(
        t0 + timedelta(hours=48), 72, 6,
        lat=43.0, lon=-9.4, kn=16.0, direc=20.0, source="atlas",
    )
    events = notable_climo_changes(_clock(calm + windy))
    assert events
    for ev in events:
        assert ev["placeFr"] == ""
        assert ev["placeEn"] == ""
        assert "Gibraltar" not in climo_sentence(ev, "fr")


def test_dosage_one_short_two_long():
    many = [
        {
            "kind": "climo", "id": f"c{i}", "event": "ne_trades" if i < 3 else "force",
            "regimeId": "ne_trades" if i < 3 else None,
            "tMs": i * 86_400_000, "title": f"v{i}",
        }
        for i in range(5)
    ]
    assert len(dose_climo_changes(many, SHORT_CROSSING_MS - 1)) == 1
    long_span = 20 * 86_400_000
    picked = dose_climo_changes(many, long_span)
    assert len(picked) == LONG_LIMIT
    assert all(c.get("regimeId") == "ne_trades" for c in picked)
