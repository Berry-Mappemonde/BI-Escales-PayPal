"""Film leg ISO bounds derived from cabin_legs.json (shared by tests and regenerate script)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

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

# Narrative Cayenne→Halifax→Cayenne slice proportions (commit 376656f), not equal 18 h quarters.
_HALIFAX_REF: list[tuple[str, str, str]] = [
    ("leg-6", "2026-08-15T20:20:47Z", "2026-08-19T04:28:25Z"),
    ("leg-7", "2026-08-19T04:28:25Z", "2026-08-21T18:34:56Z"),
    ("leg-8", "2026-08-21T18:34:56Z", "2026-08-28T20:31:05Z"),
    ("leg-9", "2026-08-28T20:31:05Z", "2026-08-29T04:31:05Z"),
]


def _parse_iso(text: str) -> datetime:
    raw = text.strip().replace("Z", "+00:00")
    moment = datetime.fromisoformat(raw)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def _iso_z(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def halifax_hold_bounds(cayenne_arr: str, cayenne_dep: str) -> dict[str, tuple[str, str]]:
    hold_start = _parse_iso(cayenne_arr)
    hold_end = _parse_iso(cayenne_dep)
    ref_start = _parse_iso(_HALIFAX_REF[0][1])
    ref_end = _parse_iso(_HALIFAX_REF[-1][2])
    ref_span = max((ref_end - ref_start).total_seconds(), 1.0)
    hold_span = max((hold_end - hold_start).total_seconds(), 1.0)
    out: dict[str, tuple[str, str]] = {}
    for leg_id, ref_a, ref_b in _HALIFAX_REF:
        a = _parse_iso(ref_a)
        b = _parse_iso(ref_b)
        f0 = (a - ref_start).total_seconds() / ref_span
        f1 = (b - ref_start).total_seconds() / ref_span
        t_a = hold_start + timedelta(seconds=hold_span * f0)
        t_b = hold_start + timedelta(seconds=hold_span * f1)
        out[leg_id] = (_iso_z(t_a), _iso_z(t_b))
    return out


def film_leg_bounds(cabin: dict) -> dict[str, tuple[str, str, str, str]]:
    """Film leg -> (tA, tB, sea_departure_iso, sea_arrival_iso)."""
    by = {row["id"]: row for row in cabin["legs"]}
    out: dict[str, tuple[str, str, str, str]] = {}
    prev_t_b: str | None = None
    cayenne_arr = by["leg-marigot-saint-martin-to-cayenne-guyane"]["arrival_iso"]
    cayenne_dep = by["leg-cayenne-guyane-to-papeete-polynesie-francaise"]["departure_iso"]
    halifax = halifax_hold_bounds(cayenne_arr, cayenne_dep)

    for film_id in [f"leg-{i}" for i in range(18)]:
        if film_id in halifax:
            t_a, t_b = halifax[film_id]
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


def fixture_tb_matches_cabin(cabin: dict) -> dict[str, tuple[str, str]]:
    """Expected (tA, tB) per film leg for fixture assertions (no sea dep override)."""
    bounds = film_leg_bounds(cabin)
    return {leg_id: (b[0], b[1]) for leg_id, b in bounds.items()}
