"""Preview and PNG rendering for a Pattern."""

from __future__ import annotations

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from stitch_engine import Pattern

_FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
]


def _font(size: int):
    for p in _FONT_CANDIDATES:
        try:
            return ImageFont.truetype(p, size)
        except OSError:
            continue
    return ImageFont.load_default()


def flat_color(pattern: Pattern, scale: int = 8) -> Image.Image:
    """Reduced-color blocks, no grid."""
    img = Image.fromarray(pattern.rgb_array(), mode="RGB")
    return img.resize(
        (pattern.stitch_w * scale, pattern.stitch_h * scale),
        Image.Resampling.NEAREST,
    )


def stitch_simulation(pattern: Pattern, scale: int = 10) -> Image.Image:
    """
    Draw each cell as a little X so the preview reads as fabric rather than
    as a pixelated photo. This is the preview that sets expectations honestly.
    """
    w, h = pattern.stitch_w * scale, pattern.stitch_h * scale
    img = Image.new("RGB", (w, h), (247, 245, 240))
    d = ImageDraw.Draw(img)
    rgb = pattern.rgb_array()
    lw = max(1, scale // 4)
    for y in range(pattern.stitch_h):
        for x in range(pattern.stitch_w):
            c = tuple(int(v) for v in rgb[y, x])
            x0, y0 = x * scale, y * scale
            x1, y1 = x0 + scale - 1, y0 + scale - 1
            d.line([x0, y0, x1, y1], fill=c, width=lw)
            d.line([x0, y1, x1, y0], fill=c, width=lw)
    return img


def _grid_lines(d: ImageDraw.ImageDraw, w: int, h: int, sw: int, sh: int,
                scale: int, offset_x: int = 0, offset_y: int = 0) -> None:
    for x in range(sw + 1):
        heavy = x % 10 == 0
        px = offset_x + x * scale
        d.line([px, offset_y, px, offset_y + sh * scale],
               fill=(60, 60, 60) if heavy else (190, 190, 190),
               width=2 if heavy else 1)
    for y in range(sh + 1):
        heavy = y % 10 == 0
        py = offset_y + y * scale
        d.line([offset_x, py, offset_x + sw * scale, py],
               fill=(60, 60, 60) if heavy else (190, 190, 190),
               width=2 if heavy else 1)


def symbol_chart(pattern: Pattern, scale: int = 22,
                 over_color: bool = False, large_print: bool = False) -> Image.Image:
    """Symbols-only chart, or symbols over color blocks."""
    if large_print:
        scale = int(scale * 1.6)
    sw, sh = pattern.stitch_w, pattern.stitch_h
    img = Image.new("RGB", (sw * scale + 1, sh * scale + 1), "white")
    d = ImageDraw.Draw(img)
    rgb = pattern.rgb_array()
    font = _font(int(scale * 0.68))

    for y in range(sh):
        for x in range(sw):
            idx = int(pattern.grid[y, x])
            x0, y0 = x * scale, y * scale
            if over_color:
                d.rectangle([x0, y0, x0 + scale, y0 + scale],
                            fill=tuple(int(v) for v in rgb[y, x]))
            sym = pattern.colors[idx].symbol
            lum = sum(pattern.colors[idx].floss.rgb) / 3
            ink = (255, 255, 255) if (over_color and lum < 110) else (0, 0, 0)
            d.text((x0 + scale / 2, y0 + scale / 2), sym,
                   fill=ink, font=font, anchor="mm")

    _grid_lines(d, img.width, img.height, sw, sh, scale)
    return img


def side_by_side(original: Image.Image, pattern: Pattern) -> Image.Image:
    """Live before/after comparison at matched height."""
    right = stitch_simulation(pattern, scale=8)
    th = 520
    lo = original.copy()
    lo.thumbnail((10000, th), Image.Resampling.LANCZOS)
    rw = int(right.width * th / right.height)
    right = right.resize((rw, th), Image.Resampling.NEAREST)
    gap = 16
    out = Image.new("RGB", (lo.width + gap + right.width, th), "white")
    out.paste(lo, (0, (th - lo.height) // 2))
    out.paste(right, (lo.width + gap, 0))
    return out


def legend_swatches(pattern: Pattern) -> list[dict]:
    """Legend rows ready for a dataframe."""
    est = pattern.skeins_estimate()
    return [
        {
            "Symbol": c.symbol,
            "Number": c.floss.number,
            "Name": c.floss.name,
            "Hex": c.floss.hex,
            "Stitches": c.count,
            "% of pattern": round(c.percent, 2),
            "Skeins (est.)": round(est[c.floss.number], 2),
        }
        for c in pattern.colors
    ]
