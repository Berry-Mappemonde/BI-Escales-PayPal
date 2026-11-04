"""Lot film — défauts de données N12, N13, 10b, N16 (VERIF-FILM-0645, 29/10/2026).

N12 : MAYOBS33 (Mayotte) annoncé au départ de Nouméa — deux stations
« Bathymétrie - … » fusionnées par leur préfixe commun.
N13 : arrivée à La Rochelle « amarré à Port de Saint-Martin-de-Ré ».
10b : « 8 393 milles, 96 jours de mer » (moyenne 3,6 nd de l'horloge).
N16 : rapport de relecture finale `source: "simulate"` alors qu'Ultra a relu.
"""
from __future__ import annotations

import asyncio

from film_script import (
    _arrival_harbor,
    _place_dedup_key,
    _usable_changes,
    change_sentence,
    chapter_metrics,
    reread_before_store,
)

DAY = 86_400_000


def _station(seq: int, title: str, t_ms: int) -> dict:
    return {
        "id": f"{seq}:station:0", "kind": "station", "score": 2,
        "title": title, "fact": f"{title} (8 nm)", "tMs": t_ms,
    }


CALICO = "Bathymétrie - Nouvelle-Calédonie, passes de Boulari (campagne CALICO, 2013)"
MAYOBS33 = "Bathymétrie - Mayotte, fer à cheval (campagne MAYOBS33, 2025)"


def test_n12_two_campaigns_with_same_dataset_prefix_are_two_sites():
    assert _place_dedup_key(_station(505, CALICO, 1)) != _place_dedup_key(_station(622, MAYOBS33, 2))


def test_n12_mayobs33_keeps_its_own_instant_at_the_end_of_the_leg():
    t_dep, t_end = 1_000 * DAY, 1_048 * DAY
    rows = _usable_changes([_station(505, CALICO, t_dep), _station(622, MAYOBS33, t_end)])
    mayobs = [c for c in rows if "MAYOBS33" in c["title"]]
    assert mayobs, rows
    # Jamais l'instant du départ de Nouméa (celui de CALICO).
    assert mayobs[0]["tMs"] == t_end
    assert any("CALICO" in c["title"] for c in rows)


def test_n12_same_campaign_still_said_once():
    a = _station(1, "Bathymétrie - Mayotte, fer à cheval (campagne MAYOBS33, 2025)", 10)
    b = _station(2, "Bathymétrie - Mayotte (campagne MAYOBS33, 2025)", 20)
    rows = _usable_changes([a, b])
    assert len([c for c in rows if "MAYOBS33" in c["title"]]) == 1


def test_n13_la_rochelle_is_not_moored_at_another_towns_port():
    dest = {"name": "La Rochelle", "lat": 46.155, "lon": -1.155}
    items = [
        {"kind": "marina", "title": "Port de Saint-Martin-de-Ré", "lat": 46.205, "lon": -1.365, "tMs": 3},
        {"kind": "marina", "title": "Port de Saint-Denis d'Oléron", "lat": 46.033, "lon": -1.38, "tMs": 2},
    ]
    fr = _arrival_harbor(items, dest, "fr")
    assert "Saint-Martin" not in fr and "Oléron" not in fr
    assert "La Rochelle" in fr
    assert "Saint-Martin" not in _arrival_harbor(items, dest, "en")


def test_n13_harbour_of_the_stop_itself_and_named_marinas_still_spoken():
    dest = {"name": "Ajaccio (Corse)", "lat": 41.92, "lon": 8.74}
    assert "Ajaccio" in _arrival_harbor(
        [{"kind": "marina", "title": "Port d'Ajaccio", "lat": 41.92, "lon": 8.74, "tMs": 1}], dest, "fr",
    )
    ffr = {"name": "Fort-de-France (Martinique)", "lat": 14.6, "lon": -61.07}
    spoken = _arrival_harbor(
        [{"kind": "marina", "title": "Étang Z'Abricots", "lat": 14.61, "lon": -61.09, "tMs": 1}], ffr, "fr",
    )
    assert "Z'Abricots" in spoken
    lr = {"name": "La Rochelle", "lat": 46.155, "lon": -1.155}
    assert "Minimes" in _arrival_harbor(
        [{"kind": "marina", "title": "Port des Minimes", "lat": 46.146, "lon": -1.168, "tMs": 1}], lr, "fr",
    )


def _slow_last_leg() -> dict:
    dep = 1_000 * DAY
    return {
        "fromName": "Europa (TAAF)", "toName": "La Rochelle",
        "from": {"name": "Europa (TAAF)", "nm": 33_000.0},
        "to": {"name": "La Rochelle", "nm": 41_393.0},
        "mode": "sail", "arrived": True,
        "departMs": dep, "tA": dep - 3 * DAY, "tB": dep + 96 * DAY,
    }


def test_10b_slow_clock_days_are_not_spoken():
    from film_script import _spoken_metrics_days

    m = chapter_metrics(_slow_last_leg(), None)
    assert m["legNm"] == 8393
    assert m["plannedKnots"] is None          # 3,6 nd ne se dit pas (déjà vrai)
    assert m.get("slowTrace") is True
    assert _spoken_metrics_days(m, "fr") == ""
    assert _spoken_metrics_days(m, "en") == ""


def test_10b_normal_leg_days_still_spoken():
    from film_script import _spoken_metrics_days

    w = _slow_last_leg()
    w["tB"] = w["departMs"] + 46 * DAY     # 8 393 milles en 46 jours ≈ 7,6 nd
    m = chapter_metrics(w, None)
    assert not m.get("slowTrace")
    assert "jours de mer" in _spoken_metrics_days(m, "fr")


def test_10b_opening_sentence_has_miles_but_no_96_days():
    from film_script import _compact_sea_opening

    w = _slow_last_leg()
    w["destName"] = "La Rochelle"
    text = _compact_sea_opening(w, lang="fr")
    assert "8 393 milles" in text, text
    assert "jours" not in text, text


def _plan() -> dict:
    return {
        "chapters": [{
            "id": "c0",
            "text": "Le 15 mai, Berry-Mappemonde quitte La Rochelle. Arrivée à Ajaccio le 26 mai.",
            "tA": "2026-05-15T08:00:00Z", "tB": "2026-05-26T12:00:00Z",
            "fromName": "La Rochelle", "toName": "Ajaccio (Corse)", "destName": "Ajaccio (Corse)",
        }],
    }


def test_n16_reread_report_names_the_model_that_read():
    async def ultra(system, user, **kw):
        return '{"ok": true, "faults": []}', "nemotron-ultra"

    stops = [{"name": "La Rochelle"}, {"name": "Ajaccio (Corse)"}]
    ok, rep = asyncio.run(reread_before_store(_plan(), stops, cascade=ultra, lang="fr"))
    assert ok is True
    assert rep["source"] == "nemotron-ultra"
    assert rep["local"] == "simulate"
    assert rep["groups"] >= 1


def test_n16_local_only_reread_still_says_simulate():
    stops = [{"name": "La Rochelle"}, {"name": "Ajaccio (Corse)"}]
    ok, rep = asyncio.run(reread_before_store(_plan(), stops, cascade=None, lang="fr"))
    assert ok is True
    assert rep["source"] == "simulate"


def test_timorese_waters_are_said_in_french():
    title = "Zone économique exclusive (Timorese)"
    fr = change_sentence({"kind": "zee-enter", "title": title, "fact": title}, "fr")
    assert "Timorese" not in fr and "Timor" in fr, fr
