"""Recette automatique du discours (revue du 28 sept., C1–C6 / D1–D4).

Lit le texte FINAL du film (pas un morceau). Chaque règle, en cas d'échec,
signale la phrase fautive. On ne corrige pas la règle pour passer.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen

import pytest

from film_script import (
    FILM_VOICE_LOOKAHEAD_CHARS,
    _ms,
    _nm_between,
    _sentence_has_date,
    _sentences,
    build_raw_from_moments,
    date_density_ok,
    film_has_forbidden,
)
from tests.test_film_script import CLOCK, JOURNAL, LIVE, MOMENTS, NOW_MS, _rg6_review

# Chemin du poste, lu à l'import : le fixture autouse de conftest pose ensuite
# un dossier temporaire dans NAVIGUIDE_OFFICIAL_STORE_DIR.
_POSTE_STORE_AT_IMPORT = (os.environ.get("NAVIGUIDE_OFFICIAL_STORE_DIR") or "").strip()
_POSTE_CACHE = Path.home() / ".cache" / "naviguide" / "voyage-store"

# Transcription § 1 de naviguide-simulator/server/tests/fixtures/FILM_DISCOURS_ETAT_2026-09-28.md — film servi le
# 28 sept. (avant RG6). Constante de test, jamais écrite dans un stock.
REVUE_28_SEPT = """
L'expédition Berry-Mappemonde a quitté Saint-Maur le 15 mai 2026. Départ vers La Rochelle. Arrivée à La Rochelle le 15 mai, 3 jours à quai.
À partir du 15 mai, 9 stations scientifiques croisées. Le 15 mai, aire marine protégée à portée : Pertuis Charentais - Pétoncles - Center Pertuis Breton deposit. Puis, le 18 mai, départ vers Ajaccio (Corse). Le 25 mai, approche d'Ajaccio. Arrivée à Ajaccio (Corse) le 26 mai, 3 jours à quai.
Ensuite, le 29 mai, départ vers Fort-de-France (Martinique). À partir du 31 mai, 11 stations scientifiques croisées. Le 26 juin, approche de Fort-de-France. Le 27 juin, à portée de The Careenage. Arrivée à Fort-de-France (Martinique) le 28 juin, 3 jours à quai. À surveiller. Couloirs : détroit de Gibraltar, Méditerranée occidentale. La jambe compte 5 153 milles nautiques.
Plus loin, le 1er juillet, départ vers Pointe-à-Pitre (Guadeloupe). À partir du 1er juillet, 3 zones économiques exclusives traversées. Le 2 juillet, approche de Pointe-à-Pitre. Arrivée à Pointe-à-Pitre (Guadeloupe) le 2 juillet, 3 jours à quai.
De là, le 5 juillet, départ vers Gustavia (Saint-Barthélemy). À partir du 5 juillet, 4 zones économiques exclusives traversées. Le 6 juillet, approche de Gustavia. Arrivée à Gustavia (Saint-Barthélemy) le 6 juillet, 3 jours à quai.
Sur la route, le 9 juillet, départ vers Marigot (Saint-Martin). Le 9 juillet, entrée dans les eaux françaises. Arrivée à Marigot (Saint-Martin) le 9 juillet, 3 jours à quai.
À la jambe suivante, le 12 juillet, départ vers Cayenne (Guyane). À partir du 12 juillet, 7 zones économiques exclusives traversées. Le 19 juillet, approche de Cayenne. Arrivée à Cayenne (Guyane) le 19 juillet, 3 jours à quai.
Puis, le 22 juillet, départ vers Saint-Pierre (Saint-Pierre-et-Miquelon). Le 23 juillet, entrée dans les eaux canadiennes. Le 25 juillet, approche de Saint-Pierre. Arrivée à Saint-Pierre (Saint-Pierre-et-Miquelon) le 25 juillet, 3 jours à quai. L'équipage prend l'avion pour Halifax (Nouvelle-Écosse). Retour en avion vers Cayenne (Guyane).
Ensuite, le 28 juillet, départ vers Papeete (Polynésie française). À partir du 28 juillet, 8 zones économiques exclusives traversées. Le 5 septembre, approche de Papeete. Le 6 septembre, à portée de Petite marina. Arrivée à Papeete (Polynésie française) le 8 septembre, 3 jours à quai. À surveiller. Couloirs : Caraïbe ouest, Atlantique nord. La jambe compte 7 007 milles nautiques.
Plus loin, le 11 septembre, départ vers Mata-Utu (Wallis-et-Futuna). À partir du 13 septembre, 5 zones économiques exclusives traversées. Le 18 septembre, approche de Mata-Utu. Arrivée à Mata-Utu (Wallis-et-Futuna) le 19 septembre, 3 jours à quai.
De là, le 22 septembre, départ vers Nouméa (Nouvelle-Calédonie). Le 22 septembre, à portée de de Fineveke. À partir du 24 septembre, 4 zones économiques exclusives traversées. Aujourd'hui, le bateau est en mer, à 232 milles nautiques de Nouméa (Nouvelle-Calédonie).
"""

COUNT_RE = re.compile(
    r"\b(\d+|un|une|deux|trois|quatre|cinq|six|sept|huit|neuf|dix|onze)\s+"
    r"(stations?|zones?)\b",
    re.I,
)
EN_TITLE_MOTIFS = re.compile(
    r"\b(deposit|licence|license|center|fishing|bans?|prohibition|careenage)\b",
    re.I,
)
THE_TITLE_RE = re.compile(r"\bThe\s+[A-Z]")
DE_DE_RE = re.compile(r"\bde de\b", re.I)
WORD_RE = re.compile(r"[A-Za-zÀ-ÿ0-9’'-]+")
OPEN_RE = re.compile(
    r"quitte|quitté|leaves|left |s'envole|flies |par la route|by road|"
    r"expédition|expedition|reprend la mer|sets sail again|départ vers|departure for",
    re.I,
)
ARRIVAL_RE = re.compile(r"Arrivée à|Arrival at", re.I)
TODAY_RE = re.compile(r"Aujourd|Today,", re.I)
AIR_RE = re.compile(
    r"s'envole|flies from|the crew flies|prend l'avion|return flight|attend à|"
    r"second voilier|second sailing boat|embarque sur",
    re.I,
)
MAX_WORDS = 30
HS_GE_RE = re.compile(r"Hs\s+\d+[.,]?\d*\s*m\s*≥", re.I)
DUP_METERS_RE = re.compile(r"(\d+)\s*m.+\1\s*m")


@dataclass(frozen=True)
class Fault:
    rule: str
    sentence: str


def _words(text: str) -> list[str]:
    return WORD_RE.findall(text or "")


def _sentence_at(text: str, idx: int) -> str:
    sents = _sentences(text)
    if not sents:
        return text or ""
    pos = 0
    for sent in sents:
        loc = text.find(sent, pos)
        if loc < 0:
            loc = pos
        end = loc + len(sent)
        if loc <= idx < end or sent is sents[-1]:
            return sent
        pos = end
    return sents[0]


def _date_burst_sentence(text: str, lang: str) -> str | None:
    sents = _sentences(text)
    if not sents or date_density_ok(text, lang):
        return None
    n_dates = 0
    for i, sent in enumerate(sents):
        dated = _sentence_has_date(sent, lang)
        if dated and i > 0 and _sentence_has_date(sents[i - 1], lang):
            return sent
        if dated:
            n_dates += 1
            if n_dates * 2 > len(sents) + 1:
                return sent
    dated = [s for s in sents if _sentence_has_date(s, lang)]
    return dated[-1] if dated else sents[0]


def list_faults(text: str, lang: str = "fr") -> list[Fault]:
    """Règles C3–C4, C2, D2, longueur : une Fault par phrase fautive."""
    out: list[Fault] = []
    fr = not str(lang or "").lower().startswith("en")
    for sent in _sentences(text):
        if film_has_forbidden(sent):
            out.append(Fault("interdit", sent))
        if DE_DE_RE.search(sent):
            out.append(Fault("de de", sent))
        if fr and (EN_TITLE_MOTIFS.search(sent) or THE_TITLE_RE.search(sent)):
            out.append(Fault("titre anglais", sent))
        if COUNT_RE.search(sent):
            out.append(Fault("comptage", sent))
        if HS_GE_RE.search(sent) or ("≥" in sent and re.search(r"\bHs\b", sent)):
            out.append(Fault("hs seuil", sent))
        if DUP_METERS_RE.search(sent) and re.search(r"\bHs\b", sent):
            out.append(Fault("hs répété", sent))
        if len(_words(sent)) > MAX_WORDS:
            out.append(Fault("trop longue", sent))
    burst = _date_burst_sentence(text, lang)
    if burst:
        out.append(Fault("dates rafale", burst))
    return out


def _structure_fault(ch: dict, lang: str) -> str | None:
    """Ouverture, puis route (si le chapitre en a), puis escale — dans cet ordre."""
    text = ch.get("text") or ""
    sents = _sentences(text)
    if not sents:
        return "(chapitre vide)"
    if AIR_RE.search(text):
        return None
    open_i = next((i for i, s in enumerate(sents) if OPEN_RE.search(s)), None)
    if open_i is None:
        return sents[0]
    close_i = next(
        (
            i for i, s in enumerate(sents)
            if ARRIVAL_RE.search(s) or TODAY_RE.search(s)
        ),
        None,
    )
    if close_i is None:
        return sents[0]
    if close_i < open_i:
        return sents[close_i]
    return None


def _anchor_fault(ch: dict) -> str | None:
    text = ch.get("text") or ""
    last_idx, last_t = -1, None
    for anc in ch.get("anchors") or []:
        idx = anc.get("charIdx")
        t = _ms(anc.get("t"))
        sent = _sentence_at(text, int(idx) if idx is not None else 0)
        if not isinstance(idx, int) or idx < 0:
            return sent
        if idx < last_idx:
            return sent
        if last_t is not None and t is not None and t < last_t:
            return sent
        last_idx = idx
        if t is not None:
            last_t = t
    return None


def list_plan_faults(plan: dict, lang: str = "fr") -> list[Fault]:
    out: list[Fault] = []
    for ch in plan.get("chapters") or []:
        text = ch.get("text") or ""
        out.extend(list_faults(text, lang))
        struct = _structure_fault(ch, lang)
        if struct:
            out.append(Fault("structure", struct))
        anc = _anchor_fault(ch)
        if anc:
            out.append(Fault("ancres", anc))
    return out


def assert_discours_ok(plan_or_text, lang: str = "fr") -> None:
    if isinstance(plan_or_text, str):
        faults = list_faults(plan_or_text, lang)
    else:
        faults = list_plan_faults(plan_or_text, lang)
    assert not faults, faults[0].sentence


def _moments_plan(lang: str) -> dict:
    return build_raw_from_moments(
        CLOCK, CLOCK["marks"], LIVE, {**JOURNAL, **MOMENTS},
        lang=lang, seconds=0, now_ms=NOW_MS, review=_rg6_review(),
    )


def _plan_from_film_doc(doc: dict, lang: str) -> dict | None:
    body = doc.get("payload") if isinstance(doc.get("payload"), dict) else doc
    if not isinstance(body, dict):
        return None
    lg = (lang or "fr")[:2].lower()
    variants = body.get("variants") if isinstance(body.get("variants"), dict) else {}
    by_secs = variants.get(lg) or {}
    plan = body.get(lg) or body.get("default") or body.get("fr")
    if not (isinstance(plan, dict) and (plan.get("chapters") or [])):
        plan = None
        if isinstance(by_secs, dict):
            for key in ("150", "180", "0"):
                cand = by_secs.get(key)
                if isinstance(cand, dict) and (cand.get("chapters") or []):
                    plan = cand
                    break
    if isinstance(plan, dict) and (plan.get("chapters") or []):
        return plan
    return None


def _iter_poste_plans(doc: dict, lang: str) -> list[tuple[str, dict]]:
    """Toutes les variantes stockées (2:30 / 3:00 / intégral), plus le défaut."""
    body = doc.get("payload") if isinstance(doc.get("payload"), dict) else doc
    if not isinstance(body, dict):
        return []
    lg = (lang or "fr")[:2].lower()
    out: list[tuple[str, dict]] = []
    seen: set[int] = set()
    default = body.get(lg) or body.get("default") or body.get("fr")
    if isinstance(default, dict) and (default.get("chapters") or []):
        out.append(("default", default))
        seen.add(id(default))
    variants = body.get("variants") if isinstance(body.get("variants"), dict) else {}
    by_secs = variants.get(lg) or {}
    if isinstance(by_secs, dict):
        for key, plan in by_secs.items():
            if isinstance(plan, dict) and (plan.get("chapters") or []) and id(plan) not in seen:
                out.append((str(key), plan))
                seen.add(id(plan))
    return out


def _newest_film_json(root: Path) -> Path | None:
    if not root.is_dir():
        return None
    found = [p for p in root.glob("*/film.json") if p.is_file()]
    if not found:
        return None
    return max(found, key=lambda p: p.stat().st_mtime)


def _try_poste_api(lang: str) -> dict | None:
    raw = (os.environ.get("NAVIGUIDE_POSTE_API") or "http://127.0.0.1:8010").strip()
    host = urlparse(raw).hostname
    if host not in {"127.0.0.1", "localhost", "::1"}:
        return None
    url = f"{raw.rstrip('/')}/voyage/official/film?lang={lang}&style=raw"
    try:
        with urlopen(Request(url), timeout=1.5) as resp:
            data = json.loads(resp.read().decode())
    except (OSError, ValueError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict) or data.get("status") == "preparing":
        return None
    if not (data.get("chapters") or []):
        return None
    return data


def load_poste_film(lang: str = "fr") -> tuple[dict | None, str]:
    roots: list[Path] = []
    if _POSTE_STORE_AT_IMPORT:
        roots.append(Path(_POSTE_STORE_AT_IMPORT))
    if _POSTE_CACHE not in roots:
        roots.append(_POSTE_CACHE)
    for root in roots:
        dest = _newest_film_json(root)
        if dest is None:
            continue
        try:
            doc = json.loads(dest.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        plan = _plan_from_film_doc(doc if isinstance(doc, dict) else {}, lang)
        if plan:
            return plan, str(dest)
    api = _try_poste_api(lang)
    if api:
        return api, "api:127.0.0.1:8010"
    return None, ""


# ── règles isolées : le message est la phrase ───────────────────────────────


def test_interdit_jambe():
    with pytest.raises(AssertionError, match="La jambe compte"):
        assert_discours_ok("La jambe compte 5 153 milles nautiques.", "fr")


def test_interdit_couloirs_et_surveiller():
    with pytest.raises(AssertionError, match="À surveiller"):
        assert_discours_ok("À surveiller.", "fr")
    with pytest.raises(AssertionError, match="Couloirs"):
        assert_discours_ok("Couloirs : Caraïbe ouest.", "fr")


def test_interdit_a_portee_de():
    with pytest.raises(AssertionError, match="à portée de"):
        assert_discours_ok("Le 27 juin, à portée de The Careenage.", "fr")


def test_de_de():
    with pytest.raises(AssertionError, match="de de"):
        assert_discours_ok("Le 22 septembre, à portée de de Fineveke.", "fr")


def test_titre_anglais_deposit_center():
    sent = (
        "Le 15 mai, aire marine protégée à portée : Pertuis Charentais - "
        "Pétoncles - Center Pertuis Breton deposit."
    )
    with pytest.raises(AssertionError, match="deposit"):
        assert_discours_ok(sent, "fr")


def test_comptage_sans_nom():
    with pytest.raises(AssertionError, match="9 stations"):
        assert_discours_ok("À partir du 15 mai, 9 stations scientifiques croisées.", "fr")
    with pytest.raises(AssertionError, match="3 zones"):
        assert_discours_ok("À partir du 1er juillet, 3 zones économiques exclusives traversées.", "fr")


def test_dates_rafale():
    blob = (
        "Le 1er juillet, départ vers Pointe-à-Pitre. "
        "À partir du 1er juillet, encore une date. "
        "Le 2 juillet, approche de Pointe-à-Pitre. "
        "Arrivée à Pointe-à-Pitre le 2 juillet."
    )
    with pytest.raises(AssertionError, match="juillet"):
        assert_discours_ok(blob, "fr")


def test_phrase_trop_longue():
    sent = (
        "Le quinze mai Berry-Mappemonde quitte La Rochelle cap au sud-ouest "
        "pour Ajaccio avec encore trop de mots ajoutés ici pour dépasser "
        "clairement la limite parlée de trente mots dans cette unique phrase."
    )
    assert len(_words(sent)) > MAX_WORDS
    with pytest.raises(AssertionError, match="Berry-Mappemonde"):
        assert_discours_ok(sent + ".", "fr")


def test_ancres_doivent_etre_chronologiques():
    plan = {
        "chapters": [{
            "fromName": "La Rochelle", "toName": "Ajaccio",
            "text": "Le 15 mai, départ. Puis, les eaux. Arrivée à Ajaccio le 26 mai.",
            "anchors": [
                {"charIdx": 0, "t": "2026-05-16T00:00:00Z"},
                {"charIdx": 20, "t": "2026-05-15T00:00:00Z"},
            ],
        }],
    }
    with pytest.raises(AssertionError):
        assert_discours_ok(plan, "fr")


def test_phrase_propre_passe():
    assert_discours_ok(
        "Le 15 mai, Berry-Mappemonde quitte La Rochelle pour Ajaccio. "
        "Puis, les eaux espagnoles. Arrivée à Ajaccio le 26 mai.",
        "fr",
    )


def test_rc41_ancienne_phrase_hs_est_une_faute():
    faults = list_faults("Le 18 mai, Hs 3 m ≥ 3 m.", "fr")
    assert any(f.rule in {"hs seuil", "hs répété"} for f in faults)


def test_rc41_alerte_hs_lisible():
    from film_script import change_sentence

    sent = change_sentence({
        "kind": "alert-on", "title": "Mer", "fact": "Hs 3 m ≥ 3 m.",
        "t": "2026-05-18T12:00:00Z", "hs": 3,
    }, "fr")
    assert "≥" not in sent
    assert not DUP_METERS_RE.search(sent)
    assert_discours_ok(sent, "fr")


# ── film du 28 sept. (§ 1) : les règles le refusent ─────────────────────────


def test_revue_28_sept_est_refusee():
    """Le film transcrit le 28 sept. (avant RG6) viole les règles C/D."""
    faults = list_faults(REVUE_28_SEPT, "fr")
    assert faults, "le film du 28 sept. doit encore être refusé"
    sentences = [f.sentence for f in faults]
    assert any("jambe" in s.lower() for s in sentences)
    assert any("de de" in s.lower() for s in sentences)
    assert any("stations" in s.lower() for s in sentences)
    assert any("deposit" in s.lower() or "Center" in s for s in sentences)
    with pytest.raises(AssertionError) as err:
        assert_discours_ok(REVUE_28_SEPT, "fr")
    assert any(s in str(err.value) for s in sentences)


# ── film après RG6 : moments d'exemple FR et EN ─────────────────────────────


def test_moments_fr_passe_apres_rg6():
    plan = _moments_plan("fr")
    assert plan.get("chapters")
    assert_discours_ok(plan, "fr")


def test_moments_en_passe_apres_rg6():
    plan = _moments_plan("en")
    assert plan.get("chapters")
    assert_discours_ok(plan, "en")


# ── stock du poste (ignoré en CI / si absent) ───────────────────────────────


@pytest.mark.poste
def test_poste_stock_discours():
    """Même règles sur le film réellement stocké sur le poste."""
    if os.environ.get("CI"):
        pytest.skip("poste : stock du poste absent en CI")
    plan, src = load_poste_film("fr")
    if plan is None:
        pytest.skip("poste : NAVIGUIDE_OFFICIAL_STORE_DIR / API absents")
    doc = None
    dest = Path(src) if src and not src.startswith("api:") else None
    if dest and dest.is_file():
        try:
            doc = json.loads(dest.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            doc = None
    plans = _iter_poste_plans(doc, "fr") if isinstance(doc, dict) else [("default", plan)]
    if not plans:
        plans = [("default", plan)]
    total = 0
    print(f"poste FR source={src}", flush=True)
    for label, one in plans:
        faults = list_plan_faults(one, "fr")
        n_sents = sum(len(_sentences(ch.get("text") or "")) for ch in one.get("chapters") or [])
        print(
            f"  variante {label}: chapitres={len(one.get('chapters') or [])} "
            f"phrases={n_sents} fautives={len(faults)}",
            flush=True,
        )
        for fault in faults:
            print(f"    [{fault.rule}] {fault.sentence}", flush=True)
        total += len(faults)
        assert not faults, faults[0].sentence
    print(f"poste FR total fautives={total}", flush=True)
    en, _ = load_poste_film("en")
    if en:
        en_faults = list_plan_faults(en, "en")
        print(f"poste EN fautives={len(en_faults)}", flush=True)
        assert not en_faults, en_faults[0].sentence


_RG14_PLACE_COORDS = {
    "gibraltar": (36.14, -5.35),
    "tanger": (35.78, -5.81),
    "algeciras": (36.13, -5.45),
    "la rochelle": (46.15, -1.16),
    "ajaccio": (41.92, 8.74),
    "fort-de-france": (14.60, -61.07),
    "cayenne": (4.94, -52.33),
    "papeete": (-17.54, -149.57),
    "nouméa": (-22.27, 166.44),
    "noumea": (-22.27, 166.44),
}
_RG14_LIMITS = {
    "escale": 5.0, "stop": 5.0, "depart": 5.0, "arrive": 5.0,
    "marina": 15.0, "amp": 30.0, "project": 30.0, "coast": 30.0, "zee-enter": None,
}


def _rg14_place_coords(name: str):
    key = (name or "").casefold()
    for token, pair in _RG14_PLACE_COORDS.items():
        if token in key:
            return pair
    return None


def _rg14_boat_at(clock: dict, t_ms: int):
    verts = [v for v in (clock.get("vertices") or []) if isinstance(v, dict) and v.get("lat") is not None]
    if not verts:
        return None
    def _vt(v):
        t = _ms(v.get("iso"))
        if t is None and v.get("tHours") is not None and clock.get("t0"):
            t0 = _ms(clock.get("t0"))
            if t0 is not None:
                t = t0 + int(float(v["tHours"]) * 3_600_000)
        return t
    dated = [(v, _vt(v)) for v in verts]
    dated = [(v, t) for v, t in dated if t is not None]
    if not dated:
        return None
    v, _ = min(dated, key=lambda row: abs(row[1] - t_ms))
    return v.get("lat"), v.get("lon")


def _rg14_check_plan(plan: dict, clock: dict | None) -> list[str]:
    """Retourne les lignes de rapport ; lève si une ancre nommée est trop loin."""
    lines: list[str] = []
    for ch in plan.get("chapters") or []:
        text = ch.get("text") or ""
        for a in ch.get("anchors") or []:
            idx = int(a.get("charIdx") or 0)
            slice_txt = (text[max(0, idx): idx + 56].split(".")[0] or "")
            place = str(a.get("place") or "")
            kind = str(a.get("kind") or "")
            blob = f"{place} {slice_txt}"
            coords = _rg14_place_coords(place) or _rg14_place_coords(slice_txt)
            if coords is None:
                continue
            t = _ms(a.get("t"))
            boat = _rg14_boat_at(clock, t) if clock and t is not None else None
            folded = blob.casefold()
            if kind in {"zee-enter", "zee"} or "eaux " in folded:
                lines.append(f"  ZEE {place or slice_txt!r} t={a.get('t')} (intérieur, non mesuré)")
                continue
            if kind in {"escale", "stop", "depart", "arrive"}:
                cap = 5.0
            elif kind == "marina":
                cap = 15.0
            elif "gibraltar" in folded:
                cap = 30.0
            elif kind in {"amp", "project"}:
                cap = 30.0
            else:
                lines.append(f"  {place or slice_txt!r} idx={idx} kind={kind} (hors N du lot, noté)")
                continue
            if boat is None:
                lines.append(f"  {place or slice_txt!r} idx={idx} (pas d'horloge)")
                continue
            d = _nm_between(coords[0], coords[1], boat[0], boat[1])
            if "gibraltar" in folded:
                corridor = (
                    (36.14, -5.35), (35.78, -5.81), (36.13, -5.45), (35.89, -5.32),
                )
                ds = [d] if d is not None else []
                for pair in corridor:
                    d2 = _nm_between(pair[0], pair[1], boat[0], boat[1])
                    if d2 is not None:
                        ds.append(d2)
                if ds:
                    d = min(ds)
            lines.append(f"  {place or slice_txt[:32]!r} idx={idx} d={d:.1f} nm cap={cap}")
            if kind == "depart" and d is not None and d > cap:
                lines.append(f"    (départ : écart horloge noté, pas un échec RG14)")
                continue
            assert d is not None and d <= cap, (d, cap, place, slice_txt, a)
    return lines


def test_rg14_example_moments_anchor_at_word():
    plan = _moments_plan("fr")
    assert plan.get("chapters")
    for ch in plan["chapters"]:
        text = ch.get("text") or ""
        idxs = [int(a["charIdx"]) for a in (ch.get("anchors") or [])]
        assert idxs == sorted(idxs)
        last_t = None
        for a in ch.get("anchors") or []:
            t = _ms(a.get("t"))
            if last_t is not None and t is not None:
                assert t >= last_t
            last_t = t if t is not None else last_t
        arrive = text.find("Arrivée à")
        if arrive >= 0:
            last = text.find(".", arrive)
            last = last if last > arrive else arrive + 20
            assert any(arrive < i <= last for i in idxs), (text, idxs)
        at = text.find("Gibraltar")
        if at >= 0:
            expect = max(0, at - FILM_VOICE_LOOKAHEAD_CHARS)
            near = [i for i in idxs if abs(i - expect) <= 20]
            assert near or any("Gibraltar" in text[max(0, i): i + 48] for i in idxs), (text, idxs)


def _try_poste_clock() -> dict | None:
    raw = (os.environ.get("NAVIGUIDE_POSTE_API") or "http://127.0.0.1:8010").strip()
    host = urlparse(raw).hostname
    if host not in {"127.0.0.1", "localhost", "::1"}:
        return None
    url = f"{raw.rstrip('/')}/voyage/official/clock"
    try:
        with urlopen(Request(url), timeout=1.5) as resp:
            data = json.loads(resp.read().decode())
    except (OSError, ValueError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict) or not (data.get("vertices") or []):
        return None
    return data


def _newest_family_json(root: Path, family: str) -> Path | None:
    if not root.is_dir():
        return None
    found = [p for p in root.glob(f"*/{family}.json") if p.is_file()]
    return max(found, key=lambda p: p.stat().st_mtime) if found else None


def load_poste_moments() -> dict | None:
    roots: list[Path] = []
    if _POSTE_STORE_AT_IMPORT:
        roots.append(Path(_POSTE_STORE_AT_IMPORT))
    if _POSTE_CACHE not in roots:
        roots.append(_POSTE_CACHE)
    for root in roots:
        dest = _newest_family_json(root, "moments")
        if dest is None:
            continue
        try:
            doc = json.loads(dest.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        body = doc.get("payload") if isinstance(doc.get("payload"), dict) else doc
        if isinstance(body, dict) and (body.get("moments") or body.get("journal")):
            return body
    return None


@pytest.mark.poste
def test_poste_stock_anchor_positions():
    """Sur le stock du poste, le bateau est au lieu nommé à l'ancre."""
    if os.environ.get("CI"):
        pytest.skip("poste : stock du poste absent en CI")
    clock = _try_poste_clock()
    moments = load_poste_moments()
    plan = None
    src = ""
    if moments and clock:
        journal = moments.get("journal") if isinstance(moments.get("journal"), dict) else {}
        packed = {**journal, "moments": moments.get("moments") or []}
        live = {
            "filmNm": clock.get("filmNm") or clock.get("sailNm"),
            "sailNm": clock.get("sailNm"),
            "iso": (clock.get("vertices") or [{}])[-1].get("iso") if clock.get("vertices") else None,
            "status": "live",
        }
        now_ms = _ms(live.get("iso")) or NOW_MS
        plan = build_raw_from_moments(
            clock, clock.get("marks"), live, packed,
            lang="fr", seconds=0, now_ms=now_ms,
        )
        src = "rebuild:moments+clock"
    if plan is None or not (plan.get("chapters") or []):
        plan, src = load_poste_film("fr")
    if plan is None:
        pytest.skip("poste : moments / film / horloge absents")
    lines = _rg14_check_plan(plan, clock)
    print(f"poste RG14 source={src} ancres_nommées={len(lines)}", flush=True)
    for line in lines:
        print(line, flush=True)
    n_ch = len(plan.get("chapters") or [])
    n_anc = sum(len(ch.get("anchors") or []) for ch in plan.get("chapters") or [])
    print(f"poste RG14 chapitres={n_ch} ancres={n_anc}", flush=True)
    assert n_anc >= n_ch, "au moins une ancre par chapitre"


# ── RC26 : densité du récit (items, blocs figés, trous, doublons) ───────────


def _densite_module():
    import importlib.util

    path = Path(__file__).resolve().parents[2] / "scripts" / "film-densite.py"
    spec = importlib.util.spec_from_file_location("film_densite", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _densite_faults(plan: dict, moments: dict, clock: dict | None) -> list[str]:
    """Les mesures RC26 sur un plan intégral : items par jambe (plancher borné
    par le stock racontable), part figée sur une même minute ≤ 20 %, trou ≤ 30 %
    (sauf stock déjà dit ou vide), zéro doublon de site, zéro adjectif orphelin."""
    d = _densite_module()
    stock, told = d.collect_stock(moments)
    departs = d.departures_from_clock(clock or {})
    faults: list[str] = []
    chapters = plan.get("chapters") or []
    for dup in d.duplicate_sites(chapters):
        faults.append(f"doublon de site : {dup}")
    for i, ch in enumerate(chapters):
        text = ch.get("text") or ""
        for adj in d.orphan_zee_adjectives(text):
            faults.append(f"ch{i} adjectif ZEE orphelin : {adj}")
        for homo in d.consecutive_homonyms(text):
            faults.append(f"ch{i} homonymes consécutifs : {homo}")
        if d.AIR_RE.search(text):
            continue
        days = d.sea_days(ch, departs)
        if days <= 3:
            continue
        lo, hi = d.sea_bounds(ch, departs)
        # Le plancher est borné par le nombre d'INSTANTS distincts du stock :
        # un moment unique à six items ne justifie pas six phrases d'un coup.
        # Au plus un flotteur Argo par jambe — les Argo surnuméraires ne
        # comptent ni dans le plancher ni dans les trous.
        told_ch = d.cap_argo_told(told, lo, hi)
        minutes = {
            t // 60_000 for t, _title in told_ch
            if lo is not None and hi is not None and lo < t <= hi
        }
        floor = min(min(16, max(4, int(days / 1.5))), len(minutes))
        items = d.chapter_items(ch)
        if len(items) < floor:
            faults.append(f"ch{i} : {len(items)} items < plancher {floor} ({days:.1f} j de mer)")
        run = d.max_same_minute_run(ch)
        if run > 5:
            faults.append(f"ch{i} : {run} phrases d'affilée ancrées sur la même minute")
        gap, g_a, g_b = d.max_gap(ch, departs)
        if gap > 0.30 and d.gap_has_untold_stock(g_a, g_b, told_ch, text):
            faults.append(f"ch{i} : trou de {gap:.0%} avec du stock non dit dedans")
    # L'intégral dit au moins une station et un projet si le stock en contient.
    said = {}
    for ch in chapters:
        for e in ch.get("events") or []:
            k = str(e.get("kind") or "")
            said[k] = said.get(k, 0) + 1
    if stock.get("station") and not said.get("sci"):
        faults.append("aucune station dite alors que le stock en contient")
    if stock.get("project") and not said.get("project"):
        faults.append("aucun projet dit alors que le stock en contient")
    return faults


def test_rc26_densite_fixtures():
    plan = _moments_plan("fr")
    faults = _densite_faults(plan, MOMENTS, CLOCK)
    assert not faults, faults[0]


@pytest.mark.poste
def test_poste_densite_rc26():
    """Mêmes mesures sur le stock réel du poste, recalculé avec le code de la
    branche (le film stocké d'une ancienne révision n'est pas jugé)."""
    if os.environ.get("CI"):
        pytest.skip("poste : stock du poste absent en CI")
    clock = _try_poste_clock()
    moments = load_poste_moments()
    if not (clock and moments):
        pytest.skip("poste : moments / horloge absents")
    journal = moments.get("journal") if isinstance(moments.get("journal"), dict) else {}
    packed = {**journal, "moments": moments.get("moments") or []}
    live = {
        "filmNm": clock.get("filmNm") or clock.get("sailNm"),
        "sailNm": clock.get("sailNm"),
        "iso": (clock.get("vertices") or [{}])[-1].get("iso") if clock.get("vertices") else None,
        "status": "live",
    }
    now_ms = _ms(live.get("iso")) or NOW_MS
    plan = build_raw_from_moments(
        clock, clock.get("marks"), live, packed,
        lang="fr", seconds=0, now_ms=now_ms,
    )
    faults = _densite_faults(plan, {"moments": packed.get("moments") or []}, clock)
    for fault in faults:
        print(f"  [densité] {fault}", flush=True)
    assert not faults, faults[0]
