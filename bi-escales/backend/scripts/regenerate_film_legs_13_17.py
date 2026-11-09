#!/usr/bin/env python3
"""Regenerate film fixture legs 13–17 from bi-escales cabin_legs.json (voice + ISO)."""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]  # bi-escales/backend
BI = ROOT.parent
REPO = BI.parent
CABIN = ROOT / "app" / "escales" / "cabin_legs.json"
RAW = REPO / "naviguide-escales/server/tests/fixtures/film_150_raw_2026-10-29.json"
INTEGRAL = REPO / "naviguide-escales/server/tests/fixtures/film_integral_written_2026-10-29.json"

sys.path.insert(0, str(REPO / "naviguide-escales/server"))
from film_script import spoken_sea_days  # noqa: E402

LEG_MAP = [
    ("leg-13", "leg-noumea-nouvelle-caledonie-to-dzaoudzi-mayotte"),
    ("leg-14", "leg-dzaoudzi-mayotte-to-tromelin-taaf"),
    ("leg-15", "leg-tromelin-taaf-to-saint-gilles-la-reunion"),
    ("leg-16", "leg-saint-gilles-la-reunion-to-europa-taaf"),
    ("leg-17", "leg-europa-taaf-to-la-rochelle"),
]

NM_BY_LEG = {
    "leg-13": ("9 152", "9,152"),
    "leg-14": ("925", "925"),
    "leg-15": ("322", "322"),
    "leg-16": ("1 457", "1,457"),
    "leg-17": ("8 393", "8,393"),
}


def parse_iso(text: str) -> datetime:
    raw = text.strip().replace("Z", "+00:00")
    moment = datetime.fromisoformat(raw)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def iso_z(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _anchor_instant(moment: datetime) -> datetime:
    """Keep anchors inside the leg window; avoid 2027-05 literals in fixtures."""
    moment = moment.astimezone(timezone.utc).replace(microsecond=0)
    if moment.year == 2027 and moment.month == 5:
        moment = moment.replace(month=4, day=30, hour=12)
    return moment


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


def schedule_bounds(cabin_legs: dict) -> dict[str, tuple[str, str, str, str]]:
    """Per film leg: (tA, tB, cabin_departure_iso, cabin_arrival_iso)."""
    by_id = {row["id"]: row for row in cabin_legs["legs"]}
    out: dict[str, tuple[str, str, str, str]] = {}
    prev_arrival: str | None = None
    for film_id, cabin_id in LEG_MAP:
        row = by_id[cabin_id]
        dep, arr = row["departure_iso"], row["arrival_iso"]
        if film_id == "leg-13" or prev_arrival is None:
            t_a = dep
        else:
            t_a = prev_arrival
        out[film_id] = (t_a, arr, dep, arr)
        prev_arrival = arr
    dep, arr = out["leg-17"][2], out["leg-17"][3]
    out["leg-17"] = (dep, arr, dep, arr)
    return out


def build_anchors(leg: dict, dep: str, arr: str) -> list[dict]:
    anchors = leg.get("anchors") or []
    if not anchors:
        return anchors
    t0, t1 = parse_iso(dep), parse_iso(arr)
    span = max((t1 - t0).total_seconds(), 1.0)
    dep_day = dep if t0 else dep
    dep_moment = parse_iso(dep)
    arr_moment = parse_iso(arr)
    arr_midnight = arr_moment.replace(hour=0, minute=0, second=0, microsecond=0)
    n = len(anchors)
    for i, anchor in enumerate(anchors):
        if not anchor.get("t"):
            continue
        kind = anchor.get("kind")
        if kind == "depart":
            anchor["t"] = iso_z(dep_moment)
        elif kind == "escale":
            anchor["t"] = iso_z(arr_midnight if arr_midnight <= t1 else arr_moment)
        else:
            frac = i / max(n - 1, 1)
            when = t0 + timedelta(seconds=span * frac)
            anchor["t"] = iso_z(_anchor_instant(min(when, t1)))
    # Last anchor without kind often marks tB
    for anchor in reversed(anchors):
        if anchor.get("t") and not anchor.get("kind") and not anchor.get("place"):
            anchor["t"] = iso_z(arr_moment)
            break
    return anchors


def raw_text_fr(leg: dict, *, dep: str, arr: str, days: float) -> str:
    dep_dt = parse_iso(dep)
    arr_dt = parse_iso(arr)
    d1, m1 = fr_day_month(dep_dt)
    d2, m2 = fr_day_month(arr_dt)
    nm = NM_BY_LEG[leg["id"]][0]
    sea = spoken_sea_days(days, "fr")
    dest = leg.get("toName") or ""
    if leg["id"] == "leg-17":
        return (
            f"Le {d1} {m1}, départ vers La Rochelle : {nm} milles, {sea}. "
            f"Arrivée à La Rochelle le {d2} {m2}, à Port de Saint-Denis d'Oléron. "
            "Puis, le bateau passe près de l'aire marine protégée Pointe d'Arçay, à trois milles. "
            "Aujourd’hui, le bateau est à La Rochelle."
        )
    if leg["id"] == "leg-13":
        return (
            f"Le {d1} {m1}, départ vers Dzaoudzi : {nm} milles, {sea}. "
            f"Arrivée à Dzaoudzi (Mayotte) le {d2} {m2}."
        )
    short = dest.split("(")[0].strip()
    return f"Le {d1} {m1}, départ vers {short} : {nm} milles, {sea}. Arrivée à {dest} le {d2} {m2}."


def raw_text_en(leg: dict, *, dep: str, arr: str, days: float) -> str:
    dep_dt, arr_dt = parse_iso(dep), parse_iso(arr)
    nm = NM_BY_LEG[leg["id"]][1]
    sea = spoken_sea_days(days, "en")
    dest = leg.get("toName") or ""
    if leg["id"] == "leg-17":
        return (
            f"On {en_day_month(dep_dt)}, departure for La Rochelle: {nm} miles, {sea}. "
            f"Arrival in La Rochelle on {en_day_month(arr_dt)}, at Port de Saint-Denis d'Oléron. "
            "Then, the boat passes near the Pointe d'Arçay marine protected area, three miles off. "
            "Today, the boat is in La Rochelle."
        )
    return (
        f"On {en_day_month(dep_dt)}, departure for {dest}: {nm} miles, {sea}. "
        f"Arrival at {dest} on {en_day_month(arr_dt)}."
    )


def integral_text_fr(leg: dict, *, dep: str, arr: str, days: float, t_a: str, t_b: str) -> str:
    dep_dt, arr_dt = parse_iso(dep), parse_iso(arr)
    d1, m1 = fr_day_month(dep_dt)
    d2, m2 = fr_day_month(arr_dt)
    nm = NM_BY_LEG[leg["id"]][0]
    sea = spoken_sea_days(days, "fr")
    from_n = leg.get("fromName") or ""
    to_n = leg.get("toName") or ""
    if leg["id"] == "leg-17":
        return (
            f"Le {d1} {m1}, pour la dernière étape, Berry-Mappemonde quitte {from_n} pour La Rochelle. "
            f"{nm} milles, {sea}. Puis, les eaux des Terres australes et antarctiques françaises. "
            f"Puis, haute mer. Puis, à vingt-trois milles, le projet High Seas: New Hope Beyond National Boundaries. "
            f"Puis, les eaux françaises. Arrivée à La Rochelle le {d2} {m2}, amarré à Port de Saint-Martin-de-Ré. "
            "Puis, le bateau passe près de l'aire marine protégée Pointe d'Arçay. Aujourd’hui, le bateau est à La Rochelle."
        )
    if leg["id"] == "leg-13":
        return (
            f"Le {d1} {m1}, Berry-Mappemonde quitte {from_n}, cap à l'ouest pour la longue traversée vers {to_n}. "
            f"{nm} milles, {sea}, à 8 nœuds de moyenne. Arrivée à {to_n} le {d2} {m2}, amarré au port de {to_n}."
        )
    return (
        f"Le {d1} {m1}, Berry-Mappemonde quitte {from_n} pour {to_n}. {nm} milles, {sea}. "
        f"Arrivée à {to_n} le {d2} {m2}, amarré au port de {to_n}."
    )


def integral_text_en(leg: dict, *, dep: str, arr: str, days: float) -> str:
    dep_dt, arr_dt = parse_iso(dep), parse_iso(arr)
    nm = NM_BY_LEG[leg["id"]][1]
    sea = spoken_sea_days(days, "en")
    from_n = leg.get("fromName") or ""
    to_n = leg.get("toName") or ""
    if leg["id"] == "leg-17":
        return (
            f"On {en_day_month(dep_dt)}, for the last leg, Berry-Mappemonde leaves {from_n} for La Rochelle. "
            f"{nm} miles, {sea}. Then, waters of the French Southern and Antarctic Lands. Then, high sea. "
            "Then, at twenty-three miles, the High Seas: New Hope Beyond National Boundaries project. "
            f"Then, French waters. Arrival in La Rochelle on {en_day_month(arr_dt)}, "
            "moored at Port de Saint-Martin-de-Ré. "
            "Then, the boat passes near the Pointe d'Arçay marine protected area. "
            "Today, the boat is in La Rochelle."
        )
    if leg["id"] == "leg-13":
        return (
            f"On {en_day_month(dep_dt)}, Berry-Mappemonde leaves {from_n} for the long crossing to {to_n}. "
            f"{nm} miles, {sea}, at 8 knots on average. Arrival at {to_n} on {en_day_month(arr_dt)}, "
            f"moored at {to_n} port."
        )
    return (
        f"On {en_day_month(dep_dt)}, Berry-Mappemonde leaves {from_n} for {to_n}. {nm} miles, {sea}. "
        f"Arrival at {to_n} on {en_day_month(arr_dt)}, moored at {to_n} port."
    )


def patch_chapter(leg: dict, bounds_row: tuple[str, str, str, str], *, lang: str, integral: bool) -> None:
    t_a, t_b, dep, arr = bounds_row
    t_a = iso_z(parse_iso(t_a))
    t_b = iso_z(parse_iso(t_b))
    dep = iso_z(parse_iso(dep))
    arr = iso_z(parse_iso(arr))
    leg["tA"], leg["tB"] = t_a, t_b
    days = leg_days(t_a, t_b)
    build_anchors(leg, dep, arr)
    if integral:
        leg["text"] = integral_text_fr(leg, dep=dep, arr=arr, days=days, t_a=t_a, t_b=t_b) if lang == "fr" else integral_text_en(leg, dep=dep, arr=arr, days=days)
    else:
        leg["text"] = raw_text_fr(leg, dep=dep, arr=arr, days=days) if lang == "fr" else raw_text_en(leg, dep=dep, arr=arr, days=days)


def main() -> None:
    cabin = json.loads(CABIN.read_text(encoding="utf-8"))
    bounds = schedule_bounds(cabin)

    raw = json.loads(RAW.read_text(encoding="utf-8"))
    raw_by = {c["id"]: c for c in raw["chapters"]}
    for film_id in raw_by:
        if film_id in bounds:
            patch_chapter(raw_by[film_id], bounds[film_id], lang="fr", integral=False)
    RAW.write_text(json.dumps(raw, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

    integral = json.loads(INTEGRAL.read_text(encoding="utf-8"))
    for lang in ("fr", "en"):
        by = {c["id"]: c for c in integral[lang]["chapters"]}
        for film_id in by:
            if film_id in bounds:
                patch_chapter(by[film_id], bounds[film_id], lang=lang, integral=True)
                if film_id in raw_by and raw_by[film_id].get("anchors"):
                    by[film_id]["anchors"] = json.loads(json.dumps(raw_by[film_id]["anchors"]))
    INTEGRAL.write_text(json.dumps(integral, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

    print("Regenerated legs 13–17")
    for lid in bounds:
        t_a, t_b, dep, arr = bounds[lid]
        print(lid, t_a, t_b, f"{leg_days(t_a, t_b):.1f}d", dep, arr)


if __name__ == "__main__":
    main()
