"""The share image: no grid line or route crosses the title block (subtitle at y 108-140)."""
from __future__ import annotations

from pathlib import Path

from PIL import Image

_OG = Path(__file__).resolve().parents[2] / "frontend" / "public" / "og-image.png"


def _brightness(pixel: tuple[int, int, int]) -> int:
    return sum(pixel[:3])


def test_nothing_bright_crosses_the_subtitle_band():
    img = Image.open(_OG).convert("RGB")
    assert img.size == (1200, 630)
    background = _brightness(img.getpixel((1180, 125)))
    # Right of the subtitle text, left of the "Voyage map" badge: only the background gradient.
    for y in range(100, 160):
        for x in range(440, 880, 4):
            assert _brightness(img.getpixel((x, y))) <= background + 30, (x, y)


def test_the_grid_is_faint():
    img = Image.open(_OG).convert("RGB")
    # On a grid line (y = 240), at a point the route does not cross.
    line = _brightness(img.getpixel((1000, 240)))
    beside = _brightness(img.getpixel((1000, 243)))
    assert 0 < line - beside < 120
