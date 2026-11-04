#!/usr/bin/env python3
"""Mesure AM1A — AMP traversées / longées par la route officielle.

Avant : centroïdes de GET /export/amp.geojson, portée = distance au point.
Après : polygones de GET /amp?bbox= (cache Mongo, span 9°), portée = distance
à la limite (0 si le point est dedans). Longée = ≤ 15 nm.

Usage :
  python3 scripts/amp-route.py                     # voyage du poste :8010 + BI live
  python3 scripts/amp-route.py --api http://127.0.0.1:8011
  python3 scripts/amp-route.py --jpeg ../docs/recette/lot-am1/03-mesure.webp
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from collections import OrderedDict
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen

_SERVER = Path(__file__).resolve().parent.parent / "server"
if str(_SERVER) not in sys.path:
    sys.path.insert(0, str(_SERVER))

from ici_engine import (  # noqa: E402
    haversine_nm,
    is_fishing_amp,
    is_jurisdiction_amp,
    slim_amp_entry,
    spoken_amp_name,
    wrap_lon,
)
from toponyms import origin_name  # noqa: E402

DEFAULT_API = "http://127.0.0.1:8010"
FALLBACK_API = "https://naviguide.fr"
DEFAULT_BI = "https://blueintelligence.online/api"
ALONG_NM = 15.0
SAMPLE_NM = 12.0
USER_AGENT = "NAVIGUIDE-simulator/am1a-amp-route"


def _get(url: str, timeout: float = 60.0) -> dict:
    req = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    with urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def _load_voyage(api: str) -> dict:
    last = None
    for base in (api, FALLBACK_API) if api.rstrip("/") != FALLBACK_API else (api,):
        try:
            data = _get(f"{base.rstrip('/')}/voyage/official", timeout=20.0)
            if isinstance(data, dict) and data.get("points"):
                return data
        except (URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
            last = exc
    raise SystemExit(f"GET /voyage/official impossible ({last})")


def _sample(points: list[dict], step_nm: float = SAMPLE_NM) -> list[dict]:
    out: list[dict] = []
    last_nm = None
    for p in points or []:
        if not isinstance(p, dict):
            continue
        if p.get("jump") or p.get("nonMaritime"):
            last_nm = None
            continue
        try:
            lat, lon = float(p["lat"]), float(p["lon"])
        except (KeyError, TypeError, ValueError):
            continue
        cum = p.get("cumNm")
        try:
            cum = float(cum) if cum is not None else None
        except (TypeError, ValueError):
            cum = None
        if out and last_nm is not None and cum is not None:
            if cum - last_nm < step_nm - 0.05:
                continue
        elif out and cum is None:
            prev = out[-1]
            if haversine_nm(prev["lat"], prev["lon"], lat, lon) < step_nm - 0.05:
                continue
        rec = {"lat": lat, "lon": lon, "cumNm": cum}
        out.append(rec)
        last_nm = cum if cum is not None else last_nm
    return out


def _marks(voy: dict) -> list[dict]:
    raw = [m for m in (voy.get("marks") or []) if isinstance(m, dict) and m.get("name")]
    out = []
    for m in raw:
        try:
            nm = float(m.get("nm") if m.get("nm") is not None else m.get("filmNm"))
        except (TypeError, ValueError):
            continue
        out.append({"name": str(m["name"]), "nm": nm})
    out.sort(key=lambda x: x["nm"])
    return out


def _leg_of(cum: float | None, marks: list[dict]) -> tuple[str, str] | None:
    if cum is None or len(marks) < 2:
        return None
    last_i = len(marks) - 2
    for i, (a, b) in enumerate(zip(marks, marks[1:])):
        if a["nm"] <= cum < b["nm"] or (i == last_i and cum <= b["nm"] + 0.05):
            return a["name"], b["name"]
    if cum < marks[0]["nm"]:
        return marks[0]["name"], marks[1]["name"]
    return marks[-2]["name"], marks[-1]["name"]


def _site_id(feat: dict) -> str:
    props = feat.get("properties") or {}
    return str(props.get("site_id") or props.get("id") or feat.get("id") or "")


def _name_of(feat: dict) -> str:
    props = feat.get("properties") or {}
    raw = props.get("name") or props.get("title") or ""
    return origin_name(spoken_amp_name(raw)) or str(raw)


def _tiles_for(samples: list[dict]) -> list[str]:
    """Tuiles 8° + marge 0,5° → span 9° (branche cache Mongo, pas ArcGIS)."""
    keys = OrderedDict()
    for p in samples:
        lat = p["lat"]
        lon = wrap_lon(p["lon"])
        slat = math.floor(lat / 8.0) * 8.0
        slon = math.floor(lon / 8.0) * 8.0
        bbox = f"{slon - 0.5},{slat - 0.5},{slon + 8.5},{slat + 8.5}"
        keys[bbox] = True
        lat_in = lat - slat
        lon_in = lon - slon
        extra = []
        if lat_in < 0.3:
            extra.append((-8.0, 0.0))
        if lat_in > 7.7:
            extra.append((8.0, 0.0))
        if lon_in < 0.3:
            extra.append((0.0, -8.0))
        if lon_in > 7.7:
            extra.append((0.0, 8.0))
        for dlat, dlon in extra:
            slat2 = math.floor((lat + dlat) / 8.0) * 8.0
            slon2 = math.floor(wrap_lon(lon + dlon) / 8.0) * 8.0
            bbox2 = f"{slon2 - 0.5},{slat2 - 0.5},{slon2 + 8.5},{slat2 + 8.5}"
            keys[bbox2] = True
    return list(keys)


def _fetch_polygons(bi: str, samples: list[dict]) -> list[dict]:
    feats: list[dict] = []
    seen = set()
    for bbox in _tiles_for(samples):
        try:
            data = _get(f"{bi.rstrip('/')}/amp?bbox={bbox}", timeout=60.0)
        except (URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
            print(f"  GET /amp?bbox={bbox} : {exc}", file=sys.stderr)
            continue
        for feat in data.get("features") or []:
            sid = _site_id(feat) or _name_of(feat)
            if not sid or sid in seen:
                continue
            seen.add(sid)
            feats.append(feat)
    return feats


def _before_hits(samples: list[dict], export_feats: list[dict]) -> dict[str, dict]:
    """siteId → {name, min_nm, legs} avec distance au centroïde."""
    hits: dict[str, dict] = {}
    for feat in export_feats:
        props = feat.get("properties") or {}
        try:
            clat = float(props.get("lat"))
            clon = float(props.get("lon"))
        except (TypeError, ValueError):
            geom = feat.get("geometry") or {}
            coords = geom.get("coordinates") or []
            if geom.get("type") == "Point" and len(coords) >= 2:
                clon, clat = float(coords[0]), float(coords[1])
            else:
                continue
        item = {"name": _name_of(feat), "site_id": _site_id(feat), "designation": props.get("designation")}
        if is_fishing_amp(item) or is_jurisdiction_amp(item) or not item["name"]:
            continue
        sid = item["site_id"] or item["name"]
        for p in samples:
            nm = haversine_nm(p["lat"], p["lon"], clat, clon)
            if nm > ALONG_NM + 0.05:
                continue
            rec = hits.setdefault(sid, {"name": item["name"], "min_nm": nm, "legs": set()})
            rec["min_nm"] = min(rec["min_nm"], nm)
            if p.get("leg"):
                rec["legs"].add(p["leg"])
    return hits


def _after_hits(samples: list[dict], poly_feats: list[dict]) -> dict[str, dict]:
    from shapely.geometry import box, shape  # noqa: PLC0415
    from shapely.strtree import STRtree  # noqa: PLC0415

    geoms, feats = [], []
    for feat in poly_feats:
        try:
            g = shape(feat.get("geometry") or {})
        except Exception:
            continue
        if g.is_empty:
            continue
        geoms.append(g)
        feats.append(feat)
    if not geoms:
        return {}
    tree = STRtree(geoms)
    hits: dict[str, dict] = {}
    for p in samples:
        lat, lon = p["lat"], wrap_lon(p["lon"])
        dlat = 0.5
        dlon = 0.5 / max(0.2, abs(math.cos(math.radians(lat))))
        env = box(lon - dlon, lat - dlat, lon + dlon, lat + dlat)
        try:
            idxs = tree.query(env)
        except Exception:
            continue
        for i in idxs:
            feat = feats[int(i)]
            item = slim_amp_entry(feat, lat, lon, source="polygon")
            if not item:
                continue
            if not item.get("inside") and float(item.get("nm") or 999) > ALONG_NM + 0.05:
                continue
            sid = str(item.get("siteId") or item.get("name"))
            rec = hits.setdefault(sid, {
                "name": item["name"],
                "inside": False,
                "min_nm": float(item.get("nm") or 0),
                "legs": set(),
                "legs_inside": set(),
            })
            rec["min_nm"] = min(rec["min_nm"], float(item.get("nm") or 0))
            if item.get("inside"):
                rec["inside"] = True
                rec["min_nm"] = 0.0
                if p.get("leg"):
                    rec["legs_inside"].add(p["leg"])
            if p.get("leg"):
                rec["legs"].add(p["leg"])
    return hits


def _leg_report(marks: list[dict], before: dict, after: dict) -> list[dict]:
    legs = [(a["name"], b["name"]) for a, b in zip(marks, marks[1:])]
    rows = []
    for leg in legs:
        b_cross, b_along = [], []
        a_cross, a_along = [], []
        for rec in before.values():
            if leg not in rec["legs"]:
                continue
            # centroïde : « traversée » n'existe pas ; on range tout en longée
            b_along.append(rec)
        for rec in after.values():
            if leg in (rec.get("legs_inside") or set()):
                a_cross.append(rec)
            elif leg in rec["legs"]:
                a_along.append(rec)
        b_along.sort(key=lambda r: r["min_nm"])
        a_cross.sort(key=lambda r: r["name"])
        a_along.sort(key=lambda r: r["min_nm"])
        rows.append({
            "from": leg[0], "to": leg[1],
            "before_along": b_along, "before_n": len(b_along),
            "after_cross": a_cross, "after_along": a_along,
            "after_cross_n": len(a_cross), "after_along_n": len(a_along),
        })
    return rows


def _fmt_leg(name_a: str, name_b: str) -> str:
    def short(s: str) -> str:
        s = s.split("(")[0].strip()
        return s if len(s) <= 28 else s[:26] + "…"
    return f"{short(name_a)} → {short(name_b)}"


def render_lines(stats: dict, rows: list[dict], bi_total: int | None) -> list[str]:
    lines = [
        "AM1A — AMP de la route officielle (≤ 15 nm)",
        f"Couche BI : {bi_total if bi_total is not None else '?'} sites (GET /amp/stats)",
        f"Échantillons : {stats['samples']} points / {stats['legs']} jambes",
        f"Avant (centroïdes) : {stats['before_n']} AMP à portée",
        f"Après (polygones)  : {stats['after_cross_n']} traversées, "
        f"{stats['after_along_n']} longées, {stats['after_n']} distinctes",
        "",
        f"{'Jambe':<42} {'av.':>4} {'tr.':>4} {'lg.':>4}",
    ]
    for row in rows:
        label = _fmt_leg(row["from"], row["to"])
        lines.append(
            f"{label:<42} {row['before_n']:>4} {row['after_cross_n']:>4} {row['after_along_n']:>4}"
        )
    return lines


def _save_webp(img, path: Path) -> None:
    """WebP q85, ou lossless si ce rendu est plus petit (texte fin)."""
    import io

    lossy = io.BytesIO()
    img.save(lossy, "WEBP", quality=85, method=6)
    exact = io.BytesIO()
    img.save(exact, "WEBP", lossless=True, quality=100, method=6)
    path.write_bytes(exact.getvalue() if exact.tell() < lossy.tell() else lossy.getvalue())


def write_jpeg(path: Path, lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        from PIL import Image, ImageDraw, ImageFont  # noqa: PLC0415
    except ImportError:
        _write_jpeg_ppm(path, lines)
        return
    w, h = 1280, 800
    img = Image.new("RGB", (w, h), (15, 23, 42))
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("/System/Library/Fonts/Menlo.ttc", 14)
        font_b = ImageFont.truetype("/System/Library/Fonts/Menlo.ttc", 18)
    except OSError:
        font = ImageFont.load_default()
        font_b = font
    y = 24
    draw.text((32, y), lines[0], fill=(226, 232, 240), font=font_b)
    y += 36
    for line in lines[1:]:
        fill = (148, 163, 184) if line.startswith("Jambe") or not line else (226, 232, 240)
        draw.text((32, y), line, fill=fill, font=font)
        y += 18
        if y > h - 24:
            break
    if path.suffix.lower() == ".webp":
        _save_webp(img, path)
    else:
        img.save(path, "JPEG", quality=70, optimize=True)


def _write_jpeg_ppm(path: Path, lines: list[str]) -> None:
    """Repli sans Pillow : PPM 1280×800 puis `sips`, WebP via `cwebp` si le chemin l'exige."""
    import shutil
    import subprocess
    import tempfile

    w, h = 1280, 800
    ppm = bytearray(b"P6\n%d %d\n255\n" % (w, h))
    bg = bytes((15, 23, 42))
    row = bg * w
    body = row * h
    # pas de texte sans fonte : bandeau + lignes en ASCII 5×7 trop pauvre ;
    # on laisse le JPEG lisible via sips + texte overlay n'est pas dispo.
    ppm.extend(body)
    tmp = Path(tempfile.mkstemp(suffix=".ppm")[1])
    tmp.write_bytes(ppm)
    sips = shutil.which("sips")
    want_webp = path.suffix.lower() == ".webp"
    if not sips:
        if not want_webp:
            path.write_bytes(ppm)
        tmp.unlink(missing_ok=True)
        path.with_suffix(".txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
        return
    raster = Path(tempfile.mkstemp(suffix=".jpg")[1]) if want_webp else path
    subprocess.run(
        [sips, "-s", "format", "jpeg", "-s", "formatOptions", "70", str(tmp), "--out", str(raster)],
        check=False, capture_output=True,
    )
    tmp.unlink(missing_ok=True)
    if want_webp:
        cwebp = shutil.which("cwebp")
        if cwebp and raster.is_file():
            q = Path(tempfile.mkstemp(suffix=".webp")[1])
            exact = Path(tempfile.mkstemp(suffix=".webp")[1])
            subprocess.run(
                [cwebp, "-q", "85", "-m", "6", "-metadata", "none", str(raster), "-o", str(q)],
                check=False, capture_output=True,
            )
            subprocess.run(
                [cwebp, "-lossless", "-z", "6", "-metadata", "none", str(raster), "-o", str(exact)],
                check=False, capture_output=True,
            )
            pick = exact if exact.is_file() and q.is_file() and exact.stat().st_size < q.stat().st_size else q
            if pick.is_file() and pick.stat().st_size:
                path.write_bytes(pick.read_bytes())
            q.unlink(missing_ok=True)
            exact.unlink(missing_ok=True)
        raster.unlink(missing_ok=True)
    # annoter avec un fichier texte à côté si sips a tout aplati
    path.with_suffix(".txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Mesure AMP avant/après polygones.")
    p.add_argument("--api", default=DEFAULT_API, help="API voyage (défaut 127.0.0.1:8010)")
    p.add_argument("--bi", default=DEFAULT_BI, help="API Blue Intelligence")
    p.add_argument("--jpeg", default="", help="Chemin 1280×800 de la table (.webp ou .jpg)")
    args = p.parse_args(argv)

    print("Voyage officiel…", flush=True)
    voy = _load_voyage(args.api)
    marks = _marks(voy)
    samples = _sample(voy.get("points") or [])
    for s in samples:
        s["leg"] = _leg_of(s.get("cumNm"), marks)
    print(f"  {len(voy.get('points') or [])} points, {len(samples)} échantillons, {max(0, len(marks)-1)} jambes", flush=True)

    bi_total = None
    try:
        st = _get(f"{args.bi.rstrip('/')}/amp/stats", timeout=15.0)
        bi_total = st.get("total")
        print(f"  GET /amp/stats total = {bi_total}", flush=True)
    except (URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
        print(f"  GET /amp/stats : {exc}", file=sys.stderr)

    print("Export centroïdes (avant)…", flush=True)
    try:
        export = _get(f"{args.bi.rstrip('/')}/export/amp.geojson", timeout=60.0)
        export_feats = export.get("features") or []
    except (URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
        print(f"  export : {exc}", file=sys.stderr)
        export_feats = []
    print(f"  {len(export_feats)} centroïdes", flush=True)

    print("Polygones GET /amp (après)…", flush=True)
    poly_feats = _fetch_polygons(args.bi, samples)
    print(f"  {len(poly_feats)} polygones uniques", flush=True)

    before = _before_hits(samples, export_feats)
    after = _after_hits(samples, poly_feats)
    rows = _leg_report(marks, before, after)
    after_cross = [r for r in after.values() if r.get("inside")]
    after_along = [r for r in after.values() if not r.get("inside")]
    stats = {
        "samples": len(samples),
        "legs": max(0, len(marks) - 1),
        "before_n": len(before),
        "after_n": len(after),
        "after_cross_n": len(after_cross),
        "after_along_n": len(after_along),
    }

    print()
    print(f"{'Jambe':<42} {'avant':>6} {'trav.':>6} {'long.':>6}")
    print("-" * 64)
    for row in rows:
        print(
            f"{_fmt_leg(row['from'], row['to']):<42} "
            f"{row['before_n']:>6} {row['after_cross_n']:>6} {row['after_along_n']:>6}"
        )
        for rec in row["after_cross"][:8]:
            print(f"    · traversée : {rec['name']}")
        for rec in row["after_along"][:6]:
            print(f"    · longée {rec['min_nm']:.1f} nm : {rec['name']}")
    print("-" * 64)
    print(
        f"TOTAL  avant (centroïdes ≤ {ALONG_NM:.0f} nm) : {stats['before_n']}  |  "
        f"après : {stats['after_cross_n']} traversées, {stats['after_along_n']} longées "
        f"({stats['after_n']} distinctes)"
    )
    if bi_total is not None:
        print(f"Couche BI : {bi_total} sites")

    if args.jpeg:
        lines = render_lines(stats, rows, bi_total)
        write_jpeg(Path(args.jpeg), lines)
        print(f"Capture : {args.jpeg}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
