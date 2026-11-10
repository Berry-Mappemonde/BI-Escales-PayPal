#!/usr/bin/env python3
"""Re-time film fixture legs 0–17 from bi-escales/app/escales/cabin_legs.json."""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent.parent
CABIN = ROOT / "app" / "escales" / "cabin_legs.json"
RAW = REPO / "naviguide-escales/server/tests/fixtures/film_150_raw_2026-10-29.json"
INTEGRAL = REPO / "naviguide-escales/server/tests/fixtures/film_integral_written_2026-10-29.json"

sys.path.insert(0, str(REPO / "naviguide-escales/server"))
from film_script import spoken_sea_days  # noqa: E402

# Film leg -> cabin leg id (None = synthetic slice between two cabin instants)
FILM_CABIN: dict[str, str | None] = {
    "leg-0": "leg-la-rochelle-to-ajaccio-corse",
    "leg-1": "leg-ajaccio-corse-to-fort-de-france-martinique",
    "leg-2": "leg-fort-de-france-martinique-to-pointe-a-pitre-guadeloupe",
    "leg-3": "leg-pointe-a-pitre-guadeloupe-to-gustavia-saint-barthelemy",
    "leg-4": "leg-gustavia-saint-barthelemy-to-marigot-saint-martin",
    "leg-5": "leg-marigot-saint-martin-to-cayenne-guyane",
    "leg-6": None,
    "leg-7": None,
    "leg-8": None,
    "leg-9": None,
    "leg-10": "leg-cayenne-guyane-to-papeete-polynesie-francaise",
    "leg-11": "leg-papeete-polynesie-francaise-to-mata-utu-wallis-et-futuna",
    "leg-12": "leg-mata-utu-wallis-et-futuna-to-noumea-nouvelle-caledonie",
    "leg-13": "leg-noumea-nouvelle-caledonie-to-dzaoudzi-mayotte",
    "leg-14": "leg-dzaoudzi-mayotte-to-tromelin-taaf",
    "leg-15": "leg-tromelin-taaf-to-saint-gilles-la-reunion",
    "leg-16": "leg-saint-gilles-la-reunion-to-europa-taaf",
    "leg-17": "leg-europa-taaf-to-la-rochelle",
}


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
    months = [
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
    ]
    day = "1er" if dt.day == 1 else str(dt.day)
    return day, months[dt.month - 1]


def en_day_month(dt: datetime) -> str:
    months = [
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
    ]
    return f"{months[dt.month - 1]} {dt.day}"


def cabin_by_id(data: dict) -> dict[str, dict]:
    return {row["id"]: row for row in data["legs"]}


def schedule_all(cabin: dict) -> dict[str, tuple[str, str, str, str]]:
    """Return film leg -> (tA, tB, sea_departure_iso, sea_arrival_iso)."""
    by = cabin_by_id(cabin)
    out: dict[str, tuple[str, str, str, str]] = {}
    prev_t_b: str | None = None
    cayenne_arr = by["leg-marigot-saint-martin-to-cayenne-guyane"]["arrival_iso"]
    cayenne_dep = by["leg-cayenne-guyane-to-papeete-polynesie-francaise"]["departure_iso"]
    halifax_start = parse_iso(cayenne_arr)
    halifax_end = parse_iso(cayenne_dep)
    halifax_span = max((halifax_end - halifax_start).total_seconds(), 1.0)

    for film_id in [f"leg-{i}" for i in range(18)]:
        if film_id in {"leg-6", "leg-7", "leg-8", "leg-9"}:
            idx = int(film_id.split("-")[1]) - 6
            frac0, frac1 = idx / 4, (idx + 1) / 4
            t_a = iso_z(halifax_start + timedelta(seconds=halifax_span * frac0))
            t_b = iso_z(halifax_start + timedelta(seconds=halifax_span * frac1))
            out[film_id] = (t_a, t_b, t_a, t_b)
            prev_t_b = t_b
            continue
        cabin_id = FILM_CABIN.get(film_id)
        if not cabin_id:
            continue
        row = by[cabin_id]
        dep, arr = row["departure_iso"], row["arrival_iso"]
        if film_id in {"leg-0", "leg-17"}:
            t_a = dep
        elif prev_t_b:
            t_a = prev_t_b
        else:
            t_a = dep
        out[film_id] = (t_a, arr, dep, arr)
        prev_t_b = arr
    return out


def minimal_anchors(leg: dict, dep: str, arr: str) -> list[dict]:
    """Keep only depart + escale; leg-17 adds alert-on at approach (near arrival)."""
    dep_m = parse_iso(dep)
    arr_m = parse_iso(arr)
    anchors: list[dict] = [
        {"charIdx": 0, "t": iso_z(dep_m), "kind": "depart"},
        {
            "charIdx": max(len(leg.get("text") or "") - 40, 1),
            "t": iso_z(arr_m),
            "place": leg.get("toName") or "",
            "kind": "escale",
        },
    ]
    if leg.get("id") == "leg-17":
        approach = arr_m - timedelta(days=1)
        anchors.insert(
            1,
            {
                "charIdx": 80,
                "t": iso_z(approach),
                "place": "Pointe d'Arçay",
                "kind": "alert-on",
            },
        )
    return anchors


def replace_sea_days_in_text(text: str, sea: str, *, en: bool) -> str:
    if en:
        text = re.sub(
            r"(?i)(about (?:ten|fifteen|twenty|thirty|forty) days at sea|"
            r"less than a day at sea|one day at sea|"
            r"\d+ days at sea|"
            r"(?:one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|"
            r"thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty) days at sea)",
            sea,
            text,
            count=1,
        )
        text = re.sub(r"(?i)\d+ days at sea", sea, text, count=1)
    else:
        cardinals = (
            "moins d'un|un|une dizaine|une quinzaine|une vingtaine|une trentaine|une quarantaine|"
            "deux|trois|quatre|cinq|six|sept|huit|neuf|dix|onze|douze|treize|quatorze|quinze|"
            "seize|dix-sept|dix-huit|dix-neuf|vingt|\\d+"
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


def leg17_raw_fr(dep: datetime, arr: datetime, sea: str) -> str:
    d1, m1 = fr_day_month(dep)
    d2, m2 = fr_day_month(arr)
    return (
        f"Le {d1} {m1}, départ vers La Rochelle : 8 393 milles, {sea}. "
        f"Arrivée à La Rochelle le {d2} {m2}. "
        "Puis, le bateau passe près de l'aire marine protégée Pointe d'Arçay."
    )


def leg17_raw_en(dep: datetime, arr: datetime, sea: str) -> str:
    return (
        f"On {en_day_month(dep)}, departure for La Rochelle: 8,393 miles, {sea}. "
        f"Arrival in La Rochelle on {en_day_month(arr)}. "
        "Then, the boat passes near the Pointe d'Arçay marine protected area."
    )


def leg0_raw_fr(dep: datetime, arr: datetime, sea: str) -> str:
    d1, m1 = fr_day_month(dep)
    d2, m2 = fr_day_month(arr)
    return (
        f"L’expédition Berry-Mappemonde a quitté La Rochelle le {d1} {m1}, cap au sud-ouest. "
        f"Départ vers Ajaccio : 1 819 milles, {sea}. Arrivée à Ajaccio (Corse) le {d2} {m2}."
    )


def leg0_raw_en(dep: datetime, arr: datetime, sea: str) -> str:
    return (
        f"The Berry-Mappemonde expedition left La Rochelle on {en_day_month(dep)}, heading southwest. "
        f"Departure for Ajaccio (Corsica): 1,819 miles, {sea}. "
        f"Arrival at Ajaccio (Corsica) on {en_day_month(arr)}."
    )


def apply_leg(
    leg: dict,
    bounds: tuple[str, str, str, str],
    *,
    lang: str,
    integral: bool,
    rewrite_opening: bool = False,
) -> None:
    t_a, t_b, dep, arr = bounds
    t_a, t_b, dep, arr = iso_z(parse_iso(t_a)), iso_z(parse_iso(t_b)), iso_z(parse_iso(dep)), iso_z(parse_iso(arr))
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
                f"L’expédition Berry-Mappemonde a quitté La Rochelle le {d1} {m1}, cap au sud-ouest. "
                f"Départ vers Ajaccio (Corse) : 1 819 milles, {sea}. "
                f"Arrivée à Ajaccio (Corse) le {d2} {m2}, amarré au port d’Ajaccio (Corse). Trois jours d'escale."
            )
        else:
            leg["text"] = (
                f"The Berry-Mappemonde expedition left La Rochelle on {en_day_month(dep_dt)}, heading southwest. "
                f"Departure for Ajaccio (Corsica): 1,819 miles, {sea}. "
                f"Arrival at Ajaccio (Corsica) on {en_day_month(arr_dt)}, moored at Ajaccio (Corsica) marina. "
                "Three days' stopover."
            )
    elif leg_id == "leg-17" and not integral:
        leg["text"] = leg17_raw_fr(dep_dt, arr_dt, sea) if lang == "fr" else leg17_raw_en(dep_dt, arr_dt, sea)
    elif integral and leg_id == "leg-17":
        from_n = leg.get("fromName") or "Europa (TAAF)"
        d1, m1 = fr_day_month(dep_dt)
        d2, m2 = fr_day_month(arr_dt)
        if lang == "fr":
            leg["text"] = (
                f"Le {d1} {m1}, pour la dernière étape, Berry-Mappemonde quitte {from_n} pour La Rochelle. "
                f"8 393 milles, {sea}. Puis, les eaux des Terres australes et antarctiques françaises. "
                f"Puis, haute mer. Puis, à vingt-trois milles, le projet High Seas: New Hope Beyond National Boundaries. "
                f"Puis, les eaux françaises. "
                f"Arrivée à La Rochelle le {d2} {m2}, amarré à Port de Saint-Martin-de-Ré, "
                "près de l'aire marine protégée Pointe d'Arçay. "
                "Puis, le bateau passe près de l'aire marine protégée Pointe d'Arçay. "
                "Aujourd’hui, le bateau est à La Rochelle."
            )
        else:
            leg["text"] = (
                f"On {en_day_month(dep_dt)}, for the last leg, Berry-Mappemonde leaves {from_n} for La Rochelle. "
                f"8,393 miles, {sea}. Then, waters of the French Southern and Antarctic Lands. Then, high sea. "
                "Then, at twenty-three miles, the High Seas: New Hope Beyond National Boundaries project. "
                f"Then, French waters. Arrival in La Rochelle on {en_day_month(arr_dt)}, "
                "moored at Port de Saint-Martin-de-Ré, near the Pointe d'Arçay marine protected area. "
                "Then, the boat passes near the Pointe d'Arçay marine protected area. "
                "Today, the boat is in La Rochelle."
            )
    elif leg_id == "leg-6" and not integral:
        d1, m1 = fr_day_month(dep_dt)
        text = leg.get("text") or ""
        text = re.sub(r"\bLe (\d+|1er) [\wéû]+", f"Le {d1} {m1}", text, count=1)
        leg["text"] = text
    elif leg_id in {"leg-7", "leg-8", "leg-9", "leg-10"} and not integral:
        to_n = leg.get("toName") or ""
        d1, m1 = fr_day_month(dep_dt)
        d2, m2 = fr_day_month(arr_dt)
        if lang == "fr":
            leg["text"] = (
                f"Le {d1} {m1}, départ vers {to_n.split('(')[0].strip()} : "
                f"{sea}. Arrivée à {to_n} le {d2} {m2}."
            )
        else:
            leg["text"] = (
                f"On {en_day_month(dep_dt)}, departure for {to_n}: {sea}. "
                f"Arrival at {to_n} on {en_day_month(arr_dt)}."
            )
    elif leg_id in {"leg-14", "leg-15", "leg-16"} and not integral:
        to_n = leg.get("toName") or ""
        from_n = leg.get("fromName") or ""
        d1, m1 = fr_day_month(dep_dt)
        d2, m2 = fr_day_month(arr_dt)
        if lang == "fr":
            leg["text"] = (
                f"Le {d1} {m1}, départ vers {to_n.split('(')[0].strip()} : "
                f"{sea}. Arrivée à {to_n} le {d2} {m2}."
            )
        else:
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
                text = text.replace("au port de Europa", "au port d'Europa")
        else:
            text = patch_dates_en(text, dep_dt, arr_dt)
            if integral and leg_id == "leg-13" and "New Caledonia" not in text:
                text = text.replace("Nouvelle-Calédonie", "New Caledonia")
        leg["text"] = text

    leg["anchors"] = minimal_anchors(leg, dep, arr)


def main() -> None:
    cabin = json.loads(CABIN.read_text(encoding="utf-8"))
    bounds = schedule_all(cabin)

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
            "tA", t_a[:10],
            "tB", t_b[:10],
            "sea", f"{leg_days(dep, arr):.1f}d",
            spoken_sea_days(leg_days(dep, arr), "fr"),
        )


if __name__ == "__main__":
    main()
