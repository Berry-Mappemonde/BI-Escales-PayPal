#!/usr/bin/env python3
"""Remplit le stock du voyage officiel par le VRAI calcul — dans un PROCESSUS à part (RC18).

Aucune donnée écrite en dur : une famille qui échoue reste « en préparation ».

    prepare_official_store.py                 # une passe (ensure-dev.sh --prod, avant d'ouvrir le navigateur)
    prepare_official_store.py --loop          # le remplisseur de l'API : périodique + réveil par fichier « nudge »
    prepare_official_store.py --rebuild-film fr:150   # une variante, journal, arrêt si silence

Pourquoi un processus : le calcul tient le GIL ; dans le processus de l'API il l'étouffait (27 sept. : 97 % CPU,
/clock en 7 s, POST /voyage coupé à 100 s). Ici il tourne en priorité basse, l'API ne fait que lire le stock.
Dos : disque (NAVIGUIDE_OFFICIAL_STORE_DIR) ou MongoDB si SIMULATOR_MONGO_URL est posé (VPS) — le même que l'API.
"""
from __future__ import annotations

import argparse
import os
import signal
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "server"
sys.path.insert(0, str(SERVER))

os.environ.setdefault(
    "NAVIGUIDE_OFFICIAL_STORE_DIR",
    str(Path.home() / ".cache" / "naviguide" / "voyage-store"),
)
os.environ["NAVIGUIDE_OFFICIAL_WORKER"] = "0"   # ce processus EST le remplisseur : pas de fil, pas d'enfant

LABELS = {
    "climo": "horloge / climatologie",
    "moments": "journal des moments",
    "film": "script du film",
    "eta": "ETA et fourchettes",
    "ici": "sacs « ici »",
    "plan_review": "revue du plan",
}

_STOP = False


def _say(msg: str) -> None:
    print(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}", flush=True)


def _progress_printer(n: int):
    import official_store
    from official_store import COMPUTE_ORDER, READY

    def progress(family: str, status: str, detail: str = "") -> None:
        if family == "*":
            _say(f"  · {status} {detail}".rstrip())
            return
        label = LABELS.get(family, family)
        idx = COMPUTE_ORDER.index(family) + 1 if family in COMPUTE_ORDER else "?"
        mark = "prêt" if status == READY else ("déjà en stock" if status == "unchanged" else "en préparation")
        extra = f" — {detail}" if detail else ""
        _say(f"[{idx}/{n}] {label} … {mark}{extra}")

    return progress


def _film_only_value(raw: str) -> str:
    """`fr:150`, `en:180` ou `fr:0`. Autre chose : le script s'arrête."""
    text = (raw or "").strip().lower()
    lang, sep, secs = text.partition(":")
    if sep != ":" or lang not in {"fr", "en"}:
        raise SystemExit(f"variante invalide : {raw} (attendu fr:150, en:180 ou fr:0)")
    try:
        n = int(secs)
    except ValueError:
        raise SystemExit(f"variante invalide : {raw} (attendu fr:150, en:180 ou fr:0)")
    from official_store import FILM_VARIANT_SECONDS  # noqa: PLC0415
    if n not in FILM_VARIANT_SECONDS:
        raise SystemExit(f"variante invalide : {raw} (attendu fr:150, en:180 ou fr:0)")
    return f"{lang}:{n}"


def one_pass(*, force_film: bool = False) -> int:
    import official_store
    from ici_engine import ensure_pearl_amp_layer_sig  # noqa: PLC0415
    from official_store import COMPUTE_ORDER, READY

    ensure_pearl_amp_layer_sig("prepare_official_store")
    n = len(COMPUTE_ORDER)
    t0 = time.monotonic()
    # Le film forcé suit : ne pas le calculer deux fois dans la même passe.
    skip = ("film",) if force_film else ()
    out = official_store.refresh_missing(
        progress=_progress_printer(n), should_stop=lambda: _STOP, skip=skip,
    )
    if force_film and not _STOP:
        try:
            limit = official_store.film_variant_timeout_s()
            _say(f"[film] une variante à la fois, délai max {limit:.0f} s")
            status = official_store.refresh_family("film", force=True)
            _say(f"[film] script recalculé ({status})")
        except Exception as exc:  # jamais fatal
            _say(f"[film] recalcul impossible : {exc}")
        out = official_store.family_status()
    families = (out or {}).get("families") or {}
    ready = sum(1 for v in families.values() if v.get("status") == READY)
    _say(f"passage terminé en {time.monotonic() - t0:.0f} s — {ready}/{n} familles prêtes")
    for name in COMPUTE_ORDER:
        st = (families.get(name) or {}).get("status") or "preparing"
        _say(f"  {LABELS[name]} : {st}")
    return ready


def _on_stop(signum, _frame) -> None:
    global _STOP
    _STOP = True
    _say(f"signal {signum} : arrêt après le passage en cours")


def _watch_parent(parent: int) -> None:
    """Le timeout ne tue que le bash : ce python restait orphelin (ppid 1) et continuait
    d'écrire le stock. Si le parent disparaît, on s'arrête, puis on quitte pour de bon
    si le calcul en cours (lecture JSON) n'a pas vu le signal."""
    global _STOP
    while not _STOP:
        time.sleep(2)
        if os.getppid() == parent:
            continue
        _STOP = True
        _say(f"parent {parent} disparu : arrêt")
        try:
            os.kill(os.getpid(), signal.SIGTERM)
        except OSError:
            os._exit(0)
        time.sleep(15)
        os._exit(0)


def _arm_parent_watch() -> None:
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return
    parent = os.getppid()
    if parent <= 1:
        return
    threading.Thread(target=_watch_parent, args=(parent,), name="fill-parent", daemon=True).start()


def _nudge_stamp(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def loop(period_s: float) -> int:
    import official_store

    pidfile = official_store.fill_pidfile()
    nudge = official_store.fill_nudgefile()
    try:
        pidfile.parent.mkdir(parents=True, exist_ok=True)
        me = Path(__file__).resolve()
        pidfile.write_text(f"{os.getpid()}\n{me}\n{official_store._fill_script_stamp()}\n", encoding="utf-8")
    except OSError:
        pass

    signal.signal(signal.SIGTERM, _on_stop)
    signal.signal(signal.SIGINT, _on_stop)
    try:   # un seul remplisseur par machine (29 sept. : quatre écrivaient le même stock)
        gone = official_store.stop_other_fill_processes(keep=os.getpid())
        if gone:
            _say(f"remplisseurs concurrents arrêtés : {gone}")
    except Exception as exc:
        _say(f"ménage des remplisseurs impossible : {exc}")
    _say(f"remplisseur en boucle (pid {os.getpid()}, période {int(period_s)} s, réveil par {nudge.name})")
    last_nudge = _nudge_stamp(nudge)
    first = True
    while not _STOP:
        try:
            one_pass(force_film=first)
        except Exception as exc:  # le remplisseur ne meurt pas d'une exception
            _say(f"passage en erreur : {type(exc).__name__}: {exc}")
        first = False
        deadline = time.monotonic() + max(60.0, period_s)
        while not _STOP and time.monotonic() < deadline:
            time.sleep(5)
            stamp = _nudge_stamp(nudge)
            if stamp > last_nudge:
                last_nudge = stamp
                _say("réveil demandé par l'API")
                break
    try:
        if pidfile.exists() and pidfile.read_text(encoding="utf-8").split()[0] == str(os.getpid()):
            pidfile.unlink()
    except (OSError, IndexError):
        pass
    _say("remplisseur arrêté")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--loop", action="store_true", help="tourner en continu : une passe, puis toutes les --period s ou au réveil")
    ap.add_argument("--store", default="", help="dossier du stock (NAVIGUIDE_OFFICIAL_STORE_DIR) — porté sur la ligne de commande pour qu'un seul remplisseur tourne par stock")
    ap.add_argument("--period", type=float, default=float(os.environ.get("NAVIGUIDE_OFFICIAL_STORE_PERIOD_S") or 6 * 3600))
    ap.add_argument("--nice", type=int, default=10, help="priorité basse (os.nice) ; 0 = priorité normale")
    ap.add_argument(
        "--write-film",
        action="store_true",
        help="RG11A : forcer le rédigé Nemotron 3.5 Super VL, palier write (sans recalculer le brut)",
    )
    ap.add_argument(
        "--film-only",
        default="",
        help="une seule variante du film, langue:secondes (fr:150, en:180, fr:0)",
    )
    ap.add_argument(
        "--rebuild-film",
        default="",
        metavar="LANGUE:DUREE",
        help="reconstruire une seule variante (fr:150, en:180 ou fr:0) ; arrêt si aucun progrès avant le délai maximum",
    )
    args = ap.parse_args()
    if args.rebuild_film and args.film_only:
        raise SystemExit("une seule variante : --rebuild-film ou --film-only, pas les deux")
    if args.rebuild_film and args.loop:
        raise SystemExit("--rebuild-film construit une variante et s'arrête : pas avec --loop")
    if args.rebuild_film and args.write_film:
        raise SystemExit("--rebuild-film inclut l'appel Nemotron : pas avec --write-film")
    if args.rebuild_film:
        os.environ["NAVIGUIDE_FILM_ONLY"] = _film_only_value(args.rebuild_film)
    elif args.film_only:
        os.environ["NAVIGUIDE_FILM_ONLY"] = _film_only_value(args.film_only)
    if args.store:
        os.environ["NAVIGUIDE_OFFICIAL_STORE_DIR"] = args.store

    if args.nice:
        try:
            os.nice(args.nice)
        except OSError:
            pass
    dest = Path(os.environ["NAVIGUIDE_OFFICIAL_STORE_DIR"])
    dest.mkdir(parents=True, exist_ok=True)
    _say(f"stock : {'MongoDB (SIMULATOR_MONGO_URL)' if os.environ.get('SIMULATOR_MONGO_URL') else dest}")
    _say("calcul réel — aucune donnée écrite en dur")

    import official_store
    official_store.reset_store()
    signal.signal(signal.SIGTERM, _on_stop)
    signal.signal(signal.SIGINT, _on_stop)
    _arm_parent_watch()
    if args.write_film and not args.loop:
        out = official_store.fill_written_film(force=True)
        _say(f"rédigé : {out}")
        return 0
    if args.rebuild_film:
        variant = os.environ["NAVIGUIDE_FILM_ONLY"]
        lang, _, secs = variant.partition(":")
        _say(f"film : reconstruction {variant}")
        from ici_engine import ensure_pearl_amp_layer_sig  # noqa: PLC0415
        ensure_pearl_amp_layer_sig("prepare_official_store")
        try:
            official_store.rebuild_film_variant(lang, int(secs))
        except official_store.FilmProgressStalled as exc:
            _say(str(exc))
            return 1
        except Exception as exc:
            _say(f"film : reconstruction impossible : {type(exc).__name__}: {exc}")
            return 1
        _say(f"film {variant} reconstruit")
        return 0
    if args.loop:
        return loop(args.period)
    one_pass()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
