"""Base embarquée du simulateur — SQLite, un fichier dans `voyage_data/`.

Première table : les **perles** (sacs `ici()` échantillonnés le long de la
route officielle). Un sac riche (toutes les couches sans horodatage)
ou thin (ZEE, ports d'entrée, AMP, ports), sa position, son moment.

Pourquoi SQLite et pas un JSON : 3 272 perles riches font ~60 Mo ; on les
lit une par une (clé), on les remplace au fil du chauffage, on veut les
garder sur disque entre deux redémarrages sans réécrire tout le fichier
toutes les 30 s. Le module stdlib suffit ; WAL pour que le chauffeur
écrive pendant que les requêtes lisent. Sauvegardé avec `voyage_data/`.
Pas de MongoDB côté simulateur : Mongo reste la base de Blue Intelligence.
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Callable, Iterator, Optional

log = logging.getLogger("naviguide-simulator.store")

# Une tuile AMP GeoJSON (7–40 Mo) gravée dans kv `amp-bbox` a fait gonfler
# le sqlite de recette à 5 Go. json.loads de ces lignes saturait l'API.
KV_MAX_BYTES = 2_000_000

_LOCK = threading.RLock()
_conn: Optional[sqlite3.Connection] = None
_path: Optional[Path] = None

_SCHEMA = (
    "CREATE TABLE IF NOT EXISTS pearls ("
    " key TEXT PRIMARY KEY,"
    " lat REAL, lon REAL,"
    " kind TEXT NOT NULL,"      # thin | rich
    " bag TEXT NOT NULL,"       # JSON
    " ts REAL NOT NULL)",
    "CREATE INDEX IF NOT EXISTS pearls_kind ON pearls(kind)",
    # Generic namespaced cache: escale sheets, pre-generated stories…
    "CREATE TABLE IF NOT EXISTS kv ("
    " ns TEXT NOT NULL,"
    " key TEXT NOT NULL,"
    " value TEXT NOT NULL,"     # JSON
    " ts REAL NOT NULL,"
    " PRIMARY KEY (ns, key))",
    # Journal des moments : une ligne par changement de signature.
    "CREATE TABLE IF NOT EXISTS moments ("
    " voyage_id TEXT NOT NULL,"
    " seq INTEGER NOT NULL,"
    " t TEXT,"
    " lat REAL, lon REAL,"
    " leg_idx INTEGER,"
    " signature TEXT NOT NULL,"
    " changes TEXT NOT NULL,"   # JSON
    " moment TEXT NOT NULL,"    # JSON
    " PRIMARY KEY (voyage_id, seq))",
    "CREATE INDEX IF NOT EXISTS moments_voyage_t ON moments(voyage_id, t)",
)


def db_path() -> Path:
    from voyage_store import voyage_dir  # noqa: PLC0415
    return voyage_dir() / "naviguide.sqlite"


def _connect() -> sqlite3.Connection:
    global _conn, _path
    p = db_path()
    with _LOCK:
        if _conn is not None and _path == p:
            return _conn
        close()
        p.parent.mkdir(parents=True, exist_ok=True)
        initialize = not p.exists()
        conn = sqlite3.connect(str(p), check_same_thread=False, isolation_level=None, timeout=10.0)
        if initialize:
            conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        for stmt in _SCHEMA:
            conn.execute(stmt)
        _conn, _path = conn, p
        return conn


def close() -> None:
    global _conn, _path
    with _LOCK:
        if _conn is not None:
            try:
                _conn.close()
            except Exception:  # defensive
                pass
        _conn, _path = None, None


def reset() -> None:
    """Tests: forget the connection so a new voyage dir takes effect."""
    close()


# ── perles ──────────────────────────────────────────────────────────────────

def list_pearl_amp_layer_suffixes() -> list[str]:
    """Suffixes numériques `aNNNN` (N > 0), le plus récent d'abord.

    La récence est l'horodatage le plus élevé des perles qui portent le suffixe ;
    à horodatage égal, le plus grand numéro l'emporte.
    """
    try:
        if not db_path().is_file():
            return []
        with _LOCK:
            rows = _connect().execute(
                "SELECT key, ts FROM pearls WHERE key LIKE '%:a%'",
            ).fetchall()
    except Exception as exc:
        log.warning("store perles (suffixes AMP) : %s", exc)
        return []
    best: dict[int, float] = {}
    for key, ts in rows:
        for part in str(key).split(":"):
            if len(part) > 1 and part[0] == "a" and part[1:].isdigit():
                number = int(part[1:])
                if number > 0:
                    best[number] = max(best.get(number, 0.0), float(ts or 0))
    ordered = sorted(best, key=lambda number: (best[number], number), reverse=True)
    return [str(number) for number in ordered]


def list_pearl_key_times(prefix: str) -> list[tuple[str, float]]:
    """Clés de la cellule `prefix` (clé exacte ou `prefix:…`), les plus récentes d'abord."""
    try:
        if not db_path().is_file():
            return []
        with _LOCK:
            rows = _connect().execute(
                "SELECT key, ts FROM pearls WHERE key = ? OR key LIKE ? ORDER BY ts DESC",
                (prefix, f"{prefix}:%"),
            ).fetchall()
        return [(str(key), float(ts or 0)) for key, ts in rows]
    except Exception as exc:
        log.warning("store perles (préfixe) : %s", exc)
        return []


def list_pearl_keys_prefixed(prefix: str) -> list[str]:
    return [key for key, _ts in list_pearl_key_times(prefix)]


def get_pearl(key: str) -> Optional[dict]:
    """{ kind, bag, ts } or None. Never raises (a broken store = a cache miss)."""
    try:
        with _LOCK:
            row = _connect().execute("SELECT kind, bag, ts FROM pearls WHERE key = ?", (key,)).fetchone()
    except Exception as exc:
        log.warning("store perles (lecture) : %s", exc)
        return None
    if not row:
        return None
    try:
        return {"kind": row[0], "bag": json.loads(row[1]), "ts": float(row[2])}
    except Exception:
        return None


def pearl_meta(key: str) -> Optional[dict]:
    """{ kind, ts } sans décoder le sac — pour savoir si une perle est là et riche (3 272 sacs × json.loads
    au boot tenaient la boucle d'événements ~2 min, 27 sept.)."""
    try:
        with _LOCK:
            row = _connect().execute("SELECT kind, ts FROM pearls WHERE key = ?", (key,)).fetchone()
    except Exception as exc:
        log.warning("store perles (méta) : %s", exc)
        return None
    if not row:
        return None
    try:
        return {"kind": row[0], "ts": float(row[1])}
    except Exception:
        return None


def insert_pearl_if_absent(
    key: str,
    bag: dict,
    kind: str = "thin",
    lat: float | None = None,
    lon: float | None = None,
    ts: float | None = None,
) -> bool:
    """Ajoute une perle sous `key` si elle n'existe pas. Ne remplace jamais une ligne."""
    if get_pearl(key):
        return False
    return put_pearl(key, bag, kind, lat, lon, ts)


def put_pearl(key: str, bag: dict, kind: str = "thin", lat: float | None = None,
              lon: float | None = None, ts: float | None = None) -> bool:
    """Insert or replace. A rich pearl is never downgraded by a thin one.

    Une clé se terminant par :a0 est refusée dès qu'une signature de couche réelle existe.
    """
    from ici_engine import refuse_pearl_key_with_zero_amp_suffix  # noqa: PLC0415

    refuse_pearl_key_with_zero_amp_suffix(key, "put_pearl")
    try:
        payload = json.dumps(bag, ensure_ascii=False, default=str)
        with _LOCK:
            conn = _connect()
            cur = conn.execute("SELECT kind FROM pearls WHERE key = ?", (key,)).fetchone()
            if cur and cur[0] == "rich" and kind != "rich":
                return False
            conn.execute(
                "INSERT OR REPLACE INTO pearls (key, lat, lon, kind, bag, ts) VALUES (?, ?, ?, ?, ?, ?)",
                (key, lat, lon, kind, payload, float(ts if ts is not None else time.time())),
            )
        return True
    except Exception as exc:
        log.warning("store perles (écriture) : %s", exc)
        return False


def non_polygon_amp_pearls(kind: str = "rich") -> list[tuple[str, float | None, float | None]]:
    """Perles riches dont une aire n'est pas marquée polygone (centroïde ou marque absente).

    Une requête SQL, sans json.loads. (clé, lat, lon) — lat/lon peuvent manquer.
    """
    try:
        with _LOCK:
            rows = _connect().execute(
                "SELECT DISTINCT p.key, p.lat, p.lon FROM pearls p, json_each(p.bag, '$.amp') j "
                "WHERE p.kind = ? AND json_valid(p.bag) "
                "AND COALESCE(json_extract(j.value, '$.source'), '') != 'polygon'",
                (kind,),
            ).fetchall()
    except Exception as exc:
        log.warning("store perles (AMP non polygones) : %s", exc)
        return []
    out: list[tuple[str, float | None, float | None]] = []
    for key, lat, lon in rows:
        try:
            plat = float(lat) if lat is not None else None
            plon = float(lon) if lon is not None else None
        except (TypeError, ValueError):
            plat = plon = None
        out.append((str(key), plat, plon))
    return out


def delete_pearl(key: str) -> bool:
    try:
        with _LOCK:
            cur = _connect().execute("DELETE FROM pearls WHERE key = ?", (key,))
            return bool(cur.rowcount)
    except Exception as exc:
        log.warning("store perles (suppression) : %s", exc)
        return False


def count_pearls() -> dict[str, int]:
    try:
        with _LOCK:
            rows = _connect().execute("SELECT kind, COUNT(*) FROM pearls GROUP BY kind").fetchall()
    except Exception:
        return {"total": 0, "rich": 0, "thin": 0}
    out = {"total": 0, "rich": 0, "thin": 0}
    for kind, n in rows:
        out[kind if kind in out else "thin"] += int(n)
        out["total"] += int(n)
    return out


def purge_pearls(older_than_s: float, kind: str | None = None) -> int:
    """Drop pearls older than `older_than_s` (all kinds, or one)."""
    cutoff = time.time() - float(older_than_s)
    try:
        with _LOCK:
            conn = _connect()
            if kind:
                cur = conn.execute("DELETE FROM pearls WHERE ts < ? AND kind = ?", (cutoff, kind))
            else:
                cur = conn.execute("DELETE FROM pearls WHERE ts < ?", (cutoff,))
            return int(cur.rowcount or 0)
    except Exception as exc:
        log.warning("store perles (purge) : %s", exc)
        return 0


def nearest_pearl_key(
    lat: float,
    lon: float,
    *,
    kind: str | None = None,
    accept: Callable[[str], bool] | None = None,
) -> tuple[Optional[str], Optional[float]]:
    """(clé, distance nm) de la perle la plus proche — sur les colonnes lat/lon, SANS décoder les sacs.
    27 sept. : /ici/moment décodait les 3 272 sacs à chaque requête (34 requêtes au démarrage → minutes de CPU).
    `accept` filtre les clés (lecture seule : aucune écriture)."""
    import math  # noqa: PLC0415
    try:
        with _LOCK:
            if kind:
                rows = _connect().execute("SELECT key, lat, lon FROM pearls WHERE kind = ? AND lat IS NOT NULL AND lon IS NOT NULL", (kind,)).fetchall()
            else:
                rows = _connect().execute("SELECT key, lat, lon FROM pearls WHERE lat IS NOT NULL AND lon IS NOT NULL").fetchall()
    except Exception as exc:
        log.warning("store perles (plus proche) : %s", exc)
        return None, None
    best_key, best_d = None, None
    la1 = math.radians(float(lat))
    for key, plat, plon in rows:
        key_s = str(key)
        if accept is not None and not accept(key_s):
            continue
        try:
            la2 = math.radians(float(plat))
            dlon = math.radians(float(plon) - float(lon))
            # distance sphérique (nm), même formule que isochrone.haversine
            a = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin(dlon / 2) ** 2
            d = 2 * 3440.065 * math.asin(min(1.0, math.sqrt(a)))
        except (TypeError, ValueError):
            continue
        if best_d is None or d < best_d:
            best_key, best_d = key_s, d
    return best_key, best_d


def iter_pearls(kind: str | None = None) -> Iterator[tuple[str, dict]]:
    """(key, { kind, bag, ts }) for every pearl — used by the warmer's status only."""
    try:
        with _LOCK:
            if kind:
                rows = _connect().execute("SELECT key, kind, bag, ts FROM pearls WHERE kind = ?", (kind,)).fetchall()
            else:
                rows = _connect().execute("SELECT key, kind, bag, ts FROM pearls").fetchall()
    except Exception as exc:
        log.warning("store perles (parcours) : %s", exc)
        return iter(())
    def gen():
        for key, k, bag, ts in rows:
            try:
                yield key, {"kind": k, "bag": json.loads(bag), "ts": float(ts)}
            except Exception:
                continue
    return gen()


def import_legacy_json(path: Path, ttl_s: float) -> int:
    """One-time migration of the former `ici_thin_cache.json` (thin bags)."""
    if not path.exists():
        return 0
    try:
        data = json.loads(path.read_text())
    except Exception as exc:
        log.warning("ancien cache perles illisible (%s) : ignoré", exc)
        return 0
    now = time.time()
    n = 0
    for key, hit in (data or {}).items():
        if not isinstance(hit, dict) or "bag" not in hit:
            continue
        ts = float(hit.get("ts") or 0)
        if now - ts > ttl_s:
            continue
        parts = key.split(":")
        # 3 = lat:lon:radius ; 4 = + PEARL_REV (rg3) ; 5 = + a{sig}.
        # Un 4e segment numérique = ancien mois, ignoré.
        if len(parts) == 3:
            pass
        elif len(parts) == 4 and not str(parts[3]).isdigit():
            pass
        elif len(parts) == 5 and str(parts[4]).startswith("a"):
            pass
        else:
            continue
        try:
            lat, lon = float(parts[0]), float(parts[1])
        except Exception:
            lat = lon = None
        try:
            written = put_pearl(key, hit["bag"], "thin", lat, lon, ts)
        except RuntimeError as exc:
            log.warning("cache perles : clé %s ignorée (%s)", key, exc)
            continue
        if written:
            n += 1
    try:
        path.rename(path.with_suffix(".json.migrated"))
    except Exception:
        pass
    log.info("cache perles : %d sacs thin migrés vers SQLite", n)
    return n


# ── cache générique (ns, key) ────────────────────────────────────────────────

def kv_get(ns: str, key: str, max_age_s: float | None = None) -> Optional[dict]:
    """{ value, ts } or None (missing, stale, or broken store)."""
    try:
        with _LOCK:
            row = _connect().execute("SELECT value, ts FROM kv WHERE ns = ? AND key = ?", (ns, key)).fetchone()
    except Exception as exc:
        log.warning("store kv (lecture) : %s", exc)
        return None
    if not row:
        return None
    ts = float(row[1])
    if max_age_s is not None and time.time() - ts > float(max_age_s):
        return None
    try:
        return {"value": json.loads(row[0]), "ts": ts}
    except Exception:
        return None


def kv_put(ns: str, key: str, value: Any) -> bool:
    try:
        payload = json.dumps(value, ensure_ascii=False, default=str)
        if len(payload.encode("utf-8")) > KV_MAX_BYTES:
            log.warning("store kv (écriture) : %s/%s trop gros (%s octets) — ignoré", ns, key, len(payload))
            return False
        with _LOCK:
            _connect().execute(
                "INSERT OR REPLACE INTO kv (ns, key, value, ts) VALUES (?, ?, ?, ?)",
                (ns, key, payload, time.time()),
            )
        return True
    except Exception as exc:
        log.warning("store kv (écriture) : %s", exc)
        return False


def kv_update(ns: str, key: str, update: Callable[[Any], Any]) -> Any:
    """Atomically read, transform and write a KV value across processes."""
    with _LOCK:
        conn = _connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT value FROM kv WHERE ns = ? AND key = ?", (ns, key)).fetchone()
            current = json.loads(row[0]) if row else None
            value = update(current)
            payload = json.dumps(value, ensure_ascii=False, default=str)
            if len(payload.encode("utf-8")) > KV_MAX_BYTES:
                raise ValueError("KV value too large")
            conn.execute(
                "INSERT OR REPLACE INTO kv (ns, key, value, ts) VALUES (?, ?, ?, ?)",
                (ns, key, payload, time.time()),
            )
            conn.execute("COMMIT")
            return value
        except Exception:
            conn.execute("ROLLBACK")
            raise


def kv_delete(ns: str, key: str) -> bool:
    """Drop one kv row. True if a row was removed. Never wipes the namespace."""
    try:
        with _LOCK:
            cur = _connect().execute("DELETE FROM kv WHERE ns = ? AND key = ?", (ns, key))
            return int(cur.rowcount or 0) > 0
    except Exception as exc:
        log.warning("store kv (suppression) : %s", exc)
        return False


def kv_keys(ns: str) -> list[str]:
    """Toutes les clés d'un namespace (migration HC1). Vide si store cassé."""
    try:
        with _LOCK:
            rows = _connect().execute("SELECT key FROM kv WHERE ns = ?", (ns,)).fetchall()
        return [str(r[0]) for r in rows]
    except Exception as exc:
        log.warning("store kv (clés) : %s", exc)
        return []


def kv_count(ns: str) -> int:
    try:
        with _LOCK:
            row = _connect().execute("SELECT COUNT(*) FROM kv WHERE ns = ?", (ns,)).fetchone()
        return int(row[0] or 0)
    except Exception:
        return 0


def kv_purge(ns: str, older_than_s: float) -> int:
    cutoff = time.time() - float(older_than_s)
    try:
        with _LOCK:
            cur = _connect().execute("DELETE FROM kv WHERE ns = ? AND ts < ?", (ns, cutoff))
            return int(cur.rowcount or 0)
    except Exception:
        return 0


def moments_decrease_allowed() -> bool:
    """Tests uniquement : autorise une écriture qui réduit le nombre de lignes."""
    return os.environ.get("NAVIGUIDE_TEST_ALLOW_MOMENT_DECREASE", "").strip() in {
        "1", "true", "yes", "on",
    }


def replace_moments(voyage_id: str, rows: list[dict]) -> int:
    """Réécrit le journal d'un voyage (idempotent). Jamais d'erreur vers l'appelant."""
    try:
        with _LOCK:
            conn = _connect()
            before_row = conn.execute(
                "SELECT COUNT(*) FROM moments WHERE voyage_id = ?", (voyage_id,),
            ).fetchone()
            before = int((before_row[0] if before_row else 0) or 0)
            after = len(rows)
            if before > 0 and after < before and not moments_decrease_allowed():
                log.error(
                    "store moments (écriture refusée) : %s lignes → %s pour %s "
                    "(fusion ou restauration requise ; flag test NAVIGUIDE_TEST_ALLOW_MOMENT_DECREASE)",
                    before,
                    after,
                    voyage_id,
                )
                return before
            conn.execute("BEGIN")
            try:
                conn.execute("DELETE FROM moments WHERE voyage_id = ?", (voyage_id,))
                for row in rows:
                    pos = row.get("pos") if isinstance(row.get("pos"), dict) else {}
                    conn.execute(
                        "INSERT INTO moments "
                        "(voyage_id, seq, t, lat, lon, leg_idx, signature, changes, moment) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            voyage_id,
                            int(row.get("seq") or 0),
                            row.get("t"),
                            pos.get("lat"),
                            pos.get("lon"),
                            row.get("legIdx"),
                            str(row.get("signature") or ""),
                            json.dumps(row.get("changes") or [], ensure_ascii=False, default=str),
                            json.dumps(row.get("moment") or {}, ensure_ascii=False, default=str),
                        ),
                    )
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise
        return len(rows)
    except Exception as exc:
        log.warning("store moments (écriture) : %s", exc)
        return 0


def list_moments(voyage_id: str) -> list[dict]:
    """Lignes du journal, ordre de seq. Jamais lève."""
    try:
        with _LOCK:
            rows = _connect().execute(
                "SELECT seq, t, lat, lon, leg_idx, signature, changes, moment "
                "FROM moments WHERE voyage_id = ? ORDER BY seq",
                (voyage_id,),
            ).fetchall()
    except Exception as exc:
        log.warning("store moments (lecture) : %s", exc)
        return []
    out: list[dict] = []
    for seq, t, lat, lon, leg_idx, sig, changes, moment in rows:
        try:
            out.append({
                "voyageId": voyage_id,
                "seq": int(seq),
                "t": t,
                "pos": {"lat": lat, "lon": lon},
                "legIdx": leg_idx,
                "signature": sig,
                "changes": json.loads(changes),
                "moment": json.loads(moment),
            })
        except Exception:
            continue
    return out


def _table_row_counts(conn: sqlite3.Connection) -> dict[str, int]:
    out: dict[str, int] = {}
    for table in ("pearls", "kv", "moments"):
        try:
            row = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
            out[table] = int(row[0] or 0)
        except Exception:
            out[table] = 0
    return out


def sqlite_table_counts(path: Path) -> dict[str, int]:
    """Comptes pearls / kv / moments sur un fichier sqlite (lecture seule)."""
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        return _table_row_counts(conn)
    finally:
        conn.close()


def backup_database(dest: Path) -> dict[str, Any]:
    """Copie cohérente à chaud (API backup), même si la base est en WAL."""
    src = db_path()
    if not src.is_file():
        raise FileNotFoundError(f"sqlite absent : {src}")
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        dest.unlink()
    src_conn = sqlite3.connect(str(src), timeout=30.0)
    dst_conn = sqlite3.connect(str(dest))
    try:
        src_conn.execute("PRAGMA busy_timeout=30000")
        with _LOCK:
            src_conn.backup(dst_conn)
        dst_conn.commit()
    finally:
        dst_conn.close()
        src_conn.close()
    return verify_database_backup(src, dest)


def verify_database_backup(src: Path, dest: Path) -> dict[str, Any]:
    """integrity_check + mêmes comptes de lignes sur la copie."""
    src_counts = sqlite_table_counts(src)
    dst_counts = sqlite_table_counts(dest)
    if src_counts != dst_counts:
        raise RuntimeError(f"backup sqlite : comptes différents {src_counts} vs {dst_counts}")
    conn = sqlite3.connect(f"file:{dest}?mode=ro", uri=True)
    try:
        row = conn.execute("PRAGMA integrity_check").fetchone()
        status = str(row[0] if row else "")
    finally:
        conn.close()
    if status.lower() != "ok":
        raise RuntimeError(f"backup sqlite : integrity_check={status!r}")
    return {"integrity": status, "counts": dst_counts, "source": str(src), "dest": str(dest)}


def count_kv_rows() -> int:
    try:
        with _LOCK:
            row = _connect().execute("SELECT COUNT(*) FROM kv").fetchone()
            return int(row[0] or 0)
    except Exception:
        return 0


def count_moments(voyage_id: str | None = None) -> int:
    try:
        with _LOCK:
            if voyage_id:
                row = _connect().execute(
                    "SELECT COUNT(*) FROM moments WHERE voyage_id = ?", (voyage_id,),
                ).fetchone()
            else:
                row = _connect().execute("SELECT COUNT(*) FROM moments").fetchone()
        return int((row[0] if row else 0) or 0)
    except Exception:
        return 0


def info() -> dict[str, Any]:
    p = db_path()
    size = p.stat().st_size if p.exists() else 0
    return {
        "path": str(p),
        "bytes": size,
        **count_pearls(),
        "escales": kv_count("escale"),
        "stories": kv_count("story"),
        "truth": kv_count("truth"),
        "hindcast": kv_count("hindcast"),
        "watch": kv_count("watch"),
        "enrich": kv_count("enrich"),
        "filmStory": kv_count("film-story"),
        "moments": count_moments(),
    }
