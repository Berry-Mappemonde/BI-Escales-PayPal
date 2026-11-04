"""Défauts du film intégral relevés le 29/10/2026 (VERIF-FILM-0100, section 01 h 10)."""
import asyncio
import json

import climo_events
import film_script as fs
from toponyms import origin_name


def test_argo_identifier_not_grouped_quantities_still_are():
    out = fs._digits_for_speech("Puis, le flotteur Argo 4903331. 8393 milles, en 2027, 10000 enfants.")
    assert "Argo 4903331" in out
    assert "8 393 milles" in out and "10 000 enfants" in out and "2027" in out


def test_en_thousands_use_commas_same_length():
    src = "Then 1 642 miles, Argo float 4903331, 10 000 children."
    out = fs.en_thousands_commas(src)
    assert out == "Then 1,642 miles, Argo float 4903331, 10,000 children."
    assert len(out) == len(src)


def test_raw_port_names_respelled():
    assert origin_name("Fort De France") == "Fort-de-France"
    assert origin_name("Degrad Des Cannes") == "Dégrad des Cannes"
    assert origin_name("L'ile Rousse") == "L'Île-Rousse"
    assert origin_name("St Johns") == "Saint John's"
    assert origin_name("Basse Terre") == "Basse-Terre"
    assert origin_name("LA ROCHELLE") == "La Rochelle"


def test_campaign_said_by_name_or_not_at_all():
    named = {"kind": "campaign", "sciKind": "campaign", "name": "campagne CALICO", "title": "campagne CALICO, 2013"}
    fr = fs.station_spoken_label(named, "fr")
    en = fs.station_spoken_label(named, "en")
    if fr:  # le type « campaign » est reconnu par le sac
        assert "CALICO" in fr and fr != "une campagne"
        assert "CALICO" in en
    assert fs._campaign_code({"title": "Ifremer campagne MAYOBS33"}) == "MAYOBS33"
    assert fs._campaign_code({"title": "une campagne"}) == ""


def test_wind_turn_preposition():
    # Formulation « la moyenne de saison » : couverte par test_climo_events / test_film_script.
    assert climo_events._fr_to_dir("ouest") == "à l'ouest"
    assert climo_events._fr_to_dir("nord-est") == "au nord-est"


def test_translate_keeps_project_names():
    facts = {"projects": ["Agence de Recherche pour la Biodiversité", "Absent"], "amp": [], "stations": []}
    keep = fs._translate_keep_names(facts, "le projet Agence de Recherche pour la Biodiversité à La Réunion.")
    assert "Agence de Recherche pour la Biodiversité" in keep and "Absent" not in keep
    assert fs._translate_keep_names({"projects": []}, "x") == ""


def _plan(texts):
    return {"chapters": [{"id": f"c{i}", "text": t, "anchors": []} for i, t in enumerate(texts)]}


def test_judge_chapters_reports_failed_and_restore():
    async def cascade(system, user, **kw):
        txt = json.loads(user)["text"]
        return (json.dumps({"ok": "BAD" not in txt}), "nvidia-ultra")

    edited = _plan(["Bon un.", "BAD deux.", "Bon trois."])
    failed = asyncio.run(fs.judge_written_chapters(edited, cascade=cascade, raw_plan=edited))
    assert failed == [1]
    super_plan = _plan(["S un.", "S deux.", "S trois."])
    fixed = fs._restore_chapters(edited, super_plan, failed)
    assert [c["text"] for c in fixed["chapters"]] == ["Bon un.", "S deux.", "Bon trois."]
    again = asyncio.run(fs.judge_written_chapters(fixed, cascade=cascade, raw_plan=fixed, only={1}))
    assert again == []
    assert asyncio.run(fs.judge_written_once(edited, cascade=cascade, raw_plan=edited)) is False


def test_judge_chapters_transport_failure_is_none():
    async def cascade(system, user, **kw):
        return ("", "rules")

    assert asyncio.run(fs.judge_written_chapters(_plan(["a."]), cascade=cascade)) is None


def test_lendemain_counts_as_heard_date():
    out = fs.thin_chapter_dates([
        "Le 6 novembre, la zone de la campagne océanographique CALICO.",
        "Le 7 novembre, à vingt-six milles, le projet Programme Animlagon.",
        "Le 7 novembre, à vingt-six milles, le projet 10 000 enfants pour les coraux.",
        "Arrivée à Nouméa (Nouvelle-Calédonie) le 7 novembre, amarré à Port Brunelet.",
    ], "fr")
    assert out[1].startswith("Le lendemain")
    assert not out[2].startswith("Le 7 novembre") and not out[2].startswith("Le lendemain")


def test_angle_gap():
    assert fs._angle_gap(350, 10) == 20
    assert fs._angle_gap(90, 270) == 180


def test_translate_keep_name_completes_cut_fact_name():
    keep = fs._translate_keep_names(
        {"projects": ["Cape Verde Marine Protected Areas Networ"]},
        "Le 28 juin, le projet Cape Verde Marine Protected Areas Network. Puis.",
    )
    assert keep.endswith("Cape Verde Marine Protected Areas Network")


def test_fortnight_fixed_for_forty_days():
    out = fs._fix_fortnight("5,153 miles, a fortnight at sea.", "5 153 milles, une quarantaine de jours de mer.")
    assert out == "5,153 miles, about forty days at sea."


def test_off_route_coast_passed_at_sea_not_confirmed():
    text = "On 26 January, the waters of La Réunion. Then, the boat sails past Saint-Denis. Arrival at Saint-Gilles."
    assert fs._fault_confirmed("off-route: Saint-Denis", text, "en", []) is False
    assert fs._fault_confirmed("off-route: Saint-Denis", "Arrival at Saint-Denis.", "en", []) is True
    assert fs._fault_confirmed("off-route: Atlantis", text, "en", []) is True


def test_repair_en_day_shift():
    src = "Le 8 juin, les eaux espagnoles. Le 17 juin, les eaux marocaines. Arrivée le 1er juillet."
    en = "On June 8, Spanish waters. On June 16, Moroccan waters. Arrival on 1 July."
    assert fs._repair_en_days(src, en) == "On June 8, Spanish waters. On June 17, Moroccan waters. Arrival on 1 July."
    assert fs._repair_en_days(src, "On June 8, Spanish waters.") == "On June 8, Spanish waters."


def test_edit_keeps_digit_sentences_no_duplicate_arrival():
    raw = {"chapters": [{"id": "leg-0", "kind": "leg", "fromName": "Saint-Maur", "toName": "Ajaccio (Corse)", "text": (
        "Le 4 juin, Berry-Mappemonde quitte La Rochelle. Puis, les vents d'ouest s'installent : douze nœuds, "
        "la moyenne de saison. Arrivée à Ajaccio (Corse) le 1er juin, amarré au port d’Ajaccio (Corse). "
        "Trois jours d'escale."), "anchors": []}]}
    sup_text = ("Le 4 juin, Berry-Mappemonde quitte La Rochelle. Puis, les vents d’ouest s’installent : 12 nœuds, "
                "la moyenne de saison. Arrivée à Ajaccio (Corse) le 1er juin, amarré au port d’Ajaccio (Corse). "
                "3 jours d’escale.")
    sup = {"chapters": [{**raw["chapters"][0], "text": sup_text}], "source": "nemotron-super"}

    async def cascade(system, user, *, facts=None, **kw):
        from story_cascade import NO_NUMBER_FILTER, filter_numbers
        out = sup_text
        if facts is not NO_NUMBER_FILTER:
            out, _ = filter_numbers(out, facts)
        return out, "nemotron-ultra"

    edited = asyncio.run(fs.edit_written_once(sup, raw, cascade=cascade))
    text = (edited or sup)["chapters"][0]["text"]
    assert text.count("Arrivée à Ajaccio") == 1
    assert "la moyenne de saison" in text


# --- Défauts relevés à 01 h 28 (CHECKLIST-REVUE-VISUELLE) et sur les runs réels de 02 h 10 ---


def test_thin_dates_keeps_opening_and_arrival_dates():
    """2:30 : « Puis, le catamaran reprend la mer » perdait le 29 août (2 morceaux datés)."""
    bits = [
        "Le 29 août, le catamaran reprend la mer, départ vers Papeete. 6 671 milles, 46 jours de mer.",
        "Arrivée à Papeete le 14 octobre.",
    ]
    out = fs.thin_chapter_dates(bits, "fr")
    assert out[0].startswith("Le 29 août"), out
    assert "14 octobre" in out[1]
    en = fs.thin_chapter_dates(
        ["On August 19, at Halifax, the crew boards a second sailing boat. 497 miles.", "Arrival at Saint-Pierre on August 21."],
        "en",
    )
    assert en[0].startswith("On August 19"), en


def test_dedupe_arrival_sentences_keeps_richest():
    sents = [
        "Le 17 juillet, départ vers Pointe-à-Pitre : 192 milles, un jour de mer.",
        "Arrivée à Pointe-à-Pitre le 18 juillet.",
        "Arrivée à Pointe-à-Pitre (Guadeloupe) le 18 juillet, à Port de Sainte-Rose.",
    ]
    out = fs.dedupe_arrival_sentences(sents)
    assert len(out) == 2 and out[1].endswith("Port de Sainte-Rose."), out
    assert fs.dedupe_arrival_sentences(["Arrivée à A le 1er juin.", "Arrivée à A le 1er juin."]) == ["Arrivée à A le 1er juin."]
    # Deux lieux différents restent.
    assert len(fs.dedupe_arrival_sentences(["Arrivée à A le 1er juin.", "Arrivée à B le 2 juin."])) == 2


def test_edit_condensed_chapter_no_duplicate_arrival():
    """150 s FR : le brut a 3 phrases, Super condensé 2 ; l'alignement sur le brut
    recollait l'arrivée du brut après celle d'Ultra (« Arrivée à Pointe-à-Pitre le 18 juillet » ×2)."""
    raw_text = (
        "Le 17 juillet, départ vers Pointe-à-Pitre : 192 milles, un jour de mer. "
        "Puis, à vingt et un milles, le projet Restaurer les coraux. "
        "Arrivée à Pointe-à-Pitre (Guadeloupe) le 18 juillet, à Port de Sainte-Rose."
    )
    super_text = "Le 17 juillet, départ vers Pointe-à-Pitre : 192 milles, un jour de mer. Arrivée à Pointe-à-Pitre le 18 juillet."
    ultra = "Le 17 juillet, départ vers Pointe-à-Pitre : 192 milles, un jour de mer. Arrivée à Pointe-à-Pitre (Guadeloupe) le 18 juillet."
    raw_plan = {"chapters": [{"id": "leg-2", "text": raw_text, "tA": None, "tB": None}]}
    sup = {"chapters": [{"id": "leg-2", "text": super_text}], "targetSeconds": 150}

    async def fake(system, user, **kw):
        return ultra, "tokenfactory-ultra"

    out = asyncio.run(fs.edit_written_once(sup, raw_plan, cascade=fake))
    txt = out["chapters"][0]["text"] if out else super_text
    assert txt.count("Arrivée à Pointe-à-Pitre") == 1, txt


def test_final_arrival_has_no_stopover_before_today():
    """Fin d'intégral : « Escale de 3 jours. Aujourd'hui, le bateau est à La Rochelle »."""
    stop = {"name": "La Rochelle", "iso": "2027-05-31T12:00:00Z", "holdHours": 72}
    mid = fs._arrival_sentence(stop, "fr", chapter_i=1)
    fin = fs._arrival_sentence(stop, "fr", chapter_i=1, final=True)
    assert "escale" in mid.casefold(), mid  # l'escale intermédiaire garde sa durée
    assert fin.startswith("Arrivée à La Rochelle le 31 mai")
    assert "escale" not in fin.casefold() and "trois jours" not in fin, fin
    fin_en = fs._arrival_sentence(stop, "en", chapter_i=1, final=True)
    assert "stopover" not in fin_en and "three days" not in fin_en, fin_en


def test_en_argo_float_word_order():
    assert fs.en_argo_float("Then, Argo 7902126. On May 3, Argo 4903967 float.") == (
        "Then, Argo float 7902126. On May 3, Argo float 4903967."
    )
    assert fs.en_argo_float("the Argo float 4903331") == "the Argo float 4903331"


def test_edit_condensed_chapter_ultra_readds_sentence_keeps_arrival():
    """2:30 : Ultra remet « 497 milles » retiré par la condensation ; le garde-fou
    aligné sur Super coupait alors l'arrivée à Saint-Pierre."""
    raw_text = (
        "Le 19 août, à Halifax, l'équipage embarque sur un second voilier pour Saint-Pierre. "
        "497 milles, trois jours de mer. Arrivée à Saint-Pierre le 21 août."
    )
    super_text = "Le 19 août, à Halifax, l'équipage embarque sur un second voilier pour Saint-Pierre. Arrivée à Saint-Pierre le 21 août."
    raw_plan = {"chapters": [{"id": "leg-7", "text": raw_text, "tA": None, "tB": None}]}
    sup = {"chapters": [{"id": "leg-7", "text": super_text}], "targetSeconds": 150}

    async def fake(system, user, **kw):
        return raw_text, "tokenfactory-ultra"

    out = asyncio.run(fs.edit_written_once(sup, raw_plan, cascade=fake))
    txt = out["chapters"][0]["text"] if out else super_text
    assert "Arrivée à Saint-Pierre le 21 août" in txt, txt


def test_en_dates_one_form_without_ordinals():
    """150 s EN : « On July 30th … on August 15th » à côté de « On July 17 »."""
    assert fs.en_month_first("On July 30th, departure. Arrival on August 15th.") == (
        "On July 30, departure. Arrival on August 15."
    )
    assert fs.en_month_first("On 4 June and on 21st May 2027.") == "On June 4 and on May 21, 2027."
