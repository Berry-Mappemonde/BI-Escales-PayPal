#!/usr/bin/env python3
"""Cherche une date où la lecture du film dure entre 2:30 et 3:00.

Le temps de lecture suit le texte : caractères ÷ débit (15 car./s).
Couper une phrase ou fusionner des chapitres ne change pas cette horloge.
La dichotomie avance la date : un chapitre dont la fin est encore après
cette date est lu en entier, les autres sont déjà derrière. Le départ
officiel n'est pas modifié.

Sans argument, le script lit le film intégral déjà en stock et les escales
datées du voyage. Il n'écrit rien et n'appelle aucun modèle.

  python3 scripts/film_t0_search.py
  python3 scripts/film_t0_search.py --lang fr --json
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

# Fenêtre demandée, en secondes de lecture. Bornes incluses.
READING_LO_S = 150.0
READING_HI_S = 180.0
# Même débit que film_script.FILM_ESTIMATE_CPS. Le CLI le relit dans le module.
DEFAULT_CPS = 15.0
# Même écart que dated_marks : un second passage (Halifax, Saint-Pierre,
# Cayenne) à plus de 6 h est une autre escale, pas un doublon.
VISIT_GAP_MS = 6 * 3_600_000

_SIMULATOR = Path(__file__).resolve().parents[1]
_SERVER = _SIMULATOR / "server"


def parse_ms(iso: Any) -> int:
    """Millisecondes UTC. Refuse une date absente ou illisible."""
    if isinstance(iso, (int, float)) and not isinstance(iso, bool):
        return int(iso)
    text = str(iso or "").strip()
    if not text:
        raise ValueError("date absente")
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
    delta = dt - epoch
    return delta.days * 86_400_000 + delta.seconds * 1000 + delta.microseconds // 1000


def format_iso(ms: int) -> str:
    dt = datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc)
    if ms % 1000 == 0:
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{ms % 1000:03d}Z"


def clock_label(seconds: float) -> str:
    """Horloge m:ss, arrondie comme film_estimated_seconds."""
    whole = max(0, int(round(seconds)))
    return f"{whole // 60}:{whole % 60:02d}"


def _chapter(raw: dict) -> dict:
    text = str(raw.get("text") or "")
    t_a = parse_ms(raw.get("tA_ms", raw.get("tA")))
    t_b = parse_ms(raw.get("tB_ms", raw.get("tB")))
    return {
        "text": text,
        "chars": len(text),
        "tA_ms": t_a,
        "tB_ms": t_b,
        "tA": format_iso(t_a),
        "tB": format_iso(t_b),
        "fromName": str(raw.get("fromName") or ""),
        "toName": str(raw.get("toName") or ""),
    }


def _stop(raw: dict) -> dict:
    name = str(raw.get("name") or "").strip()
    if not name:
        raise ValueError("escale sans nom")
    ms = parse_ms(raw.get("ms", raw.get("iso")))
    return {"name": name, "iso": format_iso(ms), "ms": ms}


def chars_still_ahead(chapters: list[dict], t_ms: int) -> int:
    """Caractères des chapitres pas encore finis. Chacun est compté en entier."""
    return sum(ch["chars"] for ch in chapters if ch["tB_ms"] > t_ms)


def split_stops(stops: list[dict], t_ms: int) -> tuple[list[dict], list[dict]]:
    """Déjà passées : arrivée ≤ t0. Encore à venir : arrivée après t0."""
    passed = [s for s in stops if s["ms"] <= t_ms]
    upcoming = [s for s in stops if s["ms"] > t_ms]
    return passed, upcoming


def _public_stop(stop: dict) -> dict:
    return {"name": stop["name"], "iso": stop["iso"]}


def _public_chapter(ch: dict) -> dict:
    return {
        "fromName": ch["fromName"],
        "toName": ch["toName"],
        "tA": ch["tA"],
        "tB": ch["tB"],
        "chars": ch["chars"],
    }


def _first_t(lo: int, hi: int, pred: Callable[[int], bool], probes: list[int]) -> Optional[int]:
    """Plus petit instant de [lo, hi] où pred est vrai.

    pred est fausse puis vraie (la durée restante ne remonte pas).
    """
    def check(t: int) -> bool:
        probes[0] += 1
        return pred(t)

    if lo > hi:
        return None
    if not check(hi):
        return None
    if check(lo):
        return lo
    while lo < hi:
        mid = (lo + hi) // 2
        if check(mid):
            hi = mid
        else:
            lo = mid + 1
    return lo


def search_reading_t0(
    chapters: list[dict],
    stops: list[dict],
    *,
    lo_s: float = READING_LO_S,
    hi_s: float = READING_HI_S,
    cps: float = DEFAULT_CPS,
) -> Optional[dict]:
    """Dichotomie : plus petite date dont la lecture restante est dans [lo_s, hi_s].

    Retourne None si le texte entier est déjà trop court, ou si le passage
    sous hi_s tombe d'un coup sous lo_s (aucun instant dans la fenêtre).
    """
    if hi_s < lo_s:
        raise ValueError("fenêtre de lecture inversée")
    rate = float(cps)
    if rate <= 0:
        raise ValueError("débit nul")
    prepared = [_chapter(ch) for ch in chapters]
    if not prepared:
        return None
    dated = [_stop(s) for s in stops]
    left = min(ch["tA_ms"] for ch in prepared)
    right = max(ch["tB_ms"] for ch in prepared)

    def seconds_at(t_ms: int) -> float:
        return chars_still_ahead(prepared, t_ms) / rate

    probes = [0]
    # Premier instant où la lecture n'est plus au-dessus du plafond.
    enter = _first_t(left, right, lambda t: seconds_at(t) <= hi_s, probes)
    if enter is None:
        return None
    seconds = seconds_at(enter)
    if seconds < lo_s:
        return None
    # Dernier instant encore dans la fenêtre : 1 ms avant la chute sous le plancher.
    drop = _first_t(enter, right, lambda t: seconds_at(t) < lo_s, probes)
    until = right if drop is None else drop - 1
    passed, upcoming = split_stops(dated, enter)
    kept = [ch for ch in prepared if ch["tB_ms"] > enter]
    chars = sum(ch["chars"] for ch in kept)
    return {
        "t0": format_iso(enter),
        "t0Ms": enter,
        "until": format_iso(until),
        "untilMs": until,
        "seconds": chars / rate,
        "clock": clock_label(chars / rate),
        "chars": chars,
        "cps": rate,
        "probes": probes[0],
        "passed": [_public_stop(s) for s in passed],
        "upcoming": [_public_stop(s) for s in upcoming],
        "kept": [_public_chapter(ch) for ch in kept],
    }


def read_official_t0(server: Path = _SERVER) -> str:
    """Relit la constante dans le source. Ne l'assigne pas."""
    for line in (server / "voyage_clock.py").read_text(encoding="utf-8").splitlines():
        if line.startswith("OFFICIAL_T0 = "):
            return json.loads(line.split("=", 1)[1].strip())
    raise RuntimeError("OFFICIAL_T0 introuvable")


def integral_chapters(payload: dict, lang: str) -> list[dict]:
    variants = payload.get("variants") if isinstance(payload.get("variants"), dict) else {}
    by_lang = variants.get(lang) if isinstance(variants.get(lang), dict) else {}
    plan = by_lang.get("0")
    if not isinstance(plan, dict):
        plan = by_lang.get(0)
    if not isinstance(plan, dict):
        return []
    out: list[dict] = []
    for ch in plan.get("chapters") or []:
        if not isinstance(ch, dict) or not ch.get("tA") or not ch.get("tB"):
            continue
        out.append({
            "text": str(ch.get("text") or ""),
            "tA": ch.get("tA"),
            "tB": ch.get("tB"),
            "fromName": str(ch.get("fromName") or ""),
            "toName": str(ch.get("toName") or ""),
        })
    return out


def _film_payload(doc: dict) -> dict:
    payload = doc.get("payload") if isinstance(doc.get("payload"), dict) else doc
    return payload if isinstance(payload, dict) else {}


def find_film_json(explicit: Optional[str] = None) -> Path:
    if explicit:
        path = Path(explicit)
        if not path.is_file():
            raise FileNotFoundError(path)
        return path
    roots: list[Path] = []
    import os
    env = (os.environ.get("NAVIGUIDE_OFFICIAL_STORE_DIR") or "").strip()
    if env:
        roots.append(Path(env))
    roots.append(Path.home() / ".cache" / "naviguide" / "voyage-store")
    found: list[Path] = []
    for root in roots:
        if not root.is_dir():
            continue
        found.extend(p for p in root.glob("*/film.json") if p.is_file())
        direct = root / "film.json"
        if direct.is_file():
            found.append(direct)
    found.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    if not found:
        raise FileNotFoundError("film intégral introuvable dans le stock")
    return found[0]


def default_voyage_path() -> Path:
    return _SERVER / "voyage_data" / "voyage_berry-mappemonde-2026-officiel.json"


def _visit_key(name: str) -> str:
    """Clé des escales qui ont un aller et un retour."""
    folded = name.casefold()
    if "halifax" in folded:
        return "halifax"
    if "cayenne" in folded:
        return "cayenne"
    if "saint-pierre" in folded or "saint pierre" in folded:
        return "saint-pierre"
    return ""


def merge_clock_visits(
    base: list[dict],
    clock_marks: list[dict],
    route_marks: list[dict],
    same_stop: Callable[[str, str], bool],
) -> list[dict]:
    """Complète les escales datées avec un passage déjà écrit dans l'horloge.

    Halifax, Cayenne et Saint-Pierre ont un aller et un retour. La Rochelle
    aussi : le retour est un autre mille de la route. Une date d'horloge dont
    le mille ne correspond à aucune marque de la route (Mata-Utu recollé sur
    le retour atlantique) n'est pas ajoutée.
    """
    rows = [
        {"name": str(stop["name"]), "iso": str(stop["iso"])}
        for stop in base
        if isinstance(stop, dict) and stop.get("name") and stop.get("iso")
    ]

    def already(name: str, mark_ms: int) -> bool:
        for row in rows:
            if not same_stop(row["name"], name):
                continue
            if abs(parse_ms(row["iso"]) - mark_ms) < VISIT_GAP_MS:
                return True
        return False

    def matches_route(name: str, film: float) -> bool:
        for mark in route_marks:
            if not isinstance(mark, dict) or not same_stop(str(mark.get("name") or ""), name):
                continue
            raw = mark.get("filmNm") if mark.get("filmNm") is not None else mark.get("nm")
            try:
                other = float(raw)
            except (TypeError, ValueError):
                continue
            if abs(other - film) < 0.6:
                return True
        return False

    for mark in clock_marks:
        if not isinstance(mark, dict) or not mark.get("name") or not mark.get("iso"):
            continue
        name = str(mark["name"])
        try:
            mark_ms = parse_ms(mark["iso"])
            raw_film = mark.get("filmNm") if mark.get("filmNm") is not None else mark.get("nm")
            film = float(raw_film) if raw_film is not None else -1.0
        except (TypeError, ValueError):
            continue
        if not _visit_key(name) and not matches_route(name, film):
            continue
        if already(name, mark_ms):
            continue
        rows.append({"name": name, "iso": format_iso(mark_ms)})
    rows.sort(key=lambda row: parse_ms(row["iso"]))
    return rows


def load_dated_stops(voyage: dict) -> list[dict]:
    """Escales datées du voyage. Les dates viennent de l'horloge, pas d'une constante."""
    if str(_SERVER) not in sys.path:
        sys.path.insert(0, str(_SERVER))
    from film_script import official_dated_stops, same_stop  # noqa: PLC0415

    clock = voyage.get("clock") if isinstance(voyage.get("clock"), dict) else {}
    base = official_dated_stops(voyage.get("marks") or [], clock)
    return merge_clock_visits(
        base,
        list(clock.get("marks") or []),
        list(voyage.get("marks") or []),
        same_stop,
    )


def reading_at(chapters: list[dict], t_ms: int, cps: float) -> dict:
    prepared = [_chapter(ch) for ch in chapters]
    kept = [ch for ch in prepared if ch["tB_ms"] > t_ms]
    chars = sum(ch["chars"] for ch in kept)
    full = sum(ch["chars"] for ch in prepared)
    return {
        "chars": chars,
        "seconds": (chars / cps) if cps else 0.0,
        "clock": clock_label(chars / cps) if cps and chars else "0:00",
        "fullChars": full,
        "fullSeconds": (full / cps) if cps else 0.0,
        "chaptersKept": len(kept),
        "chaptersTotal": len(prepared),
    }


def _summary(payload: dict) -> str:
    passed = ", ".join(f"{s['name']} ({s['iso']})" for s in payload["passed"]) or "—"
    upcoming = ", ".join(f"{s['name']} ({s['iso']})" for s in payload["upcoming"]) or "—"
    lines = [
        f"Départ officiel inchangé : {payload['officialT0']}",
        f"t0 : {payload['t0']}  (lecture encore dans la fenêtre jusqu'au {payload['until']})",
        (
            f"Lecture {payload['lang']} : {payload['clock']} "
            f"({payload['seconds']:.3f} s, {payload['chars']} caractères, "
            f"{payload['cps']:g} car./s)"
        ),
        f"Intégral {payload['lang']} : {payload['fullSeconds']:.3f} s, {payload['fullChars']} caractères",
        f"Escales déjà passées : {passed}",
        f"Escales encore à venir : {upcoming}",
    ]
    other = payload.get("other")
    if isinstance(other, dict):
        lines.append(
            f"Même date, {other['lang']} : {other['clock']} "
            f"({other['seconds']:.3f} s, {other['chars']} caractères)"
        )
    return "\n".join(lines)


def run(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Date où le film se lit entre 2:30 et 3:00.")
    parser.add_argument("--lang", default="en", choices=("en", "fr"))
    parser.add_argument("--lo", type=float, default=READING_LO_S)
    parser.add_argument("--hi", type=float, default=READING_HI_S)
    parser.add_argument("--film", default=None)
    parser.add_argument("--voyage", default=None)
    parser.add_argument("--json", action="store_true", help="JSON seul sur la sortie standard")
    args = parser.parse_args(argv)

    import os
    os.environ.setdefault("NAVIGUIDE_LLM_MODE", "off")
    os.environ.setdefault("NAVIGUIDE_STORY_PREGEN", "0")

    official = read_official_t0()
    if str(_SERVER) not in sys.path:
        sys.path.insert(0, str(_SERVER))
    from film_script import FILM_ESTIMATE_CPS, OFFICIAL_T0, film_estimated_seconds  # noqa: PLC0415

    if OFFICIAL_T0 != official:
        print("OFFICIAL_T0 du module et du source divergent", file=sys.stderr)
        return 4
    cps = float(FILM_ESTIMATE_CPS)
    film_path = find_film_json(args.film)
    doc = json.loads(film_path.read_text(encoding="utf-8"))
    payload_doc = _film_payload(doc)
    chapters = integral_chapters(payload_doc, args.lang)
    if not chapters:
        print(f"pas de film intégral ({args.lang}) dans {film_path}", file=sys.stderr)
        return 2
    voyage_path = Path(args.voyage) if args.voyage else default_voyage_path()
    if not voyage_path.is_file():
        print(f"voyage absent : {voyage_path}", file=sys.stderr)
        return 2
    voyage = json.loads(voyage_path.read_text(encoding="utf-8"))
    stops = load_dated_stops(voyage)
    found = search_reading_t0(chapters, stops, lo_s=args.lo, hi_s=args.hi, cps=cps)
    if found is None:
        print("aucune date dont la lecture tombe dans la fenêtre", file=sys.stderr)
        return 3
    if found["t0"] == official and found["seconds"] > args.hi:
        print("la date trouvée est le départ officiel", file=sys.stderr)
        return 4
    estimate = film_estimated_seconds(found["chars"], cps)
    other_lang = "fr" if args.lang == "en" else "en"
    other_chapters = integral_chapters(payload_doc, other_lang)
    other = None
    if other_chapters:
        measured = reading_at(other_chapters, found["t0Ms"], cps)
        other = {"lang": other_lang, **measured}
    start = min(parse_ms(ch["tA"]) for ch in chapters)
    full = reading_at(chapters, start - 1, cps)
    payload = {
        "officialT0": official,
        "t0": found["t0"],
        "until": found["until"],
        "seconds": found["seconds"],
        "clock": found["clock"],
        "estimatedSeconds": estimate,
        "chars": found["chars"],
        "cps": cps,
        "lang": args.lang,
        "fullChars": full["fullChars"],
        "fullSeconds": full["fullSeconds"],
        "probes": found["probes"],
        "passed": found["passed"],
        "upcoming": found["upcoming"],
        "kept": found["kept"],
        "other": other,
        "film": str(film_path),
    }
    if args.json:
        json.dump(payload, sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
    else:
        print(_summary(payload), file=sys.stderr)
        json.dump(payload, sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
    return 0


def main() -> None:
    sys.exit(run())


if __name__ == "__main__":
    main()
