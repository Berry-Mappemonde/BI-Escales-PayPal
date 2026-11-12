#!/usr/bin/env python3
"""Re-time film fixture legs 0–17 from bi-escales/app/escales/cabin_legs.json."""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent.parent
CABIN = ROOT / "app" / "escales" / "cabin_legs.json"
RAW = REPO / "naviguide-escales/server/tests/fixtures/film_150_raw_2026-10-29.json"
INTEGRAL = REPO / "naviguide-escales/server/tests/fixtures/film_integral_written_2026-10-29.json"

sys.path.insert(0, str(ROOT / "tests"))
from film_cabin_schedule import film_leg_bounds  # noqa: E402

sys.path.insert(0, str(REPO / "naviguide-escales/server"))
from film_script import spoken_sea_days  # noqa: E402

_FR_MONTHS = (
    "janvier",
    "février",
    "mars",
    "avril",
    "mai",
    "juin",
    "juillet",
    "août",
    "septembre",
    "octobre",
    "novembre",
    "décembre",
)
_EN_MONTHS = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)

# The Halifax side trip (legs 6–9) and leg 10 templates below keep their original August
# wording. Their dates ("Le 18 août", "On August 19", "le 14 octobre"…) and sea-day counts
# ("trois jours de mer", "five days at sea", "46 jours de mer"…) are PLACEHOLDERS: apply_leg
# rewrites them at run time from the cabin schedule (patch_halifax_text, replace_sea_days_in_text,
# scrub_integral_dates). Fix the schedule or those functions, not the numbers in these strings.
RAW_HALIFAX_FR: dict[str, str] = {
    "leg-6": "Le 18 août, l'équipage s'envole de Cayenne pour Halifax ; le catamaran attend à Cayenne.",
    "leg-7": (
        "Le 19 août, à Halifax (Nouvelle-Écosse), l'équipage embarque sur un second voilier pour "
        "Saint-Pierre (Saint-Pierre-et-Miquelon). 497 milles, trois jours de mer. "
        "Arrivée à Saint-Pierre (Saint-Pierre-et-Miquelon) le 21 août."
    ),
    "leg-8": (
        "Le 23 août, à Saint-Pierre (Saint-Pierre-et-Miquelon), l'équipage reprend un second voilier pour "
        "Halifax (Nouvelle-Écosse). 417 milles, cinq jours de mer. Arrivée à Halifax (Nouvelle-Écosse) le 28 août."
    ),
    "leg-9": "Le 28 août, l'équipage s'envole d'Halifax pour Cayenne.",
}

INTEGRAL_HALIFAX_FR: dict[str, str] = {
    "leg-6": (
        "Le 18 août, l'équipage s'envole de Cayenne (Guyane) pour Halifax (Nouvelle-Écosse) ; "
        "le catamaran attend à Cayenne (Guyane)."
    ),
    "leg-7": (
        "Le 19 août, à Halifax (Nouvelle-Écosse), l'équipage embarque sur un second voilier pour "
        "Saint-Pierre (Saint-Pierre-et-Miquelon). 497 milles, trois jours de mer. "
        "Puis, le vent tourne à l'ouest : huit nœuds, la moyenne de saison. "
        "Puis, les vents d'ouest s'installent : douze nœuds, la moyenne de saison. "
        "Arrivée à Saint-Pierre (Saint-Pierre-et-Miquelon) le 21 août, amarré au port de "
        "Saint-Pierre (Saint-Pierre-et-Miquelon)."
    ),
    "leg-8": (
        "Le 23 août, à Saint-Pierre (Saint-Pierre-et-Miquelon), l'équipage reprend un second voilier pour "
        "Halifax (Nouvelle-Écosse). 417 milles, cinq jours de mer. "
        "Arrivée à Halifax (Nouvelle-Écosse) le 28 août, amarré au port d'Halifax (Nouvelle-Écosse)."
    ),
    "leg-9": "Le 28 août, l'équipage s'envole d'Halifax pour Cayenne.",
}

INTEGRAL_HALIFAX_EN: dict[str, str] = {
    "leg-6": (
        "On August 18, the crew flies from Cayenne (French Guiana) to Halifax (Nova Scotia); "
        "the catamaran waits in Cayenne (French Guiana)."
    ),
    "leg-7": (
        "On August 19, in Halifax (Nova Scotia), the crew boards a second vessel for "
        "Saint-Pierre (Saint Pierre and Miquelon). 497 miles, three days at sea. "
        "Then, the wind turns west: eight knots, the seasonal average. "
        "Then, the westerly winds set in: twelve knots, the seasonal average. "
        "Arrival at Saint-Pierre (Saint Pierre and Miquelon) on August 21, "
        "moored at Saint-Pierre (Saint Pierre and Miquelon) port."
    ),
    "leg-8": (
        "On August 23, at Saint-Pierre (Saint Pierre and Miquelon), the crew takes on a second vessel "
        "for Halifax (Nova Scotia). 417 miles, five days at sea. "
        "Arrival in Halifax (Nova Scotia) on August 28, moored at the Halifax (Nova Scotia) port."
    ),
    "leg-9": "On August 28, the crew flies from Halifax to Cayenne.",
}

INTEGRAL_LEG10_FR = (
    "Le 29 août, le catamaran reprend la mer, départ vers Papeete (Polynésie française). "
    "6 671 milles, 46 jours de mer, à 6 nœuds de moyenne. Le lendemain, le vent tourne au nord-est : "
    "six nœuds, la moyenne de saison. Le 30 août, les alizés de nord-est s'installent : "
    "douze nœuds, la moyenne de saison. Puis, à l'équateur, les alizés de sud-est s'installent : "
    "douze nœuds, la moyenne de saison. Arrivée à Papeete (Polynésie française) le 14 octobre, "
    "amarré au port de Papeete (Polynésie française). Trois jours au port."
)

INTEGRAL_LEG10_EN = (
    "On August 29, the catamaran puts to sea, departure for Papeete (French Polynesia). "
    "6,671 miles, 46 days at sea, at 6 knots average. The next day, the wind turns north-east: "
    "six knots, the seasonal average. On August 30, the north-east trade winds set in: "
    "twelve knots, the seasonal average. Then, at the equator, the south-east trade winds set in: "
    "twelve knots, the seasonal average. Arrival at Papeete (French Polynesia) on October 14, "
    "moored at Papeete (French Polynesia). Three days at port."
)

RAW_LEG10_FR = (
    "Le 29 août, le catamaran reprend la mer, départ vers Papeete (Polynésie française). "
    "6 671 milles, 46 jours de mer, à 6 nœuds de moyenne. "
    "Arrivée à Papeete (Polynésie française) le 14 octobre."
)


def parse_iso(text: str) -> datetime:
    raw = text.strip().replace("Z", "+00:00")
    moment = datetime.fromisoformat(raw)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def iso_z(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def leg_days(t_a: str, t_b: str) -> float:
    return (parse_iso(t_b) - parse_iso(t_a)).total_seconds() / 86400.0


def fr_day_month(dt: datetime) -> tuple[str, str]:
    day = "1er" if dt.day == 1 else str(dt.day)
    return day, _FR_MONTHS[dt.month - 1]


def en_day_month(dt: datetime) -> str:
    return f"{_EN_MONTHS[dt.month - 1]} {dt.day}"


def replace_sea_days_in_text(text: str, sea: str, *, en: bool) -> str:
    if en:
        text = re.sub(
            r"(?i)(about (?:ten|fifteen|twenty|thirty|forty) days at sea|"
            r"a fortnight at sea|"
            r"less than a day at sea|one day at sea|"
            r"roughly forty days at sea|"
            r"\d+ days at sea|"
            r"(?:one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|"
            r"thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty) days at sea)",
            sea,
            text,
            count=1,
        )
    else:
        cardinals = (
            r"moins d'un|un|une dizaine|une quinzaine|une vingtaine|une trentaine|une quarantaine|"
            r"deux|trois|quatre|cinq|six|sept|huit|neuf|dix|onze|douze|treize|quatorze|quinze|"
            r"seize|dix-sept|dix-huit|dix-neuf|vingt|\d+"
        )
        text = re.sub(rf"({cardinals})(?:\s+de)?\s+jours de mer", sea, text, count=1)
    return text


def patch_dates_fr(text: str, dep: datetime, arr: datetime) -> str:
    d1, m1 = fr_day_month(dep)
    d2, m2 = fr_day_month(arr)
    text = re.sub(
        r"\bLe (\d+|1er) [\wéû]+(?=, départ)",
        f"Le {d1} {m1}",
        text,
        count=1,
    )
    text = re.sub(
        r"\bLe (\d+|1er) [\wéû]+, (?=(?:d'île|Berry|pour la).{0,40}quitte)",
        f"Le {d1} {m1}, ",
        text,
        count=1,
    )
    text = re.sub(
        r"Arrivée à [^\.]+ le (\d+|1er) [\wéû]+",
        lambda m: re.sub(r"le (\d+|1er) [\wéû]+", f"le {d2} {m2}", m.group(0)),
        text,
        count=1,
    )
    return text


def patch_dates_en(text: str, dep: datetime, arr: datetime) -> str:
    text = re.sub(
        r"\bOn [A-Za-z]+ \d{1,2}(?=,)",
        f"On {en_day_month(dep)}",
        text,
        count=1,
    )
    text = re.sub(
        r"(Arrival (?:at|in) [^,]+ on )[A-Za-z]+ \d{1,2}",
        rf"\g<1>{en_day_month(arr)}",
        text,
        count=1,
    )
    return text


def patch_halifax_text(text: str, dep: datetime, arr: datetime, *, lang: str) -> str:
    if lang == "fr":
        d1, m1 = fr_day_month(dep)
        text = re.sub(r"^Le (\d+|1er) [\wéû]+", f"Le {d1} {m1}", text, count=1)
        text = re.sub(
            r"(Arrivée à [^\.]+ le )(\d+|1er) [\wéû]+",
            lambda m: m.group(1) + " ".join(fr_day_month(arr)),
            text,
            count=1,
        )
        return text
    text = re.sub(r"^On [A-Za-z]+ \d{1,2}", f"On {en_day_month(dep)}", text, count=1)
    text = re.sub(
        r"(Arrival (?:at|in) [^,]+ on )[A-Za-z]+ \d{1,2}",
        rf"\g<1>{en_day_month(arr)}",
        text,
        count=1,
    )
    return text


def _capitalise_first(sentence: str) -> str:
    """A sentence that lost its leading date ("Le 5 juin, la Corse…") still starts with a capital."""
    return sentence[:1].upper() + sentence[1:]


def scrub_integral_dates(text: str, dep: datetime, arr: datetime, *, lang: str, leg_id: str) -> str:
    """Keep spoken departure + arrival day-month only on legs 1–12 integral narrative."""
    if leg_id not in {f"leg-{n}" for n in range(1, 13)}:
        return text
    if lang == "fr":
        d1, m1 = fr_day_month(dep)
        d2, m2 = fr_day_month(arr)
        text = re.sub(
            r"^Le (\d+|1er) [\wéû]+, (?=(?:d'île|Berry|pour la|le catamaran).*)",
            f"Le {d1} {m1}, ",
            text,
            count=1,
        )
        text = patch_dates_fr(text, dep, arr)
        parts = [p.strip() for p in re.split(r"(?<=\.) ", text) if p.strip()]
        cleaned: list[str] = []
        fr_lead = re.compile(
            rf"^Le (\d+|1er) ({'|'.join(_FR_MONTHS)}), ",
            flags=re.IGNORECASE,
        )
        for idx, part in enumerate(parts):
            if part.startswith("Arrivée"):
                cleaned.append(
                    re.sub(
                        r"le (\d+|1er) [\wéû]+",
                        f"le {d2} {m2}",
                        part,
                        count=1,
                    )
                )
                continue
            if idx == 0 or "quitte" in part or "quitté" in part:
                cleaned.append(part)
                continue
            if part.startswith("Le lendemain") or part.startswith("The next day"):
                cleaned.append(part)
                continue
            cleaned.append(_capitalise_first(fr_lead.sub("", part)))
        return " ".join(cleaned)
    text = patch_dates_en(text, dep, arr)
    parts = [p.strip() for p in re.split(r"(?<=\.) ", text) if p.strip()]
    cleaned = []
    en_lead = re.compile(
        rf"^On ({'|'.join(_EN_MONTHS)}) \d{{1,2}}, ",
        flags=re.IGNORECASE,
    )
    for idx, part in enumerate(parts):
        if part.startswith("Arrival"):
            cleaned.append(part)
            continue
        if idx == 0 or "leaves" in part or "left" in part:
            cleaned.append(part)
            continue
        if part.startswith("The next day"):
            cleaned.append(part)
            continue
        cleaned.append(_capitalise_first(en_lead.sub("", part)))
    return " ".join(cleaned)


def leg17_integral_text(leg: dict, dep: datetime, arr: datetime, sea: str, *, lang: str) -> str:
    from_n = leg.get("fromName") or "Europa (TAAF)"
    if lang == "fr":
        d1, m1 = fr_day_month(dep)
        d2, m2 = fr_day_month(arr)
        return (
            f"Le {d1} {m1}, pour la dernière étape, Berry-Mappemonde quitte {from_n} pour La Rochelle. "
            f"8 393 milles, {sea}. Puis, les eaux des Terres australes et antarctiques françaises. "
            "Puis, haute mer. Puis, à vingt-trois milles, le projet High Seas: New Hope Beyond National Boundaries. "
            "Puis, les eaux françaises. Puis, le bateau passe près de l'aire marine protégée Pointe d'Arçay. "
            f"Arrivée à La Rochelle le {d2} {m2}, amarré à Port de Saint-Martin-de-Ré. "
            "Aujourd'hui, le bateau est à La Rochelle."
        )
    return (
        f"On {en_day_month(dep)}, for the last leg, Berry-Mappemonde leaves {from_n} for La Rochelle. "
        f"8,393 miles, {sea}. Then, waters of the French Southern and Antarctic Lands. Then, high sea. "
        "Then, at twenty-three miles, the High Seas: New Hope Beyond National Boundaries project. "
        "Then, French waters. Then, the boat passes near the Pointe d'Arçay marine protected area. "
        f"Arrival in La Rochelle on {en_day_month(arr)}, moored at Port de Saint-Martin-de-Ré. "
        "Today, the boat is in La Rochelle."
    )


def leg0_raw_fr(dep: datetime, arr: datetime, sea: str) -> str:
    d1, m1 = fr_day_month(dep)
    d2, m2 = fr_day_month(arr)
    return (
        f"L'expédition Berry-Mappemonde a quitté La Rochelle le {d1} {m1}, cap au sud-ouest. "
        f"Départ vers Ajaccio : 1 819 milles, {sea}. Arrivée à Ajaccio (Corse) le {d2} {m2}."
    )


def leg17_raw_fr(dep: datetime, arr: datetime, sea: str) -> str:
    d1, m1 = fr_day_month(dep)
    d2, m2 = fr_day_month(arr)
    return (
        f"Le {d1} {m1}, départ vers La Rochelle : 8 393 milles, {sea}. "
        f"Puis, le bateau passe près de l'aire marine protégée Pointe d'Arçay. "
        f"Arrivée à La Rochelle le {d2} {m2}."
    )


def leg17_raw_en(dep: datetime, arr: datetime, sea: str) -> str:
    return (
        f"On {en_day_month(dep)}, departure for La Rochelle: 8,393 miles, {sea}. "
        "Then, the boat passes near the Pointe d'Arçay marine protected area. "
        f"Arrival in La Rochelle on {en_day_month(arr)}."
    )


def leg0_raw_en(dep: datetime, arr: datetime, sea: str) -> str:
    return (
        f"The Berry-Mappemonde expedition left La Rochelle on {en_day_month(dep)}, heading southwest. "
        f"Departure for Ajaccio (Corsica): 1,819 miles, {sea}. "
        f"Arrival at Ajaccio (Corsica) on {en_day_month(arr)}."
    )


def halifax_anchors(leg: dict, dep: str, arr: str) -> list[dict]:
    leg_id = leg.get("id") or ""
    text = leg.get("text") or ""
    dep_m, arr_m = parse_iso(dep), parse_iso(arr)
    if leg_id == "leg-6":
        return [{"charIdx": 0, "t": iso_z(dep_m), "kind": "depart"}]
    if leg_id == "leg-9":
        return [{"charIdx": 0, "t": iso_z(dep_m), "kind": "depart"}]
    escale_idx = text.find("Arrivée") if "Arrivée" in text else text.find("Arrival")
    if escale_idx < 0:
        escale_idx = max(len(text) - 40, 1)
    return [
        {"charIdx": 0, "t": iso_z(dep_m), "kind": "depart"},
        {"charIdx": escale_idx, "t": iso_z(arr_m), "place": leg.get("toName") or "", "kind": "escale"},
    ]


def minimal_anchors(leg: dict, dep: str, arr: str) -> list[dict]:
    leg_id = leg.get("id") or ""
    if leg_id in {"leg-6", "leg-7", "leg-8", "leg-9"}:
        return halifax_anchors(leg, dep, arr)
    dep_m = parse_iso(dep)
    arr_m = parse_iso(arr)
    text = leg.get("text") or ""
    escale_idx = text.find("Arrivée") if "Arrivée" in text else text.find("Arrival")
    if escale_idx < 0:
        escale_idx = max(len(text) - 40, 1)
    return [
        {"charIdx": 0, "t": iso_z(dep_m), "kind": "depart"},
        {"charIdx": escale_idx, "t": iso_z(arr_m), "place": leg.get("toName") or "", "kind": "escale"},
    ]


def apply_leg(
    leg: dict,
    bounds: tuple[str, str, str, str],
    *,
    lang: str,
    integral: bool,
) -> None:
    t_a, t_b, dep, arr = bounds
    t_a, t_b = iso_z(parse_iso(t_a)), iso_z(parse_iso(t_b))
    dep, arr = iso_z(parse_iso(dep)), iso_z(parse_iso(arr))
    leg["tA"], leg["tB"] = t_a, t_b
    sea_days = leg_days(dep, arr)
    sea = spoken_sea_days(sea_days, lang)
    dep_dt, arr_dt = parse_iso(dep), parse_iso(arr)
    leg_id = leg.get("id") or ""

    if leg_id == "leg-0":
        if not integral:
            leg["text"] = leg0_raw_fr(dep_dt, arr_dt, sea) if lang == "fr" else leg0_raw_en(dep_dt, arr_dt, sea)
        elif lang == "fr":
            d1, m1 = fr_day_month(dep_dt)
            d2, m2 = fr_day_month(arr_dt)
            leg["text"] = (
                f"L'expédition Berry-Mappemonde a quitté La Rochelle le {d1} {m1}, cap au sud-ouest. "
                f"Départ vers Ajaccio (Corse) : 1 819 milles, {sea}. "
                f"Arrivée à Ajaccio (Corse) le {d2} {m2}, amarré au port d'Ajaccio (Corse). Trois jours d'escale."
            )
        else:
            leg["text"] = (
                f"The Berry-Mappemonde expedition left La Rochelle on {en_day_month(dep_dt)}, heading southwest. "
                f"Departure for Ajaccio (Corsica): 1,819 miles, {sea}. "
                f"Arrival at Ajaccio (Corsica) on {en_day_month(arr_dt)}, moored at Ajaccio (Corsica) marina. "
                "Three days' stopover."
            )
    elif leg_id in RAW_HALIFAX_FR:
        # Halifax ↔ Saint-Pierre: the sea days are the passage's own window in the schedule
        # (NAVIGUIDE's _side_hop_metrics caps them the same way), never the template's count.
        if not integral:
            template, text_lang = RAW_HALIFAX_FR[leg_id], "fr"
        elif lang == "fr":
            template, text_lang = INTEGRAL_HALIFAX_FR[leg_id], "fr"
        else:
            template, text_lang = INTEGRAL_HALIFAX_EN[leg_id], "en"
        template = replace_sea_days_in_text(template, sea, en=text_lang == "en")
        leg["text"] = patch_halifax_text(template, parse_iso(t_a), parse_iso(t_b), lang=text_lang)
    elif leg_id == "leg-10" and not integral and lang == "fr":
        text = RAW_LEG10_FR
        text = replace_sea_days_in_text(text, sea, en=False)
        leg["text"] = patch_halifax_text(text, dep_dt, arr_dt, lang="fr")
    elif leg_id == "leg-10" and integral:
        base = INTEGRAL_LEG10_FR if lang == "fr" else INTEGRAL_LEG10_EN
        text = replace_sea_days_in_text(base, sea, en=lang == "en")
        leg["text"] = scrub_integral_dates(text, dep_dt, arr_dt, lang=lang, leg_id=leg_id)
    elif leg_id == "leg-17" and not integral:
        leg["text"] = leg17_raw_fr(dep_dt, arr_dt, sea) if lang == "fr" else leg17_raw_en(dep_dt, arr_dt, sea)
    elif leg_id == "leg-17" and integral:
        leg["text"] = leg17_integral_text(leg, dep_dt, arr_dt, sea, lang=lang)
    elif leg_id in {"leg-14", "leg-15", "leg-16"} and not integral and lang == "fr":
        to_n = leg.get("toName") or ""
        d1, m1 = fr_day_month(dep_dt)
        d2, m2 = fr_day_month(arr_dt)
        leg["text"] = (
            f"Le {d1} {m1}, départ vers {to_n.split('(')[0].strip()} : "
            f"{sea}. Arrivée à {to_n} le {d2} {m2}."
        )
    elif leg_id in {"leg-14", "leg-15", "leg-16"} and not integral and lang == "en":
        to_n = leg.get("toName") or ""
        leg["text"] = (
            f"On {en_day_month(dep_dt)}, departure for {to_n}: {sea}. "
            f"Arrival at {to_n} on {en_day_month(arr_dt)}."
        )
    else:
        text = leg.get("text") or ""
        text = replace_sea_days_in_text(text, sea, en=lang == "en")
        if lang == "fr":
            text = patch_dates_fr(text, dep_dt, arr_dt)
            if integral and leg_id == "leg-16" and "port d'" not in text and "Europa" in text:
                text = text.replace("amarré au port de Europa", "amarré au port d'Europa")
        else:
            text = patch_dates_en(text, dep_dt, arr_dt)
        if integral and leg_id in {f"leg-{n}" for n in range(1, 13)}:
            text = scrub_integral_dates(text, dep_dt, arr_dt, lang=lang, leg_id=leg_id)
        leg["text"] = text

    anchor_dep = t_a if leg_id in {"leg-6", "leg-7", "leg-8", "leg-9"} else dep
    anchor_arr = t_b if leg_id in {"leg-7", "leg-8"} else arr
    leg["anchors"] = minimal_anchors(leg, anchor_dep, anchor_arr)


def main() -> None:
    cabin = json.loads(CABIN.read_text(encoding="utf-8"))
    bounds = film_leg_bounds(cabin)

    raw = json.loads(RAW.read_text(encoding="utf-8"))
    for leg in raw["chapters"]:
        fid = leg.get("id")
        if fid in bounds:
            apply_leg(leg, bounds[fid], lang="fr", integral=False)
    RAW.write_text(json.dumps(raw, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

    integral = json.loads(INTEGRAL.read_text(encoding="utf-8"))
    raw_by = {c["id"]: c for c in raw["chapters"]}
    for lang in ("fr", "en"):
        for leg in integral[lang]["chapters"]:
            fid = leg.get("id")
            if fid in bounds:
                apply_leg(leg, bounds[fid], lang=lang, integral=True)
                leg["anchors"] = json.loads(json.dumps(raw_by[fid]["anchors"]))
    INTEGRAL.write_text(json.dumps(integral, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

    print("Regenerated film legs 0–17 from cabin_legs.json")
    for fid in sorted(bounds.keys(), key=lambda x: int(x.split("-")[1])):
        t_a, t_b, dep, arr = bounds[fid]
        print(
            fid,
            "tA",
            t_a[:10],
            "tB",
            t_b[:10],
            "sea",
            f"{leg_days(dep, arr):.1f}d",
            spoken_sea_days(leg_days(dep, arr), "fr"),
        )


if __name__ == "__main__":
    main()
