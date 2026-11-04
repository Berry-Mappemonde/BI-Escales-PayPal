"""Film intégral : jour redit (N11), « Année 1 » collé au titre (N10), année au nouvel an (N14)."""
import film_script as fs


def test_n11_same_day_after_opening_becomes_puis():
    out = fs.drop_repeated_heard_dates([
        "Le 17 juillet, d'île en île, Berry-Mappemonde quitte Fort-de-France (Martinique).",
        "Puis, les eaux de la Dominique.",
        "Le 17 juillet, à vingt et un milles, le projet CleanMyIsland.",
        "Arrivée à Pointe-à-Pitre (Guadeloupe) le 18 juillet.",
    ], "fr")
    assert out[2] == "Puis, à vingt et un milles, le projet CleanMyIsland."
    assert out[0].startswith("Le 17 juillet")
    assert out[3] == "Arrivée à Pointe-à-Pitre (Guadeloupe) le 18 juillet."


def test_n11_next_day_counts_as_heard():
    out = fs.drop_repeated_heard_dates([
        "Le 14 août, les eaux de la Guyane.",
        "Le lendemain, la zone de la campagne océanographique LINKS.",
        "Le 15 août, le bateau longe Dégrad des Cannes.",
        "Le 17 août, haute mer.",
    ], "fr")
    assert out[2] == "Puis, le bateau longe Dégrad des Cannes."
    assert out[3] == "Le 17 août, haute mer."


def test_n11_keeps_proper_noun_capital_and_english():
    out = fs.drop_repeated_heard_dates([
        "On 26 January, Berry-Mappemonde leaves Tromelin.",
        "On 26 January, the waters of Réunion.",
    ], "en")
    assert out[1] == "Then, the waters of Réunion."
    out = fs.drop_repeated_heard_dates([
        "Le 17 octobre, Berry-Mappemonde quitte Papeete.",
        "Le 17 octobre, Tia'i fenua passe au large.",
    ], "fr")
    assert out[1] == "Puis, Tia'i fenua passe au large."


def test_n11_thin_chapter_dates_drops_repeat():
    got = fs.thin_chapter_dates([
        "Le 30 juillet, Berry-Mappemonde quitte Marigot (Saint-Martin), cap au sud pour Cayenne (Guyane).",
        "Puis, les eaux de Saint-Martin (partie française).",
        "Le 30 juillet, haute mer.",
        "Puis, les eaux de la Dominique.",
        "Arrivée à Cayenne (Guyane) le 15 août.",
    ], "fr")
    assert "Puis, haute mer." in got
    assert sum(1 for s in got if "30 juillet" in s) == 1


def test_n10_project_year_suffix_in_parentheses():
    assert fs.project_spoken_title(
        "Restaurer les coraux préférés des poissons-demoiselles Année 1"
    ) == "Restaurer les coraux préférés des poissons-demoiselles (Année 1)"
    assert fs.project_spoken_title("Coral nursery - Year 2") == "Coral nursery (Year 2)"
    assert fs.project_spoken_title("CleanMyIsland") == "CleanMyIsland"
    assert fs.project_spoken_title("Année 1") == "Année 1"
    assert fs.project_spoken_title("Projet (Année 1)") == "Projet (Année 1)"


def test_n14_year_said_at_new_year_only_once():
    chapters = [
        {"text": "L'expédition a quitté Saint-Maur le 15 mai 2026. Arrivée à Ajaccio le 1er juin.",
         "anchors": [{"charIdx": 0}]},
        {"text": "Le 10 novembre, départ. Arrivée à Dzaoudzi (Mayotte) le 31 décembre.",
         "anchors": [{"charIdx": 0}]},
        {"text": "Le 3 janvier, Berry-Mappemonde quitte Dzaoudzi. Arrivée à Tromelin le 21 janvier.",
         "anchors": [{"charIdx": 0}, {"charIdx": 48, "t": "x"}], "events": [{"charIdx": 48}]},
        {"text": "Le 24 janvier, départ vers Saint-Gilles.", "anchors": [{"charIdx": 0}]},
    ]
    fs.mark_year_changes(chapters, "fr")
    assert chapters[2]["text"].startswith("Le 3 janvier 2027, Berry-Mappemonde")
    assert "21 janvier." in chapters[2]["text"] and "2027" not in chapters[3]["text"]
    assert chapters[2]["anchors"][0]["charIdx"] == 0
    assert chapters[2]["anchors"][1]["charIdx"] == 53
    assert chapters[2]["events"][0]["charIdx"] == 53
    assert chapters[2]["text"][53:].startswith("Arrivée")
    # Idempotent : l'année déjà dite n'est pas redoublée.
    fs.mark_year_changes(chapters, "fr")
    assert chapters[2]["text"].count("2027") == 1


def test_n14_no_written_year_no_insertion_and_english():
    chapters = [{"text": "Le 31 décembre, arrivée."}, {"text": "Le 3 janvier, départ."}]
    fs.mark_year_changes(chapters, "fr")
    assert "2027" not in chapters[1]["text"]
    en = [{"text": "The expedition left Saint-Maur on 15 May 2026. Arrival on 31 December."},
          {"text": "On 3 January, Berry-Mappemonde leaves Dzaoudzi."}]
    fs.mark_year_changes(en, "en")
    assert en[1]["text"] == "On 3 January 2027, Berry-Mappemonde leaves Dzaoudzi."


def test_polish_written_plan_applies_n10_n11_n14():
    raw = {"chapters": [
        {"id": "a", "tA": "2026-05-15T08:00:00Z", "tB": "2026-12-31T00:00:00Z",
         "text": "x", "anchors": []},
        {"id": "b", "tA": "2026-12-31T00:00:00Z", "tB": "2027-01-21T00:00:00Z",
         "text": "y", "anchors": []},
    ]}
    plan = {"chapters": [
        {"id": "a", "tA": "2026-05-15T08:00:00Z", "tB": "2026-12-31T00:00:00Z",
         "text": "L'expédition a quitté Saint-Maur le 15 mai 2026. Arrivée à Dzaoudzi le 31 décembre."},
        {"id": "b", "tA": "2026-12-31T00:00:00Z", "tB": "2027-01-21T00:00:00Z",
         "text": "Le 3 janvier, Berry-Mappemonde quitte Dzaoudzi. Le 3 janvier, le projet Coraux Année 1. "
                 "Arrivée à Tromelin le 21 janvier."},
    ]}
    out = fs._polish_written_plan(plan, raw, "fr")
    text = out["chapters"][1]["text"]
    assert text.startswith("Le 3 janvier 2027, Berry-Mappemonde")
    assert "Puis, le projet Coraux (Année 1)." in text
    assert text.count("3 janvier") == 1
