"""Version 150 s au « now » réel (29/10/2026) : la barre suit la date dite.

Le 2:30 coupe des phrases d'eaux (« Puis, les eaux capverdiennes. ») dont
l'ancre restait dans la liste. Le repli « 12 premiers caractères » de
_locate_spoken la posait sur une autre phrase restée (« Puis, les eaux
françaises. ») : la barre disait 26 juin pour une phrase du 4 juin, et la
relecture refusait le rédigé (« date »).
"""
import film_script as fs
from film_script import _anchor_dates_regress, _locate_spoken, chapter_anchors, chapter_metrics

DAY = 86_400_000
T0 = 1_780_531_200_000  # 2026-06-04T00:00:00Z


def _iso_day(iso: str) -> str:
    return iso[:10]


def test_prefix_fallback_needs_the_same_sentence():
    text = "Le 4 juin, départ vers Fort-de-France. Puis, les eaux françaises. Le 6 juin, les eaux italiennes."
    assert _locate_spoken(text, "Puis, les eaux capverdiennes.") < 0
    assert _locate_spoken(text, "Puis, les eaux françaises.") == text.index("Puis, les eaux françaises.")


def test_prefix_fallback_still_finds_a_trimmed_sentence():
    text = "Le 4 juin, départ vers Fort-de-France : 5 153 milles. Arrivée le 14 juillet."
    spoken = "Le 4 juin, départ vers Fort-de-France : 5 153 milles, une quarantaine de jours de mer."
    assert _locate_spoken(text, spoken) == 0


def test_suffix_fallback_does_not_anchor_to_another_sentence():
    suffix = "la phrase reste en mémoire."
    text = f"Une phrase différente contient {suffix} Et la suite continue."
    spoken = "Le texte coupé décrit un autre départ, puis " + suffix
    assert _locate_spoken(text, spoken) < 0


def test_review_metrics_match_leg_in_either_direction():
    review = {"legs": [{"from": "Saint-Pierre", "to": "Halifax", "legNm": 489,
                        "daysAtSea": 3, "plannedKnots": 8}]}
    for frm, to in (("Halifax", "Saint-Pierre"), ("Saint-Pierre", "Halifax")):
        window = {"fromName": frm, "toName": to,
                  "from": {"name": frm, "nm": 100}, "to": {"name": to, "nm": 589},
                  "mode": "sail", "tA": T0, "tB": T0 + 3 * DAY}
        assert chapter_metrics(window, review)["legNm"] == 489
        assert fs._side_hop_metrics(window, review)["legNm"] == 489


def test_via_marker_does_not_split_saint_pierre_hop():
    t0, t1, t2 = 1_800_000_000_000, 1_800_100_000_000, 1_800_200_000_000
    windows = fs._windows([
        {"name": "Halifax", "iso": fs._iso(t0), "nm": 8_643.0, "filmNm": 8_643.0},
        {"name": "Saint-Pierre", "iso": fs._iso(t1), "nm": 9_015.0, "filmNm": 9_132.54, "kind": "via"},
        {"name": "Saint-Pierre", "iso": fs._iso(t2), "nm": 9_132.0, "filmNm": 9_132.0},
    ], t0, t2)
    assert len(windows) == 1
    assert windows[0]["fromName"] == "Halifax"
    assert windows[0]["toName"] == "Saint-Pierre"
    assert fs._window_leg_nm(windows[0]) == 489


def test_cut_sentence_does_not_steal_a_kept_anchor():
    text = (
        "Le 4 juin, départ vers Fort-de-France. Puis, les eaux françaises. "
        "Le 6 juin, les eaux italiennes. Arrivée à Fort-de-France le 14 juillet."
    )
    anchored = [
        ("Le 4 juin, départ vers Fort-de-France.", T0, {"role": "depart"}),
        ("Puis, les eaux françaises.", T0, {"kind": "zee-enter", "place": "France"}),
        ("Le 6 juin, les eaux italiennes.", T0 + 2 * DAY, {"kind": "zee-enter", "place": "Italie"}),
        ("Puis, les eaux capverdiennes.", T0 + 22 * DAY, {"kind": "zee-enter", "place": "Cap-Vert"}),
        ("Arrivée à Fort-de-France le 14 juillet.", T0 + 40 * DAY, {"role": "arrive"}),
    ]
    anchors = chapter_anchors(text, anchored, T0, T0 + 40 * DAY, "fr")
    by_place = {a.get("place"): _iso_day(a["t"]) for a in anchors if a.get("place")}
    assert by_place.get("France") == "2026-06-04"
    assert by_place.get("Italie") == "2026-06-06"
    assert "Cap-Vert" not in by_place
    chapter = {"text": text, "anchors": anchors}
    assert not _anchor_dates_regress([chapter], "fr")
    assert fs.nemotron_reread_report(text, [], lang="fr", chapters=[chapter]).get("faults", []).count("date") == 0


FR_LEG8 = ("Le 23 août, à Saint-Pierre, l'équipage reprend le second voilier pour Halifax : "
           "417 milles, 5 jours de mer. Arrivée à Halifax le 28 août.")
# Réponse réelle de Lightning (run TF du 29/10, 150 s, leg-8) : le français, espaces mangées.
GLUED_LEG8 = ("Le 23août, àSaint-Pierre, l'équipagereprend le secondvoilierpourHalifax : "
              "417milles, 5jours de mer. Arrivée àHalifaxle28août.")
EN_LEG8 = ("On August 23, at Saint-Pierre, the crew boards the second vessel again for Halifax: "
           "417 miles, 5 days at sea. Arrival in Halifax on August 28.")


def test_glued_french_share_separates_copy_from_translation():
    src_w = set(__import__("re").findall(r"[^\W\d_]{3,}", FR_LEG8.casefold()))
    assert fs._glued_french_share(src_w, GLUED_LEG8) > 0.8
    assert fs._glued_french_share(src_w, EN_LEG8) < 0.6


def test_glued_french_share_uses_accent_folded_whole_words():
    assert fs._glued_french_share({"mer"}, "summer") == 0
    assert fs._glued_french_share({"équipage"}, "equipage à bord") == 1


def test_glued_french_is_retried_never_served_as_english():
    import asyncio
    raw_ch = {"id": "leg-8", "text": FR_LEG8, "anchors": []}
    answers = [GLUED_LEG8, EN_LEG8]
    calls = []

    async def tr(system, user, **kw):
        calls.append(user)
        return answers[min(len(calls) - 1, 1)], "nemotron-lightning"

    en = asyncio.run(fs.translate_written_plan({"chapters": [raw_ch]}, {"chapters": [raw_ch]}, cascade=tr))
    assert len(calls) == 2, "la réponse soudée doit être redemandée"
    assert en and "août" not in en["chapters"][0]["text"]
    assert en["chapters"][0]["text"].startswith("On August 23")

    async def always_glued(system, user, **kw):
        return GLUED_LEG8, "nemotron-lightning"

    assert asyncio.run(fs.translate_written_plan(
        {"chapters": [raw_ch]}, {"chapters": [raw_ch]}, cascade=always_glued)) is None


def test_frozen_store_holds_reviewed_150s_film_fr_and_en():
    """Pré-génération figée (N17) : le stock de la CI porte le 150 s rédigé, relu FR et EN,
    sous 150 s, sans eaux coupées ancrées à une date d'après, et sans français dans l'anglais."""
    import json
    import tarfile
    from pathlib import Path

    archive = Path(__file__).resolve().parent / "fixtures" / "official_store.tar.gz"
    with tarfile.open(archive, "r:gz") as tf:
        films = [
            json.load(tf.extractfile(m)) for m in tf.getmembers()
            if m.isfile() and m.name.endswith(".json")
        ]
    film_key = "c4a0d2dc06cea61b:2026-05-15T08:00:00Z:2026-10-29:" + __import__("official_store").FILM_SCRIPT_REV
    films = [d for d in films if d.get("family") == "film" and d.get("key") == film_key]
    assert len(films) == 1
    written = films[0]["payload"].get("written") or {}
    for lg in ("fr", "en"):
        plan = (written.get(lg) or {}).get("150") or {}
        assert plan.get("chapters"), lg
        assert plan.get("estimatedSeconds", 999) <= 150, (lg, plan.get("estimatedSeconds"))
        receipt = plan.get("receipt") or {}
        assert receipt.get("llmCalls", 0) > 0 and receipt.get("ruleFallbacks") == 0
        assert receipt.get("reread") == "pass" and receipt.get("reread_en") == "pass"
        assert not fs._anchor_dates_regress(plan["chapters"], lg), lg
        if lg == "en":
            text = " ".join(c["text"] for c in plan["chapters"])
            for fr_word in ("août", "milles", "jours de mer", "équipage", "Arrivée"):
                assert fr_word not in text, fr_word
