#!/usr/bin/env python3
"""Build public/og-image.png (1200×630) from BI Escales voyage visuals."""
from __future__ import annotations

import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "frontend" / "public" / "og-image.png"
ROUTE = ROOT / "frontend" / "public" / "route.geojson"
BUNDLED_FONT = ROOT / "backend" / "app" / "escales" / "assets" / "DejaVuSans.ttf"

W, H = 1200, 630
# The title and subtitle end above this line: no grid line or route point crosses them.
GRID_TOP = 170
GRID_STEP = 70
GRID_ALPHA = 28
NAVY = (0, 61, 122)
SEA = (0, 40, 88)
ACCENT = (0, 119, 255)
WHITE = (255, 255, 255)
MUTED = (160, 190, 220)
ROUTE_COLOR = (80, 180, 255)


def _load_route_points() -> list[tuple[float, float]]:
    data = json.loads(ROUTE.read_text(encoding="utf-8"))
    coords: list[tuple[float, float]] = []
    for feature in data.get("features", []):
        geom = feature.get("geometry") or {}
        if geom.get("type") == "LineString":
            for lon, lat in geom.get("coordinates", []):
                coords.append((float(lon), float(lat)))
    if not coords:
        return [(-5, 48), (10, 42), (25, 36), (50, 15), (100, 5)]
    step = max(1, len(coords) // 120)
    return coords[::step]


def _project(points: list[tuple[float, float]]) -> list[tuple[int, int]]:
    lons = [p[0] for p in points]
    lats = [p[1] for p in points]
    min_lon, max_lon = min(lons), max(lons)
    min_lat, max_lat = min(lats), max(lats)
    # The route stays below the title block and above the footer text.
    pad_x, pad_y = 80, GRID_TOP
    box_w, box_h = W - pad_x * 2, H - pad_y - 90

    def to_xy(lon: float, lat: float) -> tuple[int, int]:
        x = pad_x + (lon - min_lon) / (max_lon - min_lon or 1) * box_w
        y = pad_y + (1 - (lat - min_lat) / (max_lat - min_lat or 1)) * box_h
        return int(x), int(y)

    return [to_xy(lon, lat) for lon, lat in points]


def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    ]
    for path in candidates:
        if Path(path).is_file():
            return ImageFont.truetype(path, size)
    # The regular face the backend ships: the picture can be redrawn on any machine.
    if BUNDLED_FONT.is_file():
        return ImageFont.truetype(str(BUNDLED_FONT), size)
    return ImageFont.load_default()


def _has_bold_face() -> bool:
    return any(
        Path(path).is_file()
        for path in (
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        )
    )


def main() -> None:
    img = Image.new("RGB", (W, H), NAVY)
    draw = ImageDraw.Draw(img)
    for y in range(H):
        t = y / H
        r = int(SEA[0] + (NAVY[0] - SEA[0]) * t)
        g = int(SEA[1] + (NAVY[1] - SEA[1]) * t)
        b = int(SEA[2] + (NAVY[2] - SEA[2]) * t)
        draw.line([(0, y), (W, y)], fill=(r, g, b))

    # Faint latitude grid, below the title block. The image is RGB, so the alpha only
    # counts on an overlay composited onto it.
    grid = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    grid_draw = ImageDraw.Draw(grid)
    for i in range(6):
        y = GRID_TOP + i * GRID_STEP
        grid_draw.line([(60, y), (W - 60, y)], fill=(255, 255, 255, GRID_ALPHA), width=1)
    img = Image.alpha_composite(img.convert("RGBA"), grid).convert("RGB")
    draw = ImageDraw.Draw(img)

    pts = _project(_load_route_points())
    if len(pts) > 1:
        draw.line(pts, fill=ROUTE_COLOR, width=4, joint="curve")
    for i, (x, y) in enumerate(pts[:: max(1, len(pts) // 8)]):
        r = 5 if i else 7
        fill = ACCENT if i else WHITE
        draw.ellipse((x - r, y - r, x + r, y + r), fill=fill, outline=WHITE, width=1)

    # sailboat near last point
    if pts:
        bx, by = pts[min(len(pts) - 1, len(pts) * 3 // 4)]
        hull = [(bx - 28, by + 10), (bx, by - 34), (bx + 28, by + 10)]
        draw.polygon(hull, fill=WHITE)
        draw.polygon([(bx - 18, by + 8), (bx, by - 18), (bx + 18, by + 8)], fill=ACCENT)
        draw.rectangle((bx - 2, by - 32, bx + 2, by + 12), fill=WHITE)

    title_font = _font(52, bold=True)
    sub_font = _font(28, bold=False)
    small_font = _font(22, bold=False)

    # Without a bold face on this machine, a one-pixel stroke thickens the regular one.
    draw.text(
        (72, 48),
        "BI Escales",
        font=title_font,
        fill=WHITE,
        stroke_width=0 if _has_bold_face() else 1,
        stroke_fill=WHITE,
    )
    draw.text((72, 108), "Pay only when we arrive", font=sub_font, fill=MUTED)
    draw.text((72, H - 72), "Berry-Mappemonde", font=sub_font, fill=WHITE)
    draw.text(
        (72, H - 40),
        "Expedition · departure 12 November 2026",
        font=small_font,
        fill=MUTED,
    )

    badge_x, badge_y = W - 290, 48
    draw.rounded_rectangle((badge_x, badge_y, W - 48, badge_y + 44), radius=8, fill=ACCENT)
    draw.text((badge_x + 16, badge_y + 9), "Voyage map", font=small_font, fill=WHITE)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    img.save(OUT, format="PNG", optimize=True)
    assert Image.open(OUT).size == (W, H), OUT


if __name__ == "__main__":
    main()
