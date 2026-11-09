"""Mile sponsorship certificates (PNG/PDF). Issued lazily after a successful mile pledge."""
from __future__ import annotations

import asyncio
import copy
import datetime as dt
import hashlib
import hmac
import inspect
import io
import json
import logging
import math
import os
import secrets
import threading
import uuid
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Optional

from app.escales.app_i18n import normalize_app_lang
from app.escales.ledger import get_ledger, now_iso
from app.escales.naviguide_bridge import _haversine_nm
from app.escales.pledges import PledgeNotFound, require_pledge
from app.escales_names import display_name as escale_display_name

log = logging.getLogger("escales.certificates")

CERTIFICATES_COLLECTION = "escales_certificates"
_SUCCESS_STATUSES = frozenset({"authorized", "vaulted", "captured"})
_FONT_PATH = Path(__file__).with_name("assets") / "DejaVuSans.ttf"
_ROUTE_GEOJSON = Path(__file__).resolve().parents[3] / "frontend" / "public" / "route.geojson"
_R_NM = 3440.065
_DEPARTURE_LABEL = "12 Nov 2026"

_CAPTAIN_FALLBACK = {
    "fr": (
        "Le Capitaine atteste que ce mil marin soutient l'expédition BI Escales. "
        "Merci pour votre confiance — nous naviguons ensemble, un mile après l'autre."
    ),
    "en": (
        "The Captain confirms this nautical mile supports the BI Escales expedition. "
        "Thank you for sailing with us — one mile at a time."
    ),
}

_LABELS = {
    "fr": {
        "title": "Certificat de mile parrainé",
        "name": "Parrain / Marraine",
        "mile": "Mile n°",
        "route": "Segment officiel",
        "issued": "Date d'émission",
        "departure": "Départ",
        "captain": "Mot du Capitaine",
        "footer": "BI Escales — Pay Only If We Sail · PayPal sandbox",
    },
    "en": {
        "title": "Sponsored mile certificate",
        "name": "Supporter",
        "mile": "Mile no.",
        "route": "Official segment",
        "issued": "Issue date",
        "departure": "Departure",
        "captain": "Captain's word",
        "footer": "BI Escales — Pay Only If We Sail · PayPal sandbox",
    },
}

_flat_route_cache: Optional[dict[str, Any]] = None
_store: Any = None


def reset_certificate_store() -> None:
    global _store, _flat_route_cache
    _store = None
    _flat_route_cache = None


def _mongo_wanted() -> bool:
    mode = os.environ.get("ESCALES_STORE", "").strip().lower()
    if mode == "memory":
        return False
    if mode == "mongo":
        return True
    return bool((os.environ.get("MONGO_URL") or "").strip())


class MemoryCertificateStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._by_token: dict[str, dict] = {}
        self._by_pledge: dict[str, str] = {}

    async def find_by_token(self, token: str) -> Optional[dict]:
        with self._lock:
            doc = self._by_token.get(token)
            return copy.deepcopy(doc) if doc else None

    async def find_by_pledge(self, pledge_id: str) -> Optional[dict]:
        with self._lock:
            token = self._by_pledge.get(pledge_id)
            if not token:
                return None
            doc = self._by_token.get(token)
            return copy.deepcopy(doc) if doc else None

    async def insert_once(self, doc: dict) -> dict:
        with self._lock:
            pledge_id = str(doc.get("pledge_id") or "")
            existing = self._by_pledge.get(pledge_id)
            if existing:
                return copy.deepcopy(self._by_token[existing])
            stored = copy.deepcopy(doc)
            self._by_token[stored["token"]] = stored
            self._by_pledge[pledge_id] = stored["token"]
            return copy.deepcopy(stored)


class MongoCertificateStore:
    def __init__(self, db: Any) -> None:
        self._col = db[CERTIFICATES_COLLECTION]
        self._ready = False

    async def _ensure(self) -> None:
        if self._ready:
            return
        await self._col.create_index("token", unique=True, name="escales_certificates_token")
        await self._col.create_index("pledge_id", unique=True, name="escales_certificates_pledge")
        self._ready = True

    async def find_by_token(self, token: str) -> Optional[dict]:
        await self._ensure()
        doc = await self._col.find_one({"token": token})
        return copy.deepcopy(doc) if doc else None

    async def find_by_pledge(self, pledge_id: str) -> Optional[dict]:
        await self._ensure()
        doc = await self._col.find_one({"pledge_id": pledge_id})
        return copy.deepcopy(doc) if doc else None

    async def insert_once(self, doc: dict) -> dict:
        await self._ensure()
        pledge_id = str(doc.get("pledge_id") or "")
        existing = await self._col.find_one({"pledge_id": pledge_id})
        if existing:
            return copy.deepcopy(existing)
        stored = copy.deepcopy(doc)
        try:
            await self._col.insert_one(stored)
        except Exception as exc:
            if exc.__class__.__name__ == "DuplicateKeyError":
                again = await self._col.find_one({"pledge_id": pledge_id})
                if again:
                    return copy.deepcopy(again)
            raise
        return stored


def get_certificate_store() -> Any:
    global _store
    if _store is None:
        if _mongo_wanted():
            from app.db import db

            _store = MongoCertificateStore(db)
        else:
            _store = MemoryCertificateStore()
    return _store


def _unwrap_lon(prev_lon: Optional[float], lon: float) -> float:
    if prev_lon is None or not math.isfinite(prev_lon):
        return lon
    x = lon
    while x - prev_lon > 180:
        x -= 360
    while x - prev_lon < -180:
        x += 360
    return x


def _leg_scale(coords: list, declared_nm: Optional[float]) -> float:
    if not declared_nm or declared_nm <= 0:
        return 1.0
    geom = 0.0
    for i in range(1, len(coords)):
        lon1, lat1 = float(coords[i - 1][0]), float(coords[i - 1][1])
        lon2, lat2 = float(coords[i][0]), float(coords[i][1])
        lon2 = _unwrap_lon(lon1, lon2)
        geom += _haversine_nm(lon1, lat1, lon2, lat2)
    return (declared_nm / geom) if geom > 0 else 1.0


def flatten_official_route() -> dict[str, Any]:
    global _flat_route_cache
    if _flat_route_cache is not None:
        return _flat_route_cache
    raw = json.loads(_ROUTE_GEOJSON.read_text(encoding="utf-8"))
    points: list[dict[str, float]] = []
    cum_nm = 0.0

    def add(lon: float, lat: float, scale: float = 1.0) -> None:
        nonlocal cum_nm
        if not math.isfinite(lat) or not math.isfinite(lon):
            return
        if points:
            prev = points[-1]
            lon = _unwrap_lon(prev["lon"], lon)
            if abs(prev["lat"] - lat) < 1e-9 and abs(prev["lon"] - lon) < 1e-6:
                return
            d = _haversine_nm(prev["lon"], prev["lat"], lon, lat) * scale
            cum_nm += d
        points.append({"lon": lon, "lat": lat, "cumNm": cum_nm})

    for feature in raw.get("features") or []:
        if not isinstance(feature, dict):
            continue
        geometry = feature.get("geometry") or {}
        if geometry.get("type") != "LineString":
            continue
        coords = geometry.get("coordinates") or []
        if len(coords) < 2:
            continue
        props = feature.get("properties") or {}
        nm_raw = props.get("nm")
        declared = float(nm_raw) if nm_raw is not None else None
        scale = _leg_scale(coords, declared)
        for pt in coords:
            add(float(pt[0]), float(pt[1]), scale=scale)

    total_nm = points[-1]["cumNm"] if points else 0.0
    _flat_route_cache = {"points": points, "totalNm": total_nm}
    return _flat_route_cache


def interpolate_at_nm(nm: float) -> Optional[dict[str, float]]:
    flat = flatten_official_route()
    pts = flat.get("points") or []
    if not pts:
        return None
    if len(pts) == 1:
        pt = pts[0]
        return {"lon": pt["lon"], "lat": pt["lat"], "cumNm": 0.0}
    target = max(0.0, min(float(flat.get("totalNm") or 0), float(nm)))
    idx = 0
    while idx < len(pts) - 2 and pts[idx + 1]["cumNm"] <= target:
        idx += 1
    a, b = pts[idx], pts[idx + 1]
    span = b["cumNm"] - a["cumNm"]
    t = (target - a["cumNm"]) / span if span > 0 else 1.0
    lat = a["lat"] + t * (b["lat"] - a["lat"])
    lon = a["lon"] + t * (b["lon"] - a["lon"])
    return {"lon": lon, "lat": lat, "cumNm": target}


def mile_quantity_from_pledge(doc: dict) -> int:
    quantity = doc.get("quantity")
    if isinstance(quantity, int) and not isinstance(quantity, bool) and quantity >= 1:
        return quantity
    try:
        amount = Decimal(str(doc.get("amount_eur") or "0"))
    except (InvalidOperation, ValueError):
        return 1
    miles = int(amount.to_integral_value())
    return max(1, miles)


def _pledge_sort_key(doc: dict) -> tuple:
    moment = str(doc.get("authorized_at") or doc.get("vaulted_at") or doc.get("created_at") or "")
    return moment, str(doc.get("_id") or "")


async def allocated_mile_number(pledge_id: str) -> int:
    """First sponsored mile index (1-based) for this pledge along the expedition route."""
    start = 1
    pledges = await get_ledger().list_pledges()
    eligible = [
        row
        for row in pledges
        if str(row.get("kind") or "mile") == "mile" and str(row.get("status") or "") in _SUCCESS_STATUSES
    ]
    for row in sorted(eligible, key=_pledge_sort_key):
        if str(row.get("_id")) == pledge_id:
            return start
        start += mile_quantity_from_pledge(row)
    raise ValueError("pledge is not a successful mile sponsorship")


def segment_for_miles(mile_number: int, quantity: int) -> dict[str, float]:
    start_nm = float(max(0, mile_number - 1))
    end_nm = start_nm + float(max(1, quantity))
    start = interpolate_at_nm(start_nm) or {"lon": 0.0, "lat": 0.0}
    end = interpolate_at_nm(end_nm) or start
    return {
        "segment_start_lat": round(start["lat"], 5),
        "segment_start_lon": round(start["lon"], 5),
        "segment_end_lat": round(end["lat"], 5),
        "segment_end_lon": round(end["lon"], 5),
    }


def _issue_date_iso(moment: Optional[dt.datetime] = None) -> str:
    when = moment or dt.datetime.now(dt.timezone.utc)
    if when.tzinfo is None:
        when = when.replace(tzinfo=dt.timezone.utc)
    return when.astimezone(dt.timezone.utc).date().isoformat()


def _format_coords(lat: float, lon: float) -> str:
    lat_bit = f"{lat:.4f}°N" if lat >= 0 else f"{abs(lat):.4f}°S"
    lon_bit = f"{lon:.4f}°E" if lon >= 0 else f"{abs(lon):.4f}°W"
    return f"{lat_bit}, {lon_bit}"


async def _captain_text(
    *,
    display_name: str,
    mile_number: int,
    milestone_id: str,
    lang: str,
) -> str:
    from app.core import llm

    port = escale_display_name(str(milestone_id or ""))
    prompt = (
        f"Write 1-3 short sentences in {lang.upper()} for a mile sponsorship certificate. "
        f"Supporter name: {display_name}. Mile number: {mile_number}. Port: {port}. "
        "Tone: warm, nautical, no payment amounts, no email, no PayPal."
    )
    if not llm.has_llm() or not await _consume_llm_budget():
        return _CAPTAIN_FALLBACK.get(lang, _CAPTAIN_FALLBACK["en"])
    try:
        result = await asyncio.wait_for(
            llm.ask_text(prompt, max_tokens=160, lang=lang),
            timeout=8.0,
        )
        text = str(getattr(result, "text", "") or "").strip()
        if text:
            return text[:600]
    except Exception as exc:
        log.info("certificate captain text fallback (%s)", type(exc).__name__)
    return _CAPTAIN_FALLBACK.get(lang, _CAPTAIN_FALLBACK["en"])


def payer_proof_expected(pledge: dict) -> Optional[str]:
    """PayPal order id (AUTHORIZE) or setup token id (VAULT) held by the payer after checkout."""
    mode = str(pledge.get("payment_mode") or pledge.get("intent") or "AUTHORIZE").strip().upper()
    if mode == "VAULT":
        proof = str(pledge.get("setup_token_id") or "").strip()
    else:
        proof = str(pledge.get("order_id") or "").strip()
    return proof or None


def payer_proof_matches(pledge: dict, supplied: Optional[str]) -> bool:
    expected = payer_proof_expected(pledge)
    if not expected:
        return False
    provided = str(supplied or "").strip()
    if not provided or len(provided) != len(expected):
        return False
    return hmac.compare_digest(provided, expected)


def _log_token_ref(token: str) -> str:
    digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
    return digest[:6]


async def _consume_llm_budget() -> bool:
    from app.core import llm

    result = llm.consume_llm_call()
    if inspect.isawaitable(result):
        result = await result
    return bool(result)


def _validate_mile_pledge(doc: dict) -> None:
    if str(doc.get("kind") or "mile") != "mile":
        raise ValueError("certificate is only available for mile pledges")
    if str(doc.get("status") or "") not in _SUCCESS_STATUSES:
        raise ValueError("mile pledge is not in a successful state")


async def ensure_certificate(
    pledge_id: str,
    *,
    display_name: Optional[str] = None,
    lang: Optional[str] = None,
) -> dict:
    existing = await get_certificate_store().find_by_pledge(pledge_id)
    if existing:
        return existing
    try:
        pledge = await require_pledge(pledge_id)
    except PledgeNotFound as exc:
        raise exc
    _validate_mile_pledge(pledge)
    resolved_lang = normalize_app_lang(lang)
    label = (display_name or pledge.get("contributor") or "Friend").strip() or "Friend"
    if len(label) > 120:
        label = label[:120]
    quantity = mile_quantity_from_pledge(pledge)
    mile_number = await allocated_mile_number(pledge_id)
    segment = segment_for_miles(mile_number, quantity)
    captain_text = await _captain_text(
        display_name=label,
        mile_number=mile_number,
        milestone_id=str(pledge.get("milestone_id") or ""),
        lang=resolved_lang,
    )
    token = secrets.token_urlsafe(24)
    doc = {
        "_id": uuid.uuid4().hex,
        "token": token,
        "pledge_id": pledge_id,
        "mile_number": mile_number,
        "mile_quantity": quantity,
        **segment,
        "display_name": label,
        "milestone_id": str(pledge.get("milestone_id") or ""),
        "issue_date": _issue_date_iso(),
        "lang": resolved_lang,
        "captain_text": captain_text,
        "created_at": now_iso(),
    }
    stored = await get_certificate_store().insert_once(doc)
    log.info("certificate issued ref=%s", _log_token_ref(token))
    return stored


async def load_certificate(token: str) -> Optional[dict]:
    return await get_certificate_store().find_by_token(token)


def captain_text_for_render(doc: dict, lang: str) -> str:
    stored_lang = str(doc.get("lang") or "en")
    text = str(doc.get("captain_text") or "").strip()
    if lang == stored_lang and text:
        return text
    return _CAPTAIN_FALLBACK.get(lang, _CAPTAIN_FALLBACK["en"])


def _render_lines(doc: dict, lang: str) -> list[str]:
    labels = _LABELS.get(lang, _LABELS["en"])
    qty = int(doc.get("mile_quantity") or 1)
    mile_label = f"{labels['mile']} {doc.get('mile_number')}"
    if qty > 1:
        mile_label += f"–{int(doc['mile_number']) + qty - 1}"
    seg = (
        f"{_format_coords(doc['segment_start_lat'], doc['segment_start_lon'])} → "
        f"{_format_coords(doc['segment_end_lat'], doc['segment_end_lon'])}"
    )
    return [
        labels["title"],
        "",
        f"{labels['name']}: {doc.get('display_name')}",
        mile_label,
        f"{labels['route']}: {seg}",
        f"{labels['issued']}: {doc.get('issue_date')}",
        f"{labels['departure']}: {_DEPARTURE_LABEL}",
        "",
        labels["captain"],
        captain_text_for_render(doc, lang),
        "",
        labels["footer"],
    ]


def render_certificate_png(doc: dict, lang: str) -> bytes:
    from PIL import Image, ImageDraw, ImageFont

    width, height = 1200, 848
    image = Image.new("RGB", (width, height), (247, 251, 255))
    draw = ImageDraw.Draw(image)
    draw.rectangle((40, 40, width - 40, height - 40), outline=(12, 76, 110), width=4)
    font_path = str(_FONT_PATH)
    title_font = ImageFont.truetype(font_path, 42)
    body_font = ImageFont.truetype(font_path, 28)
    small_font = ImageFont.truetype(font_path, 22)
    y = 80
    for line in _render_lines(doc, lang):
        if not line:
            y += 18
            continue
        if line == _LABELS.get(lang, _LABELS["en"])["title"]:
            draw.text((80, y), line, fill=(12, 76, 110), font=title_font)
            y += 58
            continue
        if line in {_LABELS.get(lang, _LABELS["en"])["captain"], _LABELS.get(lang, _LABELS["en"])["footer"]}:
            draw.text((80, y), line, fill=(40, 60, 80), font=small_font)
            y += 34
            continue
        draw.text((80, y), line, fill=(20, 32, 48), font=body_font)
        y += 40
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


def render_certificate_pdf(doc: dict, lang: str) -> bytes:
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.pdfgen import canvas

    if "DejaVuSans" not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont("DejaVuSans", str(_FONT_PATH)))
    buffer = io.BytesIO()
    page_w, page_h = landscape(A4)
    pdf = canvas.Canvas(buffer, pagesize=landscape(A4))
    pdf.setCreator("BI Escales")
    pdf.setTitle("Mile certificate")
    fixed = dt.datetime(2026, 11, 12, 12, 0, 0, tzinfo=dt.timezone.utc)
    pdf.setDateFormatter(None)
    pdf._doc.info.CreationDate = fixed
    pdf._doc.info.ModDate = fixed
    y = page_h - 72
    for line in _render_lines(doc, lang):
        if not line:
            y -= 14
            continue
        if line == _LABELS.get(lang, _LABELS["en"])["title"]:
            pdf.setFont("DejaVuSans", 22)
            pdf.drawString(56, y, line)
            y -= 36
            continue
        if line in {_LABELS.get(lang, _LABELS["en"])["captain"], _LABELS.get(lang, _LABELS["en"])["footer"]}:
            pdf.setFont("DejaVuSans", 11)
            pdf.drawString(56, y, line)
            y -= 20
            continue
        pdf.setFont("DejaVuSans", 14)
        pdf.drawString(56, y, line)
        y -= 24
    pdf.showPage()
    pdf.save()
    return buffer.getvalue()


def public_certificate_links(token: str) -> dict[str, str]:
    return {
        "png": f"/api/escales/certificates/{token}.png",
        "pdf": f"/api/escales/certificates/{token}.pdf",
    }
