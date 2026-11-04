"""Toponymes de la route — une table, une règle.

Pays, territoires et eaux : exonyme de la langue du récit, jamais une
traduction automatique. Ports, AMP, stations, projets : nom d'origine,
casse normalisée. Îles partagées : les deux formes distinguées
(Saint-Martin / Sint Maarten, Hispaniola, Timor, Nouvelle-Guinée).

Table : ``src/engine/toponymsTable.json`` (JO/UNTERM + Marine Regions).
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

_TABLE_PATH = (
    Path(__file__).resolve().parent.parent / "src" / "engine" / "toponymsTable.json"
)

_PREP_HEAD = re.compile(r"^(de |du |des |d['’])", re.I)
_PAREN_RE = re.compile(r"\(([^)]+)\)")
_EEZ_JARGON_RE = re.compile(
    r"zone économique exclusive|exclusive economic zone|eez|\bzee\b",
    re.I,
)
_DISTINGUISHER_RE = re.compile(
    r"\s*\((?:partie française|partie néerlandaise|french side|dutch side|"
    r"partie orientale|partie occidentale|eastern side|west(?:ern)? (?:timor|new guinea)|"
    r"timor occidental|nouvelle-guinée occidentale)\)\s*",
    re.I,
)
_WATERS_CHUNK_RE = re.compile(
    r"(?:les eaux|celles|waters)\s+(?:de |d['’]|du |des )?"
    r"([^,;.]+?)(?=, (?:puis|then)\b|\.|$)",
    re.I,
)
_SMALL_WORDS = frozenset({
    "de", "da", "do", "del", "della", "of", "the", "and", "la", "le", "du", "des",
    "y", "e", "di",
})
_ACCENT_OVERLAY = {
    "coruna": "Coruña",
    "coruña": "Coruña",
    "muxia": "Muxía",
    "muxía": "Muxía",
    "camarinas": "Camariñas",
    "camariñas": "Camariñas",
    "almeria": "Almería",
    "almería": "Almería",
    "mahon": "Mahón",
    "mahón": "Mahón",
}


def _en(lang: str) -> bool:
    return str(lang or "").lower().startswith("en")


@lru_cache(maxsize=1)
def _payload() -> dict:
    return json.loads(_TABLE_PATH.read_text(encoding="utf-8"))


def sources() -> list[str]:
    return list(_payload().get("sources") or [])


def territories() -> list[dict]:
    return list(_payload().get("territories") or [])


@lru_cache(maxsize=1)
def _indexes() -> tuple[list[dict], dict[int, dict], dict[str, dict], dict[str, dict], list[tuple[re.Pattern, dict]]]:
    rows = territories()
    by_mrgid: dict[int, dict] = {}
    by_iso: dict[str, dict] = {}
    by_territory: dict[str, dict] = {}
    alias_rx: list[tuple[re.Pattern, dict]] = []
    for row in rows:
        mrgid = row.get("mrgid")
        if isinstance(mrgid, int):
            by_mrgid.setdefault(mrgid, row)
        iso = str(row.get("iso") or "").strip().upper()
        if iso and iso not in by_iso:
            by_iso[iso] = row
        terr = str(row.get("territory") or "").strip()
        if terr:
            by_territory[terr] = row
        for raw in row.get("aliases") or []:
            alias_rx.append((re.compile(str(raw), re.I), row))
    # Extra French EEZ MRGIDs (ici_engine.FRENCH_EEZ_MRGID) share the FR / overseas rows.
    extra_mrgid = {
        48966: "fr", 48976: "fr",
        48948: "nc",
        48945: "tf", 8341: "tf", 8339: "tf", 8340: "tf",
        8386: "tf", 8385: "tf", 8387: "tf",
    }
    by_id = {str(r.get("id")): r for r in rows}
    for mid, rid in extra_mrgid.items():
        if rid in by_id:
            by_mrgid.setdefault(mid, by_id[rid])
    return rows, by_mrgid, by_iso, by_territory, alias_rx


def _match_aliases(text: str, alias_rx: list[tuple[re.Pattern, dict]]) -> Optional[dict]:
    blob = str(text or "").strip()
    if not blob:
        return None
    for rx, row in alias_rx:
        if rx.search(blob):
            return row
    return None


def lookup(
    raw: str | None = None,
    *,
    mrgid: int | None = None,
    iso: str | None = None,
    territory: str | None = None,
) -> Optional[dict]:
    """Première entrée de table pour un nom de source, un MRGID, un ISO ou une clé outre-mer."""
    _rows, by_mrgid, by_iso, by_territory, alias_rx = _indexes()
    key = str(territory or "").strip()
    if key and key in by_territory and key != "france_metropolitaine":
        return by_territory[key]
    if isinstance(mrgid, int) and mrgid in by_mrgid:
        return by_mrgid[mrgid]
    if key and key in by_territory:
        return by_territory[key]
    code = str(iso or "").strip().upper()
    if code and code in by_iso:
        return by_iso[code]
    blob = str(raw or "").strip()
    if not blob:
        return None
    inner = ""
    found = _PAREN_RE.search(blob)
    if found:
        inner = found.group(1).strip()
    if inner:
        hit = _match_aliases(inner, alias_rx)
        if hit:
            return hit
    return _match_aliases(blob, alias_rx)


def _overseas_territory(row: dict) -> bool:
    terr = str(row.get("territory") or "").strip()
    return bool(terr) and terr != "france_metropolitaine"


def _waters_tail(row: dict, lang: str) -> str:
    if _en(lang):
        extra = str(row.get("en") or "").strip()
        adj = str(row.get("adj_en") or "").strip()
        if extra and (row.get("shared") or _overseas_territory(row)):
            return extra
        if adj:
            return adj
        return extra
    prep = str(row.get("prep_fr") or "").strip()
    adj = str(row.get("adj_fr") or "").strip()
    if prep and (row.get("shared") or _overseas_territory(row) or not adj):
        return prep
    if adj:
        return adj
    return prep or str(row.get("fr") or "").strip()


def _is_prep(tail: str) -> bool:
    return bool(_PREP_HEAD.match(str(tail or "").strip()))


def waters_label(
    name: str | None,
    lang: str = "fr",
    *,
    mrgid: int | None = None,
    iso: str | None = None,
    territory: str | None = None,
) -> str:
    """« les eaux espagnoles » / « Spanish waters » / « haute mer »."""
    raw = str(name or "")
    row = lookup(raw, mrgid=mrgid, iso=iso, territory=territory)
    if row and row.get("kind") == "high_seas":
        return "the high seas" if _en(lang) else "haute mer"
    if row and row.get("kind") == "overlap":
        return (
            "disputed waters of Western Sahara"
            if _en(lang) else
            "les eaux disputées du Sahara occidental"
        )
    if row:
        tail = _waters_tail(row, lang)
        if not tail:
            return ""
        if _en(lang):
            return f"{tail} waters" if "water" not in tail.casefold() else tail
        if tail.startswith("disput"):
            return f"les eaux {tail}"
        return f"les eaux {tail}"
    rest = _EEZ_JARGON_RE.sub("", raw).strip(" ()-")
    rest = re.sub(r"\s*\([^)]*$", "", rest).strip(" ()-")
    if _EEZ_JARGON_RE.search(rest):
        return ""
    had = bool(_EEZ_JARGON_RE.search(raw) or re.search(r"eaux", raw, re.I))
    if rest and had:
        return f"{rest} waters" if _en(lang) else f"les eaux {rest}"
    return ""


def sheet_label(
    name: str | None,
    lang: str = "fr",
    *,
    mrgid: int | None = None,
    iso: str | None = None,
    territory: str | None = None,
) -> str:
    """Fiche « ici » : « Zone économique exclusive française (Guadeloupe) »."""
    row = lookup(name, mrgid=mrgid, iso=iso, territory=territory)
    if not row:
        return ""
    if row.get("kind") == "high_seas":
        return "High seas" if _en(lang) else "Haute mer"
    if row.get("kind") == "overlap":
        return (
            "Disputed waters of Western Sahara"
            if _en(lang) else
            "Eaux disputées du Sahara occidental"
        )
    if _en(lang):
        adj_en = str(row.get("adj_en") or "").strip()
        extra = str(row.get("en") or "").strip()
        terr_key = str(row.get("territory") or "")
        if adj_en:
            if terr_key == "france_metropolitaine":
                return f"{adj_en} EEZ (metropolitan France)"
            if terr_key and extra and extra.lower() not in adj_en.lower():
                return f"{adj_en} EEZ ({extra})"
            return f"{adj_en} EEZ"
        return f"{extra} EEZ" if extra else "EEZ"
    adj_eez = str(row.get("adj_eez_fr") or "").strip()
    prep = str(row.get("prep_fr") or "").strip()
    if adj_eez:
        label = f"Zone économique exclusive {adj_eez}"
        extra = str(row.get("fr") or "").strip()
        terr_key = str(row.get("territory") or "")
        if terr_key and terr_key != "france_metropolitaine" and extra and extra.lower() not in label.lower():
            label = f"{label} ({extra})"
        elif terr_key == "france_metropolitaine":
            label = f"{label} (France métropolitaine)"
        return label
    if prep:
        return f"Zone économique exclusive {prep}"
    adj = str(row.get("adj_fr") or "").strip()
    if adj:
        # Fiche : adjectif singulier si le pluriel des eaux finit par « es ».
        singular = adj[:-1] if adj.endswith("es") and not adj.endswith("aises") else adj
        if adj.endswith("iennes"):
            singular = adj[:-1]
        elif adj.endswith("aises") or adj.endswith("oles"):
            singular = adj[:-1]
        return f"Zone économique exclusive {singular}"
    return f"Zone économique exclusive ({row.get('fr')})"


def names_for(
    name: str | None = None,
    *,
    mrgid: int | None = None,
    iso: str | None = None,
    territory: str | None = None,
) -> Optional[dict[str, str]]:
    row = lookup(name, mrgid=mrgid, iso=iso, territory=territory)
    if not row:
        return None
    return {
        "fr": sheet_label(name, "fr", mrgid=mrgid, iso=iso, territory=territory),
        "en": sheet_label(name, "en", mrgid=mrgid, iso=iso, territory=territory),
    }


def identity_key(
    raw: str | None = None,
    *,
    mrgid: int | None = None,
    iso: str | None = None,
    territory: str | None = None,
    lang: str = "fr",
) -> str:
    """Clé de dédoublonnage d'identité (pas à l'oreille) : MF ≠ SX."""
    row = lookup(raw, mrgid=mrgid, iso=iso, territory=territory)
    if row and row.get("id"):
        return str(row["id"])
    lab = waters_label(raw, lang, mrgid=mrgid, iso=iso, territory=territory)
    return re.sub(r"[\s-]+", " ", (lab or str(raw or "")).casefold()).strip()


def group_waters(members: list, lang: str = "fr") -> str:
    """« les eaux de Saint-Christophe-et-Niévès, puis celles de Saint-Eustache »."""
    en = _en(lang)
    parts: list[str] = []
    seen: set[str] = set()
    for member in members or []:
        raw = str(member or "")
        row = lookup(raw)
        if row is None:
            lab = waters_label(raw, lang)
            key = identity_key(raw, lang=lang)
            if not lab or key in seen:
                continue
            seen.add(key)
            parts.append(lab)
            continue
        key = str(row.get("id") or identity_key(raw, lang=lang))
        if key in seen:
            continue
        seen.add(key)
        tail = _waters_tail(row, lang)
        if not tail:
            continue
        full = f"{tail} waters" if en else f"les eaux {tail}"
        if en or not parts or not _is_prep(tail):
            parts.append(full)
        else:
            parts.append(f"celles {tail}")
    if not parts:
        return ""
    return ", then ".join(parts) if en else ", puis ".join(parts)


def _plain_core(label: str) -> str:
    s = _DISTINGUISHER_RE.sub(" ", str(label or ""))
    s = s.casefold()
    s = re.sub(r"\bles eaux\b|\bcelles\b|\bwaters\b", " ", s)
    s = re.sub(r"\b(de|du|des|d['’]|the)\b", " ", s)
    s = re.sub(r"\bsint\b", "saint", s)
    s = re.sub(r"\bmaarten\b", "martin", s)
    s = re.sub(r"[^a-zà-ÿ]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def consecutive_homonyms(text: str) -> list[str]:
    """Deux eaux d'affilée au même nom affiché, sans distinguo — 0 attendu."""
    blob = str(text or "")
    hits: list[str] = []
    chunks = [m.group(0) for m in _WATERS_CHUNK_RE.finditer(blob)]
    prev_core = ""
    prev_raw = ""
    prev_distinguished = False
    for raw in chunks:
        distinguished = bool(_DISTINGUISHER_RE.search(raw))
        core = _plain_core(raw)
        if not core:
            prev_core, prev_raw, prev_distinguished = core, raw, distinguished
            continue
        if prev_core and core == prev_core and not (distinguished and prev_distinguished):
            hits.append(f"{prev_raw} → {raw}")
        prev_core, prev_raw, prev_distinguished = core, raw, distinguished
    return hits


# Noms de ports bruts (jeux WPI / OSM en casse de titre ou sans accents) que le
# film disait tels quels en français : « Fort De France », « Degrad Des Cannes »,
# « L'ile Rousse », « St Johns », « Basse Terre ». Clé : minuscules sans accents.
_PORT_NAME_FIX = {
    "fort de france": "Fort-de-France",
    "degrad des cannes": "Dégrad des Cannes",
    "l'ile rousse": "L'Île-Rousse",
    "l ile rousse": "L'Île-Rousse",
    "ile rousse": "L'Île-Rousse",
    "st johns": "Saint John's",
    "st john's": "Saint John's",
    "st. john's": "Saint John's",
    "saint johns": "Saint John's",
    "basse terre": "Basse-Terre",
    "pointe a pitre": "Pointe-à-Pitre",
    "st george's": "Saint George's",
    "st georges": "Saint George's",
    "st. george's": "Saint George's",
    "pago pago harbor": "Pago Pago",
    "st pierre": "Saint-Pierre",
    "st denis": "Saint-Denis",
    "saint denis": "Saint-Denis",
}


def _port_fix_key(s: str) -> str:
    import unicodedata  # noqa: PLC0415
    folded = "".join(
        c for c in unicodedata.normalize("NFKD", s.replace("’", "'")) if not unicodedata.combining(c)
    )
    return re.sub(r"\s+", " ", folded).strip().casefold()


def origin_name(raw: str | None) -> str:
    """Nom d'origine : MAJUSCULES → casse de titre ; accents RC19 ; le mixte reste.

    Quelques ports bruts connus reprennent leur graphie (_PORT_NAME_FIX).
    """
    s = re.sub(r"\s+", " ", str(raw or "")).strip()
    if not s:
        return ""
    fixed = _PORT_NAME_FIX.get(_port_fix_key(s))
    if fixed:
        return fixed
    letters = re.sub(r"[^A-Za-zÀ-ÿ]", "", s)
    if len(letters) < 3:
        return s
    up = sum(1 for c in letters if c.isupper())
    if up / len(letters) < 0.85:
        return s

    def one_word(word: str, index: int) -> str:
        folded = word.casefold()
        if folded in _ACCENT_OVERLAY:
            return _ACCENT_OVERLAY[folded]
        bits = folded.split("-")
        out = []
        for j, bit in enumerate(bits):
            if not bit:
                continue
            if bit in _ACCENT_OVERLAY:
                out.append(_ACCENT_OVERLAY[bit])
                continue
            if (index > 0 or j > 0) and bit in _SMALL_WORDS:
                out.append(bit)
                continue
            out.append(bit[:1].upper() + bit[1:])
        return "-".join(out) if out else word

    return " ".join(one_word(w, i) for i, w in enumerate(s.split(" ")))


def localize_ctx_places(ctx: dict | None, lang: str = "fr") -> dict:
    """Le paquet de faits du chat : eaux et pays passent par la table."""
    if not isinstance(ctx, dict):
        return {}
    around = ctx.get("around") if isinstance(ctx.get("around"), dict) else None
    if around:
        zee = around.get("zee") if isinstance(around.get("zee"), dict) else None
        if zee:
            spoken = waters_label(
                zee.get("name"), lang, mrgid=_as_int(zee.get("mrgid")),
            )
            if spoken:
                zee["spoken"] = spoken
                zee["name"] = spoken
        for key in (
            "ports", "portsOfEntry", "protectedAreas", "marinas",
            "harbourMasters", "projects", "science", "aidsToNavigation",
        ):
            for item in around.get(key) or []:
                if isinstance(item, dict) and item.get("name"):
                    item["name"] = origin_name(item["name"])
        ctx["around"] = around
    for entry in ctx.get("journal") or []:
        if not isinstance(entry, dict):
            continue
        if entry.get("kind") == "zee" and entry.get("name"):
            spoken = waters_label(entry.get("name"), lang, mrgid=_as_int(entry.get("mrgid")))
            if spoken:
                entry["name"] = spoken
        elif entry.get("name"):
            entry["name"] = origin_name(entry["name"])
    return ctx


def _as_int(value: Any) -> Optional[int]:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None
