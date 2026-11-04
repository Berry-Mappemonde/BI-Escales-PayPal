#!/usr/bin/env python3
"""Gèle le stock DISQUE courant en archive versionnée.

Aucune donnée inventée : on copie les familles déjà calculées (payloads
intacts). JSON compacté (même objet) pour rester ≤ 3 Mo une fois gzip.
Si le climo dépasse encore, on retire seulement les champs vides des
sommets — jamais un sommet, jamais une valeur renseignée.

    cd naviguide-simulator && .venv/bin/python scripts/freeze_official_store.py
"""
from __future__ import annotations

import json
import os
import sys
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "server"
FIXTURES = SERVER / "tests" / "fixtures"
ARCHIVE = FIXTURES / "official_store.tar.gz"
README = FIXTURES / "official_store.README.md"
# La route sur laquelle le stock a été calculé : la recette hors ligne la sert avec lui.
ROUTE = ROOT / "public" / "route.geojson"
ROUTE_FIXTURE = FIXTURES / "official_store.route.geojson"
DEFAULT_SRC = Path.home() / ".cache" / "naviguide" / "voyage-store"
MAX_BYTES = 3 * 1024 * 1024
FAMILIES = ("moments", "film", "eta", "climo", "ici", "plan_review")


def source_dir() -> Path:
    env = (os.environ.get("NAVIGUIDE_OFFICIAL_STORE_DIR") or "").strip()
    return Path(env) if env else DEFAULT_SRC


def _drop_empty(row: dict) -> dict:
    return {
        k: v
        for k, v in row.items()
        if v is not None and v != [] and v != ""
    }


def maybe_thin_climo(doc: dict) -> dict:
    """Garde tous les sommets ; retire seulement les champs vides."""
    if doc.get("family") != "climo":
        return doc
    out = json.loads(json.dumps(doc))
    payload = out.get("payload")
    if not isinstance(payload, dict):
        return out
    clock = payload.get("clock")
    if isinstance(clock, dict) and isinstance(clock.get("vertices"), list):
        clock["vertices"] = [
            _drop_empty(v) if isinstance(v, dict) else v
            for v in clock["vertices"]
        ]
    fiches = payload.get("fiches")
    if isinstance(fiches, list):
        payload["fiches"] = [
            _drop_empty(f) if isinstance(f, dict) else f
            for f in fiches
        ]
    return out


def iter_docs(root: Path) -> list[tuple[Path, dict]]:
    found: list[tuple[Path, dict]] = []
    if not root.exists():
        return found
    for path in sorted(root.rglob("*.json")):
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(doc, dict) or not doc.get("key") or not doc.get("family"):
            continue
        found.append((path.relative_to(root), doc))
    return found


def write_tree(docs: list[tuple[Path, dict]], dest: Path, *, thin_climo: bool) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    for rel, doc in docs:
        body = maybe_thin_climo(doc) if thin_climo else doc
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(body, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )


def pack_tree(tree: Path, archive: Path) -> int:
    archive.parent.mkdir(parents=True, exist_ok=True)
    tmp = archive.with_suffix(".tmp.tar.gz")
    with tarfile.open(tmp, "w:gz", compresslevel=9) as tf:
        for path in sorted(tree.rglob("*")):
            if path.is_file():
                tf.add(path, arcname=str(path.relative_to(tree)))
    tmp.replace(archive)
    return archive.stat().st_size


def unpack(archive: Path, dest: Path) -> Path:
    dest.mkdir(parents=True, exist_ok=True)
    kwargs = {}
    if sys.version_info >= (3, 12):
        kwargs["filter"] = "data"
    with tarfile.open(archive, "r:gz") as tf:
        tf.extractall(dest, **kwargs)
    return dest


def freeze(src: Path, archive: Path = ARCHIVE) -> dict:
    docs = iter_docs(src)
    if not docs:
        raise SystemExit(f"stock vide : {src}")
    keys = sorted({str(doc.get("key") or "") for _, doc in docs if doc.get("key")})
    families = sorted({str(doc.get("family") or "") for _, doc in docs})
    with tempfile.TemporaryDirectory(prefix="naviguide-freeze-") as tmp:
        tree = Path(tmp) / "store"
        write_tree(docs, tree, thin_climo=False)
        size = pack_tree(tree, archive)
        thinned = False
        if size > MAX_BYTES:
            write_tree(docs, tree, thin_climo=True)
            size = pack_tree(tree, archive)
            thinned = True
    if archive == ARCHIVE:
        ROUTE_FIXTURE.write_bytes(ROUTE.read_bytes())
    return {
        "src": str(src),
        "archive": str(archive),
        "bytes": size,
        "keys": keys,
        "families": families,
        "docs": len(docs),
        "thinned": thinned,
    }


def write_readme(info: dict, dest: Path = README) -> None:
    missing = [name for name in FAMILIES if name not in info["families"]]
    when = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    keys = "\n".join(f"- `{k}`" for k in info["keys"])
    fams = ", ".join(info["families"])
    miss = ", ".join(missing) if missing else "aucune"
    dest.write_text(
        f"""# Stock officiel figé (lot RF11)

Date du gel : {when} (UTC).
Archive : `server/tests/fixtures/official_store.tar.gz` ({info["bytes"]} octets).
Familles présentes : {fams}.
Familles absentes du poste (restent « en préparation ») : {miss}.
Clés :

{keys}

Route du gel : `server/tests/fixtures/official_store.route.geojson`, copie de
`public/route.geojson` au moment du gel. La recette hors ligne sert les deux
ensemble ; `test_frozen_archive_is_paired_with_its_route` échoue s'ils divergent.

Commande pour régénérer (après un vrai calcul, si la route ou t0 change) :

```bash
cd naviguide-simulator
NAVIGUIDE_LLM_MODE=off .venv/bin/python scripts/prepare_official_store.py
.venv/bin/python scripts/freeze_official_store.py
```

`NAVIGUIDE_LLM_MODE=off` : sans lui, une clé présente sur le poste fait des
appels Nano/Lightning payants pendant le calcul.

Le script lit `~/.cache/naviguide/voyage-store` (ou `NAVIGUIDE_OFFICIAL_STORE_DIR`).
Aucune donnée n'est inventée : on gèle le stock déjà calculé.
""",
        encoding="utf-8",
    )


def main() -> int:
    src = source_dir()
    print(f"source : {src}", flush=True)
    info = freeze(src, ARCHIVE)
    write_readme(info, README)
    print(
        f"archive : {ARCHIVE} ({info['bytes']} octets, "
        f"{info['docs']} fichiers, thin={info['thinned']})",
        flush=True,
    )
    for key in info["keys"]:
        print(f"  clé {key}", flush=True)
    print(f"familles : {', '.join(info['families'])}", flush=True)
    if info["bytes"] > MAX_BYTES:
        print(f"ATTENTION : archive > {MAX_BYTES} octets", flush=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
