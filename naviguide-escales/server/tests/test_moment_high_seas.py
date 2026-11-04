"""« High seas » is only said from a confirmed « no EEZ » answer, far from any port."""
from __future__ import annotations

import asyncio

import httpx

from ici_engine import lookup_zee, reset_caches, zee_from_record
from moment import TERRITORIAL_SEA_NM, _here, _sentences, zee_is_high_seas

HIGH_FR = "haute mer"
HIGH_EN = "high seas"


def _pearl(zee, *, src="vliz-local", poe=None, marinas=None, wpi=None):
    return {
        "zee": zee,
        "poe": poe or [],
        "amp": [],
        "nearby": {"marinas": marinas or [], "capitaineries": [], "wpi": wpi or []},
        "sources": {"zee": src},
    }


def _said_high_seas(pearl, lang="fr") -> bool:
    here = _here(pearl, {}, lang)
    text = " ".join(here["sentences"]).lower()
    return (HIGH_EN if lang == "en" else HIGH_FR) in text


def test_absent_zee_is_never_high_seas():
    for lang in ("fr", "en"):
        pearl = _pearl(None, src=None)
        assert not zee_is_high_seas(None, pearl)
        assert not _said_high_seas(pearl, lang)
        assert _here(pearl, {}, lang)["zee"]["name"] == ("Unknown EEZ" if lang == "en" else "ZEE inconnue")


def test_unavailable_zee_is_never_high_seas():
    for zee in ({"name": None, "mrgid": None, "unknown": True}, zee_from_record(None)):
        pearl = _pearl(zee, src="unavailable")
        assert not zee_is_high_seas(zee, pearl)
        assert not _said_high_seas(pearl, "fr")
        assert not _said_high_seas(pearl, "en")


def test_near_known_port_is_never_high_seas():
    # Ajaccio, boat in the harbour: even a « no EEZ » answer is wrong here.
    pearl = _pearl(zee_from_record(None), marinas=[{"name": "Port Tino Rossi", "nm": 0.3}])
    assert not _said_high_seas(pearl, "fr")
    pearl = _pearl(zee_from_record(None), poe=[{"name": "Ajaccio", "nm": 1.0}])
    assert not _said_high_seas(pearl, "en")


def test_territorial_waters_are_never_high_seas():
    assert TERRITORIAL_SEA_NM == 12.0
    inside = _pearl(zee_from_record(None), wpi=[{"name": "Ajaccio", "nm": 11.5}])
    assert not _said_high_seas(inside, "fr")
    # Offshore, with a confirmed « no EEZ » answer, the sentence stays.
    offshore = _pearl(zee_from_record(None), wpi=[{"name": "Ajaccio", "nm": 60}])
    assert _said_high_seas(offshore, "fr")
    assert _said_high_seas(offshore, "en")


def test_ashore_is_never_high_seas():
    pearl = _pearl({"name": "À terre (France)", "mrgid": None, "ashore": True})
    sentences = _sentences("À terre (France)", pearl["zee"], [], [], {}, "fr", pearl)
    assert not any(HIGH_FR in s.lower() for s in sentences)


def test_gazetteer_down_gives_unknown_zee(monkeypatch):
    reset_caches()
    import zee_local

    monkeypatch.setattr(zee_local, "zee_at", lambda lat, lon: zee_local.UNKNOWN)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await lookup_zee(client, 41.92, 8.74)

    zee, src = asyncio.run(run())
    assert src == "unavailable"
    assert zee["unknown"] is True
    assert zee["name"] is None
    assert not zee_is_high_seas(zee, _pearl(zee, src=src))
