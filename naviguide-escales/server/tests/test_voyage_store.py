"""voyage_store — écriture atomique à nom unique (29 sept. : voyage officiel corrompu par deux remplisseurs).

Le 29 sept. à 20:07 (changement de jour UTC), deux processus ont sauvegardé le voyage officiel en même temps
par le même `voyage_….tmp` : chacun avait ouvert le fichier avant que l'autre n'écrive ; le contenu court a
recouvert le début du long, la fin de l'ancien est restée → « Extra data » à la lecture, /voyage/official en
500 toute la soirée, bateau au jour 0 à distance. Ces tests rejouent le scénario au niveau des fichiers."""
import json
import os
import threading

import pytest

import voyage_store


@pytest.fixture
def store_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(voyage_store, "_DIR", tmp_path)
    return tmp_path


def _voyage(vid: str, n_points: int) -> dict:
    return {"voyageId": vid, "t0": "2026-05-15T08:00:00Z", "points": [{"lat": 46.0 + i * 1e-6, "lon": -1.0} for i in range(n_points)]}


def test_save_then_load_roundtrip(store_dir):
    voyage_store.save_voyage(_voyage("v1", 5))
    assert voyage_store.load_voyage("v1")["points"][4]["lat"] == pytest.approx(46.000004)
    assert not list(store_dir.glob("*.tmp")), "aucun temporaire ne reste après une écriture réussie"


def test_two_writers_never_produce_a_mixed_file(store_dir):
    """Deux écrivains (threads ici, processus dans la vie réelle : le verrou de module ne les voit pas) qui
    sauvent en boucle un long et un court : le fichier est TOUJOURS un JSON entier, jamais un mélange."""
    long_v = _voyage("official", 4000)
    short_v = _voyage("official", 50)
    stop = threading.Event()
    errors: list[str] = []

    def writer(v):
        while not stop.is_set():
            try:
                voyage_store.save_voyage(v)
            except Exception as exc:  # pragma: no cover — tout échec est une régression
                errors.append(repr(exc))

    def reader():
        while not stop.is_set():
            try:
                got = voyage_store.load_voyage("official")
            except json.JSONDecodeError as exc:
                errors.append(f"mélange lu : {exc}")
                return
            assert got is None or len(got["points"]) in (50, 4000)

    threads = [threading.Thread(target=writer, args=(long_v,)), threading.Thread(target=writer, args=(short_v,)),
               threading.Thread(target=reader)]
    for t in threads:
        t.start()
    threading.Event().wait(1.5)
    stop.set()
    for t in threads:
        t.join(timeout=10)
    assert not errors, errors[:3]
    final = json.loads((store_dir / "voyage_official.json").read_text(encoding="utf-8"))
    assert len(final["points"]) in (50, 4000)


_HAMMER = """
import os, sys, time
sys.path.insert(0, sys.argv[1]); os.environ["NAVIGUIDE_VOYAGE_DIR"] = sys.argv[2]
import voyage_store as vs
n = int(sys.argv[3]); v = {"voyageId": "official", "t0": "2026-05-15T08:00:00Z",
                           "points": [{"lat": 46.0 + i * 1e-6, "lon": -1.0} for i in range(n)]}
end = time.monotonic() + float(sys.argv[4])
while time.monotonic() < end:
    vs.save_voyage(v)
"""


def test_two_processes_never_produce_a_mixed_file(store_dir):
    """Le vrai scénario : deux PROCESSUS (remplisseurs) — le verrou de module ne les voit pas."""
    import subprocess
    import sys

    server_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    procs = [subprocess.Popen([sys.executable, "-c", _HAMMER, server_dir, str(store_dir), str(n), "1.5"],
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for n in (4000, 50)]
    outs = [p.communicate(timeout=60) for p in procs]
    assert all(p.returncode == 0 for p in procs), [o[1][-300:] for o in outs]
    final = json.loads((store_dir / "voyage_official.json").read_text(encoding="utf-8"))
    assert len(final["points"]) in (50, 4000)
    assert not list(store_dir.glob("*.tmp"))


def test_unique_temp_name_per_writer(store_dir, monkeypatch):
    """Le nom du temporaire est propre à chaque écriture : deux `save_voyage` concurrents ne partagent jamais
    un fichier ouvert (c'était le mécanisme exact de la corruption)."""
    seen: list[str] = []
    real_mkstemp = voyage_store.tempfile.mkstemp

    def spy(*a, **k):
        fd, name = real_mkstemp(*a, **k)
        seen.append(name)
        return fd, name

    monkeypatch.setattr(voyage_store.tempfile, "mkstemp", spy)
    voyage_store.save_voyage(_voyage("v2", 3))
    voyage_store.save_voyage(_voyage("v2", 3))
    assert len(seen) == 2 and seen[0] != seen[1]
    assert all(os.path.dirname(n) == str(store_dir) for n in seen), "même dossier : le renommage reste atomique"


def test_failed_write_leaves_previous_file_intact(store_dir, monkeypatch):
    voyage_store.save_voyage(_voyage("v3", 7))
    before = (store_dir / "voyage_v3.json").read_text(encoding="utf-8")

    def boom(*a, **k):
        raise OSError("disque plein")

    monkeypatch.setattr(voyage_store.os, "replace", boom)
    with pytest.raises(OSError):
        voyage_store.save_voyage(_voyage("v3", 1))
    assert (store_dir / "voyage_v3.json").read_text(encoding="utf-8") == before
    assert not list(store_dir.glob("*.tmp")), "le temporaire raté est nettoyé"
